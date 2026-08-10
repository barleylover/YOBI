from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.dialogue import (
    ConversationEventInput,
    ConversationEventType,
    DialogueAct,
    MealNeedState,
)
from app.domain.models import ProfileCreate
from app.services.chat_service import ChatService
from app.services.demo_control import DemoControl


def _service(repository: SQLiteYobiRepository) -> ChatService:
    return ChatService(repository, Settings(), DemoControl())


def test_greeting_is_a_persisted_no_card_turn(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)

    turn = _service(repository).respond(session, profile, "hi")

    assert turn.dialogue_act == DialogueAct.GREET
    assert turn.readiness is not None and turn.readiness.may_recommend is False
    assert turn.cards == []
    assert turn.fallback_used is False
    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.state_version == 1
    assert persisted.dialogue_act == DialogueAct.GREET
    assistant = repository.list_messages(session.session_id)[-1]
    assert assistant["message_id"] == turn.message_id
    assert assistant["safe_metadata"]["cards"] == []
    messages = repository.list_messages(session.session_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hi"


def test_stale_chat_request_does_not_leave_an_orphan_user_message(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    stale_session = repository.create_session(profile.profile_id)
    service = _service(repository)
    service.respond(stale_session, profile, "hi")
    before = repository.list_messages(stale_session.session_id)

    with pytest.raises(RuntimeError, match="CHAT_STATE_VERSION_CONFLICT"):
        service.respond(stale_session, profile, "This request is stale")

    assert repository.list_messages(stale_session.session_id) == before


def test_completed_chat_request_replays_without_advancing_state(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    request_id = "chat-replay-request-0001"

    first = service.respond(session, profile, "hi", request_id=request_id)
    committed = repository.get_session(session.session_id)
    assert committed is not None
    replayed = service.respond(committed, profile, "hi", request_id=request_id)

    assert replayed == first
    assert repository.get_session(session.session_id).state_version == committed.state_version  # type: ignore[union-attr]
    messages = repository.list_messages(session.session_id)
    assert len(messages) == 2
    assert messages[0]["safe_metadata"]["client_request_id"] == request_id
    assert messages[1]["message_id"] == first.message_id

    with pytest.raises(ValueError, match="CHAT_REQUEST_ID_REUSED"):
        service.respond(committed, profile, "a different message", request_id=request_id)


def test_chat_request_retry_recovers_one_prior_cart_mutation(
    repository: SQLiteYobiRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        )
    )
    session = repository.create_session(profile.profile_id)
    menu_id = "menu_001_01"
    selections: dict[str, list[str]] = {}
    for group in repository.get_options(menu_id):
        available = [item.option_item_id for item in group.items if item.available]
        if group.min_select:
            selections[group.option_group_id] = available[: group.min_select]
    selected_state = MealNeedState(
        selected_menu_id=menu_id,
        option_selections=selections,
    )
    selected_session = repository.update_dialogue_state(
        session.session_id,
        DialogueAct.SELECT,
        selected_state,
        session.state.value,
        session.state_version,
    )
    service = _service(repository)
    original_commit = repository.commit_chat_turn

    def fail_before_turn_commit(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic lost response before turn commit")

    monkeypatch.setattr(repository, "commit_chat_turn", fail_before_turn_commit)
    request_id = "chat-cart-recovery-0001"
    with pytest.raises(RuntimeError, match="synthetic lost response"):
        service.respond(
            selected_session,
            profile,
            "add this to cart",
            request_id=request_id,
        )
    assert len(repository.get_cart(session.session_id).items) == 1
    assert repository.list_messages(session.session_id) == []

    monkeypatch.setattr(repository, "commit_chat_turn", original_commit)
    current = repository.get_session(session.session_id)
    assert current is not None
    recovered = service.respond(
        current,
        profile,
        "add this to cart",
        request_id=request_id,
    )

    assert recovered.dialogue_act == DialogueAct.ORDER_ACTION
    assert len(repository.get_cart(session.session_id).items) == 1
    assert len(repository.list_messages(session.session_id)) == 2


def test_hold_negative_constraint_and_correction_survive_multiple_turns(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = _service(repository)

    first = service.respond(session, profile, "No soup and no pork. Ask me questions first.")
    assert first.dialogue_act == DialogueAct.HOLD_RECOMMENDATION
    assert first.cards == []

    session = repository.get_session(session.session_id)
    assert session is not None
    second = service.respond(session, profile, "I would like something warm, savory and chewy.")
    assert second.cards == []
    assert second.readiness is not None and second.readiness.status.value == "HELD"

    session = repository.get_session(session.session_id)
    assert session is not None
    corrected = service.respond(session, profile, "Actually soup is okay, but still no pork.")
    assert corrected.cards == []
    state = repository.get_session(session.session_id)
    assert state is not None
    assert "soup" not in state.meal_need_state.excluded_categories
    assert "pork" in state.meal_need_state.excluded_ingredients

    recommended = service.respond(state, profile, "Recommend something now under 15,000 won.")
    assert recommended.cards
    assert recommended.recommendation_snapshot_id
    final_state = repository.get_session(session.session_id)
    assert final_state is not None
    assert "pork" in final_state.meal_need_state.excluded_ingredients
    assert final_state.meal_need_state.budget_krw == 15000


def test_unknown_answer_does_not_trigger_recommendation(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)

    turn = _service(repository).respond(session, profile, "I don't know yet")

    assert turn.cards == []
    assert turn.readiness is not None and turn.readiness.may_recommend is False


@pytest.mark.parametrize(
    "message",
    [
        "I don't want you to recommend anything yet.",
        "Don't recommend anything.",
        "Do not recommend.",
        "I don't want recommendations yet.",
        "I don't need any recommendations right now.",
        "Please don't give me recommendations.",
    ],
)
def test_indirect_recommendation_hold_does_not_show_menu_cards(
    repository: SQLiteYobiRepository,
    message: str,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    turn = _service(repository).respond(
        session,
        profile,
        message,
    )

    assert turn.dialogue_act == DialogueAct.HOLD_RECOMMENDATION
    assert turn.cards == []
    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.meal_need_state.recommendation_hold is True


def test_sensory_negation_and_correction_replace_conflicting_preferences(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)

    service.respond(
        session,
        profile,
        "I don't want warm food, don't want crispy food, and don't want spicy food.",
    )
    current = repository.get_session(session.session_id)
    assert current is not None
    assert {"warm", "crispy", "spicy"}.issubset(
        current.meal_need_state.negative_preferences
    )
    assert "warm" not in current.meal_need_state.temperature_preferences
    assert "crispy" not in current.meal_need_state.texture_preferences
    assert current.meal_need_state.max_spiciness == 1

    service.respond(
        current,
        profile,
        "Actually spicy is fine, and I want cold food instead.",
    )
    corrected = repository.get_session(session.session_id)
    assert corrected is not None
    assert "spicy" not in corrected.meal_need_state.negative_preferences
    assert "spicy" in corrected.meal_need_state.flavor_preferences
    assert corrected.meal_need_state.max_spiciness == profile.spice_tolerance
    assert corrected.meal_need_state.temperature_preferences == ["cold"]


@pytest.mark.parametrize(
    ("message", "negative", "positive_field"),
    [
        ("I don't like sweet food.", "sweet", "flavor_preferences"),
        ("I dislike crispy food.", "crispy", "texture_preferences"),
        ("I hate warm food.", "warm", "temperature_preferences"),
        ("I don't like spicy food.", "spicy", "flavor_preferences"),
    ],
)
def test_common_dislike_phrases_are_negative_preferences(
    repository: SQLiteYobiRepository,
    message: str,
    negative: str,
    positive_field: str,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    _service(repository).respond(session, profile, message)

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert negative in persisted.meal_need_state.negative_preferences
    assert negative not in getattr(persisted.meal_need_state, positive_field)


def test_sensory_question_does_not_relax_an_existing_spice_limit(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    service.respond(session, profile, "I prefer mild food.")
    current = repository.get_session(session.session_id)
    assert current is not None

    service.respond(current, profile, "Is the sauce spicy?")

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.meal_need_state.max_spiciness == 1
    assert "spicy" not in persisted.meal_need_state.flavor_preferences


def test_same_turn_positive_correction_wins_over_negative_flavor(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    _service(repository).respond(
        session,
        profile,
        "I don't want sweet, but actually sweet is fine.",
    )

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert "sweet" in persisted.meal_need_state.flavor_preferences
    assert "sweet" not in persisted.meal_need_state.negative_preferences


def test_last_same_turn_flavor_clause_wins(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    _service(repository).respond(
        session,
        profile,
        "Actually sweet is fine, but I don't want sweet.",
    )

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert "sweet" not in persisted.meal_need_state.flavor_preferences
    assert "sweet" in persisted.meal_need_state.negative_preferences


def test_last_korean_same_turn_flavor_clause_wins(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    _service(repository).respond(
        session,
        profile,
        "달콤한 건 싫었는데, 아니 이제는 달콤한 게 좋아요.",
    )

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert "sweet" in persisted.meal_need_state.flavor_preferences
    assert "sweet" not in persisted.meal_need_state.negative_preferences


@pytest.mark.parametrize(
    ("message", "expected"),
    [("How about cold food?", "cold"), ("What about something warm?", "warm")],
)
def test_sensory_suggestion_questions_capture_the_preference(
    repository: SQLiteYobiRepository,
    message: str,
    expected: str,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    _service(repository).respond(session, profile, message)

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert expected in persisted.meal_need_state.temperature_preferences


@pytest.mark.parametrize(
    ("message", "expected_spice"),
    [
        ("순한 음식 추천해줘", 1),
        ("순하고 따뜻한 음식 추천해줘", 1),
        ("순하게 만들어 주세요", 1),
        ("순하지 않은 매운 음식 추천해줘", 3),
        ("순한 음식 말고 매운 음식 추천해줘", 3),
        ("I don't want mild food; recommend something spicy.", 3),
        ("Mild food is not okay; recommend something spicy.", 3),
    ],
)
def test_mild_word_forms_do_not_match_negation(
    repository: SQLiteYobiRepository,
    message: str,
    expected_spice: int,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    _service(repository).respond(session, profile, message)

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.meal_need_state.max_spiciness == expected_spice


def test_provider_context_labels_current_and_previous_dialogue_acts(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = _service(repository)

    payload = json.loads(
        service._dynamic_context(
            session,
            profile,
            session.meal_need_state,
            current_dialogue_act=DialogueAct.ORDER_ACTION,
        )
    )

    assert payload["dialogue_act"] == "ORDER_ACTION"
    assert payload["previous_dialogue_act"] == "COLLECT_NEEDS"


def test_second_menu_reference_uses_latest_persisted_snapshot(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(session, profile, "Recommend a mild meal under 15,000 won")
    assert recommendation.recommendation_result is not None
    assert len(recommendation.recommendation_result.candidates) >= 2
    expected = recommendation.recommendation_result.candidates[1].menu_id

    session = repository.get_session(session.session_id)
    assert session is not None
    explanation = service.respond(session, profile, "Tell me about the second menu")

    assert explanation.dialogue_act == DialogueAct.EXPLAIN
    assert explanation.recommendation_snapshot_id is None
    assert explanation.cards[0].data["menu"]["menu_id"] == expected
    assert explanation.cards[0].data["explanation"]["source_position"] == 2


def test_generic_dish_question_uses_wiki_explanation_without_recommendation(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)

    turn = _service(repository).respond(session, profile, "What is gimbap?")

    assert turn.dialogue_act == DialogueAct.EXPLAIN
    assert turn.recommendation_snapshot_id is None
    assert [card.type for card in turn.cards] == ["menu_explanation"]
    assert turn.cards[0].data["explanation"]["general_wiki_explanation"] is True
    assert "general synthetic Wiki knowledge" in turn.text
    assert "recommend" not in turn.text.lower()


def test_generic_explanation_does_not_show_a_hard_constraint_conflict(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    service.respond(session, profile, "No pork.")
    current = repository.get_session(session.session_id)
    assert current is not None

    turn = service.respond(current, profile, "What is Gukbap?")

    assert turn.dialogue_act == DialogueAct.EXPLAIN
    assert [card.type for card in turn.cards] == ["menu_explanation"]
    assert "menu" not in turn.cards[0].data
    assert turn.cards[0].data["explanation"]["category"] == "Gukbap"
    assert turn.cards[0].data["explanation"]["compatible_listing"] is False
    assert "general synthetic Wiki knowledge" in turn.text


@pytest.mark.parametrize(
    "message",
    [
        "Explain quantum mechanics.",
        "Compare quantum mechanics and relativity.",
        "Tell me about Seoul.",
    ],
)
def test_targetless_information_request_asks_for_a_food_target(
    repository: SQLiteYobiRepository,
    message: str,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    turn = _service(repository).respond(session, profile, message)

    assert turn.dialogue_act == DialogueAct.COLLECT_NEEDS
    assert turn.readiness is not None and turn.readiness.may_recommend is False
    assert turn.cards == []
    assert turn.recommendation_snapshot_id is None
    assert "food" in turn.text.lower() or "menu" in turn.text.lower()


@pytest.mark.parametrize(
    ("initial", "target", "expected_act", "expected_card"),
    [
        ("Explain it.", "Bibimbap", DialogueAct.EXPLAIN, "menu_explanation"),
        ("Compare them.", "Bibimbap", DialogueAct.COMPARE, "merchant_comparison"),
    ],
)
def test_information_clarification_consumes_a_target_only_followup(
    repository: SQLiteYobiRepository,
    initial: str,
    target: str,
    expected_act: DialogueAct,
    expected_card: str,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)

    clarification = service.respond(session, profile, initial)
    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.meal_need_state.pending_information_request is not None

    resolved = service.respond(persisted, profile, target)

    assert clarification.cards == []
    assert resolved.dialogue_act == expected_act
    assert [card.type for card in resolved.cards] == [expected_card]
    final_session = repository.get_session(session.session_id)
    assert final_session is not None
    assert final_session.meal_need_state.pending_information_request is None


def test_explanation_clarification_resolves_a_visible_snapshot_ordinal(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session,
        profile,
        "Recommend a mild savory meal under 15,000 won",
    )
    assert recommendation.recommendation_result is not None
    expected = recommendation.recommendation_result.candidates[0].menu_id
    current = repository.get_session(session.session_id)
    assert current is not None

    clarification = service.respond(current, profile, "Explain it.")
    current = repository.get_session(session.session_id)
    assert current is not None
    resolved = service.respond(current, profile, "first menu")

    assert clarification.dialogue_act == DialogueAct.COLLECT_NEEDS
    assert resolved.dialogue_act == DialogueAct.EXPLAIN
    assert resolved.cards[0].data["menu"]["menu_id"] == expected
    final_session = repository.get_session(session.session_id)
    assert final_session is not None
    assert final_session.meal_need_state.pending_information_request is None


def test_explanation_clarification_resolves_a_visible_snapshot_name(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session,
        profile,
        "Recommend a varied meal under 20,000 won",
    )
    assert recommendation.recommendation_result is not None
    expected = recommendation.recommendation_result.candidates[0].menu_id
    menu = repository.get_menu(expected, profile)
    assert menu is not None
    current = repository.get_session(session.session_id)
    assert current is not None
    service.respond(current, profile, "Explain it.")
    current = repository.get_session(session.session_id)
    assert current is not None

    resolved = service.respond(current, profile, menu.name_en)

    assert resolved.dialogue_act == DialogueAct.EXPLAIN
    assert resolved.cards[0].data["menu"]["menu_id"] == expected


@pytest.mark.parametrize("followup", ["and the second menu", "Compare the second menu"])
def test_partial_snapshot_comparison_remembers_the_first_ordinal(
    repository: SQLiteYobiRepository,
    followup: str,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session,
        profile,
        "Recommend a varied meal under 20,000 won",
    )
    assert recommendation.recommendation_result is not None
    expected = [
        candidate.menu_id for candidate in recommendation.recommendation_result.candidates[:2]
    ]
    current = repository.get_session(session.session_id)
    assert current is not None

    clarification = service.respond(current, profile, "Compare the first menu")
    current = repository.get_session(session.session_id)
    assert current is not None
    resolved = service.respond(current, profile, followup)

    assert clarification.cards == []
    assert current.meal_need_state.pending_information_request == "compare"
    assert resolved.dialogue_act == DialogueAct.COMPARE
    assert [item["menu_id"] for item in resolved.cards[0].data["merchants"]] == expected
    final_session = repository.get_session(session.session_id)
    assert final_session is not None
    assert final_session.meal_need_state.pending_information_request is None


def test_food_target_comparison_still_returns_grounded_merchants(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)

    turn = _service(repository).respond(session, profile, "Compare bibimbap restaurants.")

    assert turn.dialogue_act == DialogueAct.COMPARE
    assert [card.type for card in turn.cards] == ["merchant_comparison"]
    assert turn.cards[0].data["merchants"]
    assert all(
        item["menu_name"] and item["menu_id"] for item in turn.cards[0].data["merchants"]
    )


def test_natural_comparison_uses_the_latest_snapshot_candidates(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session, profile, "Recommend a mild meal under 15,000 won"
    )
    assert recommendation.recommendation_result is not None
    expected = [
        candidate.menu_id for candidate in recommendation.recommendation_result.candidates[:2]
    ]
    current = repository.get_session(session.session_id)
    assert current is not None

    compared = service.respond(current, profile, "Compare the first and second menus")

    assert compared.dialogue_act == DialogueAct.COMPARE
    assert compared.recommendation_snapshot_id == recommendation.recommendation_snapshot_id
    assert [item["menu_id"] for item in compared.cards[0].data["merchants"]] == expected
    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.meal_need_state.compared_menu_ids == expected


def test_named_visible_menus_take_priority_over_category_comparison(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session,
        profile,
        "Recommend a varied meal under 20,000 won",
    )
    assert recommendation.recommendation_result is not None
    assert len(recommendation.recommendation_result.candidates) >= 2
    first_two = recommendation.recommendation_result.candidates[:2]
    names = [repository.get_menu(candidate.menu_id, profile) for candidate in first_two]
    assert all(menu is not None for menu in names)
    current = repository.get_session(session.session_id)
    assert current is not None

    compared = service.respond(
        current,
        profile,
        f"Compare {names[0].name_en} and {names[1].name_en}.",  # type: ignore[union-attr]
    )

    assert compared.dialogue_act == DialogueAct.COMPARE
    assert compared.recommendation_snapshot_id == recommendation.recommendation_snapshot_id
    assert [item["menu_id"] for item in compared.cards[0].data["merchants"]] == [
        candidate.menu_id for candidate in first_two
    ]


def test_category_comparison_preserves_session_hard_constraints(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    constrained = repository.update_dialogue_state(
        session.session_id,
        DialogueAct.REVISE,
        MealNeedState(max_spiciness=1),
        session.state.value,
        session.state_version,
    )

    turn = _service(repository).respond(
        constrained,
        profile,
        "Compare Tteokbokki restaurants.",
    )

    assert turn.dialogue_act == DialogueAct.COMPARE
    for card in turn.cards:
        for comparison in card.data.get("merchants", []):
            menu = repository.get_menu(comparison["menu_id"], profile)
            assert menu is not None and menu.spice_level <= 1
    if not turn.cards:
        assert "current hard constraints" in turn.text


def test_category_comparison_followup_does_not_reject_an_old_snapshot_menu(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    service.respond(session, profile, "Recommend a varied meal under 20,000 won")
    current = repository.get_session(session.session_id)
    assert current is not None
    comparison = service.respond(current, profile, "Compare Bibimbap restaurants.")
    assert comparison.cards
    followup_text = comparison.suggested_replies[1]
    current = repository.get_session(session.session_id)
    assert current is not None
    rejected_before = list(current.meal_need_state.rejected_menu_ids)

    service.respond(current, profile, followup_text)

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.meal_need_state.rejected_menu_ids == rejected_before


def test_natural_rejection_is_persisted_before_recommendation_refresh(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session, profile, "Recommend a mild meal under 15,000 won"
    )
    assert recommendation.recommendation_result is not None
    rejected_id = recommendation.recommendation_result.candidates[0].menu_id
    current = repository.get_session(session.session_id)
    assert current is not None

    refreshed = service.respond(
        current, profile, "I do not like the first menu. Show another."
    )

    assert refreshed.dialogue_act == DialogueAct.RECOMMEND
    assert refreshed.recommendation_result is not None
    assert rejected_id not in {
        candidate.menu_id for candidate in refreshed.recommendation_result.candidates
    }
    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert rejected_id in persisted.meal_need_state.rejected_menu_ids


def test_natural_ordinal_selection_updates_authoritative_session_columns(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session, profile, "Recommend a mild meal under 15,000 won"
    )
    assert recommendation.recommendation_result is not None
    expected = recommendation.recommendation_result.candidates[1]
    current = repository.get_session(session.session_id)
    assert current is not None

    selected = service.respond(current, profile, "Choose the second menu")

    assert selected.dialogue_act == DialogueAct.SELECT
    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert persisted.selected_menu_id == expected.menu_id
    assert persisted.selected_merchant_id == expected.merchant_id
    assert persisted.meal_need_state.selected_menu_id == expected.menu_id


def test_deterministic_order_action_keeps_options_and_cart_flow(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        )
    )
    session = repository.create_session(profile.profile_id)
    service = _service(repository)
    recommendation = service.respond(
        session, profile, "Recommend a mild savory meal under 15,000 won"
    )
    assert recommendation.recommendation_result is not None
    current = repository.get_session(session.session_id)
    assert current is not None
    selected = service.respond(current, profile, "Choose the first menu")
    assert selected.dialogue_act == DialogueAct.SELECT
    selected_session = repository.get_session(session.session_id)
    assert selected_session is not None
    selected_menu_id = selected_session.selected_menu_id
    assert selected_menu_id is not None

    current = repository.get_session(session.session_id)
    assert current is not None
    needs_options = service.respond(current, profile, "Add it to my cart")

    assert needs_options.dialogue_act == DialogueAct.ORDER_ACTION
    assert [card.type for card in needs_options.cards] == ["option_question"]
    assert repository.get_cart(session.session_id).items == []

    for index, group in enumerate(repository.get_options(selected_menu_id)):
        current = repository.get_session(session.session_id)
        assert current is not None
        chosen = [item.option_item_id for item in group.items if item.available][
            : group.min_select
        ]
        repository.apply_conversation_event(
            session.session_id,
            ConversationEventInput(
                event_type=ConversationEventType.UPDATE_OPTIONS,
                menu_id=selected_menu_id,
                option_group_id=group.option_group_id,
                option_item_ids=chosen,
                expected_state_version=current.state_version,
                idempotency_key=f"fallback-option-{index:02d}",
            ),
        )

    current = repository.get_session(session.session_id)
    assert current is not None
    added = service.respond(current, profile, "Add it to my cart")

    assert added.dialogue_act == DialogueAct.ORDER_ACTION
    assert [card.type for card in added.cards] == ["cart_summary"]
    cart = repository.get_cart(session.session_id)
    assert len(cart.items) == 1
    assert cart.items[0].menu_id == selected_menu_id


def test_snapshot_selection_event_is_validated_and_idempotent(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = _service(repository).respond(session, profile, "Recommend a mild meal under 15,000 won")
    assert turn.recommendation_result is not None
    menu_id = turn.recommendation_result.candidates[0].menu_id
    event = ConversationEventInput(
        event_type=ConversationEventType.SELECT_MENU,
        snapshot_id=turn.recommendation_snapshot_id,
        menu_id=menu_id,
        expected_state_version=turn.state_version,
        idempotency_key="select-event-0001",
    )

    applied = repository.apply_conversation_event(session.session_id, event)
    duplicate = repository.apply_conversation_event(session.session_id, event)

    assert applied.selected_menu_id == menu_id
    assert applied.selected_menu is not None
    assert duplicate.event_id == applied.event_id
    assert duplicate.duplicate is True
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.apply_conversation_event(
            session.session_id,
            event.model_copy(update={"event_type": ConversationEventType.REJECT_MENU}),
        )
    persisted = repository.get_session(session.session_id)
    assert persisted is not None and persisted.selected_menu_id == menu_id


def test_option_event_enforces_group_cardinality(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = _service(repository).respond(
        session, profile, "Recommend a mild meal under 15,000 won"
    )
    assert turn.recommendation_result is not None
    menu_id = turn.recommendation_result.candidates[0].menu_id
    selected = repository.apply_conversation_event(
        session.session_id,
        ConversationEventInput(
            event_type=ConversationEventType.SELECT_MENU,
            snapshot_id=turn.recommendation_snapshot_id,
            menu_id=menu_id,
            expected_state_version=turn.state_version,
            idempotency_key="select-before-cardinality-check",
        ),
    )
    required_group = next(
        group for group in repository.get_options(menu_id) if group.min_select > 0
    )

    with pytest.raises(ValueError, match="OPTION_SELECTION_CARDINALITY_INVALID"):
        repository.apply_conversation_event(
            session.session_id,
            ConversationEventInput(
                event_type=ConversationEventType.UPDATE_OPTIONS,
                menu_id=menu_id,
                option_group_id=required_group.option_group_id,
                option_item_ids=[],
                expected_state_version=selected.state_version,
                idempotency_key="invalid-empty-required-option",
            ),
        )


def test_concurrent_event_replay_returns_one_authoritative_result(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = _service(repository).respond(session, profile, "Recommend a mild meal under 15,000 won")
    assert turn.recommendation_result is not None
    event = ConversationEventInput(
        event_type=ConversationEventType.SELECT_MENU,
        snapshot_id=turn.recommendation_snapshot_id,
        menu_id=turn.recommendation_result.candidates[0].menu_id,
        expected_state_version=turn.state_version,
        idempotency_key="concurrent-select-event-0001",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: repository.apply_conversation_event(session.session_id, event),
                range(2),
            )
        )

    assert results[0].event_id == results[1].event_id
    assert sorted(result.duplicate for result in results) == [False, True]


def test_snapshot_rejects_menu_that_was_not_shown(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    turn = _service(repository).respond(session, profile, "Recommend a mild meal under 15,000 won")
    event = ConversationEventInput(
        event_type=ConversationEventType.SELECT_MENU,
        snapshot_id=turn.recommendation_snapshot_id,
        menu_id="menu_not_shown",
        idempotency_key="select-event-0002",
    )

    try:
        repository.apply_conversation_event(session.session_id, event)
    except ValueError as exc:
        assert str(exc) == "MENU_NOT_IN_RECOMMENDATION_SNAPSHOT"
    else:
        raise AssertionError("Out-of-snapshot selection must fail")


def test_explicit_religion_rules_are_persisted_without_nationality_inference(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            nationality="United States",
            religion_selection="Judaism",
            dietary_rules=[],
            allergy_severity="mild",
        )
    )
    session = repository.create_session(profile.profile_id)

    _service(repository).respond(session, profile, "I want something warm")

    persisted = repository.get_session(session.session_id)
    assert persisted is not None
    assert {"no_pork", "no_shellfish", "kosher_certification_unverified"}.issubset(
        persisted.meal_need_state.profile_dietary_rules
    )
    assert {"pork", "shellfish"}.issubset(persisted.meal_need_state.excluded_ingredients)


def test_ordinal_selection_is_distinct_from_ordinal_explanation() -> None:
    from app.services.dialogue_engine import DialogueEngine

    engine = DialogueEngine()

    assert engine.extract_delta("Choose the second menu").dialogue_act == DialogueAct.SELECT
    assert engine.extract_delta("첫 번째 메뉴로 선택").dialogue_act == DialogueAct.SELECT
    assert (
        engine.extract_delta("Tell me about the second menu").dialogue_act
        == DialogueAct.REQUEST_EXPLANATION
    )


def test_dialogue_extracts_all_ui_allergies_and_supports_corrections() -> None:
    from app.services.dialogue_engine import DialogueEngine

    engine = DialogueEngine()
    delta = engine.extract_delta("I am allergic to fish, peanut, tree nuts, wheat, soy, and sesame")
    assert {
        "fish_allergy",
        "peanut_allergy",
        "tree_nut_allergy",
        "wheat_allergy",
        "soy_allergy",
        "sesame_allergy",
    }.issubset(delta.add_dietary_rules)


def test_allergy_negation_and_clause_scope_are_applied_as_corrections(
    repository: SQLiteYobiRepository,
) -> None:
    from app.services.dialogue_engine import DialogueEngine

    engine = DialogueEngine()
    negated = engine.extract_delta("I'm not allergic to shellfish")
    assert "shellfish_allergy" not in negated.add_dietary_rules
    assert "shellfish_allergy" in negated.remove_dietary_rules
    assert "shellfish" not in negated.add_excluded_ingredients
    assert "shellfish" in negated.remove_excluded_ingredients

    scoped = engine.extract_delta("I'm allergic to shellfish and I like beef")
    assert scoped.add_dietary_rules == ["shellfish_allergy"]
    assert scoped.add_excluded_ingredients == ["shellfish"]
    assert "beef_allergy" not in scoped.add_dietary_rules
    assert "beef" not in scoped.add_excluded_ingredients

    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], allergy_severity="mild")
    )
    state = engine.merge(
        repository.create_session(profile.profile_id).meal_need_state,
        engine.extract_delta("I am allergic to shellfish"),
        profile,
    )
    corrected = engine.merge(
        state,
        engine.extract_delta("Actually, shellfish is not an allergy"),
        profile,
    )
    assert "shellfish_allergy" not in corrected.dietary_rules
    assert "shellfish" not in corrected.excluded_ingredients


def test_cart_view_variants_do_not_clear_recommendation_hold(
    repository: SQLiteYobiRepository,
) -> None:
    from app.services.dialogue_engine import DialogueEngine

    engine = DialogueEngine()
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], allergy_severity="mild")
    )
    state = engine.merge(
        repository.create_session(profile.profile_id).meal_need_state,
        engine.extract_delta("Ask me questions first"),
        profile,
    )
    assert state.recommendation_hold is True

    for message in (
        "Show me my cart",
        "Show the cart",
        "What's in my cart?",
        "Open my cart",
    ):
        delta = engine.extract_delta(message)
        assert delta.dialogue_act == DialogueAct.ORDER_ACTION
        assert delta.explicit_recommendation_request is False
        assert delta.recommendation_hold is None
        assert engine.merge(state, delta, profile).recommendation_hold is True

    recommend = engine.extract_delta("Recommend something for me")
    assert recommend.dialogue_act == DialogueAct.REQUEST_RECOMMENDATION
    assert recommend.recommendation_hold is False
    assert engine.merge(state, recommend, profile).recommendation_hold is False


def test_dialogue_removes_turn_rules_and_does_not_make_negatives_positive(
    repository: SQLiteYobiRepository,
) -> None:
    from app.services.dialogue_engine import DialogueEngine

    engine = DialogueEngine()
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], allergy_severity="mild")
    )
    state = engine.merge(
        repository.create_session(profile.profile_id).meal_need_state,
        engine.extract_delta("I am vegan and allergic to peanut"),
        profile,
    )
    corrected = engine.merge(
        state,
        engine.extract_delta("I am not vegan anymore and peanut is okay"),
        profile,
    )
    assert "vegan" not in corrected.dietary_rules
    assert "peanut_allergy" not in corrected.dietary_rules
    assert "peanut" not in corrected.excluded_ingredients

    negative_spicy = engine.extract_delta("I don't want spicy food")
    negative_sweet = engine.extract_delta("I want something not sweet")
    assert "spicy" not in negative_spicy.add_flavor_preferences
    assert "spicy" in negative_spicy.add_negative_preferences
    assert negative_spicy.max_spiciness == 1
    assert "sweet" not in negative_sweet.add_flavor_preferences
    assert "sweet" in negative_sweet.add_negative_preferences

    avoid_sweet = engine.merge(
        repository.create_session(profile.profile_id).meal_need_state,
        negative_sweet,
        profile,
    )
    sweet_is_fine = engine.merge(
        avoid_sweet,
        engine.extract_delta("Actually sweet is fine"),
        profile,
    )
    assert "sweet" not in sweet_is_fine.negative_preferences
    assert "sweet" in sweet_is_fine.flavor_preferences
    avoid_sweet_again = engine.merge(
        sweet_is_fine,
        engine.extract_delta("I do not want sweet food"),
        profile,
    )
    assert "sweet" in avoid_sweet_again.negative_preferences
    assert "sweet" not in avoid_sweet_again.flavor_preferences
    assert engine.extract_delta("Add it to my cart").dialogue_act == DialogueAct.ORDER_ACTION
    assert engine.extract_delta("Show my cart").dialogue_act == DialogueAct.ORDER_ACTION
    assert engine.extract_delta("장바구니 보여줘").dialogue_act == DialogueAct.ORDER_ACTION


@pytest.mark.parametrize(
    ("message", "expected_act"),
    [
        (
            "I don't want you to compare; just recommend something mild.",
            DialogueAct.REQUEST_RECOMMENDATION,
        ),
        (
            "Do not explain it; recommend something else.",
            DialogueAct.REQUEST_RECOMMENDATION,
        ),
        ("비교 말고 순한 음식 추천해줘.", DialogueAct.REQUEST_RECOMMENDATION),
        ("설명하지 말고 순한 음식 추천해줘.", DialogueAct.REQUEST_RECOMMENDATION),
        ("Compare the recommendations.", DialogueAct.COMPARE),
        ("Explain your recommendation.", DialogueAct.REQUEST_EXPLANATION),
        ("Don't recommend yet; compare these menus.", DialogueAct.COMPARE),
        ("Don't recommend yet; explain bibimbap.", DialogueAct.REQUEST_EXPLANATION),
        ("Don't compare these.", DialogueAct.COLLECT_NEEDS),
        ("설명하지 마.", DialogueAct.COLLECT_NEEDS),
    ],
)
def test_negated_compare_or_explanation_does_not_override_the_requested_action(
    message: str,
    expected_act: DialogueAct,
) -> None:
    from app.services.dialogue_engine import DialogueEngine

    assert DialogueEngine().extract_delta(message).dialogue_act == expected_act


@pytest.mark.parametrize("message", ["순한 음식", "순하고 짭짤한 음식", "순하게 해주세요"])
def test_korean_mild_inflection_updates_spice_constraint(message: str) -> None:
    from app.services.dialogue_engine import DialogueEngine

    assert DialogueEngine().extract_delta(message).max_spiciness == 1


def test_latest_profile_rules_replace_stale_profile_snapshot(
    repository: SQLiteYobiRepository,
) -> None:
    from app.services.dialogue_engine import DialogueEngine

    engine = DialogueEngine()
    original = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=["peanut_allergy"],
            allergy_severity="severe",
        )
    )
    state = engine.merge(
        repository.create_session(original.profile_id).meal_need_state,
        engine.extract_delta("I want something warm"),
        original,
    )
    assert "peanut_allergy" in state.dietary_rules
    updated = original.model_copy(update={"dietary_rules": []})

    refreshed = engine.merge(
        state,
        engine.extract_delta("Something savory"),
        updated,
    )

    assert "peanut_allergy" not in refreshed.profile_dietary_rules
    assert "peanut_allergy" not in refreshed.dietary_rules


def test_stale_snapshot_selection_revalidates_current_hard_constraints(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        )
    )
    session = repository.create_session(profile.profile_id)
    turn = _service(repository).respond(session, profile, "Recommend a mild meal under 30,000 won")
    assert turn.recommendation_result is not None
    candidate = turn.recommendation_result.candidates[0]
    menu = repository.get_menu(candidate.menu_id, profile)
    assert menu is not None
    latest = repository.get_session(session.session_id)
    assert latest is not None
    changed_state = latest.meal_need_state.model_copy(deep=True)
    changed_state.excluded_categories.append(menu.category.lower())
    updated = repository.update_dialogue_state(
        session.session_id,
        DialogueAct.REVISE,
        changed_state,
        latest.state.value,
        latest.state_version,
    )

    event = ConversationEventInput(
        event_type=ConversationEventType.SELECT_MENU,
        snapshot_id=turn.recommendation_snapshot_id,
        menu_id=candidate.menu_id,
        expected_state_version=updated.state_version,
        idempotency_key="stale-select-current-constraints",
    )
    with pytest.raises(ValueError, match="MENU_NO_LONGER_ELIGIBLE"):
        repository.apply_conversation_event(session.session_id, event)


def test_compare_event_persists_validated_menu_ids(
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        )
    )
    session = repository.create_session(profile.profile_id)
    turn = _service(repository).respond(session, profile, "Recommend a mild meal under 30,000 won")
    assert turn.recommendation_result is not None
    menu_ids = [candidate.menu_id for candidate in turn.recommendation_result.candidates[:2]]
    assert len(menu_ids) == 2

    result = repository.apply_conversation_event(
        session.session_id,
        ConversationEventInput(
            event_type=ConversationEventType.COMPARE_MENUS,
            snapshot_id=turn.recommendation_snapshot_id,
            menu_ids=menu_ids,
            expected_state_version=turn.state_version,
            idempotency_key="compare-persist-menu-ids",
        ),
    )

    assert result.state.compared_menu_ids == menu_ids
