from __future__ import annotations
import threading
from collections import deque
from typing import Iterable


class RingBuffer:
    """Thread-safe fixed-capacity FIFO. Newest items at the end."""

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._dq: deque = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def append(self, item) -> int:
        with self._lock:
            self._seq += 1
            self._dq.append((self._seq, item))
            return self._seq

    def extend(self, items: Iterable) -> None:
        with self._lock:
            for it in items:
                self._seq += 1
                self._dq.append((self._seq, it))

    def snapshot(self, since_seq: int = 0, limit: int | None = None) -> list[tuple[int, object]]:
        with self._lock:
            data = [pair for pair in self._dq if pair[0] > since_seq]
        if limit is not None and len(data) > limit:
            data = data[-limit:]
        return data

    def tail(self, n: int) -> list[tuple[int, object]]:
        with self._lock:
            data = list(self._dq)
        return data[-n:]

    def __len__(self) -> int:
        with self._lock:
            return len(self._dq)

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq
