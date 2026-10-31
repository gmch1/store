#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
version="${1:?Usage: scripts/build-probe.sh VERSION_CODE}"
[[ "$version" =~ ^[1-9][0-9]*$ ]] || { echo 'Version must be a positive integer' >&2; exit 1; }
sdk="${ANDROID_HOME:-$HOME/.android-sdk}"
bt="$sdk/build-tools/35.0.0"
android="$sdk/platforms/android-35/android.jar"
[[ -f "$android" ]] || android="$sdk/platforms/android-36/android.jar"
out="$PWD/.local/probe/$version"
mkdir -p "$out/classes" "$out/dex" .local/probe
if [[ ! -f .local/probe/test-key.p12 ]]; then
    keytool -genkeypair -keystore .local/probe/test-key.p12 -storepass store-probe-only -keypass store-probe-only -alias probe -dname 'CN=Store Test Probe' -keyalg RSA -keysize 2048 -validity 3650
fi
cat > "$out/AndroidManifest.xml" <<EOF
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.ming.store.probe" android:versionCode="$version" android:versionName="0.0.$version">
  <uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35" />
  <application android:label="Store Test Probe" android:theme="@android:style/Theme.Material.Light.NoActionBar" android:allowBackup="false">
    <activity android:name=".MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>
  </application>
</manifest>
EOF
javac -source 8 -target 8 -classpath "$android" -d "$out/classes" tests/probe/MainActivity.java
"$bt/d8" --lib "$android" --output "$out/dex" "$out/classes/com/ming/store/probe/MainActivity.class"
"$bt/aapt" package -f -M "$out/AndroidManifest.xml" -I "$android" -F "$out/unsigned.apk"
python3 - "$out" <<'PY'
import sys, zipfile
from pathlib import Path
p = Path(sys.argv[1])
with zipfile.ZipFile(p / 'unsigned.apk', 'a') as z:
    z.write(p / 'dex/classes.dex', 'classes.dex')
PY
"$bt/zipalign" -f 4 "$out/unsigned.apk" "$out/aligned.apk"
"$bt/apksigner" sign --ks .local/probe/test-key.p12 --ks-pass pass:store-probe-only --out "$out/com.ming.store.probe_$version.apk" "$out/aligned.apk"
"$bt/apksigner" verify "$out/com.ming.store.probe_$version.apk"
echo "$out/com.ming.store.probe_$version.apk"
