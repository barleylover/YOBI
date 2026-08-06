from app.db.seed_data import seed_counts
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import EvidenceStatus, ProfileCreate, ProfileUpdate


def test_seed_meets_master_minimums() -> None:
    counts = seed_counts()
    assert counts["merchants"] == 30
    assert counts["menus"] == 150
    assert counts["knowledge"] == 150
    assert counts["reviews"] == 600
    assert counts["evidence"] == 300
    assert counts["option_items"] >= 250
    assert counts["hotels"] == 20


def test_severe_shellfish_filter_excludes_classic_risk_but_keeps_grounded_alternative(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    results = repository.search_menus(
        "red rice cake dish creamy and mild",
        profile,
        budget_krw=15000,
        max_spiciness=5,
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
