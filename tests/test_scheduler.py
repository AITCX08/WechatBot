"""Tests for the daily report push helper (extracted from main.py scheduler)."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from main import push_daily_report_to_all
from dashboard.accounts import AccountConfig, AccountState, AccountStatus, AccountManager
from router.reporter import Reporter
from router.pricing import PricingTable


def _make_state_with_accounts(accounts: dict) -> MagicMock:
    """Build a mock state.accounts.all() returning the given list of AccountState."""
    state = MagicMock()
    state.accounts = MagicMock()
    state.accounts.all = MagicMock(return_value=list(accounts.values()))
    return state


def _make_acc(name: str, status: AccountStatus, with_adapter: bool = True) -> AccountState:
    s = AccountState(config=AccountConfig(name=name, label=name))
    s.status = status
    if with_adapter:
        s.wx_adapter = MagicMock()
    return s


@pytest.fixture
def reporter(tmp_path):
    pricing = PricingTable({"default": 5.0})
    return Reporter(audit_dir=tmp_path, pricing=pricing)


def test_push_skips_stopped_accounts(reporter):
    a = _make_acc("a", AccountStatus.STOPPED)
    b = _make_acc("b", AccountStatus.RUNNING)
    state = _make_state_with_accounts({"a": a, "b": b})

    n = push_daily_report_to_all(state, reporter)
    assert n == 1
    a.wx_adapter.send_text.assert_not_called()
    b.wx_adapter.send_text.assert_called_once()


def test_push_skips_account_without_adapter(reporter):
    a = _make_acc("a", AccountStatus.RUNNING, with_adapter=False)
    state = _make_state_with_accounts({"a": a})

    n = push_daily_report_to_all(state, reporter)
    assert n == 0


def test_push_to_all_running_accounts(reporter):
    a = _make_acc("a", AccountStatus.RUNNING)
    b = _make_acc("b", AccountStatus.RUNNING)
    c = _make_acc("c", AccountStatus.STARTING)
    state = _make_state_with_accounts({"a": a, "b": b, "c": c})

    n = push_daily_report_to_all(state, reporter)
    assert n == 2
    a.wx_adapter.send_text.assert_called_once()
    b.wx_adapter.send_text.assert_called_once()
    c.wx_adapter.send_text.assert_not_called()


def test_push_message_targets_filehelper(reporter):
    a = _make_acc("a", AccountStatus.RUNNING)
    state = _make_state_with_accounts({"a": a})

    push_daily_report_to_all(state, reporter)
    args = a.wx_adapter.send_text.call_args[0]
    assert args[1] == "filehelper"
    # Body must contain account label/name and the report header
    assert "today" in args[0].lower() or "今日" in args[0]


def test_push_continues_after_per_account_exception(reporter):
    a = _make_acc("a", AccountStatus.RUNNING)
    a.wx_adapter.send_text.side_effect = RuntimeError("boom")
    b = _make_acc("b", AccountStatus.RUNNING)
    state = _make_state_with_accounts({"a": a, "b": b})

    # Should not raise; b should still receive
    n = push_daily_report_to_all(state, reporter)
    assert n == 1
    b.wx_adapter.send_text.assert_called_once()


def test_push_uses_today_window(reporter, tmp_path):
    """Render text for a running account contains today's window label."""
    a = _make_acc("a", AccountStatus.RUNNING)
    state = _make_state_with_accounts({"a": a})

    push_daily_report_to_all(state, reporter)
    text = a.wx_adapter.send_text.call_args[0][0]
    assert "今日" in text or "today" in text.lower()


def test_push_zero_accounts(reporter):
    state = _make_state_with_accounts({})
    n = push_daily_report_to_all(state, reporter)
    assert n == 0
