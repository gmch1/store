import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

from fastapi.testclient import TestClient
import pytest

from store.api import create_api, create_downloads
from store.repository import Repository

ROOT = Path(__file__).resolve().parents[1]
KEY = "store-integration-test-" + "x" * 32
PACKAGE = "com.ming.store.probe"


@pytest.fixture(scope="module")
def apks():
    for version in (1, 2, 3):
        path = ROOT / f".local/probe/{version}/{PACKAGE}_{version}.apk"
        if not path.exists():
            subprocess.run(["bash", "scripts/build-probe.sh", str(version)], cwd=ROOT, check=True, capture_output=True)
    return {v: ROOT / f".local/probe/{v}/{PACKAGE}_{v}.apk" for v in (1, 2, 3)}


@pytest.fixture
def repo(tmp_path):
    tools = Path(os.environ.get("ANDROID_HOME", str(Path.home() / ".android-sdk"))) / "build-tools/35.0.0"
    repository = Repository(tmp_path / "store", "http://127.0.0.1:8766/fdroid/repo",
                            fdroid=str(ROOT / ".venv/bin/fdroid"), aapt=str(tools / "aapt"), apksigner=str(tools / "apksigner"))
    repository.initialize()
    return repository


def client(repo, **kwargs):
    return TestClient(create_api(repo, key=KEY, initialize=False, **kwargs), client=("127.0.0.1", 1234))


def upload(client, path, **kwargs):
    return client.post("/api/v1/releases", content=path.read_bytes(), headers={"X-API-Key": KEY, "Content-Type": "application/vnd.android.package-archive"}, **kwargs)


def test_real_publish_upgrade_retry_and_download(repo, apks):
    api = client(repo)
    downloads = TestClient(create_downloads(repo))
    first = upload(api, apks[1], params={"notes": "首个版本\n修复测试"})
    assert first.status_code == 201, first.text
    assert first.json()["app"]["name"] == "Store Test Probe"
    assert upload(api, apks[1]).json()["status"] == "unchanged"
    assert len(list((repo.root / "generations").iterdir())) == 1
    filename = first.json()["app"]["file"]
    assert (repo.current() / "repo" / filename).stat().st_mode & 0o777 == 0o644
    response = downloads.get(f"/fdroid/repo/{filename}", headers={"Range": "bytes=0-15"})
    assert response.status_code == 206
    assert response.content == apks[1].read_bytes()[:16]
    assert downloads.head(f"/fdroid/repo/{filename}").headers["content-length"] == str(apks[1].stat().st_size)
    # A download opened before replacement must survive old-version deletion.
    held = repo.open_download(filename)
    second = upload(api, apks[2])
    assert second.status_code == 201, second.text
    assert held.read() == apks[1].read_bytes()
    held.close()
    assert downloads.get(f"/fdroid/repo/{filename}").status_code == 404
    assert upload(api, apks[1]).status_code == 409
    assert upload(api, apks[2]).status_code == 200
    files = list((repo.root / "generations").glob("*/repo/*.apk"))
    assert [f.name for f in files] == [f"{PACKAGE}_2.apk"]
    with zipfile.ZipFile(repo.current() / "repo/index-v1.jar") as archive:
        index = json.loads(archive.read("index-v1.json"))
    assert index["packages"][PACKAGE][0]["versionCode"] == 2
    assert index["packages"][PACKAGE][0]["hash"] == hashlib.sha256(apks[2].read_bytes()).hexdigest()
    assert list((repo.root / "incoming").iterdir()) == []
    # A process restart removes interrupted work but preserves the repository identity.
    fingerprint = repo.state()["fingerprint"]
    (repo.root / "generations/interrupted").mkdir()
    (repo.root / "incoming/interrupted.apk").write_bytes(b"partial")
    repo.initialize()
    assert repo.state()["fingerprint"] == fingerprint
    assert len(list((repo.root / "generations").iterdir())) == 1
    assert not list((repo.root / "incoming").iterdir())


def test_auth_limits_and_separate_public_surface(repo, apks):
    api = client(repo, max_bytes=16)
    assert api.post("/api/v1/releases", content=b"x").status_code == 401
    assert api.get("/api/v1/apps", headers={"X-API-Key": "wrong"}).status_code == 401
    assert upload(api, apks[1]).status_code == 413
    assert not list((repo.root / "incoming").iterdir())
    assert api.post("/api/v1/releases", headers={"X-API-Key": KEY}, content=b"x").status_code == 415
    external = TestClient(create_api(repo, key=KEY, initialize=False), client=("2001:db8::123", 1234))
    assert external.get("/api/v1/apps", headers={"X-API-Key": KEY, "X-Forwarded-For": "127.0.0.1"}).status_code == 403
    public = TestClient(create_downloads(repo))
    for path in ("/api/v1/apps", "/config.yml", "/fdroid/repo/%2e%2e/state.json", "/fdroid/repo/%2e%2e/%2e%2e/signing/config.yml"):
        assert public.get(path).status_code == 404
    assert public.post("/api/v1/releases", headers={"X-API-Key": KEY}, content=b"x").status_code == 404


def test_failed_index_and_busy_publisher_leave_current_intact(repo, apks):
    api = client(repo)
    assert upload(api, apks[1]).status_code == 201
    previous = repo.current()
    signed_index = (previous / "repo/index-v1.jar").read_bytes()
    with repo.lock():
        busy = upload(api, apks[2])
        assert busy.status_code == 503
        assert busy.headers["retry-after"] == "5"
    repo.fdroid = "/bin/false"
    result = upload(api, apks[2])
    assert result.status_code == 500, result.text
    assert repo.current() == previous
    assert (previous / "repo/index-v1.jar").read_bytes() == signed_index
    assert len(list((repo.root / "generations").iterdir())) == 1
    assert not list((repo.root / "incoming").iterdir())


def test_reject_unsigned_changed_certificate_and_reused_version(repo, apks, tmp_path):
    api = client(repo)
    assert upload(api, apks[1]).status_code == 201
    unsigned = ROOT / ".local/probe/2/unsigned.apk"
    assert upload(api, unsigned).status_code == 422
    # A valid APK with the same version and signing key but different bytes.
    changed = tmp_path / "changed.apk"
    shutil.copy2(ROOT / ".local/probe/1/unsigned.apk", changed)
    with zipfile.ZipFile(changed, "a") as archive:
        archive.writestr("assets/changed.txt", "different build, same version")
    subprocess.run([repo.apksigner, "sign", "--ks", str(ROOT / ".local/probe/test-key.p12"), "--ks-pass", "pass:store-probe-only", str(changed)], check=True, capture_output=True)
    assert upload(api, changed).status_code == 409
    # An otherwise valid newer APK signed by an unrelated developer key.
    alternate = tmp_path / "other-key.p12"
    subprocess.run(["keytool", "-genkeypair", "-keystore", str(alternate), "-storepass", "test-only-password", "-alias", "other", "-dname", "CN=Other Test", "-keyalg", "RSA", "-validity", "1"], check=True, capture_output=True)
    shutil.copy2(unsigned, changed)
    subprocess.run([repo.apksigner, "sign", "--ks", str(alternate), "--ks-pass", "pass:test-only-password", str(changed)], check=True, capture_output=True)
    result = upload(api, changed)
    assert result.status_code == 409
    assert "certificate" in result.json()["detail"]
    assert repo.state()["apps"][PACKAGE]["version_code"] == 1
