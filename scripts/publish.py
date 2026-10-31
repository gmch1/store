#!/usr/bin/env python3
"""Compatibility wrapper: all publication now goes through the API."""
from pathlib import Path
import subprocess
import sys

if len(sys.argv) < 2:
    sys.exit('Usage: python3 scripts/publish.py SIGNED_APK [SIGNED_APK ...]')
for apk in sys.argv[1:]:
    subprocess.run([sys.executable, str(Path(__file__).with_name('upload.py')), apk], check=True)
