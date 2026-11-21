"""Bounded, thread-safe event sequence with replay support."""

from __future__ import annotations

import threading
from collections import deque


class EventBuffer:
    def __init__(self, max_events: int = 10_000):
        self._events: deque[dict] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._seq = 0

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def append(self, event: dict) -> dict:
        with self._lock:
            self._seq += 1
            stored = {**event, "seq": self._seq}
            self._events.append(stored)
            return stored

    def since(self, seq: int) -> list[dict]:
        with self._lock:
            return [event for event in self._events if event["seq"] > seq]

    def first_seq(self) -> int | None:
        with self._lock:
            return self._events[0]["seq"] if self._events else None
