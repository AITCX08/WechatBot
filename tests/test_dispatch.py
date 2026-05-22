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
