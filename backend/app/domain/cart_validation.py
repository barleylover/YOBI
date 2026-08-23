from __future__ import annotations

from app.domain.structured_recommendation import RecommendationCriteriaV2

CART_MENU_NO_LONGER_ELIGIBLE = "CART_MENU_NO_LONGER_ELIGIBLE"
CART_DIETARY_CONFLICT = "CART_DIETARY_CONFLICT"


def structured_v3_cart_error(
    criteria: RecommendationCriteriaV2,
    *,
    price: int,
    spice_level: int,
    country_spice_baseline: int,
    halal_fit: bool,
    vegan_fit: bool,
) -> str | None:
    """Return the stable cart error for a v3 menu that no longer meets its criteria."""

    price_range = criteria.price_range_krw
    if price_range is None or not price_range.min <= price <= price_range.max:
        return CART_MENU_NO_LONGER_ELIGIBLE

    spice_matches = (
        spice_level < country_spice_baseline
        if criteria.spice_preference == "LESS"
        else spice_level > country_spice_baseline
        if criteria.spice_preference == "MORE"
        else spice_level == country_spice_baseline
    )
    if not spice_matches:
        return CART_MENU_NO_LONGER_ELIGIBLE

    dietary = criteria.dietary_filters
    if (dietary.halal_certified_only and not halal_fit) or (dietary.vegan and not vegan_fit):
        return CART_DIETARY_CONFLICT
    return None


def deterministic_korean_order_note(note: str) -> str:
    """Translate the narrow offline note fallback without claiming general translation."""

    lowered = note.lower()
    translations = []
    if "mild" in lowered or "not spicy" in lowered:
        translations.append("최대한 맵지 않게 부탁드립니다.")
    if "front desk" in lowered:
        translations.append("호텔 프런트에 맡겨 주세요.")
    elif "at the door" in lowered:
        translations.append("문 앞에 놓아 주세요.")
    elif "meet me outside" in lowered:
        translations.append("건물 밖에서 직접 전달해 주세요.")
    if "no cutlery" in lowered or "no disposable" in lowered:
        translations.append("일회용 수저와 포크는 필요 없습니다.")
    elif "include disposable cutlery" in lowered:
        translations.append("일회용 수저와 포크를 포함해 주세요.")
    if "do not ring" in lowered or "no bell" in lowered:
        translations.append("벨을 누르지 말아 주세요.")
    elif "ring the bell" in lowered:
        translations.append("도착하면 벨을 눌러 주세요.")
    return " ".join(translations) or "요청사항을 확인해 주세요."
