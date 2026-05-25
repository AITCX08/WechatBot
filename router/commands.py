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
    """Bundle the dependencies handlers need."""
    wx_adapter: object       # WxAdapter; duck-typed (send_text + queue + ...)
    state: object            # dashboard.state.BotState
    account_state: object | None = None
    reporter: object | None = None        # Reporter instance for /report
    pricing: object | None = None         # PricingTable instance for /pricing


HandlerFn = Callable[[CommandContext, str], str]


class CommandRegistry:
    """Slash-prefixed command registry with optional Chinese-keyword aliases."""

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
            parts = text.split(None, 1)
            cmd = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            fn = self._handlers.get(cmd)
            if fn is None:
                return None
            return fn, args
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
        "/status   或 「状态」    — 查看运行状态\n"
        "/pause    或 「暂停」    — 暂停响应\n"
        "/resume   或 「恢复」    — 取消暂停\n"
        "/report   或 「日报/今日」— 今日报告 (/report yesterday|7d|30d)\n"
        "/pending  或 「待确认」  — 待确认订单列表\n"
        "/pricing  或 「价格」    — 当前价格表\n"
        "/help     或 「帮助」    — 此说明"
    )


def cmd_report(ctx: CommandContext, args: str) -> str:
    if ctx.reporter is None:
        return "⚠ 报告引擎未就绪"
    account = "default"
    if ctx.account_state is not None:
        try:
            account = ctx.account_state.config.name
        except Exception:
            pass
    window = (args or "today").strip()
    rep = ctx.reporter.aggregate(account=account, window=window)
    return ctx.reporter.render_text(rep)


def cmd_pending(ctx: CommandContext, args: str) -> str:
    oh = None
    if ctx.account_state is not None:
        oh = getattr(ctx.account_state, "order_handler", None)
    if oh is None and ctx.state is not None:
        oh = getattr(ctx.state, "order_handler", None)
    if oh is None:
        return "⚠ OrderHandler 未就绪"
    pending = list(oh._pending.values()) if hasattr(oh, "_pending") else []
    if not pending:
        return "✅ 当前无待确认订单"
    lines = [f"📋 待确认订单 ({len(pending)} 笔):"]
    for d in pending:
        lines.append(f"  {d.requester_wxid}: {d.kcname or '?'} ({d.kcid or '?'}) · 第 {d.extract_rounds} 轮")
    return "\n".join(lines)


def cmd_pricing(ctx: CommandContext, args: str) -> str:
    if ctx.pricing is None:
        return "⚠ 价格表未配置"
    table = ctx.pricing._table
    lines = ["💰 当前价格表："]
    default = table.get("default")
    if default is not None:
        lines.append(f"  全局默认: ¥{float(default):.2f}")
    for k, v in table.items():
        if k == "default" or not isinstance(v, dict):
            continue
        lines.append(f"  [{k}] 默认 ¥{float(v.get('default', 0)):.2f}")
        for course, price in v.items():
            if course == "default":
                continue
            lines.append(f"    · {course}  ¥{float(price):.2f}")
    return "\n".join(lines)


def build_default_registry() -> CommandRegistry:
    """Wire the v2 commands and their Chinese aliases."""
    reg = CommandRegistry()
    reg.register("/status", cmd_status, aliases=["状态"])
    reg.register("/pause",  cmd_pause,  aliases=["暂停"])
    reg.register("/resume", cmd_resume, aliases=["恢复"])
    reg.register("/help",   cmd_help,   aliases=["帮助"])
    reg.register("/report", cmd_report, aliases=["日报", "今日", "报告"])
    reg.register("/pending", cmd_pending, aliases=["待确认", "待办"])
    reg.register("/pricing", cmd_pricing, aliases=["价格", "价目"])
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
