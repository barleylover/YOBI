from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.knowledge.catalog_seed import build_knowledge_catalog_seed

CATALOG_VERSION = "demo-2026.08.09-knowledge-v2"
UPDATED_AT = "2026-08-08"

CATEGORIES = [
    ("Tteokbokki", "떡볶이", 3, "sweet-spicy gochujang and chewy rice cakes"),
    ("Rose tteokbokki", "로제 떡볶이", 1, "creamy, gently sweet sauce and chewy rice cakes"),
    ("Chicken kalguksu", "닭칼국수", 1, "rich chicken broth with thick wheat noodles"),
    ("Bibimbap", "비빔밥", 1, "warm rice and seasoned vegetables mixed at the table"),
    ("Gimbap", "김밥", 1, "seaweed rice rolls with colourful fillings"),
    ("Korean fried chicken", "한국식 치킨", 2, "crisp fried chicken with a glossy sauce"),
    ("Samgyetang", "삼계탕", 1, "whole young chicken in a gentle ginseng broth"),
    ("Jjajangmyeon", "짜장면", 1, "springy noodles in a savoury black bean sauce"),
    ("Sundubu", "순두부찌개", 3, "silky tofu stew served bubbling hot"),
    ("Bulgogi", "불고기", 1, "sweet-savoury soy-marinated beef"),
    ("Kimchi stew", "김치찌개", 3, "tangy fermented kimchi stew"),
    ("Japchae", "잡채", 1, "glossy sweet-potato noodles and vegetables"),
    ("Mandu", "만두", 1, "Korean dumplings with a juicy filling"),
    ("Naengmyeon", "냉면", 1, "chilled buckwheat noodles with a bright broth"),
    ("Dosirak", "도시락", 1, "a balanced Korean lunch box"),
    ("Pizza", "피자", 1, "a crisp delivery pizza with generous toppings"),
    ("Gukbap", "국밥", 1, "rice served with a deeply savoury Korean soup"),
    ("Hotteok", "호떡", 1, "a warm griddled pancake with a sweet nutty filling"),
    ("Seolleongtang", "설렁탕", 1, "a mild milky beef-bone soup with rice"),
    ("Eomuk", "어묵", 1, "springy fish cake with a light warm broth"),
]

SERVICE_AREAS = {
    "Myeongdong": ("area_myeongdong", "Jung-gu"),
    "Hongdae": ("area_hongdae", "Mapo-gu"),
    "Gangnam": ("area_gangnam", "Gangnam-gu"),
}


def _code(value: str) -> str:
    return "_".join(value.lower().replace("-", " ").split())


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

PRESET_MERCHANT_NAMES = {
    21: ("BBQ 명동점", "BBQ Myeongdong", "crisp Korean fried chicken for delivery"),
    22: ("BHC 을지로점", "BHC Euljiro", "bold seasoned Korean fried chicken"),
    23: ("노모어피자 명동점", "No More Pizza Myeongdong", "generous Korean-style pizza toppings"),
    24: ("홍콩반점 명동점", "Hong Kong Banjeom Myeongdong", "classic Korean-Chinese comfort food"),
    25: (
        "엽기떡볶이 명동점",
        "Yeopgi Tteokbokki Myeongdong",
        "chewy tteokbokki with selectable heat",
    ),
    26: ("남산 한줄김밥", "Namsan Gimbap", "neatly rolled gimbap for an easy meal"),
    27: ("서울 따뜻한국밥", "Seoul Gukbap House", "warming soup and rice bowls"),
    28: ("명동 호떡마을", "Myeongdong Hotteok", "fresh griddled Korean sweet pancakes"),
    29: ("을지 설렁탕", "Eulji Seolleongtang", "mild slow-simmered beef-bone soup"),
    30: ("종로 어묵상회", "Jongno Eomuk House", "warm fish cake and light broth"),
}


def _merchant_name(index: int) -> tuple[str, str, str]:
    if index in PRESET_MERCHANT_NAMES:
        return PRESET_MERCHANT_NAMES[index]
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
    preset_menus: dict[int, dict[str, Any]] = {
        21: {
            "category": "Korean fried chicken",
            "name_ko": "황금 올리브 치킨",
            "name_en": "Golden olive fried chicken",
            "description": "Extra-crisp fried chicken with a clean savoury finish.",
            "cultural_description": "A classic Korean delivery chicken with a light, crisp coating.",
            "price": 23000,
            "spice_level": 1,
            "dietary_tags": ["preset_weekly_rank", "one_chicken", "shellfish_sauce_absent"],
            "allergen_tags": ["wheat", "soy"],
            "evidence_status": "VERIFIED",
        },
        22: {
            "category": "Korean fried chicken",
            "name_ko": "뿌링클 치킨",
            "name_en": "Cheese-seasoned fried chicken",
            "description": "Crisp chicken finished with a sweet-savoury cheese seasoning.",
            "cultural_description": "Korean fried chicken with a playful powdered seasoning.",
            "price": 22000,
            "spice_level": 1,
            "dietary_tags": ["preset_weekly_rank", "shareable", "shellfish_sauce_absent"],
            "allergen_tags": ["milk", "wheat", "soy"],
            "evidence_status": "VERIFIED",
        },
        23: {
            "category": "Pizza",
            "name_ko": "반반 시그니처 피자",
            "name_en": "Half-and-half signature pizza",
            "description": "Two popular topping styles on one crisp delivery pizza.",
            "cultural_description": "A Korean delivery favourite that lets a group share two flavours.",
            "price": 24900,
            "spice_level": 1,
            "dietary_tags": ["preset_weekly_rank", "shareable", "shellfish_sauce_absent"],
            "allergen_tags": ["milk", "wheat"],
            "evidence_status": "VERIFIED",
        },
        24: {
            "category": "Jjajangmyeon",
            "name_ko": "짜장면과 탕수육 세트",
            "name_en": "Jjajangmyeon and tangsuyuk set",
            "description": "Black-bean noodles paired with crisp sweet-and-sour pork.",
            "cultural_description": "A familiar Korean-Chinese delivery combination for sharing.",
            "price": 18500,
            "spice_level": 1,
            "dietary_tags": ["preset_weekly_rank", "shareable", "shellfish_sauce_absent"],
            "allergen_tags": ["wheat", "soy"],
            "evidence_status": "VERIFIED",
        },
        25: {
            "category": "Tteokbokki",
            "name_ko": "엽기떡볶이 오리지널",
            "name_en": "Yeopgi original tteokbokki",
            "description": "Chewy rice cakes in a bold sweet-spicy sauce.",
            "cultural_description": "A famously bold delivery tteokbokki with chewy rice cakes.",
            "price": 14000,
            "spice_level": 3,
            "dietary_tags": [
                "preset_weekly_rank",
                "shareable",
                "fish_cake_default",
                "shellfish_sauce_absent",
            ],
            "allergen_tags": ["fish", "soy"],
            "evidence_status": "RISK_SIGNAL",
        },
        26: {
            "category": "Gimbap",
            "name_ko": "알록달록 한줄김밥",
            "name_en": "Colourful classic gimbap",
            "description": "Rice and colourful fillings rolled neatly in seaweed.",
            "cultural_description": "A portable Korean rice roll with varied textures in every slice.",
            "price": 6500,
            "spice_level": 1,
            "dietary_tags": ["preset_kpop_menu", "one_person", "shellfish_sauce_absent"],
            "allergen_tags": ["egg", "soy"],
            "evidence_status": "VERIFIED",
        },
        27: {
            "category": "Gukbap",
            "name_ko": "따뜻한 돼지국밥",
            "name_en": "Warm pork gukbap",
            "description": "Steamed rice served with a deeply savoury pork soup.",
            "cultural_description": "A comforting Korean soup-and-rice meal served piping hot.",
            "price": 11000,
            "spice_level": 1,
            "dietary_tags": ["preset_kpop_menu", "one_person", "shellfish_sauce_absent"],
            "allergen_tags": ["soy"],
            "evidence_status": "VERIFIED",
        },
        28: {
            "category": "Hotteok",
            "name_ko": "씨앗 꿀호떡",
            "name_en": "Seed and honey hotteok",
            "description": "A warm griddled pancake filled with brown sugar, honey and seeds.",
            "cultural_description": "A crisp-edged, chewy Korean street sweet best enjoyed warm.",
            "price": 5000,
            "spice_level": 1,
            "dietary_tags": ["preset_kpop_menu", "dessert", "shellfish_sauce_absent"],
            "allergen_tags": ["wheat", "tree_nut"],
            "evidence_status": "VERIFIED",
        },
        29: {
            "category": "Seolleongtang",
            "name_ko": "맑고 순한 설렁탕",
            "name_en": "Mild seolleongtang",
            "description": "Slow-simmered milky beef-bone soup served with rice.",
            "cultural_description": "A gentle Korean soup seasoned at the table to your taste.",
            "price": 13000,
            "spice_level": 1,
            "dietary_tags": ["preset_kpop_menu", "one_person", "mild", "shellfish_sauce_absent"],
            "allergen_tags": [],
            "evidence_status": "VERIFIED",
        },
        30: {
            "category": "Eomuk",
            "name_ko": "따뜻한 모둠어묵",
            "name_en": "Warm assorted eomuk",
            "description": "Springy fish cakes served with a light, warming broth.",
            "cultural_description": "A beloved Korean street snack with soft, bouncy texture.",
            "price": 8500,
            "spice_level": 1,
            "dietary_tags": ["preset_kpop_menu", "street_food", "shellfish_sauce_absent"],
            "allergen_tags": ["fish", "wheat", "soy"],
            "evidence_status": "VERIFIED",
        },
    }
    if merchant_index in preset_menus:
        return preset_menus[merchant_index]
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
            "spice_level": 3,
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
            "spice_level": 1,
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
        service_area = (
            "Myeongdong"
            if merchant_index in PRESET_MERCHANT_NAMES
            else ("Myeongdong", "Hongdae", "Gangnam")[(merchant_index - 1) % 3]
        )
        service_area_id = SERVICE_AREAS[service_area][0]
        merchants.append(
            {
                "merchant_id": merchant_id,
                "service_area": service_area,
                "service_area_id": service_area_id,
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
                spice_level = max(1, min(3, base_spice + ((merchant_index + menu_index) % 3 - 1)))
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
                if menu_id == "menu_001_02":
                    item["dietary_tags"].append("shellfish_sauce_absent")
                    item["evidence_status"] = "VERIFIED"

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
                    "category_id": f"category_{_code(item['category'])}",
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
            elif menu_id == "menu_001_02":
                evidence_rows = [
                    (
                        "shellfish_sauce",
                        "VERIFIED",
                        "SYNTHETIC_RESTAURANT_DECLARATION",
                        "The seeded menu specification lists no shellfish ingredient or shellfish sauce.",
                        "high",
                        "Cross-contamination remains unverified; confirm directly if severe.",
                    ),
                    (
                        "cross_contamination",
                        "UNKNOWN",
                        "SYNTHETIC_RESTAURANT_DECLARATION",
                        "Separate preparation equipment is not verified for this synthetic menu.",
                        "low",
                        "Treat kitchen cross-contamination as unknown.",
                    ),
                ]
            elif menu_id == "menu_002_01":
                evidence_rows = [
                    (
                        "shellfish",
                        "RISK_SIGNAL",
                        "SYNTHETIC_MENU_SPEC",
                        "The synthetic classic sauce specification records a shellfish-derived stock risk.",
                        "high",
                        "Avoid by default for a shellfish allergy and choose an alternative.",
                    ),
                    (
                        "spiciness",
                        "RISK_SIGNAL",
                        "SYNTHETIC_MENU_SPEC",
                        "The synthetic menu specification records level 3 on YOBI's three-level spice scale.",
                        "high",
                        "Choose the mild rose alternative for spice tolerance level 1.",
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
                    (
                        "spice",
                        "Spice level",
                        "맵기",
                        True,
                        [
                            ("mild", "Mild", "순한맛", 0),
                            ("medium", "Medium", "보통맛", 0),
                            ("hot", "Hot", "매운맛", 0),
                        ],
                    ),
                    (
                        "size",
                        "Size",
                        "사이즈",
                        True,
                        [("regular", "Regular", "보통", 0), ("large", "Large", "큰 사이즈", 3000)],
                    ),
                    (
                        "cheese",
                        "Cheese",
                        "치즈",
                        False,
                        [
                            ("none", "No cheese", "치즈 없음", 0),
                            ("add", "Add cheese", "치즈 추가", 1500),
                        ],
                    ),
                    (
                        "fishcake",
                        "Fish cake",
                        "어묵",
                        False,
                        [
                            ("remove", "Remove fish cake", "어묵 빼기", 0),
                            ("keep", "Keep fish cake", "어묵 포함", 0),
                        ],
                    ),
                ]
            else:
                group_defs = [
                    (
                        "size",
                        "Size",
                        "사이즈",
                        True,
                        [("regular", "Regular", "보통", 0), ("large", "Large", "큰 사이즈", 2500)],
                    ),
                    (
                        "extra",
                        "Extra",
                        "추가",
                        False,
                        [
                            ("none", "No extra", "추가 없음", 0),
                            ("side", "House side", "사이드 추가", 1800),
                        ],
                    ),
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
                        dietary_conflict = (
                            "Contains fish; shellfish cross-contamination remains unknown."
                        )
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
                "name_ko": "요비 명동 호텔"
                if is_canonical_hotel
                else f"요비 데모 호텔 {hotel_index:02d}",
                "name_en": "YOBI Myeongdong Hotel"
                if is_canonical_hotel
                else f"YOBI Demo Hotel {hotel_index:02d}",
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
                "fixture_sha256": (
                    "49f7f262d369a904b3b4ae395ec438bb5fcd98581b643dcfa32bbf4bbec08876"
                    if is_canonical_hotel
                    else None
                ),
                "service_area_id": "area_myeongdong",
                "is_synthetic": 1,
            }
        )

    knowledge = [
        {
            "knowledge_id": f"knowledge_{menu['menu_id']}",
            "menu_id": menu["menu_id"],
            "knowledge_type": "SYNTHETIC_MENU_GUIDE",
            "language": "en",
            "content": f"{menu['description']} {menu['cultural_description']}",
            "source_type": "SYNTHETIC_CATALOG",
            "source_ref": menu["menu_id"],
            "license_state": "SYNTHETIC",
            "embedding_text": menu["semantic_text"],
            "updated_at": UPDATED_AT,
        }
        for menu in menus
    ]

    service_areas = [
        {
            "service_area_id": identifier,
            "city": "Seoul",
            "district": district,
            "display_name": name,
            "active": 1,
        }
        for name, (identifier, district) in SERVICE_AREAS.items()
    ]
    menu_categories = [
        {
            "category_id": f"category_{_code(name_en)}",
            "name_ko": name_ko,
            "name_en": name_en,
            "description": description,
            "tags_json": json.dumps([_code(name_en)]),
            "typical_spice_min": max(1, spice - 1),
            "typical_spice_max": min(3, spice + 1),
        }
        for name_en, name_ko, spice, description in CATEGORIES
    ]
    dietary_codes = sorted({tag for menu in menus for tag in json.loads(menu["dietary_tags_json"])})
    dietary_attributes = [
        {
            "attribute_id": f"diet_{code}",
            "code": code,
            "display_name": code.replace("_", " ").title(),
        }
        for code in dietary_codes
    ]
    menu_dietary_attributes = [
        {
            "menu_id": menu["menu_id"],
            "attribute_id": f"diet_{code}",
            "status": "VERIFIED" if code == "shellfish_sauce_absent" else "PRESENT",
            "evidence_id": f"ev_{menu['menu_id'][5:8]}_{menu['menu_id'][9:11]}_1",
        }
        for menu in menus
        for code in json.loads(menu["dietary_tags_json"])
    ]
    knowledge_catalog = build_knowledge_catalog_seed(menus)
    knowledge_release_id = knowledge_catalog.compiled_release.release_id
    allergen_codes = sorted(
        {tag for menu in menus for tag in json.loads(menu["allergen_tags_json"])}
    )
    legacy_allergens = [
        {
            "allergen_id": f"allergen_{code}",
            "code": code,
            "name_en": code.replace("_", " ").title(),
            "name_ko": code,
        }
        for code in allergen_codes
    ]
    allergens_by_id = {row["allergen_id"]: row for row in legacy_allergens}
    allergens_by_id.update({row["allergen_id"]: row for row in knowledge_catalog.allergens})
    allergens = [allergens_by_id[key] for key in sorted(allergens_by_id)]
    menu_allergens = [
        {
            "menu_id": menu["menu_id"],
            "allergen_id": f"allergen_{code}",
            "status": "RISK_SIGNAL" if code.endswith("risk") else "PRESENT",
            "evidence_id": f"ev_{menu['menu_id'][5:8]}_{menu['menu_id'][9:11]}_1",
            "cross_contamination_status": (
                "UNKNOWN" if code == "cross_contamination_unknown" else "NOT_ASSESSED"
            ),
        }
        for menu in menus
        for code in json.loads(menu["allergen_tags_json"])
    ]
    ingredients = knowledge_catalog.ingredients
    explicit_menu_facts: dict[str, list[tuple[str, str]]] = {
        "menu_001_01": [("ingredient_dairy_cream", "CONFIRMED_PRESENT")],
        "menu_002_01": [("ingredient_fish_cake", "CONFIRMED_PRESENT")],
        "menu_003_01": [
            ("ingredient_chicken", "CONFIRMED_PRESENT"),
            ("ingredient_chicken_broth", "CONFIRMED_PRESENT"),
            ("ingredient_wheat_noodles", "CONFIRMED_PRESENT"),
        ],
        "menu_024_01": [("ingredient_pork", "CONFIRMED_PRESENT")],
        "menu_027_01": [("ingredient_pork", "CONFIRMED_PRESENT")],
    }
    menu_ingredients = [
        {
            "menu_id": menu_id,
            "ingredient_id": ingredient_id,
            "status": status,
            "source_id": f"synthetic_menu_fact:{menu_id}:{ingredient_id}",
            "is_optional": 0,
        }
        for menu_id, facts in sorted(explicit_menu_facts.items())
        for ingredient_id, status in facts
    ]
    claims_by_concept: dict[str, list[dict[str, Any]]] = {}
    for claim in knowledge_catalog.compiled_release.claims:
        if claim["claim_type"] != "INGREDIENT" or claim["ingredient_role"] not in {
            "DEFINING",
            "CORE",
        }:
            continue
        claims_by_concept.setdefault(str(claim["concept_id"]), []).append(claim)
    mapping_by_menu = {
        row["menu_id"]: row["concept_id"] for row in knowledge_catalog.menu_concept_maps
    }
    menus_by_merchant: dict[str, list[dict[str, Any]]] = {}
    for menu in menus:
        menus_by_merchant.setdefault(str(menu["merchant_id"]), []).append(menu)
    merchant_origin_declarations: list[dict[str, Any]] = []
    merchant_ingredients: list[dict[str, Any]] = []
    for merchant in merchants:
        merchant_id = str(merchant["merchant_id"])
        ingredient_ids = sorted(
            {
                str(claim["ingredient_id"])
                for menu in menus_by_merchant[merchant_id]
                for claim in claims_by_concept.get(str(mapping_by_menu[menu["menu_id"]]), [])
            }
        )
        declaration_id = f"origin_{merchant_id}"
        ingredient_names = {row["ingredient_id"]: row["name_en"] for row in ingredients}
        rendered = ", ".join(ingredient_names[item] for item in ingredient_ids)
        raw_text = (
            "Synthetic demo origin declaration for this merchant. Reviewed core ingredients "
            f"used across its catalog include: {rendered}. This merchant-wide list does not "
            "prove that every ingredient is present in every menu."
        )
        merchant_origin_declarations.append(
            {
                "release_id": knowledge_release_id,
                "declaration_id": declaration_id,
                "merchant_id": merchant_id,
                "language": "en",
                "raw_text": raw_text,
                "content_sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
                "source_type": "SYNTHETIC_MERCHANT_ORIGIN_DECLARATION",
                "source_ref": f"synthetic-origin:{merchant_id}",
                "source_version": CATALOG_VERSION,
                "review_status": "REVIEWED_DEMO",
                "is_synthetic": 1,
                "valid_from": UPDATED_AT,
                "valid_to": None,
                "updated_at": UPDATED_AT,
            }
        )
        merchant_ingredients.extend(
            {
                "release_id": knowledge_release_id,
                "merchant_id": merchant_id,
                "ingredient_id": ingredient_id,
                "declaration_id": declaration_id,
                "status": "CONFIRMED_PRESENT",
                "origin_text": "Listed in the synthetic merchant-wide origin declaration",
                "source_ref": f"synthetic-origin:{merchant_id}",
                "is_synthetic": 1,
                "updated_at": UPDATED_AT,
            }
            for ingredient_id in ingredient_ids
        )
    option_effect_specs = {
        "oi_001_01_cheese_add": ("ingredient_cheese", "ADD", "CONFIRMED_PRESENT"),
        "oi_001_01_cheese_none": ("ingredient_cheese", "REMOVE", "CONFIRMED_ABSENT"),
        "oi_001_01_fishcake_keep": (
            "ingredient_fish_cake",
            "ADD",
            "CONFIRMED_PRESENT",
        ),
        "oi_001_01_fishcake_remove": (
            "ingredient_fish_cake",
            "REMOVE",
            "CONFIRMED_ABSENT",
        ),
    }
    option_ingredient_effects = [
        {
            "release_id": knowledge_release_id,
            "option_item_id": option_item_id,
            "ingredient_id": values[0],
            "effect": values[1],
            "assertion_status": values[2],
            "source_ref": f"synthetic-option:{option_item_id}",
            "is_synthetic": 1,
            "updated_at": UPDATED_AT,
        }
        for option_item_id, values in sorted(option_effect_specs.items())
    ]
    option_dietary_conflicts = [
        {
            "option_item_id": item["option_item_id"],
            "rule_code": "shellfish_allergy",
            "conflict_status": "UNKNOWN_CROSS_CONTAMINATION",
            "evidence_id": None,
        }
        for item in option_items
        if item["dietary_conflict"]
    ]

    return {
        "merchants": merchants,
        "menus": menus,
        "knowledge": knowledge,
        "evidence": evidence,
        "reviews": reviews,
        "option_groups": option_groups,
        "option_items": option_items,
        "hotels": hotels,
        "service_areas": service_areas,
        "menu_categories": menu_categories,
        "dietary_attributes": dietary_attributes,
        "menu_dietary_attributes": menu_dietary_attributes,
        "allergens": allergens,
        "menu_allergens": menu_allergens,
        "ingredients": ingredients,
        "menu_ingredients": menu_ingredients,
        "menu_concept_maps": knowledge_catalog.menu_concept_maps,
        "merchant_origin_declarations": merchant_origin_declarations,
        "merchant_ingredients": merchant_ingredients,
        "option_ingredient_effects": option_ingredient_effects,
        "option_dietary_conflicts": option_dietary_conflicts,
    }


def seed_counts() -> dict[str, int]:
    seed = build_seed()
    return {name: len(rows) for name, rows in seed.items()}


def generated_at() -> str:
    return datetime.now(timezone.utc).isoformat()
