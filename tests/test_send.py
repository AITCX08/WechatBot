from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wx.send import SendBackend


@pytest.fixture
def contacts():
    c = MagicMock()
    c.wxid_to_name.return_value = None   # default: not found
    return c


@pytest.fixture
def sb(contacts):
    return SendBackend(weixin_exe=Path("C:/x/Weixin.exe"), contacts=contacts)


# ---- _resolve_display: filehelper builtin ([0]) + @chatroom guard ([2]) ----

def test_resolve_filehelper_builtin(sb, contacts):
    # filehelper is NOT in the contact table (wxid_to_name None) but must resolve,
    # otherwise the filehelper command-reply channel is dead (review issue [0]).
    contacts.wxid_to_name.return_value = None
    assert sb._resolve_display("filehelper") == "文件传输助手"


def test_resolve_normal_contact(sb, contacts):
    contacts.wxid_to_name.return_value = "小爱"
    assert sb._resolve_display("wxid_alice") == "小爱"


def test_resolve_unknown_returns_none(sb, contacts):
    contacts.wxid_to_name.return_value = None
    assert sb._resolve_display("wxid_ghost") is None


def test_resolve_raw_chatroom_id_rejected(sb, contacts):
    # group with no remark/nick_name falls back to the raw 'xxx@chatroom' id,
    # which is NOT a searchable conversation label — must be rejected (issue [2]).
    contacts.wxid_to_name.return_value = "123@chatroom"
    assert sb._resolve_display("123@chatroom") is None


def test_resolve_named_group_ok(sb, contacts):
    contacts.wxid_to_name.return_value = "项目群"
    assert sb._resolve_display("123@chatroom") == "项目群"


# ---- send_text end-to-end: filehelper reply MUST succeed ([0]) ----

def test_send_text_to_filehelper_succeeds(sb, contacts, monkeypatch):
    contacts.wxid_to_name.return_value = None   # filehelper not in contacts
    opened = []
    monkeypatch.setattr(sb, "_throttle", lambda: None)
    monkeypatch.setattr(sb, "_open_chat", lambda d: opened.append(d))
    monkeypatch.setattr(sb, "_focus_input", lambda: None)
    monkeypatch.setattr(sb, "_paste_and_send", lambda t: None)
    ok = sb.send_text("filehelper", "✅ 运行中")
    assert ok is True
    assert opened == ["文件传输助手"]


def test_send_text_unknown_recipient_fails(sb, contacts, monkeypatch):
    contacts.wxid_to_name.return_value = None
    monkeypatch.setattr(sb, "_throttle", lambda: None)
    called = []
    monkeypatch.setattr(sb, "_open_chat", lambda d: called.append(d))
    ok = sb.send_text("wxid_ghost", "hi")
    assert ok is False
    assert called == []   # must never try to open a chat for an unresolved name


def test_send_text_raw_chatroom_fails(sb, contacts, monkeypatch):
    contacts.wxid_to_name.return_value = "999@chatroom"
    monkeypatch.setattr(sb, "_throttle", lambda: None)
    called = []
    monkeypatch.setattr(sb, "_open_chat", lambda d: called.append(d))
    ok = sb.send_text("999@chatroom", "hi")
    assert ok is False
    assert called == []   # raw @chatroom id must not be pasted into the search box


# ---- _pick_input_edit: never select the search box ([4]) ----

class _FakeCtrl:
    def __init__(self, name):
        self.Name = name


def test_pick_input_excludes_search_box(sb):
    search = _FakeCtrl("搜索")
    inp = _FakeCtrl("")
    # search box must never be chosen even if it appears last
    assert sb._pick_input_edit([inp, search]) is inp


def test_pick_input_bottom_most_when_no_search(sb):
    a = _FakeCtrl("")
    b = _FakeCtrl("")
    assert sb._pick_input_edit([a, b]) is b


def test_pick_input_empty_returns_none(sb):
    assert sb._pick_input_edit([]) is None
