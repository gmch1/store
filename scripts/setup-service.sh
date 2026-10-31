#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .local/data
python3 - <<'PY'
from pathlib import Path
import os, secrets
p = Path('.local/api-key')
if not p.exists():
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(48) + '\n')
if not Path('.env').exists():
    Path('.env').write_text(Path('.env.example').read_text())
print('API key: .local/api-key (not printed)')
PY
