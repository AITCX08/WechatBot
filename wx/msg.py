from __future__ import annotations
from dataclasses import dataclass


@dataclass
class WxMsg:
    """Wire-compatible substitute for wcferry.WxMsg.

    Only carries fields and methods actually consulted by robot.py.
    """
    id: int
    type: int                # 1=text, 3=image, 37=friend request, 10000=system
    sender: str              # wxid of the sender
    roomid: str              # group id ("" for DM)
    content: str             # text content or XML payload
    is_self: bool
    ts: int

    def from_group(self) -> bool:
        return bool(self.roomid)

    def from_self(self) -> bool:
        return self.is_self

    def is_at(self, wxid: str) -> bool:
        # Group @ is encoded as "@<displayname>" in Weixin clients.
        # We don't have a perfect wxid→displayname mapping at parse time,
        # so the dispatcher will pass the bot's own wxid AND resolve via
        # ContactsBackend later. Here we just check whether the content
        # contains any "@" token in a group context.
        if not self.from_group():
            return False
        return "@" in self.content
