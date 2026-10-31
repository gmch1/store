"""Independent phone DDNS daemon; service stops do not stop DNS updates."""
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

STOP = threading.Event()
ACTIVE = None


def stop(signum, frame):
    STOP.set()
    if ACTIVE is not None and ACTIVE.poll() is None:
        try:
            os.killpg(ACTIVE.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def save(state):
    state['heartbeat'] = time.monotonic()
    temporary = Path('/run/ddns-status.tmp')
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace('/run/ddns-status.json')


def main():
    global ACTIVE
    config = json.loads(Path('/config/ddns.json').read_text())
    interval = int(config.get('interval_seconds', 60))
    retry = int(config.get('retry_seconds', 30))
    if not 15 <= interval <= 60 or not 15 <= retry <= 60:
        raise ValueError('DDNS intervals must be between 15 and 60 seconds')
    log = logging.getLogger('ddns')
    log.setLevel(logging.INFO)
    handler = RotatingFileHandler('/logs/ddns.log', maxBytes=2*1024*1024, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    log.addHandler(handler)
    state = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 pid=os.getpid(), last_success=None, result=None, error=None)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    while not STOP.is_set():
        save(state)
        delay = interval
        try:
            ACTIVE = subprocess.Popen(['python', '/app/deploy/android/worker_exec.py', str(os.getpid()),
                                       'python', '/app/deploy/android/update_dns.py'],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      start_new_session=True)
            try:
                output, errors = ACTIVE.communicate(timeout=75)
            except subprocess.TimeoutExpired:
                os.killpg(ACTIVE.pid, signal.SIGKILL)
                ACTIVE.communicate()
                raise RuntimeError('DNS update exceeded its 75-second deadline')
            if STOP.is_set():
                break
            if ACTIVE.returncode:
                raise RuntimeError(errors[-2000:].strip() or 'DNS update failed')
            state.update(result=json.loads(output), last_success=datetime.now(timezone.utc).isoformat(), error=None)
            log.info('DNS updated: %s', json.dumps(state['result']))
        except Exception as exc:
            state['error'] = str(exc)
            delay = retry
            log.warning('DNS retry in %ss: %s', delay, exc)
        finally:
            ACTIVE = None
            save(state)
        STOP.wait(delay)


if __name__ == '__main__':
    main()
