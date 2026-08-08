from __future__ import annotations

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.dialogue import MealNeedState
from app.domain.knowledge import ClaimStatus, SourceScope
from app.domain.models import ProfileCreate


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


def test_merchant_origin_is_visible_but_not_promoted_to_every_menu_fact(
    repository: SQLiteYobiRepository,
) -> None:
    knowledge = repository.get_grounded_menu_knowledge("menu_001_02")

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


def test_severe_peanut_and_wheat_unknowns_fail_closed(
    repository: SQLiteYobiRepository,
) -> None:
    for allergy in ("peanut_allergy", "wheat_allergy"):
        profile = repository.create_profile(
            ProfileCreate(
                consent_demo_data=True,
                dietary_rules=[allergy],
                allergy_severity="severe",
                spice_tolerance=3,
            )
        )

        assert (
            repository.search_menus(
                "a mild meal",
                profile,
                budget_krw=30000,
                max_spiciness=3,
                excluded_ingredients=[],
                limit=150,
            )
            == []
        )


def test_shellfish_mastered_menu_fact_preserves_existing_demo_path(
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
        "warm soup and rice",
        profile,
        MealNeedState(max_spiciness=3),
        limit=150,
    )

    assert "menu_027_01" in {menu.menu_id for menu in results}


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
