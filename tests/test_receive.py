from queue import Queue, Empty
import pytest

from wx.msg import WxMsg
from wx.receive import ReceiveBackend
from tests.fixtures import sample_sse_events as evs


@pytest.fixture
def queue():
    return Queue()


@pytest.fixture
def backend(queue):
    # No subprocess; we feed events straight into the translator.
    return ReceiveBackend(decrypt_repo=None, sidecar_url="http://nowhere", msg_queue=queue)


# ---- bare-frame translation ----

def test_translate_text_dm(backend):
    msg = backend._translate_event(evs.TEXT_DM)
    assert isinstance(msg, WxMsg)
    assert msg.type == 1                  # '文本' mapped back to numeric 1
    assert msg.sender == "wxid_alice"     # 1-on-1 sender == username (peer wxid)
    assert msg.roomid == ""               # not a group
    assert msg.content == "hi bot"
    assert msg.is_self is False
    assert msg.receiver == ""             # SSE provides no receiver for normal DMs
    assert msg.ts == 1700000000


def test_translate_group(backend):
    msg = backend._translate_event(evs.TEXT_GROUP_AT)
    assert msg.roomid == "123@chatroom"   # group id == username
    assert msg.from_group() is True
    assert msg.is_at("wxid_bot") is True  # content has an @ token
    assert msg.type == 1
    assert msg.sender == "张三"           # group: sender is the member display name


def test_translate_image_type_maps_to_3(backend):
    msg = backend._translate_event(evs.IMAGE_DM)
    assert msg.type == 3                  # '图片' → 3


def test_filehelper_bridge_marks_self_and_receiver(backend):
    # The killer adaptation: a message in the filehelper session is, by nature,
    # written by the operator. Bridge it so the command channel keeps working
    # even though SSE carries no direction/receiver field.
    msg = backend._translate_event(evs.FILEHELPER_CMD)
    assert msg is not None
    assert msg.is_self is True
    assert msg.receiver == "filehelper"
    assert msg.content == "/status"
    assert msg.type == 1


def test_async_image_update_ignored(backend):
    # Frames carrying an `event` key are async updates, not new messages.
    assert backend._translate_event(evs.IMAGE_UPDATE) is None


def test_async_tool_log_ignored(backend):
    assert backend._translate_event(evs.TOOL_LOG) is None


def test_translate_missing_username_returns_none(backend):
    assert backend._translate_event({"timestamp": 1, "content": "x", "type": "文本"}) is None


def test_unknown_chinese_type_is_zero(backend):
    ev = dict(evs.TEXT_DM)
    ev["type"] = "天外飞仙"
    msg = backend._translate_event(ev)
    assert msg is not None
    assert msg.type == 0                  # unknown Chinese label → 0, still delivered


# ---- queue plumbing ----

def test_enqueue_filters_async_frames(backend, queue):
    backend._consume_event(evs.TEXT_DM)
    backend._consume_event(evs.IMAGE_UPDATE)    # async → dropped
    backend._consume_event(evs.TEXT_GROUP_AT)
    assert queue.qsize() == 2
    m1 = queue.get_nowait()
    m2 = queue.get_nowait()
    assert m1.content == "hi bot"
    assert m2.roomid == "123@chatroom"
    with pytest.raises(Empty):
        queue.get_nowait()


# ---- heartbeat / liveness (review issue #1) ----

class _FakeProc:
    """Stand-in for a running subprocess: poll() None == alive."""
    def poll(self):
        return None


def test_heartbeat_line_keeps_alive(backend, monkeypatch):
    # A healthy sidecar emits ': hb' every 15s with no new messages. is_alive()
    # must treat ANY line (incl. heartbeat) as proof of life, not only delivered
    # messages — otherwise a quiet-but-healthy sidecar is wrongly marked dead.
    backend._proc = _FakeProc()
    t = [1000.0]
    monkeypatch.setattr("wx.receive.time.time", lambda: t[0])

    backend._note_line()          # heartbeat / any SSE line arrives at t=1000
    t[0] = 1000.0 + 25            # 25s later, still < 30s timeout, no new message
    assert backend.is_alive() is True


def test_no_lines_for_timeout_marks_dead(backend, monkeypatch):
    backend._proc = _FakeProc()
    t = [1000.0]
    monkeypatch.setattr("wx.receive.time.time", lambda: t[0])

    backend._note_line()
    t[0] = 1000.0 + 31            # past HEARTBEAT_TIMEOUT_SEC with zero traffic
    assert backend.is_alive() is False


def test_message_also_counts_as_liveness(backend, monkeypatch):
    backend._proc = _FakeProc()
    t = [2000.0]
    monkeypatch.setattr("wx.receive.time.time", lambda: t[0])
    backend._consume_event(evs.TEXT_DM)   # delivering a message refreshes liveness
    t[0] = 2000.0 + 10
    assert backend.is_alive() is True


def test_dead_when_proc_exited(backend):
    class _Exited:
        def poll(self):
            return 1   # non-None == process exited
    backend._proc = _Exited()
    assert backend.is_alive() is False


# ---- filehelper bridge needs an is_group guard (review issue #6) ----

def test_filehelper_bridge_skipped_for_group(backend):
    # A group whose id literally equals 'filehelper' must NOT be privileged into
    # a self-command; only a real 1-on-1 filehelper session is the operator.
    ev = {
        "username": "filehelper", "is_group": True, "sender": "张三",
        "timestamp": 1700000000, "type": "文本", "content": "/pause",
    }
    msg = backend._translate_event(ev)
    assert msg is not None
    assert msg.is_self is False          # not bridged
    assert msg.roomid == "filehelper"    # treated as a normal group


def test_filehelper_bridge_applies_for_dm(backend):
    ev = {
        "username": "filehelper", "is_group": False,
        "timestamp": 1700000000, "type": "文本", "content": "/status",
    }
    msg = backend._translate_event(ev)
    assert msg.is_self is True
    assert msg.receiver == "filehelper"


# ---- dirty timestamp is a bad frame (review issue #8) ----

def test_unparseable_timestamp_dropped(backend):
    for bad in (None, "", "abc", "12x"):
        ev = {"username": "wxid_x", "timestamp": bad, "type": "文本", "content": "hi"}
        assert backend._translate_event(ev) is None, f"ts={bad!r} should drop"


def test_numeric_string_timestamp_ok(backend):
    ev = {"username": "wxid_x", "timestamp": "1700000000", "type": "文本", "content": "hi"}
    msg = backend._translate_event(ev)
    assert msg is not None
    assert msg.ts == 1700000000
