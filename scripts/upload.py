#!/usr/bin/env python3
"""CI/Skill client: upload an APK, retry safely, report the committed version."""
import argparse
import http.client
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode, urlsplit

parser = argparse.ArgumentParser()
parser.add_argument('apk', type=Path)
parser.add_argument('--url', default=os.environ.get('STORE_API_URL', 'http://127.0.0.1:8767'))
parser.add_argument('--key-file', type=Path, default=os.environ.get('STORE_API_KEY_FILE', '.local/api-key'))
parser.add_argument('--notes-file', type=Path)
args = parser.parse_args()
key = Path(args.key_file).read_text().strip()
notes = args.notes_file.read_text() if args.notes_file else ''
if len(notes.encode()) > 8192:
    sys.exit('Release notes exceed 8192 bytes')
url = urlsplit(args.url)
if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
    sys.exit('Invalid API base URL')
route = url.path.rstrip('/') + '/api/v1/releases'
if notes:
    route += '?' + urlencode({'notes': notes})
connection_type = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
for attempt in range(4):
    connection = connection_type(url.hostname, url.port, timeout=900)
    try:
        with args.apk.open('rb') as apk:
            connection.request('POST', route, body=apk, headers={
                'X-API-Key': key, 'Content-Type': 'application/vnd.android.package-archive',
                'Content-Length': str(args.apk.stat().st_size)})
            response = connection.getresponse()
            data = response.read()
            if response.status in (200, 201):
                print(json.dumps(json.loads(data), ensure_ascii=False, indent=2))
                sys.exit(0)
            if response.status not in (502, 503, 504) or attempt == 3:
                sys.exit(f'Upload failed (HTTP {response.status}): {data.decode(errors="replace")}')
    except (OSError, http.client.HTTPException) as exc:
        if attempt == 3:
            sys.exit(f'Upload failed: {exc}')
    finally:
        connection.close()
    time.sleep(5 * (attempt + 1))
