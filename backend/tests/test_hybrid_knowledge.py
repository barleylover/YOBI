from __future__ import annotations

from math import ceil

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.dialogue import MealNeedState
from app.domain.knowledge import ClaimStatus, SourceScope
from app.domain.models import ProfileCreate
from app.domain.recommendation import rerank_menu_candidates
from app.rag.embeddings import (
    hybrid_knowledge_chunk_score,
    routed_knowledge_facets,
)


def test_bilingual_wiki_facet_router_is_deterministic() -> None:
    assert routed_knowledge_facets("어떤 재료가 들어가?")[0] == "ingredients"
    assert routed_knowledge_facets("알레르기 위험이 있어?")[0] == "safety"
    assert routed_knowledge_facets("무슨 맛이야?")[0] == "taste"
    assert routed_knowledge_facets("식감이 쫄깃해?")[0] == "texture"
    assert routed_knowledge_facets("따뜻하게 먹어?")[0] == "temperature"
    assert routed_knowledge_facets("어떻게 조리해?")[0] == "preparation"
    for safety_query in (
        "할랄 식단이야?",
        "Is this halal?",
        "비건으로 먹을 수 있어?",
        "vegan dietary option",
        "채식 메뉴인가요?",
        "vegetarian religious restriction",
    ):
        assert routed_knowledge_facets(safety_query)[0] == "safety"


def test_exact_korean_alias_and_requested_facet_beat_vector_only_noise() -> None:
    routed = hybrid_knowledge_chunk_score(
        "참치김밥의 알레르기를 알려줘",
        0.0,
        "safety",
        ["참치김밥", "tuna gimbap"],
    )
    unrelated = hybrid_knowledge_chunk_score(
        "참치김밥의 알레르기를 알려줘",
        0.1,
        "culture",
        ["치즈김밥", "cheese gimbap"],
    )

    assert routed > unrelated


def test_korean_questions_retrieve_the_requested_active_wiki_facet_first(
    repository: SQLiteYobiRepository,
) -> None:
    queries = {
        "어떤 재료가 들어가?": "ingredients",
        "알레르기 위험이 있어?": "safety",
        "무슨 맛이야?": "taste",
        "식감이 쫄깃해?": "texture",
        "따뜻하게 먹어?": "temperature",
        "할랄 식단에 맞아?": "safety",
        "비건으로 먹을 수 있어?": "safety",
        "Is this suitable for a vegetarian religious diet?": "safety",
    }

    for query, expected_facet in queries.items():
        knowledge = repository.get_grounded_menu_knowledge("menu_001_01", query=query)
        assert knowledge.release_id
        assert knowledge.passages[0].facet == expected_facet


def test_wiki_core_and_menu_fact_constraints_filter_candidates(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )

    no_beef = repository.recommend_menus(
        "savory grilled meal",
        profile,
        MealNeedState(
            flavor_preferences=["savory"],
            excluded_ingredients=["beef"],
            max_spiciness=3,
        ),
        limit=150,
    )
    assert no_beef
    assert all(menu.category != "Bulgogi" for menu in no_beef)

    no_pork = repository.recommend_menus(
        "warm filling rice",
        profile,
        MealNeedState(
            temperature_preferences=["warm"],
            flavor_preferences=["hearty"],
            excluded_ingredients=["pork"],
            max_spiciness=3,
        ),
        limit=150,
    )
    assert all(menu.menu_id not in {"menu_024_01", "menu_027_01"} for menu in no_pork)


def test_missing_wiki_claim_never_becomes_confirmed_absent_and_option_can_override(
    repository: SQLiteYobiRepository,
) -> None:
    base = repository.get_grounded_menu_knowledge("menu_001_01", query="ingredients")
    assert base.release_id
    assert base.concept_id == "dish_rose_tteokbokki"
    assert base.passages
    assert all(claim.status is not ClaimStatus.CONFIRMED_ABSENT for claim in base.ingredient_claims)

    customized = repository.get_grounded_menu_knowledge(
        "menu_001_01",
        query="ingredients",
        option_item_ids=["oi_001_01_fishcake_remove"],
    )
    fish_cake = next(
        claim
        for claim in customized.ingredient_claims
        if claim.ingredient_id == "ingredient_fish_cake"
    )
    assert fish_cake.status is ClaimStatus.CONFIRMED_ABSENT
    assert fish_cake.source_scope is SourceScope.OPTION
    assert fish_cake.name_ko == "어묵"
    assert fish_cake.model_dump(mode="json")["name_ko"] == "어묵"


def test_grounded_knowledge_exposes_structured_dietary_and_preparation_claims(
    repository: SQLiteYobiRepository,
) -> None:
    knowledge = repository.get_grounded_menu_knowledge(
        "menu_001_01", query="할랄 비건 채식 식단과 조리법"
    )

    assert knowledge.dietary_claims
    assert knowledge.preparation_claims
    assert any(
        claim.source_scope is SourceScope.DISH_CONCEPT
        and claim.status in {ClaimStatus.POSSIBLE, ClaimStatus.PRESUMED_PRESENT}
        for claim in knowledge.dietary_claims
    )
    assert any(
        claim.source_scope is SourceScope.MENU for claim in knowledge.dietary_claims
    )
    assert all(
        claim.source_scope is SourceScope.DISH_CONCEPT
        for claim in knowledge.preparation_claims
    )
    structured_ids = {
        claim.source_id
        for claim in [*knowledge.dietary_claims, *knowledge.preparation_claims]
    }
    assert structured_ids.issubset(knowledge.claim_ids)


def test_explicit_allergen_absence_preserves_unknown_cross_contact(
    repository: SQLiteYobiRepository,
) -> None:
    with repository._connection() as connection:
        row = connection.execute(
            """
            SELECT menu_id,allergen_id FROM menu_allergen
            WHERE status='ABSENT' AND cross_contamination_status='UNKNOWN'
            ORDER BY menu_id,allergen_id LIMIT 1
            """
        ).fetchone()
    assert row is not None

    knowledge = repository.get_grounded_menu_knowledge(str(row["menu_id"]), query="allergy")
    absence = next(
        claim
        for claim in knowledge.allergen_claims
        if claim.allergen_id == row["allergen_id"]
    )
    assert absence.status is ClaimStatus.CONFIRMED_ABSENT
    assert absence.cross_contamination_status == "UNKNOWN"
    assert any("not a safety certification" in item for item in knowledge.unknowns)


def test_merchant_origin_is_visible_but_not_promoted_to_every_menu_fact(
    repository: SQLiteYobiRepository,
) -> None:
    with repository._connection() as connection:
        menu_id = str(
            connection.execute(
                """
                SELECT menu.menu_id
                FROM menu
                JOIN merchant_origin_declaration declaration
                  ON declaration.merchant_id=menu.merchant_id
                ORDER BY menu.menu_id
                LIMIT 1
                """
            ).fetchone()[0]
        )
    knowledge = repository.get_grounded_menu_knowledge(menu_id)

    assert knowledge.merchant_origin_notes
    assert all("merchant-wide" in note.lower() for note in knowledge.merchant_origin_notes)
    assert all(
        claim.source_scope is not SourceScope.MERCHANT for claim in knowledge.ingredient_claims
    )


def test_review_text_has_zero_recommendation_weight(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    state = MealNeedState(
        temperature_preferences=["warm"],
        flavor_preferences=["savory"],
        max_spiciness=3,
    )
    before = [
        menu.menu_id
        for menu in repository.recommend_menus("warm savory meal", profile, state, limit=10)
    ]
    with repository._connection() as connection:
        connection.execute(
            "UPDATE review_snippet SET review_text='adversarial unrelated commercial review'"
        )
    after = [
        menu.menu_id
        for menu in repository.recommend_menus("warm savory meal", profile, state, limit=10)
    ]

    assert after == before


def test_structured_preferences_rerank_cold_refreshing_noodles(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )

    results = repository.recommend_menus(
        "cold refreshing noodles",
        profile,
        MealNeedState(
            temperature_preferences=["cold"],
            flavor_preferences=["light"],
            preferred_categories=["noodles"],
            max_spiciness=3,
        ),
        limit=3,
    )

    assert results
    assert results[0].category == "Naengmyeon"
    assert any("cold preference" in reason.lower() for reason in results[0].match_reasons)


def test_temperature_contradiction_never_gets_a_positive_match_reason(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    candidates = repository.search_menus(
        "cold refreshing noodles",
        profile,
        budget_krw=None,
        max_spiciness=3,
        excluded_ingredients=[],
        limit=40,
    )
    naengmyeon = next(menu for menu in candidates if menu.category == "Naengmyeon")

    [reranked] = rerank_menu_candidates(
        [naengmyeon],
        MealNeedState(temperature_preferences=["warm"], max_spiciness=3),
        {naengmyeon.merchant_id: "area_myeongdong"},
        limit=1,
    )

    assert not any("warm preference" in reason.lower() for reason in reranked.match_reasons)
    assert reranked.semantic_score < naengmyeon.semantic_score


def test_negative_flavor_preference_is_an_explicit_candidate_filter(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )

    results = repository.recommend_menus(
        "savory meal, not sweet",
        profile,
        MealNeedState(
            flavor_preferences=["savory"],
            negative_preferences=["sweet"],
            max_spiciness=3,
        ),
        limit=10,
    )

    assert results
    assert all(
        "sweet" not in f"{menu.category} {menu.description}".lower().replace("sweet-potato", "")
        for menu in results
    )
    assert len({menu.category for menu in results[:3]}) >= 2


def test_party_budget_accounts_for_required_portion_count(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    party_size = 4
    budget = 40_000

    results = repository.recommend_menus(
        "savory dinner for four people",
        profile,
        MealNeedState(
            party_size=party_size,
            budget_krw=budget,
            flavor_preferences=["savory"],
            max_spiciness=3,
        ),
        limit=10,
    )

    assert results
    assert all(menu.price * ceil(party_size / menu.serves_max) <= budget for menu in results)
    assert all(
        any("for 4 people" in reason for reason in menu.match_reasons) for menu in results
    )


def test_party_budget_filter_runs_before_any_retrieval_truncation(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    party_size = 6
    budget = 20_000

    results = repository.recommend_menus(
        "meal for 6",
        profile,
        MealNeedState(party_size=party_size, budget_krw=budget, max_spiciness=3),
        limit=10,
    )

    assert results
    assert all(menu.price * ceil(party_size / menu.serves_max) <= budget for menu in results)


def test_each_service_area_has_a_qualified_alternative_for_all_onboarding_allergies(
    repository: SQLiteYobiRepository,
) -> None:
    with repository._connection() as connection:
        expected_areas = {
            str(row[0])
            for row in connection.execute(
                "SELECT service_area_id FROM service_area WHERE active=1"
            ).fetchall()
        }
        merchant_areas = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT merchant_id,service_area_id FROM merchant"
            ).fetchall()
        }
    for allergy, allergen_code in (
        ("shellfish_allergy", "shellfish_risk"),
        ("fish_allergy", "fish"),
        ("milk_allergy", "milk"),
        ("egg_allergy", "egg"),
        ("peanut_allergy", "peanut"),
        ("tree_nut_allergy", "tree_nut"),
        ("wheat_allergy", "wheat"),
        ("soy_allergy", "soy"),
        ("sesame_allergy", "sesame"),
    ):
        profile = repository.create_profile(
            ProfileCreate(
                consent_demo_data=True,
                dietary_rules=[allergy],
                allergy_severity="severe",
                spice_tolerance=3,
            )
        )

        results = repository.recommend_menus(
            "a mild meal",
            profile,
            MealNeedState(budget_krw=30_000, max_spiciness=3),
            limit=600,
        )
        assert results
        assert {merchant_areas[menu.merchant_id] for menu in results} == expected_areas
        for menu in results:
            knowledge = repository.get_grounded_menu_knowledge(menu.menu_id, query="allergy")
            matching = [
                claim for claim in knowledge.allergen_claims if claim.code == allergen_code
            ]
            assert matching
            assert all(claim.status is ClaimStatus.CONFIRMED_ABSENT for claim in matching)
            assert all(claim.source_scope is SourceScope.MENU for claim in matching)
            assert all(claim.cross_contamination_status == "UNKNOWN" for claim in matching)
            assert "Cross-contamination is not verified" in menu.risk_hints
            assert any(
                allergen_code.removesuffix("_risk").replace("_", " ") in reason.lower()
                for reason in menu.match_reasons
            )


def test_canonical_shellfish_alternative_requires_scoped_absence_and_unknown_cross_contact(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=["shellfish_allergy"],
            allergy_severity="severe",
            spice_tolerance=3,
        )
    )

    results = repository.recommend_menus(
        "creamy mild rice cakes",
        profile,
        MealNeedState(max_spiciness=3),
        limit=150,
    )

    matched = next(menu for menu in results if menu.menu_id == "menu_001_01")
    assert "Cross-contamination is not verified" in matched.risk_hints
    knowledge = repository.get_grounded_menu_knowledge("menu_001_01", query="shellfish")
    absence = next(
        claim for claim in knowledge.allergen_claims if claim.code == "shellfish_risk"
    )
    assert absence.status is ClaimStatus.CONFIRMED_ABSENT
    assert absence.source_scope is SourceScope.MENU
    assert absence.cross_contamination_status == "UNKNOWN"


def test_explicit_islam_profile_excludes_grounded_pork_without_nationality_inference(
    repository: SQLiteYobiRepository,
) -> None:
    islam_profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            nationality="United States",
            religion_selection="Islam",
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        )
    )
    no_religion_profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            nationality="Indonesia",
            religion_selection="No specific religion",
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        )
    )

    islam_results = repository.recommend_menus(
        "warm rice meal",
        islam_profile,
        MealNeedState(max_spiciness=3),
        limit=150,
    )
    no_religion_results = repository.recommend_menus(
        "warm rice meal",
        no_religion_profile,
        MealNeedState(max_spiciness=3),
        limit=150,
    )

    assert "menu_027_01" not in {menu.menu_id for menu in islam_results}
    assert "menu_027_01" in {menu.menu_id for menu in no_religion_results}
