from __future__ import annotations

from math import ceil

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.dialogue import MealNeedState
from app.domain.knowledge import ClaimStatus, SourceScope
from app.domain.models import ProfileCreate
from app.domain.recommendation import rerank_menu_candidates
from app.rag.embeddings import (
    HybridChunkCandidate,
    apply_soft_profile_retrieval_signal,
    exact_essential_similarity,
    hybrid_knowledge_chunk_score,
    rank_hybrid_chunks_rrf,
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


def test_rrf_combines_vector_lexical_and_exact_essential_rankings() -> None:
    ranked = rank_hybrid_chunks_rrf(
        ("spicy chili", "매운맛"),
        [
            HybridChunkCandidate(
                chunk_id="chunk-vector-only",
                content="A gentle and creamy dish.",
                facet="paragraph",
                aliases=("cream noodles",),
                vector_similarity=1.0,
            ),
            HybridChunkCandidate(
                chunk_id="chunk-multi-signal",
                content="A spicy chili flavor defines this dish.",
                facet="paragraph",
                aliases=("spicy noodles",),
                vector_similarity=0.7,
            ),
            HybridChunkCandidate(
                chunk_id="chunk-essential",
                content="Main ingredient: chili pepper.",
                facet="essential_fact",
                aliases=("pepper rice",),
                vector_similarity=0.6,
            ),
        ],
        limit=2,
    )

    assert [candidate.chunk_id for candidate, _ in ranked] == [
        "chunk-multi-signal",
        "chunk-essential",
    ]
    assert ranked[0][1] > ranked[1][1] > 0.0
    assert exact_essential_similarity(
        ("chili",),
        "Main ingredient: chili pepper.",
        "essential_fact",
    ) == 1.0
    assert abs(apply_soft_profile_retrieval_signal(0.8, 1.0) - 0.82) < 1e-9
    assert apply_soft_profile_retrieval_signal(0.95, 0.0) > (
        apply_soft_profile_retrieval_signal(0.8, 1.0)
    )


def test_korean_questions_retrieve_the_requested_active_wiki_facet_first(
    repository: SQLiteYobiRepository,
) -> None:
    # Prose-v2 chunks deliberately use a compatibility `paragraph` facet. The
    # natural paragraph content, not one of the old fixed nine facet labels,
    # must remain the retrieval authority.
    queries = (
        "어떤 재료가 들어가?",
        "무슨 맛이야?",
        "식감이 쫄깃해?",
        "따뜻하게 먹어?",
    )

    for query in queries:
        knowledge = repository.get_grounded_menu_knowledge("menu_001_01", query=query)
        assert knowledge.release_id
        assert knowledge.passages[0].facet in {"paragraph", "essential_fact"}
        assert knowledge.passages[0].content.strip()


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


def test_grounded_knowledge_exposes_essential_preparation_without_public_dietary_wiki_claims(
    repository: SQLiteYobiRepository,
) -> None:
    knowledge = repository.get_grounded_menu_knowledge(
        "menu_001_01", query="할랄 비건 채식 식단과 조리법"
    )

    assert knowledge.preparation_claims
    # Prose-v2 no longer elevates subjective or safety-oriented Wiki text into
    # dietary claims. Any retained dietary facts are menu-catalog compatibility
    # signals, while preparation can remain an essential concept fact.
    assert all(
        claim.source_scope is SourceScope.MENU for claim in knowledge.dietary_claims
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
