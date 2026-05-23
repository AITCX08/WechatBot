"""Per-account state and lifecycle management for the bot.

An "account" is one Weixin instance the bot drives. Each account has:
  - its own WxAdapter (own Weixin window, own sidecar URL, own contacts DB)
  - its own Robot/Dispatcher/OrderHandler
  - its own pause flag, ring buffers (logs filtered by account name),
    audit log file
  - independent lifecycle: STOPPED -> STARTING -> RUNNING (paused?) -> STOPPING -> STOPPED

The AccountManager holds them in memory and exposes start/stop/pause/resume.

NOTE: process spawning lives in `dashboard.launcher`. This module is just
state + orchestration.
"""
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from dashboard.ring_buffer import RingBuffer

LOG = logging.getLogger(__name__)


class AccountStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class AccountConfig:
    """Static config for one account, parsed from config.yaml."""
    name: str
    label: str = ""                           # display name in UI
    exe: str = ""                             # Weixin.exe path
    sidecar_url: str = "http://127.0.0.1:5678"
    sidecar_repo: str = ""
    decrypted_db_path: str = ""
    self_wxid: str = ""

    def display(self) -> str:
        return self.label or self.name


@dataclass
class AccountState:
    """Per-account runtime state."""
    config: AccountConfig
    status: AccountStatus = AccountStatus.STOPPED
    started_at: float = 0.0
    last_error: str = ""
    paused: bool = False
    pause_reason: str = ""

    # injected when bot is running
    wx_adapter: Optional[object] = None
    robot: Optional[object] = None
    order_handler: Optional[object] = None

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def name(self) -> str:
        return self.config.name

    def snapshot(self) -> dict:
        snap = {
            "name": self.name,
            "label": self.config.display(),
            "status": self.status.value,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "uptime_sec": int(time.time() - self.started_at) if self.started_at else 0,
            "last_error": self.last_error,
            "sidecar_alive": False,
            "weixin_attached": False,
            "queue_depth": 0,
            "pending_orders": 0,
            "daily_orders": 0,
        }
        wx = self.wx_adapter
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
        oh = self.order_handler
        if oh is not None:
            try:
                snap["pending_orders"] = len(oh._pending)  # type: ignore[attr-defined]
                snap["daily_orders"] = oh._daily_count    # type: ignore[attr-defined]
            except Exception:
                pass
        return snap

    def pause(self, reason: str = "") -> None:
        with self._lock:
            self.paused = True
            self.pause_reason = reason or "manual"

    def resume(self) -> None:
        with self._lock:
            self.paused = False
            self.pause_reason = ""


# Bot factory: given an AccountConfig, build a running (adapter, robot, order_handler).
# Provided by main.py at startup so this module stays decoupled from robot/wx.
BotFactory = Callable[[AccountConfig, "AccountState"], tuple]


class AccountManager:
    """Holds N accounts and orchestrates per-account start/stop/pause/resume."""

    def __init__(self):
        self._accounts: dict[str, AccountState] = {}
        self._factory: Optional[BotFactory] = None
        self._lock = threading.Lock()
        # Persistence callback (set by main.py); invoked after register/unregister
        # with the list of accounts that should survive restart.
        self._persist: Optional[Callable[[list[AccountConfig]], None]] = None

    # ---- setup ----
    def set_factory(self, fac: BotFactory) -> None:
        self._factory = fac

    @property
    def factory_registered(self) -> bool:
        return self._factory is not None

    def set_persistence(self, persist_fn: Callable[[list], None]) -> None:
        self._persist = persist_fn

    def register(self, cfg: AccountConfig, persist: bool = False) -> AccountState:
        with self._lock:
            if cfg.name in self._accounts:
                return self._accounts[cfg.name]
            state = AccountState(config=cfg)
            self._accounts[cfg.name] = state
            LOG.info("account registered: %s", cfg.name)
        if persist and self._persist is not None:
            try:
                self._persist(self._dynamic_configs())
            except Exception as e:
                LOG.warning("persistence callback failed: %s", e)
        return state

    def unregister(self, name: str) -> tuple[bool, str]:
        """Remove account from manager. Refuses if status != STOPPED."""
        with self._lock:
            state = self._accounts.get(name)
            if state is None:
                return False, f"unknown account: {name}"
            if state.status != AccountStatus.STOPPED:
                return False, f"cannot remove account in status={state.status.value}; stop it first"
            del self._accounts[name]
            LOG.info("account unregistered: %s", name)
        if self._persist is not None:
            try:
                self._persist(self._dynamic_configs())
            except Exception as e:
                LOG.warning("persistence callback failed: %s", e)
        return True, "removed"

    def _dynamic_configs(self) -> list:
        """Return list of AccountConfig that should be persisted.
        Currently: all accounts. main.py decides what to write (it skips
        accounts that came from config.yaml to avoid duplication)."""
        return [s.config for s in self._accounts.values()]

    # ---- lookup ----
    def all(self) -> list[AccountState]:
        return list(self._accounts.values())

    def get(self, name: str) -> Optional[AccountState]:
        return self._accounts.get(name)

    def names(self) -> list[str]:
        return list(self._accounts.keys())

    # ---- lifecycle ----
    def start(self, name: str) -> tuple[bool, str]:
        state = self.get(name)
        if state is None:
            return False, f"unknown account: {name}"
        if state.status in (AccountStatus.RUNNING, AccountStatus.STARTING):
            return True, "already running/starting"
        if self._factory is None:
            return False, "bot factory not registered"

        state.status = AccountStatus.STARTING
        state.last_error = ""

        def _bg():
            try:
                LOG.info("account %s: starting...", name)
                wx, robot, order = self._factory(state.config, state)
                state.wx_adapter = wx
                state.robot = robot
                state.order_handler = order
                state.started_at = time.time()
                state.status = AccountStatus.RUNNING
                state.paused = False
                LOG.info("account %s: running", name)
            except Exception as e:
                state.status = AccountStatus.ERROR
                state.last_error = str(e)
                LOG.error("account %s: start failed: %s", name, e, exc_info=True)

        threading.Thread(target=_bg, name=f"acc-start-{name}", daemon=True).start()
        return True, "starting"

    def stop(self, name: str) -> tuple[bool, str]:
        state = self.get(name)
        if state is None:
            return False, f"unknown account: {name}"
        if state.status == AccountStatus.STOPPED:
            return True, "already stopped"

        state.status = AccountStatus.STOPPING

        def _bg():
            try:
                LOG.info("account %s: stopping...", name)
                if state.wx_adapter is not None:
                    try:
                        state.wx_adapter.cleanup()  # type: ignore[attr-defined]
                    except Exception as e:
                        LOG.warning("account %s: cleanup error: %s", name, e)
                state.wx_adapter = None
                state.robot = None
                state.order_handler = None
                state.started_at = 0.0
                state.paused = False
                state.pause_reason = ""
                state.status = AccountStatus.STOPPED
                LOG.info("account %s: stopped", name)
            except Exception as e:
                state.status = AccountStatus.ERROR
                state.last_error = str(e)
                LOG.error("account %s: stop failed: %s", name, e, exc_info=True)

        threading.Thread(target=_bg, name=f"acc-stop-{name}", daemon=True).start()
        return True, "stopping"

    def pause(self, name: str, reason: str = "") -> tuple[bool, str]:
        state = self.get(name)
        if state is None:
            return False, "unknown account"
        state.pause(reason)
        return True, "paused"

    def resume(self, name: str) -> tuple[bool, str]:
        state = self.get(name)
        if state is None:
            return False, "unknown account"
        state.resume()
        return True, "resumed"

    # ---- snapshot ----
    def snapshot_all(self) -> list[dict]:
        return [s.snapshot() for s in self.all()]
