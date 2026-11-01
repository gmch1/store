#!/usr/bin/env python3
"""Build/test Ming Store, sign with the existing identity, and export corresponding source locally."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

try:
    from .client_config import ROOT, environment, public_config, signing_config, release_metadata
    from .prepare_client import archive_source, prepare, validate
except ImportError:
    from client_config import ROOT, environment, public_config, signing_config, release_metadata
    from prepare_client import archive_source, prepare, validate


def output(*args) -> bytes:
    return subprocess.check_output([str(value) for value in args])


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--example-config', action='store_true')
    parser.add_argument('--unsigned', action='store_true', help='CI/testing only: do not access signing files')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--upstream-cache', type=Path)
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    env = environment(args.env_file)
    config = public_config(env, example=args.example_config)
    release = release_metadata()
    upstream = json.loads((ROOT / 'client/upstream.json').read_text())
    series = json.loads((ROOT / 'client/patches/series.json').read_text())
    if any(Path(name).name != name or not name.endswith('.patch') for name in series):
        parser.error('Patch series must contain plain .patch file names')
    patches = [ROOT / 'client/patches' / name for name in series]
    recipe_files = [*patches, ROOT / 'client/upstream.json', ROOT / 'client/release.json',
                    ROOT / 'client/patches/series.json', ROOT / 'client/README.md',
                    ROOT / 'scripts/build_client.py', ROOT / 'scripts/prepare_client.py',
                    ROOT / 'scripts/client_config.py']
    recipe_hashes = {path: sha256(path) for path in recipe_files}
    source, expected_diff = prepare(
        upstream, patches, ROOT / '.local/client',
        upstream=str(args.upstream_cache.resolve()) if args.upstream_cache else None,
        version_name=release['version_name'], version_code=release['version_code'], config=config,
        application_id=release['application_id'],
    )
    if args.prepare_only:
        print(source)
        return
    sdk_value = args.sdk or env.get('STORE_CLIENT_ANDROID_HOME') or env.get('ANDROID_HOME')
    if not sdk_value:
        parser.error('Set ANDROID_HOME or pass --sdk')
    sdk = Path(sdk_value).expanduser().resolve()
    tools = sdk / 'build-tools/36.0.0'
    for required in (sdk / 'platforms/android-37.1/android.jar', tools / 'aapt2', tools / 'zipalign', tools / 'apksigner'):
        if not required.is_file():
            parser.error(f'Missing SDK component: {required}')
    signing = None if args.unsigned else signing_config(env)
    if signing:
        certificate = output('keytool', '-exportcert', '-keystore', signing.keystore,
                             '-storepass:file', signing.password_file, '-alias', signing.alias)
        if hashlib.sha256(certificate).hexdigest().upper() != signing.certificate_sha256:
            raise RuntimeError('Keystore certificate does not match STORE_CLIENT_CERTIFICATE_SHA256')
    build_env = dict(env, ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    cache = env.get('STORE_CLIENT_GRADLE_USER_HOME') or env.get('GRADLE_USER_HOME') or str(ROOT / '.local/gradle-user-home')
    build_env['GRADLE_USER_HOME'] = str(Path(cache).expanduser().resolve())
    if build_env.get('JAVA_HOME'):
        build_env['JAVA_HOME'] = str(Path(build_env['JAVA_HOME']).expanduser().resolve())
    subprocess.run([str(source / 'gradlew'), '--no-daemon', '--no-configuration-cache',
                    f'--max-workers={args.jobs}', '-Pkotlin.compiler.execution.strategy=in-process',
                    '-Dorg.gradle.jvmargs=-Xmx3g -XX:ActiveProcessorCount=4',
                    ':app:testDebugUnitTest', ':app:assembleRelease'],
                   cwd=source, env=build_env, check=True)
    validate(source, upstream['commit'], expected_diff)
    if any(sha256(path) != value for path, value in recipe_hashes.items()):
        raise RuntimeError('Build recipe changed during compilation; rebuild with the final recipe')
    dist = ROOT / '.local/client/dist'
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.stage-', dir=dist) as temporary:
        stage = Path(temporary)
        aligned = stage / 'aligned.apk'
        unsigned = source / 'app/build/outputs/apk/release/app-release-unsigned.apk'
        output(tools / 'zipalign', '-f', '-P', '16', '4', unsigned, aligned)
        apk = stage / 'client.apk'
        cert_hash = None
        if signing:
            output(tools / 'apksigner', 'sign', '--ks', signing.keystore, '--ks-key-alias', signing.alias,
                   '--ks-pass', f'file:{signing.password_file}', '--out', apk, aligned)
            verification = output(tools / 'apksigner', 'verify', '--print-certs', apk).decode()
            certificates = set(re.findall(r'certificate SHA-256 digest: ([a-fA-F0-9]{64})', verification))
            if {value.upper() for value in certificates} != {signing.certificate_sha256}:
                raise RuntimeError('Signed APK certificate differs from the pinned signing identity')
            cert_hash = signing.certificate_sha256.lower()
        else:
            aligned.rename(apk)
        output(tools / 'zipalign', '-c', '-P', '16', '4', apk)
        badging = output(tools / 'aapt2', 'dump', 'badging', apk).decode()
        identity = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging)
        expected = (release['application_id'], str(release['version_code']), release['version_name'])
        if identity is None or identity.groups() != expected:
            raise RuntimeError('APK package/version differs from client/release.json')
        apk_hash = sha256(apk)
        archive = stage / f'{apk_hash}.tar.gz'
        archive_source(source, archive, upstream, patches, release['version_name'], release['version_code'])
        name = f"ming-store-{release['version_name']}{'-unsigned' if args.unsigned else ''}.apk"
        record = dict(release, apk=name, apk_sha256=apk_hash, source=archive.name,
                      source_sha256=sha256(archive), certificate_sha256=cert_hash,
                      upstream_commit=upstream['commit'], patch_sha256=[sha256(path) for path in patches])
        (stage / 'release.json').write_text(json.dumps(record, indent=2) + '\n')
        os.replace(archive, dist / archive.name)
        os.replace(apk, dist / name)
        os.replace(stage / 'release.json', dist / 'release.json')
    print(f"APK: {dist / name}\nCorresponding source: {dist / record['source']}")


if __name__ == '__main__':
    main()
