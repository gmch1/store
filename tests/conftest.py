import subprocess

import pytest

from scripts.prepare_client import git


@pytest.fixture
def recipe(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    (upstream / "app").mkdir()
    (upstream / "app/build.gradle.kts").write_text('defaultConfig {\n    applicationId = "com.example.original"\n    versionName = "1.0.0"\n    versionCode = 1\n}\n')
    (upstream / "app/Main.kt").write_text("val staleNotification = true\n")
    (upstream / ".gitignore").write_text("build/\nlocal.properties\n*.key\n")
    git(upstream, "add", ".")
    git(upstream, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    commit = git(upstream, "rev-parse", "HEAD").decode().strip()
    git(upstream, "tag", "vtest")
    manifest = {"url": "https://github.com/Droid-ify/client.git", "tag": "vtest", "commit": commit}
    (upstream / "app/Main.kt").write_text("val staleNotification = false\n")
    patch = tmp_path / "fix.patch"
    patch.write_bytes(git(upstream, "diff", "--binary"))
    git(upstream, "restore", "app/Main.kt")
    return upstream, manifest, patch, tmp_path / "prepared"
