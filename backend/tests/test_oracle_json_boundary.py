from __future__ import annotations

from app.db.oracle_repository import _json_text, _synthetic_review_query_binds


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
