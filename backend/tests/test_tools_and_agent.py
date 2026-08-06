import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.genai.agent_loop import AgentLoop
from app.genai.tool_registry import ToolRegistry
from app.genai.tool_schemas import TOOLS, select_tools


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
    assert payment == {
        "get_cart_preview",
        "create_mock_checkout",
        "get_mock_payment_status",
        "complete_mock_order",
    }
    assert max(len(select_tools(prompt)) for prompt in ("food", "hotel", "option", "pay")) <= 4


def test_tool_registry_rejects_unknown_and_invalid_json(repository, profile_data) -> None:  # type: ignore[no-untyped-def]
    severe_profile = repository.create_profile(profile_data)
    registry = ToolRegistry(repository, severe_profile)
    with pytest.raises(ValueError, match="UNKNOWN_TOOL"):
        registry.execute("drop_database", "{}")
    with pytest.raises(ValueError, match="INVALID_TOOL_ARGUMENTS_JSON"):
        registry.execute("search_menus", "not-json")


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
    registry = ToolRegistry(repository, profile, session.session_id)
    added = registry.execute(
        "update_cart",
        json.dumps(
            {
                "action": "ADD_ITEM",
                "menu_id": "menu_001_01",
                "cart_item_id": None,
                "quantity": 2,
                "option_item_id": None,
                "option_item_ids": [
                    "oi_001_01_spice_mild",
                    "oi_001_01_size_regular",
                ],
                "note": "As mild as possible",
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


def test_agent_loop_executes_bounded_function_call(repository, profile_data) -> None:  # type: ignore[no-untyped-def]
    severe_profile = repository.create_profile(profile_data)
    first = SimpleNamespace(
        id="resp_1",
        output=[
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
            )
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
    result = agent.run("something mild", "state=DISCOVERY", ToolRegistry(repository, severe_profile))
    assert result.text == "I found a grounded mild option."
    assert result.tool_results[0][0] == "search_menus"
    assert result.tool_results[0][1]["menus"][0]["menu_id"] == "menu_001_01"
    assert "previous_response_id" not in fake.responses.calls[1]
    assert fake.responses.calls[1]["input"][0] == {
        "role": "user",
        "content": "something mild",
    }
    assert fake.responses.calls[1]["input"][1] is first.output[0]
    returned = json.loads(fake.responses.calls[1]["input"][2]["output"])
    assert set(returned) == {"untrusted_data"}
    assert returned["untrusted_data"]["menus"][0]["menu_id"] == "menu_001_01"
