from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)
from app.genai.recommendation_generator import (
    RECOMMENDATION_GENERATION_JSON_SCHEMA,
    RecommendationGenerator,
)


class FakeProvider:
    def __init__(self, output: dict[str, Any], *, structured_output: bool = True) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []
        self._capabilities = ProviderCapabilities(
            provider="fake",
            serving_mode=GenAIServingMode.ON_DEMAND,
            responses_api=True,
            function_calling=True,
            structured_output=structured_output,
            native_streaming=False,
            client_managed_continuation=True,
            server_managed_continuation=False,
            max_input_tokens=32768,
            max_output_tokens=1200,
            max_tools_per_request=4,
            max_tool_calls_per_response=4,
        )

    @property
    def configured(self) -> bool:
        return True

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def supports_model(self, model: str) -> bool:
        return model == "xai.grok-4.3"

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        return SimpleNamespace(output_text=json.dumps(self.output))


def _criteria() -> dict[str, Any]:
    return {
        "cuisine_origins": ["KOREAN"],
        "flavors": ["SPICY", "NUTTY_SAVORY"],
        "main_ingredients": [],
        "food_forms": [],
        "temperatures": [],
        "price_bands": ["UNDER_10000"],
        "textures": [],
        "cooking_methods": [],
        "dietary_filters": {"halal_certified_only": False, "vegan": False},
        "max_spice_level": 3,
        "spice_reference_country": "KR",
    }


def _pool_item(menu_id: str, cuisine_id: str, flavor_id: str) -> dict[str, Any]:
    return {
        "menu_id": menu_id,
        "criterion_evidence": {
            "cuisine_origins": {
                "KOREAN": {"evidence_ids": [cuisine_id]},
            },
            "flavors": {
                "SPICY": {"evidence_ids": [flavor_id]},
            },
        },
        "wiki_passages": [
            {"passage_id": cuisine_id, "content": "A Korean dish."},
            {"passage_id": flavor_id, "content": "It can taste spicy."},
        ],
    }


def _recommendation(menu_id: str, rank: int, cuisine_id: str, flavor_id: str) -> dict[str, Any]:
    return {
        "rank": rank,
        "menu_id": menu_id,
        "title": f"Choice {rank}",
        "selection_reason": "It matches the requested cuisine and flavor.",
        "description": "The Wiki describes this as a satisfying Korean dish.",
        "matched_criteria": [
            {
                "category_code": "cuisine_origins",
                "selected_value_codes": ["KOREAN"],
                "evidence_ids": [cuisine_id],
            },
            {
                "category_code": "flavors",
                "selected_value_codes": ["SPICY"],
                "evidence_ids": [flavor_id],
            },
        ],
        "wiki_evidence_ids": [cuisine_id, flavor_id],
        "caution_codes": [],
    }


def test_generator_dispatches_once_without_tools_and_preserves_model_order() -> None:
    output = {
        "status": "RECOMMENDED",
        "criteria_summary": "Korean and spicy",
        "recommendations": [
            _recommendation("dish-b", 1, "chunk-b-cuisine", "chunk-b-flavor"),
            _recommendation("dish-a", 2, "chunk-a-cuisine", "chunk-a-flavor"),
        ],
        "unmatched_category_codes": [],
    }
    provider = FakeProvider(output)
    generator = RecommendationGenerator(Settings(), provider=provider)

    result = generator.generate(
        criteria=_criteria(),
        soft_profile_context={"nationality": "United States"},
        evidence_pool=[
            _pool_item("dish-a", "chunk-a-cuisine", "chunk-a-flavor"),
            _pool_item("dish-b", "chunk-b-cuisine", "chunk-b-flavor"),
        ],
        locale="English",
    )

    assert [item.menu_id for item in result.recommendations] == ["dish-b", "dish-a"]
    assert len(provider.calls) == 1
    assert "tools" not in provider.calls[0]
    assert provider.calls[0]["text"]["format"]["strict"] is True
    request_payload = json.loads(provider.calls[0]["input"][0]["content"])
    assert request_payload["response_contract"] == provider.calls[0]["text"]["format"][
        "schema"
    ]


def test_generator_supplies_json_contract_without_native_structured_output() -> None:
    provider = FakeProvider(
        {
            "status": "NO_MATCH",
            "criteria_summary": "No complete match",
            "recommendations": [],
            "unmatched_category_codes": ["flavors"],
        },
        structured_output=False,
    )
    generator = RecommendationGenerator(Settings(), provider=provider)

    generator.generate(
        criteria=_criteria(),
        soft_profile_context={},
        evidence_pool=[_pool_item("dish-a", "chunk-cuisine", "chunk-flavor")],
        locale="English",
    )

    request_payload = json.loads(provider.calls[0]["input"][0]["content"])
    assert request_payload["response_contract"] == RECOMMENDATION_GENERATION_JSON_SCHEMA
    assert "text" not in provider.calls[0]


def test_generator_rejects_menu_outside_evidence_pool_without_second_dispatch() -> None:
    output = {
        "status": "RECOMMENDED",
        "criteria_summary": "Korean and spicy",
        "recommendations": [
            _recommendation("dish-outside", 1, "chunk-cuisine", "chunk-flavor"),
        ],
        "unmatched_category_codes": [],
    }
    provider = FakeProvider(output)
    generator = RecommendationGenerator(Settings(), provider=provider)

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=[_pool_item("dish-a", "chunk-cuisine", "chunk-flavor")],
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert len(provider.calls) == 1


def test_generator_rejects_menu_fact_used_as_wiki_evidence() -> None:
    recommendation = _recommendation(
        "dish-a", 1, "chunk-cuisine", "chunk-flavor"
    )
    recommendation["wiki_evidence_ids"] = ["fact_dish_a_price"]
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": [recommendation],
            "unmatched_category_codes": [],
        }
    )
    pool_item = _pool_item("dish-a", "chunk-cuisine", "chunk-flavor")
    pool_item["menu_facts"] = [
        {
            "evidence_id": "fact_dish_a_price",
            "content": "Current base price: KRW 9,000.",
        }
    ]
    generator = RecommendationGenerator(Settings(), provider=provider)

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=[pool_item],
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert len(provider.calls) == 1


def test_generator_accepts_grounded_no_match_without_retry() -> None:
    provider = FakeProvider(
        {
            "status": "NO_MATCH",
            "criteria_summary": "No complete match",
            "recommendations": [],
            "unmatched_category_codes": ["flavors"],
        },
        structured_output=False,
    )
    generator = RecommendationGenerator(Settings(), provider=provider)

    result = generator.generate(
        criteria=_criteria(),
        soft_profile_context={},
        evidence_pool=[_pool_item("dish-a", "chunk-cuisine", "chunk-flavor")],
        locale="English",
    )

    assert result.status.value == "NO_MATCH"
    assert result.recommendations == []
    assert len(provider.calls) == 1
    assert "text" not in provider.calls[0]
