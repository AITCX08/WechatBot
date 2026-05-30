"""Canned wechat-decrypt SSE events — REAL bare-data-frame shape.

Verified against sidecar source (docs/sidecar-verification.md): a normal new
message is a BARE `data: <json>\\n\\n` frame whose JSON has top-level fields
time/timestamp/chat/username/is_group/sender/type(Chinese string)/type_icon/
content/unread/decrypt_ms/pages — NO event_type/data wrapper, NO msg_id/
from_user/to_user/room_id/is_send. Async update frames carry an `event` key
(image_update/rich_update/tool_log/tool_done) and must be ignored by the
message translator.
"""

# --- normal new message: 1-on-1 text ---
TEXT_DM = {
    "time": "14:23:05",
    "timestamp": 1700000000,
    "chat": "小爱",
    "username": "wxid_alice",    # 1-on-1 → username IS the peer's wxid
    "is_group": False,
    "sender": "",                # empty in 1-on-1
    "type": "文本",              # Chinese string, not a number
    "type_icon": "💬",
    "content": "hi bot",
    "unread": 1,
    "decrypt_ms": 12.3,
    "pages": 4,
}

# --- normal new message: group, contains an @ token ---
TEXT_GROUP_AT = {
    "time": "14:23:10",
    "timestamp": 1700000010,
    "chat": "测试群",
    "username": "123@chatroom",  # group → username is the room id
    "is_group": True,
    "sender": "张三",            # group-member display name (NOT a wxid)
    "type": "文本",
    "type_icon": "💬",
    "content": "@WxBot help",
    "unread": 2,
    "decrypt_ms": 9.1,
    "pages": 2,
}

# --- normal new message: image (type maps to numeric 3) ---
IMAGE_DM = {
    "time": "14:23:20",
    "timestamp": 1700000020,
    "chat": "小爱",
    "username": "wxid_alice",
    "is_group": False,
    "sender": "",
    "type": "图片",
    "type_icon": "🖼️",
    "content": "",
    "unread": 1,
    "decrypt_ms": 30.0,
    "pages": 8,
}

# --- operator's own message to 文件传输助手 (filehelper command channel) ---
FILEHELPER_CMD = {
    "time": "14:23:30",
    "timestamp": 1700000030,
    "chat": "文件传输助手",
    "username": "filehelper",    # filehelper session → only self can write here
    "is_group": False,
    "sender": "",
    "type": "文本",
    "type_icon": "💬",
    "content": "/status",
    "unread": 0,
    "decrypt_ms": 5.0,
    "pages": 1,
}

# --- async update frame: must be IGNORED by the message translator ---
IMAGE_UPDATE = {
    "event": "image_update",
    "timestamp": 1700000020,
    "username": "wxid_alice",
    "image_url": "/img/abcd1234.jpg",
}

# --- another async frame (tool log) — ignored ---
TOOL_LOG = {
    "event": "tool_log",
    "line": "decrypting...",
}
