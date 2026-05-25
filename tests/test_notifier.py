import time
from unittest.mock import MagicMock

import pytest

from router.notifier import Notifier


@pytest.fixture
def wx():
    return MagicMock()


@pytest.fixture
def adapters(wx):
    return {"main": wx, "support": MagicMock()}


@pytest.fixture
def notifier(adapters):
    return Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        cooldown_sec=300,
        quiet_hours=(),
        enabled_events=None,
    )


def test_emit_unknown_account_does_not_raise(notifier):
    notifier.emit("nobody", "online", {})


def test_emit_online_sends_to_filehelper(notifier, adapters):
    notifier.emit("main", "online", {})
    adapters["main"].send_text.assert_called_once()
    text, receiver = adapters["main"].send_text.call_args[0][:2]
    assert receiver == "filehelper"
    assert "上线" in text or "online" in text.lower()


def test_emit_offline_sends(notifier, adapters):
    notifier.emit("main", "offline", {})
    adapters["main"].send_text.assert_called_once()
    assert "下线" in adapters["main"].send_text.call_args[0][0]


def test_emit_order_success_with_payload(notifier, adapters):
    notifier.emit("main", "order_success", {"kcname": "形势与政策", "wxid": "wxid_x"})
    text = adapters["main"].send_text.call_args[0][0]
    assert "形势与政策" in text
    assert "wxid_x" in text


def test_cooldown_suppresses_repeat(adapters):
    n = Notifier(adapter_lookup=lambda name: adapters.get(name), cooldown_sec=300)
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.reset_mock()
    n.emit("main", "order_success", {"kcname": "B"})
    adapters["main"].send_text.assert_not_called()


def test_cooldown_per_account_independent(adapters):
    n = Notifier(adapter_lookup=lambda name: adapters.get(name), cooldown_sec=300)
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.reset_mock()
    n.emit("support", "order_success", {"kcname": "B"})
    adapters["support"].send_text.assert_called_once()


def test_cooldown_per_event_type_independent(adapters):
    n = Notifier(adapter_lookup=lambda name: adapters.get(name), cooldown_sec=300)
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.reset_mock()
    n.emit("main", "order_failure", {"kcname": "A", "msg": "bad"})
    adapters["main"].send_text.assert_called_once()


def test_disabled_event_type_not_sent(adapters):
    n = Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        enabled_events={"online", "offline"},
    )
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.assert_not_called()


def test_critical_bypasses_quiet_hours(adapters, monkeypatch):
    n = Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        quiet_hours=(0, 23),
    )
    monkeypatch.setattr("router.notifier.time.localtime",
                        lambda *_: time.struct_time((2026, 5, 25, 3, 0, 0, 0, 0, 0)))
    n.emit("main", "error", {"msg": "boom"})
    adapters["main"].send_text.assert_called_once()


def test_info_suppressed_in_quiet_hours(adapters, monkeypatch):
    n = Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        quiet_hours=(0, 7),
    )
    monkeypatch.setattr("router.notifier.time.localtime",
                        lambda *_: time.struct_time((2026, 5, 25, 3, 0, 0, 0, 0, 0)))
    n.emit("main", "online", {})
    adapters["main"].send_text.assert_not_called()


def test_send_failure_swallowed(adapters):
    adapters["main"].send_text.side_effect = RuntimeError("send broken")
    n = Notifier(adapter_lookup=lambda name: adapters.get(name))
    n.emit("main", "online", {})
