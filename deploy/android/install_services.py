"""Prepare runit and maintenance SSH inside the existing phone chroot.

Requires Debian openssh-server and runit. Does not stop or start live daemons.
Existing runit down markers and operational SSH credentials are preserved.
"""
from pathlib import Path
import os
import shutil
import subprocess


SOURCE = Path('/app/deploy/android')
ANDROID = Path('/proc/1/root')
SSH = ANDROID / 'data/adb/ming-sshd'


def prepare_ssh_config(source, target):
    """Seed a new deployment without overwriting its private interface or policy."""
    if not target.exists():
        with target.open('x') as output:
            output.write(source.read_text())
        target.chmod(0o600)


def main():
    os.umask(0o077)
    SSH.mkdir(exist_ok=True, mode=0o700)
    (SSH / 'home').mkdir(exist_ok=True, mode=0o700)
    termux = ANDROID / 'data/data/com.termux/files'
    for name, source in {
        'authorized_keys': termux / 'home/.ssh/authorized_keys',
        'ssh_host_ed25519_key': termux / 'usr/etc/ssh/ssh_host_ed25519_key',
        'ssh_host_ed25519_key.pub': termux / 'usr/etc/ssh/ssh_host_ed25519_key.pub',
    }.items():
        target = SSH / name
        if not target.exists():
            shutil.copyfile(source, target)
            target.chmod(0o600)
    shutil.copyfile(SOURCE / 'ssh-control.sh', SSH / 'control.sh')
    (SSH / 'control.sh').chmod(0o700)
    shutil.copyfile(SOURCE / 'login-shell', SSH / 'login-shell')
    (SSH / 'login-shell').chmod(0o700)
    prepare_ssh_config(SOURCE / 'maintenance-sshd.example.conf', Path('/config/maintenance-sshd.conf'))
    passwd = Path('/etc/passwd')
    if not Path('/etc/passwd.before-maintenance-ssh').exists():
        shutil.copyfile(passwd, '/etc/passwd.before-maintenance-ssh')
    lines = passwd.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith('root:'):
            fields = line.split(':')
            fields[-2:] = ['/data/adb/ming-sshd/home', '/proc/1/root/data/adb/ming-sshd/login-shell']
            lines[index] = ':'.join(fields)
    passwd.write_text('\n'.join(lines) + '\n')
    passwd.chmod(0o644)
    Path('/run/sshd').mkdir(exist_ok=True, mode=0o755)
    Path('/services').mkdir(exist_ok=True, mode=0o700)
    for source in (SOURCE / 'services').iterdir():
        unit = Path('/services') / source.name
        fresh = not unit.exists()
        unit.mkdir(exist_ok=True, mode=0o700)
        for script in source.iterdir():
            target = unit / script.name
            shutil.copyfile(script, target)
            target.chmod(0o700)
        # Deploy first, explicitly activate after validating the staged SSH daemon.
        if fresh:
            (unit / 'down').touch()
        (unit / 'log').mkdir(exist_ok=True, mode=0o700)
        logs = Path('/logs') / ('runit-' + source.name)
        logs.mkdir(exist_ok=True, mode=0o700)
        (logs / 'config').write_text('s2097152\nn2\n')
        log_script = unit / 'log/run'
        log_script.write_text(f'#!/bin/sh\nexec svlogd -tt {logs}\n')
        log_script.chmod(0o700)
    subprocess.run(['/usr/sbin/sshd', '-t', '-f', '/config/maintenance-sshd.conf'], check=True)
    print('SSH configuration and disabled runit services prepared')


if __name__ == '__main__':
    main()
