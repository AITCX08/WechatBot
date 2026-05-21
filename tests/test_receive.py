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
    # We instantiate without starting the subprocess; we'll feed events directly.
    return ReceiveBackend(
        decrypt_repo=None, sidecar_url="http://nowhere", msg_queue=queue
    )


def test_translate_text_dm(backend):
    msg = backend._translate_event(evs.TEXT_DM)
    assert isinstance(msg, WxMsg)
    assert msg.type == 1
    assert msg.sender == "wxid_alice"
    assert msg.roomid == ""
    assert msg.content == "hi bot"
    assert msg.is_self is False


def test_translate_group_at(backend):
    msg = backend._translate_event(evs.TEXT_GROUP_AT)
    assert msg.roomid == "123@chatroom"
    assert msg.from_group() is True
    assert msg.is_at("wxid_bot") is True


def test_translate_friend_request(backend):
    msg = backend._translate_event(evs.FRIEND_REQUEST)
    assert msg.type == 37


def test_translate_self_message_flag(backend):
    msg = backend._translate_event(evs.SELF_MESSAGE)
    assert msg.is_self is True


def test_translate_unrelated_event_returns_none(backend):
    assert backend._translate_event(evs.UNRELATED_EVENT) is None


def test_enqueue_via_internal_pipe(backend, queue):
    # Simulate the SSE consumer pushing translated events to the queue.
    backend._consume_event(evs.TEXT_DM)
    backend._consume_event(evs.UNRELATED_EVENT)  # should be filtered out
    backend._consume_event(evs.TEXT_GROUP_AT)
    assert queue.qsize() == 2
    m1 = queue.get_nowait()
    m2 = queue.get_nowait()
    assert m1.id == 1001
    assert m2.id == 1002
    with pytest.raises(Empty):
        queue.get_nowait()
