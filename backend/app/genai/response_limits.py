from __future__ import annotations

from collections.abc import Mapping
from typing import Any

OUTPUT_LIMIT_RETRY_MULTIPLIER = 2
OUTPUT_LIMIT_REACHED_CODE = "OUTPUT_TRUNCATED_MAX_OUTPUT_TOKENS"


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def output_limit_reached(response: Any) -> bool:
    """Recognize only an explicit Responses API max-output truncation signal."""

    details = _field(response, "incomplete_details")
    reason = str(_field(details, "reason") or "").strip().lower()
    return reason == "max_output_tokens"


def expanded_output_limit(base_limit: int, provider_limit: int) -> int:
    """Double one request's output allowance without exceeding provider capability."""

    return min(provider_limit, base_limit * OUTPUT_LIMIT_RETRY_MULTIPLIER)
