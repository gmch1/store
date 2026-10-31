#!/usr/bin/env bash
set -euo pipefail
apk="${1:?Usage: scripts/install-downloaded-root.sh EXPECTED_APK ADB_SERIAL}"
serial="${2:?ADB serial is required}"
digest="$(sha256sum "$apk" | cut -d ' ' -f 1)"
[[ "$digest" =~ ^[a-f0-9]{64}$ ]]
cache="/data/user/0/com.looker.droidify/cache/releases/$digest.apk"
actual="$(adb -s "$serial" shell "su -c 'sha256sum $cache'" | tr -d '\r' | cut -d ' ' -f 1)"
[[ "$actual" == "$digest" ]] || { echo 'Droid-ify download missing or checksum mismatch' >&2; exit 1; }
# Install the actual client download; no re-signing, downgrading, or data clearing.
adb -s "$serial" shell "su -c 'cp $cache /data/local/tmp/store-validation.apk && chmod 644 /data/local/tmp/store-validation.apk && pm install -r /data/local/tmp/store-validation.apk'"
