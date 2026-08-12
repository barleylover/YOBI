from app.db.seed_data import build_seed, seed_counts
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.dialogue import MealNeedState
from app.domain.models import EvidenceStatus, ProfileCreate, ProfileUpdate


def test_seed_meets_master_minimums() -> None:
    counts = seed_counts()
    assert counts["merchants"] == 60
    assert counts["menus"] == 600
    assert counts["knowledge"] == 600
    assert counts["reviews"] == 2400
    assert counts["evidence"] == 1200
    assert counts["option_items"] >= 1200
    assert counts["hotels"] == 20


def test_seed_uses_the_five_level_spice_contract() -> None:
    seed = build_seed()
    assert {menu["spice_level"] for menu in seed["menus"]} == {1, 2, 3, 4, 5}
    assert all(
        1 <= category["typical_spice_min"] <= category["typical_spice_max"] <= 5
        for category in seed["menu_categories"]
    )


def test_severe_shellfish_filter_excludes_classic_risk_but_keeps_grounded_alternative(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    results = repository.search_menus(
        "red rice cake dish creamy and mild",
        profile,
        budget_krw=15000,
        max_spiciness=3,
        excluded_ingredients=[],
        limit=10,
    )
    ids = {menu.menu_id for menu in results}
    assert "menu_002_01" not in ids
    assert "menu_001_01" in ids
    assert all(
        any("shellfish" in reason.lower() for reason in menu.match_reasons)
        for menu in results
    )
    mild = next(menu for menu in results if menu.menu_id == "menu_001_01")
    assert mild.evidence_status is EvidenceStatus.VERIFIED
    assert mild.evidence_ids == ["ev_001_01_1", "ev_001_01_2"]
    assert "Cross-contamination is not verified" in mild.risk_hints


def test_classic_tteokbokki_has_no_false_reassurance(
    repository: SQLiteYobiRepository,
) -> None:
    evidence = repository.get_evidence("menu_002_01")
    assert {item.status for item in evidence} == {EvidenceStatus.RISK_SIGNAL}
    combined = " ".join(item.excerpt + " " + item.suggested_action for item in evidence).lower()
    assert "safe for you" not in combined
    assert "avoid" in combined


def test_profile_can_be_updated_without_replacing_identity(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)

    updated = repository.update_profile(
        profile.profile_id,
        ProfileUpdate(spice_tolerance=3, favorite_foods=["Bibimbap"]),
    )

    assert updated is not None
    assert updated.profile_id == profile.profile_id
    assert updated.spice_tolerance == 3
    assert updated.favorite_foods == ["bibimbap"]


def test_same_merchant_followup_excludes_carted_and_dietary_conflicting_menus(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)

    menus = repository.list_merchant_menus(
        "mer_001",
        profile,
        ["menu_001_01"],
        limit=12,
        meal_need_state=MealNeedState(max_spiciness=2),
    )

    assert menus
    assert all(menu.merchant_id == "mer_001" for menu in menus)
    assert all(menu.menu_id != "menu_001_01" for menu in menus)
    assert all(menu.spice_level <= 2 for menu in menus)
    assert any(menu.menu_id == "menu_001_10" for menu in menus)


def test_same_merchant_followup_respects_explicit_spice_revision(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, spice_tolerance=1, dietary_rules=[])
    )

    menus = repository.list_merchant_menus(
        "mer_001",
        profile,
        [],
        limit=12,
        meal_need_state=MealNeedState(max_spiciness=3),
    )

    assert menus
    assert any(menu.spice_level > profile.spice_tolerance for menu in menus)
    assert all(menu.spice_level <= 3 for menu in menus)


def test_catalog_lookup_preserves_legacy_shellfish_risk_evidence(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, spice_tolerance=3, dietary_rules=[])
    )

    risky = repository.get_menu("menu_002_01", profile)
    assert risky is not None
    assert risky.evidence_status is EvidenceStatus.RISK_SIGNAL


def test_option_conflict_names_the_dietary_rule_it_applies_to(
    repository: SQLiteYobiRepository,
) -> None:
    groups = repository.get_options("menu_001_01")
    keep_fish_cake = next(
        item
        for group in groups
        for item in group.items
        if item.option_item_id == "oi_001_01_fishcake_keep"
    )

    assert keep_fish_cake.conflicting_rules == ["shellfish_allergy"]
