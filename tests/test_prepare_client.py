import json
import subprocess
import tarfile

import pytest

from scripts.prepare_client import archive_source, git, prepare


@pytest.fixture
def recipe(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    (upstream / "app").mkdir()
    (upstream / "app/build.gradle.kts").write_text('defaultConfig {\n    versionName = "1.0.0"\n    versionCode = 1\n}\n')
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


def test_pinned_patch_and_version_override_are_repeatable(recipe):
    upstream, manifest, patch, destination = recipe
    options = dict(upstream=str(upstream), version_name="1.0.1", version_code=2)
    source, expected = prepare(manifest, [patch], destination, **options)
    assert (source / "app/Main.kt").read_text() == "val staleNotification = false\n"
    assert 'versionName = "1.0.1"' in (source / "app/build.gradle.kts").read_text()
    assert "versionCode = 2" in (source / "app/build.gradle.kts").read_text()
    assert prepare(manifest, [patch], destination, **options) == (source, expected)


@pytest.mark.parametrize("change", ["unstaged", "staged", "untracked"])
def test_existing_source_edits_are_preserved_and_rejected(recipe, change):
    upstream, manifest, patch, destination = recipe
    source, _ = prepare(manifest, [patch], destination, upstream=str(upstream))
    target = source / ("extra.txt" if change == "untracked" else "app/Main.kt")
    target.write_text("developer changes\n")
    if change == "staged":
        git(source, "add", "app/Main.kt")
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        prepare(manifest, [patch], destination, upstream=str(upstream))
    assert target.read_text() == "developer changes\n"


def test_moved_upstream_tag_is_rejected(recipe):
    upstream, manifest, patch, destination = recipe
    with pytest.raises(RuntimeError, match="pinned commit"):
        prepare(dict(manifest, commit="0" * 40), [patch], destination, upstream=str(upstream))


def test_changed_patch_gets_separate_checkout(recipe):
    upstream, manifest, patch, destination = recipe
    original, _ = prepare(manifest, [patch], destination, upstream=str(upstream))
    patch.write_bytes(patch.read_bytes().replace(b"false", b"null"))
    changed, _ = prepare(manifest, [patch], destination, upstream=str(upstream))
    assert original != changed
    assert "false" in (original / "app/Main.kt").read_text()
    assert "null" in (changed / "app/Main.kt").read_text()


def test_full_source_archive_excludes_secrets_git_and_build_cache(recipe, tmp_path):
    upstream, manifest, patch, destination = recipe
    source, _ = prepare(manifest, [patch], destination, upstream=str(upstream))
    (source / "build").mkdir()
    (source / "build/cache").write_text("disposable cache")
    (source / "local.properties").write_text("sdk.dir=/example/sdk")
    (source / "signing.key").write_text("synthetic-secret")
    target = tmp_path / "source.tar.gz"
    archive_source(source, target, manifest, [patch], None, None)
    with tarfile.open(target) as archive:
        names = archive.getnames()
        assert not any(".git/" in name or "/build/" in name or name.endswith((".key", "local.properties")) for name in names)
        assert archive.extractfile("client-source/app/Main.kt").read() == b"val staleNotification = false\n"
        applied = archive.extractfile("client-source/recipe/applied.patch").read()
        assert applied == git(source, "diff", "--cached", "--binary")
        assert json.load(archive.extractfile("client-source/recipe/upstream.json")) == manifest
