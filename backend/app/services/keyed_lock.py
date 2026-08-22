from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock


@dataclass
class _LockEntry:
    lock: Lock
    users: int = 0


class KeyedLockRegistry:
    """Serialize work by key and release unused locks without waiter races."""

    def __init__(self) -> None:
        self._guard = Lock()
        self._entries: dict[str, _LockEntry] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _LockEntry(lock=Lock())
                self._entries[key] = entry
            entry.users += 1
        try:
            with entry.lock:
                yield
        finally:
            with self._guard:
                entry.users -= 1
                if entry.users == 0 and self._entries.get(key) is entry:
                    self._entries.pop(key, None)

    @property
    def active_key_count(self) -> int:
        with self._guard:
            return len(self._entries)
