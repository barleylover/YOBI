from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.db.demo_address import demo_address_row
from app.knowledge.authoring import parse_document
from app.knowledge.catalog_seed import build_knowledge_catalog_seed, default_knowledge_root
from app.knowledge.resolver import INGREDIENT_ALIASES

CATALOG_VERSION = "demo-2026.08.11-knowledge-v3"
UPDATED_AT = "2026-08-11"

def _spice_level(name_en: str, searchable_text: str) -> int:
    lowered = f"{name_en} {searchable_text}".casefold()
    name = name_en.casefold()
    if any(marker in name for marker in ("white jjamppong", "gungjung")):
        return 1
    if any(marker in name for marker in ("mala", "spicy seafood", "spicy tangsuyuk")):
        return 5
    if any(
        marker in name
        for marker in ("spicy", "tteokbokki", "jjamppong")
    ):
        return 4
    if any(
        marker in lowered
        for marker in (
            "bibim",
            "seasoned fried chicken",
            "gochujang",
            "kimchi stew",
            "kimchi-jjigae",
            "sundubu",
            "kimchi gukbap",
        )
    ):
        return 3
    if any(marker in lowered for marker in ("rose", "pepper", "light heat", "gently spicy")):
        return 2
    return 1


def _wiki_menu_templates() -> list[dict[str, Any]]:
    documents = [parse_document(path) for path in sorted(default_knowledge_root().rglob("*.md"))]
    front_by_id = {doc.front_matter.concept_id: doc.front_matter for doc in documents}

    def family_id(concept_id: str) -> str:
        current = front_by_id[concept_id]
        visited: set[str] = set()
        while current.concept_type == "VARIANT" and current.parents:
            if current.concept_id in visited:
                break
            visited.add(current.concept_id)
            current = front_by_id[current.parents[0].concept_id]
        return current.concept_id

    templates: list[dict[str, Any]] = []
    for document in documents:
        front = document.front_matter
        if front.concept_type == "CUISINE":
            continue
        searchable = " ".join(document.facets.values())
        templates.append(
            {
                "concept_id": front.concept_id,
                "concept_type": front.concept_type,
                "family_id": family_id(front.concept_id),
                "category": front.name_en,
                "name_ko": front.name_ko,
                "name_en": front.name_en,
                "aliases": front.aliases,
                "description": document.facets["overview"],
                "cultural_description": (
                    f"{document.facets['culture']} {document.facets['analogy']}"
                ),
                "flavor_text": f"{document.facets['taste']} {document.facets['texture']}",
                "spice_level": _spice_level(front.name_en, searchable),
                "wiki_allergens": [claim.allergen_id.removeprefix("allergen_") for claim in front.allergens],
                "wiki_ingredients": [claim.ingredient_id for claim in front.ingredients],
            }
        )
    return sorted(templates, key=lambda row: (str(row["family_id"]), str(row["concept_id"])))


WIKI_MENU_TEMPLATES = _wiki_menu_templates()
TEMPLATE_BY_CATEGORY = {str(row["category"]): row for row in WIKI_MENU_TEMPLATES}
TEMPLATES_BY_FAMILY: dict[str, list[dict[str, Any]]] = {}
for _template in WIKI_MENU_TEMPLATES:
    TEMPLATES_BY_FAMILY.setdefault(str(_template["family_id"]), []).append(_template)
FAMILY_IDS = sorted(TEMPLATES_BY_FAMILY)
CATEGORIES = [
    (
        str(template["category"]),
        str(template["name_ko"]),
        int(template["spice_level"]),
        str(template["description"]),
    )
    for template in WIKI_MENU_TEMPLATES
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


FOCUS_CATEGORY_OVERRIDES = {
    1: "Rose tteokbokki",
    2: "Tteokbokki",
    3: "Chicken kalguksu",
    4: "Bibimbap",
    5: "Gimbap",
    6: "Korean fried chicken",
    7: "Samgyetang",
    8: "Jjajangmyeon",
    9: "Sundubu",
    10: "Bulgogi",
    21: "Korean fried chicken",
    22: "Seasoned fried chicken",
    23: "Pizza",
    24: "Jjajangmyeon",
    25: "Tteokbokki",
    26: "Gimbap",
    27: "Gukbap",
    28: "Hotteok",
    29: "Seolleongtang",
    30: "Eomuk",
}


def _focus_family(index: int) -> str:
    category = FOCUS_CATEGORY_OVERRIDES.get(index)
    template = TEMPLATE_BY_CATEGORY.get(category or "")
    if template is not None:
        return str(template["family_id"])
    return FAMILY_IDS[(index - 1) % len(FAMILY_IDS)]


def _related_templates(focus_family: str) -> list[dict[str, Any]]:
    focus_index = FAMILY_IDS.index(focus_family)
    related_families = [
        FAMILY_IDS[(focus_index + offset) % len(FAMILY_IDS)] for offset in (1, 2, 3)
    ]
    return [template for family in related_families for template in TEMPLATES_BY_FAMILY[family]]


def _template_for_menu(merchant_index: int, menu_index: int, focus_family: str) -> dict[str, Any]:
    pool = TEMPLATES_BY_FAMILY[focus_family] if menu_index <= 7 else _related_templates(focus_family)
    if merchant_index == 27:
        # Preserve one explicit shellfish-absence demo merchant for the severe-allergy
        # presentation path. The restaurant still carries an UNKNOWN cross-contact
        # warning; it simply does not also sell an oyster/shellfish Wiki variant that
        # would create a contradictory merchant-wide kitchen signal.
        shellfish_free_pool = [
            template
            for template in pool
            if "shellfish_risk" not in template["wiki_allergens"]
            and "ingredient_shellfish" not in template["wiki_ingredients"]
        ]
        if shellfish_free_pool:
            pool = shellfish_free_pool
    return pool[(merchant_index * 3 + menu_index - 1) % len(pool)]


def _menu_price(category: str, merchant_index: int, menu_index: int) -> int:
    lowered = category.casefold()
    if any(marker in lowered for marker in ("pizza", "fried chicken", "tangsuyuk")):
        base = 17000
    elif any(marker in lowered for marker in ("bingsu", "croffle", "hotteok", "eomuk")):
        base = 5500
    elif any(marker in lowered for marker in ("baekban", "samgyetang", "gukbap", "seolleongtang")):
        base = 10500
    else:
        base = 8500
    return base + ((merchant_index * 5 + menu_index * 3) % 9) * 500


def _listing_from_template(
    template: dict[str, Any], merchant_index: int, menu_index: int
) -> dict[str, Any]:
    ko_modifiers = ("정통", "대표", "푸짐한", "수제", "담백한", "든든한", "매콤한", "고소한", "한그릇", "나눔")
    en_modifiers = (
        "Classic",
        "Signature",
        "Generous",
        "Handmade",
        "Gentle",
        "Hearty",
        "Spicy",
        "Rich",
        "One-bowl",
        "Shareable",
    )
    modifier_index = (merchant_index + menu_index - 2) % len(ko_modifiers)
    for offset in range(len(ko_modifiers)):
        candidate_index = (modifier_index + offset) % len(ko_modifiers)
        english_repeats = (
            en_modifiers[candidate_index].casefold()
            == str(template["name_en"]).split(maxsplit=1)[0].casefold()
        )
        korean_repeats = ko_modifiers[candidate_index] == "매콤한" and str(
            template["name_ko"]
        ).startswith(("매운", "매콤"))
        if not english_repeats and not korean_repeats:
            modifier_index = candidate_index
            break
    category = str(template["category"])
    return {
        "category": category,
        "name_ko": f"{ko_modifiers[modifier_index]} {template['name_ko']}",
        "name_en": f"{en_modifiers[modifier_index]} {template['name_en']}",
        "description": str(template["description"]),
        "cultural_description": str(template["cultural_description"]),
        "price": _menu_price(category, merchant_index, menu_index),
        "spice_level": int(template["spice_level"]),
        "dietary_tags": [
            "shareable" if menu_index % 4 == 0 else "one_person",
            "wiki_mapped_demo",
        ],
        "allergen_tags": (
            list(template["wiki_allergens"])[:3]
            if (merchant_index * 10 + menu_index) % 20 < 7
            else []
        ),
        "evidence_status": "VERIFIED"
        if (merchant_index * 10 + menu_index) % 20 < 7
        else "UNKNOWN",
    }


def _merchant_name(index: int, focus_family: str) -> tuple[str, str, str]:
    if index in PRESET_MERCHANT_NAMES:
        return PRESET_MERCHANT_NAMES[index]
    if index <= len(MERCHANT_NAMES):
        return MERCHANT_NAMES[index - 1]
    district = ("Myeongdong", "Hongdae", "Gangnam")[(index - 1) % 3]
    district_ko = ("명동", "홍대", "강남")[(index - 1) % 3]
    focus = TEMPLATES_BY_FAMILY[focus_family][0]
    suffix_ko, suffix_en = (
        ("식탁", "Table"),
        ("공방", "Kitchen"),
        ("한상", "Dining"),
        ("마루", "House"),
    )[index % 4]
    return (
        f"{district_ko} {focus['name_ko']} {suffix_ko}",
        f"{district} {focus['name_en']} {suffix_en}",
        f"a focused {str(focus['name_en']).lower()} menu with a few related Korean choices",
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
            "spice_level": 5,
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

    for merchant_index in range(1, 61):
        merchant_id = f"mer_{merchant_index:03d}"
        focus_family = _focus_family(merchant_index)
        name_ko, name_en, flavor = _merchant_name(merchant_index, focus_family)
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

        for menu_index in range(1, 11):
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
                item = _listing_from_template(
                    _template_for_menu(merchant_index, menu_index, focus_family),
                    merchant_index,
                    menu_index,
                )
                if menu_id == "menu_001_10":
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
                    "serves_max": (
                        3
                        if any(
                            marker in str(item["category"]).casefold()
                            for marker in ("pizza", "fried chicken", "tangsuyuk")
                        )
                        else (2 if menu_index % 3 == 0 else 1)
                    ),
                    "spice_level": item["spice_level"],
                    "dietary_tags_json": json.dumps(item["dietary_tags"]),
                    "allergen_tags_json": json.dumps(item["allergen_tags"]),
                    "semantic_text": semantic_text,
                    "availability": (
                        "AVAILABLE"
                        if canonical or (merchant_index * 10 + menu_index) % 20 < 17
                        else (
                            "SOLD_OUT"
                            if (merchant_index * 10 + menu_index) % 20 < 19
                            else "PAUSED"
                        )
                    ),
                    "is_synthetic": 1,
                    "updated_at": UPDATED_AT,
                }
            )

            if menu_id == "menu_001_01":
                evidence_rows = [
                    (
                        "shellfish_risk_absence",
                        "VERIFIED",
                        "SYNTHETIC_RESTAURANT_DECLARATION",
                        "The demo sauce specification lists no seafood or shellfish ingredients.",
                        "high",
                        "Use only as menu-level demo evidence; shared-kitchen cross-contamination "
                        "remains unknown.",
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
            elif menu_id == "menu_001_10":
                evidence_rows = [
                    (
                        "shellfish_risk_absence",
                        "VERIFIED",
                        "SYNTHETIC_MENU_SPEC",
                        "The seeded menu specification lists no shellfish ingredient or shellfish sauce.",
                        "high",
                        "Use only as menu-level demo evidence; shared-kitchen cross-contamination "
                        "remains unknown.",
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

            for evidence_index, evidence_spec in enumerate(evidence_rows, 1):
                claim_type, status, source_type, excerpt, band, action = evidence_spec
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
        if is_canonical_hotel:
            hotels.append(demo_address_row())
            continue
        hotels.append(
            {
                "place_id": f"hotel_demo_{hotel_index:02d}",
                "name_ko": f"요비 데모 호텔 {hotel_index:02d}",
                "name_en": f"YOBI Demo Hotel {hotel_index:02d}",
                "aliases_json": json.dumps([f"Demo Stay {hotel_index:02d}"]),
                "road_address": f"서울특별시 중구 데모길 {100 + hotel_index}",
                "postal_code": f"04{500 + hotel_index:03d}",
                "city": "Seoul",
                "delivery_hint": "Please leave the order with the hotel front desk.",
                "fixture_sha256": None,
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
            "typical_spice_max": min(5, spice + 1),
        }
        for name_en, name_ko, spice, description in CATEGORIES
    ]
    knowledge_catalog = build_knowledge_catalog_seed(menus)
    knowledge_release_id = knowledge_catalog.compiled_release.release_id
    claims_by_concept: dict[str, list[dict[str, Any]]] = {}
    allergen_claims_by_concept: dict[str, list[dict[str, Any]]] = {}
    for claim in knowledge_catalog.compiled_release.claims:
        if claim["claim_type"] == "INGREDIENT":
            claims_by_concept.setdefault(str(claim["concept_id"]), []).append(claim)
        elif claim["claim_type"] == "ALLERGEN":
            allergen_claims_by_concept.setdefault(str(claim["concept_id"]), []).append(claim)
    ancestors_by_concept: dict[str, list[str]] = {}
    for closure_row in sorted(
        knowledge_catalog.compiled_release.closure,
        key=lambda item: (str(item["descendant_concept_id"]), int(item["depth"])),
    ):
        if not closure_row["inherit_claims"]:
            continue
        ancestors_by_concept.setdefault(str(closure_row["descendant_concept_id"]), []).append(
            str(closure_row["ancestor_concept_id"])
        )
    mapping_by_menu = {
        str(row["menu_id"]): str(row["concept_id"])
        for row in knowledge_catalog.menu_concept_maps
        if row["concept_id"]
    }
    dietary_codes = sorted({tag for menu in menus for tag in json.loads(menu["dietary_tags_json"])})
    dietary_attributes_by_id = {
        row["attribute_id"]: row
        for row in [
        {
            "attribute_id": f"diet_{code}",
            "code": code,
            "display_name": code.replace("_", " ").title(),
        }
        for code in dietary_codes
        ]
    }
    dietary_attributes_by_id.update(
        {row["attribute_id"]: row for row in knowledge_catalog.dietary_attributes}
    )
    dietary_attributes = [dietary_attributes_by_id[key] for key in sorted(dietary_attributes_by_id)]
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
    menu_allergens.extend(
        [
            {
                "menu_id": menu_id,
                "allergen_id": "allergen_shellfish_risk",
                "status": "ABSENT",
                "evidence_id": f"ev_{menu_id[5:8]}_{menu_id[9:11]}_1",
                "cross_contamination_status": "UNKNOWN",
            }
            for menu_id in ("menu_001_01", "menu_001_10")
        ]
    )
    available_allergen_ids = set(allergens_by_id)
    menu_allergens = [
        row for row in menu_allergens if str(row["allergen_id"]) in available_allergen_ids
    ]
    menu_allergen_keys = {(row["menu_id"], row["allergen_id"]) for row in menu_allergens}
    evidence_by_id = {str(row["evidence_id"]): row for row in evidence}
    explicit_absence_menu_ids = {
        str(row["menu_id"]) for row in menu_allergens if row["status"] == "ABSENT"
    }
    protected_evidence_menu_ids = {
        "menu_001_01",
        "menu_002_01",
        "menu_003_01",
    }
    supported_allergens = tuple(
        code
        for code in (
            "shellfish_risk",
            "fish",
            "milk",
            "egg",
            "peanut",
            "tree_nut",
            "wheat",
            "soy",
            "sesame",
        )
        if f"allergen_{code}" in available_allergen_ids
    )
    merchant_by_id = {str(row["merchant_id"]): row for row in merchants}
    menu_by_id = {str(row["menu_id"]): row for row in menus}
    explicit_absence_area_pairs = {
        (
            str(merchant_by_id[str(menu_by_id[str(row["menu_id"])]["merchant_id"])][
                "service_area_id"
            ]),
            str(row["allergen_id"]),
        )
        for row in menu_allergens
        if row["status"] == "ABSENT"
    }

    def wiki_has_allergen_ingredient(menu_id: str, allergen_code: str) -> bool:
        allergy = "shellfish" if allergen_code == "shellfish_risk" else allergen_code
        risk_ingredients = INGREDIENT_ALIASES[allergy]
        concept_id = mapping_by_menu[menu_id]
        ingredient_risk = any(
            claim["ingredient_id"] in risk_ingredients
            and claim["assertion_status"]
            in {"CONFIRMED_PRESENT", "PRESUMED_PRESENT", "POSSIBLE", "CONFLICTING"}
            for ancestor_id in ancestors_by_concept.get(concept_id, [concept_id])
            for claim in claims_by_concept.get(ancestor_id, [])
        )
        allergen_id = f"allergen_{allergen_code}"
        allergen_risk = any(
            claim["allergen_id"] == allergen_id
            and claim["assertion_status"]
            in {"CONFIRMED_PRESENT", "PRESUMED_PRESENT", "POSSIBLE", "CONFLICTING"}
            for ancestor_id in ancestors_by_concept.get(concept_id, [concept_id])
            for claim in allergen_claims_by_concept.get(ancestor_id, [])
        )
        return ingredient_risk or allergen_risk

    # Each service area has a small, explicit menu-level absence record for every onboarding
    # allergy. Cross-contact remains UNKNOWN, so this is an explainable alternative, not a safety
    # certification.
    for service_area_id in sorted(SERVICE_AREAS[name][0] for name in SERVICE_AREAS):
        area_menu_ids = [
            str(menu["menu_id"])
            for menu in menus
            if menu["availability"] == "AVAILABLE"
            and merchant_by_id[str(menu["merchant_id"])]["service_area_id"] == service_area_id
        ]
        for code in supported_allergens:
            allergen_id = f"allergen_{code}"
            if (service_area_id, allergen_id) in explicit_absence_area_pairs:
                continue
            candidates = sorted(
                (
                    menu_id
                    for menu_id in area_menu_ids
                    if (menu_id, allergen_id) not in menu_allergen_keys
                    and menu_id not in explicit_absence_menu_ids
                    and menu_id not in protected_evidence_menu_ids
                    and not wiki_has_allergen_ingredient(menu_id, code)
                    and (
                        int(str(menu_by_id[menu_id]["merchant_id"]).removeprefix("mer_")) % 5
                        != 0
                    )
                    and str(menu_by_id[menu_id]["merchant_id"]) != "mer_027"
                ),
                key=lambda menu_id: (int(menu_by_id[menu_id]["spice_level"]), menu_id),
            )
            if not candidates:
                raise ValueError(
                    f"NO_EXPLICIT_ABSENCE_DEMO_CANDIDATE:{service_area_id}:{code}"
                )
            menu_id = candidates[0]
            evidence_id = f"ev_{menu_id[5:8]}_{menu_id[9:11]}_1"
            evidence_row = evidence_by_id[evidence_id]
            evidence_row.update(
                {
                    "claim_type": f"{code}_absence",
                    "status": "VERIFIED",
                    "source_type": "SYNTHETIC_MENU_SPEC",
                    "excerpt": (
                        f"The synthetic menu declaration explicitly marks {code.replace('_', ' ')} "
                        "as absent for this demo item."
                    ),
                    "confidence_band": "high",
                    "suggested_action": (
                        "Use only as menu-level demo evidence; shared-kitchen cross-contamination "
                        "remains unknown."
                    ),
                }
            )
            allergen_row = {
                "menu_id": menu_id,
                "allergen_id": allergen_id,
                "status": "ABSENT",
                "evidence_id": evidence_id,
                "cross_contamination_status": "UNKNOWN",
            }
            menu_allergens.append(allergen_row)
            menu_allergen_keys.add((menu_id, allergen_id))
            explicit_absence_menu_ids.add(menu_id)
            explicit_absence_area_pairs.add((service_area_id, allergen_id))
    ingredients = knowledge_catalog.ingredients
    explicit_menu_facts: dict[str, list[tuple[str, str]]] = {
        "menu_001_01": [
            ("ingredient_dairy_cream", "CONFIRMED_PRESENT"),
            ("ingredient_sauce", "CONFIRMED_PRESENT"),
        ],
        "menu_002_01": [
            ("ingredient_fish_cake", "CONFIRMED_PRESENT"),
            ("ingredient_sauce", "CONFIRMED_PRESENT"),
        ],
        "menu_001_04": [
            ("ingredient_cheese", "CONFIRMED_PRESENT"),
            ("ingredient_rice_cake", "CONFIRMED_PRESENT"),
        ],
        "menu_003_01": [
            ("ingredient_chicken", "CONFIRMED_PRESENT"),
            ("ingredient_chicken_broth", "CONFIRMED_PRESENT"),
            ("ingredient_wheat_noodles", "CONFIRMED_PRESENT"),
        ],
        "menu_024_01": [("ingredient_pork", "CONFIRMED_PRESENT")],
        "menu_027_01": [("ingredient_pork", "CONFIRMED_PRESENT")],
    }
    for menu in menus:
        menu_id = str(menu["menu_id"])
        if menu_id in {"menu_001_01", "menu_002_01", "menu_001_04"}:
            # Keep the canonical acceptance menus intentionally mixed-scope and the
            # replacement declaration at exactly its authored two facts. This
            # demonstrates menu-over-Wiki precedence without turning every stable
            # food fact into a restaurant declaration.
            continue
        if (
            (int(menu_id[5:8]) * 10 + int(menu_id[9:11])) % 20 >= 7
            and menu_id not in explicit_menu_facts
        ):
            continue
        concept_id = mapping_by_menu[menu_id]
        ingredient_ids = list(
            dict.fromkeys(
                str(claim["ingredient_id"])
                for ancestor_id in ancestors_by_concept.get(concept_id, [concept_id])
                for claim in claims_by_concept.get(ancestor_id, [])
                if claim["assertion_status"] == "PRESUMED_PRESENT"
                and claim["ingredient_id"]
            )
        )[:5]
        if len(ingredient_ids) < 2:
            continue
        explicit_menu_facts.setdefault(menu_id, []).extend(
            (ingredient_id, "CONFIRMED_PRESENT") for ingredient_id in ingredient_ids
        )
    menu_ingredients = [
        {
            "menu_id": menu_id,
            "ingredient_id": ingredient_id,
            "status": status,
            "source_id": f"synthetic_menu_fact:{menu_id}:{ingredient_id}",
            "is_optional": 0,
        }
        for menu_id, facts in sorted(explicit_menu_facts.items())
        for ingredient_id, status in list(dict(facts).items())[:5]
    ]
    menus_by_merchant: dict[str, list[dict[str, Any]]] = {}
    for menu in menus:
        menus_by_merchant.setdefault(str(menu["merchant_id"]), []).append(menu)
    merchant_origin_declarations: list[dict[str, Any]] = []
    merchant_ingredients: list[dict[str, Any]] = []
    for merchant in merchants:
        merchant_id = str(merchant["merchant_id"])
        merchant_index = int(merchant_id.removeprefix("mer_"))
        if merchant_index % 5 != 0 and merchant_index != 27:
            continue
        ingredient_ids = sorted(
            {
                str(claim["ingredient_id"])
                for menu in menus_by_merchant[merchant_id]
                for ancestor_id in ancestors_by_concept.get(
                    str(mapping_by_menu[menu["menu_id"]]),
                    [str(mapping_by_menu[menu["menu_id"]])],
                )
                for claim in claims_by_concept.get(ancestor_id, [])
                if claim["assertion_status"] == "PRESUMED_PRESENT"
            }
        )
        declaration_id = f"origin_{merchant_id}"
        ingredient_names = {row["ingredient_id"]: row["name_en"] for row in ingredients}
        rendered = ", ".join(ingredient_names[item] for item in ingredient_ids)
        raw_text = (
            "Synthetic demo shared-kitchen declaration for this merchant. Ingredients used "
            f"somewhere in the kitchen include: {rendered}. This merchant-wide list is only a "
            "cross-contact signal and does not prove presence in any individual menu."
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
                "origin_text": "Listed only as a synthetic shared-kitchen cross-contact signal",
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
