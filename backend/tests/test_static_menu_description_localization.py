from __future__ import annotations

import re

from scripts.generate_static_menu_descriptions import _rows_for_sources, _validate

from app.menu_source_description_localization import (
    description_source_hash,
    localize_source_description,
)


def test_description_localization_is_deterministic_and_language_safe() -> None:
    source = "쫄깃한 낙지와 김치를 비벼 먹는 메뉴"

    english = localize_source_description(source, "en")
    japanese = localize_source_description(source, "ja")

    assert english == localize_source_description(source, "en")
    assert japanese == localize_source_description(source, "ja")
    assert not re.search(r"[가-힣]", english)
    assert not re.search(r"[가-힣]", japanese)
    assert "octopus" in english.lower()
    assert "たこ" in japanese
    assert description_source_hash(source, "en") != description_source_hash(source, "ja")


def test_unique_description_translation_fans_out_to_every_menu() -> None:
    sources = [
        ("menu-1", "낙지와 김치를 비벼 먹는 메뉴"),
        ("menu-2", "낙지와 김치를 비벼 먹는 메뉴"),
        ("menu-3", "매운 떡볶이"),
    ]

    rows = _rows_for_sources(sources)
    counts = _validate(sources, rows)

    assert counts == {
        "source_menus": 3,
        "unique_descriptions": 2,
        "localized_rows": 9,
    }
    assert len({(row["menu_id"], row["language_code"]) for row in rows}) == 9
