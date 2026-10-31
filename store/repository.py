from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import zipfile

import yaml

log = logging.getLogger(__name__)


class PublishError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


class Repository:
    def __init__(self, root, url, *, fdroid="fdroid", aapt="aapt", apksigner="apksigner"):
        self.root = Path(root).resolve()
        self.url = url.rstrip("/")
        self.fdroid = fdroid
        self.aapt = aapt
        self.apksigner = apksigner

    @contextmanager
    def lock(self, name="publish", *, shared=False, blocking=True):
        # The download container only needs read access to this existing inode.
        with (self.root / f".{name}.lock").open("rb" if shared else "a+b") as lock:
            mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            try:
                fcntl.flock(lock, mode | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                raise PublishError("Another publication is in progress; retry later", 503)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def current(self):
        return (self.root / "current").resolve(strict=True)

    def state(self):
        with self.lock("commit", shared=True):
            return json.loads((self.current() / "state.json").read_text())

    def initialize(self, import_repo=None):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".commit.lock").touch(exist_ok=True)
        with self.lock():
            signing = self.root / "signing"
            if not (signing / "config.yml").exists():
                staging = self.root / ".signing-init"
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(mode=0o700)
                if import_repo:
                    source = Path(import_repo).resolve()
                    config = yaml.safe_load((source / "config.yml").read_text())
                    key = Path(config["keystore"])
                    shutil.copy2(key if key.is_absolute() else source / key, staging / "keystore.p12")
                    (staging / "config.yml").write_text(yaml.safe_dump(config))
                else:
                    subprocess.run([self.fdroid, "init", "--no-prompt", "--repo-keyalias", "store", "--distinguished-name", "CN=Ming Store"], cwd=staging, check=True, timeout=120, capture_output=True)
                config = yaml.safe_load((staging / "config.yml").read_text())
                config = {k: config[k] for k in ("keystorepass", "keypass", "repo_keyalias")}
                config["keystore"] = str(signing / "keystore.p12")
                (staging / "config.yml").write_text(yaml.safe_dump(config))
                (staging / "config.yml").chmod(0o600)
                (staging / "keystore.p12").chmod(0o600)
                os.rename(staging, signing)
            (self.root / "generations").mkdir(exist_ok=True)
            (self.root / "incoming").mkdir(exist_ok=True)
            # Recover interrupted uploads/builds; never remove the committed generation.
            for item in (self.root / "incoming").iterdir():
                item.unlink()
            with self.lock("commit"):
                self.prune()
            if not (self.root / "current").exists():
                self.build({}, None)
            elif self.state()["repo_url"] != self.url:
                self.build(self.state()["apps"], None)

    def inspect(self, path):
        try:
            result = subprocess.run([self.apksigner, "verify", "--print-certs", str(path)], capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise PublishError("Invalid or unsigned APK")
            signers = sorted(set(re.findall(r"Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})", result.stdout)))
            if not signers:
                raise PublishError("APK has no verified signing certificate")
            result = subprocess.run([self.aapt, "dump", "badging", str(path)], capture_output=True, text=True, timeout=120)
            match = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", result.stdout, re.M)
            if result.returncode or not match:
                raise PublishError("Cannot read APK package and version")
            package, code, version = match.groups()
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package) or not 0 < int(code) <= 2100000000:
                raise PublishError("Invalid package name or versionCode")
            if re.search(r"^package:.*\bsplit=", result.stdout, re.M):
                raise PublishError("Upload a standalone APK, not a split APK")
            label = re.search(r"^application-label:'(.*)'$", result.stdout, re.M)
            name = label.group(1) if label else ""
            if not name:
                # aapt omits labels stored as literal manifest strings.
                from loguru import logger
                from androguard.core.apk import APK
                logger.disable("androguard")
                try:
                    name = APK(str(path)).get_app_name()
                except Exception as exc:
                    raise PublishError("Cannot read APK application metadata") from exc
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            return {"package": package, "version_code": int(code), "version_name": version,
                    "name": name or package, "signers": signers,
                    "sha256": digest, "size": path.stat().st_size,
                    "file": f"{package}_{code}.apk"}
        except subprocess.TimeoutExpired:
            raise PublishError("APK inspection timed out")

    def publish(self, path, notes=""):
        """Caller holds publish lock, including while receiving the upload."""
        apk = self.inspect(path)
        apps = self.state()["apps"]
        previous = apps.get(apk["package"])
        if previous:
            if previous["sha256"] == apk["sha256"]:
                return {"status": "unchanged", "app": previous, "repo_url": self.url}
            if previous["signers"] != apk["signers"]:
                raise PublishError("Signing certificate does not match current app", 409)
            if apk["version_code"] <= previous["version_code"]:
                raise PublishError("versionCode must be greater than the current version", 409)
        apk["notes"] = notes
        apk["published_at"] = datetime.now(timezone.utc).isoformat()
        apps[apk["package"]] = apk
        self.build(apps, (path, apk))
        log.info("Published %s versionCode=%s sha256=%s", apk["package"], apk["version_code"], apk["sha256"])
        return {"status": "published", "app": apk, "repo_url": self.url}

    def build(self, apps, incoming):
        generation = self.root / "generations" / uuid.uuid4().hex
        generation.mkdir()
        committed = False
        try:
            repo = generation / "repo"
            repo.mkdir()
            metadata = generation / "metadata"
            metadata.mkdir()
            old = self.current() if (self.root / "current").exists() else None
            for package, apk in apps.items():
                source = incoming[0] if incoming and incoming[1]["package"] == package else old / "repo" / apk["file"]
                # Unchanged APKs share disk blocks with the previous generation.
                os.link(source, repo / apk["file"])
                # Upload tempfiles are 0600; a separate read-only download UID
                # must be able to read every public APK after publication.
                (repo / apk["file"]).chmod(0o644)
                data = {"Name": apk["name"], "Summary": apk["name"][:80], "License": "Unknown",
                        "Categories": ["Development"], "CurrentVersion": apk["version_name"],
                        "CurrentVersionCode": apk["version_code"]}
                (metadata / f"{package}.yml").write_text(yaml.safe_dump(data, allow_unicode=True))
                if apk.get("notes"):
                    changelogs = metadata / package / "en-US" / "changelogs"
                    changelogs.mkdir(parents=True)
                    (changelogs / f"{apk['version_code']}.txt").write_text(apk["notes"])
            config = yaml.safe_load((self.root / "signing/config.yml").read_text())
            config.update(repo_name="Ming Store", repo_description="Team Android apps", repo_url=self.url,
                          archive_older=0, apksigner=self.apksigner, aapt=self.aapt)
            config_path = generation / "config.yml"
            config_path.write_text(yaml.safe_dump(config))
            config_path.chmod(0o600)
            result = subprocess.run([self.fdroid, "update"], cwd=generation, capture_output=True, text=True, timeout=600)
            if result.returncode:
                # Keep only a bounded diagnostic, never include config contents in API errors.
                log.error("Index generation failed: %s", result.stderr[-4000:])
                raise PublishError("Index generation failed; current repository is unchanged", 500)
            with zipfile.ZipFile(repo / "index-v1.jar") as jar:
                index = json.loads(jar.read("index-v1.json"))
            expected = {p: [(a["version_code"], a["sha256"])] for p, a in apps.items()}
            actual = {p: [(v["versionCode"], v["hash"]) for v in versions] for p, versions in index["packages"].items()}
            if actual != expected:
                raise PublishError("Generated index does not match uploaded APKs; publication cancelled", 500)
            env = dict(os.environ, STORE_SIGNING_PASSWORD=config["keystorepass"])
            cert = subprocess.check_output(["keytool", "-exportcert", "-keystore", config["keystore"],
                                            "-alias", config["repo_keyalias"], "-storepass:env", "STORE_SIGNING_PASSWORD"], env=env, stderr=subprocess.PIPE, timeout=30)
            state = {"repo_url": self.url, "fingerprint": hashlib.sha256(cert).hexdigest().upper(), "apps": apps}
            (generation / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
            # Credentials are only needed during signing; never retain them in snapshots.
            config_path.unlink()
            for directory in ("tmp", "logs"):
                shutil.rmtree(generation / directory, ignore_errors=True)
            for file in generation.rglob("*"):
                if file.is_file():
                    with file.open("rb") as stream:
                        os.fsync(stream.fileno())
            for directory in sorted((p for p in generation.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                self.sync_dir(directory)
            self.sync_dir(generation)
            self.sync_dir(generation.parent)
            with self.lock("commit"):
                link = self.root / ".current-next"
                link.unlink(missing_ok=True)
                link.symlink_to(generation.relative_to(self.root))
                os.replace(link, self.root / "current")
                committed = True
                self.sync_dir(self.root)
                # Open downloads keep their file descriptors after unlink.
                self.prune()
        except subprocess.TimeoutExpired:
            raise PublishError("Index generation timed out; current repository is unchanged", 500)
        finally:
            if not committed:
                shutil.rmtree(generation, ignore_errors=True)

    @staticmethod
    def sync_dir(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def prune(self):
        current = self.current() if (self.root / "current").exists() else None
        for generation in (self.root / "generations").iterdir():
            if generation != current:
                shutil.rmtree(generation)

    def open_download(self, name):
        with self.lock("commit", shared=True):
            root = self.current() / "repo"
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file() or any(p.startswith(".") for p in Path(name).parts):
                raise FileNotFoundError(name)
            return path.open("rb")
