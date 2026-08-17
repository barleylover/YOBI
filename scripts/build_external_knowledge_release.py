#!/usr/bin/env python3
"""Build, stage, verify, and optionally activate external general-Wiki support.

The external catalog remains authoritative for merchant, menu, price and option
facts.  This tool adds only two explicitly synthetic, reproducible layers:

* high-confidence menu-name -> general dish concept mappings; and
* reviewed general-Wiki -> stable preference-code support edges.

It never infers merchant ingredients, vegan suitability, halal certification or
menu-specific spice levels.  Every menu receives either a high mapping or one
explicit classification reason.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.domain.concept_ranking import (
    RANKING_POLICY,
    RANKING_POLICY_SHA256,
    RANKING_POLICY_VERSION,
)
from app.domain.preference_catalog import (
    PREFERENCE_CATALOG_VERSION,
    PREFERENCE_CATEGORIES,
    localized_spice_references,
    preference_option_is_exposable,
)
from app.knowledge.authoring import (
    AuthoredDocument,
    CompiledKnowledgeRelease,
    compile_documents,
    parse_document,
)
from app.knowledge.catalog_seed import _taxonomy_rows
from app.knowledge.menu_features import (
    FEATURE_EXTRACTOR_VERSION,
    MEMBERSHIP_EXTRACTOR_VERSION,
    build_menu_concept_memberships,
    compile_menu_preference_features,
    feature_manifest_sha256,
    preference_term_matches,
)
from app.knowledge.oracle_store import load_oracle_release
from app.knowledge.preference_support import SUPPORT_METHOD_VERSION
from app.knowledge.sqlite_store import load_sqlite_release

MAPPING_METHOD_VERSION = "yobi-reviewed-name-map-v4"
MAPPING_PROVENANCE = "YOBI_DERIVED_DEMO_MAPPING"
SUPPORT_PROVENANCE = "SYNTHETIC_WIKI"

NON_FOOD_CATEGORY = re.compile(
    r"(?:주류|음료|커피|디카페인|밀크티|에이드|스무디|쉐이크|와인|맥주|소주|"
    r"콜라|사이다|생수|티\s*$|차\s*$|소스\s*$|소스\s*메뉴|시즈닝\s*$|"
    r"파티용품|숫자초|케이크\s*토퍼|사리\s*추가|추가선택)",
    re.IGNORECASE,
)
PROMOTION_NAME = re.compile(
    r"(?:리뷰\s*이벤트|포토\s*리뷰|이벤트\s*참여|쿠폰|증정\s*전용|서비스\s*메뉴)",
    re.IGNORECASE,
)
COMPOSITE_NAME = re.compile(r"(?:\+|＋|＆|&|\bset\b|세트|셋트|반반|콤보|\bor\b)", re.IGNORECASE)

# These short Korean food names were individually reviewed against the active
# external catalog.  Unlike generic two-syllable fragments (for example 타코,
# which also occurs in 타코와사비), they retain a single food meaning when they
# appear inside a longer product name.  Keeping this explicit is safer than
# globally weakening the long-alias rule.
REVIEWED_STANDALONE_SHORT_ALIASES = frozenset(
    {
        "규동",
        "버거",
        "덮밥",
        "도넛",
        "반미",
        "분짜",
        "수프",
        "식빵",
        "와플",
        "육회",
        "잡채",
        "제육",
        "주스",
        "짜조",
        "쿠키",
        "포케",
    }
)

# The general Wiki includes these families for descriptive completeness, but
# YOBI's meal recommender deliberately excludes standalone beverages.  Keeping
# this boundary concept-based avoids relying on inconsistent merchant category
# labels and keeps the expansion near the requested food-menu target.
RECOMMENDATION_EXCLUDED_CONCEPTS = frozenset(
    {
        "dish_americano",
        "dish_cafe_latte",
        "dish_cold_brew",
        "dish_juice",
        "dish_smoothie",
    }
)

CONCEPT_REJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    # This source item is explicitly raw salmon sold "for steak" rather than a
    # prepared salmon-steak dish.  It must not inherit the cooked-dish Wiki.
    "dish_grilled_salmon": re.compile(r"생연어.*스테이크용"),
}

TEXT_SUPPORT_RULES: dict[tuple[str, str], tuple[str, ...]] = {
    ("flavors", "SPICY"): ("spicy", "chilli", "chili", "heat", "peppery"),
    ("flavors", "SWEET"): ("sweet", "sugary", "honey"),
    ("flavors", "SALTY"): ("salty", "saltiness", "salted"),
    ("flavors", "SOUR"): ("sour", "tangy", "acidity", "acidic"),
    ("flavors", "NUTTY_SAVORY"): ("savoury", "savory", "umami", "nutty"),
    ("flavors", "CLEAN_MILD"): ("clean", "mild", "light broth", "delicate"),
    ("temperatures", "HOT"): ("piping hot", "bubbling hot", "steaming hot", "served hot"),
    ("temperatures", "WARM"): ("served warm", "eaten warm", "packed warm"),
    ("temperatures", "ROOM_TEMPERATURE"): ("room temperature",),
    ("temperatures", "COOL"): ("served cool", "chilled", "cold dish", "cool broth"),
    ("temperatures", "FROZEN"): ("frozen", "shaved ice", "icy"),
    ("textures", "CRISPY"): ("crispy", "crisp exterior", "crisp edges"),
    ("textures", "CHEWY"): ("chewy", "springy", "bouncy"),
    ("textures", "SOFT"): ("soft", "tender", "silky"),
    ("textures", "CRUNCHY"): ("crunchy", "crisp vegetables", "crisp vegetable"),
    ("textures", "THICK_RICH"): ("thick", "rich", "creamy", "dense"),
    ("cooking_methods", "GRILLED"): ("grilled", "on a grill", "charred"),
    ("cooking_methods", "BOILED"): ("boiled", "poached"),
    ("cooking_methods", "SIMMERED"): ("simmered", "stewed", "long braising", "braised"),
    ("cooking_methods", "STEAMED"): ("steamed",),
    ("cooking_methods", "FRIED"): ("deep-fried", "fried until", "fried exterior"),
    ("cooking_methods", "STIR_FRIED"): ("stir-fried", "stir fried"),
    ("cooking_methods", "BAKED"): ("baked", "oven-baked", "oven baked"),
}

INGREDIENT_SUPPORT: dict[str, str] = {
    "ingredient_beef": "BEEF",
    "ingredient_pork": "PORK",
    "ingredient_chicken": "CHICKEN",
    "ingredient_fish_cake": "FISH_SEAFOOD",
    "ingredient_fish_paste": "FISH_SEAFOOD",
    "ingredient_mackerel": "FISH_SEAFOOD",
    "ingredient_shellfish": "FISH_SEAFOOD",
    "ingredient_tuna": "FISH_SEAFOOD",
    "ingredient_mixed_vegetables": "VEGETABLE",
}

PREPARATION_SUPPORT: dict[str, str] = {
    "grilled": "GRILLED",
    "boiled": "BOILED",
    "poached": "BOILED",
    "simmered": "SIMMERED",
    "stewed": "SIMMERED",
    "braised": "SIMMERED",
    "steamed": "STEAMED",
    "fried": "FRIED",
    "deep_fried": "FRIED",
    "stir_fried": "STIR_FRIED",
    "baked": "BAKED",
}

FORM_CONCEPT_MARKERS: dict[str, tuple[str, ...]] = {
    "RICE": ("gimbap", "bibimbap", "fried_rice", "dosirak", "baekban", "kimchi_fried_rice", "rice_ball", "rice_bowl", "cup_bap", "risotto", "omurice", "katsudon", "gyudon", "nasi_goreng"),
    "NOODLES": ("guksu", "kalguksu", "naengmyeon", "udon", "jjajangmyeon", "jjamppong", "ramyeon", "japchae", "pasta", "ramen_japanese", "pho", "pad_thai", "yakisoba", "fried_noodles"),
    "SOUP": ("gukbap", "samgyetang", "seolleongtang", "eomuk", "soup", "yukgaejang", "pho", "tom_yum", "mala_tang"),
    "STEW_HOTPOT": ("stew", "jjigae", "sundubu"),
    "BREAD": ("pizza", "croffle", "hotteok", "sandwich", "burger", "cake", "bread", "bagel", "croissant", "salt_bread", "loaf_bread", "baguette", "pastry", "castella", "donut", "banh_mi"),
    "SALAD": ("salad",),
    "GRILLED_DISH": ("grilled", "samgyeopsal", "steak", "barbecue", "garlic_shrimp", "grilled_salmon"),
    "BOWL_POKE": ("poke", "rice_bowl", "acai_bowl", "cup_bap"),
    "DESSERT_BAKERY": ("cake", "bread", "bingsu", "croffle", "hotteok", "macaron", "tart", "donut", "bagel", "cookie", "ice_cream", "gelato", "yogurt", "croissant", "salt_bread", "loaf_bread", "baguette", "pastry", "castella", "waffle", "churros"),
    "FRIED_SNACK": ("takoyaki", "french_fries", "chicken_wings", "cheese_balls", "cheese_sticks", "croquette", "fried_shrimp", "fried_squid", "tempura"),
}

CUISINE_ROOT_SUPPORT: dict[str, str] = {
    "dish_korean_cuisine": "KOREAN",
    "dish_korean_chinese_cuisine": "CHINESE",
    "dish_chinese_cuisine": "CHINESE",
    "dish_japanese_cuisine": "JAPANESE",
    "dish_italian_cuisine": "ITALIAN",
    "dish_american_cuisine": "AMERICAN",
    "dish_southeast_asian_cuisine": "SOUTHEAST_ASIAN",
    "dish_mexican_cuisine": "MEXICAN",
}

# A small number of legacy authored concepts live in the original standalone
# seed graph, which intentionally has no dependency on external cuisine-root
# documents.  These reviewed lineage overrides let the external release attach
# those families (and their descendants) without breaking fresh local seeds.
CONCEPT_CUISINE_SUPPORT_OVERRIDES: dict[str, str] = {
    "dish_pizza": "ITALIAN",
    "dish_udon": "JAPANESE",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in normalized if character.isalnum())


def mapping_surface(value: str) -> str:
    """Remove promotion, size, and explanatory wrappers before name matching."""

    cleaned = re.sub(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）", " ", value or "")
    return cleaned if normalized_name(cleaned) else value


def _authored_documents() -> list[AuthoredDocument]:
    roots = (ROOT / "knowledge" / "dishes", ROOT / "knowledge" / "external_dishes")
    documents: list[AuthoredDocument] = []
    for source_root in roots:
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*.md")):
            relative = path.relative_to(ROOT / "knowledge")
            documents.append(parse_document(path).model_copy(update={"path": relative}))
    if not documents:
        raise RuntimeError("EXTERNAL_KNOWLEDGE_DOCUMENTS_MISSING")
    return documents


def compile_external_release(catalog_release_id: str) -> CompiledKnowledgeRelease:
    documents = _authored_documents()
    source_manifest = {
        "catalog_release_id": catalog_release_id,
        "mapping_method": MAPPING_METHOD_VERSION,
        "support_method": SUPPORT_METHOD_VERSION,
        "feature_method": FEATURE_EXTRACTOR_VERSION,
        "membership_method": MEMBERSHIP_EXTRACTOR_VERSION,
        "documents": [
            {
                "path": document.path.as_posix(),
                "concept_id": document.front_matter.concept_id,
                "content": hashlib.sha256(
                    (canonical_json(document.front_matter_payload) + "\n" + document.body).encode(
                        "utf-8"
                    )
                ).hexdigest(),
            }
            for document in documents
        ],
    }
    release_id = f"external-knowledge-{sha256_payload(source_manifest)[:24]}"
    return compile_documents(
        documents,
        release_id=release_id,
        catalog_version=catalog_release_id,
    )


def _rows(cursor: Any, sql: str, parameters: Any = None) -> list[dict[str, Any]]:
    cursor.execute(sql, parameters or {})
    columns = [str(item[0]).lower() for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def active_catalog(cursor: Any) -> dict[str, str]:
    cursor.execute(
        """
        SELECT catalog_import_id,catalog_release_id
        FROM catalog_import_batch
        WHERE status='ACTIVE'
        ORDER BY completed_at DESC
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("ACTIVE_EXTERNAL_CATALOG_REQUIRED")
    return {"catalog_import_id": str(row[0]), "catalog_release_id": str(row[1])}


def fetch_catalog_menus(cursor: Any) -> list[dict[str, Any]]:
    return _rows(
        cursor,
        """
        SELECT menu.menu_id,menu.merchant_id,menu.name_ko,menu.name_en,
               menu.category,menu.description,menu.cultural_description,
               menu.semantic_text,menu.price,menu.availability,
               menu.is_synthetic,menu.data_origin,
               COALESCE(detail.liquor,0) AS liquor,
               COALESCE(detail.is_adult,0) AS is_adult,
               COALESCE(detail.soldout,0) AS soldout
        FROM menu
        LEFT JOIN menu_source_detail detail ON detail.menu_id=menu.menu_id
        ORDER BY menu.menu_id
        """,
    )


def fetch_menu_feature_sources(
    cursor: Any,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(
        cursor,
        """
        SELECT item.menu_id,section.source_section_key,section.title,section.description
        FROM menu_source_section_item item
        JOIN menu_source_section section
          ON section.source_section_key=item.source_section_key
        ORDER BY item.menu_id,section.sort_order,section.source_section_key
        """,
    ):
        row["source_ref"] = f"menu-section:{row['source_section_key']}"
        sections[str(row["menu_id"])].append(row)

    options: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(
        cursor,
        """
        SELECT group_row.menu_id,item.option_item_id,item.name_ko,item.name_en,
               item.description
        FROM menu_option_group group_row
        JOIN menu_option_item item ON item.option_group_id=group_row.option_group_id
        WHERE item.availability='AVAILABLE'
        ORDER BY group_row.menu_id,group_row.sort_order,item.sort_order,item.option_item_id
        """,
    ):
        row["source_ref"] = f"menu-option:{row['option_item_id']}"
        options[str(row["menu_id"])].append(row)
    return dict(sections), dict(options)


def _concept_aliases(compiled: CompiledKnowledgeRelease) -> list[dict[str, str]]:
    aliases: list[dict[str, str]] = []
    for concept in compiled.concepts:
        if concept["concept_type"] == "CUISINE":
            continue
        values = {
            str(concept["canonical_name_ko"]),
            *[str(value) for value in json.loads(str(concept["aliases_json"]))],
        }
        for value in values:
            normalized = normalized_name(value)
            if len(normalized) < 2 or not re.search(r"[가-힣]", value):
                continue
            aliases.append(
                {
                    "alias": normalized,
                    "display_alias": value,
                    "concept_id": str(concept["concept_id"]),
                    "concept_type": str(concept["concept_type"]),
                }
            )
    return sorted(
        aliases,
        key=lambda item: (
            -len(item["alias"]),
            item["concept_id"],
            item["alias"],
            item["display_alias"],
        ),
    )


def classify_menus(
    menus: Sequence[Mapping[str, Any]], compiled: CompiledKnowledgeRelease
) -> list[dict[str, Any]]:
    aliases = _concept_aliases(compiled)
    timestamp = now()
    rows: list[dict[str, Any]] = []
    for menu in menus:
        menu_name = str(menu["name_ko"])
        category = str(menu["category"])
        # Brackets often contain the actual ordered dish in this source (for
        # example ``[등심 돈까스]`` or ``(접시빙수)``), so they are evidence and
        # must not be discarded.  Safety comes from the reviewed alias list,
        # minimum signal rules, and explicit non-food/add-on exclusions below.
        normalized_menu = normalized_name(menu_name)
        normalized_category = normalized_name(category)
        reason: str | None = None
        concept_id: str | None = None
        mapping_type = "UNMAPPED"
        source_ref = f"{MAPPING_METHOD_VERSION}:no-match"

        if int(menu.get("liquor") or 0) or int(menu.get("is_adult") or 0):
            reason = "NON_FOOD_OR_PROMOTION"
            source_ref = f"{MAPPING_METHOD_VERSION}:source-liquor-or-adult"
        elif int(menu.get("price") or 0) <= 0 or PROMOTION_NAME.search(menu_name):
            reason = "NON_FOOD_OR_PROMOTION"
            source_ref = f"{MAPPING_METHOD_VERSION}:promotion-signal"
        elif NON_FOOD_CATEGORY.search(menu_name):
            reason = "NON_FOOD_OR_PROMOTION"
            source_ref = f"{MAPPING_METHOD_VERSION}:non-food-category"
        elif COMPOSITE_NAME.search(menu_name):
            reason = "UNSUPPORTED_COMPOSITE"
            source_ref = f"{MAPPING_METHOD_VERSION}:composite-signal"
        else:
            hits = [item for item in aliases if item["alias"] in normalized_menu]
            reviewed_food_signal = any(
                item["alias"] == normalized_menu
                or len(item["alias"]) >= 3
                or item["alias"] in REVIEWED_STANDALONE_SHORT_ALIASES
                for item in hits
            )
            category_is_non_food = bool(
                NON_FOOD_CATEGORY.search(category) and not reviewed_food_signal
            )
            if category_is_non_food:
                reason = "NON_FOOD_OR_PROMOTION"
                source_ref = f"{MAPPING_METHOD_VERSION}:non-food-category"
            elif hits:
                # Korean product names commonly place the head food at the end
                # (for example 불고기볶음밥 or 스테이크버거). Prefer the rightmost
                # reviewed food alias, then the longest alias at that position.
                # This resolves mixed descriptors without treating '+' or set
                # products as a single dish; those were already excluded above.
                # First collapse aliases ending at the same position to the
                # longest, most specific phrase (``로제떡볶이`` must beat its
                # suffix ``떡볶이``).  Then combine three independently useful
                # signals: phrase specificity, merchant-category confirmation,
                # and the Korean rightmost head noun.  The weights were checked
                # against the active catalog: category + rightmost can beat a
                # filling such as ``불고기`` in ``불고기버거``, while a reviewed
                # variant still beats its generic family suffix.
                ends = {
                    id(item): normalized_menu.rfind(item["alias"]) + len(item["alias"])
                    for item in hits
                }
                longest_at_end: dict[int, int] = {}
                for item in hits:
                    end = ends[id(item)]
                    longest_at_end[end] = max(
                        longest_at_end.get(end, 0), len(item["alias"])
                    )
                specific_hits = [
                    item
                    for item in hits
                    if len(item["alias"]) == longest_at_end[ends[id(item)]]
                ]
                rightmost_end = max(ends[id(item)] for item in specific_hits)

                signal_scores = {
                    id(item): (
                        len(item["alias"]) * 2
                        + (4 if item["alias"] in normalized_category else 0)
                        + (2 if ends[id(item)] == rightmost_end else 0)
                    )
                    for item in specific_hits
                }

                highest_score = max(signal_scores.values())
                best = [
                    item
                    for item in specific_hits
                    if signal_scores[id(item)] == highest_score
                ]
                # Deterministic tie-breakers retain the independently confirmed
                # category signal and then the head position.
                if len({item["concept_id"] for item in best}) > 1:
                    category_best = [
                        item for item in best if item["alias"] in normalized_category
                    ]
                    if category_best:
                        best = category_best
                if len({item["concept_id"] for item in best}) > 1:
                    best_end = max(ends[id(item)] for item in best)
                    best = [item for item in best if ends[id(item)] == best_end]
                best_concepts = sorted({item["concept_id"] for item in best})
                selected = best[0]
                exact_name = selected["alias"] == normalized_menu
                category_confirmation = selected["alias"] in normalized_category
                long_reviewed_alias = len(selected["alias"]) >= 3
                standalone_short_alias = (
                    selected["alias"] in REVIEWED_STANDALONE_SHORT_ALIASES
                )
                if len(best_concepts) > 1:
                    reason = "AMBIGUOUS_NAME"
                    source_ref = f"{MAPPING_METHOD_VERSION}:equal-best-concepts"
                elif selected["concept_id"] in RECOMMENDATION_EXCLUDED_CONCEPTS:
                    reason = "NON_FOOD_OR_PROMOTION"
                    source_ref = f"{MAPPING_METHOD_VERSION}:beverage-concept"
                elif (
                    selected["concept_id"] in CONCEPT_REJECTION_PATTERNS
                    and CONCEPT_REJECTION_PATTERNS[selected["concept_id"]].search(menu_name)
                ):
                    reason = "AMBIGUOUS_NAME"
                    source_ref = f"{MAPPING_METHOD_VERSION}:reviewed-false-positive"
                elif (
                    exact_name
                    or category_confirmation
                    or long_reviewed_alias
                    or standalone_short_alias
                ):
                    concept_id = selected["concept_id"]
                    mapping_type = (
                        "EXACT" if exact_name else ("VARIANT" if selected["concept_type"] == "VARIANT" else "FAMILY")
                    )
                    source_ref = (
                        f"{MAPPING_METHOD_VERSION}:alias={selected['display_alias']}:"
                        "signal="
                        + (
                            "exact"
                            if exact_name
                            else "category"
                            if category_confirmation
                            else "long-alias"
                            if long_reviewed_alias
                            else "reviewed-short-alias"
                        )
                    )
                else:
                    reason = "AMBIGUOUS_NAME"
                    source_ref = f"{MAPPING_METHOD_VERSION}:short-alias-without-second-signal"
            elif not category_is_non_food:
                reason = "CONCEPT_NOT_AUTHORED"

        mapped = concept_id is not None
        rows.append(
            {
                "release_id": compiled.release_id,
                "menu_id": str(menu["menu_id"]),
                "concept_id": concept_id,
                "mapping_status": "MAPPED" if mapped else "UNMAPPED",
                "mapping_type": mapping_type,
                "unmapped_reason": None if mapped else reason,
                "confidence_band": "high" if mapped else "low",
                "source_type": MAPPING_PROVENANCE,
                "source_ref": source_ref,
                "review_status": "REVIEWED_DEMO" if mapped else "CLASSIFIED_DEMO",
                "is_synthetic": 1,
                "updated_at": timestamp,
            }
        )
    return rows


def _public_chunks(compiled: CompiledKnowledgeRelease) -> dict[str, list[dict[str, Any]]]:
    reviewed_documents = {
        str(row["document_id"])
        for row in compiled.documents
        if row["source_type"] == "SYNTHETIC_WIKI"
        and row["review_status"] == "REVIEWED_DEMO"
    }
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in compiled.chunks:
        if str(chunk["document_id"]) not in reviewed_documents:
            continue
        metadata = json.loads(str(chunk["metadata_json"]))
        if metadata.get("recommendation_visibility") == "INTERNAL_ONLY":
            continue
        result[str(chunk["concept_id"])].append(chunk)
    for values in result.values():
        values.sort(key=lambda item: (int(item["chunk_index"]), str(item["chunk_id"])))
    return result


def build_support_rows(compiled: CompiledKnowledgeRelease) -> list[dict[str, Any]]:
    chunks_by_concept = _public_chunks(compiled)
    ancestors: dict[str, set[str]] = defaultdict(set)
    for row in compiled.closure:
        ancestors[str(row["descendant_concept_id"])].add(str(row["ancestor_concept_id"]))
    claims_by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in compiled.claims:
        claims_by_concept[str(claim["concept_id"])].append(claim)

    timestamp = now()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_support(
        concept_id: str,
        category_code: str,
        option_code: str,
        strength: float,
        terms: tuple[str, ...] = (),
    ) -> None:
        key = (concept_id, category_code, option_code)
        if key in seen:
            return
        chunks = chunks_by_concept.get(concept_id, [])
        evidence: dict[str, Any] | None = None
        for chunk in chunks:
            content = str(chunk["content"])
            if not terms or any(preference_term_matches(content, term) for term in terms):
                evidence = chunk
                break
        if evidence is None:
            return
        seen.add(key)
        rows.append(
            {
                "knowledge_release_id": compiled.release_id,
                "concept_id": concept_id,
                "category_code": category_code,
                "option_code": option_code,
                "support_status": "SUPPORTED",
                "support_strength": round(strength, 4),
                "evidence_chunk_id": str(evidence["chunk_id"]),
                "provenance_type": SUPPORT_PROVENANCE,
                "source_ref": f"knowledge:{evidence['document_id']}:{evidence['chunk_id']}",
                "review_status": "REVIEWED_DEMO",
                "support_method_version": SUPPORT_METHOD_VERSION,
                "is_synthetic": 1,
                "updated_at": timestamp,
            }
        )

    for concept in compiled.concepts:
        concept_id = str(concept["concept_id"])
        if concept["concept_type"] == "CUISINE" or concept_id not in chunks_by_concept:
            continue
        lineage = ancestors.get(concept_id, {concept_id})
        for root_concept_id, option_code in CUISINE_ROOT_SUPPORT.items():
            if root_concept_id in lineage:
                add_support(concept_id, "cuisine_origins", option_code, 1.0)
        for ancestor_concept_id, option_code in CONCEPT_CUISINE_SUPPORT_OVERRIDES.items():
            if ancestor_concept_id in lineage:
                add_support(concept_id, "cuisine_origins", option_code, 1.0)

        for claim in claims_by_concept.get(concept_id, []):
            if claim["claim_type"] == "INGREDIENT":
                option = INGREDIENT_SUPPORT.get(str(claim.get("ingredient_id") or ""))
                if option:
                    add_support(concept_id, "main_ingredients", option, 1.0)
            elif claim["claim_type"] == "PREPARATION":
                option = PREPARATION_SUPPORT.get(str(claim.get("facet_key") or ""))
                if option:
                    add_support(concept_id, "cooking_methods", option, 1.0)

        normalized_concept = normalized_name(
            f"{concept_id} {concept['canonical_name_en']} {concept['canonical_name_ko']}"
        )
        for option, markers in FORM_CONCEPT_MARKERS.items():
            if any(normalized_name(marker) in normalized_concept for marker in markers):
                add_support(concept_id, "food_forms", option, 0.95)

        for (category_code, option_code), terms in TEXT_SUPPORT_RULES.items():
            add_support(concept_id, category_code, option_code, 0.8, terms)

    return sorted(
        rows,
        key=lambda row: (
            row["concept_id"],
            row["category_code"],
            row["option_code"],
        ),
    )


def support_manifest_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    stable_fields = (
        "knowledge_release_id",
        "concept_id",
        "category_code",
        "option_code",
        "support_status",
        "support_strength",
        "evidence_chunk_id",
        "provenance_type",
        "source_ref",
        "review_status",
        "support_method_version",
        "is_synthetic",
    )
    return sha256_payload(
        [{field: row[field] for field in stable_fields} for row in rows]
    )


def _coverage(
    menus: Sequence[Mapping[str, Any]],
    mappings: Sequence[Mapping[str, Any]],
    supports: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    menu_by_id = {str(row["menu_id"]): row for row in menus}
    codes_by_concept: dict[str, set[str]] = defaultdict(set)
    for row in supports:
        if row["support_status"] == "SUPPORTED":
            codes_by_concept[str(row["concept_id"])].add(str(row["option_code"]))
    menu_ids_by_code: dict[str, set[str]] = defaultdict(set)
    merchant_ids_by_code: dict[str, set[str]] = defaultdict(set)
    for mapping in mappings:
        concept_id = mapping.get("concept_id")
        if not concept_id:
            continue
        menu = menu_by_id[str(mapping["menu_id"])]
        if str(menu["availability"]) != "AVAILABLE":
            continue
        for code in codes_by_concept[str(concept_id)]:
            menu_ids_by_code[code].add(str(menu["menu_id"]))
            merchant_ids_by_code[code].add(str(menu["merchant_id"]))
    return {
        code: {"menu_count": len(menu_ids), "merchant_count": len(merchant_ids_by_code[code])}
        for code, menu_ids in sorted(menu_ids_by_code.items())
    }


def build_plan(cursor: Any) -> dict[str, Any]:
    catalog = active_catalog(cursor)
    compiled = compile_external_release(catalog["catalog_release_id"])
    menus = fetch_catalog_menus(cursor)
    sections_by_menu, options_by_menu = fetch_menu_feature_sources(cursor)
    mappings = classify_menus(menus, compiled)
    supports = build_support_rows(compiled)
    memberships = build_menu_concept_memberships(
        knowledge_release_id=compiled.release_id,
        menus=menus,
        mappings=mappings,
        concepts=compiled.concepts,
    )
    features, feature_evidence = compile_menu_preference_features(
        knowledge_release_id=compiled.release_id,
        menus=menus,
        mappings=mappings,
        concept_supports=supports,
        chunks=compiled.chunks,
        sections_by_menu=sections_by_menu,
        options_by_menu=options_by_menu,
    )
    mapping_reasons = Counter(
        "MAPPED_HIGH" if row["mapping_status"] == "MAPPED" else str(row["unmapped_reason"])
        for row in mappings
    )
    mapped_concepts = {str(row["concept_id"]) for row in mappings if row["concept_id"]}
    coverage = _coverage(menus, mappings, supports)
    exposed = {
        code: counts
        for code, counts in coverage.items()
        if preference_option_is_exposable(
            code,
            menu_count=counts["menu_count"],
            merchant_count=counts["merchant_count"],
            document_count=len(
                {
                    str(row["evidence_chunk_id"])
                    for row in supports
                    if str(row["option_code"]) == code
                }
            ),
        )
    }
    support_manifest = support_manifest_sha256(supports)
    feature_manifest = feature_manifest_sha256(features, feature_evidence, memberships)
    ranking_manifest = sha256_payload(RANKING_POLICY)
    if ranking_manifest != RANKING_POLICY_SHA256:
        raise RuntimeError("canonical ranking policy hash mismatch")
    family_id = (
        f"external-recommendation-{compiled.release_id.rsplit('-', 1)[-1]}-"
        f"{feature_manifest[:10]}-{ranking_manifest[:10]}"
    )
    return {
        "catalog": catalog,
        "compiled": compiled,
        "menus": menus,
        "mappings": mappings,
        "supports": supports,
        "memberships": memberships,
        "features": features,
        "feature_evidence": feature_evidence,
        "support_manifest_sha256": support_manifest,
        "feature_manifest_sha256": feature_manifest,
        "ranking_policy_sha256": ranking_manifest,
        "release_family_id": family_id,
        "summary": {
            "catalog_menu_count": len(menus),
            "knowledge_release_id": compiled.release_id,
            "knowledge_counts": compiled.expected_counts,
            "classification": dict(sorted(mapping_reasons.items())),
            "classified_menu_count": len(mappings),
            "mapped_concept_count": len(mapped_concepts),
            "support_row_count": len(supports),
            "menu_feature_count": len(features),
            "menu_feature_evidence_count": len(feature_evidence),
            "menu_concept_membership_count": len(memberships),
            "feature_counts_by_provenance": dict(
                sorted(Counter(str(row["provenance_type"]) for row in features).items())
            ),
            "feature_counts_by_scope": dict(
                sorted(Counter(str(row["evidence_scope"]) for row in features).items())
            ),
            "exposed_preference_coverage": exposed,
            "support_manifest_sha256": support_manifest,
            "feature_manifest_sha256": feature_manifest,
            "feature_extractor_version": FEATURE_EXTRACTOR_VERSION,
            "ranking_policy_version": RANKING_POLICY_VERSION,
            "ranking_policy_sha256": ranking_manifest,
            "release_family_id": family_id,
        },
    }


def _insert_many(cursor: Any, table: str, rows: Sequence[Mapping[str, Any]], oracle: bool) -> None:
    if not rows:
        return
    columns = list(rows[0])
    if oracle:
        sql = (
            f"INSERT INTO {table} ({','.join(columns)}) VALUES "
            f"({','.join(':' + column for column in columns)})"
        )
        payload: list[dict[str, Any]] = []
        for source in rows:
            row = dict(source)
            for column in columns:
                value = row[column]
                if column.endswith("_at") and isinstance(value, str):
                    row[column] = datetime.fromisoformat(value)
            payload.append(row)
        cursor.executemany(sql, payload)
    else:
        placeholders = ",".join("?" for _ in columns)
        cursor.executemany(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
            [[row[column] for column in columns] for row in rows],
        )


def _insert_taxonomy(cursor: Any, oracle: bool) -> None:
    ingredients, allergens, dietary = _taxonomy_rows(ROOT / "knowledge" / "dishes")
    for table, key, rows in (
        ("ingredient", "ingredient_id", ingredients),
        ("allergen", "allergen_id", allergens),
        ("dietary_attribute", "attribute_id", dietary),
    ):
        if oracle:
            for row in rows:
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {key}=:{key}", {key: row[key]})
                if int(cursor.fetchone()[0]) == 0:
                    _insert_many(cursor, table, [row], True)
        else:
            columns = list(rows[0]) if rows else []
            placeholders = ",".join("?" for _ in columns)
            if rows:
                cursor.executemany(
                    f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                    [[row[column] for column in columns] for row in rows],
                )


def _preference_catalog_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    preference_rows = [
        {
            "catalog_version": PREFERENCE_CATALOG_VERSION,
            "category_code": category.code,
            "option_code": option.code,
            "label_ko": option.labels["ko"],
            "label_en": option.labels["en"],
            "query_aliases_json": json.dumps(option.query_aliases, ensure_ascii=False),
            "display_order": display_order,
            "active": 1,
        }
        for category in PREFERENCE_CATEGORIES
        for display_order, option in enumerate(category.options)
    ]
    by_locale: dict[str, dict[str, dict[str, Any]]] = {}
    for locale in ("ko", "en"):
        by_locale[locale] = {
            str(reference["country"]): reference
            for reference in localized_spice_references(locale)
        }
    spice_rows: list[dict[str, Any]] = []
    for country in ("KR", "US"):
        levels: dict[str, dict[int, dict[str, Any]]] = {}
        for locale in ("ko", "en"):
            raw_levels = by_locale[locale][country]["levels"]
            if not isinstance(raw_levels, list):
                raise TypeError("SPICE_REFERENCE_LEVELS_INVALID")
            levels[locale] = {
                int(str(item["level"])): item
                for item in raw_levels
                if isinstance(item, dict)
            }
        for level in range(1, 6):
            spice_rows.append(
                {
                    "reference_version": f"{PREFERENCE_CATALOG_VERSION}-spice",
                    "country_code": country,
                    "spice_level": level,
                    "label_ko": str(levels["ko"][level]["label"]),
                    "label_en": str(levels["en"][level]["label"]),
                    "example_ko": str(levels["ko"][level]["example"]),
                    "example_en": str(levels["en"][level]["example"]),
                }
            )
    return preference_rows, spice_rows


def _ensure_preference_catalog(cursor: Any, oracle: bool) -> None:
    """Insert the immutable catalog version that a staged family references."""

    preference_rows, spice_rows = _preference_catalog_rows()
    for table, version_column, version, rows in (
        (
            "recommendation_preference_option",
            "catalog_version",
            PREFERENCE_CATALOG_VERSION,
            preference_rows,
        ),
        (
            "spice_reference",
            "reference_version",
            f"{PREFERENCE_CATALOG_VERSION}-spice",
            spice_rows,
        ),
    ):
        count = _existing_count(cursor, table, version_column, version, oracle)
        if count == 0:
            _insert_many(cursor, table, rows, oracle)
        elif count != len(rows):
            raise RuntimeError(f"IMMUTABLE_{table.upper()}_INCOMPLETE")

    preference_sql = """
        SELECT category_code,option_code,display_order,active
        FROM recommendation_preference_option
        WHERE catalog_version=:catalog_version
    """ if oracle else """
        SELECT category_code,option_code,display_order,active
        FROM recommendation_preference_option
        WHERE catalog_version=?
    """
    cursor.execute(
        preference_sql,
        {"catalog_version": PREFERENCE_CATALOG_VERSION}
        if oracle
        else (PREFERENCE_CATALOG_VERSION,),
    )
    actual_preference_keys = {
        (str(row[0]), str(row[1]), int(row[2]), int(row[3]))
        for row in cursor.fetchall()
    }
    expected_preference_keys = {
        (
            str(row["category_code"]),
            str(row["option_code"]),
            int(row["display_order"]),
            int(row["active"]),
        )
        for row in preference_rows
    }
    if actual_preference_keys != expected_preference_keys:
        raise RuntimeError("IMMUTABLE_PREFERENCE_CATALOG_KEY_MISMATCH")

    spice_sql = """
        SELECT country_code,spice_level
        FROM spice_reference WHERE reference_version=:reference_version
    """ if oracle else """
        SELECT country_code,spice_level
        FROM spice_reference WHERE reference_version=?
    """
    spice_version = f"{PREFERENCE_CATALOG_VERSION}-spice"
    cursor.execute(
        spice_sql,
        {"reference_version": spice_version} if oracle else (spice_version,),
    )
    actual_spice_keys = {(str(row[0]), int(row[1])) for row in cursor.fetchall()}
    expected_spice_keys = {
        (str(row["country_code"]), int(row["spice_level"])) for row in spice_rows
    }
    if actual_spice_keys != expected_spice_keys:
        raise RuntimeError("IMMUTABLE_SPICE_REFERENCE_KEY_MISMATCH")


def _existing_count(cursor: Any, table: str, column: str, value: str, oracle: bool) -> int:
    placeholder = f":{column}" if oracle else "?"
    cursor.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column}={placeholder}",
        {column: value} if oracle else (value,),
    )
    return int(cursor.fetchone()[0])


def ensure_sqlite_contract(connection: sqlite3.Connection) -> None:
    """Apply SQLite equivalents of additive migrations 012-013 for mirrors."""

    zero_hash = "0" * 64
    family_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(recommendation_release_family)"
        ).fetchall()
    }
    for column, definition in (
        ("support_manifest_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
        ("feature_manifest_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
        ("ranking_policy_version", "TEXT NOT NULL DEFAULT 'legacy-llm-rank-v2'"),
        ("ranking_policy_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
    ):
        if column not in family_columns:
            connection.execute(
                f"ALTER TABLE recommendation_release_family ADD COLUMN {column} {definition}"
            )
    for table, column, definition in (
        (
            "structured_recommendation_request",
            "feature_manifest_sha256",
            f"TEXT NOT NULL DEFAULT '{zero_hash}'",
        ),
        ("recommendation_snapshot", "feature_manifest_sha256", "TEXT"),
    ):
        columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS concept_preference_support (
          knowledge_release_id TEXT NOT NULL,
          concept_id TEXT NOT NULL,
          category_code TEXT NOT NULL,
          option_code TEXT NOT NULL,
          support_status TEXT NOT NULL
            CHECK (support_status IN ('SUPPORTED','UNSUPPORTED','REVIEW_REQUIRED')),
          support_strength REAL NOT NULL CHECK (support_strength >= 0 AND support_strength <= 1),
          evidence_chunk_id TEXT,
          provenance_type TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          review_status TEXT NOT NULL,
          support_method_version TEXT NOT NULL,
          is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
          updated_at TEXT NOT NULL,
          PRIMARY KEY(knowledge_release_id, concept_id, category_code, option_code),
          FOREIGN KEY(knowledge_release_id, concept_id)
            REFERENCES dish_concept(release_id, concept_id),
          FOREIGN KEY(knowledge_release_id, evidence_chunk_id)
            REFERENCES knowledge_chunk(release_id, chunk_id),
          CHECK (support_status != 'SUPPORTED' OR evidence_chunk_id IS NOT NULL)
        );
        CREATE INDEX IF NOT EXISTS idx_concept_pref_lookup
          ON concept_preference_support(
            knowledge_release_id, category_code, option_code, support_status, concept_id
          );
        CREATE INDEX IF NOT EXISTS idx_concept_pref_concept
          ON concept_preference_support(knowledge_release_id, concept_id, support_status);
        CREATE TABLE IF NOT EXISTS menu_preference_feature (
          knowledge_release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
          feature_id TEXT NOT NULL,
          menu_id TEXT NOT NULL REFERENCES menu(menu_id),
          category_code TEXT NOT NULL,
          option_code TEXT NOT NULL,
          support_status TEXT NOT NULL
            CHECK (support_status IN ('SUPPORTED','CONTRADICTED','REVIEW_REQUIRED')),
          support_strength REAL NOT NULL CHECK (support_strength >= 0 AND support_strength <= 1),
          confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
          specificity REAL NOT NULL CHECK (specificity >= 0 AND specificity <= 1),
          evidence_scope TEXT NOT NULL
            CHECK (evidence_scope IN ('MENU_DIRECT','SECTION_CONTEXT','OPTION_AVAILABILITY','CONCEPT_GENERAL')),
          provenance_type TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          review_status TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
          updated_at TEXT NOT NULL,
          PRIMARY KEY(knowledge_release_id, feature_id),
          UNIQUE(knowledge_release_id, menu_id, category_code, option_code)
        );
        CREATE TABLE IF NOT EXISTS menu_preference_feature_evidence (
          knowledge_release_id TEXT NOT NULL,
          evidence_id TEXT NOT NULL,
          feature_id TEXT NOT NULL,
          evidence_role TEXT NOT NULL
            CHECK (evidence_role IN ('SUPPORT','CONTRADICTION','CONTEXT','OVERRIDDEN_GENERAL')),
          source_type TEXT NOT NULL
            CHECK (source_type IN ('MENU_NAME','MENU_DESCRIPTION','MENU_SECTION','MENU_OPTION','WIKI_CHUNK')),
          excerpt TEXT NOT NULL,
          excerpt_sha256 TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          provenance_type TEXT NOT NULL,
          is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
          updated_at TEXT NOT NULL,
          PRIMARY KEY(knowledge_release_id, evidence_id),
          FOREIGN KEY(knowledge_release_id, feature_id)
            REFERENCES menu_preference_feature(knowledge_release_id, feature_id)
        );
        CREATE TABLE IF NOT EXISTS menu_concept_membership (
          knowledge_release_id TEXT NOT NULL REFERENCES knowledge_release(release_id),
          menu_id TEXT NOT NULL REFERENCES menu(menu_id),
          concept_id TEXT NOT NULL,
          membership_role TEXT NOT NULL
            CHECK (membership_role IN ('PRIMARY','COMPONENT','SECONDARY')),
          confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
          provenance_type TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          review_status TEXT NOT NULL,
          extractor_version TEXT NOT NULL,
          is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic IN (0,1)),
          updated_at TEXT NOT NULL,
          PRIMARY KEY(knowledge_release_id, menu_id, concept_id),
          FOREIGN KEY(knowledge_release_id, concept_id)
            REFERENCES dish_concept(release_id, concept_id)
        );
        CREATE INDEX IF NOT EXISTS idx_menu_pref_feature_lookup
          ON menu_preference_feature(
            knowledge_release_id, category_code, option_code, support_status, menu_id
          );
        CREATE INDEX IF NOT EXISTS idx_menu_pref_feature_menu
          ON menu_preference_feature(knowledge_release_id, menu_id, support_status);
        CREATE INDEX IF NOT EXISTS idx_menu_pref_evidence_feature
          ON menu_preference_feature_evidence(knowledge_release_id, feature_id, evidence_role);
        CREATE INDEX IF NOT EXISTS idx_menu_concept_membership_lookup
          ON menu_concept_membership(
            knowledge_release_id, concept_id, membership_role, menu_id
          );
        CREATE INDEX IF NOT EXISTS idx_menu_concept_high
          ON menu_concept_map(release_id, mapping_status, confidence_band, concept_id, menu_id);
        CREATE INDEX IF NOT EXISTS idx_menu_recommend_filter
          ON menu(availability, price, merchant_id, menu_id);
        CREATE INDEX IF NOT EXISTS idx_menu_source_restrict
          ON menu_source_detail(liquor, is_adult, verified_adult, soldout, menu_id);
        """
    )
    connection.commit()


def runtime_pointers(cursor: Any, oracle: bool) -> tuple[str | None, str | None]:
    """Return knowledge and recommendation pointers without emitting their values."""

    cursor.execute(
        "SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'"
    )
    knowledge_row = cursor.fetchone()
    cursor.execute(
        """
        SELECT active_release_family_id
        FROM recommendation_runtime_state
        WHERE state_key='ACTIVE'
        """
    )
    family_row = cursor.fetchone()
    return (
        str(knowledge_row[0]) if knowledge_row is not None else None,
        str(family_row[0]) if family_row is not None else None,
    )


def _stage_verified_plan(
    connection: Any,
    oracle: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cursor = connection.cursor()
    if not oracle:
        ensure_sqlite_contract(connection)
        cursor = connection.cursor()
    pointers_before = runtime_pointers(cursor, oracle)
    plan = build_plan(cursor)
    compiled: CompiledKnowledgeRelease = plan["compiled"]
    try:
        if oracle:
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version='013'")
            if int(cursor.fetchone()[0]) != 1:
                raise RuntimeError("MIGRATION_013_NOT_APPLIED")
        _insert_taxonomy(cursor, oracle)
        if oracle:
            load_oracle_release(connection, compiled, activate=False)
        else:
            load_sqlite_release(connection, compiled, activate=False)
            cursor = connection.cursor()

        mapping_count = _existing_count(
            cursor, "menu_concept_map", "release_id", compiled.release_id, oracle
        )
        if mapping_count == 0:
            _insert_many(cursor, "menu_concept_map", plan["mappings"], oracle)
        elif mapping_count != len(plan["mappings"]):
            raise RuntimeError("IMMUTABLE_MAPPING_RELEASE_INCOMPLETE")

        support_count = _existing_count(
            cursor,
            "concept_preference_support",
            "knowledge_release_id",
            compiled.release_id,
            oracle,
        )
        if support_count == 0:
            _insert_many(cursor, "concept_preference_support", plan["supports"], oracle)
        elif support_count != len(plan["supports"]):
            raise RuntimeError("IMMUTABLE_SUPPORT_RELEASE_INCOMPLETE")

        membership_count = _existing_count(
            cursor,
            "menu_concept_membership",
            "knowledge_release_id",
            compiled.release_id,
            oracle,
        )
        if membership_count == 0:
            _insert_many(cursor, "menu_concept_membership", plan["memberships"], oracle)
        elif membership_count != len(plan["memberships"]):
            raise RuntimeError("IMMUTABLE_CONCEPT_MEMBERSHIP_RELEASE_INCOMPLETE")

        feature_count = _existing_count(
            cursor,
            "menu_preference_feature",
            "knowledge_release_id",
            compiled.release_id,
            oracle,
        )
        if feature_count == 0:
            _insert_many(cursor, "menu_preference_feature", plan["features"], oracle)
            _insert_many(
                cursor,
                "menu_preference_feature_evidence",
                plan["feature_evidence"],
                oracle,
            )
        elif feature_count != len(plan["features"]):
            raise RuntimeError("IMMUTABLE_MENU_FEATURE_RELEASE_INCOMPLETE")
        evidence_count = _existing_count(
            cursor,
            "menu_preference_feature_evidence",
            "knowledge_release_id",
            compiled.release_id,
            oracle,
        )
        if evidence_count != len(plan["feature_evidence"]):
            raise RuntimeError("IMMUTABLE_MENU_FEATURE_EVIDENCE_RELEASE_INCOMPLETE")

        _ensure_preference_catalog(cursor, oracle)

        family_values = {
            "release_family_id": plan["release_family_id"],
            "knowledge_release_id": compiled.release_id,
            "catalog_release_id": plan["catalog"]["catalog_release_id"],
            "preference_catalog_version": PREFERENCE_CATALOG_VERSION,
            "spice_reference_version": f"{PREFERENCE_CATALOG_VERSION}-spice",
            "certification_release_id": (
                f"external-certifications-none-{plan['catalog']['catalog_import_id'][-20:]}"
            ),
            "embedding_model": compiled.embedding_model,
            "embedding_version": compiled.embedding_version,
            "support_manifest_sha256": plan["support_manifest_sha256"],
            "feature_manifest_sha256": plan["feature_manifest_sha256"],
            "ranking_policy_version": RANKING_POLICY_VERSION,
            "ranking_policy_sha256": plan["ranking_policy_sha256"],
            "status": "READY",
            "activated_at": None,
        }
        family_count = _existing_count(
            cursor,
            "recommendation_release_family",
            "release_family_id",
            plan["release_family_id"],
            oracle,
        )
        if family_count == 0:
            _insert_many(cursor, "recommendation_release_family", [family_values], oracle)

        staging_verification = verify_release_family(
            cursor,
            oracle,
            family_id=str(plan["release_family_id"]),
            require_active=False,
        )
        if not staging_verification["pass"]:
            raise RuntimeError("EXTERNAL_KNOWLEDGE_STAGING_VERIFICATION_FAILED")
        if runtime_pointers(cursor, oracle) != pointers_before:
            raise RuntimeError("STAGING_CHANGED_ACTIVE_POINTERS")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise

    committed_verification = verify_release_family(
        connection.cursor(),
        oracle,
        family_id=str(plan["release_family_id"]),
        require_active=False,
    )
    if not committed_verification["pass"]:
        raise RuntimeError("EXTERNAL_KNOWLEDGE_COMMITTED_STAGING_INVALID")
    pointer_invariant = runtime_pointers(connection.cursor(), oracle) == pointers_before
    if not pointer_invariant:
        raise RuntimeError("STAGING_CHANGED_ACTIVE_POINTERS")
    result = {
        **plan["summary"],
        "backend": "oracle-26ai" if oracle else "sqlite",
        "transaction_committed": True,
        "activation_performed": False,
        "active_pointers_unchanged": pointer_invariant,
        "staging_verification": committed_verification,
    }
    return plan, result


def stage_plan(connection: Any, oracle: bool) -> dict[str, Any]:
    """Load and verify the deterministic READY family without changing pointers."""

    _plan, result = _stage_verified_plan(connection, oracle)
    return result


def activate_staged_plan(
    connection: Any,
    oracle: bool,
    *,
    plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reverify and atomically activate the deterministic staged family."""

    resolved_plan = dict(plan) if plan is not None else build_plan(connection.cursor())
    staged_verification = verify_release_family(
        connection.cursor(),
        oracle,
        family_id=str(resolved_plan["release_family_id"]),
        require_active=False,
    )
    if not staged_verification["pass"]:
        raise RuntimeError("EXTERNAL_KNOWLEDGE_STAGED_RELEASE_INVALID")
    verification = _activate_verified_plan(connection, resolved_plan, oracle)
    committed_verification = verify_active(connection.cursor(), oracle)
    if (
        not committed_verification["pass"]
        or committed_verification.get("release_family_id")
        != str(resolved_plan["release_family_id"])
        or committed_verification.get("knowledge_release_id")
        != str(resolved_plan["compiled"].release_id)
    ):
        raise RuntimeError("EXTERNAL_KNOWLEDGE_ACTIVE_VERIFICATION_FAILED")
    return {
        **resolved_plan["summary"],
        "backend": "oracle-26ai" if oracle else "sqlite",
        "transaction_committed": True,
        "activation_performed": True,
        "staging_verification": staged_verification,
        "activation_transaction_verification": verification,
        "verification": committed_verification,
    }


def apply_plan(connection: Any, oracle: bool) -> dict[str, Any]:
    """Backward-compatible stage plus activation in one command invocation."""

    plan, staging_result = _stage_verified_plan(connection, oracle)
    activation_result = activate_staged_plan(connection, oracle, plan=plan)
    return {
        **activation_result,
        "staging": staging_result,
    }


def _activate_verified_plan(
    connection: Any,
    plan: Mapping[str, Any],
    oracle: bool,
) -> dict[str, Any]:
    """Move knowledge and recommendation pointers together after staged verification."""

    cursor = connection.cursor()
    family_id = str(plan["release_family_id"])
    release_id = str(plan["compiled"].release_id)
    timestamp = datetime.now(timezone.utc) if oracle else now()
    try:
        if oracle:
            cursor.execute(
                """
                SELECT family.status,knowledge.status
                FROM recommendation_release_family family
                JOIN knowledge_release knowledge
                  ON knowledge.release_id=family.knowledge_release_id
                WHERE family.release_family_id=:family_id
                  AND family.knowledge_release_id=:release_id
                FOR UPDATE
                """,
                family_id=family_id,
                release_id=release_id,
            )
            status_row = cursor.fetchone()
            if status_row is None or str(status_row[0]) not in {"READY", "ACTIVE"} \
                    or str(status_row[1]) != "READY":
                raise RuntimeError("VERIFIED_RELEASE_NOT_READY_FOR_ACTIVATION")
            cursor.execute(
                """
                UPDATE recommendation_release_family
                SET status='READY'
                WHERE release_family_id=(
                  SELECT active_release_family_id FROM recommendation_runtime_state
                  WHERE state_key='ACTIVE'
                ) AND release_family_id<>:family_id AND status='ACTIVE'
                """,
                family_id=family_id,
            )
            cursor.execute(
                """
                MERGE INTO knowledge_runtime_state target
                USING (SELECT 'ACTIVE' state_key FROM dual) source
                ON (target.state_key=source.state_key)
                WHEN MATCHED THEN UPDATE SET
                  target.active_release_id=:release_id,target.updated_at=:updated_at
                WHEN NOT MATCHED THEN INSERT
                  (state_key,active_release_id,updated_at)
                  VALUES ('ACTIVE',:release_id,:updated_at)
                """,
                release_id=release_id,
                updated_at=timestamp,
            )
            cursor.execute(
                """
                UPDATE recommendation_release_family
                SET status='ACTIVE',activated_at=:activated_at
                WHERE release_family_id=:family_id
                """,
                family_id=family_id,
                activated_at=timestamp,
            )
            cursor.execute(
                """
                MERGE INTO recommendation_runtime_state target
                USING (SELECT 'ACTIVE' state_key FROM dual) source
                ON (target.state_key=source.state_key)
                WHEN MATCHED THEN UPDATE SET
                  target.active_release_family_id=:family_id,target.updated_at=:updated_at
                WHEN NOT MATCHED THEN INSERT
                  (state_key,active_release_family_id,updated_at)
                  VALUES ('ACTIVE',:family_id,:updated_at)
                """,
                family_id=family_id,
                updated_at=timestamp,
            )
        else:
            connection.execute("BEGIN IMMEDIATE")
            status_row = cursor.execute(
                """
                SELECT family.status,knowledge.status
                FROM recommendation_release_family family
                JOIN knowledge_release knowledge
                  ON knowledge.release_id=family.knowledge_release_id
                WHERE family.release_family_id=? AND family.knowledge_release_id=?
                """,
                (family_id, release_id),
            ).fetchone()
            if status_row is None or str(status_row[0]) not in {"READY", "ACTIVE"} \
                    or str(status_row[1]) != "READY":
                raise RuntimeError("VERIFIED_RELEASE_NOT_READY_FOR_ACTIVATION")
            cursor.execute(
                """
                UPDATE recommendation_release_family SET status='READY'
                WHERE release_family_id=(
                  SELECT active_release_family_id FROM recommendation_runtime_state
                  WHERE state_key='ACTIVE'
                ) AND release_family_id<>? AND status='ACTIVE'
                """,
                (family_id,),
            )
            cursor.execute(
                """
                INSERT INTO knowledge_runtime_state(state_key,active_release_id,updated_at)
                VALUES ('ACTIVE',?,?)
                ON CONFLICT(state_key) DO UPDATE SET
                  active_release_id=excluded.active_release_id,
                  updated_at=excluded.updated_at
                """,
                (release_id, timestamp),
            )
            cursor.execute(
                """
                UPDATE recommendation_release_family
                SET status='ACTIVE',activated_at=? WHERE release_family_id=?
                """,
                (timestamp, family_id),
            )
            cursor.execute(
                """
                INSERT INTO recommendation_runtime_state(
                  state_key,active_release_family_id,updated_at
                ) VALUES ('ACTIVE',?,?)
                ON CONFLICT(state_key) DO UPDATE SET
                  active_release_family_id=excluded.active_release_family_id,
                  updated_at=excluded.updated_at
                """,
                (family_id, timestamp),
            )
        verification = verify_active(cursor, oracle)
        if (
            not verification["pass"]
            or verification.get("release_family_id") != family_id
            or verification.get("knowledge_release_id") != release_id
        ):
            raise RuntimeError("ACTIVATION_TRANSACTION_VERIFICATION_FAILED")
        connection.commit()
        return verification
    except BaseException:
        connection.rollback()
        raise


def _scalar(cursor: Any, sql: str, params: Any = None) -> int:
    cursor.execute(sql, params or {})
    return int(cursor.fetchone()[0])


def verify_release_family(
    cursor: Any,
    oracle: bool,
    *,
    family_id: str | None = None,
    require_active: bool,
) -> dict[str, Any]:
    if require_active:
        cursor.execute(
            """
            SELECT family.release_family_id,family.knowledge_release_id,
                   family.support_manifest_sha256,family.feature_manifest_sha256,
                   family.ranking_policy_version,
                   family.ranking_policy_sha256,family.preference_catalog_version,
                   family.spice_reference_version,family.status
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            JOIN knowledge_runtime_state knowledge_state
              ON knowledge_state.state_key='ACTIVE'
             AND knowledge_state.active_release_id=family.knowledge_release_id
            JOIN knowledge_release knowledge
              ON knowledge.release_id=family.knowledge_release_id
             AND knowledge.status='READY'
            WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
            """
        )
    else:
        if family_id is None:
            raise ValueError("STAGED_FAMILY_ID_REQUIRED")
        cursor.execute(
            """
            SELECT family.release_family_id,family.knowledge_release_id,
                   family.support_manifest_sha256,family.feature_manifest_sha256,
                   family.ranking_policy_version,
                   family.ranking_policy_sha256,family.preference_catalog_version,
                   family.spice_reference_version,family.status
            FROM recommendation_release_family family
            JOIN knowledge_release knowledge
              ON knowledge.release_id=family.knowledge_release_id
             AND knowledge.status='READY'
            WHERE family.release_family_id=:family_id
              AND family.status IN ('READY','ACTIVE')
            """
            if oracle
            else """
            SELECT family.release_family_id,family.knowledge_release_id,
                   family.support_manifest_sha256,family.feature_manifest_sha256,
                   family.ranking_policy_version,
                   family.ranking_policy_sha256,family.preference_catalog_version,
                   family.spice_reference_version,family.status
            FROM recommendation_release_family family
            JOIN knowledge_release knowledge
              ON knowledge.release_id=family.knowledge_release_id
             AND knowledge.status='READY'
            WHERE family.release_family_id=? AND family.status IN ('READY','ACTIVE')
            """,
            {"family_id": family_id} if oracle else (family_id,),
        )
    active = cursor.fetchone()
    if active is None:
        check_name = "active_release_family" if require_active else "staged_release_family_ready"
        return {"pass": False, "checks": {check_name: False}}
    (
        family_id,
        release_id,
        support_manifest,
        feature_manifest,
        policy_version,
        policy_sha,
        preference_catalog_version,
        spice_reference_version,
        family_status,
    ) = map(str, active)
    total_menu = _scalar(cursor, "SELECT COUNT(*) FROM menu")
    mapped = _scalar(
        cursor,
        "SELECT COUNT(*) FROM menu_concept_map WHERE release_id=:release_id AND mapping_status='MAPPED' AND confidence_band='high'"
        if oracle
        else "SELECT COUNT(*) FROM menu_concept_map WHERE release_id=? AND mapping_status='MAPPED' AND confidence_band='high'",
        {"release_id": release_id} if oracle else (release_id,),
    )
    classified = _scalar(
        cursor,
        "SELECT COUNT(*) FROM menu_concept_map WHERE release_id=:release_id"
        if oracle
        else "SELECT COUNT(*) FROM menu_concept_map WHERE release_id=?",
        {"release_id": release_id} if oracle else (release_id,),
    )
    unexplained = _scalar(
        cursor,
        """
        SELECT COUNT(*) FROM menu_concept_map
        WHERE release_id=:release_id AND mapping_status='UNMAPPED'
          AND TRIM(COALESCE(unmapped_reason,''))=''
        """
        if oracle
        else """
        SELECT COUNT(*) FROM menu_concept_map
        WHERE release_id=? AND mapping_status='UNMAPPED'
          AND TRIM(COALESCE(unmapped_reason,''))=''
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    invalid_mapping = _scalar(
        cursor,
        """
        SELECT COUNT(*) FROM menu_concept_map
        WHERE release_id=:release_id AND mapping_status='MAPPED'
          AND (confidence_band<>'high' OR source_type<>'YOBI_DERIVED_DEMO_MAPPING'
               OR review_status<>'REVIEWED_DEMO')
        """
        if oracle
        else """
        SELECT COUNT(*) FROM menu_concept_map
        WHERE release_id=? AND mapping_status='MAPPED'
          AND (confidence_band<>'high' OR source_type<>'YOBI_DERIVED_DEMO_MAPPING'
               OR review_status<>'REVIEWED_DEMO')
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    mapped_without_wiki = _scalar(
        cursor,
        """
        SELECT COUNT(*) FROM menu_concept_map mapping
        WHERE mapping.release_id=:release_id AND mapping.mapping_status='MAPPED'
          AND NOT EXISTS (
            SELECT 1 FROM knowledge_document document
            JOIN knowledge_chunk chunk
              ON chunk.release_id=document.release_id
             AND chunk.document_id=document.document_id
            WHERE document.release_id=mapping.release_id
              AND document.concept_id=mapping.concept_id
              AND document.source_type='SYNTHETIC_WIKI'
              AND document.review_status='REVIEWED_DEMO'
          )
        """
        if oracle
        else """
        SELECT COUNT(*) FROM menu_concept_map mapping
        WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
          AND NOT EXISTS (
            SELECT 1 FROM knowledge_document document
            JOIN knowledge_chunk chunk
              ON chunk.release_id=document.release_id
             AND chunk.document_id=document.document_id
            WHERE document.release_id=mapping.release_id
              AND document.concept_id=mapping.concept_id
              AND document.source_type='SYNTHETIC_WIKI'
              AND document.review_status='REVIEWED_DEMO'
          )
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    invalid_support = _scalar(
        cursor,
        """
        SELECT COUNT(*) FROM concept_preference_support
        WHERE knowledge_release_id=:release_id
          AND (support_status<>'SUPPORTED' OR evidence_chunk_id IS NULL
               OR provenance_type<>'SYNTHETIC_WIKI'
               OR review_status<>'REVIEWED_DEMO'
               OR support_method_version<>:method)
        """
        if oracle
        else """
        SELECT COUNT(*) FROM concept_preference_support
        WHERE knowledge_release_id=?
          AND (support_status<>'SUPPORTED' OR evidence_chunk_id IS NULL
               OR provenance_type<>'SYNTHETIC_WIKI'
               OR review_status<>'REVIEWED_DEMO'
               OR support_method_version<>?)
        """,
        {"release_id": release_id, "method": SUPPORT_METHOD_VERSION}
        if oracle
        else (release_id, SUPPORT_METHOD_VERSION),
    )
    support_count = _scalar(
        cursor,
        "SELECT COUNT(*) FROM concept_preference_support WHERE knowledge_release_id=:release_id"
        if oracle
        else "SELECT COUNT(*) FROM concept_preference_support WHERE knowledge_release_id=?",
        {"release_id": release_id} if oracle else (release_id,),
    )
    support_rows = _rows(
        cursor,
        """
        SELECT knowledge_release_id,concept_id,category_code,option_code,
               support_status,support_strength,evidence_chunk_id,provenance_type,
               source_ref,review_status,support_method_version,is_synthetic
        FROM concept_preference_support
        WHERE knowledge_release_id=:release_id
        ORDER BY concept_id,category_code,option_code
        """
        if oracle
        else """
        SELECT knowledge_release_id,concept_id,category_code,option_code,
               support_status,support_strength,evidence_chunk_id,provenance_type,
               source_ref,review_status,support_method_version,is_synthetic
        FROM concept_preference_support
        WHERE knowledge_release_id=?
        ORDER BY concept_id,category_code,option_code
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    computed_support_manifest = support_manifest_sha256(support_rows)
    feature_rows = _rows(
        cursor,
        """
        SELECT knowledge_release_id,feature_id,menu_id,category_code,option_code,
               support_status,support_strength,confidence,specificity,evidence_scope,
               provenance_type,source_ref,review_status,extractor_version,is_synthetic
        FROM menu_preference_feature
        WHERE knowledge_release_id=:release_id
        ORDER BY menu_id,category_code,option_code
        """
        if oracle
        else """
        SELECT knowledge_release_id,feature_id,menu_id,category_code,option_code,
               support_status,support_strength,confidence,specificity,evidence_scope,
               provenance_type,source_ref,review_status,extractor_version,is_synthetic
        FROM menu_preference_feature
        WHERE knowledge_release_id=?
        ORDER BY menu_id,category_code,option_code
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    feature_evidence_rows = _rows(
        cursor,
        """
        SELECT knowledge_release_id,evidence_id,feature_id,evidence_role,source_type,
               excerpt,excerpt_sha256,source_ref,provenance_type,is_synthetic
        FROM menu_preference_feature_evidence
        WHERE knowledge_release_id=:release_id
        ORDER BY feature_id,evidence_id
        """
        if oracle
        else """
        SELECT knowledge_release_id,evidence_id,feature_id,evidence_role,source_type,
               excerpt,excerpt_sha256,source_ref,provenance_type,is_synthetic
        FROM menu_preference_feature_evidence
        WHERE knowledge_release_id=?
        ORDER BY feature_id,evidence_id
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    membership_rows = _rows(
        cursor,
        """
        SELECT knowledge_release_id,menu_id,concept_id,membership_role,confidence,
               provenance_type,source_ref,review_status,extractor_version,is_synthetic
        FROM menu_concept_membership
        WHERE knowledge_release_id=:release_id
        ORDER BY menu_id,concept_id
        """
        if oracle
        else """
        SELECT knowledge_release_id,menu_id,concept_id,membership_role,confidence,
               provenance_type,source_ref,review_status,extractor_version,is_synthetic
        FROM menu_concept_membership
        WHERE knowledge_release_id=?
        ORDER BY menu_id,concept_id
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    computed_feature_manifest = feature_manifest_sha256(
        feature_rows,
        feature_evidence_rows,
        membership_rows,
    )
    invalid_feature = sum(
        1
        for row in feature_rows
        if str(row["extractor_version"]) != FEATURE_EXTRACTOR_VERSION
        or str(row["support_status"])
        not in {"SUPPORTED", "CONTRADICTED", "REVIEW_REQUIRED"}
    )
    direct_contradictions = sum(
        1
        for row in feature_rows
        if row["support_status"] == "CONTRADICTED"
        and row["evidence_scope"] == "MENU_DIRECT"
    )
    all_mapping_provenance = _scalar(
        cursor,
        """
        SELECT COUNT(*) FROM menu_concept_map
        WHERE release_id=:release_id
          AND source_type<>'YOBI_DERIVED_DEMO_MAPPING'
        """
        if oracle
        else """
        SELECT COUNT(*) FROM menu_concept_map
        WHERE release_id=?
          AND source_type<>'YOBI_DERIVED_DEMO_MAPPING'
        """,
        {"release_id": release_id} if oracle else (release_id,),
    )
    source_specific_facts = sum(
        _scalar(cursor, f"SELECT COUNT(*) FROM {table}")
        for table in (
            "menu_ingredient",
            "menu_allergen",
            "menu_dietary_attribute",
            "option_dietary_conflict",
            "merchant_certification",
            "merchant_ingredient",
            "merchant_origin_declaration",
            "option_ingredient_effect",
        )
    )
    expected_preference_count = sum(
        len(category.options) for category in PREFERENCE_CATEGORIES
    )
    preference_option_count = _scalar(
        cursor,
        """
        SELECT COUNT(*) FROM recommendation_preference_option
        WHERE catalog_version=:catalog_version AND active=1
        """
        if oracle
        else """
        SELECT COUNT(*) FROM recommendation_preference_option
        WHERE catalog_version=? AND active=1
        """,
        {"catalog_version": preference_catalog_version}
        if oracle
        else (preference_catalog_version,),
    )
    spice_reference_count = _scalar(
        cursor,
        "SELECT COUNT(*) FROM spice_reference WHERE reference_version=:reference_version"
        if oracle
        else "SELECT COUNT(*) FROM spice_reference WHERE reference_version=?",
        {"reference_version": spice_reference_version}
        if oracle
        else (spice_reference_version,),
    )
    checks = {
        ("active_release_family" if require_active else "staged_release_family_ready"): True,
        "classification_coverage_100_percent": classified == total_menu and total_menu > 0,
        "mapped_high_exists": mapped > 0,
        "unexplained_unmapped_zero": unexplained == 0,
        "invalid_active_mapping_zero": invalid_mapping == 0,
        "mapped_without_reviewed_public_wiki_zero": mapped_without_wiki == 0,
        "reviewed_support_exists": support_count > 0,
        "invalid_support_zero": invalid_support == 0,
        "all_mapping_provenance_explicit": all_mapping_provenance == 0,
        "support_manifest_sha256_exact": bool(
            re.fullmatch(r"[0-9a-f]{64}", support_manifest)
        )
        and support_manifest == computed_support_manifest,
        "menu_features_exist": bool(feature_rows),
        "menu_feature_evidence_exists": bool(feature_evidence_rows),
        "menu_concept_memberships_cover_primary_mappings": len(membership_rows) >= mapped,
        "invalid_menu_feature_zero": invalid_feature == 0,
        "feature_manifest_sha256_exact": bool(
            re.fullmatch(r"[0-9a-f]{64}", feature_manifest)
        )
        and feature_manifest == computed_feature_manifest,
        "ranking_policy_version_exact": policy_version == RANKING_POLICY_VERSION,
        "ranking_policy_sha256_exact": policy_sha == RANKING_POLICY_SHA256,
        "preference_catalog_version_exact": (
            preference_catalog_version == PREFERENCE_CATALOG_VERSION
        ),
        "preference_options_complete": (
            preference_option_count == expected_preference_count
        ),
        "spice_reference_version_exact": (
            spice_reference_version == f"{PREFERENCE_CATALOG_VERSION}-spice"
        ),
        "spice_references_complete": spice_reference_count == 10,
        "source_specific_fact_invention_zero": source_specific_facts == 0,
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "release_family_id": family_id,
        "knowledge_release_id": release_id,
        "catalog_menu_count": total_menu,
        "mapped_high_count": mapped,
        "classified_count": classified,
        "support_row_count": support_count,
        "support_manifest_sha256": support_manifest,
        "computed_support_manifest_sha256": computed_support_manifest,
        "menu_feature_count": len(feature_rows),
        "menu_feature_evidence_count": len(feature_evidence_rows),
        "menu_concept_membership_count": len(membership_rows),
        "direct_contradiction_count": direct_contradictions,
        "feature_manifest_sha256": feature_manifest,
        "computed_feature_manifest_sha256": computed_feature_manifest,
        "ranking_policy_version": policy_version,
        "ranking_policy_sha256": policy_sha,
        "preference_catalog_version": preference_catalog_version,
        "preference_option_count": preference_option_count,
        "spice_reference_version": spice_reference_version,
        "spice_reference_count": spice_reference_count,
        "family_status": family_status,
    }


def verify_active(cursor: Any, oracle: bool) -> dict[str, Any]:
    return verify_release_family(cursor, oracle, require_active=True)


def _connect(settings: Settings, backend: str, sqlite_path: Path | None) -> Any:
    if backend == "sqlite":
        if sqlite_path is None:
            raise RuntimeError("SQLITE_PATH_REQUIRED")
        connection = sqlite3.connect(sqlite_path)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RuntimeError("ADB_DSN_AND_DB_PASSWORD_REQUIRED")
    oracle_connection = oracledb.connect(
        user=settings.db_username,
        password=password,
        dsn=dsn,
    )
    cursor = oracle_connection.cursor()
    cursor.execute("SELECT SYS_CONTEXT('USERENV','CURRENT_USER') FROM dual")
    current_user = str(cursor.fetchone()[0])
    if current_user.upper() != settings.db_username.upper() or current_user.upper() == "ADMIN":
        oracle_connection.close()
        raise RuntimeError("ORACLE_RUNTIME_USER_MISMATCH")
    return oracle_connection


def _public_plan(summary: Mapping[str, Any], backend: str, committed: bool) -> dict[str, Any]:
    return {
        **summary,
        "backend": "oracle-26ai" if backend == "oracle" else "sqlite",
        "transaction_committed": committed,
        "source_boundaries": {
            "catalog": "YOGIYO_PUBLIC_WEB",
            "menu_concept_mapping": MAPPING_PROVENANCE,
            "general_wiki": "SYNTHETIC_WIKI/REVIEWED_DEMO",
            "merchant_ingredients": "NOT_PROVIDED",
            "halal_certifications": "NOT_PROVIDED",
            "menu_spice_levels": "NOT_PROVIDED",
        },
    }


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, oracledb.DatabaseError) and exc.args:
        code = getattr(exc.args[0], "code", None)
        return f"ORACLE_{code}" if isinstance(code, int) else "ORACLE_DATABASE_ERROR"
    value = str(exc)
    if value and len(value) <= 100 and all(
        character.isupper() or character.isdigit() or character == "_"
        for character in value
    ):
        return value
    return type(exc).__name__.upper()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build, verify, and atomically activate external-catalog general Wiki support."
    )
    parser.add_argument("--backend", choices=("oracle", "sqlite"), required=True)
    parser.add_argument("--sqlite-path", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Compile and classify without writes.")
    mode.add_argument(
        "--stage-only",
        action="store_true",
        help="Load and verify a READY family without changing active pointers.",
    )
    mode.add_argument(
        "--activate-staged",
        action="store_true",
        help="Reverify and atomically activate the deterministic staged family.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Backward-compatible stage followed by activation.",
    )
    mode.add_argument("--verify-only", action="store_true", help="Verify active release only.")
    args = parser.parse_args()

    connection: Any | None = None
    try:
        settings = Settings()
        connection = _connect(settings, args.backend, args.sqlite_path)
        if args.apply:
            result = apply_plan(connection, args.backend == "oracle")
        elif args.stage_only:
            result = stage_plan(connection, args.backend == "oracle")
        elif args.activate_staged:
            result = activate_staged_plan(connection, args.backend == "oracle")
        elif args.verify_only:
            result = {
                **verify_active(connection.cursor(), args.backend == "oracle"),
                "backend": "oracle-26ai" if args.backend == "oracle" else "sqlite",
                "transaction_committed": False,
            }
        else:
            plan = build_plan(connection.cursor())
            result = _public_plan(plan["summary"], args.backend, False)
        passed = result.get("pass", True) is not False
        result = {"status": "PASS" if passed else "FAIL", **result}
        exit_code = 0 if passed else 1
    except Exception as exc:  # noqa: BLE001 - emit one sanitized JSON failure only
        result = {"status": "FAIL", "error_code": _safe_error_code(exc)}
        exit_code = 1
    finally:
        if connection is not None:
            connection.close()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
