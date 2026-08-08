import hashlib
import sqlite3
from itertools import permutations

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import Card, ChatState, ProfileCreate
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
    assert turn.recommendation_result is not None
    assert [candidate.menu_id for candidate in turn.recommendation_result.candidates] == [
        "menu_001_01"
    ]


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


def test_rainy_fallback_badges_only_show_saved_constraints(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            spice_tolerance=2,
            favorite_foods=[],
        )
    )
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session,
        profile,
        "Recommend something after walking in the rain.",
    )

    visible_copy = " ".join([turn.text, turn.cards[0].title, turn.cards[0].subtitle or ""]).lower()
    assert "no pork" not in visible_copy
    assert "15,000" not in visible_copy
    assert "maximum spice 2 of 3" in visible_copy


def test_chicken_kalguksu_followup_has_explanation_and_evidence_sources(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session, profile, "Show me chicken kalguksu"
    )
    assert [card.type for card in turn.cards] == ["menu_explanation"]
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


def test_vegan_fallback_does_not_invent_an_allergy_or_severity(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session,
        profile,
        "I'm vegan. What could work?",
    )

    visible_copy = (turn.text + " " + turn.cards[0].subtitle).lower()
    assert "shellfish" not in visible_copy
    assert "severe allergy" not in visible_copy
    assert "verified vegan" in visible_copy


def test_tteokbokki_fallback_does_not_invent_shellfish_or_low_spice_need(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session,
        profile,
        "What is that red rice cake street food? Can I order it?",
    )

    assert "your shellfish" not in turn.text.lower()
    assert "exceeds your current maximum" not in turn.text.lower()
    assert [card.type for card in turn.cards] == ["menu_recommendations"]
    assert turn.cards[0].data["menus"][0]["menu_id"] == "menu_002_01"


def test_server_narrative_uses_profile_language_and_discloses_parser_boundary(
    repository: SQLiteYobiRepository,
) -> None:
    cases = [
        ("한국어", "안녕하세요", None),
        ("日本語", "こんにちは", "英語または韓国語"),
        ("Español", "¡Hola!", "inglés o coreano"),
    ]

    for language, greeting, boundary in cases:
        profile = repository.create_profile(
            ProfileCreate(
                consent_demo_data=True,
                preferred_language=language,
                dietary_rules=[],
            )
        )
        session = repository.create_session(profile.profile_id)
        turn = ChatService(repository, Settings(), DemoControl()).respond(
            session,
            profile,
            "hi",
        )
        assert greeting in turn.text
        if boundary is not None:
            assert boundary in turn.text


def test_server_grounded_result_is_localized_for_japanese_and_spanish(
    repository: SQLiteYobiRepository,
) -> None:
    service = ChatService(repository, Settings(), DemoControl())
    turn = service._make_turn(
        "provider text",
        ChatState.MENU_EXPLANATION,
        [
            Card(
                type="menu_recommendations",
                title="Grounded menu matches",
                data={"menus": [{"name_en": "Bibimbap"}]},
            )
        ],
        False,
    )

    assert "有力候補" in service._server_grounded_text(turn, "日本語")
    assert "mejores coincidencias" in service._server_grounded_text(turn, "Español")


def test_server_grounded_text_prioritizes_final_outcome_for_every_card_order(
    repository: SQLiteYobiRepository,
) -> None:
    service = ChatService(repository, Settings(), DemoControl())
    cards = [
        Card(
            type="option_question",
            title="Options",
            data={"option_groups": [{"name_en": "Spice"}]},
        ),
        Card(
            type="cart_summary",
            title="Cart",
            data={"cart": {"items": [{}], "total_price": 12_000, "missing_slots": []}},
        ),
        Card(
            type="payment_cta",
            title="Payment",
            data={"checkout": {"status": "SUCCEEDED", "amount": 12_000}},
        ),
        Card(
            type="order_complete",
            title="Order",
            data={"order": {"order_status": "CONFIRMED"}},
        ),
    ]

    narratives = {
        service._server_grounded_text(
            service._make_turn(
                "provider text",
                ChatState.ORDER_COMPLETE,
                list(card_order),
                False,
            )
        )
        for card_order in permutations(cards)
    }
    assert narratives == {
        "The synthetic mock order status is CONFIRMED. No restaurant received it and no "
        "real payment was made."
    }


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
    # Information-gathering questions are a normal no-tool dialogue path, not fallback.
    assert row[2] == 0


def test_duplicate_menu_tool_results_render_one_deduplicated_carousel(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    result = ToolRegistry(repository, profile, session.session_id).execute(
        "search_menus",
        '{"query":"mild rice cake","budget_krw":15000,"max_spiciness":2,"excluded_ingredients":[]}',
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
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True, spice_tolerance=3))
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session, profile, "Show me this week's delivery ranking", "weekly_ranking"
    )

    assert turn.fallback_used is False
    assert [card.type for card in turn.cards] == ["preset_collection"]
    entries = turn.cards[0].data["entries"]
    assert [entry["label"] for entry in entries] == [
        "BBQ",
        "BHC",
        "No More Pizza",
        "Hong Kong Banjeom",
        "Yeopgi Tteokbokki",
    ]
    assert [entry["menu"]["menu_id"] for entry in entries] == [
        "menu_021_01",
        "menu_022_01",
        "menu_023_01",
        "menu_024_01",
        "menu_025_01",
    ]


def test_weekly_ranking_omits_item_above_current_spice_limit(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True, spice_tolerance=1))
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session, profile, "Show me this week's delivery ranking", "weekly_ranking"
    )

    entries = turn.cards[0].data["entries"]
    assert "Yeopgi Tteokbokki" not in {entry["label"] for entry in entries}
    assert "omitted" in turn.text.lower()


def test_kpop_food_collection_is_fixed_and_orderable(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)

    turn = ChatService(repository, Settings(), DemoControl()).respond(
        session, profile, "Show me the foods from K-POP Demon Hunters", "kpop_demon_hunters"
    )

    entries = turn.cards[0].data["entries"]
    assert [entry["label"] for entry in entries] == [
        "Gimbap",
        "Gukbap",
        "Hotteok",
        "Seolleongtang",
        "Eomuk",
    ]
    for entry in entries:
        menu = entry["menu"]
        assert menu["price"] > 0
        assert repository.get_options(menu["menu_id"])
