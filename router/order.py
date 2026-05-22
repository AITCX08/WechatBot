from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from typing import Optional

from wx.msg import WxMsg
from router.order_draft import OrderDraft, REQUIRED_FIELDS

LOG = logging.getLogger(__name__)


class OrderHandler:
    CONFIRM_TOKENS = ("确认", "确定", "yes", "y", "1")
    CANCEL_TOKENS = ("取消", "放弃", "no", "n", "0", "退出")

    FIELD_LABELS = {
        "school": "学校",
        "user": "学号/账号",
        "password": "密码",
        "platform": "平台编号",
        "kcid": "课程 ID",
        "kcname": "课程名称",
    }

    def __init__(
        self,
        lexue_creds: dict,
        llm,
        wx,
        safety: dict,
        audit_log_path: Path,
        intent_prompt: str,
        extract_prompt: str,
    ):
        self.lexue_creds = lexue_creds
        self.llm = llm
        self.wx = wx
        self.safety = safety
        self.audit_log_path = Path(audit_log_path)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.intent_prompt = intent_prompt
        self.extract_prompt = extract_prompt
        self._pending: dict[str, OrderDraft] = {}     # wxid -> draft
        self._history: dict[str, list[str]] = {}      # wxid -> [recent msgs]
        self._daily_count = self._count_today_orders()
        self._last_attempt: dict[str, float] = {}     # cooldown per user

    # ---- public ----
    def is_pending_for(self, wxid: str) -> bool:
        draft = self._pending.get(wxid)
        if draft is None:
            return False
        if draft.is_expired(self.safety["confirm_timeout_sec"]):
            self._pending.pop(wxid, None)
            return False
        return True

    def looks_like_order_intent(self, text: str) -> bool:
        raw = ""
        try:
            raw = self.llm.get_answer(self.intent_prompt.format(message=text), "intent")
            obj = json.loads(raw)
            return bool(obj.get("is_order_intent"))
        except Exception as e:
            LOG.warning("intent parse failed: %s; raw=%r", e, raw)
            return False

    def handle_new_order_message(self, msg: WxMsg) -> None:
        if self._on_cooldown(msg.sender):
            self.wx.send_text("操作太频繁，请稍后再试", msg.sender)
            return
        self._history.setdefault(msg.sender, []).append(msg.content)
        draft = self._extract(msg)
        self._pending[msg.sender] = draft
        self._advance(draft, msg.sender)

    def on_user_reply(self, msg: WxMsg) -> None:
        draft = self._pending.get(msg.sender)
        if draft is None:
            return

        text = msg.content.strip()
        if text in self.CANCEL_TOKENS:
            self._pending.pop(msg.sender, None)
            self.wx.send_text("已取消下单", msg.sender)
            self._audit({"event": "cancel", "wxid": msg.sender, "draft": draft.to_dict()})
            return

        if draft.is_complete() and text in self.CONFIRM_TOKENS:
            draft.confirmed = True
            result = self.place_order(draft)
            self._pending.pop(msg.sender, None)
            self.wx.send_text(self._format_result(result), msg.sender)
            return

        # Otherwise: treat reply as additional info, re-extract
        draft.extract_rounds += 1
        if draft.extract_rounds >= self.safety["max_extract_rounds"]:
            self._pending.pop(msg.sender, None)
            self.wx.send_text(
                "信息收集次数过多，已放弃本次下单；请联系客服处理。", msg.sender
            )
            self._audit({"event": "abort_max_rounds", "wxid": msg.sender, "draft": draft.to_dict()})
            return

        self._history.setdefault(msg.sender, []).append(msg.content)
        updated = self._extract(msg)
        draft.merge(updated.to_dict())
        self._advance(draft, msg.sender)

    def place_order(self, draft: OrderDraft):
        if self._daily_count >= self.safety["daily_limit"]:
            self._audit({"event": "daily_limit_hit", "draft": draft.to_dict()})
            return {"code": -2, "msg": "今日下单已达上限"}
        if self.safety.get("dry_run"):
            self._audit({"event": "place_dry_run", "draft": draft.to_dict()})
            self._daily_count += 1
            return {"code": 1, "msg": "下单成功 (dry_run)"}
        # Real call:
        try:
            from Lexxue_api import xd
            result = xd(
                self.lexue_creds,
                draft.school, draft.user, draft.password,
                draft.platform, draft.kcname, draft.kcid,
            )
            self._daily_count += 1
            self._audit({"event": "place_real", "draft": draft.to_dict(), "result": result})
            return result
        except Exception as e:
            LOG.error("place_order failed: %s", e)
            self._audit({"event": "place_error", "draft": draft.to_dict(), "error": str(e)})
            return {"code": -1, "msg": f"下单失败: {e}"}

    # ---- internals ----
    def _advance(self, draft: OrderDraft, wxid: str) -> None:
        if draft.is_complete():
            self.wx.send_text(draft.summary_for_confirmation(), wxid)
        else:
            missing_labels = [self.FIELD_LABELS[f] for f in draft.missing_fields()]
            prompt = "请补充以下信息: " + "、".join(missing_labels)
            self.wx.send_text(prompt, wxid)

    def _extract(self, msg: WxMsg) -> OrderDraft:
        history = "\n".join(self._history.get(msg.sender, [])[-5:])
        try:
            raw = self.llm.get_answer(
                self.extract_prompt.format(history=history, message=msg.content),
                msg.sender,
            )
            obj = json.loads(raw)
        except Exception as e:
            LOG.warning("extract parse failed: %s", e)
            obj = {}
        return OrderDraft(
            school=obj.get("school"),
            user=obj.get("user"),
            password=obj.get("password"),
            platform=obj.get("platform"),
            kcid=obj.get("kcid"),
            kcname=obj.get("kcname"),
            requester_wxid=msg.sender,
            created_at=int(time.time()),
        )

    def _on_cooldown(self, wxid: str) -> bool:
        last = self._last_attempt.get(wxid, 0.0)
        cd = self.safety.get("per_user_cooldown_sec", 0)
        now = time.time()
        if now - last < cd:
            return True
        self._last_attempt[wxid] = now
        return False

    def _audit(self, event: dict) -> None:
        event["ts"] = int(time.time())
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        # Mirror into the dashboard ring buffer (best-effort).
        try:
            from dashboard.state import get_state
            get_state().audit.append(event)
        except Exception:
            pass

    def _count_today_orders(self) -> int:
        if not self.audit_log_path.exists():
            return 0
        today = time.strftime("%Y-%m-%d")
        n = 0
        for line in self.audit_log_path.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
                if obj.get("event", "").startswith("place") and \
                   time.strftime("%Y-%m-%d", time.localtime(obj.get("ts", 0))) == today:
                    n += 1
            except Exception:
                continue
        return n

    def _format_result(self, result: dict) -> str:
        if result.get("code") in (1, "1"):
            return f"下单成功: {result.get('msg', '')}"
        return f"下单失败: {result.get('msg', '未知错误')}"
