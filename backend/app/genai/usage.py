from __future__ import annotations

from typing import Any


def response_usage_metrics(
    response: Any,
    *,
    include_details: bool = False,
) -> dict[str, int]:
    """Normalize token telemetry from mapping- or attribute-style SDK responses."""

    usage = getattr(response, "usage", None)
    if usage is None:
        return {}

    def value(source: Any, key: str) -> int | None:
        raw = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            return None
        return raw

    metrics: dict[str, int] = {}
    keys = ["input_tokens", "output_tokens"]
    if include_details:
        keys.append("total_tokens")
    for key in keys:
        measured = value(usage, key)
        if measured is not None:
            metrics[key] = measured

    if not include_details:
        return metrics

    input_details = (
        usage.get("input_tokens_details")
        if isinstance(usage, dict)
        else getattr(usage, "input_tokens_details", None)
    )
    output_details = (
        usage.get("output_tokens_details")
        if isinstance(usage, dict)
        else getattr(usage, "output_tokens_details", None)
    )
    cached = value(input_details, "cached_tokens")
    reasoning = value(output_details, "reasoning_tokens")
    if cached is not None:
        metrics["cached_input_tokens"] = cached
    if reasoning is not None:
        metrics["reasoning_tokens"] = reasoning
    return metrics
