from __future__ import annotations

import pytest

from app.domain.presentation_localization import (
    SUPPORTED_PRESENTATION_LOCALES,
    build_presentation_country_context,
    is_generic_localized_title,
    normalize_presentation_locale,
    source_translation_is_safe,
    text_uses_target_script,
)


@pytest.mark.parametrize("locale", SUPPORTED_PRESENTATION_LOCALES)
def test_all_presentation_locales_share_the_preference_contract(locale: str) -> None:
    assert normalize_presentation_locale(locale) == locale


def test_source_translation_rejects_empty_quantity_drift_and_missing_latin_token() -> None:
    source = "Coca-Cola 355ml 2개와 소스"

    assert not source_translation_is_safe(source, "", "en")
    assert not source_translation_is_safe(source, "Coca-Cola 500ml, two items, with sauce.", "en")
    assert not source_translation_is_safe(source, "Two 355ml items with sauce.", "en")
    assert source_translation_is_safe(
        source,
        "2 Coca-Cola items in 355ml servings with sauce.",
        "en",
    )


def test_source_translation_requires_target_script_and_allows_exact_korean_copy() -> None:
    source = "신선한 재료로 만든 메뉴"

    assert source_translation_is_safe(source, source, "ko")
    assert not source_translation_is_safe(source, "Freshly made menu", "ja")
    assert text_uses_target_script("新鮮な食材で作ったメニュー", "ja")
    assert text_uses_target_script("用新鲜食材制作的菜品", "zh-CN")
    assert text_uses_target_script("เมนูที่ทำจากวัตถุดิบสดใหม่", "th")


def test_all_latin_source_prose_can_be_translated_without_echoing_every_word() -> None:
    source = "Chewy rice cakes in a creamy, gently sweet rose sauce."

    assert source_translation_is_safe(
        source,
        "A validated English restaurant description.",
        "en",
    )
    assert source_translation_is_safe(source, "検証済みの店舗説明です。", "ja")
    assert not source_translation_is_safe(
        "A Coca-Cola combo.",
        "検証済みのセットです。",
        "ja",
    )


def test_all_latin_source_preserves_spelled_quantities_and_metric_units() -> None:
    source = "Coca-Cola 355ml, two sets."

    assert source_translation_is_safe(source, "Two sets of Coca-Cola, 355ml each.", "en")
    assert not source_translation_is_safe(source, "One Coca-Cola set, 355ml.", "en")
    assert not source_translation_is_safe(source, "Two Coca-Cola sets, 355g each.", "en")


@pytest.mark.parametrize("title", ["Korean menu", " korean   MENU ", "韓国料理メニュー"])
def test_generic_title_sentinels_are_not_persistable(title: str) -> None:
    assert is_generic_localized_title(title)


def test_country_context_keeps_user_and_spice_reference_roles_separate() -> None:
    context = build_presentation_country_context(
        user_country_code="us",
        spice_reference_country_code="JP",
        representative_dish_en="Japanese curry",
        spice_baseline=2,
        menu_spice_level=4,
    )

    assert context.user_country_code == "US"
    assert context.spice_reference_country_code == "JP"
    assert context.representative_dish_en == "Japanese curry"
    assert context.spice_relationship == "MORE"
    assert context.comparison_is_complete


def test_unknown_user_country_disables_country_personalization_and_comparison() -> None:
    context = build_presentation_country_context(
        user_country_code="ZZ",
        spice_reference_country_code="US",
        representative_dish_en="Buffalo wings",
        spice_baseline=3,
        menu_spice_level=4,
    )

    assert context.user_country_code is None
    assert context.spice_reference_country_code is None
    assert not context.comparison_is_complete


def test_incomplete_spice_reference_is_not_partially_exposed() -> None:
    context = build_presentation_country_context(
        user_country_code="GB",
        spice_reference_country_code="GB",
        representative_dish_en=None,
        spice_baseline=3,
        menu_spice_level=4,
    )

    assert context.user_country_code == "GB"
    assert context.spice_reference_country_code is None
    assert context.spice_relationship is None
    assert not context.comparison_is_complete
