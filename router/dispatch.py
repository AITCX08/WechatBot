from __future__ import annotations
import logging
import time
from pathlib import Path

from wx.msg import WxMsg
from router.template import TemplateMatcher, TemplateAction
from router.commands import (
    CommandContext, CommandRegistry, build_default_registry,
    try_handle_filehelper_command,
)

LOG = logging.getLogger(__name__)


def _safe_record_message(msg: WxMsg) -> None:
    """Push the incoming message into BotState.messages for the dashboard.

    Lazy import + broad except so router code stays decoupled from the
    dashboard package; if dashboard isn't installed/initialized this is a no-op.
    """
    try:
        from dashboard.state import get_state
        get_state().messages.append({
            "ts": msg.ts or int(time.time()),
            "id": msg.id,
            "type": msg.type,
            "sender": msg.sender,
            "roomid": msg.roomid,
            "content": msg.content,
            "is_self": msg.is_self,
        })
    except Exception:
        pass


def _is_paused() -> bool:
    try:
        from dashboard.state import get_state
        return get_state().paused
    except Exception:
        return False


class Dispatcher:
    """Routes each incoming WxMsg through a deterministic chain."""

    def __init__(
        self,
        wx,
        template_matcher: TemplateMatcher,
        order_handler,
        llm,
        groups_allowed: set[str],
        command_registry: CommandRegistry | None = None,
        reporter=None,
        pricing=None,
    ):
        self.wx = wx
        self.tm = template_matcher
        self.order = order_handler
        self.llm = llm
        self.groups = set(groups_allowed)
        self._self_wxid = wx.get_self_wxid()
        self.commands = command_registry or build_default_registry()
        self.reporter = reporter
        self.pricing = pricing

    def handle(self, msg: WxMsg) -> None:
        _safe_record_message(msg)
        # Filehelper commands bypass the global pause flag (so /resume works).
        is_filehelper = (
            msg.from_self()
            and msg.receiver == "filehelper"
            and msg.type == 1
        )
        if _is_paused() and not msg.from_self() and msg.type != 37 and not is_filehelper:
            # When paused, ignore message-driven actions but still let
            # self/system events flow (already early-returned in _handle).
            LOG.debug("dispatcher paused; dropping msg %s", msg.id)
            return
        try:
            self._handle(msg)
        except Exception as e:
            LOG.error("dispatcher error on msg %s: %s", msg.id, e, exc_info=True)

    def _handle(self, msg: WxMsg) -> None:
        # 0. Filehelper command channel (highest priority).
        #    Security gates inside try_handle_filehelper_command ensure only
        #    self-to-filehelper text messages are accepted.
        try:
            from dashboard.state import get_state
            ctx = CommandContext(
                wx_adapter=self.wx, state=get_state(), account_state=None,
                reporter=self.reporter, pricing=self.pricing,
            )
            if try_handle_filehelper_command(msg, ctx, self.commands):
                return
        except Exception as e:
            LOG.error("filehelper command handling crashed: %s", e, exc_info=True)
            # Fall through to normal handling

        # 1. Self messages: ignore
        if msg.from_self():
            return

        # 2. Friend request (type 37): auto-accept
        if msg.type == 37:
            LOG.info("auto-accepting friend request from %s", msg.sender)
            self.wx.accept_new_friend("", "", 0)
            return

        # 3. Group filter: only respond in allowed groups, and only when @bot
        if msg.from_group():
            if msg.roomid not in self.groups:
                return
            if not msg.is_at(self._self_wxid):
                return
            # @bot in allowed group → continue processing

        receiver = msg.roomid if msg.from_group() else msg.sender

        # 4. Order pending: any reply from a sender with an open draft goes
        #    to the order handler (covers confirm/cancel/correction)
        if self.order.is_pending_for(msg.sender):
            self.order.on_user_reply(msg)
            return

        # 5. Template matches (static keyword/image/menu replies)
        actions = self.tm.match(msg.content) if msg.type == 1 else []
        if actions:
            for act in actions:
                self._dispatch_action(act, receiver)
            return

        # 6. Order intent classifier
        if msg.type == 1 and self.order.looks_like_order_intent(msg.content):
            self.order.handle_new_order_message(msg)
            return

        # 7. Fallback: LLM chitchat (only on text messages)
        if msg.type == 1:
            response = self.llm.get_answer(msg.content, receiver)
            if response:
                self.wx.send_text(response, receiver)

    def _dispatch_action(self, action: TemplateAction, receiver: str) -> None:
        if action.kind == "text":
            self.wx.send_text(action.payload, receiver)
        elif action.kind == "menu":
            self.wx.send_text(action.payload, receiver)
        elif action.kind == "image":
            self.wx.send_image(action.payload, receiver)
        else:
            LOG.warning("unknown action kind: %s", action.kind)
