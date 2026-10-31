"""Reap this chroot's dedicated store UIDs after a supervisor crash.

No app UID, root SSH session, or process outside this filesystem root qualifies.
Also covers Java grandchildren left after an uncatchable supervisor kill.
"""
import os
from pathlib import Path
import signal
import time


WORKER_UIDS = {6001, 6002, 6003}


def owned(pid, root):
    try:
        directory = Path('/proc') / str(pid)
        status = (directory / 'status').read_text()
        uid = next(line for line in status.splitlines() if line.startswith('Uid:'))
        if int(uid.split()[2]) not in WORKER_UIDS:
            return False
        info = (directory / 'root').stat()
        return (info.st_dev, info.st_ino) == root
    except (FileNotFoundError, ProcessLookupError, PermissionError, StopIteration):
        return False


def cleanup():
    info = Path('/').stat()
    root = info.st_dev, info.st_ino
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for entry in Path('/proc').iterdir():
            if entry.name.isdigit() and owned(entry.name, root):
                try:
                    os.kill(int(entry.name), sig)
                except ProcessLookupError:
                    pass
        if sig == signal.SIGTERM:
            time.sleep(1)
    for name in ('store-supervisor.pid', 'store-heartbeat'):
        (Path('/run') / name).unlink(missing_ok=True)


if __name__ == '__main__':
    cleanup()
