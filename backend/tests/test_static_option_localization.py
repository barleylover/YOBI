from __future__ import annotations

import re

from scripts.generate_static_option_localizations import (
    LANGUAGES,
    _localized_rows,
    _validate_generated,
)

from app.option_static_localization import (
    MODEL_ID,
    localize_option_name,
)


def test_common_option_names_are_natural_in_english_and_japanese() -> None:
    assert localize_option_name("음료 추가선택", "en") == "Drink add-ons"
    assert localize_option_name("음료 추가선택", "ja") == "ドリンク 追加オプション"
    assert localize_option_name("선택안함", "en") == "None"
    assert localize_option_name("선택안함", "ja") == "選択しない"
    assert localize_option_name("콜라 1.25L", "en") == "Cola 1.25L"
    assert localize_option_name("콜라 1.25L", "ja") == "コーラ 1.25L"


def test_unknown_korean_brand_text_uses_deterministic_transliteration() -> None:
    first = localize_option_name("우리집 특별 토핑", "en")
    second = localize_option_name("우리집 특별 토핑", "en")
    japanese = localize_option_name("우리집 특별 토핑", "ja")

    assert first == second
    assert not re.search(r"[가-힣]", first)
    assert not re.search(r"[가-힣]", japanese)
    assert "topping" in first
    assert "トッピング" in japanese


def test_static_rows_cover_every_object_and_language_without_provider_calls() -> None:
    sources = [
        ("group-1", "음료 추가선택", "음료 추가선택"),
        ("group-2", "맵기 선택", "맵기 선택"),
    ]

    rows = _localized_rows("GROUP", sources)

    assert len(rows) == len(sources) * len(LANGUAGES)
    assert {row["language_code"] for row in rows} == set(LANGUAGES)
    assert {row["model_id"] for row in rows if row["language_code"] != "ko"} == {MODEL_ID}
    _validate_generated(sources, [], rows, [])
