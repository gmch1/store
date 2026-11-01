#!/usr/bin/env python3
"""Prepare the pinned Android client, with optional local customization, without deploying it."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def git(source: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(source), *args])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate(source: Path, commit: str, expected_diff: str) -> None:
    if git(source, "rev-parse", "HEAD").decode().strip() != commit:
        raise RuntimeError("Prepared source has an unexpected upstream commit")
    git(source, "diff", "--exit-code")
    if digest(git(source, "diff", "--cached", "--binary")) != expected_diff:
        raise RuntimeError("Prepared source has unexpected staged changes")
    if git(source, "ls-files", "--others", "--exclude-standard").strip():
        raise RuntimeError("Prepared source contains untracked files")


def prepare(manifest: dict, patches: list[Path], destination: Path,
            *, upstream: str | None = None, version_name: str | None = None,
            version_code: int | None = None) -> tuple[Path, str]:
    patch_bytes = [patch.read_bytes() for patch in patches]
    recipe = {"upstream": manifest, "patches": [digest(data) for data in patch_bytes],
              "version_name": version_name, "version_code": version_code}
    identity = digest(json.dumps(recipe, sort_keys=True).encode())
    source = destination / f"build-{identity[:16]}"
    marker = source / ".git/store-build.json"
    if source.exists():
        if not marker.is_file():
            raise RuntimeError(f"Incomplete checkout at {source}; choose another destination")
        record = json.loads(marker.read_text())
        if record["identity"] != identity:
            raise RuntimeError("Prepared source belongs to another recipe")
        validate(source, manifest["commit"], record["diff_sha256"])
        return source, record["diff_sha256"]
    source.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", "--branch", manifest["tag"],
                    upstream or manifest["url"], str(source)], check=True)
    if git(source, "rev-parse", "HEAD").decode().strip() != manifest["commit"]:
        raise RuntimeError("Upstream tag no longer matches the pinned commit")
    for patch, expected in zip(patches, patch_bytes):
        if patch.read_bytes() != expected:
            raise RuntimeError("Patch changed during preparation")
        git(source, "apply", "--index", str(patch.resolve()))
    if version_name is not None or version_code is not None:
        gradle = source / "app/build.gradle.kts"
        text = gradle.read_text()
        for field, value in (("versionName", json.dumps(version_name)),
                             ("versionCode", str(version_code))):
            if (field == "versionName" and version_name is None or
                    field == "versionCode" and version_code is None):
                continue
            text, count = re.subn(rf'(?m)^(\s*{field}\s*=\s*)[^\n]+$',
                                  lambda match: match[1] + value, text)
            if count != 1:
                raise RuntimeError(f"Expected exactly one {field} in app/build.gradle.kts")
        gradle.write_text(text)
        git(source, "add", "app/build.gradle.kts")
    result = digest(git(source, "diff", "--cached", "--binary"))
    marker.write_text(json.dumps(dict(recipe, identity=identity, diff_sha256=result), indent=2) + "\n")
    validate(source, manifest["commit"], result)
    return source, result


def archive_source(source: Path, target: Path, manifest: dict, patches: list[Path],
                   version_name: str | None, version_code: int | None) -> None:
    """Include only tracked source and the exact applied recipe, never Git, caches or keys."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w:gz") as archive:
        for name in filter(None, git(source, "ls-files", "-z").decode().split("\0")):
            archive.add(source / name, arcname=f"client-source/{name}", recursive=False)
        additions = {
            "recipe/upstream.json": (json.dumps(manifest, indent=2) + "\n").encode(),
            "recipe/applied.patch": git(source, "diff", "--cached", "--binary"),
            "recipe/versions.json": (json.dumps({"version_name": version_name,
                                                "version_code": version_code}) + "\n").encode(),
            "recipe/README.md": (ROOT / "client/README.md").read_bytes(),
        }
        for i, patch in enumerate(patches):
            additions[f"recipe/input-{i + 1}.patch"] = patch.read_bytes()
        for name, data in additions.items():
            info = tarfile.TarInfo(f"client-source/{name}")
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customization-patch", type=Path, action="append", default=[],
                        help="Existing local branding/repository patch, applied before the public fix")
    parser.add_argument("--destination", type=Path, default=ROOT / ".local/client")
    parser.add_argument("--upstream-cache", type=Path, help="Optional local clone of the pinned upstream")
    parser.add_argument("--version-name")
    parser.add_argument("--version-code", type=int)
    parser.add_argument("--archive", type=Path, help="Write corresponding full source after validation")
    args = parser.parse_args()
    if args.version_code is not None and not 0 < args.version_code <= 2100000000:
        parser.error("--version-code must be positive and at most 2100000000")
    if args.version_name is not None and not re.fullmatch(r"[A-Za-z0-9.+_-]+", args.version_name):
        parser.error("--version-name must contain only letters, digits, '.', '+', '_' or '-'")
    manifest = json.loads((ROOT / "client/upstream.json").read_text())
    patches = [*args.customization_patch, ROOT / "client/patches/update-state.patch"]
    source, expected = prepare(manifest, patches, args.destination.resolve(),
                               upstream=str(args.upstream_cache.resolve()) if args.upstream_cache else None,
                               version_name=args.version_name, version_code=args.version_code)
    if args.archive:
        validate(source, manifest["commit"], expected)
        archive_source(source, args.archive.resolve(), manifest, patches, args.version_name, args.version_code)
    print(source)


if __name__ == "__main__":
    main()
