from __future__ import annotations
import logging
import time
from pathlib import Path
from threading import Lock

import pyperclip
import uiautomation as uia

from wx.constants import FILEHELPER_WXID
from wx.contacts import ContactsBackend

LOG = logging.getLogger(__name__)


class SendBackend:
    """Drive Weixin 4.x via UIA. Single instance per Weixin process."""

    MAIN_WINDOW_NAMES = ("微信", "Weixin")
    SEARCH_BOX_NAME = "搜索"
    PER_SEND_INTERVAL_SEC = 0.8       # throttle to avoid risk control
    OPEN_CHAT_TIMEOUT_SEC = 5
    POST_OPEN_SETTLE_SEC = 0.3

    # Built-in WeChat pseudo-contacts that are NOT rows in the contact table.
    # Without this, send_text("filehelper", ...) can't resolve a display name
    # and the whole filehelper command-reply channel is dead (review issue #0).
    BUILTIN_NAMES = {
        FILEHELPER_WXID: "文件传输助手",
    }

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

    # ---- recipient resolution ----
    def _resolve_display(self, receiver_wxid: str) -> str | None:
        """Resolve a wxid/roomid into a search-box-usable display name.

        Returns None when the recipient cannot be opened via the search box:
          - unknown contact (not in the decrypted DB)
          - a raw 'xxx@chatroom' id (group with no remark/nick_name) — the
            internal room id is NOT a searchable conversation label, so pasting
            it would open the wrong/no chat (review issue #2).
        Built-in pseudo-contacts (filehelper) are resolved here since they are
        not rows in the contact table (review issue #0).
        """
        if not receiver_wxid:
            return None
        builtin = self.BUILTIN_NAMES.get(receiver_wxid)
        if builtin:
            return builtin
        display = self._contacts.wxid_to_name(receiver_wxid)
        if not display:
            return None
        if display.endswith("@chatroom"):
            # raw room-id fallback fired → not searchable
            return None
        return display

    # ---- public ----
    def send_text(
        self, receiver_wxid: str, msg: str, at_wxids: tuple[str, ...] = ()
    ) -> bool:
        display = self._resolve_display(receiver_wxid)
        if not display:
            LOG.error("send_text: cannot resolve a searchable name for %s", receiver_wxid)
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
        display = self._resolve_display(receiver_wxid)
        if not display:
            LOG.error("send_image: cannot resolve a searchable name for %s", receiver_wxid)
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
        # KNOWN LIMITATION (review issue #3, needs_phone): search+Enter selects
        # the FIRST result, which for duplicate/prefix-matching names may be the
        # wrong conversation. A robust fix reads the opened chat's title bar and
        # verifies it equals display_name — but the title-bar control locator
        # can only be validated against a real Weixin client, so it is left as a
        # documented真机 task (docs/uia-anchors.md) rather than speculative code.

    @staticmethod
    def _pick_input_edit(edits: list) -> object | None:
        """Choose the message-input EditControl from a list of Edit controls.

        The search box is ALSO an EditControl, so naively taking the last Edit
        can land the reply in the search box (review issue #4). Exclude any Edit
        named '搜索', then take the bottom-most remaining one (the chat input
        sits at the bottom of the window).
        """
        candidates = [e for e in edits if getattr(e, "Name", "") != "搜索"]
        if not candidates:
            return None
        return candidates[-1]

    def _focus_input(self) -> None:
        # Collect all EditControls, then pick the real input (not the search box).
        edits = []

        def _collect(ctrl, depth):
            if ctrl.ControlTypeName == "EditControl":
                edits.append(ctrl)

        uia.WalkControl(self._main, _collect, maxDepth=15)
        target = self._pick_input_edit(edits)
        if target is None:
            raise RuntimeError("no usable EditControl found for message input")
        target.Click(simulateMove=False)
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
