import hashlib
import sqlite3

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import ProfileCreate
from app.genai.tool_registry import ToolRegistry
from app.services.chat_service import ChatService
from app.services.demo_control import DemoControl


def test_canonical_fallback_returns_risk_evidence_and_mild_alternative(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = ChatService(repository, Settings(), DemoControl())

    turn = service.respond(
        session,
        profile,
        "I saw people eating some red rice cake dish on the street. Can I order it?",
    )

    assert turn.fallback_used is True
    assert "avoid" in turn.text.lower()
    assert "not verified" in turn.text.lower()
    assert [card.type for card in turn.cards] == [
        "dietary_evidence",
        "menu_recommendations",
    ]
    alternative = turn.cards[1].data["menus"][0]
    assert alternative["menu_id"] == "menu_001_01"


def test_abstract_warm_request_returns_grounded_category_card(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session,
        profile,
        "Something warm and mild after walking in the rain. No pork and under 15,000 won.",
    )
    assert turn.state.value == "CATEGORY_SHORTLIST"
    assert turn.cards[0].type == "category_recommendations"
    categories = turn.cards[0].data["categories"]
    assert categories
    assert categories[0]["source_ids"]
    assert any(item["category"] == "Chicken kalguksu" for item in categories)


def test_chicken_kalguksu_followup_has_explanation_and_evidence_sources(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session, profile, "Show me chicken kalguksu"
    )
    assert [card.type for card in turn.cards] == ["menu_explanation", "menu_recommendations"]
    explanation = turn.cards[0].data["explanation"]
    assert explanation["cultural_analogy"]
    assert explanation["evidence_ids"]
    assert any("cross-contamination" in item.lower() for item in explanation["unknown_fields"])


def test_vegan_request_preserves_unknown_and_does_not_reassure(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session,
        profile,
        "I'm vegan and I can't handle spicy food. What could work?",
    )
    combined = turn.text.lower() + str(turn.cards[0].data).lower()
    assert "not verify" in combined or "not verified" in combined
    assert "safe for" not in combined
    assert "cross-contamination" in combined


def test_chat_audit_stores_hashes_without_raw_message_or_session(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    raw_message = "A private allergy question that must not be logged verbatim"

    ChatService(repository, Settings(), DemoControl()).respond(session, profile, raw_message)

    with sqlite3.connect(repository.path) as connection:
        row = connection.execute(
            "SELECT session_id, input_hash, fallback_used FROM audit_log "
            "WHERE tool = 'assistant_turn' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(session.session_id.encode()).hexdigest()
    assert row[1] == hashlib.sha256(raw_message.encode()).hexdigest()
    assert raw_message not in row
    assert session.session_id not in row
    assert row[2] == 1


def test_duplicate_menu_tool_results_render_one_deduplicated_carousel(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    result = ToolRegistry(repository, profile, session.session_id).execute(
        "search_menus",
        '{"query":"mild rice cake","budget_krw":15000,"max_spiciness":2,'
        '"excluded_ingredients":[]}',
    )

    turn = ChatService(repository, Settings(), DemoControl())._turn_from_tool_results(
        session,
        "Grounded result",
        [("search_menus", result), ("search_menus", result)],
    )

    assert [card.type for card in turn.cards] == ["menu_recommendations"]
    menu_ids = [menu["menu_id"] for menu in turn.cards[0].data["menus"]]
    assert len(menu_ids) == len(set(menu_ids))


def test_weekly_ranking_is_fixed_and_does_not_enter_fallback(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session, profile, "Show me this week's delivery ranking", "weekly_ranking"
    )

    assert turn.fallback_used is False
    assert [card.type for card in turn.cards] == ["preset_collection"]
    entries = turn.cards[0].data["entries"]
    assert [entry["label"] for entry in entries] == [
        "BBQ", "BHC", "No More Pizza", "Hong Kong Banjeom", "Yeopgi Tteokbokki"
    ]
    assert [entry["menu"]["menu_id"] for entry in entries] == [
        "menu_021_01", "menu_022_01", "menu_023_01", "menu_024_01", "menu_025_01"
    ]


def test_kpop_food_collection_is_fixed_and_orderable(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session, profile, "Show me the foods from K-POP Demon Hunters", "kpop_demon_hunters"
    )

    entries = turn.cards[0].data["entries"]
    assert [entry["label"] for entry in entries] == [
        "Gimbap", "Gukbap", "Hotteok", "Seolleongtang", "Eomuk"
    ]
    for entry in entries:
        menu = entry["menu"]
        assert menu["price"] > 0
        assert repository.get_options(menu["menu_id"])
