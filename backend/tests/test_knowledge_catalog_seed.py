from __future__ import annotations

import re
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from app.db.seed_data import CATEGORIES, build_seed
from app.knowledge.catalog_seed import (
    CANONICAL_MENU_CONCEPT_OVERRIDES,
    CATEGORY_CONCEPT_MAP,
    KNOWLEDGE_CATALOG_VERSION,
    build_knowledge_catalog_seed,
    default_knowledge_root,
    knowledge_corpus_sha256,
    knowledge_release_id_for_root,
)


def test_demo_catalog_maps_all_600_menus_to_reusable_family_or_variant_nodes() -> None:
    menus = build_seed()["menus"]
    catalog = build_knowledge_catalog_seed(menus)

    assert len(CATEGORIES) == len(CATEGORY_CONCEPT_MAP) == 100
    assert sum(row["concept_type"] == "VARIANT" for row in catalog.compiled_release.concepts) == 70
    assert len(catalog.menu_concept_maps) == len(menus) == 600
    assert {row["mapping_status"] for row in catalog.menu_concept_maps} == {"MAPPED"}
    assert {row["concept_id"] for row in catalog.menu_concept_maps} == (
        set(CATEGORY_CONCEPT_MAP.values()) | set(CANONICAL_MENU_CONCEPT_OVERRIDES.values())
    )
    mapping_by_menu = {row["menu_id"]: row for row in catalog.menu_concept_maps}
    assert mapping_by_menu["menu_001_01"]["concept_id"] == "dish_rose_tteokbokki"
    assert mapping_by_menu["menu_001_01"]["mapping_type"] == "VARIANT"
    assert mapping_by_menu["menu_002_01"]["concept_id"] == "dish_tteokbokki"
    assert mapping_by_menu["menu_002_01"]["mapping_type"] == "FAMILY"
    assert mapping_by_menu["menu_004_01"]["concept_id"] == "dish_vegetable_bibimbap"
    assert mapping_by_menu["menu_022_01"]["concept_id"] == "dish_seasoned_fried_chicken"
    assert mapping_by_menu["menu_027_01"]["concept_id"] == "dish_pork_gukbap"
    for menu_id, concept_id in CANONICAL_MENU_CONCEPT_OVERRIDES.items():
        row = mapping_by_menu[menu_id]
        assert row["concept_id"] == concept_id
        assert row["mapping_type"] == "VARIANT"
        assert row["source_type"] == "SYNTHETIC_CANONICAL_MENU_MAPPING"
        assert row["source_ref"] == f"demo-menu:{menu_id}"
    assert all(row["is_synthetic"] == 1 for row in catalog.menu_concept_maps)


def test_taxonomy_is_claim_backed_and_replaces_category_pseudo_ingredients() -> None:
    catalog = build_knowledge_catalog_seed(build_seed()["menus"])
    ingredient_ids = {row["ingredient_id"] for row in catalog.ingredients}
    allergen_ids = {row["allergen_id"] for row in catalog.allergens}
    claims = catalog.compiled_release.claims

    assert len(ingredient_ids) == len(catalog.ingredients) == 48
    assert allergen_ids == set()
    assert catalog.dietary_attributes == []
    assert ingredient_ids == {
        row["ingredient_id"] for row in claims if row["claim_type"] == "INGREDIENT"
    }
    assert not {row["allergen_id"] for row in claims if row["claim_type"] == "ALLERGEN"}
    assert (
        not {
            "ingredient_tteokbokki",
            "ingredient_bibimbap",
            "ingredient_korean_fried_chicken",
            "ingredient_pizza",
        }
        & ingredient_ids
    )
    assert all(row["ingredient_group"] != "other" for row in catalog.ingredients)
    core_concepts = {
        row["concept_id"]
        for row in claims
        if row["claim_type"] == "INGREDIENT"
        and row["ingredient_role"] in {"DEFINING", "CORE"}
        and row["assertion_status"] == "PRESUMED_PRESENT"
    }
    assert set(CATEGORY_CONCEPT_MAP.values()) <= core_concepts
    assert set(CANONICAL_MENU_CONCEPT_OVERRIDES.values()) <= core_concepts


def test_catalog_seed_is_deterministic_and_exposes_loader_dependency_order() -> None:
    menus = build_seed()["menus"]
    first = build_knowledge_catalog_seed(menus)
    second = build_knowledge_catalog_seed(list(reversed(menus)))

    assert first.compiled_release.manifest_sha256 == second.compiled_release.manifest_sha256
    assert first.deterministic_json() == second.deterministic_json()
    assert re.fullmatch(r"knowledge-demo-[0-9a-f]{24}", first.compiled_release.release_id)
    assert list(first.table_payloads()) == [
        "ingredient",
        "allergen",
        "dietary_attribute",
        "dish_concept",
        "dish_relation",
        "dish_concept_closure",
        "concept_claim",
        "knowledge_document",
        "knowledge_chunk",
        "menu_concept_map",
    ]


def test_release_id_changes_with_source_or_compiler_catalog_contract(tmp_path: Path) -> None:
    root = tmp_path / "dishes"
    shutil.copytree(default_knowledge_root(), root)
    original_hash = knowledge_corpus_sha256(root)
    original_release_id = knowledge_release_id_for_root(root)

    target = next(root.rglob("*.md"))
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert knowledge_corpus_sha256(root) != original_hash
    assert knowledge_release_id_for_root(root) != original_release_id
    assert knowledge_release_id_for_root(
        root,
        catalog_version=KNOWLEDGE_CATALOG_VERSION + "-next",
    ) != knowledge_release_id_for_root(root)


def test_compiled_and_supplemental_rows_share_source_derived_release_id() -> None:
    seed = build_seed()
    catalog = build_knowledge_catalog_seed(seed["menus"])
    release_id = catalog.compiled_release.release_id

    assert all(
        row["release_id"] == release_id
        for rows in catalog.compiled_release.model_dump().values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict) and "release_id" in row
    )
    assert {
        row["release_id"]
        for key in (
            "menu_concept_maps",
            "merchant_origin_declarations",
            "merchant_ingredients",
            "option_ingredient_effects",
        )
        for row in seed[key]
    } == {release_id}


def test_unreviewed_category_fails_closed_or_is_explicitly_unmapped() -> None:
    menu = deepcopy(build_seed()["menus"][0])
    menu["category"] = "Unreviewed fusion dish"

    with pytest.raises(ValueError, match="UNMAPPED_MENU_CATEGORIES"):
        build_knowledge_catalog_seed([menu])

    catalog = build_knowledge_catalog_seed([menu], allow_unmapped=True)
    assert catalog.menu_concept_maps == [
        {
            "release_id": catalog.compiled_release.release_id,
            "menu_id": menu["menu_id"],
            "concept_id": None,
            "mapping_status": "UNMAPPED",
            "mapping_type": "UNMAPPED",
            "unmapped_reason": "No reviewed demo concept for category: Unreviewed fusion dish",
            "confidence_band": "low",
            "source_type": "SYNTHETIC_CATEGORY_MAPPING",
            "source_ref": "demo-category:Unreviewed fusion dish",
            "review_status": "DRAFT",
            "is_synthetic": 1,
            "updated_at": "2026-08-12",
        }
    ]


def test_duplicate_menu_ids_are_rejected_before_seed_generation() -> None:
    menu = build_seed()["menus"][0]
    with pytest.raises(ValueError, match="DUPLICATE_MENU_ID"):
        build_knowledge_catalog_seed([menu, menu])


def test_canonical_override_requires_the_reviewed_seeded_menu_name() -> None:
    menu = deepcopy(next(row for row in build_seed()["menus"] if row["menu_id"] == "menu_004_01"))
    menu["name_en"] = "Generic bibimbap"

    with pytest.raises(ValueError, match="CANONICAL_OVERRIDE_NAME_MISMATCH"):
        build_knowledge_catalog_seed([menu])
