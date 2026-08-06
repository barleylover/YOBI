import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.genai.agent_loop import AgentLoop
from app.genai.tool_registry import ToolRegistry


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
    assert fake.responses.calls[1]["previous_response_id"] == "resp_1"
    returned = json.loads(fake.responses.calls[1]["input"][0]["output"])
    assert set(returned) == {"untrusted_data"}
    assert returned["untrusted_data"]["menus"][0]["menu_id"] == "menu_001_01"
