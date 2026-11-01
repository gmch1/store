import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from scripts.client_config import environment, public_config, signing_config, release_metadata
from scripts.prepare_client import prepare, archive_source


def values(**overrides):
    return dict(STORE_CLIENT_REPO_URL='https://store.example.invalid/fdroid/repo',
                STORE_CLIENT_REPO_FINGERPRINT='ab' * 32, **overrides)


def test_env_file_is_literal_and_exports_take_precedence(tmp_path):
    path = tmp_path / '.env.client'
    path.write_text('export STORE_CLIENT_REPO_URL="https://file.example.invalid/repo"\n'
                    "STORE_CLIENT_KEY_ALIAS='$(do-not-run)' # a literal, never a command\n")
    loaded = environment(path, {'STORE_CLIENT_REPO_URL': 'https://env.example.invalid/repo'})
    assert loaded['STORE_CLIENT_REPO_URL'] == 'https://env.example.invalid/repo'
    assert loaded['STORE_CLIENT_KEY_ALIAS'] == '$(do-not-run)'


def test_explicit_missing_env_file_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='does not exist'):
        environment(tmp_path / 'missing.env', {})


def test_server_keys_are_not_accepted_in_client_env_files(tmp_path):
    path = tmp_path / '.env.client'
    path.write_text('STORE_API_KEY=synthetic-private-value\n')
    with pytest.raises(ValueError, match='unsupported client configuration key') as error:
        environment(path, {})
    assert 'synthetic-private-value' not in str(error.value)


@pytest.mark.parametrize('address', [
    'https://user:secret@store.example.invalid/repo', 'https://store.example.invalid/repo?token=secret',
    'http://store.example.invalid/repo', 'https://store.example.invalid/repo\nsecret',
])
def test_invalid_or_credential_bearing_urls_fail_without_echoing_values(address):
    env = values()
    env['STORE_CLIENT_REPO_URL'] = address
    with pytest.raises(ValueError) as error:
        public_config(env)
    assert 'secret' not in str(error.value)


def test_missing_config_fails_and_example_mode_ignores_real_environment():
    with pytest.raises(ValueError, match='Missing STORE_CLIENT_REPO_URL'):
        public_config({})
    config = public_config({'STORE_CLIENT_REPO_URL': 'https://ignored.example.invalid'}, example=True)
    assert config.repo_url == 'https://store.example.invalid/fdroid/repo'
    assert config.repo_fingerprint == '0' * 64


def test_loopback_fixture_urls_and_fingerprint_normalization():
    env = values()
    env['STORE_CLIENT_REPO_URL'] = 'http://127.0.0.1:8766/fdroid/repo/'
    assert public_config(env).repo_url == 'http://127.0.0.1:8766/fdroid/repo'
    assert public_config(env).repo_fingerprint == 'AB' * 32
    env['STORE_CLIENT_REPO_FINGERPRINT'] = 'invalid'
    with pytest.raises(ValueError, match='SHA-256'):
        public_config(env)


def test_generated_source_and_archive_contain_only_public_config(recipe, tmp_path):
    upstream, manifest, patch, destination = recipe
    env = values(STORE_CLIENT_PASSWORD_FILE='/private/synthetic-password', STORE_API_KEY='private-sentinel')
    config = public_config(env)
    source, _ = prepare(manifest, [patch], destination, upstream=str(upstream), config=config)
    generated = source / 'app/src/main/kotlin/com/looker/droidify/StoreConfig.kt'
    assert config.repo_url in generated.read_text()
    record = (source / '.git/store-build.json').read_text()
    assert 'private-sentinel' not in record and 'synthetic-password' not in record
    archive = tmp_path / 'source.tar.gz'
    archive_source(source, archive, manifest, [patch], None, None)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if member.isfile():
                data = tar.extractfile(member).read()
                assert b'private-sentinel' not in data and b'synthetic-password' not in data
        archived = json.load(tar.extractfile('client-source/recipe/public-config.json'))
        assert archived == config.as_dict()
    changed = values()
    changed['STORE_CLIENT_REPO_URL'] = 'https://different.example.invalid/repo'
    other, _ = prepare(manifest, [patch], destination, upstream=str(upstream), config=public_config(changed))
    assert source != other


def test_signing_uses_existing_files_and_never_creates_an_identity(tmp_path):
    env = {'STORE_CLIENT_SIGNING_DIR': str(tmp_path), 'STORE_CLIENT_CERTIFICATE_SHA256': '12' * 32}
    with pytest.raises(ValueError, match='no new signing identity'):
        signing_config(env)
    assert list(tmp_path.iterdir()) == []
    (tmp_path / 'ming-store.p12').write_text('synthetic fixture, not a key')
    (tmp_path / 'password').write_text('synthetic fixture')
    configured = signing_config(env)
    assert configured.keystore == tmp_path / 'ming-store.p12'
    assert configured.password_file == tmp_path / 'password'


def test_private_env_is_ignored_and_example_is_publishable():
    root = Path(__file__).resolve().parents[1]
    for name, ignored in [('.env.client', True), ('.env.client.example', False),
                          ('client/signing/test.p12', True), ('client/settings.local.json', True)]:
        result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', name], cwd=root)
        assert (result.returncode == 0) == ignored


def test_public_checker_rejects_force_added_private_env_without_printing_values(tmp_path, monkeypatch, capsys):
    from scripts import check_public_files

    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.env.client').write_text('STORE_CLIENT_REPO_URL=https://private.example.invalid/PRIVATE_NOT_FOR_LOG\n')
    dns = tmp_path / 'deploy/android/ddns.example.json'
    dns.parent.mkdir(parents=True)
    dns.write_text(json.dumps({'zone_id': '0' * 32, 'zone_name': 'example.invalid'}))
    subprocess.run(['git', 'add', '-f', '.env.client', 'deploy/android/ddns.example.json'], cwd=tmp_path, check=True)
    monkeypatch.setattr(check_public_files, 'ROOT', tmp_path)
    with pytest.raises(SystemExit):
        check_public_files.check()
    out = capsys.readouterr().out
    assert '.env.client: private artifact' in out
    assert 'PRIVATE_NOT_FOR_LOG' not in out


@pytest.mark.parametrize('changes', [{'version_code': 0}, {'version_code': True},
                                    {'application_id': 'invalid'}, {'API_KEY': 'synthetic'}])
def test_release_metadata_rejects_invalid_identity_or_private_fields(tmp_path, changes):
    path = tmp_path / 'release.json'
    data = {'application_id': 'com.example.client', 'version_name': '1.0.1', 'version_code': 2}
    data.update(changes)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='valid package'):
        release_metadata(path)
