from __future__ import annotations

from threading import Lock
from typing import Literal

FailureMode = Literal["normal", "force_genai_timeout", "force_payment_failure", "force_fallback"]


class DemoControl:
    def __init__(self) -> None:
        self._mode: FailureMode = "normal"
        self._lock = Lock()

    @property
    def mode(self) -> FailureMode:
        with self._lock:
            return self._mode

    def set_mode(self, mode: FailureMode) -> None:
        with self._lock:
            self._mode = mode

