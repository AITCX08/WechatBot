import pytest
from wx.msg import WxMsg


def make_msg(**overrides):
    base = dict(
        id=1, type=1, sender="wxid_alice", roomid="", content="hello",
        is_self=False, ts=1700000000
    )
    base.update(overrides)
    return WxMsg(**base)


def test_from_group_true_when_roomid_set():
    m = make_msg(roomid="123@chatroom")
    assert m.from_group() is True


def test_from_group_false_when_roomid_empty():
    m = make_msg(roomid="")
    assert m.from_group() is False


def test_from_self_true():
    m = make_msg(is_self=True)
    assert m.from_self() is True


def test_is_at_detects_at_token():
    m = make_msg(content="@WxBot hello there", roomid="123@chatroom")
    assert m.is_at("wxid_bot") is True


def test_is_at_false_when_no_at():
    m = make_msg(content="just chatting", roomid="123@chatroom")
    assert m.is_at("wxid_bot") is False


def test_is_at_false_in_dm():
    m = make_msg(content="@bot", roomid="")
    assert m.is_at("wxid_bot") is False


def test_receiver_defaults_to_empty():
    m = make_msg()
    assert m.receiver == ""


def test_receiver_can_be_set():
    m = make_msg(receiver="filehelper")
    assert m.receiver == "filehelper"
