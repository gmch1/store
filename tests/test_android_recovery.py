"""Failure sequences that must not restart intentionally stopped services."""
from pathlib import Path
import sys


DEPLOY = Path(__file__).resolve().parents[1] / 'deploy/android'
sys.path.insert(0, str(DEPLOY))
from health import Recovery
import service_control
from install_services import prepare_ssh_config


def test_transient_failures_and_startup_do_not_restart():
    state = Recovery()
    for now in (0, 15, 30, 45, 60):
        assert not state.observe(123, True, False, now)
    assert not state.observe(123, True, True, 75)
    assert not state.observe(123, True, False, 90)
    assert not state.observe(123, True, False, 105)
    assert state.observe(123, True, False, 120)


def test_disabled_service_cannot_accumulate_failures():
    state = Recovery()
    for now in range(0, 600, 15):
        assert not state.observe(123, False, False, now)
    assert not state.observe(456, True, False, 600)
    assert not state.observe(456, True, False, 615)


def test_recovery_backoff_survives_process_replacement():
    state = Recovery()
    attempts = []
    pid = 1
    for now in range(0, 1200, 15):
        if state.observe(pid, True, False, now):
            attempts.append(now)
            pid += 1
    assert len(attempts) >= 4
    assert attempts[-1] - attempts[-2] >= 300


def test_manual_stop_wins_over_queued_health_recovery(tmp_path, monkeypatch):
    unit = tmp_path / 'store'
    unit.mkdir()
    (unit / 'down').touch()
    def must_not_start(*args, **kwargs):
        raise AssertionError('Health recovery restarted a manually stopped service')
    monkeypatch.setattr(service_control.subprocess, 'run', must_not_start)
    assert service_control.control('store', 'restart', only_if_enabled=True, services=tmp_path) == 0
    assert (unit / 'down').exists()


def test_ssh_setup_seeds_loopback_and_preserves_private_config(tmp_path):
    template = DEPLOY / 'maintenance-sshd.example.conf'
    target = tmp_path / 'sshd.conf'
    prepare_ssh_config(template, target)
    assert 'ListenAddress 127.0.0.1' in target.read_text()
    assert target.stat().st_mode & 0o777 == 0o600
    private = 'ListenAddress 192.0.2.10\nPort 2222\n'
    target.write_text(private)
    prepare_ssh_config(template, target)
    assert target.read_text() == private
