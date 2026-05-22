from unittest.mock import MagicMock

import pytest

from dashboard.state import BotState, get_state, reset_state


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_state()
    yield
    reset_state()


def test_get_state_returns_singleton():
    a = get_state()
    b = get_state()
    assert a is b


def test_default_state():
    s = get_state()
    snap = s.snapshot()
    assert snap["paused"] is False
    assert snap["pause_reason"] == ""
    assert snap["uptime_sec"] >= 0
    assert snap["sidecar_alive"] is False  # no adapter injected
    assert snap["weixin_attached"] is False
    assert snap["queue_depth"] == 0
    assert snap["pending_orders"] == 0


def test_pause_resume_cycle():
    s = get_state()
    assert not s.paused
    s.pause("test")
    assert s.paused
    assert s.pause_reason == "test"
    s.resume()
    assert not s.paused
    assert s.pause_reason == ""


def test_pause_default_reason():
    s = get_state()
    s.pause()
    assert s.pause_reason == "manual"


def test_snapshot_with_adapter_and_handler():
    s = get_state()
    s.wx_adapter = MagicMock()
    s.wx_adapter.is_receiving_msg.return_value = True
    s.wx_adapter._send._main = "fake-window"
    s.wx_adapter._queue.qsize.return_value = 7

    s.order_handler = MagicMock()
    s.order_handler._pending = {"a": object(), "b": object()}
    s.order_handler._daily_count = 12

    snap = s.snapshot()
    assert snap["sidecar_alive"] is True
    assert snap["weixin_attached"] is True
    assert snap["queue_depth"] == 7
    assert snap["pending_orders"] == 2
    assert snap["daily_orders"] == 12


def test_snapshot_swallows_adapter_errors():
    s = get_state()
    s.wx_adapter = MagicMock()
    s.wx_adapter.is_receiving_msg.side_effect = RuntimeError("boom")
    # Should not raise; sidecar_alive falls back to False.
    snap = s.snapshot()
    assert snap["sidecar_alive"] is False


def test_buffers_count_in_snapshot():
    s = get_state()
    s.logs.append({"x": 1})
    s.logs.append({"x": 2})
    s.messages.append({"y": 1})
    s.audit.append({"z": 1})
    snap = s.snapshot()
    assert snap["log_count"] == 2
    assert snap["message_count"] == 1
    assert snap["audit_count"] == 1
