import time
from unittest.mock import MagicMock

import pytest

from dashboard.accounts import AccountConfig, AccountManager, AccountStatus


def _cfg(name="x", label=""):
    return AccountConfig(name=name, label=label or name,
                         exe="C:/fake/Weixin.exe",
                         sidecar_url="http://127.0.0.1:5678")


def test_register_returns_state():
    m = AccountManager()
    s = m.register(_cfg("alice"))
    assert s.name == "alice"
    assert s.status == AccountStatus.STOPPED


def test_register_idempotent():
    m = AccountManager()
    s1 = m.register(_cfg("alice"))
    s2 = m.register(_cfg("alice"))
    assert s1 is s2


def test_names_and_all():
    m = AccountManager()
    m.register(_cfg("a"))
    m.register(_cfg("b"))
    assert set(m.names()) == {"a", "b"}
    assert len(m.all()) == 2


def test_start_without_factory_fails():
    m = AccountManager()
    m.register(_cfg("a"))
    ok, msg = m.start("a")
    assert ok is False
    assert "factory" in msg


def test_start_unknown_account():
    m = AccountManager()
    ok, msg = m.start("nobody")
    assert ok is False
    assert "unknown" in msg


def test_start_runs_factory_in_background():
    m = AccountManager()
    state = m.register(_cfg("a"))

    wx_mock = MagicMock()
    robot_mock = MagicMock()
    oh_mock = MagicMock()

    def fac(cfg, st):
        time.sleep(0.05)  # simulate work
        return (wx_mock, robot_mock, oh_mock)

    m.set_factory(fac)
    ok, msg = m.start("a")
    assert ok is True

    # Wait for background thread
    for _ in range(20):
        if state.status == AccountStatus.RUNNING:
            break
        time.sleep(0.05)
    assert state.status == AccountStatus.RUNNING
    assert state.wx_adapter is wx_mock
    assert state.robot is robot_mock
    assert state.order_handler is oh_mock
    assert state.started_at > 0


def test_start_factory_failure_sets_error():
    m = AccountManager()
    state = m.register(_cfg("a"))

    def fac(cfg, st):
        raise RuntimeError("boom")

    m.set_factory(fac)
    m.start("a")
    for _ in range(20):
        if state.status == AccountStatus.ERROR:
            break
        time.sleep(0.05)
    assert state.status == AccountStatus.ERROR
    assert "boom" in state.last_error


def test_start_already_running_returns_ok():
    m = AccountManager()
    state = m.register(_cfg("a"))
    state.status = AccountStatus.RUNNING
    m.set_factory(lambda *a: (None, None, None))
    ok, msg = m.start("a")
    assert ok is True
    assert "running" in msg.lower() or "starting" in msg.lower()


def test_stop_calls_cleanup():
    m = AccountManager()
    state = m.register(_cfg("a"))
    wx_mock = MagicMock()
    state.wx_adapter = wx_mock
    state.status = AccountStatus.RUNNING
    state.started_at = time.time()

    m.stop("a")
    for _ in range(20):
        if state.status == AccountStatus.STOPPED:
            break
        time.sleep(0.05)
    wx_mock.cleanup.assert_called_once()
    assert state.status == AccountStatus.STOPPED
    assert state.wx_adapter is None
    assert state.started_at == 0


def test_pause_and_resume():
    m = AccountManager()
    state = m.register(_cfg("a"))
    ok, _ = m.pause("a", reason="test")
    assert ok is True
    assert state.paused is True
    assert state.pause_reason == "test"

    ok, _ = m.resume("a")
    assert ok is True
    assert state.paused is False
    assert state.pause_reason == ""


def test_snapshot_all_returns_list():
    m = AccountManager()
    m.register(_cfg("a", "Account A"))
    m.register(_cfg("b", "Account B"))
    snaps = m.snapshot_all()
    assert len(snaps) == 2
    assert any(s["name"] == "a" and s["label"] == "Account A" for s in snaps)
    assert all(s["status"] == "stopped" for s in snaps)


def test_factory_registered_property():
    m = AccountManager()
    assert m.factory_registered is False
    m.set_factory(lambda c, s: (None, None, None))
    assert m.factory_registered is True


def test_on_status_change_fires_on_start():
    import time as _t
    m = AccountManager()
    state = m.register(_cfg("a"))
    seen = []
    m.set_on_status_change(lambda name, status: seen.append((name, status.value)))

    def fac(cfg, st): return (MagicMock(), MagicMock(), MagicMock())
    m.set_factory(fac)
    m.start("a")
    for _ in range(20):
        if seen:
            break
        _t.sleep(0.05)
    assert ("a", "running") in seen


def test_on_status_change_fires_on_stop():
    import time as _t
    m = AccountManager()
    state = m.register(_cfg("a"))
    state.status = AccountStatus.RUNNING
    state.wx_adapter = MagicMock()
    seen = []
    m.set_on_status_change(lambda name, status: seen.append((name, status.value)))
    m.stop("a")
    for _ in range(20):
        if seen:
            break
        _t.sleep(0.05)
    assert ("a", "stopped") in seen
