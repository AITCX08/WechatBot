from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


REQUIRED_FIELDS = ("school", "user", "password", "platform", "kcid", "kcname")


@dataclass
class OrderDraft:
    school: Optional[str]
    user: Optional[str]
    password: Optional[str]
    platform: Optional[str]
    kcid: Optional[str]
    kcname: Optional[str]
    requester_wxid: str
    created_at: int
    confirmed: bool = False
    extract_rounds: int = 0

    def is_complete(self) -> bool:
        return all(getattr(self, f) for f in REQUIRED_FIELDS)

    def missing_fields(self) -> list[str]:
        return [f for f in REQUIRED_FIELDS if not getattr(self, f)]

    def is_expired(self, timeout_sec: int) -> bool:
        return (int(time.time()) - self.created_at) > timeout_sec

    def merge(self, updates: dict) -> None:
        for f in REQUIRED_FIELDS:
            if f in updates and updates[f]:
                setattr(self, f, updates[f])

    def summary_for_confirmation(self) -> str:
        return (
            f"确认下单：\n"
            f"学校: {self.school}\n"
            f"课程: {self.kcname} (ID: {self.kcid})\n"
            f"平台: {self.platform}\n"
            f"账号: {self.user}\n"
            f"回复'确认'下单 / '取消'放弃 (5分钟有效)"
        )

    def to_dict(self) -> dict:
        return asdict(self)
