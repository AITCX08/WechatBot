from __future__ import annotations
import logging
from pathlib import Path
from queue import Queue, Empty

from wx.contacts import ContactsBackend
from wx.receive import ReceiveBackend
from wx.send import SendBackend
from wx.msg import WxMsg

LOG = logging.getLogger(__name__)


class WxAdapter:
    """Facade exposing a wcferry.Wcf-compatible subset, backed by Weixin 4.x.

    Methods mirror the wcferry calls actually used by robot.py:
      get_self_wxid, send_text, send_image, query_sql, get_alias_in_chatroom,
      accept_new_friend, enable_receiving_msg, get_msg, is_receiving_msg
    """

    def __init__(
        self,
        weixin_exe: Path,
        sidecar_url: str,
        decrypted_db_path: Path,
        decrypt_repo: Path | None = None,
        self_wxid: str = "filehelper",
    ):
        self._weixin_exe = Path(weixin_exe)
        self._self_wxid = self_wxid
        self._queue: Queue[WxMsg] = Queue()
        self._contacts = ContactsBackend(decrypted_db_path)
        self._send = SendBackend(weixin_exe=self._weixin_exe, contacts=self._contacts)
        self._recv = ReceiveBackend(
            decrypt_repo=decrypt_repo, sidecar_url=sidecar_url, msg_queue=self._queue
        )

    # ---- init / lifecycle ----
    def setup(self) -> None:
        """Idempotent: refresh contacts, attach send window, start sidecar."""
        self._contacts.refresh()
        self._send.attach()
        # ReceiveBackend.start() is deferred to enable_receiving_msg.

    # ---- wcferry-compatible API ----
    def get_self_wxid(self) -> str:
        return self._self_wxid

    def send_text(self, msg: str, receiver: str, at_list: str = "") -> int:
        at_wxids = tuple(w for w in at_list.split(",") if w)
        ok = self._send.send_text(receiver, msg, at_wxids=at_wxids)
        return 0 if ok else 1

    def send_image(self, image_path, receiver: str) -> int:
        ok = self._send.send_image(receiver, Path(image_path))
        return 0 if ok else 1

    def query_sql(self, db: str, sql: str) -> list[dict]:
        # robot.py only uses: SELECT UserName, NickName FROM Contact
        normalised = sql.strip().upper().replace("  ", " ")
        if "FROM CONTACT" in normalised and "USERNAME" in normalised:
            return [
                {"UserName": wxid, "NickName": name}
                for wxid, name in self._contacts.all_contacts().items()
            ]
        raise NotImplementedError(
            f"WxAdapter.query_sql only supports Contact lookup; got: {sql}"
        )

    def get_alias_in_chatroom(self, wxid: str, roomid: str) -> str:
        return self._contacts.alias_in_room(wxid, roomid)

    def accept_new_friend(self, v3: str, v4: str, scene: int) -> int:
        # wcferry-signature; we ignore v3/v4/scene and drive the UI directly.
        ok = self._send.accept_friend_request_via_ui()
        return 0 if ok else 1

    # ---- receive side ----
    def enable_receiving_msg(self) -> None:
        self._recv.start()

    def is_receiving_msg(self) -> bool:
        return self._recv.is_alive()

    def get_msg(self, timeout: float = 1.0) -> WxMsg:
        # raises queue.Empty on timeout (matches what robot.py already handles)
        return self._queue.get(timeout=timeout)

    def cleanup(self) -> None:
        self._recv.stop()
