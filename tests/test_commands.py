from unittest.mock import MagicMock

import pytest

from wx.msg import WxMsg
from router.commands import (
    CommandContext, CommandRegistry,
    build_default_registry, try_handle_filehelper_command,
    cmd_status, cmd_pause, cmd_resume, cmd_help,
)


def make_filehelper_msg(content: str, sender: str = "wxid_me") -> WxMsg:
    return WxMsg(
        id=1, type=1, sender=sender, roomid="", content=content,
        is_self=True, ts=0, receiver="filehelper",
    )


@pytest.fixture
def ctx():
    """Build a CommandContext with mocked wx_adapter + real BotState."""
    from dashboard.state import get_state, reset_state
    reset_state()
    state = get_state()
    wx = MagicMock()
    return CommandContext(wx_adapter=wx, state=state, account_state=None)


# ----- registry -----

def test_registry_register_and_lookup_slash():
    r = CommandRegistry()
    r.register("/foo", lambda c, a: "FOO")
    handler, args = r.lookup("/foo")
    assert handler is not None
    assert args == ""


def test_registry_lookup_with_args():
    r = CommandRegistry()
    r.register("/foo", lambda c, a: f"FOO:{a}")
    handler, args = r.lookup("/foo  bar baz")
    assert args == "bar baz"


def test_registry_alias_maps_to_slash():
    r = CommandRegistry()
    r.register("/foo", lambda c, a: "FOO", aliases=["弗欧"])
    handler, args = r.lookup("弗欧")
    assert handler is not None


def test_registry_unknown_slash_returns_none():
    r = CommandRegistry()
    assert r.lookup("/never") is None


def test_registry_non_command_text_returns_none():
    r = CommandRegistry()
    r.register("/foo", lambda c, a: "ok")
    assert r.lookup("just some chitchat") is None


def test_registry_strips_whitespace():
    r = CommandRegistry()
    r.register("/foo", lambda c, a: "ok")
    handler, args = r.lookup("  /foo  ")
    assert handler is not None


# ----- handlers -----

def test_status_handler_returns_running_text(ctx):
    out = cmd_status(ctx, "")
    assert "运行中" in out


def test_status_handler_shows_paused_when_paused(ctx):
    ctx.state.pause("manual")
    out = cmd_status(ctx, "")
    assert "已暂停" in out


def test_pause_handler_sets_state(ctx):
    out = cmd_pause(ctx, "")
    assert "已暂停" in out
    assert ctx.state.paused is True


def test_resume_handler_clears_state(ctx):
    ctx.state.pause("test")
    out = cmd_resume(ctx, "")
    assert "已恢复" in out
    assert ctx.state.paused is False


def test_help_handler_lists_commands(ctx):
    out = cmd_help(ctx, "")
    assert "/status" in out
    assert "/pause" in out
    assert "/resume" in out
    assert "/help" in out
    # Includes Chinese alias for usability:
    assert "状态" in out


# ----- entry point -----

def test_try_handle_recognizes_slash_command(ctx):
    reg = build_default_registry()
    msg = make_filehelper_msg("/status")
    handled = try_handle_filehelper_command(msg, ctx, reg)
    assert handled is True
    ctx.wx_adapter.send_text.assert_called_once()
    call_args = ctx.wx_adapter.send_text.call_args
    sent_text = call_args[0][0]
    receiver = call_args[0][1]
    assert "运行中" in sent_text
    assert receiver == "filehelper"


def test_try_handle_recognizes_chinese_alias(ctx):
    reg = build_default_registry()
    msg = make_filehelper_msg("状态")
    handled = try_handle_filehelper_command(msg, ctx, reg)
    assert handled is True
    ctx.wx_adapter.send_text.assert_called_once()
    assert "运行中" in ctx.wx_adapter.send_text.call_args[0][0]


def test_try_handle_unknown_slash_replies_with_hint(ctx):
    reg = build_default_registry()
    msg = make_filehelper_msg("/xyz_no_such_cmd")
    handled = try_handle_filehelper_command(msg, ctx, reg)
    assert handled is True
    ctx.wx_adapter.send_text.assert_called_once()
    assert "未知命令" in ctx.wx_adapter.send_text.call_args[0][0]


def test_try_handle_plain_chitchat_returns_false(ctx):
    reg = build_default_registry()
    msg = make_filehelper_msg("just talking to myself")
    handled = try_handle_filehelper_command(msg, ctx, reg)
    assert handled is False
    ctx.wx_adapter.send_text.assert_not_called()


def test_try_handle_non_filehelper_returns_false(ctx):
    reg = build_default_registry()
    msg = WxMsg(
        id=1, type=1, sender="wxid_me", roomid="", content="/pause",
        is_self=True, ts=0, receiver="wxid_someone_else",
    )
    handled = try_handle_filehelper_command(msg, ctx, reg)
    assert handled is False
    ctx.wx_adapter.send_text.assert_not_called()


def test_try_handle_non_self_returns_false(ctx):
    reg = build_default_registry()
    msg = WxMsg(
        id=1, type=1, sender="wxid_other", roomid="", content="/pause",
        is_self=False, ts=0, receiver="filehelper",
    )
    handled = try_handle_filehelper_command(msg, ctx, reg)
    assert handled is False
    ctx.wx_adapter.send_text.assert_not_called()


def test_try_handle_handler_exception_replies_with_error(ctx):
    reg = CommandRegistry()
    def boom(c, a):
        raise RuntimeError("kaboom")
    reg.register("/boom", boom)
    msg = make_filehelper_msg("/boom")
    handled = try_handle_filehelper_command(msg, ctx, reg)
    assert handled is True
    ctx.wx_adapter.send_text.assert_called_once()
    assert "执行失败" in ctx.wx_adapter.send_text.call_args[0][0]
    assert "kaboom" in ctx.wx_adapter.send_text.call_args[0][0]
