from __future__ import annotations
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue

import requests

from wx.msg import WxMsg

LOG = logging.getLogger(__name__)


class ReceiveBackend:
    """Wraps the wechat-decrypt sidecar. One process per backend instance."""

    SSE_PATH = "/stream"             # path on monitor_web.py; verify in Task 0.3
    HEARTBEAT_TIMEOUT_SEC = 30
    RESTART_BACKOFF_SEC = 5
    MAX_RESTARTS = 3

    def __init__(
        self,
        decrypt_repo: Path | None,
        sidecar_url: str,
        msg_queue: Queue,
    ):
        self._repo = Path(decrypt_repo) if decrypt_repo else None
        self._url = sidecar_url.rstrip("/")
        self._queue = msg_queue
        self._proc: subprocess.Popen | None = None
        self._sse_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_event_ts = 0.0
        self._restart_count = 0

    # ---- lifecycle ----
    def start(self) -> None:
        if self._proc is not None:
            return
        self._spawn_sidecar()
        self._sse_thread = threading.Thread(
            target=self._sse_loop, name="ReceiveSSE", daemon=True
        )
        self._sse_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def is_alive(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        if self._last_event_ts == 0.0:
            return True   # not yet received first event; grace period
        return (time.time() - self._last_event_ts) < self.HEARTBEAT_TIMEOUT_SEC

    # ---- subprocess + SSE ----
    def _spawn_sidecar(self) -> None:
        if self._repo is None:
            LOG.warning("ReceiveBackend: no decrypt_repo, assuming external sidecar")
            return
        venv_py = self._repo / ".venv" / "Scripts" / "python.exe"
        py = str(venv_py) if venv_py.exists() else "python"
        cmd = [py, str(self._repo / "monitor_web.py")]
        LOG.info("Launching sidecar: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd, cwd=str(self._repo),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(2)   # give the web server time to bind

    def _sse_loop(self) -> None:
        while not self._stop.is_set():
            try:
                with requests.get(
                    self._url + self.SSE_PATH, stream=True, timeout=(5, None)
                ) as r:
                    r.raise_for_status()
                    for line in r.iter_lines(decode_unicode=True):
                        if self._stop.is_set():
                            return
                        if not line or not line.startswith("data:"):
                            continue
                        try:
                            payload = json.loads(line[len("data:"):].strip())
                        except json.JSONDecodeError:
                            LOG.warning("malformed SSE line: %r", line)
                            continue
                        self._consume_event(payload)
            except Exception as e:
                LOG.error("SSE connection lost: %s", e)
                if self._stop.is_set():
                    return
                self._restart_count += 1
                if self._restart_count > self.MAX_RESTARTS:
                    LOG.error("max restarts exceeded; giving up")
                    return
                time.sleep(self.RESTART_BACKOFF_SEC)

    # ---- translation ----
    def _consume_event(self, event: dict) -> None:
        msg = self._translate_event(event)
        if msg is not None:
            self._last_event_ts = time.time()
            self._queue.put(msg)

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
            )
        except (KeyError, ValueError, TypeError) as e:
            LOG.warning("malformed message event %r: %s", event, e)
            return None
