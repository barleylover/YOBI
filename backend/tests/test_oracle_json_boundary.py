from __future__ import annotations

import inspect
from datetime import datetime, timezone

from app.db.oracle_repository import (
    OracleYobiRepository,
    _json_text,
    _synthetic_review_query_binds,
)


def test_oracle_native_json_is_serialized_as_valid_canonical_json() -> None:
    expected = '{"criteria":{"cuisine_origins":["KOREAN"]},"version":2}'

    assert (
        _json_text(
            {
                "version": 2,
                "criteria": {"cuisine_origins": ["KOREAN"]},
            }
        )
        == expected
    )
    assert _json_text(expected) == expected


def test_synthetic_review_query_omits_unused_oracle_binds() -> None:
    assert _synthetic_review_query_binds(
        {
            "synthetic_release_id": "release-1",
            "presentation_locale": "ja",
            "country_code": "JP",
            "synthetic_menu_0": "menu-1",
            "synthetic_menu_1": "menu-2",
        }
    ) == {
        "synthetic_release_id": "release-1",
        "synthetic_menu_0": "menu-1",
        "synthetic_menu_1": "menu-2",
    }


def test_oracle_repository_does_not_use_reserved_session_alias() -> None:
    assert "chat_session session" not in inspect.getsource(OracleYobiRepository)


def test_country_aware_cache_accepts_oracle_native_json_values() -> None:
    now = datetime.now(timezone.utc)
    entry = OracleYobiRepository._country_aware_presentation_cache_entry_from_row(
        {
            "cache_key": "a" * 64,
            "release_id": "release-1",
            "menu_id": "menu-1",
            "language_code": "es",
            "user_country_code": "US",
            "spice_reference_country_code": "GB",
            "localized_subtitle": "Menú claro",
            "short_explanation": "Explicación breve.",
            "long_explanation": "Explicación detallada.",
            "review_summary": "Resumen disponible.",
            "evidence_ids_json": ["evidence-1"],
            "review_ids_json": ["review-1"],
            "evidence_map_json": {"presentation_country_context": {"user": "US"}},
            "model_id": "fake-model",
            "prompt_version": "prompt-v1",
            "content_schema_version": "1",
            "source_hash": "b" * 64,
            "personalization_applied": 1,
            "created_at": now,
            "updated_at": now,
        }
    )

    assert entry.evidence_ids == ["evidence-1"]
    assert entry.review_ids == ["review-1"]
    assert entry.evidence_map["presentation_country_context"]["user"] == "US"
    assert entry.personalization_applied is True
