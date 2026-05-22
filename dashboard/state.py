from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

from dashboard.ring_buffer import RingBuffer


@dataclass
class BotState:
    """Singleton bot-runtime state shared between bot threads and dashboard."""

    started_at: float = field(default_factory=time.time)
    paused: bool = False
    pause_reason: str = ""

    # injected at runtime
    wx_adapter: Optional[object] = None
    order_handler: Optional[object] = None

    # ring buffers (capacity tuned for ~1 hour @ moderate traffic)
    logs: RingBuffer = field(default_factory=lambda: RingBuffer(2000))
    messages: RingBuffer = field(default_factory=lambda: RingBuffer(500))
    audit: RingBuffer = field(default_factory=lambda: RingBuffer(500))

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- pause/resume ----
    def pause(self, reason: str = "") -> None:
        with self._lock:
            self.paused = True
            self.pause_reason = reason or "manual"

    def resume(self) -> None:
        with self._lock:
            self.paused = False
            self.pause_reason = ""

    # ---- status snapshot ----
    def snapshot(self) -> dict:
        wx = self.wx_adapter
        oh = self.order_handler
        snap = {
            "uptime_sec": int(time.time() - self.started_at),
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "sidecar_alive": False,
            "weixin_attached": False,
            "queue_depth": 0,
            "pending_orders": 0,
            "daily_orders": 0,
            "log_count": len(self.logs),
            "message_count": len(self.messages),
            "audit_count": len(self.audit),
        }
        if wx is not None:
            try:
                snap["sidecar_alive"] = bool(wx.is_receiving_msg())
            except Exception:
                pass
            try:
                snap["weixin_attached"] = wx._send._main is not None  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                snap["queue_depth"] = wx._queue.qsize()  # type: ignore[attr-defined]
            except Exception:
                pass
        if oh is not None:
            try:
                snap["pending_orders"] = len(oh._pending)  # type: ignore[attr-defined]
                snap["daily_orders"] = oh._daily_count    # type: ignore[attr-defined]
            except Exception:
                pass
        return snap


# Module-level singleton; constructed lazily so import is cheap.
_STATE: Optional[BotState] = None
_STATE_LOCK = threading.Lock()


def get_state() -> BotState:
    global _STATE
    with _STATE_LOCK:
        if _STATE is None:
            _STATE = BotState()
        return _STATE


def reset_state() -> None:
    """Test-only: drop the singleton."""
    global _STATE
    with _STATE_LOCK:
        _STATE = None
