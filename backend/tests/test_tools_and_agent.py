import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.domain.dialogue import DialogueAct, MealNeedState
from app.domain.models import AssistantTurn, ChatState
from app.genai.agent_loop import AgentLoop
from app.genai.contracts import GenAIErrorCode, GenAIProviderError
from app.genai.grounding import GroundedResponseValidator
from app.genai.tool_registry import ToolRegistry
from app.genai.tool_schemas import TOOLS, select_tools


def _selected_state(repository: Any, menu_id: str, option_ids: list[str]) -> MealNeedState:
    selections: dict[str, list[str]] = {}
    for group in repository.get_options(menu_id):
        allowed = {item.option_item_id for item in group.items}
        selected = [option_id for option_id in option_ids if option_id in allowed]
        if selected:
            selections[group.option_group_id] = selected
    return MealNeedState(
        selected_menu_id=menu_id,
        option_selections=selections,
    )


def test_master_spec_exposes_all_fourteen_tools() -> None:
    assert {tool["name"] for tool in TOOLS} == {
        "recommend_menu_categories",
        "search_menus",
        "explain_menu",
        "get_dietary_evidence",
        "compare_merchants",
        "get_menu_options",
        "update_cart",
        "translate_order_note",
        "resolve_address",
        "update_delivery_preferences",
        "get_cart_preview",
        "create_mock_checkout",
        "get_mock_payment_status",
        "complete_mock_order",
    }


def test_tool_routing_keeps_each_provider_turn_small_and_relevant() -> None:
    discovery = {tool["name"] for tool in select_tools("warm mild food after rain")}
    assert discovery == {"recommend_menu_categories", "search_menus", "explain_menu"}
    payment = {tool["name"] for tool in select_tools("check my payment status")}
    assert payment == {"get_cart_preview", "get_mock_payment_status"}
    assert max(len(select_tools(prompt)) for prompt in ("food", "hotel", "option", "pay")) <= 4


def test_tool_routing_prefers_structured_dialogue_act_over_last_message_keyword() -> None:
    comparison = {
        tool["name"] for tool in select_tools("tell me more", DialogueAct.COMPARE)
    }
    explanation = {
        tool["name"]
        for tool in select_tools("what about it?", DialogueAct.REQUEST_EXPLANATION)
    }

    assert comparison == {"search_menus", "compare_merchants", "get_dietary_evidence"}
    assert explanation == {"explain_menu", "get_dietary_evidence", "get_menu_options"}
    add_to_cart = {
        tool["name"] for tool in select_tools("add it to cart", DialogueAct.ORDER_ACTION)
    }
    assert add_to_cart == {
        "get_menu_options",
        "update_cart",
        "translate_order_note",
        "get_cart_preview",
    }
    show_cart = {
        tool["name"] for tool in select_tools("show my cart", DialogueAct.ORDER_ACTION)
    }
    assert show_cart == {"get_cart_preview"}
    korean_cart = {
        tool["name"] for tool in select_tools("장바구니 보여줘", DialogueAct.ORDER_ACTION)
    }
    assert korean_cart == {"get_cart_preview"}


def test_tool_registry_rejects_unknown_and_invalid_json(repository, profile_data) -> None:  # type: ignore[no-untyped-def]
    severe_profile = repository.create_profile(profile_data)
    registry = ToolRegistry(repository, severe_profile)
    with pytest.raises(ValueError, match="UNKNOWN_TOOL"):
        registry.execute("drop_database", "{}")
    with pytest.raises(ValueError, match="INVALID_TOOL_ARGUMENTS_JSON"):
        registry.execute("search_menus", "not-json")


@pytest.mark.parametrize("leak", ["update_cart", "chunk_internal_123", "merchant_001"])
def test_grounding_validator_rejects_internal_names_and_ids(leak: str) -> None:
    turn = AssistantTurn(
        message_id="msg-test",
        text=f"I used {leak} for this answer.",
        state=ChatState.DISCOVERY,
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(GenAIProviderError) as caught:
        GroundedResponseValidator().validate(turn, [], [])
    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED


def test_no_tool_dialogue_must_be_structured_and_cannot_smuggle_a_menu() -> None:
    validator = GroundedResponseValidator()
    safe_turn = AssistantTurn(
        message_id="msg-question",
        text="Would you prefer something warm and comforting or light and fresh?",
        state=ChatState.CLARIFICATION,
        created_at=datetime.now(timezone.utc),
    )
    validator.validate_no_tool_dialogue(safe_turn, "QUESTION")

    unsafe_turn = safe_turn.model_copy(
        update={"text": "I recommend bibimbap as your best match."}
    )
    with pytest.raises(GenAIProviderError) as caught:
        validator.validate_no_tool_dialogue(unsafe_turn, "QUESTION")
    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED

    unseen_dish = safe_turn.model_copy(
        update={"text": "A good option is pizza. Would you like that?"}
    )
    with pytest.raises(GenAIProviderError) as caught_unseen:
        validator.validate_no_tool_dialogue(unseen_dish, "QUESTION")
    assert caught_unseen.value.code is GenAIErrorCode.GROUNDING_REJECTED

    with pytest.raises(GenAIProviderError) as unstructured:
        validator.validate_no_tool_dialogue(safe_turn, None)
    assert unstructured.value.code is GenAIErrorCode.NO_TOOL_RESPONSE


def test_extended_read_tools_are_grounded_and_confirmation_safe(repository, profile_data) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    registry = ToolRegistry(repository, profile, session.session_id)
    categories = registry.execute(
        "recommend_menu_categories",
        json.dumps(
            {
                "query": "warm mild chicken noodle soup after rain",
                "budget_krw": 15000,
                "max_spiciness": 1,
                "excluded_ingredients": ["pork"],
                "servings": 1,
                "desired_temperature": "warm",
                "desired_texture": ["soupy"],
                "desired_flavors": ["mild", "savory"],
            }
        ),
    )
    assert categories["categories"]
    explanation = registry.execute("explain_menu", '{"menu_id":"menu_003_01"}')
    assert explanation["explanation"]["evidence_ids"]
    assert explanation["explanation"]["dietary_claims"]
    assert explanation["explanation"]["preparation_claims"]
    dietary = registry.execute("get_dietary_evidence", '{"menu_id":"menu_003_01"}')
    assert dietary["menu_id"] == "menu_003_01"
    assert dietary["dietary_claims"]
    assert dietary["preparation_claims"]
    assert dietary["wiki_passages"]
    assert dietary["grounded_passage_ids"]
    assert {
        claim["source_id"]
        for claim in [*dietary["dietary_claims"], *dietary["preparation_claims"]]
    }.issubset(dietary["grounded_claim_ids"])
    compact_dietary = AgentLoop._compact_tool_result("get_dietary_evidence", dietary)
    assert compact_dietary["dietary_claims"]
    assert compact_dietary["preparation_claims"]
    assert compact_dietary["wiki_passages"]
    assert compact_dietary["grounded_passage_ids"]
    address = registry.execute("resolve_address", '{"text":"YOBI Myeongdong Hotel"}')
    assert address["requires_confirmation"] is True
    note = registry.execute(
        "translate_order_note",
        '{"user_note":"No cutlery, leave at front desk","target_context":"courier","tone":"polite"}',
    )
    assert note["requires_confirmation"] is True
    assert "프런트" in note["korean_translation"]


def test_update_cart_tool_uses_repository_pricing_and_can_clear(repository, profile_data) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    option_ids = [
        "oi_001_01_spice_mild",
        "oi_001_01_size_regular",
    ]
    registry = ToolRegistry(
        repository,
        profile,
        session.session_id,
        meal_need_state=_selected_state(repository, "menu_001_01", option_ids),
    )
    added = registry.execute(
        "update_cart",
        json.dumps(
            {
                "action": "ADD_ITEM",
                "menu_id": "menu_001_01",
                "cart_item_id": None,
                "quantity": 2,
                "option_item_id": None,
                "option_item_ids": option_ids,
                "note": "",
            }
        ),
    )["cart"]
    assert added["items"][0]["line_total"] == added["items"][0]["unit_price"] * 2
    assert added["confirmed"] is False
    cleared = registry.execute(
        "update_cart",
        json.dumps(
            {
                "action": "CLEAR",
                "menu_id": None,
                "cart_item_id": None,
                "quantity": None,
                "option_item_id": None,
                "option_item_ids": [],
                "note": None,
            }
        ),
    )["cart"]
    assert cleared["items"] == []


def test_update_cart_agent_request_key_prevents_duplicate_add(repository, profile_data) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    registry = ToolRegistry(
        repository,
        profile,
        session.session_id,
        meal_need_state=_selected_state(
            repository,
            "menu_001_01",
            ["oi_001_01_spice_mild", "oi_001_01_size_regular"],
        ),
        mutation_idempotency_key="agent-add-one-menu-001",
    )
    arguments = json.dumps(
        {
            "action": "ADD_ITEM",
            "menu_id": "menu_001_01",
            "cart_item_id": None,
            "quantity": 1,
            "option_item_id": None,
            "option_item_ids": [
                "oi_001_01_spice_mild",
                "oi_001_01_size_regular",
            ],
            "note": None,
        }
    )

    first = registry.execute("update_cart", arguments)["cart"]
    duplicate = registry.execute("update_cart", arguments)["cart"]

    assert len(first["items"]) == 1
    assert len(duplicate["items"]) == 1
    assert duplicate["items"][0]["cart_item_id"] == first["items"][0]["cart_item_id"]
    changed_arguments = json.loads(arguments)
    changed_arguments["quantity"] = 2
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REUSED"):
        registry.execute("update_cart", json.dumps(changed_arguments))


def test_update_cart_tool_cannot_override_server_selection_or_options(
    repository, profile_data
) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    selected_options = ["oi_001_01_spice_mild", "oi_001_01_size_regular"]
    registry = ToolRegistry(
        repository,
        profile,
        session.session_id,
        meal_need_state=_selected_state(repository, "menu_001_01", selected_options),
    )

    with pytest.raises(ValueError, match="CART_MENU_SELECTION_MISMATCH"):
        registry.execute(
            "update_cart",
            json.dumps(
                {
                    "action": "ADD_ITEM",
                    "menu_id": "menu_002_01",
                    "option_item_ids": ["oi_002_01_size_regular"],
                }
            ),
        )
    with pytest.raises(ValueError, match="CART_OPTION_SELECTION_MISMATCH"):
        registry.execute(
            "update_cart",
            json.dumps(
                {
                    "action": "ADD_ITEM",
                    "menu_id": "menu_001_01",
                    "option_item_ids": [*selected_options, "oi_001_01_cheese_add"],
                }
            ),
        )
    assert repository.get_cart(session.session_id).items == []


def test_tool_audit_failure_never_masks_authoritative_result(
    repository, profile_data, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit sink outage")

    monkeypatch.setattr(repository, "record_audit", fail_audit)
    result = ToolRegistry(repository, profile).execute(
        "search_menus",
        '{"query":"mild rice cake","excluded_ingredients":[]}',
    )

    assert result["menus"]


def test_agent_loop_executes_bounded_function_call(repository, profile_data) -> None:  # type: ignore[no-untyped-def]
    severe_profile = repository.create_profile(profile_data)
    first = SimpleNamespace(
        id="resp_1",
        output=[
            SimpleNamespace(type="reasoning", summary="provider-specific auxiliary item"),
            SimpleNamespace(
                type="function_call",
                name="search_menus",
                arguments=json.dumps(
                    {
                        "query": "mild red rice cake",
                        "budget_krw": 15000,
                        "max_spiciness": 1,
                        "excluded_ingredients": [],
                    }
                ),
                call_id="call_1",
            ),
        ],
        output_text="",
    )
    second = SimpleNamespace(id="resp_2", output=[], output_text="I found a grounded mild option.")

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return first if len(self.calls) == 1 else second

    fake = SimpleNamespace(responses=FakeResponses())
    agent = AgentLoop(Settings(oci_genai_api_key="test-key", tool_call_max_steps=2))
    agent.client_factory.build = lambda: fake  # type: ignore[method-assign]
    result = agent.run(
        "something mild", "state=DISCOVERY", ToolRegistry(repository, severe_profile)
    )
    assert result.text == "I found a grounded mild option."
    assert result.tool_results[0][0] == "search_menus"
    assert result.tool_results[0][1]["menus"][0]["menu_id"] == "menu_001_01"
    assert "previous_response_id" not in fake.responses.calls[1]
    assert "You are YOBI" in fake.responses.calls[1]["instructions"]
    assert "state=DISCOVERY" in fake.responses.calls[1]["instructions"]
    assert fake.responses.calls[1]["input"][0] == {
        "role": "user",
        "content": "something mild",
    }
    assert fake.responses.calls[1]["input"][1] is first.output[1]
    returned = json.loads(fake.responses.calls[1]["input"][2]["output"])
    assert set(returned) == {"untrusted_data"}
    assert returned["untrusted_data"]["menus"][0]["menu_id"] == "menu_001_01"
    assert "description" not in returned["untrusted_data"]["menus"][0]
    assert len(fake.responses.calls[1]["input"][2]["output"]) < 4_000


@pytest.mark.parametrize(
    "unoffered_name",
    ["update_cart", "create_mock_checkout", "update_delivery_preferences"],
)
def test_agent_rejects_every_unoffered_mutation_before_registry_execution(
    repository, profile_data, unoffered_name: str
) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    response = SimpleNamespace(
        id="unoffered-mutation",
        output=[
            SimpleNamespace(
                type="function_call",
                name=unoffered_name,
                arguments="{}",
                call_id="call-unoffered",
            )
        ],
        output_text="",
    )

    class FakeResponses:
        def create(self, **kwargs: Any) -> Any:
            return response

    registry = ToolRegistry(repository, profile, session.session_id)
    executed: list[str] = []

    def forbidden_execute(name: str, arguments: str) -> dict[str, Any]:
        executed.append(name)
        return {}

    registry.execute = forbidden_execute  # type: ignore[method-assign]
    agent = AgentLoop(Settings(oci_genai_api_key="test-key", llm_max_retries=0))
    agent.client_factory.build = lambda: SimpleNamespace(responses=FakeResponses())  # type: ignore[method-assign]

    with pytest.raises(GenAIProviderError) as caught:
        agent.run(
            "recommend something mild",
            "state=DISCOVERY",
            registry,
            dialogue_act=DialogueAct.REQUEST_RECOMMENDATION,
        )

    assert caught.value.code is GenAIErrorCode.INVALID_TOOL_ARGUMENT
    assert executed == []
    assert repository.get_cart(session.session_id).items == []


def test_mutation_result_survives_provider_failure_after_tool_execution(
    repository, profile_data
) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    tool_call = SimpleNamespace(
        id="resp_mutation",
        output=[
            SimpleNamespace(
                type="function_call",
                name="update_cart",
                arguments=json.dumps(
                    {
                        "action": "ADD_ITEM",
                        "menu_id": "menu_001_01",
                        "cart_item_id": None,
                        "quantity": 1,
                        "option_item_id": None,
                        "option_item_ids": [
                            "oi_001_01_spice_mild",
                            "oi_001_01_size_regular",
                        ],
                        "note": None,
                    }
                ),
                call_id="call_mutation",
            )
        ],
        output_text="",
    )

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                return tool_call
            raise TimeoutError("continuation timed out")

    responses = FakeResponses()
    agent = AgentLoop(Settings(oci_genai_api_key="test-key", llm_max_retries=0))
    agent.client_factory.build = lambda: SimpleNamespace(responses=responses)  # type: ignore[method-assign]
    registry = ToolRegistry(
        repository,
        profile,
        session.session_id,
        meal_need_state=_selected_state(
            repository,
            "menu_001_01",
            ["oi_001_01_spice_mild", "oi_001_01_size_regular"],
        ),
        mutation_idempotency_key="agent-mutation-timeout",
    )

    result = agent.run(
        "add this to cart",
        "state=ORDERING",
        registry,
        dialogue_act=DialogueAct.ORDER_ACTION,
    )

    assert result.provider_error_code is GenAIErrorCode.TIMEOUT
    assert result.tool_results[0][0] == "update_cart"
    assert len(result.tool_results[0][1]["cart"]["items"]) == 1
    assert len(repository.get_cart(session.session_id).items) == 1


@pytest.mark.parametrize(
    ("continuation_kind", "expected_code"),
    [
        ("empty", GenAIErrorCode.EMPTY_RESPONSE),
        ("invalid_schema", GenAIErrorCode.GROUNDING_REJECTED),
        ("step_limit", GenAIErrorCode.TOOL_STEP_LIMIT),
    ],
)
def test_mutation_result_survives_every_downstream_response_failure(
    repository,
    profile_data,
    continuation_kind: str,
    expected_code: GenAIErrorCode,
) -> None:  # type: ignore[no-untyped-def]
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    tool_call = SimpleNamespace(
        id="resp-mutation-boundary",
        output=[
            SimpleNamespace(
                type="function_call",
                name="update_cart",
                arguments=json.dumps(
                    {
                        "action": "ADD_ITEM",
                        "menu_id": "menu_001_01",
                        "cart_item_id": None,
                        "quantity": 1,
                        "option_item_id": None,
                        "option_item_ids": [
                            "oi_001_01_spice_mild",
                            "oi_001_01_size_regular",
                        ],
                        "note": None,
                    }
                ),
                call_id="call-mutation-boundary",
            )
        ],
        output_text="",
    )

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1 or continuation_kind == "step_limit":
                return tool_call
            if continuation_kind == "invalid_schema":
                return SimpleNamespace(
                    id="invalid-continuation",
                    output=[],
                    output_text='{"unexpected":"shape"}',
                )
            return SimpleNamespace(id="empty-continuation", output=[], output_text="")

    responses = FakeResponses()
    agent = AgentLoop(
        Settings(
            oci_genai_api_key="test-key",
            llm_max_retries=0,
            tool_call_max_steps=1 if continuation_kind == "step_limit" else 2,
        )
    )
    agent.client_factory.build = lambda: SimpleNamespace(responses=responses)  # type: ignore[method-assign]
    registry = ToolRegistry(
        repository,
        profile,
        session.session_id,
        meal_need_state=_selected_state(
            repository,
            "menu_001_01",
            ["oi_001_01_spice_mild", "oi_001_01_size_regular"],
        ),
        mutation_idempotency_key=f"mutation-{continuation_kind}-boundary",
    )

    result = agent.run(
        "add this to cart",
        "state=ORDERING",
        registry,
        dialogue_act=DialogueAct.ORDER_ACTION,
    )

    assert result.provider_error_code is expected_code
    assert result.tool_results[0][0] == "update_cart"
    assert len(repository.get_cart(session.session_id).items) == 1
