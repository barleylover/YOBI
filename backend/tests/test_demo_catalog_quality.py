from __future__ import annotations

import json
from collections import Counter, defaultdict

from app.db.seed_data import build_seed
from app.knowledge.catalog_seed import build_knowledge_catalog_seed

SUPPORTED_ONBOARDING_ALLERGENS = {
    "allergen_shellfish_risk",
    "allergen_fish",
    "allergen_milk",
    "allergen_egg",
    "allergen_peanut",
    "allergen_tree_nut",
    "allergen_wheat",
    "allergen_soy",
    "allergen_sesame",
}


def test_demo_catalog_has_realistic_scale_specialization_and_operational_variety() -> None:
    seed = build_seed()
    catalog = build_knowledge_catalog_seed(seed["menus"])

    assert len(seed["service_areas"]) == 3
    assert len(seed["hotels"]) == 20
    assert len(seed["merchants"]) == 60
    assert len(seed["menus"]) == 600

    menus_by_merchant: dict[str, list[dict[str, object]]] = defaultdict(list)
    for menu in seed["menus"]:
        menus_by_merchant[str(menu["merchant_id"])].append(menu)
    assert {len(rows) for rows in menus_by_merchant.values()} == {10}

    concept_types = {
        str(row["concept_id"]): str(row["concept_type"])
        for row in catalog.compiled_release.concepts
    }
    family_by_concept = {
        concept_id: concept_id
        for concept_id, concept_type in concept_types.items()
        if concept_type == "FAMILY"
    }
    for row in sorted(catalog.compiled_release.closure, key=lambda item: int(item["depth"])):
        descendant = str(row["descendant_concept_id"])
        ancestor = str(row["ancestor_concept_id"])
        if descendant not in family_by_concept and concept_types[ancestor] == "FAMILY":
            family_by_concept[descendant] = ancestor
    concept_by_menu = {
        str(row["menu_id"]): str(row["concept_id"])
        for row in catalog.menu_concept_maps
    }
    for rows in menus_by_merchant.values():
        family_counts = Counter(
            family_by_concept[concept_by_menu[str(menu["menu_id"])]] for menu in rows
        )
        assert family_counts.most_common(1)[0][1] >= 7

    assert Counter(menu["availability"] for menu in seed["menus"]) == {
        "AVAILABLE": 510,
        "SOLD_OUT": 60,
        "PAUSED": 30,
    }
    assert not any("house style" in str(menu["name_en"]).casefold() for menu in seed["menus"])
    assert not any(
        (tokens := str(menu["name_en"]).casefold().split())[:1] == tokens[1:2]
        for menu in seed["menus"]
    )
    assert not any(
        str(menu["name_ko"]).startswith(("매콤한 매운", "매콤한 매콤"))
        for menu in seed["menus"]
    )
    assert len({str(menu["name_en"]) for menu in seed["menus"]}) >= 350
    assert len({str(menu["description"]) for menu in seed["menus"]}) >= 70


def test_menu_level_facts_are_intentionally_incomplete_but_cover_demo_allergies() -> None:
    seed = build_seed()
    menu_count = len(seed["menus"])
    ingredient_counts = Counter(row["menu_id"] for row in seed["menu_ingredients"])
    allergen_menu_ids = {str(row["menu_id"]) for row in seed["menu_allergens"]}

    assert 0.25 <= len(ingredient_counts) / menu_count <= 0.35
    assert all(2 <= count <= 5 for count in ingredient_counts.values())
    assert 0.30 <= len(allergen_menu_ids) / menu_count <= 0.40
    assert SUPPORTED_ONBOARDING_ALLERGENS <= {
        str(row["allergen_id"]) for row in seed["allergens"]
    }

    merchants = {str(row["merchant_id"]): row for row in seed["merchants"]}
    menu_by_id = {str(row["menu_id"]): row for row in seed["menus"]}
    explicit_absences = {
        (
            str(merchants[str(menu_by_id[str(row["menu_id"])]["merchant_id"])]["service_area_id"]),
            str(row["allergen_id"]),
        )
        for row in seed["menu_allergens"]
        if row["status"] == "ABSENT" and row["cross_contamination_status"] == "UNKNOWN"
    }
    assert explicit_absences == {
        (service_area["service_area_id"], allergen_id)
        for service_area in seed["service_areas"]
        for allergen_id in SUPPORTED_ONBOARDING_ALLERGENS
    }
    evidence_by_id = {str(row["evidence_id"]): row for row in seed["evidence"]}
    for row in seed["menu_allergens"]:
        if row["status"] != "ABSENT":
            continue
        evidence = evidence_by_id[str(row["evidence_id"])]
        assert evidence["status"] == "VERIFIED"
        assert evidence["source_type"] in {
            "SYNTHETIC_MENU_SPEC",
            "SYNTHETIC_RESTAURANT_DECLARATION",
        }
        assert str(evidence["claim_type"]).endswith("_absence")
        assert row["cross_contamination_status"] == "UNKNOWN"
        assert "cross-contamination remains unknown" in str(
            evidence["suggested_action"]
        ).casefold()

    # Missing declarations remain missing rows; they are not encoded as confirmed absence.
    declared_allergen_pairs = {
        (str(row["menu_id"]), str(row["allergen_id"])) for row in seed["menu_allergens"]
    }
    assert any(
        (str(menu["menu_id"]), allergen_id) not in declared_allergen_pairs
        for menu in seed["menus"]
        for allergen_id in SUPPORTED_ONBOARDING_ALLERGENS
    )


def test_every_menu_maps_to_a_reusable_wiki_node_without_merchant_specific_concepts() -> None:
    seed = build_seed()
    catalog = build_knowledge_catalog_seed(seed["menus"])
    merchant_names = {
        str(value).casefold()
        for merchant in seed["merchants"]
        for value in (merchant["name_ko"], merchant["name_en"])
    }

    assert len(catalog.menu_concept_maps) == len(seed["menus"])
    assert {row["mapping_status"] for row in catalog.menu_concept_maps} == {"MAPPED"}
    assert {row["mapping_type"] for row in catalog.menu_concept_maps} <= {"FAMILY", "VARIANT"}
    assert all(
        str(concept["canonical_name_en"]).casefold() not in merchant_names
        and str(concept["canonical_name_ko"]).casefold() not in merchant_names
        for concept in catalog.compiled_release.concepts
    )

    mapping_by_menu = {str(row["menu_id"]): row for row in catalog.menu_concept_maps}
    categories = {str(menu["category"]) for menu in seed["menus"]}
    assert categories == {
        str(concept["canonical_name_en"])
        for concept in catalog.compiled_release.concepts
        if concept["concept_type"] != "CUISINE"
    }
    assert all(
        json.loads(str(menu["allergen_tags_json"])) == []
        or mapping_by_menu[str(menu["menu_id"])]["concept_id"]
        for menu in seed["menus"]
    )


def test_wiki_compiles_structured_preparation_dietary_and_nine_allergen_claims() -> None:
    catalog = build_knowledge_catalog_seed(build_seed()["menus"])
    claims = catalog.compiled_release.claims
    claim_types = Counter(str(row["claim_type"]) for row in claims)

    assert 70 <= len(catalog.compiled_release.concepts) <= 120
    assert claim_types["PREPARATION"] >= 20
    assert claim_types["DIETARY"] >= 20
    assert SUPPORTED_ONBOARDING_ALLERGENS <= {
        str(row["allergen_id"])
        for row in claims
        if row["claim_type"] == "ALLERGEN"
    }
