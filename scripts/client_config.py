"""Client build configuration. Only PublicConfig may enter Android source or source archives."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CLIENT_KEYS = {
    'STORE_CLIENT_REPO_URL', 'STORE_CLIENT_REPO_FINGERPRINT', 'STORE_CLIENT_SOURCE_URL',
    'STORE_CLIENT_SIGNING_DIR', 'STORE_CLIENT_KEYSTORE', 'STORE_CLIENT_KEY_ALIAS',
    'STORE_CLIENT_PASSWORD_FILE', 'STORE_CLIENT_CERTIFICATE_SHA256',
    'STORE_CLIENT_ANDROID_HOME', 'STORE_CLIENT_GRADLE_USER_HOME',
    'ANDROID_HOME', 'GRADLE_USER_HOME', 'JAVA_HOME',
}


def release_metadata(path: Path | None = None) -> dict:
    data = json.loads((path or ROOT / 'client/release.json').read_text())
    if (set(data) != {'application_id', 'version_name', 'version_code'} or
            not isinstance(data.get('application_id'), str) or
            not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', data['application_id']) or
            not isinstance(data.get('version_name'), str) or
            not re.fullmatch(r'[A-Za-z0-9.+_-]+', data['version_name']) or
            type(data.get('version_code')) is not int or not 0 < data['version_code'] <= 2100000000):
        raise ValueError('client/release.json must contain a valid package, version name and positive version code')
    return data


def environment(path: Path | None = None, environ: dict | None = None) -> dict:
    """Read literal dotenv values; never execute shell, expand commands, or read password contents."""
    if path is not None and not path.is_file():
        raise ValueError('Requested client environment file does not exist')
    path = path if path is not None else ROOT / '.env.client'
    result = {}
    if path.exists():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].lstrip()
            key, separator, value = line.partition('=')
            key = key.strip()
            if not separator or key not in CLIENT_KEYS:
                raise ValueError(f'{path.name}:{number}: unsupported client configuration key')
            try:
                values = shlex.split(value, comments=True)
            except ValueError:
                raise ValueError(f'{path.name}:{number}: malformed quoted value') from None
            if len(values) > 1:
                raise ValueError(f'{path.name}:{number}: quote values containing spaces')
            result[key] = values[0] if values else ''
    result.update(os.environ if environ is None else environ)
    return result


def url(value: str, key: str) -> str:
    try:
        parsed = urlsplit(value)
        local = parsed.hostname == 'localhost'
        try:
            local = local or ipaddress.ip_address(parsed.hostname or '').is_loopback
        except ValueError:
            pass
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(character.isspace() or ord(character) < 32 for character in value)
                or parsed.scheme not in ('http', 'https')
                or parsed.scheme == 'http' and not local):
            raise ValueError()
        parsed.port
    except ValueError:
        raise ValueError(f'{key} must be HTTPS (or loopback HTTP), without credentials, query or fragment') from None
    return value.rstrip('/')


def fingerprint(value: str, key: str) -> str:
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError(f'{key} must be a 64-digit SHA-256 fingerprint')
    return value.upper()


@dataclass(frozen=True)
class PublicConfig:
    repo_url: str
    repo_fingerprint: str
    source_url: str

    def as_dict(self) -> dict:
        return asdict(self)


def public_config(env: dict, *, example: bool = False) -> PublicConfig:
    if example:
        # Deliberately ignore real environment values in CI/example builds.
        env = {'STORE_CLIENT_REPO_URL': 'https://store.example.invalid/fdroid/repo',
               'STORE_CLIENT_REPO_FINGERPRINT': '0' * 64}
    for key in ('STORE_CLIENT_REPO_URL', 'STORE_CLIENT_REPO_FINGERPRINT'):
        if not env.get(key):
            raise ValueError(f'Missing {key}; set it in the environment or .env.client')
    return PublicConfig(
        url(env['STORE_CLIENT_REPO_URL'], 'STORE_CLIENT_REPO_URL'),
        fingerprint(env['STORE_CLIENT_REPO_FINGERPRINT'], 'STORE_CLIENT_REPO_FINGERPRINT'),
        url(env.get('STORE_CLIENT_SOURCE_URL') or 'https://github.com/gmch1/store', 'STORE_CLIENT_SOURCE_URL'),
    )


@dataclass(frozen=True)
class SigningConfig:
    keystore: Path
    password_file: Path
    alias: str
    certificate_sha256: str


def signing_config(env: dict) -> SigningConfig:
    directory = Path(env.get('STORE_CLIENT_SIGNING_DIR') or '~/.local/share/ming-store/signing').expanduser()
    key = Path(env.get('STORE_CLIENT_KEYSTORE') or directory / 'ming-store.p12').expanduser()
    password = Path(env.get('STORE_CLIENT_PASSWORD_FILE') or directory / 'password').expanduser()
    alias = env.get('STORE_CLIENT_KEY_ALIAS') or 'ming-store'
    expected = fingerprint(env.get('STORE_CLIENT_CERTIFICATE_SHA256', ''), 'STORE_CLIENT_CERTIFICATE_SHA256')
    if not key.is_file() or not password.is_file():
        raise ValueError('Existing client signing files are missing; no new signing identity was generated')
    return SigningConfig(key.resolve(), password.resolve(), alias, expected)
