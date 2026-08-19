from __future__ import annotations

from app.knowledge.menu_features import (
    build_menu_concept_memberships,
    compile_menu_preference_features,
    feature_manifest_sha256,
    normalize_preference_text,
    preference_term_matches,
    reviewed_general_support_matches,
)


def _menu(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "menu_id": "menu-a",
        "name_ko": "매운 닭고기 국수",
        "name_en": "Spicy chicken noodles",
        "description": "No pork. A spicy chicken noodle dish.",
        "cultural_description": "",
        "category": "Noodles",
        "data_origin": "YOGIYO_PUBLIC_WEB",
        "is_synthetic": 0,
    }
    row.update(updates)
    return row


def test_normalization_is_nfkc_casefolded_and_latin_aliases_use_word_boundaries() -> None:
    assert normalize_preference_text("ＳＰＩＣＹ—Chicken") == "spicy chicken"
    assert preference_term_matches("High-heat wok cooking", "heat") is True
    assert preference_term_matches("Cake made with wheat flour", "heat") is False
    assert preference_term_matches("Pork-cutlet with wheat crumbs", "heat") is False
    assert preference_term_matches("cupcake", "cake") is False
    assert preference_term_matches("pork-cutlet", "pork") is True
    assert preference_term_matches("매운떡볶이", "매운") is True


def test_general_wiki_support_rejects_possible_negated_and_variable_claims() -> None:
    assert reviewed_general_support_matches("The broth is commonly served hot.", "served hot")
    assert not reviewed_general_support_matches("The broth may be served hot.", "served hot")
    assert not reviewed_general_support_matches("The dish is not spicy.", "spicy")
    assert not reviewed_general_support_matches("Heat varies by menu.", "heat")
    assert reviewed_general_support_matches(
        "It is commonly served hot, although some versions are served cool.",
        "served hot",
    )
    assert not reviewed_general_support_matches(
        "It is commonly served hot, although some versions are served cool.",
        "served cool",
    )


def test_compiler_blocks_savory_cake_and_espresso_false_positives() -> None:
    features, _evidence = compile_menu_preference_features(
        knowledge_release_id="knowledge-v1",
        menus=[
            _menu(
                menu_id="fish-cake",
                name_en="Fish cake soup",
                name_ko="오뎅탕",
                description="espresso sauce",
                cultural_description="",
                category="",
            )
        ],
        mappings=[],
        concept_supports=[],
        chunks=[],
    )

    supported = {
        (row["category_code"], row["option_code"])
        for row in features
        if row["support_status"] == "SUPPORTED"
    }
    assert ("food_forms", "DESSERT_BAKERY") not in supported
    assert ("food_forms", "SOUP") in supported  # explicit soup, not espresso


def test_direct_contradiction_overrides_menu_and_general_concept_support() -> None:
    menus = [
        _menu(
            name_ko="안 매운 국수",
            name_en="Not spicy noodles",
            description="No pork. A mild noodle dish.",
        )
    ]
    mappings = [
        {
            "menu_id": "menu-a",
            "concept_id": "concept-noodle",
            "mapping_status": "MAPPED",
        }
    ]
    concept_supports = [
        {
            "concept_id": "concept-noodle",
            "category_code": "flavors",
            "option_code": "SPICY",
            "support_status": "SUPPORTED",
            "support_strength": 0.8,
            "evidence_chunk_id": "chunk-spicy",
            "provenance_type": "SYNTHETIC_WIKI",
            "source_ref": "wiki:concept-noodle",
            "review_status": "REVIEWED_DEMO",
            "is_synthetic": 1,
        }
    ]
    chunks = [
        {
            "chunk_id": "chunk-spicy",
            "content": "Some noodle dishes may be spicy.",
        }
    ]

    features, evidence = compile_menu_preference_features(
        knowledge_release_id="knowledge-v2",
        menus=menus,
        mappings=mappings,
        concept_supports=concept_supports,
        chunks=chunks,
        options_by_menu={
            "menu-a": [
                {
                    "name_en": "Add crispy topping",
                    "source_ref": "option:crispy",
                }
            ]
        },
    )

    by_key = {
        (row["category_code"], row["option_code"]): row for row in features
    }
    spicy = by_key[("flavors", "SPICY")]
    assert spicy["support_status"] == "CONTRADICTED"
    assert spicy["evidence_scope"] == "MENU_DIRECT"
    assert spicy["provenance_type"] == "YOGIYO_PUBLIC_WEB"
    pork = by_key[("main_ingredients", "PORK")]
    assert pork["support_status"] == "CONTRADICTED"
    crispy = by_key[("textures", "CRISPY")]
    assert crispy["support_status"] == "REVIEW_REQUIRED"
    assert crispy["evidence_scope"] == "OPTION_AVAILABILITY"
    spicy_evidence = [
        row for row in evidence if row["feature_id"] == spicy["feature_id"]
    ]
    assert {row["evidence_role"] for row in spicy_evidence} == {
        "CONTRADICTION",
        "OVERRIDDEN_GENERAL",
    }


def test_single_syllable_korean_alias_does_not_match_inside_unlisted_compound() -> None:
    features, _evidence = compile_menu_preference_features(
        knowledge_release_id="knowledge-v2",
        menus=[
            _menu(
                name_ko="오늘의 음료",
                name_en="Daily beverage",
                description="",
                category="음료",
            )
        ],
        mappings=[],
        concept_supports=[],
        chunks=[],
        options_by_menu={
            "menu-a": [
                {
                    "name_ko": "빙탕설리 500mL",
                    "source_ref": "option:beverage",
                }
            ]
        },
    )

    assert not any(row["option_code"] == "SOUP" for row in features)


def test_composite_menu_adds_memberships_without_replacing_primary_mapping() -> None:
    memberships = build_menu_concept_memberships(
        knowledge_release_id="knowledge-v2",
        menus=[_menu(name_ko="김치찌개 + 돈까스", name_en="")],
        mappings=[
            {
                "menu_id": "menu-a",
                "concept_id": "concept-kimchi-stew",
                "mapping_status": "MAPPED",
                "source_type": "YOBI_DERIVED_DEMO_MAPPING",
                "source_ref": "mapping:primary",
                "review_status": "REVIEWED_DEMO",
                "is_synthetic": 1,
            }
        ],
        concepts=[
            {
                "concept_id": "concept-kimchi-stew",
                "concept_type": "DISH",
                "canonical_name_ko": "김치찌개",
                "canonical_name_en": "kimchi stew",
                "aliases_json": "[]",
            },
            {
                "concept_id": "concept-pork-cutlet",
                "concept_type": "DISH",
                "canonical_name_ko": "돈까스",
                "canonical_name_en": "pork cutlet",
                "aliases_json": "[]",
            },
        ],
    )

    assert [(row["concept_id"], row["membership_role"]) for row in memberships] == [
        ("concept-kimchi-stew", "PRIMARY"),
        ("concept-pork-cutlet", "COMPONENT"),
    ]


def test_compiler_preserves_non_synthetic_provenance_flags() -> None:
    mapping = {
        "menu_id": "menu-a",
        "concept_id": "concept-noodle",
        "mapping_status": "MAPPED",
        "source_type": "YOGIYO_PUBLIC_WEB",
        "source_ref": "mapping:public",
        "review_status": "SOURCE_DERIVED",
        "is_synthetic": 0,
    }
    features, evidence = compile_menu_preference_features(
        knowledge_release_id="knowledge-v2",
        menus=[_menu(name_ko="중립 메뉴", name_en="Neutral menu", description="")],
        mappings=[mapping],
        concept_supports=[
            {
                "concept_id": "concept-noodle",
                "category_code": "temperatures",
                "option_code": "HOT",
                "support_status": "SUPPORTED",
                "support_strength": 0.8,
                "evidence_chunk_id": "chunk-hot",
                "provenance_type": "YOGIYO_PUBLIC_WEB",
                "source_ref": "public:concept-noodle",
                "review_status": "SOURCE_DERIVED",
                "is_synthetic": 0,
            }
        ],
        chunks=[{"chunk_id": "chunk-hot", "content": "Served hot."}],
    )
    hot = next(row for row in features if row["option_code"] == "HOT")
    assert hot["is_synthetic"] == 0
    hot_evidence = [row for row in evidence if row["feature_id"] == hot["feature_id"]]
    assert hot_evidence and all(row["is_synthetic"] == 0 for row in hot_evidence)

    memberships = build_menu_concept_memberships(
        knowledge_release_id="knowledge-v2",
        menus=[_menu(name_ko="중립 메뉴", name_en="Neutral menu")],
        mappings=[mapping],
        concepts=[],
    )
    assert memberships[0]["is_synthetic"] == 0


def test_feature_manifest_ignores_timestamps_but_detects_semantic_changes() -> None:
    features, evidence = compile_menu_preference_features(
        knowledge_release_id="knowledge-v2",
        menus=[_menu()],
        mappings=[],
        concept_supports=[],
        chunks=[],
    )
    first = feature_manifest_sha256(features, evidence, [])
    timestamp_changed = [dict(row, updated_at="2099-01-01T00:00:00Z") for row in features]
    assert feature_manifest_sha256(timestamp_changed, evidence, []) == first
    changed = [dict(row) for row in features]
    changed[0]["support_strength"] = 0.01
    assert feature_manifest_sha256(changed, evidence, []) != first
