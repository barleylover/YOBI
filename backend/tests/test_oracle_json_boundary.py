from __future__ import annotations

from app.db.oracle_repository import _json_text


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
