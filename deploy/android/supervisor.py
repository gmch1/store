"""Phone process supervisor; application workers run under dedicated UIDs."""
import json
import fcntl
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

ROOT = Path('/app')
CONFIG = json.loads(Path('/config/runtime.json').read_text())
STOP = threading.Event()
PROCESSES = {}
Path('/logs').mkdir(exist_ok=True)
LOCK = Path('/run/store-supervisor.lock').open('a')
fcntl.flock(LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
Path('/run/store-supervisor.pid').write_text(str(os.getpid()))


def logger(name):
    result = logging.getLogger(name)
    if result.handlers:
        return result
    result.setLevel(logging.INFO)
    handler = RotatingFileHandler(f'/logs/{name}.log', maxBytes=2*1024*1024, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    result.addHandler(handler)
    return result


LOG = logger('supervisor')


def consume(process, name):
    output = logger(name)
    for line in process.stdout:
        output.info(line.rstrip())


def worker(name, args, uid, extra=None, bind=False):
    env = dict(os.environ, HOME=f'/home/{name}', PYTHONUNBUFFERED='1',
               STORE_DATA='/data', STORE_REPO_URL=CONFIG['repo_url'])
    if extra:
        env.update(extra)
    command = ['setpriv', f'--reuid={uid}', f'--regid={uid}', '--groups=3003', '--no-new-privs']
    if bind:
        command += ['--inh-caps=+net_bind_service', '--ambient-caps=+net_bind_service']
    command += ['python', '/app/deploy/android/worker_exec.py', str(os.getpid()), *args]
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors='replace', start_new_session=True)
    threading.Thread(target=consume, args=(process, name), daemon=True).start()
    PROCESSES[name] = process
    LOG.info('Started %s pid=%s uid=%s', name, process.pid, uid)


def stop(signum, frame):
    STOP.set()


for sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(sig, stop)
specs = {
    'api': (['python', '-m', 'store', 'api', '--host', CONFIG['api_bind'], '--port', '8767'], 6001,
            {'STORE_API_KEY_FILE': '/run/secrets/store_api_key'}, False),
    'downloads': (['python', '-m', 'store', 'downloads', '--host', '127.0.0.1', '--port', '18766'], 6002, None, False),
    'https': (['caddy', 'run', '--config', '/config/Caddyfile', '--adapter', 'caddyfile'], 6003,
              {'XDG_DATA_HOME': '/caddy/data', 'XDG_CONFIG_HOME': '/caddy/config'}, True),
}
try:
    while not STOP.is_set():
        heartbeat = Path('/run/store-heartbeat.tmp')
        heartbeat.write_text(str(time.monotonic()))
        heartbeat.replace('/run/store-heartbeat')
        for name, spec in specs.items():
            process = PROCESSES.get(name)
            if process is None or process.poll() is not None:
                if process:
                    LOG.warning('%s exited with %s; restarting', name, process.returncode)
                worker(name, *spec)
        STOP.wait(5)
finally:
    for process in PROCESSES.values():
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 15
    for process in PROCESSES.values():
        try:
            process.wait(timeout=max(0.1, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    Path('/run/store-supervisor.pid').unlink(missing_ok=True)
    Path('/run/store-heartbeat').unlink(missing_ok=True)
    LOG.info('Stopped all workers')
