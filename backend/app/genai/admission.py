from __future__ import annotations

from dataclasses import dataclass, field
from threading import BoundedSemaphore, Lock
from time import monotonic, sleep
from typing import Callable, TypeVar

from openai import APIStatusError, RateLimitError

T = TypeVar("T")


class ModelAdmissionCooldown(RuntimeError):
    """Fail fast while a shared model cooldown is active."""

    def __init__(self, remaining_seconds: float) -> None:
        super().__init__("MODEL_ADMISSION_COOLDOWN")
        self.remaining_seconds = max(0.0, remaining_seconds)


@dataclass
class _ModelGate:
    max_concurrent: int
    semaphore: BoundedSemaphore = field(init=False)
    state_lock: Lock = field(default_factory=Lock)
    cooldown_until: float = 0.0
    next_allowed_at: float = 0.0

    def __post_init__(self) -> None:
        self.semaphore = BoundedSemaphore(self.max_concurrent)


class SharedModelAdmissionController:
    """Process-wide admission control shared by every OCI model call path.

    Recommendation selection, presentation generation, chat, and note translation
    construct separate provider objects. A module-level registry makes their
    concurrency and cooldown state converge on the actual remote model instead of
    applying independent per-feature limits.
    """

    _registry_lock = Lock()
    _gates: dict[tuple[str, str, int], _ModelGate] = {}

    @classmethod
    def run(
        cls,
        *,
        endpoint: str,
        model: str,
        max_concurrent: int,
        min_interval_seconds: float,
        default_cooldown_seconds: float,
        call: Callable[[], T],
    ) -> T:
        gate = cls._gate(endpoint, model, max_concurrent)
        gate.semaphore.acquire()
        called = False
        try:
            with gate.state_lock:
                now = monotonic()
                if gate.cooldown_until > now:
                    raise ModelAdmissionCooldown(gate.cooldown_until - now)
                delay = max(0.0, gate.next_allowed_at - now)
            if delay:
                sleep(delay)
            with gate.state_lock:
                now = monotonic()
                if gate.cooldown_until > now:
                    raise ModelAdmissionCooldown(gate.cooldown_until - now)
            called = True
            try:
                return call()
            except Exception as exc:
                if cls._is_rate_limit(exc):
                    cooldown = cls._retry_after_seconds(exc) or default_cooldown_seconds
                    with gate.state_lock:
                        gate.cooldown_until = max(
                            gate.cooldown_until,
                            monotonic() + max(0.0, cooldown),
                        )
                raise
        finally:
            if called:
                with gate.state_lock:
                    gate.next_allowed_at = max(
                        gate.next_allowed_at,
                        monotonic() + max(0.0, min_interval_seconds),
                    )
            gate.semaphore.release()

    @classmethod
    def _gate(cls, endpoint: str, model: str, max_concurrent: int) -> _ModelGate:
        key = (endpoint.rstrip("/"), model, max_concurrent)
        with cls._registry_lock:
            gate = cls._gates.get(key)
            if gate is None:
                gate = _ModelGate(max_concurrent=max_concurrent)
                cls._gates[key] = gate
            return gate

    @staticmethod
    def _is_rate_limit(exc: BaseException) -> bool:
        return isinstance(exc, RateLimitError) or (
            isinstance(exc, APIStatusError) and exc.status_code == 429
        )

    @staticmethod
    def _retry_after_seconds(exc: BaseException) -> float | None:
        response = getattr(exc, "response", None)
        if response is None:
            return None
        value = response.headers.get("retry-after")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._registry_lock:
            cls._gates.clear()
