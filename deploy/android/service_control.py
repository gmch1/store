"""Serialize manual operations and health recovery, respecting persistent stops."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import time


def control(unit, action, only_if_enabled=False, services=Path('/services')):
    if unit not in {'store', 'sshd', 'health', 'ddns'}:
        raise ValueError('Unknown service')
    directory = services / unit
    with (directory / 'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        disabled = directory / 'down'
        if only_if_enabled and disabled.exists():
            return 0
        if action == 'stop':
            disabled.touch()
        elif action in {'start', 'restart'}:
            disabled.unlink(missing_ok=True)
        if action != 'status':
            deadline = time.monotonic() + 12
            while True:
                try:
                    fd = os.open(directory / 'supervise/ok', os.O_WRONLY | os.O_NONBLOCK)
                    os.close(fd)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.2)
        operation = {'stop': 'force-stop', 'restart': 'force-restart'}.get(action, action)
        result = subprocess.run(['sv', '-w', '25', operation, str(directory)], timeout=40)
        if result.returncode and action in {'stop', 'restart'}:
            # force-* sends KILL at its deadline. Wait for orphan cleanup too.
            operation = 'stop' if action == 'stop' else 'start'
            result = subprocess.run(['sv', '-w', '20', operation, str(directory)], timeout=35)
        return result.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('unit', choices=['store', 'sshd', 'health', 'ddns'])
    parser.add_argument('action', choices=['start', 'stop', 'restart', 'status'])
    args = parser.parse_args()
    raise SystemExit(control(args.unit, args.action))
