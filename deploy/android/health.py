"""Local protocol checks and bounded recovery for independent runit services."""
import argparse
import http.client
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import socket
import ssl
import subprocess
import time
from urllib.parse import urlparse

from service_control import control

INTERVAL = 15
GRACE = 45
FAILURES = 3


def http_health(host, port, tls_name=None):
    with socket.create_connection((host, port), timeout=3) as connection:
        stream = connection
        if tls_name:
            stream = ssl.create_default_context().wrap_socket(connection, server_hostname=tls_name)
        try:
            stream.sendall(f'GET /healthz HTTP/1.1\r\nHost: {tls_name or host}\r\nConnection: close\r\n\r\n'.encode())
            response = http.client.HTTPResponse(stream)
            response.begin()
            body = response.read(4096)
            if response.status != 200 or json.loads(body).get('status') != 'ok':
                raise RuntimeError(f'Unhealthy HTTP response from {host}:{port}')
        finally:
            if stream is not connection:
                stream.close()


def check(unit, config):
    if unit == 'sshd':
        # Check key exchange, rather than merely an open TCP listener.
        result = subprocess.run(['ssh-keyscan', '-T', '3', '-t', 'ed25519', '-p', '8022',
                                 config['api_bind']], capture_output=True, text=True, timeout=5)
        expected = Path('/maintenance-ssh/ssh_host_ed25519_key.pub').read_text().split()[1]
        keys = [line.split()[2] for line in result.stdout.splitlines()
                if len(line.split()) == 3 and line.split()[1] == 'ssh-ed25519']
        if result.returncode or expected not in keys:
            raise RuntimeError('SSH key exchange failed or unexpected host key')
    elif unit == 'ddns':
        state = json.loads(Path('/run/ddns-status.json').read_text())
        if state['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            raise RuntimeError('DDNS status is from a previous boot')
        if time.monotonic() - state['heartbeat'] > 180:
            raise RuntimeError('DDNS daemon heartbeat expired')
    elif unit == 'store':
        heartbeat = float(Path('/run/store-heartbeat').read_text())
        if time.monotonic() - heartbeat > GRACE:
            raise RuntimeError('Store supervisor heartbeat expired')
        http_health(config['api_bind'], 8767)
        http_health('127.0.0.1', 18766)
        http_health('127.0.0.1', 443, urlparse(config['repo_url']).hostname)
    else:
        raise ValueError('Unknown health target')


class Recovery:
    def __init__(self):
        self.pid = None
        self.since = 0
        self.failures = 0
        self.next_attempt = 0
        self.delay = 30
        self.healthy_since = None

    def observe(self, pid, enabled, healthy, now):
        if not enabled:
            self.__init__()
            return False
        if pid != self.pid:
            self.pid, self.since, self.failures = pid, now, 0
            self.healthy_since = None
        if healthy:
            self.failures = 0
            if self.healthy_since is None:
                self.healthy_since = now
            if now - self.healthy_since >= 120:
                self.delay = 30
            return False
        self.healthy_since = None
        if not pid or now - self.since < GRACE:
            return False
        self.failures += 1
        if self.failures < FAILURES or now < self.next_attempt:
            return False
        self.next_attempt = now + self.delay
        self.delay = min(self.delay * 2, 300)
        self.failures = 0
        return True


def monitor(config):
    Path('/proc/self/oom_score_adj').write_text('0')
    log = logging.getLogger('health')
    log.setLevel(logging.INFO)
    handler = RotatingFileHandler('/logs/health.log', maxBytes=2*1024*1024, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    log.addHandler(handler)
    states = {name: Recovery() for name in ('sshd', 'store', 'ddns')}
    while True:
        for name, state in states.items():
            directory = Path('/services') / name
            enabled = not (directory / 'down').exists()
            try:
                pid = int((directory / 'supervise/pid').read_text() or '0')
            except (OSError, ValueError):
                pid = 0
            healthy, error = False, None
            if enabled and pid:
                try:
                    check(name, config)
                    healthy = True
                except Exception as exc:
                    error = str(exc)
            previous_failures = state.failures
            recover = state.observe(pid, enabled, healthy, time.monotonic())
            if healthy and previous_failures:
                log.info('%s healthy again', name)
            if error and state.failures == 1:
                log.warning('%s: %s', name, error)
            if recover:
                log.warning('Restarting %s after repeated failed checks: %s', name, error)
                try:
                    result = control(name, 'restart', only_if_enabled=True)
                    log.info('%s restart result=%s', name, result)
                except Exception:
                    log.exception('%s recovery failed', name)
        time.sleep(INTERVAL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', choices=['store', 'sshd', 'ddns'])
    args = parser.parse_args()
    configuration = json.loads(Path('/config/runtime.json').read_text())
    if args.check:
        check(args.check, configuration)
    else:
        monitor(configuration)
