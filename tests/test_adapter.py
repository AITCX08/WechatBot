from pathlib import Path
from queue import Empty
from unittest.mock import MagicMock

import pytest

from wx.adapter import WxAdapter
from wx.msg import WxMsg


@pytest.fixture
def adapter(monkeypatch):
    # Patch out backend constructors so __init__ doesn't try real I/O
    monkeypatch.setattr("wx.adapter.ContactsBackend", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("wx.adapter.ReceiveBackend", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("wx.adapter.SendBackend", lambda *a, **kw: MagicMock())
    return WxAdapter(
        weixin_exe=Path("C:/Program Files/Tencent/Weixin/Weixin.exe"),
        sidecar_url="http://127.0.0.1:5678",
        decrypted_db_path=Path("tests/fixtures/sample_contact.db"),
        decrypt_repo=Path("wx/sidecar/wechat-decrypt"),
    )


def test_send_text_delegates_to_send_backend(adapter):
    adapter._send.send_text.return_value = True
    rc = adapter.send_text("hello", "wxid_alice")
    adapter._send.send_text.assert_called_once_with("wxid_alice", "hello", at_wxids=())
    assert rc == 0


def test_send_text_returns_nonzero_on_failure(adapter):
    adapter._send.send_text.return_value = False
    rc = adapter.send_text("hello", "wxid_alice")
    assert rc != 0


def test_send_image_delegates(adapter):
    adapter._send.send_image.return_value = True
    rc = adapter.send_image("/tmp/x.png", "wxid_alice")
    adapter._send.send_image.assert_called_once()
    assert rc == 0


def test_get_alias_in_chatroom_delegates(adapter):
    adapter._contacts.alias_in_room.return_value = "Group Alice"
    assert adapter.get_alias_in_chatroom("wxid_alice", "123@chatroom") == "Group Alice"


def test_query_sql_contact_table_returns_list(adapter):
    adapter._contacts.all_contacts.return_value = {"wxid_alice": "Alice"}
    rows = adapter.query_sql("MicroMsg.db", "SELECT UserName, NickName FROM Contact")
    assert rows == [{"UserName": "wxid_alice", "NickName": "Alice"}]


def test_query_sql_other_raises(adapter):
    with pytest.raises(NotImplementedError):
        adapter.query_sql("MicroMsg.db", "SELECT * FROM Message")


def test_get_msg_blocks_and_returns(adapter):
    test_msg = WxMsg(
        id=1, type=1, sender="x", roomid="", content="hi",
        is_self=False, ts=0
    )
    adapter._queue.put(test_msg)
    got = adapter.get_msg(timeout=0.1)
    assert got is test_msg


def test_get_msg_raises_empty_on_timeout(adapter):
    with pytest.raises(Empty):
        adapter.get_msg(timeout=0.05)
