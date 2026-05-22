"""Weixin process launcher with login-detection polling.

Workflow (per account):
  1. If no Weixin process matching `exe` is running → spawn it
  2. Poll for the main window to become available (Name='微信' or 'Weixin')
  3. Returns when the window is ready, or raises TimeoutError

We do NOT auto-scan the QR code — that is impossible by design (Tencent
requires a real device). The user must scan with their phone after the
Weixin window appears.
"""
from __future__ import annotations
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

LOG = logging.getLogger(__name__)

MAIN_WINDOW_NAMES = ("微信", "Weixin")


def _find_running_weixin(exe_path: Path) -> Optional[int]:
    """Return PID of any Weixin process whose exe matches the given path."""
    try:
        import psutil
    except ImportError:
        return None
    target = str(exe_path).lower().replace("/", "\\")
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = (proc.info.get("exe") or "").lower().replace("/", "\\")
            if exe == target:
                return proc.info["pid"]
        except Exception:
            continue
    return None


def _find_weixin_window(pid: Optional[int] = None):
    """Locate the main Weixin window via UIA.

    If pid is given, only return a window owned by that PID.
    Returns None if no logged-in window is found.
    """
    try:
        import uiautomation as uia
    except ImportError:
        return None
    for name in MAIN_WINDOW_NAMES:
        w = uia.WindowControl(searchDepth=2, Name=name)
        if not w.Exists(maxSearchSeconds=1):
            continue
        if pid is not None:
            try:
                if w.ProcessId != pid:
                    continue
            except Exception:
                pass
        return w
    return None


def ensure_weixin_running(
    exe_path: str,
    spawn_if_missing: bool = True,
    login_timeout_sec: int = 120,
    poll_interval_sec: float = 2.0,
) -> int:
    """Ensure a Weixin instance is open and logged in. Returns its PID.

    Raises:
        FileNotFoundError: if exe_path doesn't exist and we need to spawn it.
        TimeoutError: if no logged-in window appears within login_timeout_sec.
        RuntimeError: on other failures.
    """
    exe = Path(exe_path)
    if not exe.exists():
        if not spawn_if_missing:
            raise FileNotFoundError(f"Weixin.exe not found: {exe_path}")
        raise FileNotFoundError(f"Weixin.exe not found: {exe_path}")

    pid = _find_running_weixin(exe)
    if pid is None and spawn_if_missing:
        LOG.info("spawning %s", exe)
        try:
            # CREATE_NEW_PROCESS_GROUP so Ctrl+C in our process doesn't kill it
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [str(exe)],
                cwd=str(exe.parent),
                creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as e:
            raise RuntimeError(f"failed to spawn Weixin: {e}") from e

        # Give the process time to come up
        for _ in range(10):
            pid = _find_running_weixin(exe)
            if pid is not None:
                break
            time.sleep(0.5)
        if pid is None:
            raise RuntimeError("Weixin spawned but PID not discoverable")

    # Now wait for the logged-in window to appear
    deadline = time.time() + login_timeout_sec
    LOG.info(
        "waiting for Weixin login (PID=%s)... timeout=%ds; scan QR with phone",
        pid, login_timeout_sec,
    )
    while time.time() < deadline:
        w = _find_weixin_window(pid=pid)
        if w is not None:
            LOG.info("Weixin login detected (PID=%s)", pid)
            return pid
        time.sleep(poll_interval_sec)
    raise TimeoutError(
        f"Weixin did not show a logged-in window within {login_timeout_sec}s "
        f"(PID={pid}). Make sure you scanned the QR with your phone."
    )
