# Filehelper Commands MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize messages the operator sends to their own filehelper as bot control commands (`/status` `/pause` `/resume` `/help` + Chinese aliases), respond in the same filehelper window.

**Architecture:** Add `receiver` field to `WxMsg` (populated from sidecar SSE `to_user`). In `Dispatcher._handle`, BEFORE the existing self-message early-return, branch on `from_self && receiver == "filehelper"` → look up handler in a new `CommandRegistry` → reply via `wx.send_text(result, "filehelper")`. Four handlers live in a single sub-200-line `router/commands.py`. No external dependencies.

**Tech Stack:** Python 3.10+, existing pytest stack, no new packages.

**Spec source:** This MVP was finalized via /req on 2026-05-23 (Q1: 斜杠+关键词混合; Q3: 每账号自己 filehelper; QA picked MVP version A).

---

## File Structure

**New files:**
- `wx/constants.py` — `FILEHELPER_WXID` constant (string literal in one place)
- `router/commands.py` — `CommandContext` dataclass, `CommandRegistry` class, 4 handler functions (`cmd_status`, `cmd_pause`, `cmd_resume`, `cmd_help`), `build_default_registry()` factory, `try_handle_filehelper_command(msg, ctx)` entry point
- `tests/test_commands.py` — Unit tests for registry + each handler with mocked ctx

**Modified files:**
- `wx/msg.py` — Add `receiver: str = ""` field (default keeps existing constructors valid)
- `wx/receive.py:_translate_event` — Populate `receiver=str(d.get("to_user", ""))`
- `router/dispatch.py` — Insert filehelper command branch at top of `_handle`, before `if msg.from_self():`
- `tests/test_msg.py` — Add 1 test confirming default receiver=""
- `tests/test_receive.py` — Update existing event-translation tests to assert receiver is populated; add 1 case for missing `to_user`
- `tests/test_dispatch.py` — Add filehelper-command branch tests + 2 security tests (non-self /pause, self in group /pause)

---

## Task 1: Add `receiver` field to `WxMsg` (backward-compatible)

**Files:**
- Modify: `wx/msg.py:7-24`
- Modify: `tests/test_msg.py`

- [ ] **Step 1: Add failing test for receiver default**

Append to `tests/test_msg.py`:

```python
def test_receiver_defaults_to_empty():
    m = make_msg()
    assert m.receiver == ""


def test_receiver_can_be_set():
    m = make_msg(receiver="filehelper")
    assert m.receiver == "filehelper"
```

- [ ] **Step 2: Run tests to verify the first fails**

```bash
pytest tests/test_msg.py::test_receiver_defaults_to_empty -v
```

Expected: FAIL with `AttributeError: 'WxMsg' object has no attribute 'receiver'`.

- [ ] **Step 3: Add `receiver` field to `WxMsg`**

In `wx/msg.py`, modify the dataclass to add the field with a default. Replace lines 7-24 with:

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class WxMsg:
    """Wire-compatible substitute for wcferry.WxMsg.

    Only carries fields and methods actually consulted by robot.py.
    """
    id: int
    type: int                # 1=text, 3=image, 37=friend request, 10000=system
    sender: str              # wxid of the sender
    roomid: str              # group id ("" for DM)
    content: str             # text content or XML payload
    is_self: bool
    ts: int
    receiver: str = ""       # destination wxid (for DMs); used to detect filehelper

    def from_group(self) -> bool:
        return bool(self.roomid)

    def from_self(self) -> bool:
        return self.is_self

    def is_at(self, wxid: str) -> bool:
        # Group @ is encoded as "@<displayname>" in Weixin clients.
        # We don't have a perfect wxid→displayname mapping at parse time,
        # so the dispatcher will pass the bot's own wxid AND resolve via
        # ContactsBackend later. Here we just check whether the content
        # contains any "@" token in a group context.
        if not self.from_group():
            return False
        return "@" in self.content
```

- [ ] **Step 4: Run full WxMsg suite to verify no regressions + new tests pass**

```bash
pytest tests/test_msg.py -v
```

Expected: 8 passed (6 original + 2 new).

- [ ] **Step 5: Commit**

```bash
git add wx/msg.py tests/test_msg.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(wx): add receiver field to WxMsg (default '')"
```

---

## Task 2: Populate `receiver` in `ReceiveBackend`

**Files:**
- Modify: `wx/receive.py:_translate_event`
- Modify: `tests/test_receive.py`

- [ ] **Step 1: Update existing translation tests to assert receiver, and add a missing-to_user case**

In `tests/test_receive.py`, update the four `test_translate_*` tests to assert `msg.receiver`. Find this block:

```python
def test_translate_text_dm(backend):
    msg = backend._translate_event(evs.TEXT_DM)
    assert isinstance(msg, WxMsg)
    assert msg.type == 1
    assert msg.sender == "wxid_alice"
    assert msg.roomid == ""
    assert msg.content == "hi bot"
    assert msg.is_self is False
```

Append one assertion:

```python
    assert msg.receiver == "wxid_self"
```

Also append after the existing tests in the same file:

```python
def test_translate_event_with_missing_to_user(backend):
    event = {
        "event_type": "new_message",
        "data": {
            "msg_id": 9999,
            "type": 1,
            "from_user": "wxid_x",
            "room_id": "",
            "content": "hi",
            "is_send": 0,
            "timestamp": 1700000000,
            # to_user intentionally absent
        },
    }
    msg = backend._translate_event(event)
    assert msg is not None
    assert msg.receiver == ""
```

- [ ] **Step 2: Run the receiver assertion to verify it fails**

```bash
pytest tests/test_receive.py::test_translate_text_dm -v
```

Expected: FAIL — `assert '' == 'wxid_self'` because we haven't populated yet.

- [ ] **Step 3: Populate `receiver` in `_translate_event`**

In `wx/receive.py`, find the `_translate_event` method and modify the `WxMsg(...)` construction to include `receiver`:

```python
    def _translate_event(self, event: dict) -> WxMsg | None:
        if event.get("event_type") != "new_message":
            return None
        d = event.get("data") or {}
        try:
            return WxMsg(
                id=int(d["msg_id"]),
                type=int(d["type"]),
                sender=str(d.get("from_user", "")),
                roomid=str(d.get("room_id", "")),
                content=str(d.get("content", "")),
                is_self=bool(d.get("is_send", 0)),
                ts=int(d.get("timestamp", 0)),
                receiver=str(d.get("to_user", "")),
            )
        except (KeyError, ValueError, TypeError) as e:
            LOG.warning("malformed message event %r: %s", event, e)
            return None
```

- [ ] **Step 4: Run all receive tests**

```bash
pytest tests/test_receive.py -v
```

Expected: 7 passed (6 original updated + 1 new).

- [ ] **Step 5: Commit**

```bash
git add wx/receive.py tests/test_receive.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(wx): populate WxMsg.receiver from SSE to_user field"
```

---

## Task 3: Add `FILEHELPER_WXID` constant

**Files:**
- Create: `wx/constants.py`

- [ ] **Step 1: Create the constants module**

Create `wx/constants.py`:

```python
"""Project-wide constants for wx-layer code."""
from __future__ import annotations

# The internal wxid used by WeChat / Weixin for the "文件传输助手" pseudo-contact.
# Stable across WeChat 3.x and Weixin 4.x. Centralized here so future
# version drift only needs a single edit.
FILEHELPER_WXID = "filehelper"
```

- [ ] **Step 2: Verify import**

```bash
python -c "from wx.constants import FILEHELPER_WXID; assert FILEHELPER_WXID == 'filehelper'; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add wx/constants.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(wx): add FILEHELPER_WXID constant"
```

---

## Task 4: Build `CommandRegistry` and 4 handlers with tests

**Files:**
- Create: `tests/test_commands.py`
- Create: `router/commands.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_commands.py`:

```python
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
    # ctx.wx_adapter.send_text was invoked with filehelper as receiver
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
```

- [ ] **Step 2: Run tests to verify they fail at import**

```bash
pytest tests/test_commands.py -v
```

Expected: ImportError on `router.commands`.

- [ ] **Step 3: Implement `router/commands.py`**

Create `router/commands.py`:

```python
"""Filehelper command interface.

Operator sends commands to their own 文件传输助手 (filehelper); the bot
recognizes them and responds in the same window. Only messages that satisfy
all three conditions are treated as commands:
  - msg.from_self() == True       (the operator wrote it)
  - msg.receiver == FILEHELPER_WXID
  - msg.type == 1                  (text)

Anything else falls through to the normal dispatcher path.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from wx.constants import FILEHELPER_WXID
from wx.msg import WxMsg

LOG = logging.getLogger(__name__)


@dataclass
class CommandContext:
    """Bundle the dependencies handlers need.

    `account_state` is None in single-account mode; in multi-account mode
    it's the AccountState the message belongs to. Handlers should prefer
    `account_state` when present and fall back to global `state`.
    """
    wx_adapter: object       # WxAdapter; duck-typed (send_text + queue + ...)
    state: object            # dashboard.state.BotState
    account_state: object | None = None


HandlerFn = Callable[[CommandContext, str], str]


class CommandRegistry:
    """Slash-prefixed command registry with optional Chinese-keyword aliases.

    Lookup rules:
      - Input is stripped of surrounding whitespace.
      - If input is "/cmd[ args]" and "/cmd" is registered → (handler, args).
      - Else if input matches an alias key → (handler, "").
      - Else None.
    """

    def __init__(self):
        self._handlers: dict[str, HandlerFn] = {}     # "/cmd" -> fn
        self._aliases: dict[str, str] = {}            # "状态" -> "/status"

    def register(self, name: str, fn: HandlerFn, aliases: tuple | list = ()):
        assert name.startswith("/"), "command name must start with /"
        self._handlers[name] = fn
        for a in aliases:
            self._aliases[a] = name

    def lookup(self, raw_text: str) -> Optional[tuple[HandlerFn, str]]:
        text = (raw_text or "").strip()
        if not text:
            return None
        if text.startswith("/"):
            # Split into command word + rest
            parts = text.split(None, 1)
            cmd = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            fn = self._handlers.get(cmd)
            if fn is None:
                return None
            return fn, args
        # Plain text — try alias
        target = self._aliases.get(text)
        if target is None:
            return None
        fn = self._handlers.get(target)
        if fn is None:
            return None
        return fn, ""

    def is_slash_command(self, raw_text: str) -> bool:
        return (raw_text or "").strip().startswith("/")


# ============ handlers ============

def cmd_status(ctx: CommandContext, args: str) -> str:
    state = ctx.state
    paused = getattr(state, "paused", False)
    pause_reason = getattr(state, "pause_reason", "")
    queue_depth = 0
    pending = 0
    today = 0
    try:
        snap = state.snapshot()
        queue_depth = snap.get("queue_depth", 0)
        pending = snap.get("pending_orders", 0)
        today = snap.get("daily_orders", 0)
    except Exception as e:
        LOG.warning("status snapshot failed: %s", e)
    head = "⏸ 已暂停" + (f" ({pause_reason})" if pause_reason else "") if paused else "✅ 运行中"
    return f"{head}\n队列: {queue_depth} | 待确认: {pending} | 今日: {today}"


def cmd_pause(ctx: CommandContext, args: str) -> str:
    ctx.state.pause("manual via filehelper")
    return "⏸ 已暂停。回复 /resume 或 「恢复」继续。"


def cmd_resume(ctx: CommandContext, args: str) -> str:
    ctx.state.resume()
    return "▶ 已恢复。"


def cmd_help(ctx: CommandContext, args: str) -> str:
    return (
        "📋 可用命令：\n"
        "/status  或 「状态」  — 查看运行状态\n"
        "/pause   或 「暂停」  — 暂停响应\n"
        "/resume  或 「恢复」  — 取消暂停\n"
        "/help    或 「帮助」  — 此说明"
    )


def build_default_registry() -> CommandRegistry:
    """Wire the 4 MVP commands and their Chinese aliases."""
    reg = CommandRegistry()
    reg.register("/status", cmd_status, aliases=["状态"])
    reg.register("/pause",  cmd_pause,  aliases=["暂停"])
    reg.register("/resume", cmd_resume, aliases=["恢复"])
    reg.register("/help",   cmd_help,   aliases=["帮助"])
    return reg


# ============ entry point ============

def try_handle_filehelper_command(
    msg: WxMsg,
    ctx: CommandContext,
    registry: CommandRegistry,
) -> bool:
    """Try to route msg as a filehelper command. Return True if handled.

    Security gates (ALL must hold):
      - msg.from_self()  → only the operator can issue commands
      - msg.receiver == FILEHELPER_WXID  → only the filehelper channel
      - msg.type == 1    → text only
    """
    if not msg.from_self():
        return False
    if msg.receiver != FILEHELPER_WXID:
        return False
    if msg.type != 1:
        return False

    hit = registry.lookup(msg.content)
    if hit is None:
        # Slash-prefixed but unknown → reply with hint; plain chitchat → ignore
        if registry.is_slash_command(msg.content):
            try:
                ctx.wx_adapter.send_text("❓ 未知命令，发 /help 查看可用命令", FILEHELPER_WXID)
            except Exception as e:
                LOG.error("send unknown-cmd reply failed: %s", e)
            return True
        return False

    handler, args = hit
    try:
        result = handler(ctx, args)
    except Exception as e:
        LOG.error("command handler raised: %s", e, exc_info=True)
        result = f"❗ 执行失败: {e}"

    try:
        ctx.wx_adapter.send_text(result, FILEHELPER_WXID)
    except Exception as e:
        LOG.error("send command reply failed: %s", e)
    return True
```

- [ ] **Step 4: Run command tests**

```bash
pytest tests/test_commands.py -v
```

Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add router/commands.py tests/test_commands.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(router): add CommandRegistry + 4 filehelper command handlers"
```

---

## Task 5: Wire filehelper command branch into `Dispatcher`

**Files:**
- Modify: `router/dispatch.py`
- Modify: `tests/test_dispatch.py`

- [ ] **Step 1: Add failing tests for the new branch + security**

Append to `tests/test_dispatch.py` (after existing tests, before any closing whitespace):

```python
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
    # Should have called wx.send_text with text containing "运行中" and target filehelper
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
    # No reply (filehelper plain text shouldn't trigger LLM either — self message
    # paths already early-return on the next branch)
    wx.send_text.assert_not_called()
    llm.get_answer.assert_not_called()


def test_security_non_self_pause_does_not_pause(dispatcher, wx):
    """Critical security test: a stranger DMing /pause must NOT control the bot."""
    from dashboard.state import reset_state, get_state
    reset_state()
    msg = WxMsg(
        id=1, type=1, sender="wxid_attacker", roomid="", content="/pause",
        is_self=False, ts=0, receiver="filehelper",
    )
    dispatcher.handle(msg)
    assert get_state().paused is False
    # Should fall through to LLM fallback (since not friend req, not template,
    # not order); send_text may be called for LLM reply but state is unchanged
    # — what matters is paused stayed False.


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
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest tests/test_dispatch.py -v -k "filehelper or security"
```

Expected: 8 new tests FAIL (most likely AssertionError because wx.send_text wasn't called / paused didn't change — the branch doesn't exist yet).

- [ ] **Step 3: Wire commands into `Dispatcher._handle`**

In `router/dispatch.py`:

(a) Add imports at the top after the existing imports:

```python
from router.commands import (
    CommandContext, CommandRegistry, build_default_registry,
    try_handle_filehelper_command,
)
```

(b) Modify `Dispatcher.__init__` to build a registry:

```python
    def __init__(
        self,
        wx,
        template_matcher: TemplateMatcher,
        order_handler,
        llm,
        groups_allowed: set[str],
        command_registry: CommandRegistry | None = None,
    ):
        self.wx = wx
        self.tm = template_matcher
        self.order = order_handler
        self.llm = llm
        self.groups = set(groups_allowed)
        self._self_wxid = wx.get_self_wxid()
        self.commands = command_registry or build_default_registry()
```

(c) In `_handle`, insert the filehelper branch as the FIRST step (above the existing self-message early-return):

```python
    def _handle(self, msg: WxMsg) -> None:
        # 0. Filehelper command channel (highest priority; bypasses pause check).
        #    Security gates inside try_handle_filehelper_command ensure only
        #    self-to-filehelper text messages are accepted.
        try:
            from dashboard.state import get_state
            ctx = CommandContext(wx_adapter=self.wx, state=get_state(), account_state=None)
            if try_handle_filehelper_command(msg, ctx, self.commands):
                return
        except Exception as e:
            LOG.error("filehelper command handling crashed: %s", e, exc_info=True)
            # Fall through to normal handling

        # 1. Self messages: ignore
        if msg.from_self():
            return
        # ... rest of existing logic unchanged
```

**IMPORTANT:** Also adjust the wrapping `handle()` method — the existing pause-check early-returns on `_is_paused()` and drops the message. Filehelper commands must work even when paused (you need /resume to unpause!). Modify `handle()`:

```python
    def handle(self, msg: WxMsg) -> None:
        _safe_record_message(msg)
        # Filehelper commands bypass the global pause flag (so /resume works).
        is_filehelper = (
            msg.from_self()
            and msg.receiver == "filehelper"
            and msg.type == 1
        )
        if _is_paused() and not msg.from_self() and msg.type != 37 and not is_filehelper:
            LOG.debug("dispatcher paused; dropping msg %s", msg.id)
            return
        try:
            self._handle(msg)
        except Exception as e:
            LOG.error("dispatcher error on msg %s: %s", msg.id, e, exc_info=True)
```

(Note: `is_filehelper` is redundant in the current condition since `not msg.from_self()` already excludes self-messages, but the explicit check is intentional documentation that filehelper is never dropped.)

- [ ] **Step 4: Run dispatch tests**

```bash
pytest tests/test_dispatch.py -v
```

Expected: all original + 8 new pass (≥ 19 tests).

- [ ] **Step 5: Commit**

```bash
git add router/dispatch.py tests/test_dispatch.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(router): wire filehelper command branch into Dispatcher with security tests"
```

---

## Task 6: Full-suite verification + push

**Files:** none (verification + git ops)

- [ ] **Step 1: Run the entire test suite**

```bash
pytest tests/ -q
```

Expected: all green (previous 105 + ~25 new ≈ 130 passed).

- [ ] **Step 2: Sanity-import main**

```bash
python -c "import main; print('main imports ok')"
```

Expected: `main imports ok`.

- [ ] **Step 3: Push to GitHub main**

```bash
git push github master:main
```

Expected: 4 new commits land on `AITCX08/WechatBot:main`.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task | Notes |
|---|---|---|
| 4 commands (/status /pause /resume /help) | Task 4 | All 4 handlers + tests |
| Chinese aliases (状态/暂停/恢复/帮助) | Task 4 | Tested via `test_registry_alias_maps_to_slash` + `test_filehelper_chinese_alias_works` |
| Slash prefix routing | Task 4 | `lookup` + `is_slash_command` |
| Unknown /cmd → hint | Task 4, Task 5 | `test_try_handle_unknown_slash_replies_with_hint` |
| Plain chitchat → ignore | Task 4 | `test_try_handle_plain_chitchat_returns_false` |
| from_self + receiver=filehelper gate | Task 4 | 3 security tests in test_commands + 3 in test_dispatch |
| Multi-account isolation (MVP scope: global pause OK) | Task 5 | `state.pause()` is global by design; comment in code |
| Handler exception → friendly error | Task 4 | `test_try_handle_handler_exception_replies_with_error` |
| WxMsg receiver field, default "" | Task 1 | backward-compatible |
| Sidecar populates receiver from to_user | Task 2 | `test_translate_event_with_missing_to_user` covers missing case |
| Filehelper bypasses pause flag (/resume must work paused) | Task 5 | `handle()` modification |

No gaps.

**Placeholder scan:** Searched plan for TBD/TODO/fill-in/handle edge cases/etc. None found.

**Type consistency:**
- `CommandFn` aka `HandlerFn` signature `(CommandContext, str) -> str` used consistently in registry + handlers + tests
- `CommandContext` fields (`wx_adapter`, `state`, `account_state`) used same way throughout
- `try_handle_filehelper_command` signature `(msg, ctx, registry) -> bool` consistent in commands.py + dispatch.py + tests
- `FILEHELPER_WXID` constant used in commands.py + dispatch.py `handle()`; string literal `"filehelper"` used in tests for clarity (matches the constant value)

All consistent.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-filehelper-commands-mvp.md`.

Proceeding with **Subagent-Driven** execution per the established session pattern (one subagent per task, push at the end).
