"""Event-driven notifications to per-account filehelper."""
from __future__ import annotations
import logging
import threading
import time
from typing import Callable, Optional

LOG = logging.getLogger(__name__)

CRITICAL_EVENTS = frozenset({"error", "sidecar_down", "order_failure"})

FORMATTERS = {
    "online":         lambda p: "🟢 [{account}] 已上线",
    "offline":        lambda p: "🔴 [{account}] 已下线",
    "order_success":  lambda p: "✅ [{account}] 下单成功 / {wxid} / {kcname}",
    "order_failure":  lambda p: "❌ [{account}] 下单失败 / {wxid} / {kcname} / {msg}",
    "order_dry_run":  lambda p: "🟡 [{account}] dry_run 下单 / {wxid} / {kcname}",
    "error":          lambda p: "❗ [{account}] 错误：{msg}",
    "sidecar_down":   lambda p: "❗ [{account}] sidecar 心跳超时",
}


class Notifier:
    """Send filehelper notifications per account, with cooldown + quiet hours."""

    def __init__(
        self,
        adapter_lookup: Callable[[str], object],
        cooldown_sec: int = 300,
        quiet_hours: tuple = (),
        enabled_events: Optional[set] = None,
    ):
        self._lookup = adapter_lookup
        self._cooldown_sec = int(cooldown_sec)
        self._quiet_hours = tuple(quiet_hours) if quiet_hours else ()
        self._enabled = enabled_events
        self._last_emit: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def emit(self, account: str, event_type: str, payload: dict) -> None:
        try:
            self._emit(account, event_type, payload)
        except Exception as e:
            LOG.warning("notifier.emit failed: %s", e)

    def _emit(self, account: str, event_type: str, payload: dict) -> None:
        if self._enabled is not None and event_type not in self._enabled:
            return

        is_critical = event_type in CRITICAL_EVENTS
        if not is_critical and self._in_quiet_hours():
            return

        key = (account, event_type)
        now = time.time()
        with self._lock:
            last = self._last_emit.get(key, 0.0)
            if not is_critical and (now - last) < self._cooldown_sec:
                return
            self._last_emit[key] = now

        adapter = self._lookup(account)
        if adapter is None:
            LOG.debug("no adapter for account %s; dropping notification", account)
            return

        text = self._format(account, event_type, payload)
        try:
            adapter.send_text(text, "filehelper")
        except Exception as e:
            LOG.warning("notifier send_text failed: %s", e)

    def _format(self, account: str, event_type: str, payload: dict) -> str:
        fmt = FORMATTERS.get(event_type)
        ctx = {"account": account, "wxid": "", "kcname": "", "msg": ""}
        ctx.update(payload or {})
        if fmt is None:
            return f"ℹ️ [{account}] {event_type}: {payload}"
        try:
            return fmt(ctx).format(**ctx)
        except Exception:
            return f"ℹ️ [{account}] {event_type}"

    def _in_quiet_hours(self) -> bool:
        if not self._quiet_hours or len(self._quiet_hours) != 2:
            return False
        start, end = self._quiet_hours
        hour = time.localtime().tm_hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end
