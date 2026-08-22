from __future__ import annotations

from fastapi import HTTPException, status


def not_found(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": code})


def structured_recommendation_http_error(exc: Exception) -> HTTPException:
    """Map recommendation domain failures to the stable HTTP contract."""

    code = str(exc).strip("'") or type(exc).__name__.upper()
    if code in {
        "CHAT_STATE_VERSION_CONFLICT",
        "CRITERIA_REQUEST_ID_REUSED",
        "RECOMMENDATION_REQUEST_ID_REUSED",
        "RECOMMENDATION_COMPLETION_PAYLOAD_CHANGED",
        "RECOMMENDATION_DISPATCH_PAYLOAD_CHANGED",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code})
    if code in {"PREFERENCE_CATALOG_CHANGED", "PREFERENCE_CATALOG_VERSION_CONFLICT"}:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PREFERENCE_CATALOG_CHANGED"},
        )
    if code in {
        "SESSION_NOT_FOUND",
        "PROFILE_NOT_FOUND",
        "RECOMMENDATION_CRITERIA_NOT_FOUND",
        "RECOMMENDATION_CRITERIA_VERSION_NOT_FOUND",
        "RECOMMENDATION_REQUEST_NOT_FOUND",
    }:
        return not_found(code)
    if code in {
        "RECOMMENDATION_CRITERIA_EMPTY",
        "HALAL_PORK_CRITERIA_CONFLICT",
        "VEGAN_ANIMAL_INGREDIENT_CRITERIA_CONFLICT",
        "INVALID_RECOMMENDATION_REQUEST_HASH",
        "HALAL_CERTIFICATION_UNAVAILABLE",
        "VEGAN_EVIDENCE_UNAVAILABLE",
        "SPICE_LEVEL_UNAVAILABLE",
        "RECOMMENDATION_COMPARISON_NOT_AVAILABLE",
        "RECOMMENDATION_COMPARISON_REQUIRES_TWO_MENUS",
        "RECOMMENDATION_SNAPSHOT_REQUEST_MISMATCH",
    }:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": code},
        )
    if code == "RECOMMENDATION_RELEASE_NOT_READY":
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": code},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "RECOMMENDATION_FAILED"},
    )
