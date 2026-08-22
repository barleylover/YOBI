from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from app.services.keyed_lock import KeyedLockRegistry


def test_keyed_lock_serializes_same_key_and_releases_registry_entries() -> None:
    registry = KeyedLockRegistry()
    start = Barrier(4)
    state_guard = Lock()
    active = 0
    maximum_active = 0

    def worker() -> None:
        nonlocal active, maximum_active
        start.wait()
        with registry.hold("recommendation-1"):
            with state_guard:
                active += 1
                maximum_active = max(maximum_active, active)
            with state_guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _index: worker(), range(4)))

    assert maximum_active == 1
    assert registry.active_key_count == 0


def test_keyed_lock_releases_entry_when_work_raises() -> None:
    registry = KeyedLockRegistry()

    with pytest.raises(RuntimeError, match="boom"):
        with registry.hold("comparison-1"):
            raise RuntimeError("boom")

    assert registry.active_key_count == 0
