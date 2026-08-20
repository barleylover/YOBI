from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
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
    GeneratedMenuRecommendation,
    RecommendationGenerator,
    RecommendationGroundingRejectionCode,
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
            max_output_tokens=4096,
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
        return model == "openai.gpt-oss-120b"

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        return SimpleNamespace(output_text=json.dumps(self.output))


class RawTextProvider(FakeProvider):
    def __init__(self, raw_output: str) -> None:
        super().__init__({}, structured_output=False)
        self.raw_output = raw_output

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        return SimpleNamespace(output_text=self.raw_output)


class BlockingProvider(FakeProvider):
    def __init__(self, output: dict[str, Any]) -> None:
        super().__init__(output)
        self.release = Event()
        self.two_active = Event()
        self.third_entered = Event()
        self.lock = Lock()
        self.active = 0
        self.max_active = 0

    def create_response(self, model: str, **kwargs: Any) -> Any:
        with self.lock:
            self.calls.append({"model": model, **kwargs})
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == 2:
                self.two_active.set()
            if len(self.calls) == 3:
                self.third_entered.set()
        try:
            if not self.release.wait(timeout=2):
                raise RuntimeError("test provider release timed out")
            return SimpleNamespace(output_text=json.dumps(self.output))
        finally:
            with self.lock:
                self.active -= 1


class RateLimitedProvider(FakeProvider):
    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        raise GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True)


class UsageProvider(FakeProvider):
    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        return SimpleNamespace(
            output_text=json.dumps(self.output),
            usage=SimpleNamespace(
                input_tokens=1_234,
                output_tokens=456,
                total_tokens=1_690,
                input_tokens_details=SimpleNamespace(cached_tokens=100),
                output_tokens_details=SimpleNamespace(reasoning_tokens=200),
            ),
        )


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
        "merchant_id": f"merchant-{menu_id}",
        "base_price": 9_000,
        "spice_level": 3,
        "halal_certified": False,
        "vegan_status": "UNKNOWN",
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


def _pool_three() -> list[dict[str, Any]]:
    return [
        _pool_item(
            f"dish-{suffix}",
            f"chunk-{suffix}-cuisine",
            f"chunk-{suffix}-flavor",
        )
        for suffix in ("a", "b", "c")
    ]


def _recommendations_three(
    menu_ids: tuple[str, str, str] = ("dish-a", "dish-b", "dish-c"),
) -> list[dict[str, Any]]:
    return [
        _recommendation(
            menu_id,
            rank,
            f"chunk-{menu_id.removeprefix('dish-')}-cuisine",
            f"chunk-{menu_id.removeprefix('dish-')}-flavor",
        )
        for rank, menu_id in enumerate(menu_ids, start=1)
    ]


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
        "caution_codes": [],
    }


def test_v3_presentation_copy_enforces_sentence_ranges() -> None:
    payload = {
        **_recommendation("dish-a", 1, "chunk-a-cuisine", "chunk-a-flavor"),
        "localized_title": "Tteokbokki",
        "yobi_short_explanation": "Chewy rice cakes meet a bold sauce.",
        "yobi_long_explanation": (
            "This dish is built around chewy rice cakes. "
            "Its sauce brings the main flavor. It is commonly served warm."
        ),
        "review_summary": "Diners liked the texture. Some found the seasoning strong.",
    }

    assert GeneratedMenuRecommendation.model_validate(payload).localized_title == "Tteokbokki"

    with pytest.raises(ValueError, match="yobi_long_explanation"):
        GeneratedMenuRecommendation.model_validate(
            {**payload, "yobi_long_explanation": "Only one sentence."}
        )


def test_generator_dispatches_once_without_tools_and_allows_bounded_rerank() -> None:
    output = {
        "status": "RECOMMENDED",
        "criteria_summary": "Korean and spicy",
        "recommendations": _recommendations_three(("dish-c", "dish-a", "dish-b")),
        "unmatched_category_codes": [],
    }
    provider = FakeProvider(output)
    generator = RecommendationGenerator(Settings(), provider=provider)

    result = generator.generate(
        criteria=_criteria(),
        soft_profile_context={"nationality": "United States"},
        evidence_pool=_pool_three(),
        locale="English",
    )

    assert [item.menu_id for item in result.recommendations] == [
        "dish-c",
        "dish-a",
        "dish-b",
    ]
    assert len(provider.calls) == 1
    assert provider.calls[0]["model"] == "openai.gpt-oss-120b"
    assert provider.calls[0]["max_output_tokens"] == 2048
    assert "tools" not in provider.calls[0]
    instructions = str(provider.calls[0]["instructions"])
    assert "Return the JSON immediately without analysis or preamble." in instructions
    assert "This call performs SELECTION only" in instructions
    assert "do not write titles, explanations, review summaries" in instructions
    assert provider.calls[0]["text"]["format"]["strict"] is True
    request_payload = json.loads(provider.calls[0]["input"][0]["content"])
    assert request_payload["response_contract"] == provider.calls[0]["text"]["format"][
        "schema"
    ]
    item_properties = request_payload["response_contract"]["properties"][
        "recommendations"
    ]["items"]["properties"]
    assert "localized_title" not in item_properties
    assert "yobi_short_explanation" not in item_properties


def test_generator_supplies_json_contract_without_native_structured_output() -> None:
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": _recommendations_three(),
            "unmatched_category_codes": [],
        },
        structured_output=False,
    )
    generator = RecommendationGenerator(Settings(), provider=provider)

    generator.generate(
        criteria=_criteria(),
        soft_profile_context={},
        evidence_pool=_pool_three(),
        locale="English",
    )

    request_payload = json.loads(provider.calls[0]["input"][0]["content"])
    assert request_payload["response_contract"] == RECOMMENDATION_GENERATION_JSON_SCHEMA
    assert "text" not in provider.calls[0]


def test_generator_records_actual_usage_and_request_size_without_exposing_it_to_model() -> None:
    provider = UsageProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": _recommendations_three(),
            "unmatched_category_codes": [],
        }
    )
    result = RecommendationGenerator(Settings(), provider=provider).generate(
        criteria=_criteria(),
        soft_profile_context={},
        evidence_pool=_pool_three(),
        locale="English",
    )

    assert result.provider_metrics["input_tokens"] == 1_234
    assert result.provider_metrics["output_tokens"] == 456
    assert result.provider_metrics["reasoning_tokens"] == 200
    assert result.provider_metrics["request_utf8_bytes"] > 0
    assert result.provider_metrics["requested_max_output_tokens"] == 2048
    assert "provider_metrics" not in result.model_dump()


@pytest.mark.parametrize(
    ("raw_output", "expected_reason"),
    [
        ("not-json", RecommendationGroundingRejectionCode.INVALID_JSON),
        (
            json.dumps({"status": "RECOMMENDED"}),
            RecommendationGroundingRejectionCode.RESPONSE_SCHEMA_INVALID,
        ),
        (
            json.dumps(
                {
                    "status": "RECOMMENDED",
                    "criteria_summary": "Korean and spicy",
                    "recommendations": [
                        {**item, "rank": 3 - index}
                        for index, item in enumerate(_recommendations_three())
                    ],
                    "unmatched_category_codes": [],
                }
            ),
            RecommendationGroundingRejectionCode.RANK_ORDER_INVALID,
        ),
    ],
)
def test_generator_classifies_response_contract_rejections(
    raw_output: str,
    expected_reason: RecommendationGroundingRejectionCode,
) -> None:
    provider = RawTextProvider(raw_output)

    with pytest.raises(GenAIProviderError) as caught:
        RecommendationGenerator(Settings(), provider=provider).generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert caught.value.safe_reason_code == expected_reason.value
    assert caught.value.safe_reason_stage == "RESPONSE_CONTRACT"
    if expected_reason is RecommendationGroundingRejectionCode.INVALID_JSON:
        assert caught.value.safe_reason_detail is None
    else:
        assert caught.value.safe_reason_detail is not None
    assert len(provider.calls) == 1


def test_generator_rejects_menu_outside_evidence_pool_without_second_dispatch() -> None:
    output = {
        "status": "RECOMMENDED",
        "criteria_summary": "Korean and spicy",
        "recommendations": [
            _recommendation(
                "dish-outside", 1, "chunk-outside-cuisine", "chunk-outside-flavor"
            ),
            _recommendation("dish-b", 2, "chunk-b-cuisine", "chunk-b-flavor"),
            _recommendation("dish-c", 3, "chunk-c-cuisine", "chunk-c-flavor"),
        ],
        "unmatched_category_codes": [],
    }
    provider = FakeProvider(output)
    generator = RecommendationGenerator(Settings(), provider=provider)

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert (
        caught.value.safe_reason_code
        == RecommendationGroundingRejectionCode.MENU_OUTSIDE_SHORTLIST.value
    )
    assert len(provider.calls) == 1


def test_generator_rejects_duplicate_menu_ids_without_second_dispatch() -> None:
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": [
                _recommendation("dish-a", 1, "chunk-a-cuisine", "chunk-a-flavor"),
                _recommendation("dish-a", 2, "chunk-a-cuisine", "chunk-a-flavor"),
                _recommendation("dish-c", 3, "chunk-c-cuisine", "chunk-c-flavor"),
            ],
            "unmatched_category_codes": [],
        }
    )
    generator = RecommendationGenerator(Settings(), provider=provider)

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert (
        caught.value.safe_reason_code
        == RecommendationGroundingRejectionCode.DUPLICATE_MENU_ID.value
    )
    assert len(provider.calls) == 1


def test_generator_rejects_evidence_owned_by_another_menu() -> None:
    first = _recommendation(
        "dish-a", 1, "chunk-a-cuisine", "chunk-a-flavor"
    )
    first["matched_criteria"][0]["evidence_ids"] = ["chunk-b-cuisine"]
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": [first, *_recommendations_three()[1:]],
            "unmatched_category_codes": [],
        }
    )
    generator = RecommendationGenerator(Settings(), provider=provider)

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert (
        caught.value.safe_reason_code
        == RecommendationGroundingRejectionCode.CATEGORY_EVIDENCE_NOT_OWNED.value
    )
    assert len(provider.calls) == 1


def test_generator_enforces_three_merchants_when_shortlist_supports_it() -> None:
    pool = [*_pool_three(), _pool_item("dish-d", "chunk-d-cuisine", "chunk-d-flavor")]
    pool[1]["merchant_id"] = pool[0]["merchant_id"]
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": _recommendations_three(),
            "unmatched_category_codes": [],
        }
    )
    generator = RecommendationGenerator(Settings(), provider=provider)

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=pool,
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert (
        caught.value.safe_reason_code
        == RecommendationGroundingRejectionCode.MERCHANT_DIVERSITY_VIOLATION.value
    )
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("pool_update", "criteria_update", "expected_reason"),
    [
        (
            {"base_price": 12_000},
            {},
            RecommendationGroundingRejectionCode.PRICE_BAND_VIOLATION,
        ),
        (
            {"spice_level": 4},
            {},
            RecommendationGroundingRejectionCode.SPICE_LEVEL_VIOLATION,
        ),
        (
            {"halal_certified": False},
            {"dietary_filters": {"halal_certified_only": True, "vegan": False}},
            RecommendationGroundingRejectionCode.HALAL_CERTIFICATION_VIOLATION,
        ),
        (
            {"vegan_status": "CONFLICT"},
            {"dietary_filters": {"halal_certified_only": False, "vegan": True}},
            RecommendationGroundingRejectionCode.VEGAN_STATUS_VIOLATION,
        ),
    ],
)
def test_generator_rechecks_hard_constraints_after_model_selection(
    pool_update: dict[str, Any],
    criteria_update: dict[str, Any],
    expected_reason: RecommendationGroundingRejectionCode,
) -> None:
    pool = _pool_three()
    pool[0].update(pool_update)
    criteria = {**_criteria(), **criteria_update}
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": _recommendations_three(),
            "unmatched_category_codes": [],
        }
    )

    with pytest.raises(GenAIProviderError) as caught:
        RecommendationGenerator(Settings(), provider=provider).generate(
            criteria=criteria,
            soft_profile_context={},
            evidence_pool=pool,
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert caught.value.safe_reason_code == expected_reason.value
    assert len(provider.calls) == 1


def test_generator_rejects_selected_menu_without_wiki_evidence() -> None:
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": _recommendations_three(),
            "unmatched_category_codes": [],
        }
    )
    pool_item = _pool_item("dish-a", "chunk-a-cuisine", "chunk-a-flavor")
    pool_item["wiki_passages"] = []
    generator = RecommendationGenerator(Settings(), provider=provider)

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=[pool_item, *_pool_three()[1:]],
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert (
        caught.value.safe_reason_code
        == RecommendationGroundingRejectionCode.WIKI_EVIDENCE_NOT_AVAILABLE.value
    )
    assert len(provider.calls) == 1


def test_generator_rejects_model_no_match_after_server_freezes_candidates() -> None:
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

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.GROUNDING_REJECTED
    assert (
        caught.value.safe_reason_code
        == RecommendationGroundingRejectionCode.MODEL_RETURNED_NO_MATCH.value
    )
    assert len(provider.calls) == 1
    assert "text" not in provider.calls[0]


def test_generator_contract_requires_empty_unmatched_categories() -> None:
    assert RECOMMENDATION_GENERATION_JSON_SCHEMA["properties"][
        "unmatched_category_codes"
    ]["maxItems"] == 0
    provider = FakeProvider(
        {
            "status": "RECOMMENDED",
            "criteria_summary": "Korean and spicy",
            "recommendations": _recommendations_three(),
            "unmatched_category_codes": ["flavors"],
        },
        structured_output=False,
    )

    with pytest.raises(GenAIProviderError) as caught:
        RecommendationGenerator(Settings(), provider=provider).generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )

    assert caught.value.safe_reason_code == (
        RecommendationGroundingRejectionCode.UNMATCHED_CATEGORY_PRESENT.value
    )
    assert caught.value.safe_reason_stage == "SELECTION_POLICY"
    assert caught.value.safe_reason_detail == "unmatched_category_codes:too_long"


def test_comparison_uses_structured_model_cap_in_one_dispatch() -> None:
    provider = FakeProvider(
        {
            "summary": "Two grounded options.",
            "items": [
                {
                    "menu_id": menu_id,
                    "name": name,
                    "key_difference": difference,
                    "taste_texture": "Grounded taste and texture.",
                    "ingredients_form": "Specific ingredients are unverified.",
                    "spice_heaviness": "Spice is described by supplied evidence.",
                    "eating_context": "Suitable context depends on the diner.",
                    "best_for": "A diner comparing the supplied facts.",
                    "unverified_dietary_info": "Dietary details are unverified.",
                }
                for menu_id, name, difference in (
                    ("dish-a", "Choice A", "First grounded difference."),
                    ("dish-b", "Choice B", "Second grounded difference."),
                )
            ],
        }
    )
    generator = RecommendationGenerator(Settings(), provider=provider)

    result = generator.compare(
        evidence_items=[
            {"menu_id": "dish-a", "name": "Choice A"},
            {"menu_id": "dish-b", "name": "Choice B"},
        ],
        locale="English",
    )

    assert [item.menu_id for item in result.items] == ["dish-a", "dish-b"]
    assert len(provider.calls) == 1
    assert provider.calls[0]["model"] == "openai.gpt-oss-120b"
    assert provider.calls[0]["max_output_tokens"] == 2048


def test_structured_rate_limit_never_retries_or_dispatches_fallback_model() -> None:
    provider = RateLimitedProvider({})
    generator = RecommendationGenerator(
        Settings(
            llm_max_retries=3,
            oci_genai_fallback_model="automatic-fallback-must-not-run",
        ),
        provider=provider,
    )

    with pytest.raises(GenAIProviderError) as caught:
        generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )

    assert caught.value.code is GenAIErrorCode.RATE_LIMIT
    assert caught.value.safe_metadata["request_utf8_bytes"] > 0
    assert caught.value.safe_metadata["requested_max_output_tokens"] == 2048
    assert [call["model"] for call in provider.calls] == ["openai.gpt-oss-120b"]


def test_structured_concurrency_setting_limits_provider_dispatches_to_two() -> None:
    output = {
        "status": "RECOMMENDED",
        "criteria_summary": "Korean and spicy",
        "recommendations": _recommendations_three(),
        "unmatched_category_codes": [],
    }
    provider = BlockingProvider(output)
    generator = RecommendationGenerator(
        Settings(structured_recommendation_max_concurrent_requests=2),
        provider=provider,
    )

    def generate_once() -> list[str]:
        result = generator.generate(
            criteria=_criteria(),
            soft_profile_context={},
            evidence_pool=_pool_three(),
            locale="English",
        )
        return [item.menu_id for item in result.recommendations]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(generate_once) for _ in range(3)]
        try:
            assert provider.two_active.wait(timeout=1)
            assert not provider.third_entered.wait(timeout=0.1)
        finally:
            provider.release.set()
        results = [future.result(timeout=2) for future in futures]

    assert results == [["dish-a", "dish-b", "dish-c"]] * 3
    assert provider.max_active == 2
    assert len(provider.calls) == 3


@pytest.mark.parametrize("value", [0, 9])
def test_structured_concurrency_setting_rejects_out_of_bounds(value: int) -> None:
    with pytest.raises(ValueError):
        Settings(structured_recommendation_max_concurrent_requests=value)
