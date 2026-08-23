from __future__ import annotations

import re

_HANGUL = re.compile(r"[\uac00-\ud7a3]")

# A deliberately small, reviewed title set for the English demo paths.  Unknown
# source listings fall back to their mapped general-food concept below; no LLM
# call, DB write, or guessed translation is introduced by browse collections.
_CURATED_ENGLISH_TITLES = {
    "스팸김밥": "Spam Gimbap",
    "가래쌀떡볶이": "Garaetteok Tteokbokki",
    "국물떡볶이": "Soup Tteokbokki",
    "가성비 1등 국물떡볶이": "Best-Value Soup Tteokbokki",
    "로제떡볶이": "Rose Tteokbokki",
    "오뎅": "Eomuk Fish Cake",
    "[글루텐프리] 살얼음 해장 물냉면": "Gluten-Free Icy Mul Naengmyeon",
    "종로 나물비빔밥 도시락": "Jongno Vegetable Bibimbap Lunchbox",
    "비프스테이크 도시락": "Beef Steak Lunchbox",
    "제육볶음 도시락": "Spicy Pork Lunchbox",
    "매콤크림 파스타": "Spicy Cream Pasta",
    "미친피자 페퍼로니 2X": "Double Pepperoni Pizza",
    "순살치킨가라아게": "Boneless Chicken Karaage",
}


def english_discovery_title(
    name_en: str | None,
    name_ko: str | None,
    dish_name: str | None,
) -> str:
    """Return a safe English browse label without generating or persisting it."""

    candidates = [str(name_en or "").strip(), str(name_ko or "").strip()]
    for candidate in candidates:
        if candidate in _CURATED_ENGLISH_TITLES:
            return _CURATED_ENGLISH_TITLES[candidate]
    for candidate in candidates:
        if candidate and not _HANGUL.search(candidate):
            return candidate
    concept = str(dish_name or "").strip()
    return concept or "Available menu"
