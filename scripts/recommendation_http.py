"""Shared HTTP 202 -> persisted-request polling contract for release harnesses."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic, sleep
from typing import Any

import httpx

POLL_INTERVAL_SECONDS = 0.5
RESULT_TIMEOUT_SECONDS = 180.0
_TRANSIENT_POLL_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _payload(response: httpx.Response, *, error_prefix: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"{error_prefix}_HTTP_{response.status_code}")
    value = response.json() if response.content else {}
    if not isinstance(value, dict):
        raise TypeError(f"{error_prefix}_RESPONSE_INVALID")
    return value


def await_recommendation_response(
    client: httpx.Client,
    *,
    session_id: str,
    initial_response: httpx.Response,
    timeout_seconds: float = RESULT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
    error_prefix: str = "RECOMMENDATION",
) -> dict[str, Any]:
    """Await one persisted request without ever repeating the POST dispatch."""

    if initial_response.status_code not in {200, 202}:
        return _payload(initial_response, error_prefix=error_prefix)
    value = initial_response.json() if initial_response.content else {}
    if not isinstance(value, dict):
        raise TypeError(f"{error_prefix}_RESPONSE_INVALID")
    deadline = clock() + timeout_seconds
    while str(value.get("status") or "").upper() == "PENDING":
        if clock() >= deadline:
            raise TimeoutError(f"{error_prefix}_POLL_TIMEOUT")
        request_id = str(value.get("request_id") or "")
        if not request_id:
            raise RuntimeError(f"{error_prefix}_PENDING_REQUEST_ID_MISSING")
        sleeper(poll_interval_seconds)
        try:
            response = client.get(
                f"/api/v1/sessions/{session_id}/recommendation-requests/{request_id}"
            )
        except httpx.TransportError:
            # The request is already persisted. A transient read failure must
            # never cause another POST/provider dispatch.
            continue
        if response.status_code in _TRANSIENT_POLL_STATUSES:
            continue
        value = _payload(response, error_prefix=error_prefix)
    return value
