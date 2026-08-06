from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

CATALOG_VERSION = "demo-2026.08.06-v1"
UPDATED_AT = "2026-08-06"

CATEGORIES = [
    ("Tteokbokki", "떡볶이", 4, "sweet-spicy gochujang and chewy rice cakes"),
    ("Rose tteokbokki", "로제 떡볶이", 1, "creamy, gently sweet sauce and chewy rice cakes"),
    ("Chicken kalguksu", "닭칼국수", 1, "rich chicken broth with thick wheat noodles"),
    ("Bibimbap", "비빔밥", 1, "warm rice and seasoned vegetables mixed at the table"),
    ("Gimbap", "김밥", 0, "seaweed rice rolls with colourful fillings"),
    ("Korean fried chicken", "한국식 치킨", 2, "crisp fried chicken with a glossy sauce"),
    ("Samgyetang", "삼계탕", 0, "whole young chicken in a gentle ginseng broth"),
    ("Jjajangmyeon", "짜장면", 0, "springy noodles in a savoury black bean sauce"),
    ("Sundubu", "순두부찌개", 3, "silky tofu stew served bubbling hot"),
    ("Bulgogi", "불고기", 0, "sweet-savoury soy-marinated beef"),
    ("Kimchi stew", "김치찌개", 3, "tangy fermented kimchi stew"),
    ("Japchae", "잡채", 0, "glossy sweet-potato noodles and vegetables"),
    ("Mandu", "만두", 1, "Korean dumplings with a juicy filling"),
    ("Naengmyeon", "냉면", 1, "chilled buckwheat noodles with a bright broth"),
    ("Dosirak", "도시락", 1, "a balanced Korean lunch box"),
]

MERCHANT_NAMES = [
    ("명동 서울 로제떡볶이", "Seoul Rose Tteokbokki", "creamier and beginner-friendly"),
    ("명동 떡집", "Myeongdong Tteok House", "sweeter sauce and generous portions"),
    ("한옥 닭칼국수", "Hanok Chicken Kalguksu", "slow-simmered broth and thick noodles"),
    ("서울 채소 비빔밥", "Seoul Garden Bibimbap", "vegetable-forward bowls and clear options"),
    ("남산 김밥방", "Namsan Gimbap Room", "neat rolls for light hotel meals"),
    ("을지로 바삭치킨", "Euljiro Crisp Chicken", "extra-crisp packing for delivery"),
    ("종로 삼계탕집", "Jongno Samgyetang House", "gentle broth and one-person portions"),
    ("명동 짜장공방", "Myeongdong Jjajang Workshop", "deep black-bean flavour"),
    ("청계 순두부", "Cheonggye Soft Tofu", "customisable heat levels"),
    ("서울 불고기상", "Seoul Bulgogi Table", "sweet soy flavour and shareable plates"),
]


def _merchant_name(index: int) -> tuple[str, str, str]:
    if index <= len(MERCHANT_NAMES):
        return MERCHANT_NAMES[index - 1]
    district = ("Myeongdong", "Hongdae", "Gangnam")[(index - 1) % 3]
    return (
        f"요비 데모 키친 {index:02d}",
        f"YOBI Demo Kitchen {district} {index:02d}",
        "clear menu descriptions and reliable demo packaging",
    )


def _canonical_menu(merchant_index: int, menu_index: int) -> dict[str, Any] | None:
    if menu_index != 1:
        return None
    if merchant_index == 1:
        return {
            "category": "Rose tteokbokki",
            "name_ko": "순한 로제 떡볶이",
            "name_en": "Mild rose tteokbokki",
            "description": "Chewy rice cakes in a creamy, gently sweet rose sauce.",
            "cultural_description": (
                "Imagine creamy pasta sauce wrapped around chewy rice cakes, with a very gentle "
                "gochujang warmth."
            ),
            "price": 12900,
            "spice_level": 1,
            "dietary_tags": ["mild", "shellfish_sauce_absent", "fish_cake_removable"],
            "allergen_tags": ["milk", "cross_contamination_unknown"],
            "evidence_status": "VERIFIED",
        }
    if merchant_index == 2:
        return {
            "category": "Tteokbokki",
            "name_ko": "명동 옛날 떡볶이",
            "name_en": "Myeongdong classic tteokbokki",
            "description": "Classic chewy rice cakes in a bold sweet-spicy gochujang sauce.",
            "cultural_description": (
                "A much chewier, hotter cousin of a sweet chilli noodle dish, usually eaten as "
                "Korean street comfort food."
            ),
            "price": 9900,
            "spice_level": 4,
            "dietary_tags": ["street_food", "fish_cake_default"],
            "allergen_tags": ["shellfish_risk", "fish"],
            "evidence_status": "RISK_SIGNAL",
        }
    if merchant_index == 3:
        return {
            "category": "Chicken kalguksu",
            "name_ko": "맑은 닭칼국수",
            "name_en": "Gentle chicken kalguksu",
            "description": "Thick wheat noodles in a warm, slow-simmered chicken broth.",
            "cultural_description": (
                "Like chicken noodle soup with thicker handmade noodles and a deeper, less herby "
                "broth."
            ),
            "price": 11000,
            "spice_level": 1,
            "dietary_tags": ["mild", "no_pork", "one_person", "shellfish_sauce_absent"],
            "allergen_tags": ["wheat", "cross_contamination_unknown"],
            "evidence_status": "VERIFIED",
        }
    if merchant_index == 4:
        return {
            "category": "Bibimbap",
            "name_ko": "채소 비빔밥",
            "name_en": "Plant-forward bibimbap",
            "description": "Warm rice with seasoned vegetables and gochujang served on the side.",
            "cultural_description": (
                "A Korean build-your-own grain bowl: mix the vegetables, rice and sauce only as "
                "much as you like."
            ),
            "price": 10500,
            "spice_level": 0,
            "dietary_tags": ["vegan_option", "sauce_on_side", "no_pork"],
            "allergen_tags": ["soy"],
            "evidence_status": "VERIFIED",
        }
    return None


def build_seed() -> dict[str, list[dict[str, Any]]]:
    merchants: list[dict[str, Any]] = []
    menus: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    option_groups: list[dict[str, Any]] = []
    option_items: list[dict[str, Any]] = []

    for merchant_index in range(1, 31):
        merchant_id = f"mer_{merchant_index:03d}"
        name_ko, name_en, flavor = _merchant_name(merchant_index)
        service_area = ("Myeongdong", "Hongdae", "Gangnam")[(merchant_index - 1) % 3]
        merchants.append(
            {
                "merchant_id": merchant_id,
                "service_area": service_area,
                "name_ko": name_ko,
                "name_en": name_en,
                "description": f"Synthetic {service_area} demo restaurant with {flavor}.",
                "delivery_fee": 1000 + (merchant_index % 4) * 500,
                "eta_min": 18 + merchant_index % 9,
                "eta_max": 32 + merchant_index % 13,
                "min_order_amount": 9000 + (merchant_index % 3) * 1000,
                "flavor_profile": flavor,
                "packaging_signal": (
                    "Reviewers often mention tidy, spill-resistant packaging."
                    if merchant_index % 2
                    else "Portions are generous; packaging is secure but can retain steam."
                ),
                "is_synthetic": 1,
            }
        )

        for menu_index in range(1, 6):
            menu_id = f"menu_{merchant_index:03d}_{menu_index:02d}"
            canonical = _canonical_menu(merchant_index, menu_index)
            if canonical:
                item = canonical
            elif menu_id == "menu_003_01":
                evidence_rows = [
                    (
                        "shellfish_sauce",
                        "VERIFIED",
                        "SYNTHETIC_RESTAURANT_DECLARATION",
                        "The synthetic chicken broth specification lists no shellfish ingredients.",
                        "high",
                        "Kitchen cross-contamination is still not verified for a severe allergy.",
                    ),
                    (
                        "cross_contamination",
                        "UNKNOWN",
                        "SYNTHETIC_RESTAURANT_DECLARATION",
                        "Separate preparation equipment is not verified in this synthetic kitchen.",
                        "low",
                        "Confirm directly before ordering with a severe allergy.",
                    ),
                ]
            else:
                category_index = (merchant_index * 3 + menu_index - 1) % len(CATEGORIES)
                category_en, category_ko, base_spice, flavor_text = CATEGORIES[category_index]
                spice_level = max(0, min(5, base_spice + ((merchant_index + menu_index) % 3 - 1)))
                item = {
                    "category": category_en,
                    "name_ko": f"{category_ko} 데모 {menu_index}",
                    "name_en": f"{category_en} house style {menu_index}",
                    "description": f"A synthetic house variation featuring {flavor_text}.",
                    "cultural_description": (
                        f"A friendly introduction to {category_en.lower()}, described through taste, "
                        "texture and portion rather than a literal translation."
                    ),
                    "price": 8500 + ((merchant_index * 7 + menu_index * 3) % 12) * 500,
                    "spice_level": spice_level,
                    "dietary_tags": ["demo_estimate", "one_person"],
                    "allergen_tags": ["unknown_cross_contamination"],
                    "evidence_status": "UNKNOWN",
                }

            semantic_text = " ".join(
                [
                    item["category"],
                    item["name_en"],
                    item["description"],
                    item["cultural_description"],
                    *item["dietary_tags"],
                    *item["allergen_tags"],
                    f"spice {item['spice_level']}",
                    service_area,
                ]
            )
            menus.append(
                {
                    "menu_id": menu_id,
                    "merchant_id": merchant_id,
                    "category": item["category"],
                    "name_ko": item["name_ko"],
                    "name_en": item["name_en"],
                    "description": item["description"],
                    "cultural_description": item["cultural_description"],
                    "price": item["price"],
                    "serves_min": 1,
                    "serves_max": 1 if menu_index % 3 else 2,
                    "spice_level": item["spice_level"],
                    "dietary_tags_json": json.dumps(item["dietary_tags"]),
                    "allergen_tags_json": json.dumps(item["allergen_tags"]),
                    "semantic_text": semantic_text,
                    "availability": "AVAILABLE",
                    "is_synthetic": 1,
                    "updated_at": UPDATED_AT,
                }
            )

            if menu_id == "menu_001_01":
                evidence_rows = [
                    (
                        "shellfish_sauce",
                        "VERIFIED",
                        "SYNTHETIC_RESTAURANT_DECLARATION",
                        "The demo sauce specification lists no seafood or shellfish ingredients.",
                        "high",
                        "Cross-contamination is still unverified; confirm with the restaurant if severe.",
                    ),
                    (
                        "cross_contamination",
                        "UNKNOWN",
                        "SYNTHETIC_RESTAURANT_DECLARATION",
                        "The synthetic kitchen record does not verify separate preparation equipment.",
                        "low",
                        "Treat as not verified for a severe shellfish allergy.",
                    ),
                ]
            elif menu_id == "menu_002_01":
                evidence_rows = [
                    (
                        "shellfish",
                        "RISK_SIGNAL",
                        "SYNTHETIC_DEMO_REVIEW",
                        "Three demo reviews mention shrimp or seafood stock in the broth.",
                        "medium",
                        "Avoid by default for a shellfish allergy and choose an alternative.",
                    ),
                    (
                        "spiciness",
                        "RISK_SIGNAL",
                        "SYNTHETIC_DEMO_REVIEW",
                        "Twelve demo review signals describe the heat as stronger than expected (4/5).",
                        "medium",
                        "Choose the mild rose alternative for spice tolerance 1/5.",
                    ),
                ]
            else:
                evidence_rows = [
                    (
                        "ingredients",
                        item["evidence_status"],
                        "SYNTHETIC_MENU_SPEC",
                        "Demo ingredient evidence is internally consistent with the seeded menu record.",
                        "medium" if item["evidence_status"] == "VERIFIED" else "low",
                        "Check the displayed status; unknown does not mean safe.",
                    ),
                    (
                        "cross_contamination",
                        "UNKNOWN",
                        "SYNTHETIC_MENU_SPEC",
                        "Separate equipment and kitchen cross-contamination are not verified.",
                        "low",
                        "Users with severe allergies should exclude this menu by default.",
                    ),
                ]

            for evidence_index, row in enumerate(evidence_rows, 1):
                claim_type, status, source_type, excerpt, band, action = row
                evidence.append(
                    {
                        "evidence_id": f"ev_{merchant_index:03d}_{menu_index:02d}_{evidence_index}",
                        "subject_id": menu_id,
                        "claim_type": claim_type,
                        "status": status,
                        "source_type": source_type,
                        "excerpt": excerpt,
                        "confidence_band": band,
                        "suggested_action": action,
                        "updated_at": UPDATED_AT,
                    }
                )

            review_templates = (
                "The flavour matched the description and the portion felt right for one.",
                "Delivery packaging arrived tidy in this synthetic demo review.",
                "The spice level felt consistent with the menu card in this demo sample.",
                "A useful option for travellers who want clear explanations before ordering.",
            )
            if menu_id == "menu_002_01":
                review_templates = (
                    "Much spicier than expected; the heat felt close to four out of five.",
                    "The broth tasted like it may include a seafood or shrimp element.",
                    "Chewy and sweet, but not a mild choice for a first tteokbokki.",
                    "Fish cake comes in the standard portion in this synthetic menu.",
                )
            for review_index, review_text in enumerate(review_templates, 1):
                reviews.append(
                    {
                        "snippet_id": f"rev_{merchant_index:03d}_{menu_index:02d}_{review_index}",
                        "merchant_id": merchant_id,
                        "menu_id": menu_id,
                        "rating": 4 + (review_index % 2),
                        "review_text": review_text,
                        "source_type": "SYNTHETIC_DEMO",
                        "is_synthetic": 1,
                        "updated_at": UPDATED_AT,
                    }
                )

            if menu_id == "menu_001_01":
                group_defs = [
                    ("spice", "Spice level", "맵기", True, [("mild", "Mild", "순한맛", 0), ("medium", "Medium", "보통맛", 0), ("hot", "Hot", "매운맛", 0)]),
                    ("size", "Size", "사이즈", True, [("regular", "Regular", "보통", 0), ("large", "Large", "큰 사이즈", 3000)]),
                    ("cheese", "Cheese", "치즈", False, [("none", "No cheese", "치즈 없음", 0), ("add", "Add cheese", "치즈 추가", 1500)]),
                    ("fishcake", "Fish cake", "어묵", False, [("remove", "Remove fish cake", "어묵 빼기", 0), ("keep", "Keep fish cake", "어묵 포함", 0)]),
                ]
            else:
                group_defs = [
                    ("size", "Size", "사이즈", True, [("regular", "Regular", "보통", 0), ("large", "Large", "큰 사이즈", 2500)]),
                    ("extra", "Extra", "추가", False, [("none", "No extra", "추가 없음", 0), ("side", "House side", "사이드 추가", 1800)]),
                ]
            for group_order, group_def in enumerate(group_defs, 1):
                suffix, name_en, name_ko, required, items = group_def
                group_id = f"og_{merchant_index:03d}_{menu_index:02d}_{suffix}"
                option_groups.append(
                    {
                        "option_group_id": group_id,
                        "menu_id": menu_id,
                        "name_en": name_en,
                        "name_ko": name_ko,
                        "description": f"Choose {name_en.lower()} for this synthetic menu.",
                        "required": int(required),
                        "min_select": 1 if required else 0,
                        "max_select": 1,
                        "sort_order": group_order,
                    }
                )
                for item_order, option in enumerate(items, 1):
                    code, option_en, option_ko, price_delta = option
                    dietary_conflict = None
                    if suffix == "fishcake" and code == "keep":
                        dietary_conflict = "Contains fish; shellfish cross-contamination remains unknown."
                    option_items.append(
                        {
                            "option_item_id": f"oi_{merchant_index:03d}_{menu_index:02d}_{suffix}_{code}",
                            "option_group_id": group_id,
                            "name_en": option_en,
                            "name_ko": option_ko,
                            "description": f"{option_en} ({option_ko})",
                            "price_delta": price_delta,
                            "availability": "AVAILABLE",
                            "dietary_conflict": dietary_conflict,
                            "sort_order": item_order,
                        }
                    )

    hotels: list[dict[str, Any]] = []
    for hotel_index in range(1, 21):
        is_canonical_hotel = hotel_index == 1
        hotels.append(
            {
                "place_id": f"hotel_demo_{hotel_index:02d}",
                "name_ko": "요비 명동 호텔" if is_canonical_hotel else f"요비 데모 호텔 {hotel_index:02d}",
                "name_en": "YOBI Myeongdong Hotel" if is_canonical_hotel else f"YOBI Demo Hotel {hotel_index:02d}",
                "aliases_json": json.dumps(
                    ["YOBI Hotel Myeongdong", "요비호텔"]
                    if is_canonical_hotel
                    else [f"Demo Stay {hotel_index:02d}"]
                ),
                "road_address": (
                    "서울특별시 중구 데모로 21"
                    if is_canonical_hotel
                    else f"서울특별시 중구 데모길 {100 + hotel_index}"
                ),
                "postal_code": f"04{500 + hotel_index:03d}",
                "city": "Seoul",
                "delivery_hint": "Please leave the order with the hotel front desk.",
                "fixture_sha256": None,
                "is_synthetic": 1,
            }
        )

    return {
        "merchants": merchants,
        "menus": menus,
        "evidence": evidence,
        "reviews": reviews,
        "option_groups": option_groups,
        "option_items": option_items,
        "hotels": hotels,
    }


def seed_counts() -> dict[str, int]:
    seed = build_seed()
    return {name: len(rows) for name, rows in seed.items()}


def generated_at() -> str:
    return datetime.now(timezone.utc).isoformat()
