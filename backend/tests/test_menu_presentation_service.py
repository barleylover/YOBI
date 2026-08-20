from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.domain.models import (
    EvidenceStatus,
    MenuPresentationCacheEntry,
    MenuSummary,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
    OptionGroup,
    OptionItem,
)
from app.domain.recommendation_copy import deterministic_presentation_copy
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)
from app.genai.presentation_generator import MenuPresentationGenerator
from app.services.menu_presentation import (
    MenuPresentationService,
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
        self.leases: dict[str, str] = {}
        self.lock = Lock()
        self.saved_option_localizations: list[
            tuple[str, str, dict[str, str], dict[str, str], str]
        ] = []
        self.saved_menu_localizations: list[tuple[str, str, str, str, str, str]] = []

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
        localized_title: str,
        localized_source_description: str,
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

    def supports_model(self, model: str) -> bool:
        return model in {"xai.grok-4.3", "openai.gpt-oss-120b"}

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append(model)
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
                "localized_title": f"Tteokbokki {menu_id}",
                "localized_subtitle": "Chewy Korean rice cakes in sauce",
                "localized_source_description": "Natural restaurant description.",
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
                    "source_description_ko",
                    "wiki_passages",
                    "synthetic_reviews",
                ],
                "personalization_applied": False,
                "covered_component_ids": [],
                "option_group_localizations": [],
                "option_item_localizations": [],
            }
            for menu_id in ids
        ]
    }


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


def test_presentation_translates_fields_by_purpose_and_caches_options() -> None:
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
            "localized_title": "Spicy rice cakes menu-1",
            "localized_subtitle": "Chewy rice cakes in a spicy Korean sauce",
            "localized_source_description": "Fresh rice cakes cooked to order.",
            "option_group_localizations": [
                {"object_id": "group-1", "display_name": "Drink add-ons"}
            ],
            "option_item_localizations": [
                {
                    "object_id": "item-1",
                    "display_name": "Add Coca-Cola (355ml)",
                }
            ],
            "used_source_fields": [
                "menu_title_ko",
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

    assert page.items[0].localized_title == "Spicy rice cakes menu-1"
    assert page.items[0].source_description == "Fresh rice cakes cooked to order."
    assert repository.saved_option_localizations == [
        (
            "session-1",
            "menu-1",
            {"group-1": "Drink add-ons"},
            {"item-1": "Add Coca-Cola (355ml)"},
            "xai.grok-4.3",
        )
    ]
    assert repository.saved_menu_localizations[0][2:4] == (
        "Spicy rice cakes menu-1",
        "Fresh rice cakes cooked to order.",
    )
    assert len(repository.cache) == 1


def test_phonetic_option_copy_is_rejected_instead_of_cached() -> None:
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

    assert page.items[0].generation_model == "DETERMINISTIC_GROUNDED_FALLBACK"
    assert repository.cache == {}
    assert repository.saved_option_localizations == []


def test_phonetic_yogiyo_description_is_rejected_instead_of_cached() -> None:
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

    assert page.items[0].generation_model == "DETERMINISTIC_GROUNDED_FALLBACK"
    assert repository.cache == {}
    assert repository.saved_menu_localizations == []


def test_menu_presentation_rate_limit_falls_back_to_120b_with_same_page() -> None:
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


def test_invalid_grounding_contract_keeps_deterministic_copy_without_fallback() -> None:
    original = _presentation()
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[original]))
    provider = PresentationProvider(output='{"items": []}')
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.calls == ["xai.grok-4.3"]
    assert page.items[0].model_dump(mode="json") == original.model_copy(
        update={
            "localized_title": "Tteokbokki",
            "localized_subtitle": "Tteokbokki",
            "source_description": "",
        }
    ).model_dump(mode="json")
    assert repository.cache == {}


def test_invalid_batch_is_not_retried_and_keeps_deterministic_copy() -> None:
    items = [_presentation(f"menu-{index}") for index in range(1, 4)]
    repository = PresentationRepository(MerchantMenuPresentationPage(items=items))
    provider = SplitOnBatchProvider()
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        generator=MenuPresentationGenerator(Settings(), provider=provider),
    )

    page = service.list_presentations("session-1", "merchant-1", MerchantMenuPresentationRequest())

    assert provider.requested_ids == [["menu-1", "menu-2", "menu-3"]]
    assert repository.cache == {}
    assert all(item.generation_model == "DETERMINISTIC_GROUNDED_FALLBACK" for item in page.items)


def test_compound_presentation_requires_every_component_id() -> None:
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

    assert page.items[0].generation_model == "DETERMINISTIC_GROUNDED_FALLBACK"
    assert repository.cache == {}


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
    second = _presentation("menu-2", localized_title="Rabokki")
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
    repository.page = MerchantMenuPresentationPage(
        items=[
            _presentation(
                source_description="변경된 요기요 원문",
                language_code="ja",
                country_code="JP",
            )
        ]
    )
    resolve(Settings())
    resolve(Settings(menu_presentation_prompt_version="presentation-prompt-v-next"))

    assert provider.requested_ids == [["menu-1"]] * 4
    assert len(repository.cache) == 4


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
