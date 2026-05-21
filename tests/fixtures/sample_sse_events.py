"""Canned wechat-decrypt SSE events.

The real event schema is discovered during Task 0.3 verification and
recorded in docs/sidecar-verification.md. These shapes match what we expect:
each event is a dict with `event_type` and `data` keys.
"""

TEXT_DM = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1001,
        "type": 1,
        "from_user": "wxid_alice",
        "to_user": "wxid_self",
        "room_id": "",
        "content": "hi bot",
        "is_send": 0,
        "timestamp": 1700000000,
    },
}

TEXT_GROUP_AT = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1002,
        "type": 1,
        "from_user": "wxid_alice",
        "to_user": "123@chatroom",
        "room_id": "123@chatroom",
        "content": "@WxBot help",
        "is_send": 0,
        "timestamp": 1700000010,
    },
}

FRIEND_REQUEST = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1003,
        "type": 37,
        "from_user": "wxid_new",
        "to_user": "wxid_self",
        "room_id": "",
        "content": "<msg encryptusername='v3_xxx' ticket='v4_xxx' scene='14' />",
        "is_send": 0,
        "timestamp": 1700000020,
    },
}

SELF_MESSAGE = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1004,
        "type": 1,
        "from_user": "wxid_self",
        "to_user": "wxid_alice",
        "room_id": "",
        "content": "I'm replying",
        "is_send": 1,
        "timestamp": 1700000030,
    },
}

UNRELATED_EVENT = {
    "event_type": "key_refreshed",
    "data": {"timestamp": 1700000040},
}
