from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.domain.models import (
    CountryAwareMenuPresentationCacheEntry,
    EvidenceStatus,
    MenuPresentationCacheEntry,
    MenuSummary,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
    OptionGroup,
    OptionItem,
    RuntimeMenuSourceDescriptionLocalizationEntry,
)
from app.domain.recommendation_copy import deterministic_presentation_copy
from app.domain.structured_recommendation import EvidencePoolItem
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)
from app.genai.presentation_generator import (
    MENU_PRESENTATION_JSON_SCHEMA,
    MenuPresentationGenerator,
    _english_title_coverage_is_sufficient,
)
from app.services.menu_presentation import (
    MenuPresentationService,
    deterministic_localized_source_description,
    deterministic_localized_subtitle,
)


class PresentationRepository:
    def __init__(
        self,
        page: MerchantMenuPresentationPage,
        *,
        options: list[OptionGroup] | None = None,
    ) -> None:
        self.page = page
        self.options = options or []
        self.cache: dict[str, MenuPresentationCacheEntry] = {}
        self.country_cache: dict[str, CountryAwareMenuPresentationCacheEntry] = {}
        self.runtime_sources: dict[
            tuple[str, str, str, str, str],
            RuntimeMenuSourceDescriptionLocalizationEntry,
        ] = {}
        self.leases: dict[str, str] = {}
        self.lock = Lock()
        self.saved_option_localizations: list[
            tuple[str, str, dict[str, str], dict[str, str], str]
        ] = []
        self.saved_menu_localizations: list[
            tuple[str, str, str | None, str | None, str, str]
        ] = []

    def list_merchant_menu_presentations(
        self,
        session_id: str,
        merchant_id: str,
        request: MerchantMenuPresentationRequest,
    ) -> MerchantMenuPresentationPage:
        del session_id, merchant_id, request
        return self.page

    def get_menu_presentation_cache(self, cache_key: str) -> MenuPresentationCacheEntry | None:
        with self.lock:
            return self.cache.get(cache_key)

    def save_menu_presentation_cache_entry(self, entry: MenuPresentationCacheEntry) -> None:
        with self.lock:
            self.cache.setdefault(entry.cache_key, entry)

    def get_country_aware_menu_presentation_cache(
        self, cache_key: str
    ) -> CountryAwareMenuPresentationCacheEntry | None:
        return self.country_cache.get(cache_key)

    def save_country_aware_menu_presentation_cache_entry(
        self, entry: CountryAwareMenuPresentationCacheEntry
    ) -> None:
        self.country_cache.setdefault(entry.cache_key, entry)

    def get_runtime_menu_source_description_localization(
        self,
        release_id: str,
        menu_id: str,
        language_code: str,
        prompt_version: str,
        source_hash: str,
    ) -> RuntimeMenuSourceDescriptionLocalizationEntry | None:
        return self.runtime_sources.get(
            (release_id, menu_id, language_code, prompt_version, source_hash)
        )

    def save_runtime_menu_source_description_localization(
        self, entry: RuntimeMenuSourceDescriptionLocalizationEntry
    ) -> None:
        self.runtime_sources[
            (
                entry.release_id,
                entry.menu_id,
                entry.language_code,
                entry.prompt_version,
                entry.source_hash,
            )
        ] = entry

    def get_session(self, session_id: str) -> Any:
        del session_id
        return SimpleNamespace(profile_id="profile-1")

    def get_profile(self, profile_id: str) -> Any:
        del profile_id
        return SimpleNamespace(preferred_language="English", country_code="US")

    def acquire_menu_presentation_lease(self, cache_key: str, owner_token: str, **_: Any) -> bool:
        with self.lock:
            if cache_key in self.leases:
                return False
            self.leases[cache_key] = owner_token
            return True

    def finish_menu_presentation_lease(
        self, cache_key: str, owner_token: str, *, error_code: str | None = None
    ) -> None:
        with self.lock:
            if error_code is None and self.leases.get(cache_key) == owner_token:
                self.leases.pop(cache_key, None)

    def get_options(self, menu_id: str, session_id: str | None = None) -> list[OptionGroup]:
        del menu_id, session_id
        return self.options

    def save_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        group_names: dict[str, str],
        item_names: dict[str, str],
        model_id: str,
    ) -> None:
        self.saved_option_localizations.append(
            (session_id, menu_id, group_names, item_names, model_id)
        )

    def save_menu_runtime_localizations(
        self,
        session_id: str,
        menu_id: str,
        localized_title: str | None,
        localized_source_description: str | None,
        model_id: str,
        prompt_version: str,
    ) -> None:
        self.saved_menu_localizations.append(
            (
                session_id,
                menu_id,
                localized_title,
                localized_source_description,
                model_id,
                prompt_version,
            )
        )


class BrokenCacheRepository(PresentationRepository):
    def __init__(
        self,
        page: MerchantMenuPresentationPage,
        *,
        fail_read: bool = False,
        fail_write: bool = False,
    ) -> None:
        super().__init__(page)
        self.fail_read = fail_read
        self.fail_write = fail_write

    def get_menu_presentation_cache(self, cache_key: str) -> MenuPresentationCacheEntry | None:
        if self.fail_read:
            raise RuntimeError("CACHE_READ_UNAVAILABLE")
        return super().get_menu_presentation_cache(cache_key)

    def save_menu_presentation_cache_entry(self, entry: MenuPresentationCacheEntry) -> None:
        if self.fail_write:
            raise RuntimeError("CACHE_WRITE_UNAVAILABLE")
        super().save_menu_presentation_cache_entry(entry)


class PresentationProvider:
    configured = True
    capabilities = ProviderCapabilities(
        provider="fake",
        serving_mode=GenAIServingMode.ON_DEMAND,
        responses_api=True,
        function_calling=True,
        structured_output=True,
        native_streaming=False,
        client_managed_continuation=True,
        server_managed_continuation=False,
        max_input_tokens=32_768,
        max_output_tokens=8_192,
        max_tools_per_request=4,
        max_tool_calls_per_response=4,
    )

    def __init__(
        self,
        *,
        rate_limit_primary: bool = False,
        output: str | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.rate_limit_primary = rate_limit_primary
        self.output = output
        self.delay_seconds = delay_seconds
        self.calls: list[str] = []
        self.requested_ids: list[list[str]] = []
        self.requests: list[dict[str, Any]] = []

    def supports_model(self, model: str) -> bool:
        return model in {"xai.grok-4.3", "openai.gpt-oss-120b"}

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append(model)
        self.requests.append(kwargs)
        if self.rate_limit_primary and model == "xai.grok-4.3":
            raise GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        request_payload = json.loads(str(kwargs["input"][0]["content"]))
        menu_ids = [str(item["menu_id"]) for item in request_payload["menus"]]
        self.requested_ids.append(menu_ids)
        output = self.output or json.dumps(_generated_payload(menu_ids))
        return SimpleNamespace(output_text=output)


class SplitOnBatchProvider(PresentationProvider):
    def create_response(self, model: str, **kwargs: Any) -> Any:
        request_payload = json.loads(str(kwargs["input"][0]["content"]))
        menu_ids = [str(item["menu_id"]) for item in request_payload["menus"]]
        self.calls.append(model)
        self.requested_ids.append(menu_ids)
        if len(menu_ids) > 1:
            return SimpleNamespace(output_text='{"items":')
        return SimpleNamespace(output_text=json.dumps(_generated_payload(menu_ids)))


class TruncatingPresentationProvider(PresentationProvider):
    def __init__(self, *, grok_truncations: int) -> None:
        super().__init__()
        self.grok_truncations = grok_truncations
        self.grok_calls = 0

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append(model)
        self.requests.append(kwargs)
        request_payload = json.loads(str(kwargs["input"][0]["content"]))
        menu_ids = [str(item["menu_id"]) for item in request_payload["menus"]]
        self.requested_ids.append(menu_ids)
        if model == "xai.grok-4.3":
            self.grok_calls += 1
            if self.grok_calls <= self.grok_truncations:
                return SimpleNamespace(
                    status="incomplete",
                    incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                    output_text='{"items":',
                    usage=SimpleNamespace(input_tokens=1_000, output_tokens=4_096),
                )
        return SimpleNamespace(
            status="completed",
            incomplete_details=None,
            output_text=json.dumps(_generated_payload(menu_ids)),
            usage=SimpleNamespace(input_tokens=1_000, output_tokens=1_500),
        )


class AlwaysRateLimitedPresentationProvider(PresentationProvider):
    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append(model)
        self.requests.append(kwargs)
        raise GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True)


def _menu() -> MenuSummary:
    return MenuSummary(
        menu_id="menu-1",
        merchant_id="merchant-1",
        merchant_name="Restaurant",
        name_en="Rice Cake",
        name_ko="떡볶이",
        category="Korean",
        description="요기요 원문",
        cultural_description="",
        price=12_000,
        delivery_fee=2_000,
        eta_min=25,
        eta_max=35,
        dietary_summary="",
        evidence_status=EvidenceStatus.UNKNOWN,
        match_reasons=[],
        risk_hints=[],
        semantic_score=0.5,
    )


def _presentation(
    menu_id: str = "menu-1",
    *,
    localized_title: str = "Tteokbokki",
    source_description: str = "요기요 원문",
    language_code: str = "en",
    country_code: str = "US",
) -> MerchantMenuPresentation:
    menu = _menu().model_copy(
        update={
            "menu_id": menu_id,
            "name_ko": f"떡볶이 {menu_id}",
            "description": source_description,
        }
    )
    return MerchantMenuPresentation(
        menu=menu,
        localized_title=localized_title,
        yobi_short_explanation="Wiki passage one.",
        yobi_long_explanation="Wiki passage one. Wiki passage two.",
        source_description=source_description,
        review_summary="The texture was chewy. The portion felt generous.",
        country_preference={
            "country_code": country_code,
            "preference_percent": 78,
            "sample_size": 420,
        },
        evidence_ids=["wiki-1", "wiki-2"],
        review_ids=["review-1", "review-2"],
        generation_model="DETERMINISTIC_GROUNDED_FALLBACK",
        release_id="release-1",
        language_code=language_code,  # type: ignore[arg-type]
        evidence_map={
            "wiki_passages": [
                {
                    "evidence_id": "wiki-1",
                    "evidence_type": "WIKI_PASSAGE",
                    "content": "Rice cakes are chewy.",
                },
                {
                    "evidence_id": "wiki-2",
                    "evidence_type": "WIKI_PASSAGE",
                    "content": "The dish is served with sauce.",
                },
            ],
            "menu_facts": [],
            "synthetic_reviews": [
                {
                    "review_id": "review-1",
                    "topic": "TEXTURE",
                    "rating": 5,
                    "review_text": "Chewy texture.",
                },
                {
                    "review_id": "review-2",
                    "topic": "PORTION",
                    "rating": 4,
                    "review_text": "Generous portion.",
                },
            ],
            "source_identity": {"knowledge_release_id": "knowledge-1"},
        },
    )


def _generated_payload(menu_ids: list[str] | None = None) -> dict[str, Any]:
    ids = menu_ids or ["menu-1"]
    return {
        "items": [
            {
                "menu_id": menu_id,
                "localized_title": "Tteokbokki",
                "localized_subtitle": "Chewy Korean rice cakes in sauce",
                "localized_source_description": "Chewy rice cakes cooked to order.",
                "yobi_short_explanation": (
                    "Think of chewy rice cakes in a warm Korean sauce. It is an easy dish to share."
                ),
                "yobi_long_explanation": (
                    "Tteokbokki centers on chewy rice cakes. "
                    "The supplied Wiki describes a warm sauce. "
                    "Its bite is soft and springy. "
                    "This listing keeps the familiar rice-cake format."
                ),
                "review_summary": (
                    "Reviewers liked the chewy texture. They also found the portion generous."
                ),
                "used_evidence_ids": ["wiki-1", "wiki-2", "review-1", "review-2"],
                "used_source_fields": [
                    "menu_title_ko",
                    "localized_title",
                    "source_description_ko",
                    "wiki_passages",
                    "synthetic_reviews",
                ],
                "yobi_used_evidence_ids": ["wiki-1", "wiki-2"],
                "review_used_ids": ["review-1", "review-2"],
                "yobi_used_source_fields": [
                    "menu_title_ko",
                    "localized_title",
                    "source_description_ko",
                    "wiki_passages",
                ],
                "review_used_source_fields": ["synthetic_reviews"],
                "personalization_applied": False,
                "covered_component_ids": [],
                "component_mentions": [],
                "option_group_localizations": [],
                "option_item_localizations": [],
            }
            for menu_id in ids
        ]
    }


def _presentation_validation_reason(
    payload: dict[str, Any],
    presentation: MerchantMenuPresentation | None = None,
    *,
    locale: str = "English",
) -> str | None:
    provider = PresentationProvider(output=json.dumps(payload))
    generator = MenuPresentationGenerator(Settings(), provider=provider)
    with pytest.raises(GenAIProviderError) as raised:
        generator.generate(
            items=[MenuPresentationService._generation_payload(presentation or _presentation())],
            locale=locale,
        )
    return raised.value.safe_reason_code


def _generate_presentation(
    payload: dict[str, Any],
    presentation: MerchantMenuPresentation | None = None,
    *,
    locale: str = "English",
):
    provider = PresentationProvider(output=json.dumps(payload))
    return MenuPresentationGenerator(Settings(), provider=provider).generate(
        items=[MenuPresentationService._generation_payload(presentation or _presentation())],
        locale=locale,
    )


def test_menu_presentation_uses_grok_once_and_caches_structured_copy() -> None:
    repository = PresentationRepository(
        MerchantMenuPresentationPage(items=[_presentation()], next_cursor="menu-1")
    )
    provider = PresentationProvider()
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.calls == ["xai.grok-4.3"]
    assert page.items[0].generation_model == "xai.grok-4.3"
    assert page.next_cursor == "menu-1"
    assert len(repository.cache) == 1
    second = service.list_presentations(
        "session-1", "merchant-1", MerchantMenuPresentationRequest()
    )
    assert second.items == page.items
    assert provider.calls == ["xai.grok-4.3"]


def test_presentation_request_uses_compact_model_owned_schema_and_output_cap() -> None:
    provider = PresentationProvider()
    generator = MenuPresentationGenerator(Settings(), provider=provider)

    generator.generate(
        items=[MenuPresentationService._generation_payload(_presentation())],
        locale="English",
    )

    request = provider.requests[0]
    assert request["max_output_tokens"] == 4096
    assert request["text"]["format"]["schema"] == MENU_PRESENTATION_JSON_SCHEMA
    properties = MENU_PRESENTATION_JSON_SCHEMA["properties"]["items"]["items"][
        "properties"
    ]
    assert set(properties) == {
        "menu_id",
        "localized_subtitle",
        "localized_source_description",
        "yobi_short_explanation",
        "yobi_long_explanation",
        "review_summary",
        "personalization_applied",
        "covered_component_ids",
        "component_mentions",
    }
    input_payload = json.loads(request["input"][0]["content"])
    assert "evidence_type" not in input_payload["menus"][0]["wiki_passages"][0]
    instructions = str(request["instructions"])
    assert "prioritize supported taste, perceived heat, how it is commonly eaten" in instructions
    assert 'gopbaegi as "extra-large portion"' in instructions
    assert 'jeon as "savory Korean pancake"' in instructions
    assert "dosirak" in instructions and '"Korean lunchbox"' in instructions
    assert "Avoid encyclopedic taxonomy" in instructions


def test_presentation_retries_explicit_output_truncation_once_with_double_limit() -> None:
    provider = TruncatingPresentationProvider(grok_truncations=1)
    attempts: list[tuple[str, str | None, dict[str, int]]] = []

    result = MenuPresentationGenerator(Settings(), provider=provider).generate(
        items=[MenuPresentationService._generation_payload(_presentation())],
        locale="English",
        on_provider_attempt=lambda _attempt, _model, status, error, _latency, usage: (
            attempts.append((status, error, usage))
        ),
    )

    assert provider.calls == ["xai.grok-4.3", "xai.grok-4.3"]
    assert [request["max_output_tokens"] for request in provider.requests] == [4_096, 8_192]
    assert [attempt[:2] for attempt in attempts] == [
        ("FAILED", "OUTPUT_TRUNCATED_MAX_OUTPUT_TOKENS"),
        ("SUCCEEDED", None),
    ]
    assert result.generation_model == "xai.grok-4.3"
    assert result.provider_metrics["requested_max_output_tokens"] == 8_192


def test_presentation_uses_gpt_oss_after_grok_exhausts_truncation_retry() -> None:
    provider = TruncatingPresentationProvider(grok_truncations=2)

    result = MenuPresentationGenerator(Settings(), provider=provider).generate(
        items=[MenuPresentationService._generation_payload(_presentation())],
        locale="English",
    )

    assert provider.calls == [
        "xai.grok-4.3",
        "xai.grok-4.3",
        "openai.gpt-oss-120b",
    ]
    assert [request["max_output_tokens"] for request in provider.requests] == [
        4_096,
        8_192,
        4_096,
    ]
    assert result.generation_model == "openai.gpt-oss-120b"


def test_presentation_translates_card_fields_without_option_localization() -> None:
    options = [
        OptionGroup(
            option_group_id="group-1",
            name_en="legacy romanization",
            name_ko="음료 추가선택",
            description="",
            required=False,
            min_select=0,
            max_select=1,
            items=[
                OptionItem(
                    option_item_id="item-1",
                    name_en="legacy romanization",
                    name_ko="코카콜라 355ml 추가",
                    description="",
                    price_delta=2000,
                    available=True,
                )
            ],
        )
    ]
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_title": "Tteokbokki",
            "localized_subtitle": "Chewy rice cakes in a spicy Korean sauce",
            "localized_source_description": "Fresh rice cakes cooked to order.",
            "option_group_localizations": [],
            "option_item_localizations": [],
            "used_source_fields": [
                "menu_title_ko",
                "localized_title",
                "source_description_ko",
                "wiki_passages",
                "synthetic_reviews",
            ],
        }
    )
    repository = PresentationRepository(
        MerchantMenuPresentationPage(items=[_presentation()]), options=options
    )
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].localized_title == "Tteokbokki"
    assert page.items[0].source_description == "Fresh rice cakes cooked to order."
    assert repository.saved_option_localizations == []
    assert repository.saved_menu_localizations[0][2:4] == (
        "Tteokbokki",
        "Fresh rice cakes cooked to order.",
    )
    assert len(repository.cache) == 1


def test_presentation_ignores_option_localizations_from_card_model() -> None:
    options = [
        OptionGroup(
            option_group_id="group-1",
            name_en="legacy",
            name_ko="조리, 비조리 선택",
            description="",
            required=True,
            min_select=1,
            max_select=1,
            items=[
                OptionItem(
                    option_item_id="item-1",
                    name_en="legacy",
                    name_ko="비조리 선택",
                    description="",
                    price_delta=0,
                    available=True,
                )
            ],
        )
    ]
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "option_group_localizations": [
                {"object_id": "group-1", "display_name": "Jori, bijori seontaek"}
            ],
            "option_item_localizations": [
                {"object_id": "item-1", "display_name": "Bijori seontaek"}
            ],
            "used_source_fields": [
                "menu_title_ko",
                "localized_title",
                "source_description_ko",
                "wiki_passages",
                "synthetic_reviews",
                "menu_options",
            ],
        }
    )
    repository = PresentationRepository(
        MerchantMenuPresentationPage(items=[_presentation()]), options=options
    )
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3+SAFE_FIELD_FALLBACK"
    assert len(repository.cache) == 1
    assert page.items[0].evidence_map["safe_field_fallbacks"] == ["option_localizations"]
    assert repository.saved_option_localizations == []


def test_presentation_canonicalizes_changed_title_without_discarding_grok_copy() -> None:
    payload = _generated_payload()
    payload["items"][0]["localized_title"] = "Tteokbokki!!!"
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].localized_title == "Tteokbokki"
    assert page.items[0].yobi_short_explanation == payload["items"][0]["yobi_short_explanation"]
    assert page.items[0].generation_model == "xai.grok-4.3+SAFE_FIELD_FALLBACK"
    assert page.items[0].evidence_map["safe_field_fallbacks"] == ["localized_title"]
    assert len(repository.cache) == 1


def test_phonetic_yogiyo_description_uses_safe_field_fallback_and_caches_other_copy() -> None:
    source = "싱싱한 생 바지락으로 우려낸 깊은 육수와 정성으로 빚은 생면"
    payload = _generated_payload()
    payload["items"][0]["localized_source_description"] = (
        "Singsinghan saeng bajirageuro uryeonaen gipeun yuksuwa jeongseongeuro biteun saengmyeon"
    )
    repository = PresentationRepository(
        MerchantMenuPresentationPage(items=[_presentation(source_description=source)])
    )
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3+SAFE_FIELD_FALLBACK"
    assert page.items[0].source_description == ""
    assert len(repository.cache) == 1
    assert repository.saved_menu_localizations[0][3] is None
    cached = next(iter(repository.cache.values()))
    assert "localized_source_description" not in cached.evidence_map


def test_english_presentation_replaces_only_the_hangul_field() -> None:
    payload = _generated_payload()
    payload["items"][0]["yobi_short_explanation"] = "떡볶이 설명입니다."

    generated = _generate_presentation(payload)

    assert generated.items[0].yobi_short_explanation == ""
    assert generated.items[0].yobi_long_explanation
    assert generated.field_fallbacks["menu-1"] == ["yobi_short_explanation"]


def test_japanese_presentation_replaces_only_romanized_prose() -> None:
    payload = _generated_payload()
    payload["items"][0]["localized_title"] = "トッポッキ"
    presentation = _presentation(localized_title="トッポッキ", language_code="ja")

    generated = _generate_presentation(payload, presentation, locale="日本語")

    assert generated.items[0].localized_subtitle == ""
    assert "localized_subtitle" in generated.field_fallbacks["menu-1"]


def test_presentation_accepts_title_repeated_as_a_safe_subtitle() -> None:
    payload = _generated_payload()
    payload["items"][0]["localized_subtitle"] = "Tteokbokki"

    generated = _generate_presentation(payload)

    assert generated.items[0].localized_subtitle == "Tteokbokki"


def test_presentation_omitted_non_identity_fields_use_safe_field_fallbacks() -> None:
    payload = _generated_payload()
    for field_name in (
        "localized_subtitle",
        "yobi_short_explanation",
        "yobi_long_explanation",
        "review_summary",
        "used_source_fields",
        "yobi_used_source_fields",
    ):
        payload["items"][0].pop(field_name)

    generated = _generate_presentation(payload)

    assert generated.items[0].localized_title == "Tteokbokki"
    assert generated.field_fallbacks["menu-1"] == [
        "localized_subtitle",
        "review_summary",
        "yobi_long_explanation",
        "yobi_short_explanation",
    ]
    assert generated.items[0].used_source_fields
    assert generated.items[0].yobi_used_source_fields


def test_presentation_accepts_natural_copy_without_token_overlap_rejection() -> None:
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_title": "Nakji Kimchi Bibimbap",
            "localized_subtitle": "A Korean mixed rice bowl",
            "yobi_short_explanation": (
                "Bibimbap combines rice and seasoned vegetables. It is mixed before eating."
            ),
            "yobi_long_explanation": (
                "Bibimbap is a Korean rice bowl. Vegetables are arranged over the rice. "
                "The bowl is mixed before eating. Its exact toppings depend on the listing."
            ),
        }
    )
    presentation = _presentation(localized_title="Nakji Kimchi Bibimbap")

    generated = _generate_presentation(payload, presentation)

    assert generated.items[0].yobi_short_explanation.startswith("Bibimbap")


def test_title_coverage_accepts_grounded_natural_copy_without_exact_token_echo() -> None:
    assert _english_title_coverage_is_sufficient(
        "Italian Cheese Pizza (L)",
        "A cheese pizza with a baked crust",
    )
    assert _english_title_coverage_is_sufficient(
        "Original Shrimp Aglio Olio Pasta (Slightly Spicy)",
        "Shrimp pasta with garlic, olive oil and mild heat",
    )
    assert not _english_title_coverage_is_sufficient(
        "Original Shrimp Aglio Olio Pasta (Slightly Spicy)",
        "An Italian pasta served with a classic sauce",
    )


def test_presentation_does_not_require_restaurant_copy_to_be_repeated_in_yobi_copy() -> None:
    payload = _generated_payload()
    payload["items"][0]["localized_source_description"] = "Tender octopus with crisp kimchi."

    generated = _generate_presentation(payload)

    assert generated.items[0].localized_source_description == "Tender octopus with crisp kimchi."


def test_presentation_replaces_review_leakage_only_in_yobi_fields() -> None:
    payload = _generated_payload()
    payload["items"][0]["yobi_short_explanation"] = (
        "Reviewers found the chewy rice cakes balanced and easy to enjoy."
    )

    generated = _generate_presentation(payload)

    assert generated.items[0].yobi_short_explanation == ""
    assert generated.items[0].yobi_long_explanation == ""
    assert generated.items[0].review_summary


def test_presentation_canonicalizes_review_ids_and_sources_claimed_for_yobi_copy() -> None:
    payload = _generated_payload()
    payload["items"][0]["yobi_used_evidence_ids"] = ["review-1"]

    generated = _generate_presentation(payload)
    assert generated.items[0].yobi_used_evidence_ids == ["wiki-1", "wiki-2"]

    payload = _generated_payload()
    payload["items"][0]["yobi_used_source_fields"].append("synthetic_reviews")
    generated = _generate_presentation(payload)
    assert "synthetic_reviews" not in generated.items[0].yobi_used_source_fields


def test_presentation_canonicalizes_missing_model_provenance_metadata() -> None:
    payload = _generated_payload()
    payload["items"][0]["used_source_fields"] = ["localized_title"]
    payload["items"][0]["yobi_used_source_fields"] = ["localized_title"]
    payload["items"][0]["review_used_source_fields"] = []
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3"
    assert page.items[0].evidence_map["yobi_used_source_fields"] == [
        "localized_title",
        "menu_title_ko",
        "source_description_ko",
        "wiki_passages",
    ]
    assert page.items[0].evidence_map["review_used_source_fields"] == ["synthetic_reviews"]
    assert page.items[0].evidence_map["used_source_fields"] == [
        "localized_title",
        "menu_title_ko",
        "source_description_ko",
        "synthetic_reviews",
        "wiki_passages",
    ]


def test_presentation_accepts_spelled_quantity_when_value_is_unchanged() -> None:
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_source_description": "Beef fried rice, one serving.",
            "localized_subtitle": "Tteokbokki served with beef fried rice",
            "yobi_short_explanation": (
                "Tteokbokki keeps its chewy rice cakes beside beef fried rice. "
                "The listing is for one serving."
            ),
            "yobi_long_explanation": (
                "Tteokbokki centers on chewy rice cakes. "
                "This listing pairs them with beef fried rice. "
                "The restaurant describes one serving. "
                "The supplied Wiki explains the rice-cake format."
            ),
        }
    )
    repository = PresentationRepository(
        MerchantMenuPresentationPage(
            items=[_presentation(source_description="소고기 볶음밥 1인분")]
        )
    )
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3"
    assert page.items[0].source_description == "Beef fried rice, one serving."
    assert len(repository.cache) == 1


def test_presentation_accepts_spelled_spice_count_in_source_translation() -> None:
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_source_description": "Garlic coated in five-spice seasoning.",
            "localized_subtitle": "Tteokbokki with five-spice garlic",
            "yobi_short_explanation": (
                "Tteokbokki keeps chewy rice cakes beside aromatic garlic. "
                "The five-spice seasoning adds a layered savory aroma."
            ),
            "yobi_long_explanation": (
                "Tteokbokki centers on chewy rice cakes in sauce. "
                "This restaurant seasons fried garlic with five spices. "
                "The garlic adds aroma and crisp texture. "
                "The supplied Wiki explains the rice-cake format."
            ),
        }
    )
    repository = PresentationRepository(
        MerchantMenuPresentationPage(
            items=[_presentation(source_description="5가지 향신료를 입힌 마늘")]
        )
    )
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3"
    assert page.items[0].source_description == "Garlic coated in five-spice seasoning."
    assert len(repository.cache) == 1


def test_presentation_accepts_one_sentence_review_summary() -> None:
    payload = _generated_payload()
    payload["items"][0]["review_summary"] = "Reviewers liked the chewy texture."
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3"
    assert page.items[0].review_summary == "Reviewers liked the chewy texture."


def test_presentation_replaces_only_yogiyo_translation_with_changed_quantities() -> None:
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_source_description": "Coca-Cola with 3 dumplings.",
            "localized_subtitle": "Tteokbokki with Coca-Cola and dumplings",
            "yobi_short_explanation": (
                "Tteokbokki comes with Coca-Cola and dumplings. The rice cakes remain central."
            ),
            "yobi_long_explanation": (
                "Tteokbokki centers on chewy rice cakes. Coca-Cola is included. "
                "Dumplings accompany the dish. The exact bundle follows the restaurant listing."
            ),
        }
    )
    presentation = _presentation(source_description="코카콜라 355ml 2개")

    generated = _generate_presentation(payload, presentation)

    assert generated.items[0].localized_source_description == ""
    assert generated.items[0].yobi_short_explanation
    assert generated.field_fallbacks["menu-1"] == ["localized_source_description"]


def test_quantity_failure_isolated_to_one_menu_in_provider_batch() -> None:
    presentations = [
        _presentation("menu-1"),
        _presentation("menu-2", source_description="코카콜라 355ml 2개"),
        _presentation("menu-3"),
    ]
    payload = _generated_payload([item.menu.menu_id for item in presentations])
    payload["items"][1].update(
        {
            "localized_source_description": "Coca-Cola 355ml with 3 dumplings.",
            "localized_subtitle": "Tteokbokki with Coca-Cola and dumplings",
            "yobi_short_explanation": (
                "Tteokbokki comes with Coca-Cola and dumplings. The rice cakes remain central."
            ),
            "yobi_long_explanation": (
                "Tteokbokki centers on chewy rice cakes. "
                "Coca-Cola is included. Dumplings accompany the dish. "
                "The exact bundle follows the restaurant listing."
            ),
        }
    )
    repository = PresentationRepository(MerchantMenuPresentationPage(items=presentations))
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.requested_ids == [["menu-1", "menu-2", "menu-3"]]
    assert [item.generation_model for item in page.items] == [
        "xai.grok-4.3",
        "xai.grok-4.3+SAFE_FIELD_FALLBACK",
        "xai.grok-4.3",
    ]
    assert {entry[1] for entry in repository.saved_menu_localizations} == {
        "menu-1",
        "menu-2",
        "menu-3",
    }
    assert len(repository.cache) == 3


def test_sentence_count_variation_does_not_reject_a_menu() -> None:
    presentations = [_presentation(f"menu-{index}") for index in range(1, 4)]
    payload = _generated_payload([item.menu.menu_id for item in presentations])
    payload["items"][1]["review_summary"] = "One. Two. Three. Four."
    repository = PresentationRepository(MerchantMenuPresentationPage(items=presentations))
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert all(item.generation_model == "xai.grok-4.3" for item in page.items)
    assert len(repository.cache) == 3


def test_menu_presentation_rate_limit_falls_back_to_gpt_oss_and_caches_copy() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = PresentationProvider(rate_limit_primary=True)
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.calls == ["xai.grok-4.3", "openai.gpt-oss-120b"]
    assert page.items[0].generation_model == "openai.gpt-oss-120b"
    assert len(repository.cache) == 1


def test_menu_presentation_uses_deterministic_copy_after_both_models_rate_limit() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = AlwaysRateLimitedPresentationProvider()
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.calls == ["xai.grok-4.3", "openai.gpt-oss-120b"]
    assert page.items[0].generation_model == "DETERMINISTIC_GROUNDED_FALLBACK"
    assert repository.cache == {}


def test_selected_menu_fallback_keeps_validated_target_language_yogiyo_copy() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[]))
    service = MenuPresentationService(repository, Settings())  # type: ignore[arg-type]
    item = EvidencePoolItem(
        menu=_menu(),
        knowledge_release_id="knowledge-1",
        catalog_release_id="catalog-1",
        recommendation_release_family_id="family-1",
        localized_title="Tteokbokki",
        localized_source_description="Chewy rice cakes cooked to order.",
    )

    presented = service.present_selected(
        [item], session_id="session-1", language_code="en", country_code="US"
    )

    assert presented["menu-1"].source_description == "Chewy rice cakes cooked to order."


def _country_aware_item(
    *,
    spice_country: str,
    representative_dish: str,
    localized_source_description: str | None = None,
) -> EvidencePoolItem:
    return EvidencePoolItem(
        menu=_menu(),
        knowledge_release_id="knowledge-1",
        catalog_release_id="catalog-1",
        recommendation_release_family_id="family-1",
        synthetic_enrichment_release_id="release-1",
        localized_title="Tteokbokki",
        localized_source_description=localized_source_description,
        synthetic_spice_level=4,
        country_spice_baseline=3,
        spice_reference_country_code=spice_country,
        spice_reference_dish_en=representative_dish,
        country_preference={
            "country_code": spice_country,
            "preference_percent": 71,
            "sample_size": 220,
        },
    )


def test_country_aware_us_and_gb_caches_are_separate_but_source_translation_is_reused() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[]))
    provider = PresentationProvider()
    settings = Settings(country_aware_presentation_enabled=True)
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=MenuPresentationGenerator(settings, provider=provider),
    )

    us = service.present_selected(
        [_country_aware_item(spice_country="US", representative_dish="Buffalo wings")],
        session_id="session-1",
        language_code="en",
        country_code="US",
    )["menu-1"]
    second_payload = _generated_payload()
    second_payload["items"][0]["localized_source_description"] = (
        "A different but otherwise safe rice-cake description."
    )
    provider.output = json.dumps(second_payload)
    gb = service.present_selected(
        [
            _country_aware_item(
                spice_country="GB",
                representative_dish="Chicken tikka masala",
            )
        ],
        session_id="session-1",
        language_code="en",
        country_code="GB",
    )["menu-1"]

    assert us.menu.menu_id == gb.menu.menu_id == "menu-1"
    assert us.cache_key != gb.cache_key
    assert len(repository.country_cache) == 2
    assert len(repository.runtime_sources) == 1
    assert gb.source_description == us.source_description == "Chewy rice cakes cooked to order."
    request_contexts = [
        json.loads(request["input"][0]["content"])["menus"][0][
            "presentation_country_context"
        ]
        for request in provider.requests
    ]
    assert request_contexts[0]["user_country_code"] == "US"
    assert request_contexts[0]["representative_dish_en"] == "Buffalo wings"
    assert request_contexts[1]["user_country_code"] == "GB"
    assert request_contexts[1]["representative_dish_en"] == "Chicken tikka masala"
    assert all(
        "country_preference"
        not in json.loads(request["input"][0]["content"])["menus"][0]
        for request in provider.requests
    )
    assert all(
        "localized_source_description" not in entry.evidence_map
        for entry in repository.country_cache.values()
    )


def test_country_aware_cache_identity_uses_profile_country_not_preference_statistic() -> None:
    service = MenuPresentationService(
        PresentationRepository(MerchantMenuPresentationPage(items=[])),  # type: ignore[arg-type]
        Settings(country_aware_presentation_enabled=True),
    )
    base = _presentation(country_code="US").model_copy(
        update={
            "evidence_map": {
                **_presentation().evidence_map,
                "presentation_country_context": {
                    "user_country_code": "GB",
                    "spice_reference_country_code": "JP",
                },
            }
        }
    )
    changed_statistic = base.model_copy(
        update={
            "country_preference": {
                "country_code": "FR",
                "preference_percent": 91,
                "sample_size": 999,
            }
        }
    )
    changed_user_country = base.model_copy(
        update={
            "evidence_map": {
                **base.evidence_map,
                "presentation_country_context": {
                    "user_country_code": "US",
                    "spice_reference_country_code": "JP",
                },
            }
        }
    )

    gb = service._with_cache_identity(base, country_aware=True)
    same_gb = service._with_cache_identity(changed_statistic, country_aware=True)
    us = service._with_cache_identity(changed_user_country, country_aware=True)

    assert gb.cache_key == same_gb.cache_key
    assert gb.cache_key != us.cache_key


_EXTENDED_LOCALE_COPY = {
    "zh-CN": "这是为点餐准备的菜单说明。",
    "zh-TW": "這是為點餐準備的菜單說明。",
    "es": "Descripción clara del menú para realizar el pedido.",
    "fr": "Description claire du menu pour passer la commande.",
    "de": "Klare Menübeschreibung für die Bestellung.",
    "it": "Descrizione chiara del menu per effettuare l'ordine.",
    "pt": "Descrição clara do menu para fazer o pedido.",
    "th": "คำอธิบายเมนูที่ชัดเจนสำหรับการสั่งอาหาร",
    "vi": "Mô tả thực đơn rõ ràng để đặt món.",
    "id": "Deskripsi menu yang jelas untuk memesan makanan.",
    "ar": "وصف واضح لقائمة الطعام من أجل الطلب.",
    "hi": "ऑर्डर करने के लिए मेनू का स्पष्ट विवरण।",
    "ru": "Понятное описание меню для оформления заказа.",
}


@pytest.mark.parametrize(("locale", "copy"), _EXTENDED_LOCALE_COPY.items())
def test_country_aware_generator_accepts_each_extended_locale(
    locale: str, copy: str
) -> None:
    presentation = _presentation(language_code=locale, source_description="요기요 원문")
    presentation = presentation.model_copy(
        update={
            "evidence_map": {
                **presentation.evidence_map,
                "presentation_country_context": {
                    "user_country_code": "US",
                    "spice_reference_country_code": None,
                    "representative_dish_en": None,
                    "spice_baseline": None,
                    "menu_spice_level": None,
                    "spice_relationship": None,
                    "comparison_is_complete": False,
                },
            }
        }
    )
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_subtitle": copy,
            "localized_source_description": copy,
            "yobi_short_explanation": copy,
            "yobi_long_explanation": f"{copy} {copy}",
            "review_summary": copy,
        }
    )
    provider = PresentationProvider(output=json.dumps(payload, ensure_ascii=False))

    generated = MenuPresentationGenerator(Settings(), provider=provider).generate_country_aware(
        items=[
            MenuPresentationService._generation_payload(
                presentation,
                country_aware=True,
            )
        ],
        locale=locale,
    )

    assert generated.items[0].localized_source_description == copy
    assert generated.field_fallbacks == {}


def test_extended_locale_provider_failure_returns_english_fallback_without_cache() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[]))
    provider = AlwaysRateLimitedPresentationProvider()
    settings = Settings(country_aware_presentation_enabled=True)
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=MenuPresentationGenerator(settings, provider=provider),
    )

    result = service.present_selected(
        [
            _country_aware_item(
                spice_country="US",
                representative_dish="Buffalo wings",
                localized_source_description="Chewy rice cakes cooked to order.",
            )
        ],
        session_id="session-1",
        language_code="es",
        country_code="US",
    )["menu-1"]

    assert result.generation_model == "DETERMINISTIC_GROUNDED_FALLBACK"
    assert result.source_description == "Chewy rice cakes cooked to order."
    assert repository.country_cache == {}


def test_extended_locale_invalid_narrative_keeps_safe_source_without_caching_narrative() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[]))
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_subtitle": "잘못된 문자권 부제",
            "localized_source_description": "Descripción fiel del restaurante.",
            "yobi_short_explanation": "잘못된 문자권 설명",
            "yobi_long_explanation": "잘못된 문자권 긴 설명",
            "review_summary": "잘못된 문자권 리뷰",
        }
    )
    provider = PresentationProvider(output=json.dumps(payload, ensure_ascii=False))
    settings = Settings(country_aware_presentation_enabled=True)
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=MenuPresentationGenerator(settings, provider=provider),
    )

    result = service.present_selected(
        [
            _country_aware_item(
                spice_country="US",
                representative_dish="Buffalo wings",
            )
        ],
        session_id="session-1",
        language_code="es",
        country_code="US",
    )["menu-1"]

    assert result.generation_model == "DETERMINISTIC_GROUNDED_FALLBACK"
    assert result.source_description == "Descripción fiel del restaurante."
    assert len(repository.runtime_sources) == 1
    assert repository.country_cache == {}


def test_deterministic_source_fallback_rejects_old_phonetic_localizations() -> None:
    source = "매콤한 떡볶이와 불향가득 차돌박이를 정성껏 준비했습니다"

    assert (
        deterministic_localized_source_description(
            "en",
            source_ko=source,
            candidates=[
                "Maekomhan tteokbokki wa bulhyanggadeuk chadolbakireul "
                "jeongseongkkeot junbihaetseupnida."
            ],
        )
        == ""
    )
    assert (
        deterministic_localized_source_description(
            "ja",
            source_ko=source,
            candidates=[
                "メコムハン トッポッキ オァ ブルヒャンガドゥク チャドルバクイルル "
                "ジョンソンコッ ジュンビヘッスプニダ。"
            ],
        )
        == ""
    )
    assert (
        deterministic_localized_source_description(
            "en",
            source_ko=source,
            candidates=["Spicy tteokbokki served with smoky beef brisket."],
        )
        == "Spicy tteokbokki served with smoky beef brisket."
    )


def test_invalid_grounding_contract_tries_fallback_then_keeps_deterministic_copy() -> None:
    original = _presentation()
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[original]))
    provider = PresentationProvider(output='{"items": []}')
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.calls == ["xai.grok-4.3", "openai.gpt-oss-120b"]
    assert page.items[0].model_dump(mode="json") == original.model_copy(
        update={
            "localized_title": "Tteokbokki",
            "localized_subtitle": "Tteokbokki",
            "source_description": "",
        }
    ).model_dump(mode="json")
    assert repository.cache == {}


def test_invalid_batch_tries_fallback_without_splitting_and_keeps_deterministic_copy() -> None:
    items = [_presentation(f"menu-{index}") for index in range(1, 4)]
    repository = PresentationRepository(MerchantMenuPresentationPage(items=items))
    provider = SplitOnBatchProvider()
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.requested_ids == [
        ["menu-1", "menu-2", "menu-3"],
        ["menu-1", "menu-2", "menu-3"],
    ]
    assert repository.cache == {}
    assert all(item.generation_model == "DETERMINISTIC_GROUNDED_FALLBACK" for item in page.items)


def test_partial_batch_keeps_valid_grok_items_and_falls_back_only_missing_menu() -> None:
    items = [_presentation(f"menu-{index}") for index in range(1, 4)]
    payload = _generated_payload(["menu-1", "menu-2"])
    payload["items"].append({**payload["items"][0], "menu_id": "unknown-menu"})
    repository = PresentationRepository(MerchantMenuPresentationPage(items=items))
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert [item.generation_model for item in page.items] == [
        "xai.grok-4.3",
        "xai.grok-4.3",
        "DETERMINISTIC_GROUNDED_FALLBACK",
    ]
    assert len(repository.cache) == 2


def test_compound_presentation_missing_component_metadata_uses_safe_field_fallback() -> None:
    original = _presentation().model_copy(
        update={
            "evidence_map": {
                **_presentation().evidence_map,
                "menu_components": [
                    {"component_id": "cold-noodle", "name_en": "cold noodles"},
                    {"component_id": "cutlet", "name_en": "pork cutlet"},
                ],
            }
        }
    )
    invalid = _generated_payload()
    invalid["items"][0]["covered_component_ids"] = ["cutlet"]
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[original]))
    provider = PresentationProvider(output=json.dumps(invalid))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3+SAFE_FIELD_FALLBACK"
    assert len(repository.cache) == 1
    assert page.items[0].evidence_map["covered_component_ids"] == []
    assert page.items[0].evidence_map["safe_field_fallbacks"] == ["component_metadata"]


def test_compound_presentation_requires_component_mentions_in_actual_copy() -> None:
    components = [
        {"component_id": "cold-noodle", "name_en": "cold noodles"},
        {"component_id": "cutlet", "name_en": "pork cutlet"},
    ]
    original = _presentation(localized_title="Cold Noodles and Pork Cutlet Set").model_copy(
        update={
            "evidence_map": {
                **_presentation().evidence_map,
                "menu_components": components,
            }
        }
    )
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_title": "Cold Noodles and Pork Cutlet Set",
            "localized_subtitle": "Cold noodles paired with a pork cutlet",
            "localized_source_description": "Cold noodles served with pork cutlet.",
            "yobi_short_explanation": (
                "The cold noodles are the chilled main dish. A pork cutlet adds a crisp side."
            ),
            "yobi_long_explanation": (
                "Cold noodles provide the chilled noodle portion. "
                "The pork cutlet is a separate fried component. "
                "Both items belong to this set. Each keeps its own serving style."
            ),
            "used_source_fields": [
                "menu_title_ko",
                "localized_title",
                "source_description_ko",
                "wiki_passages",
                "synthetic_reviews",
                "menu_components",
            ],
            "yobi_used_source_fields": [
                "menu_title_ko",
                "localized_title",
                "source_description_ko",
                "wiki_passages",
                "menu_components",
            ],
            "covered_component_ids": ["cold-noodle", "cutlet"],
            "component_mentions": [
                {"component_id": "cold-noodle", "mention_text": "cold noodles"},
                {"component_id": "cutlet", "mention_text": "pork cutlet"},
            ],
        }
    )
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[original]))
    provider = PresentationProvider(output=json.dumps(payload))
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3"
    assert len(repository.cache) == 1
    assert page.items[0].evidence_map["component_mentions"] == [
        {"component_id": "cold-noodle", "mention_text": "cold noodles"},
        {"component_id": "cutlet", "mention_text": "pork cutlet"},
    ]
    assert page.items[0].evidence_map["yobi_used_evidence_ids"] == ["wiki-1", "wiki-2"]
    assert page.items[0].evidence_map["review_used_ids"] == ["review-1", "review-2"]
    assert "synthetic_reviews" not in page.items[0].evidence_map["yobi_used_source_fields"]
    assert page.items[0].evidence_map["review_used_source_fields"] == ["synthetic_reviews"]


def test_compound_presentation_filters_incorrect_component_bookkeeping_without_rejecting_copy() -> (
    None
):
    components = [
        {"component_id": "cold-noodle", "name_en": "cold noodles"},
        {"component_id": "cutlet", "name_en": "pork cutlet"},
    ]
    presentation = _presentation(localized_title="Cold Noodles and Pork Cutlet Set").model_copy(
        update={
            "evidence_map": {
                **_presentation().evidence_map,
                "menu_components": components,
            }
        }
    )
    payload = _generated_payload()
    payload["items"][0].update(
        {
            "localized_title": "Cold Noodles and Pork Cutlet Set",
            "localized_subtitle": "Cold noodles paired with a pork cutlet",
            "localized_source_description": "Cold noodles served with pork cutlet.",
            "yobi_short_explanation": (
                "The cold noodles are chilled. The pork cutlet is served separately."
            ),
            "yobi_long_explanation": (
                "Cold noodles form one component. The pork cutlet forms the other. "
                "Both belong to this set. Each keeps its own serving style."
            ),
            "used_source_fields": [
                "menu_title_ko",
                "localized_title",
                "source_description_ko",
                "wiki_passages",
                "synthetic_reviews",
                "menu_components",
            ],
            "yobi_used_source_fields": [
                "menu_title_ko",
                "localized_title",
                "source_description_ko",
                "wiki_passages",
                "menu_components",
            ],
            "covered_component_ids": ["cold-noodle", "cutlet"],
            "component_mentions": [
                {"component_id": "cold-noodle", "mention_text": "cold noodles"},
                {"component_id": "cutlet", "mention_text": "cold noodles"},
            ],
        }
    )

    generated = _generate_presentation(payload, presentation)

    assert [mention.component_id for mention in generated.items[0].component_mentions] == [
        "cold-noodle"
    ]
    assert generated.items[0].covered_component_ids == ["cold-noodle"]
    assert generated.field_fallbacks["menu-1"] == ["component_metadata"]


def test_deterministic_presentation_copy_is_locale_safe_and_schema_sized() -> None:
    copy = deterministic_presentation_copy(
        "ja",
        localized_title="トッポッキ",
        wiki_passages=["떡볶이는 떡과 양념으로 만듭니다."],
        reviews=[
            {"topic": "TASTE", "rating": 5, "review_text": "맛이 좋아요."},
            {"topic": "TEXTURE", "rating": 4, "review_text": "식감이 좋아요."},
        ],
    )

    assert not re.search(r"[가-힣]", copy.short_explanation)
    assert not re.search(r"[가-힣]", copy.long_explanation)
    assert not re.search(r"[가-힣]", copy.review_summary)
    assert len(re.findall(r"[.!?。！？]", copy.short_explanation)) in {1, 2}
    assert 3 <= len(re.findall(r"[.!?。！？]", copy.long_explanation)) <= 5
    assert 2 <= len(re.findall(r"[.!?。！？]", copy.review_summary)) <= 3


def test_nakji_fallback_waits_for_grounded_presentation_translation() -> None:
    assert (
        deterministic_localized_subtitle(
            "en",
            title_ko="낙지김치비빔밥",
            localized_title="Nakji Kimchi Bibimbap",
        )
        == "Nakji Kimchi Bibimbap"
    )


def test_partial_cache_hit_batches_only_missing_presentations() -> None:
    first = _presentation("menu-1")
    second = _presentation("menu-2")
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[first, second]))
    provider = PresentationProvider()
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )
    prepared_first = service._with_cache_identity(first)
    repository.save_menu_presentation_cache_entry(service._cache_entry(prepared_first))

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.requested_ids == [["menu-2"]]
    assert len(repository.cache) == 2
    assert [item.menu.menu_id for item in page.items] == ["menu-1", "menu-2"]


def test_empty_legacy_cached_source_is_ignored_in_favor_of_safe_existing_copy() -> None:
    original = _presentation(source_description="Chewy rice cakes cooked to order.")
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[original]))
    service = MenuPresentationService(repository, Settings())  # type: ignore[arg-type]
    prepared = service._with_cache_identity(original)
    cached = service._cache_entry(prepared).model_copy(
        update={
            "evidence_map": {
                **prepared.evidence_map,
                "localized_source_description": "",
            }
        }
    )
    repository.save_menu_presentation_cache_entry(cached)

    page = service.list_presentations(
        "session-1", "merchant-1", MerchantMenuPresentationRequest()
    )

    assert page.items[0].source_description == "Chewy rice cakes cooked to order."
    assert "localized_source_description" not in page.items[0].evidence_map


def test_source_language_country_and_prompt_changes_each_invalidate_cache() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = PresentationProvider()

    def resolve(settings: Settings) -> None:
        MenuPresentationService(
            repository,  # type: ignore[arg-type]
            settings,
            generator=MenuPresentationGenerator(settings, provider=provider),
        ).list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    resolve(Settings())
    repository.page = MerchantMenuPresentationPage(
        items=[_presentation(source_description="변경된 요기요 원문")]
    )
    resolve(Settings())
    japanese_payload = _generated_payload()
    japanese_payload["items"][0].update(
        {
            "localized_title": "トッポッキ",
            "localized_subtitle": "もちもちした韓国餅の甘辛い料理",
            "localized_source_description": "変更されたヨギヨの原文です。",
            "yobi_short_explanation": (
                "トッポッキは、もちもちした韓国餅を温かいソースで味わう料理です。"
                "分けやすい一品です。"
            ),
            "yobi_long_explanation": (
                "トッポッキの中心は、もちもちした韓国餅です。"
                "提供された情報では温かいソースを使います。"
                "やわらかく弾力のある食感です。"
                "この商品も韓国餅の特徴を保っています。"
            ),
            "review_summary": (
                "口コミでは、もちもちした食感が好評でした。量にも満足したという声がありました。"
            ),
        }
    )
    provider.output = json.dumps(japanese_payload)
    repository.page = MerchantMenuPresentationPage(
        items=[
            _presentation(
                source_description="변경된 요기요 원문",
                localized_title="トッポッキ",
                language_code="ja",
                country_code="JP",
            )
        ]
    )
    resolve(Settings())
    resolve(Settings(menu_presentation_prompt_version="presentation-prompt-v-next"))

    assert provider.requested_ids == [["menu-1"]] * 4
    assert len(repository.cache) == 4


def test_current_prompt_and_schema_logically_invalidate_legacy_cache_without_deleting_it() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    legacy_settings = Settings(
        menu_presentation_prompt_version="yobi-menu-presentation-v7-card-only",
        menu_presentation_schema_version="4",
    )
    legacy_service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        legacy_settings,
        generator=MenuPresentationGenerator(legacy_settings, provider=PresentationProvider()),
    )
    legacy_item = legacy_service._with_cache_identity(_presentation())
    legacy_key = legacy_item.cache_key
    repository.save_menu_presentation_cache_entry(legacy_service._cache_entry(legacy_item))

    provider = PresentationProvider()
    current_settings = Settings()
    current_service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        current_settings,
        generator=MenuPresentationGenerator(current_settings, provider=provider),
    )
    page = current_service.list_presentations(
        "session-1", "merchant-1", MerchantMenuPresentationRequest()
    )

    assert current_settings.menu_presentation_prompt_version == (
        "yobi-menu-presentation-v19-traveler-tone"
    )
    assert current_settings.menu_presentation_schema_version == "7"
    assert provider.requested_ids == [["menu-1"]]
    assert page.items[0].generation_model == "xai.grok-4.3"
    assert len(repository.cache) == 2
    assert legacy_key in repository.cache


def test_ten_simultaneous_cold_misses_generate_one_cache_row_once() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = PresentationProvider(delay_seconds=0.1)
    settings = Settings(
        menu_presentation_wait_seconds=1.0,
        menu_presentation_poll_seconds=0.05,
    )
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=MenuPresentationGenerator(settings, provider=provider),
    )

    with ThreadPoolExecutor(max_workers=10) as executor:
        pages = list(
            executor.map(
                lambda _: service.list_presentations(
                    "session-1", "merchant-1", MerchantMenuPresentationRequest()
                ),
                range(10),
            )
        )

    assert provider.calls == ["xai.grok-4.3"]
    assert len(repository.cache) == 1
    assert all(page.items[0].generation_model == "xai.grok-4.3" for page in pages)


def test_cache_read_failure_returns_selected_menu_with_deterministic_copy() -> None:
    original = _presentation()
    repository = BrokenCacheRepository(
        MerchantMenuPresentationPage(items=[original]),
        fail_read=True,
    )
    provider = PresentationProvider()
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].model_dump(mode="json") == original.model_copy(
        update={
            "localized_title": "Tteokbokki",
            "localized_subtitle": "Tteokbokki",
            "source_description": "",
        }
    ).model_dump(mode="json")
    assert provider.calls == []


def test_cache_write_failure_keeps_valid_generated_copy_for_this_response() -> None:
    repository = BrokenCacheRepository(
        MerchantMenuPresentationPage(items=[_presentation()]),
        fail_write=True,
    )
    provider = PresentationProvider()
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert page.items[0].generation_model == "xai.grok-4.3"
    assert page.items[0].localized_subtitle == "Chewy Korean rice cakes in sauce"
    assert repository.cache == {}
