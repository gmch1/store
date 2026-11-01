#!/usr/bin/env python3
"""Check tracked source for private artifacts and accidental deployment literals.

This complements credential scanners; it is not a complete secret detector.
Diagnostics include file names and categories, never matched credential values.
"""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'.local', '.venv', '__pycache__', 'metadata'}
PRIVATE_SUFFIXES = {'.apk', '.jks', '.p12', '.pfx', '.keystore', '.key', '.pem',
                    '.log', '.bundle', '.zip', '.pyc', '.db', '.sqlite', '.sqlite3'}
PRIVATE_CONFIGS = {'deploy/android/runtime.json', 'deploy/android/ddns.json',
                   'deploy/android/Caddyfile', 'deploy/android/Caddyfile.tencent',
                   'deploy/android/maintenance-sshd.conf', '.env'}
UPSTREAM_HOSTS = {'github.com', 'codeberg.org', 'f-droid.org',
                  'fastapi.tiangolo.com', 'schemas.android.com', 'api.cloudflare.com',
                  'fsf.org', 'www.gnu.org'}
# Public repository hosts in the pinned Droid-ify v0.7.8 source, retained in patch removals.
UPSTREAM_HOSTS.update({
    'app.futo.org', 'app.simplex.chat', 'apt.izzysoft.de', 'archive.newpipe.net',
    'brave-browser-apk-beta.s3.brave.com', 'brave-browser-apk-nightly.s3.brave.com',
    'brave-browser-apk-release.s3.brave.com', 'breezy-weather.github.io', 'briarproject.org',
    'calyxos.gitlab.io', 'cdn.kde.org', 'f-droid.monerujo.io', 'f5a.torus.icu',
    'fdroid.cakelabs.com', 'fdroid.fedilab.app', 'fdroid.getsession.org', 'fdroid.i2pd.xyz',
    'fdroid.ironfoxoss.org', 'fdroid.mm20.de', 'fdroid.twinhelix.com', 'fdroid.typeblog.net',
    'gh.artemchep.com', 'guardianproject-wind.s3.amazonaws.com', 'guardianproject.info',
    'microg.org', 'mobileapp.bitwarden.com', 'molly.im', 'nanolx.org', 'raw.githubusercontent.com',
    'releases.threema.ch', 'repo.netsyms.com', 's2.spiritcroc.de', 'static.cryptomator.org',
    'store.nethunter.com', 'thecapslock.gitlab.io', 'www.collaboraoffice.com',
    'www.cromite.org', 'zimbelstern.eu',
})
DOC_NETWORKS = [ipaddress.ip_network(x) for x in
                ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24')]
NETWORK_BASES = {'10.0.0.0', '172.16.0.0', '192.168.0.0'}
SECRETS = [
    r'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----\s*\n[A-Za-z0-9+/=]{20,}',
    r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})',
    r'\bsk-[A-Za-z0-9_-]{32,}',
]


def check():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    issues = set()
    for name in filter(None, names):
        path = ROOT / name
        private_override = (path.name.startswith('.env') and not path.name.endswith('.example') or
                            path.name.endswith(('.local.env', '.local.json', '.local.patch')))
        if (PRIVATE_PARTS.intersection(Path(name).parts) or path.suffix in PRIVATE_SUFFIXES or
                name in PRIVATE_CONFIGS or private_override):
            issues.add((name, 'private artifact or runtime configuration'))
        if path.is_symlink():
            issues.add((name, 'symlink requires explicit public-source review'))
            continue
        if not path.exists():
            issues.add((name, 'tracked file missing'))
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            issues.add((name, 'unexpected binary'))
            continue
        if any(re.search(pattern, text) for pattern in SECRETS):
            issues.add((name, 'credential-like material'))
        for value in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', text):
            try:
                ip = ipaddress.ip_address(value)
            except ValueError:
                continue
            if not (ip.is_loopback or ip.is_unspecified or value in NETWORK_BASES or
                    any(ip in network for network in DOC_NETWORKS)):
                issues.add((name, 'non-example IPv4 literal'))
        for url in re.findall(r'https?://[^\s\x22\x27<>`]+', text):
            host = urlsplit(url).hostname
            if not host or host == 'localhost' or host in UPSTREAM_HOSTS or host.endswith(('.example.invalid', '.example.org', '.example.com')):
                continue
            try:
                ip = ipaddress.ip_address(host)
                allowed = ip.is_loopback or ip.is_unspecified
            except ValueError:
                allowed = False
            if not allowed:
                issues.add((name, 'URL host needs public-source review'))
    dns = json.loads((ROOT / 'deploy/android/ddns.example.json').read_text())
    if dns['zone_id'] != '0' * 32 or dns['zone_name'] != 'example.invalid':
        issues.add(('deploy/android/ddns.example.json', 'non-placeholder DNS account'))
    client_example = ROOT / '.env.client.example'
    if client_example.exists():
        try:
            try:
                from .client_config import environment, public_config
            except ImportError:
                from client_config import environment, public_config
            values = environment(client_example, {})
            config = public_config(values)
            if (not urlsplit(config.repo_url).hostname.endswith('.example.invalid') or
                    config.repo_fingerprint != '0' * 64 or
                    values.get('STORE_CLIENT_CERTIFICATE_SHA256') != '0' * 64):
                issues.add(('.env.client.example', 'client example must contain synthetic placeholders'))
        except ValueError:
            issues.add(('.env.client.example', 'invalid or unsupported example configuration'))
    for name, reason in sorted(issues):
        print(f'{name}: {reason}')
    if issues:
        raise SystemExit(1)
    print('Tracked public files: no private artifacts or deployment literals detected.')


if __name__ == '__main__':
    check()
