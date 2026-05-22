import threading
import pytest

from dashboard.ring_buffer import RingBuffer


def test_append_returns_monotonic_seq():
    rb = RingBuffer(10)
    s1 = rb.append("a")
    s2 = rb.append("b")
    s3 = rb.append("c")
    assert s1 == 1
    assert s2 == 2
    assert s3 == 3


def test_overflow_drops_oldest():
    rb = RingBuffer(3)
    for c in "abcde":
        rb.append(c)
    items = [v for _, v in rb.snapshot()]
    assert items == ["c", "d", "e"]


def test_snapshot_since_seq():
    rb = RingBuffer(10)
    for c in "abcde":
        rb.append(c)
    # Get only items with seq > 2
    items = rb.snapshot(since_seq=2)
    assert [v for _, v in items] == ["c", "d", "e"]


def test_snapshot_limit():
    rb = RingBuffer(10)
    for c in "abcde":
        rb.append(c)
    items = rb.snapshot(limit=2)
    assert [v for _, v in items] == ["d", "e"]


def test_tail():
    rb = RingBuffer(10)
    for c in "abcde":
        rb.append(c)
    assert [v for _, v in rb.tail(2)] == ["d", "e"]
    assert [v for _, v in rb.tail(100)] == list("abcde")


def test_extend():
    rb = RingBuffer(10)
    rb.extend(["a", "b", "c"])
    assert len(rb) == 3
    assert rb.last_seq == 3


def test_thread_safe_append():
    rb = RingBuffer(1000)

    def worker():
        for i in range(100):
            rb.append(i)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(rb) == 1000
    seqs = [s for s, _ in rb.snapshot()]
    assert len(set(seqs)) == 1000  # all unique
    assert seqs == sorted(seqs)    # monotonic


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        RingBuffer(0)
    with pytest.raises(ValueError):
        RingBuffer(-1)
