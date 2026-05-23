from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

from dashboard.accounts import AccountManager, AccountState
from dashboard.ring_buffer import RingBuffer


@dataclass
class BotState:
    """Singleton bot-runtime state shared between bot threads and dashboard.

    Multi-account: real per-account runtime lives in `self.accounts`
    (an AccountManager). The top-level `paused` flag is a *global* override
    that the dispatcher honors regardless of account.

    Legacy single-account compat: code that pre-dates the manager can still
    set `self.wx_adapter` / `self.order_handler`. We mirror these into a
    synthetic "default" account so the dashboard always sees a uniform view.
    """

    started_at: float = field(default_factory=time.time)
    paused: bool = False
    pause_reason: str = ""

    # Legacy single-account refs (kept for backward compat with router code
    # that does `from dashboard.state import get_state; get_state().wx_adapter`).
    wx_adapter: Optional[object] = None
    order_handler: Optional[object] = None

    # Multi-account manager. Always present; can be empty.
    accounts: AccountManager = field(default_factory=AccountManager)

    # Ring buffers shared across all accounts (logs are global; messages and
    # audit are tagged with account name in their payload).
    logs: RingBuffer = field(default_factory=lambda: RingBuffer(2000))
    messages: RingBuffer = field(default_factory=lambda: RingBuffer(500))
    audit: RingBuffer = field(default_factory=lambda: RingBuffer(500))

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- global pause/resume ----
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
        """Aggregate snapshot for the dashboard top-bar."""
        snap = {
            "uptime_sec": int(time.time() - self.started_at),
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "log_count": len(self.logs),
            "message_count": len(self.messages),
            "audit_count": len(self.audit),
            "account_count": len(self.accounts.names()),
            "accounts": self.accounts.snapshot_all(),
            "factory_registered": self.accounts.factory_registered,
            # Legacy aggregate fields (sum across accounts + legacy default):
            "sidecar_alive": False,
            "weixin_attached": False,
            "queue_depth": 0,
            "pending_orders": 0,
            "daily_orders": 0,
        }
        # Aggregate per-account numbers
        for acc in snap["accounts"]:
            if acc["sidecar_alive"]:
                snap["sidecar_alive"] = True
            if acc["weixin_attached"]:
                snap["weixin_attached"] = True
            snap["queue_depth"] += acc.get("queue_depth", 0)
            snap["pending_orders"] += acc.get("pending_orders", 0)
            snap["daily_orders"] += acc.get("daily_orders", 0)

        # Mix in legacy single-account state if any (for pre-refactor code paths)
        wx = self.wx_adapter
        oh = self.order_handler
        if wx is not None:
            try:
                if bool(wx.is_receiving_msg()):
                    snap["sidecar_alive"] = True
            except Exception:
                pass
            try:
                if wx._send._main is not None:  # type: ignore[attr-defined]
                    snap["weixin_attached"] = True
            except Exception:
                pass
            try:
                snap["queue_depth"] += wx._queue.qsize()  # type: ignore[attr-defined]
            except Exception:
                pass
        if oh is not None:
            try:
                snap["pending_orders"] += len(oh._pending)  # type: ignore[attr-defined]
                snap["daily_orders"] += oh._daily_count    # type: ignore[attr-defined]
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
