import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wx.msg import WxMsg
from router.order import OrderHandler


def make_msg(content, sender="wxid_alice"):
    return WxMsg(
        id=1, type=1, sender=sender, roomid="", content=content,
        is_self=False, ts=int(time.time()),
    )


@pytest.fixture
def lexue_creds():
    return {"user": "1492246", "pass": "xxx", "url": "http://lxuexi.cn/"}


@pytest.fixture
def llm():
    return MagicMock()


@pytest.fixture
def wx():
    return MagicMock()


@pytest.fixture
def safety():
    return {
        "dry_run": True,
        "confirm_timeout_sec": 300,
        "max_extract_rounds": 3,
        "daily_limit": 50,
        "per_user_cooldown_sec": 0,
    }


@pytest.fixture
def handler(tmp_path, lexue_creds, safety, llm, wx):
    return OrderHandler(
        lexue_creds=lexue_creds,
        llm=llm,
        wx=wx,
        safety=safety,
        audit_log_path=tmp_path / "orders.jsonl",
        intent_prompt="判断是否下单意图: {message}",
        extract_prompt="提取字段: history={history} message={message}",
    )


def test_intent_classifier_true(handler, llm):
    llm.get_answer.return_value = '{"is_order_intent": true, "confidence": 0.9, "reason": "ok"}'
    assert handler.looks_like_order_intent("下单 北理工 学号x") is True


def test_intent_classifier_false(handler, llm):
    llm.get_answer.return_value = '{"is_order_intent": false, "confidence": 0.95, "reason": "chitchat"}'
    assert handler.looks_like_order_intent("你好") is False


def test_intent_classifier_malformed_treated_as_false(handler, llm):
    llm.get_answer.return_value = "not json"
    assert handler.looks_like_order_intent("???") is False


def test_extract_complete_draft_requests_confirmation(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": "北理工", "user": "18543", "password": "wjx",
        "platform": "1736", "kcid": "40", "kcname": "形势与政策",
        "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单 北理工 学号18543 密码wjx 平台1736 课程40 形势与政策"))
    # Bot should have asked for confirmation
    wx.send_text.assert_called_once()
    assert "确认下单" in wx.send_text.call_args[0][0]
    # Draft must be pending
    assert handler.is_pending_for("wxid_alice")


def test_extract_incomplete_asks_for_missing(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": "北理工", "user": None, "password": None,
        "platform": None, "kcid": None, "kcname": None,
        "missing": ["user", "password", "platform", "kcid", "kcname"],
    })
    handler.handle_new_order_message(make_msg("我想下单"))
    wx.send_text.assert_called_once()
    asked = wx.send_text.call_args[0][0]
    assert "user" in asked or "学号" in asked or "账号" in asked
    assert handler.is_pending_for("wxid_alice")


def test_on_user_reply_confirm_triggers_place_order_in_dry_run(handler, llm, wx, tmp_path):
    # Seed: pending draft with complete fields
    llm.get_answer.return_value = json.dumps({
        "school": "北理工", "user": "18543", "password": "wjx",
        "platform": "1736", "kcid": "40", "kcname": "形势与政策",
        "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单"))
    wx.send_text.reset_mock()
    # User replies '确认'
    handler.on_user_reply(make_msg("确认"))
    # In dry_run, place_order writes audit + replies success; does NOT call lexue
    wx.send_text.assert_called()
    assert "下单成功" in wx.send_text.call_args[0][0] or "dry_run" in wx.send_text.call_args[0][0]
    # Pending draft is cleared
    assert not handler.is_pending_for("wxid_alice")
    # Audit log has one line
    audit_path = handler.audit_log_path
    assert audit_path.exists()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1


def test_on_user_reply_cancel_drops_draft(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": "x", "user": "y", "password": "z",
        "platform": "1", "kcid": "2", "kcname": "k", "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单"))
    wx.send_text.reset_mock()
    handler.on_user_reply(make_msg("取消"))
    assert not handler.is_pending_for("wxid_alice")
    assert any("取消" in c[0][0] or "放弃" in c[0][0] for c in wx.send_text.call_args_list)


def test_max_extract_rounds_aborts(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": None, "user": None, "password": None,
        "platform": None, "kcid": None, "kcname": None,
        "missing": ["school", "user", "password", "platform", "kcid", "kcname"],
    })
    handler.handle_new_order_message(make_msg("下单"))
    handler.on_user_reply(make_msg("还是没说全"))
    handler.on_user_reply(make_msg("继续没说全"))
    handler.on_user_reply(make_msg("依然没说全"))   # 3rd reply → extract_rounds reaches 3 → abort
    # Final state: pending dropped, escalation message sent
    assert not handler.is_pending_for("wxid_alice")


def test_audit_calls_notifier_on_place_dry_run(handler, llm, wx):
    """OrderHandler with notifier attached should emit order_dry_run event."""
    notif = MagicMock()
    handler.notifier = notif
    handler.account_name = "main"
    llm.get_answer.return_value = json.dumps({
        "school": "x", "user": "u", "password": "p",
        "platform": "1736", "kcid": "40", "kcname": "形势与政策",
        "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单"))
    handler.on_user_reply(make_msg("确认"))
    emitted = [c[0] for c in notif.emit.call_args_list]
    assert any(c[1] == "order_dry_run" for c in emitted), f"expected order_dry_run in {emitted}"
    # Check that account_name is the first arg
    dry_run_call = next(c for c in emitted if c[1] == "order_dry_run")
    assert dry_run_call[0] == "main"


def test_audit_calls_notifier_on_cancel_does_NOT_emit(handler, llm, wx):
    """Cancel events are not in the mapping; should not call notifier."""
    notif = MagicMock()
    handler.notifier = notif
    handler.account_name = "main"
    llm.get_answer.return_value = json.dumps({
        "school": "x", "user": "u", "password": "p",
        "platform": "1736", "kcid": "40", "kcname": "k",
        "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单"))
    handler.on_user_reply(make_msg("取消"))
    emitted_events = [c[0][1] for c in notif.emit.call_args_list]
    assert "order_success" not in emitted_events
    assert "order_dry_run" not in emitted_events
    # (cancel just writes an audit row with event="cancel" which isn't in the mapping)
