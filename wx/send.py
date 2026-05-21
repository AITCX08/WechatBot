from __future__ import annotations
import logging
import time
from pathlib import Path
from threading import Lock

import pyperclip
import uiautomation as uia

from wx.contacts import ContactsBackend

LOG = logging.getLogger(__name__)


class SendBackend:
    """Drive Weixin 4.x via UIA. Single instance per Weixin process."""

    MAIN_WINDOW_NAMES = ("微信", "Weixin")
    SEARCH_BOX_NAME = "搜索"
    PER_SEND_INTERVAL_SEC = 0.8       # throttle to avoid risk control
    OPEN_CHAT_TIMEOUT_SEC = 5
    POST_OPEN_SETTLE_SEC = 0.3

    def __init__(self, weixin_exe: Path, contacts: ContactsBackend):
        self._exe = Path(weixin_exe)
        self._contacts = contacts
        self._main: uia.WindowControl | None = None
        self._send_lock = Lock()
        self._last_send_ts = 0.0

    # ---- lifecycle ----
    def attach(self) -> None:
        for name in self.MAIN_WINDOW_NAMES:
            w = uia.WindowControl(searchDepth=2, Name=name)
            if w.Exists(maxSearchSeconds=2):
                self._main = w
                LOG.info("attached to Weixin window: %s", name)
                return
        raise RuntimeError(
            f"Weixin main window not found (tried {self.MAIN_WINDOW_NAMES}). "
            "Make sure Weixin is running and logged in."
        )

    # ---- public ----
    def send_text(
        self, receiver_wxid: str, msg: str, at_wxids: tuple[str, ...] = ()
    ) -> bool:
        display = self._contacts.wxid_to_name(receiver_wxid)
        if not display:
            LOG.error("send_text: no display name for %s", receiver_wxid)
            return False
        with self._send_lock:
            self._throttle()
            try:
                self._open_chat(display)
                self._focus_input()
                if at_wxids and "@" in msg:
                    self._send_with_ats(msg, at_wxids)
                else:
                    self._paste_and_send(msg)
                return True
            except Exception as e:
                LOG.error("send_text failed to %s: %s", display, e)
                return False

    def send_image(self, receiver_wxid: str, image_path: Path) -> bool:
        display = self._contacts.wxid_to_name(receiver_wxid)
        if not display:
            return False
        with self._send_lock:
            self._throttle()
            try:
                self._open_chat(display)
                self._focus_input()
                # Use Windows clipboard image insertion
                from PIL import Image
                import win32clipboard
                from io import BytesIO

                img = Image.open(image_path)
                output = BytesIO()
                img.convert("RGB").save(output, "BMP")
                data = output.getvalue()[14:]   # strip BMP header
                output.close()
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                finally:
                    win32clipboard.CloseClipboard()
                uia.SendKeys("{Ctrl}v")
                time.sleep(0.3)
                uia.SendKeys("{Enter}")
                return True
            except Exception as e:
                LOG.error("send_image failed: %s", e)
                return False

    def accept_friend_request_via_ui(self, requester_hint: str = "") -> bool:
        """Best-effort: open '新的朋友' panel and click the topmost '通过' button."""
        if self._main is None:
            self.attach()
        try:
            # Sidebar contains a 新的朋友 entry
            entry = self._main.TextControl(searchDepth=20, Name="新的朋友")
            if not entry.Exists(maxSearchSeconds=2):
                LOG.warning("'新的朋友' entry not found")
                return False
            entry.Click(simulateMove=False)
            time.sleep(0.5)
            accept_btn = self._main.ButtonControl(searchDepth=20, Name="接受")
            if not accept_btn.Exists(maxSearchSeconds=2):
                LOG.info("No pending friend request to accept")
                return False
            accept_btn.Click(simulateMove=False)
            return True
        except Exception as e:
            LOG.error("accept_friend_request_via_ui failed: %s", e)
            return False

    # ---- internals ----
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_send_ts
        if elapsed < self.PER_SEND_INTERVAL_SEC:
            time.sleep(self.PER_SEND_INTERVAL_SEC - elapsed)
        self._last_send_ts = time.time()

    def _open_chat(self, display_name: str) -> None:
        if self._main is None:
            self.attach()
        search = self._main.EditControl(searchDepth=10, Name=self.SEARCH_BOX_NAME)
        if not search.Exists(maxSearchSeconds=self.OPEN_CHAT_TIMEOUT_SEC):
            raise RuntimeError("search box not found")
        search.Click(simulateMove=False)
        time.sleep(0.1)
        # Clear any prior input then type the name
        uia.SendKeys("{Ctrl}a", waitTime=0.05)
        uia.SendKeys("{Delete}", waitTime=0.05)
        pyperclip.copy(display_name)
        uia.SendKeys("{Ctrl}v", waitTime=0.1)
        time.sleep(0.4)   # wait for search results to populate
        uia.SendKeys("{Enter}", waitTime=0.05)
        time.sleep(self.POST_OPEN_SETTLE_SEC)

    def _focus_input(self) -> None:
        # The message input is the bottom-most EditControl in the chat pane.
        # Heuristic: take the last EditControl encountered.
        edits = []

        def _collect(ctrl, depth):
            if ctrl.ControlTypeName == "EditControl":
                edits.append(ctrl)

        uia.WalkControl(self._main, _collect, maxDepth=15)
        if not edits:
            raise RuntimeError("no EditControl found for message input")
        edits[-1].Click(simulateMove=False)
        time.sleep(0.1)

    def _paste_and_send(self, text: str) -> None:
        pyperclip.copy(text)
        uia.SendKeys("{Ctrl}v", waitTime=0.1)
        time.sleep(0.1)
        uia.SendKeys("{Enter}", waitTime=0.05)

    def _send_with_ats(self, msg: str, at_wxids: tuple[str, ...]) -> None:
        # Caller has already injected " @displayname" placeholders into msg;
        # for accurate group @ we'd need to type "@" then pick from popup.
        # MVP: paste the whole message; @ token is plain text in this version.
        self._paste_and_send(msg)
