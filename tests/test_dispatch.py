from unittest.mock import MagicMock
import pytest

from wx.msg import WxMsg
from router.dispatch import Dispatcher
from router.template import TemplateMatcher, TemplateAction


def make_msg(content="hi", sender="wxid_alice", roomid="", type=1, is_self=False):
    return WxMsg(
        id=1, type=type, sender=sender, roomid=roomid, content=content,
        is_self=is_self, ts=0,
    )


@pytest.fixture
def wx():
    m = MagicMock()
    m.get_self_wxid.return_value = "wxid_bot"
    return m


@pytest.fixture
def tm():
    m = MagicMock(spec=TemplateMatcher)
    m.match.return_value = []
    return m


@pytest.fixture
def order_handler():
    m = MagicMock()
    m.is_pending_for.return_value = False
    m.looks_like_order_intent.return_value = False
    return m


@pytest.fixture
def llm():
    m = MagicMock()
    m.get_answer.return_value = "LLM says hi"
    return m


@pytest.fixture
def dispatcher(wx, tm, order_handler, llm):
    return Dispatcher(
        wx=wx, template_matcher=tm, order_handler=order_handler, llm=llm,
        groups_allowed={"123@chatroom"},
    )


def test_self_messages_ignored(dispatcher, wx):
    dispatcher.handle(make_msg(is_self=True))
    wx.send_text.assert_not_called()


def test_friend_request_triggers_accept(dispatcher, wx):
    msg = make_msg(type=37, content="<msg encryptusername='v3' ticket='v4' scene='14'/>")
    dispatcher.handle(msg)
    wx.accept_new_friend.assert_called_once()


def test_template_text_action_sends(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("text", "hello back")]
    dispatcher.handle(make_msg(content="你好"))
    wx.send_text.assert_called_with("hello back", "wxid_alice")


def test_template_image_action_sends(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("image", "images/x.png")]
    dispatcher.handle(make_msg(content="菜单图"))
    wx.send_image.assert_called_with("images/x.png", "wxid_alice")


def test_group_non_at_ignored(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("text", "x")]
    dispatcher.handle(make_msg(content="hi", roomid="123@chatroom"))
    # Group messages only handled when @bot
    wx.send_text.assert_not_called()


def test_group_unconfigured_ignored(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("text", "x")]
    dispatcher.handle(make_msg(content="@WxBot hi", roomid="999@chatroom"))
    wx.send_text.assert_not_called()


def test_order_pending_routes_to_handler(dispatcher, order_handler):
    order_handler.is_pending_for.return_value = True
    dispatcher.handle(make_msg(content="确认"))
    order_handler.on_user_reply.assert_called_once()


def test_order_intent_routes_to_handler(dispatcher, order_handler):
    order_handler.looks_like_order_intent.return_value = True
    dispatcher.handle(make_msg(content="下单 北理工 学号xxx"))
    order_handler.handle_new_order_message.assert_called_once()


def test_fallback_to_llm(dispatcher, wx, llm):
    dispatcher.handle(make_msg(content="random chat"))
    llm.get_answer.assert_called_once()
    wx.send_text.assert_called()


def test_paused_state_blocks_user_messages(dispatcher, wx, llm):
    from dashboard.state import get_state, reset_state
    reset_state()
    get_state().pause("test")
    try:
        dispatcher.handle(make_msg(content="hi"))
        llm.get_answer.assert_not_called()
        wx.send_text.assert_not_called()
    finally:
        reset_state()


def test_paused_state_still_records_messages(dispatcher, wx, llm):
    from dashboard.state import get_state, reset_state
    reset_state()
    get_state().pause("test")
    try:
        dispatcher.handle(make_msg(content="should be logged"))
        msgs = get_state().messages.snapshot()
        contents = [e["content"] for _, e in msgs]
        assert "should be logged" in contents
    finally:
        reset_state()


# ===== filehelper command branch =====

def _filehelper_msg(content, sender="wxid_me", is_self=True):
    return WxMsg(
        id=99, type=1, sender=sender, roomid="", content=content,
        is_self=is_self, ts=0, receiver="filehelper",
    )


def test_filehelper_status_command_replies(dispatcher, wx):
    from dashboard.state import reset_state, get_state
    reset_state()
    dispatcher.handle(_filehelper_msg("/status"))
    wx.send_text.assert_called_once()
    text, receiver = wx.send_text.call_args[0][:2]
    assert "运行中" in text
    assert receiver == "filehelper"


def test_filehelper_pause_command_sets_global_pause(dispatcher, wx):
    from dashboard.state import reset_state, get_state
    reset_state()
    dispatcher.handle(_filehelper_msg("/pause"))
    assert get_state().paused is True
    wx.send_text.assert_called_once()
    assert "已暂停" in wx.send_text.call_args[0][0]


def test_filehelper_chinese_alias_works(dispatcher, wx):
    from dashboard.state import reset_state
    reset_state()
    dispatcher.handle(_filehelper_msg("状态"))
    wx.send_text.assert_called_once()
    assert "运行中" in wx.send_text.call_args[0][0]


def test_filehelper_unknown_slash_gets_hint(dispatcher, wx):
    from dashboard.state import reset_state
    reset_state()
    dispatcher.handle(_filehelper_msg("/nopecmd"))
    wx.send_text.assert_called_once()
    assert "未知命令" in wx.send_text.call_args[0][0]


def test_filehelper_plain_chitchat_does_nothing(dispatcher, wx, llm):
    from dashboard.state import reset_state
    reset_state()
    dispatcher.handle(_filehelper_msg("自言自语"))
    wx.send_text.assert_not_called()
    llm.get_answer.assert_not_called()


def test_security_non_self_pause_does_not_pause(dispatcher, wx):
    """Critical: a stranger DMing /pause must NOT control the bot."""
    from dashboard.state import reset_state, get_state
    reset_state()
    msg = WxMsg(
        id=1, type=1, sender="wxid_attacker", roomid="", content="/pause",
        is_self=False, ts=0, receiver="filehelper",
    )
    dispatcher.handle(msg)
    assert get_state().paused is False


def test_security_self_in_group_pause_does_not_pause(dispatcher, wx):
    """Critical: operator typing /pause in a group must NOT pause the bot."""
    from dashboard.state import reset_state, get_state
    reset_state()
    msg = WxMsg(
        id=1, type=1, sender="wxid_me", roomid="123@chatroom", content="/pause",
        is_self=True, ts=0, receiver="123@chatroom",
    )
    dispatcher.handle(msg)
    assert get_state().paused is False
    wx.send_text.assert_not_called()


def test_security_self_dm_to_someone_else_pause_does_not_pause(dispatcher, wx):
    """Critical: even self-message but to a non-filehelper contact must not trigger."""
    from dashboard.state import reset_state, get_state
    reset_state()
    msg = WxMsg(
        id=1, type=1, sender="wxid_me", roomid="", content="/pause",
        is_self=True, ts=0, receiver="wxid_friend",
    )
    dispatcher.handle(msg)
    assert get_state().paused is False
    wx.send_text.assert_not_called()
