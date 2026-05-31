from __future__ import annotations
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue

import requests

from wx.constants import FILEHELPER_WXID
from wx.msg import WxMsg

LOG = logging.getLogger(__name__)

# wechat-decrypt emits the message type as a Chinese string (format_msg_type,
# monitor_web.py:567-572). Map it back to the wcferry-style numeric code so the
# rest of the codebase (dispatch.py / order.py: `msg.type == 1`) keeps working.
# Verified mapping — see docs/sidecar-verification.md.
_TYPE_CN_TO_NUM = {
    "文本": 1,
    "图片": 3,
    "语音": 34,
    "名片": 42,
    "视频": 43,
    "表情": 47,
    "位置": 48,
    "链接/文件": 49,
    "通话": 50,
    "系统": 10000,
    "撤回": 10002,
}


class ReceiveBackend:
    """Wraps the wechat-decrypt sidecar. One process per backend instance.

    SSE contract verified against sidecar source (docs/sidecar-verification.md):
    endpoint GET /stream on port 5678, normal new messages are BARE
    `data: <json>\\n\\n` frames with top-level fields (no event_type/data wrap);
    async update frames carry an `event` key and are ignored here.
    """

    SSE_PATH = "/stream"             # verified: monitor_web.py:2850
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
        self._last_event_ts = 0.0   # last delivered message
        self._last_line_ts = 0.0    # last ANY line incl. heartbeat (liveness)
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
        # Liveness = any SSE line (heartbeat OR message) within the timeout.
        # The sidecar emits ': hb' every 15s on idle (monitor_web.py:2863-2868),
        # so a quiet-but-healthy connection keeps refreshing _last_line_ts even
        # with zero new messages (review issue #1).
        last = max(self._last_event_ts, self._last_line_ts)
        if last == 0.0:
            return True   # not yet received anything; grace period
        return (time.time() - last) < self.HEARTBEAT_TIMEOUT_SEC

    def _note_line(self) -> None:
        """Record that the SSE stream produced a line (incl. heartbeat)."""
        self._last_line_ts = time.time()

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
                        # ANY line (heartbeat ': hb', 'event:' frames, blank
                        # keep-alives) proves the stream is alive — record it for
                        # is_alive() before filtering down to data lines.
                        if line is not None:
                            self._note_line()
                        # Only data lines carry JSON. 'event:' lines, ':' heartbeat
                        # comments and blank lines are skipped; the per-frame
                        # `event` key inside the JSON is what distinguishes async
                        # update frames (handled in _translate_event).
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
        """Translate one bare-data-frame payload into a WxMsg.

        Returns None for async-update frames (which carry an `event` key),
        heartbeats, and malformed payloads. See docs/sidecar-verification.md
        for the field contract and the semantic gaps SSE does NOT provide
        (from_user wxid / direction / numeric type / msg_id).
        """
        if not isinstance(event, dict):
            return None
        # Async update / tool frames carry an `event` key — not new messages.
        if "event" in event:
            return None
        username = event.get("username")
        if not username:
            return None
        # timestamp must be present AND parseable — a dirty ts is a bad frame,
        # not a t=0 message (review issue #8: silent collapse to id=ts=0).
        if "timestamp" not in event:
            return None
        try:
            ts = int(event["timestamp"])
        except (TypeError, ValueError):
            LOG.warning("dropping frame with unparseable timestamp: %r",
                        event.get("timestamp"))
            return None

        raw_type = event.get("type")
        if isinstance(raw_type, int):
            type_num = raw_type
        else:
            type_num = _TYPE_CN_TO_NUM.get(str(raw_type), 0)
        content = str(event.get("content", ""))
        is_group = bool(event.get("is_group"))

        # filehelper bridge — the killer adaptation. A message in the filehelper
        # session is by nature written by the operator (only self can post to
        # 文件传输助手). SSE carries no direction/receiver, so bridge it so the
        # command channel keeps working: mark is_self + receiver=filehelper.
        # Guard with `not is_group` so a group whose id literally equals
        # 'filehelper' can't be privileged into a self-command (review issue #6).
        if username == FILEHELPER_WXID and not is_group:
            return WxMsg(
                id=ts, type=type_num, sender=FILEHELPER_WXID, roomid="",
                content=content, is_self=True, ts=ts, receiver=FILEHELPER_WXID,
            )

        # Normal message. SSE gives no sender wxid for groups (only a display
        # name) and no direction. Map what's available:
        if is_group:
            sender = str(event.get("sender") or "")  # group-member display name
            roomid = str(username)
        else:
            sender = str(username)                    # 1-on-1: username is peer wxid
            roomid = ""
        return WxMsg(
            id=ts, type=type_num, sender=sender, roomid=roomid,
            content=content, is_self=False, ts=ts, receiver="",
        )
