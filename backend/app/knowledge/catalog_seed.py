from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.knowledge.authoring import (
    CompiledKnowledgeRelease,
    compile_directory,
    parse_document,
)

KNOWLEDGE_CATALOG_VERSION = "demo-knowledge-catalog-2026.08.11-v3"
KNOWLEDGE_UPDATED_AT = "2026-08-11"
KNOWLEDGE_COMPILER_CONTRACT = "yobi-knowledge-compiler-v2"

def _authored_category_concept_map() -> dict[str, str]:
    """Map every reusable FAMILY/VARIANT Wiki node to a menu-category label.

    The authored corpus is the authority. This prevents a hand-maintained category map from
    drifting as the demo Wiki grows, while CUISINE nodes remain hierarchy-only concepts.
    """

    root = Path(__file__).resolve().parents[3] / "knowledge" / "dishes"
    rows: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        front = parse_document(path).front_matter
        if front.concept_type == "CUISINE":
            continue
        if front.name_en in rows:
            raise ValueError(f"DUPLICATE_CATEGORY_NAME:{front.name_en}")
        rows[front.name_en] = front.concept_id
    return rows


CATEGORY_CONCEPT_MAP: dict[str, str] = _authored_category_concept_map()

# These three seeded menu names explicitly identify a reviewed child variant. All other generated
# "house style" names remain mapped at category level rather than receiving an invented subtype.
CANONICAL_MENU_CONCEPT_OVERRIDES: dict[str, str] = {
    "menu_004_01": "dish_vegetable_bibimbap",
    "menu_022_01": "dish_seasoned_fried_chicken",
    "menu_027_01": "dish_pork_gukbap",
}
CANONICAL_MENU_OVERRIDE_NAMES: dict[str, str] = {
    "menu_004_01": "Plant-forward bibimbap",
    "menu_022_01": "Cheese-seasoned fried chicken",
    "menu_027_01": "Warm pork gukbap",
}

# Ingredient groups are deliberately explicit. A newly authored ingredient must be reviewed and
# classified before a release can be built instead of silently falling into an "other" bucket.
INGREDIENT_GROUPS: dict[str, str] = {
    "ingredient_assorted_side_dishes": "prepared_component",
    "ingredient_beef": "animal_protein",
    "ingredient_beef_bone_broth": "broth_stock",
    "ingredient_bean_sprouts": "vegetable_aromatic",
    "ingredient_black_bean_paste": "sauce_seasoning",
    "ingredient_broth": "broth_stock",
    "ingredient_brown_sugar": "sweetener",
    "ingredient_buckwheat_noodles": "grain_starch",
    "ingredient_cheese": "dairy",
    "ingredient_chicken": "animal_protein",
    "ingredient_chicken_broth": "broth_stock",
    "ingredient_chili_seasoning": "sauce_seasoning",
    "ingredient_chocolate": "sweetener",
    "ingredient_chilled_broth": "broth_stock",
    "ingredient_dairy_cream": "dairy",
    "ingredient_egg": "animal_protein",
    "ingredient_fish_cake": "processed_seafood",
    "ingredient_fish_paste": "seafood",
    "ingredient_frying_oil": "oil_fat",
    "ingredient_garlic": "vegetable_aromatic",
    "ingredient_ginseng": "vegetable_aromatic",
    "ingredient_glutinous_rice": "grain_starch",
    "ingredient_gochujang": "sauce_seasoning",
    "ingredient_kimchi": "fermented_vegetable",
    "ingredient_mackerel": "seafood",
    "ingredient_mango": "fruit",
    "ingredient_mixed_filling": "prepared_component",
    "ingredient_mixed_seeds": "seed_nut",
    "ingredient_mixed_vegetables": "vegetable_aromatic",
    "ingredient_onion": "vegetable_aromatic",
    "ingredient_pickled_radish": "fermented_vegetable",
    "ingredient_pork": "animal_protein",
    "ingredient_rice": "grain_starch",
    "ingredient_rice_cake": "grain_starch",
    "ingredient_red_bean": "legume",
    "ingredient_sauce": "sauce_seasoning",
    "ingredient_seaweed": "sea_vegetable",
    "ingredient_sesame_oil": "oil_fat",
    "ingredient_shellfish": "seafood",
    "ingredient_shaved_ice": "prepared_component",
    "ingredient_soft_tofu": "soy_product",
    "ingredient_soy_sauce": "sauce_seasoning",
    "ingredient_starch": "grain_starch",
    "ingredient_sugar": "sweetener",
    "ingredient_sweet_potato": "vegetable_aromatic",
    "ingredient_sweet_potato_noodles": "grain_starch",
    "ingredient_tofu": "soy_product",
    "ingredient_tomato_sauce": "sauce_seasoning",
    "ingredient_tree_nuts": "seed_nut",
    "ingredient_tuna": "seafood",
    "ingredient_wheat_dough": "grain_starch",
    "ingredient_wheat_flour": "grain_starch",
    "ingredient_wheat_noodles": "grain_starch",
    "ingredient_wheat_wrapper": "grain_starch",
}

# Some concepts describe the same taxonomy item using a more specific phrase. These canonical
# labels keep the shared ingredient row stable while each claim retains its authored value_text.
INGREDIENT_NAME_OVERRIDES: dict[str, tuple[str, str]] = {
    "ingredient_chicken": ("닭고기", "Chicken"),
    "ingredient_mixed_vegetables": ("채소", "Mixed vegetables"),
    "ingredient_pork": ("돼지고기", "Pork"),
    "ingredient_rice": ("쌀", "Rice"),
    "ingredient_wheat_dough": ("밀 반죽", "Wheat dough"),
    "ingredient_wheat_flour": ("밀가루", "Wheat flour"),
    "ingredient_wheat_noodles": ("밀면", "Wheat noodles"),
}

ALLERGEN_NAMES: dict[str, tuple[str, str, str]] = {
    "allergen_egg": ("egg", "Egg", "달걀"),
    "allergen_fish": ("fish", "Fish", "생선"),
    "allergen_milk": ("milk", "Milk", "우유"),
    "allergen_peanut": ("peanut", "Peanut", "땅콩"),
    "allergen_sesame": ("sesame", "Sesame", "참깨"),
    "allergen_shellfish_risk": ("shellfish_risk", "Shellfish risk", "갑각류 위험 가능성"),
    "allergen_soy": ("soy", "Soy", "대두"),
    "allergen_tree_nut": ("tree_nut", "Tree nuts", "견과류"),
    "allergen_wheat": ("wheat", "Wheat", "밀"),
}

# Wiki dietary claims are intentionally broad, reusable demo classifications. They describe
# common dish-level possibilities, never certification for a specific merchant menu.
DIETARY_ATTRIBUTE_NAMES: dict[str, tuple[str, str]] = {
    "diet_alcohol_possible": ("Alcohol possible", "주류 성분 가능성"),
    "diet_contains_animal_product": ("Animal product commonly used", "동물성 재료 일반 사용"),
    "diet_halal_not_verified": ("Halal status not verified", "할랄 여부 미확인"),
    "diet_pork_possible": ("Pork possible", "돼지고기 가능성"),
    "diet_vegan_possible": ("Vegan variation possible", "비건 변형 가능"),
    "diet_vegetarian_possible": ("Vegetarian variation possible", "채식 변형 가능"),
}


class KnowledgeCatalogSeed(BaseModel):
    """Portable, deterministic payload; DB-specific loaders own transactions and VECTOR binding."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    compiled_release: CompiledKnowledgeRelease
    ingredients: list[dict[str, Any]]
    allergens: list[dict[str, Any]]
    dietary_attributes: list[dict[str, Any]]
    menu_concept_maps: list[dict[str, Any]]

    def table_payloads(self) -> dict[str, list[dict[str, Any]]]:
        """Return rows in dependency order, excluding the DB-specific release state row.

        `knowledge_release` must first be inserted as LOADING by the repository loader. Oracle must
        also convert each chunk's JSON vector to VECTOR(1536); SQLite stores the JSON unchanged.
        """

        compiled = self.compiled_release
        return {
            "ingredient": self.ingredients,
            "allergen": self.allergens,
            "dietary_attribute": self.dietary_attributes,
            "dish_concept": compiled.concepts,
            "dish_relation": compiled.relations,
            "dish_concept_closure": compiled.closure,
            "concept_claim": compiled.claims,
            "knowledge_document": compiled.documents,
            "knowledge_chunk": compiled.chunks,
            "menu_concept_map": self.menu_concept_maps,
        }

    def deterministic_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def default_knowledge_root() -> Path:
    return Path(__file__).resolve().parents[3] / "knowledge" / "dishes"


def knowledge_corpus_sha256(
    root: Path,
    *,
    catalog_version: str = KNOWLEDGE_CATALOG_VERSION,
) -> str:
    """Hash the complete authored source contract, independent of filesystem location/order."""

    paths = sorted(root.rglob("*.md"))
    if not paths:
        raise ValueError(f"NO_KNOWLEDGE_DOCUMENTS:{root}")
    sources = []
    for path in paths:
        normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        sources.append(
            {
                "path": path.relative_to(root).as_posix(),
                "content_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            }
        )
    payload = {
        "catalog_version": catalog_version,
        "compiler_contract": KNOWLEDGE_COMPILER_CONTRACT,
        "sources": sources,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def knowledge_release_id_for_root(
    root: Path,
    *,
    catalog_version: str = KNOWLEDGE_CATALOG_VERSION,
) -> str:
    """Return an immutable release ID derived from corpus sources and compiler contract."""

    return f"knowledge-demo-{knowledge_corpus_sha256(root, catalog_version=catalog_version)[:24]}"


# Compatibility export for callers that need the current default authored release identifier.
# Custom roots must use ``knowledge_release_id_for_root`` or leave ``release_id`` unset below.
KNOWLEDGE_RELEASE_ID = knowledge_release_id_for_root(default_knowledge_root())


def _taxonomy_rows(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ingredient_names: dict[str, set[tuple[str, str]]] = defaultdict(set)
    allergen_ids: set[str] = set()
    dietary_attribute_ids: set[str] = set()
    for path in sorted(root.rglob("*.md")):
        front = parse_document(path).front_matter
        for ingredient in front.ingredients:
            ingredient_names[ingredient.ingredient_id].add(
                (ingredient.name_ko.strip(), ingredient.name_en.strip())
            )
        allergen_ids.update(allergen.allergen_id for allergen in front.allergens)
        dietary_attribute_ids.update(dietary.attribute_id for dietary in front.dietary)

    unclassified = sorted(set(ingredient_names) - INGREDIENT_GROUPS.keys())
    if unclassified:
        raise ValueError(f"UNCLASSIFIED_INGREDIENTS:{','.join(unclassified)}")
    unknown_allergens = sorted(allergen_ids - ALLERGEN_NAMES.keys())
    if unknown_allergens:
        raise ValueError(f"UNCLASSIFIED_ALLERGENS:{','.join(unknown_allergens)}")
    unknown_dietary = sorted(dietary_attribute_ids - DIETARY_ATTRIBUTE_NAMES.keys())
    if unknown_dietary:
        raise ValueError(f"UNCLASSIFIED_DIETARY_ATTRIBUTES:{','.join(unknown_dietary)}")

    ingredients: list[dict[str, Any]] = []
    for ingredient_id, names in sorted(ingredient_names.items()):
        name_ko, name_en = INGREDIENT_NAME_OVERRIDES.get(
            ingredient_id,
            min(names, key=lambda item: (len(item[1]), item[1].casefold(), item[0])),
        )
        ingredients.append(
            {
                "ingredient_id": ingredient_id,
                "name_ko": name_ko,
                "name_en": name_en,
                "ingredient_group": INGREDIENT_GROUPS[ingredient_id],
            }
        )

    allergens = [
        {
            "allergen_id": allergen_id,
            "code": ALLERGEN_NAMES[allergen_id][0],
            "name_en": ALLERGEN_NAMES[allergen_id][1],
            "name_ko": ALLERGEN_NAMES[allergen_id][2],
        }
        for allergen_id in sorted(allergen_ids)
    ]
    dietary_attributes = [
        {
            "attribute_id": attribute_id,
            "code": attribute_id.removeprefix("diet_"),
            "display_name": DIETARY_ATTRIBUTE_NAMES[attribute_id][0],
        }
        for attribute_id in sorted(dietary_attribute_ids)
    ]
    return ingredients, allergens, dietary_attributes


def _menu_concept_rows(
    menus: Sequence[Mapping[str, Any]],
    compiled: CompiledKnowledgeRelease,
    *,
    allow_unmapped: bool,
) -> list[dict[str, Any]]:
    concept_types = {row["concept_id"]: row["concept_type"] for row in compiled.concepts}
    required_concepts = set(CATEGORY_CONCEPT_MAP.values()) | set(
        CANONICAL_MENU_CONCEPT_OVERRIDES.values()
    )
    missing_concepts = sorted(required_concepts - concept_types.keys())
    if missing_concepts:
        raise ValueError(f"CATEGORY_MAP_DANGLING_CONCEPTS:{','.join(missing_concepts)}")
    closure_pairs = {
        (row["descendant_concept_id"], row["ancestor_concept_id"])
        for row in compiled.closure
    }

    normalized: list[tuple[str, str, str]] = []
    seen_menu_ids: set[str] = set()
    for menu in menus:
        menu_id = str(menu.get("menu_id") or "").strip()
        category = str(menu.get("category") or "").strip()
        name_en = str(menu.get("name_en") or "").strip()
        if not menu_id or not category:
            raise ValueError("MENU_ID_AND_CATEGORY_REQUIRED")
        if menu_id in seen_menu_ids:
            raise ValueError(f"DUPLICATE_MENU_ID:{menu_id}")
        seen_menu_ids.add(menu_id)
        normalized.append((menu_id, category, name_en))

    unmapped_categories = sorted(
        {
            category
            for menu_id, category, _ in normalized
            if menu_id not in CANONICAL_MENU_CONCEPT_OVERRIDES
            and category not in CATEGORY_CONCEPT_MAP
        }
    )
    if unmapped_categories and not allow_unmapped:
        raise ValueError(f"UNMAPPED_MENU_CATEGORIES:{','.join(unmapped_categories)}")

    for menu_id, category, name_en in normalized:
        override_concept_id = CANONICAL_MENU_CONCEPT_OVERRIDES.get(menu_id)
        if override_concept_id is None:
            continue
        expected_name = CANONICAL_MENU_OVERRIDE_NAMES[menu_id]
        if name_en != expected_name:
            raise ValueError(
                f"CANONICAL_OVERRIDE_NAME_MISMATCH:{menu_id}:{expected_name}:{name_en}"
            )
        category_concept_id = CATEGORY_CONCEPT_MAP.get(category)
        if category_concept_id is None:
            raise ValueError(f"CANONICAL_OVERRIDE_CATEGORY_UNMAPPED:{menu_id}:{category}")
        if (override_concept_id, category_concept_id) not in closure_pairs:
            raise ValueError(
                "CANONICAL_OVERRIDE_NOT_CATEGORY_DESCENDANT:"
                f"{menu_id}:{override_concept_id}:{category_concept_id}"
            )

    rows: list[dict[str, Any]] = []
    for menu_id, category, _ in sorted(normalized):
        override_concept_id = CANONICAL_MENU_CONCEPT_OVERRIDES.get(menu_id)
        concept_id = override_concept_id or CATEGORY_CONCEPT_MAP.get(category)
        if concept_id is None:
            rows.append(
                {
                    "release_id": compiled.release_id,
                    "menu_id": menu_id,
                    "concept_id": None,
                    "mapping_status": "UNMAPPED",
                    "mapping_type": "UNMAPPED",
                    "unmapped_reason": f"No reviewed demo concept for category: {category}",
                    "confidence_band": "low",
                    "source_type": "SYNTHETIC_CATEGORY_MAPPING",
                    "source_ref": f"demo-category:{category}",
                    "review_status": "DRAFT",
                    "is_synthetic": 1,
                    "updated_at": KNOWLEDGE_UPDATED_AT,
                }
            )
            continue
        rows.append(
            {
                "release_id": compiled.release_id,
                "menu_id": menu_id,
                "concept_id": concept_id,
                "mapping_status": "MAPPED",
                "mapping_type": ("VARIANT" if concept_types[concept_id] == "VARIANT" else "FAMILY"),
                "unmapped_reason": None,
                "confidence_band": "high",
                "source_type": (
                    "SYNTHETIC_CANONICAL_MENU_MAPPING"
                    if override_concept_id
                    else "SYNTHETIC_CATEGORY_MAPPING"
                ),
                "source_ref": (
                    f"demo-menu:{menu_id}"
                    if override_concept_id
                    else f"demo-category:{category}"
                ),
                "review_status": "REVIEWED_DEMO",
                "is_synthetic": 1,
                "updated_at": KNOWLEDGE_UPDATED_AT,
            }
        )
    return rows


def build_knowledge_catalog_seed(
    menus: Sequence[Mapping[str, Any]],
    *,
    knowledge_root: Path | None = None,
    release_id: str | None = None,
    catalog_version: str = KNOWLEDGE_CATALOG_VERSION,
    allow_unmapped: bool = False,
) -> KnowledgeCatalogSeed:
    """Compile authored Wiki documents and map menu categories without importing seed_data."""

    root = knowledge_root or default_knowledge_root()
    resolved_release_id = release_id or knowledge_release_id_for_root(
        root,
        catalog_version=catalog_version,
    )
    compiled = compile_directory(
        root,
        release_id=resolved_release_id,
        catalog_version=catalog_version,
    )
    ingredients, allergens, dietary_attributes = _taxonomy_rows(root)
    ingredient_ids = {row["ingredient_id"] for row in ingredients}
    allergen_ids = {row["allergen_id"] for row in allergens}
    claim_ingredient_ids = {
        row["ingredient_id"] for row in compiled.claims if row["claim_type"] == "INGREDIENT"
    }
    claim_allergen_ids = {
        row["allergen_id"] for row in compiled.claims if row["claim_type"] == "ALLERGEN"
    }
    if ingredient_ids != claim_ingredient_ids:
        raise ValueError("INGREDIENT_TAXONOMY_CLAIM_MISMATCH")
    if allergen_ids != claim_allergen_ids:
        raise ValueError("ALLERGEN_TAXONOMY_CLAIM_MISMATCH")
    return KnowledgeCatalogSeed(
        compiled_release=compiled,
        ingredients=ingredients,
        allergens=allergens,
        dietary_attributes=dietary_attributes,
        menu_concept_maps=_menu_concept_rows(
            menus,
            compiled,
            allow_unmapped=allow_unmapped,
        ),
    )
