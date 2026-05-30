from __future__ import annotations
import sqlite3
import threading
from pathlib import Path


class ContactsBackend:
    """Read-only access to the decrypted Weixin contact DB with in-memory cache.

    Schema verified against the wechat-decrypt sidecar source
    (docs/sidecar-verification.md): the real `contact` table has columns
    `username` / `nick_name` (underscore!) / `remark` and NO `type` column.
    There is NO `chatroom_member_nickname` table in Weixin 4.x; per-room member
    display names live in the message DB (Name2Id rowid->user_name + contact
    lookup) — recovering those belongs to the receive layer, so alias_in_room
    degrades to the global contact display name here.
    The decrypted DB is plain SQLite (sidecar writes a standard
    'SQLite format 3' file), so standard sqlite3 opens it with no key.
    """

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._by_wxid: dict[str, str] = {}    # wxid -> display name (remark > nick_name)
        self._by_name: dict[str, str] = {}    # display name -> wxid
        self._room_alias: dict[tuple[str, str], str] = {}  # (wxid, roomid) -> display
        self._raw: dict[str, dict] = {}       # wxid -> raw row

    def refresh(self) -> None:
        with self._lock:
            con = sqlite3.connect(self._db_path)
            con.row_factory = sqlite3.Row
            try:
                self._load_contacts(con)
                self._load_room_aliases(con)
            finally:
                con.close()

    def _load_contacts(self, con: sqlite3.Connection) -> None:
        self._by_wxid.clear()
        self._by_name.clear()
        self._raw.clear()
        # Real Weixin 4.x columns: username / nick_name / remark (no `type`).
        for row in con.execute("SELECT username, nick_name, remark FROM contact"):
            wxid = row["username"]
            nickname = row["nick_name"] or ""
            remark = row["remark"] or ""
            display = remark or nickname or wxid
            self._by_wxid[wxid] = display
            # Reverse index: prefer remark, then nick_name; both point to wxid.
            if remark:
                self._by_name[remark] = wxid
            if nickname and nickname not in self._by_name:
                self._by_name[nickname] = wxid
            self._raw[wxid] = dict(row)

    def _load_room_aliases(self, con: sqlite3.Connection) -> None:
        self._room_alias.clear()
        # NOTE: real Weixin 4.x has NO chatroom_member_nickname table (verified —
        # docs/sidecar-verification.md). On a real decrypted DB this query raises
        # OperationalError and we degrade to the global display name. The table is
        # still read if present (e.g. fixtures or a future enriched DB).
        try:
            cursor = con.execute(
                "SELECT roomid, wxid, display_name FROM chatroom_member_nickname"
            )
        except sqlite3.OperationalError:
            return  # Table absent on real Weixin 4.x; alias_in_room falls back.
        for row in cursor:
            self._room_alias[(row["wxid"], row["roomid"])] = row["display_name"]

    def wxid_to_name(self, wxid: str) -> str | None:
        return self._by_wxid.get(wxid)

    def name_to_wxid(self, name: str) -> str | None:
        return self._by_name.get(name)

    def alias_in_room(self, wxid: str, roomid: str) -> str:
        in_room = self._room_alias.get((wxid, roomid))
        if in_room:
            return in_room
        return self.wxid_to_name(wxid) or wxid

    def all_contacts(self) -> dict[str, str]:
        return dict(self._by_wxid)
