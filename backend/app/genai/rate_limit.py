from __future__ import annotations

import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from openai import RateLimitError


def retry_delay_seconds(
    error: RateLimitError,
    *,
    default_seconds: float | None = None,
    uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    """Return a safe retry delay without exposing the response body."""
    header: str | None = None
    response = getattr(error, "response", None)
    if response is not None:
        header = response.headers.get("retry-after")
    if header:
        try:
            parsed = max(0.0, float(header))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(header)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                parsed = max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                parsed = -1.0
        if parsed >= 0:
            return parsed + uniform(1.0, 3.0)
    if default_seconds is not None:
        return max(0.0, default_seconds)
    return uniform(65.0, 70.0)


def call_with_rate_limit_retry(
    call: Callable[..., Any],
    /,
    *args: Any,
    max_retries: int = 2,
    sleep: Callable[[float], None],
    uniform: Callable[[float, float], float] = random.uniform,
    on_retry: Callable[[float, int, int], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Retry only HTTP 429, at most ``max_retries`` times."""
    for attempt in range(max_retries + 1):
        try:
            return call(*args, **kwargs)
        except RateLimitError as exc:
            if attempt >= max_retries:
                raise RuntimeError("GENAI_RATE_LIMIT_RETRIES_EXHAUSTED") from None
            delay = retry_delay_seconds(exc, uniform=uniform)
            if on_retry is not None:
                on_retry(delay, attempt + 1, max_retries)
            sleep(delay)
    raise RuntimeError("GENAI_RATE_LIMIT_RETRIES_EXHAUSTED")
