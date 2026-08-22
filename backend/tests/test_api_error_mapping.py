from __future__ import annotations

import pytest

from app.api.errors import structured_recommendation_http_error


@pytest.mark.parametrize(
    ("code", "expected_status", "expected_code"),
    [
        ("CHAT_STATE_VERSION_CONFLICT", 409, "CHAT_STATE_VERSION_CONFLICT"),
        ("PREFERENCE_CATALOG_VERSION_CONFLICT", 409, "PREFERENCE_CATALOG_CHANGED"),
        ("RECOMMENDATION_REQUEST_NOT_FOUND", 404, "RECOMMENDATION_REQUEST_NOT_FOUND"),
        ("RECOMMENDATION_CRITERIA_EMPTY", 422, "RECOMMENDATION_CRITERIA_EMPTY"),
        ("RECOMMENDATION_RELEASE_NOT_READY", 503, "RECOMMENDATION_RELEASE_NOT_READY"),
        ("UNEXPECTED_FAILURE", 500, "RECOMMENDATION_FAILED"),
    ],
)
def test_structured_recommendation_error_mapping(
    code: str,
    expected_status: int,
    expected_code: str,
) -> None:
    error = structured_recommendation_http_error(ValueError(code))

    assert error.status_code == expected_status
    assert error.detail == {"code": expected_code}
