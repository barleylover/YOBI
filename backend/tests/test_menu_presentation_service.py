from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.domain.models import (
    EvidenceStatus,
    MenuSummary,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
)
from app.domain.recommendation_copy import deterministic_presentation_copy
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)
from app.services.menu_presentation import MenuPresentationService


class PresentationRepository:
    def __init__(self, page: MerchantMenuPresentationPage) -> None:
        self.page = page
        self.saved: list[MerchantMenuPresentation] = []

    def list_merchant_menu_presentations(
        self,
        session_id: str,
        merchant_id: str,
        request: MerchantMenuPresentationRequest,
    ) -> MerchantMenuPresentationPage:
        del session_id, merchant_id, request
        return self.page

    def save_menu_presentation_cache(
        self, session_id: str, presentation: MerchantMenuPresentation
    ) -> None:
        assert session_id == "session-1"
        self.saved.append(presentation)


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
        max_output_tokens=4_096,
        max_tools_per_request=4,
        max_tool_calls_per_response=4,
    )

    def __init__(self, *, rate_limit_primary: bool = False, output: str | None = None) -> None:
        self.rate_limit_primary = rate_limit_primary
        self.output = output or json.dumps(_generated_payload())
        self.calls: list[str] = []

    def supports_model(self, model: str) -> bool:
        return model in {"xai.grok-4.3", "openai.gpt-oss-120b"}

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        del kwargs
        self.calls.append(model)
        if self.rate_limit_primary and model == "xai.grok-4.3":
            raise GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True)
        return SimpleNamespace(output_text=self.output)


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


def _presentation() -> MerchantMenuPresentation:
    return MerchantMenuPresentation(
        menu=_menu(),
        localized_title="Tteokbokki",
        yobi_short_explanation="Wiki passage one.",
        yobi_long_explanation="Wiki passage one. Wiki passage two.",
        source_description="요기요 원문",
        review_summary="The texture was chewy. The portion felt generous.",
        country_preference={
            "country_code": "US",
            "preference_percent": 78,
            "sample_size": 420,
        },
        evidence_ids=["wiki-1", "wiki-2"],
        review_ids=["review-1", "review-2"],
        generation_model="DETERMINISTIC_WIKI_FALLBACK",
    )


def _generated_payload() -> dict[str, Any]:
    return {
        "items": [
            {
                "menu_id": "menu-1",
                "yobi_short_explanation": (
                    "Think of chewy rice cakes in a warm Korean sauce. "
                    "It is an easy dish to share."
                ),
                "yobi_long_explanation": (
                    "Tteokbokki centers on chewy rice cakes. "
                    "The supplied Wiki describes a warm sauce. "
                    "Its bite is soft and springy."
                ),
                "review_summary": (
                    "Reviewers liked the chewy texture. "
                    "They also found the portion generous."
                ),
            }
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
        provider=provider,
    )

    page = service.list_presentations(
        "session-1", "merchant-1", MerchantMenuPresentationRequest()
    )

    assert provider.calls == ["xai.grok-4.3"]
    assert page.items[0].generation_model == "xai.grok-4.3"
    assert page.next_cursor == "menu-1"
    assert repository.saved == page.items


def test_menu_presentation_rate_limit_falls_back_to_120b_with_same_page() -> None:
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[_presentation()]))
    provider = PresentationProvider(rate_limit_primary=True)
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    )

    page = service.list_presentations(
        "session-1", "merchant-1", MerchantMenuPresentationRequest()
    )

    assert provider.calls == ["xai.grok-4.3", "openai.gpt-oss-120b"]
    assert page.items[0].generation_model == "openai.gpt-oss-120b"


def test_invalid_grounding_contract_keeps_deterministic_copy_without_fallback() -> None:
    original = _presentation()
    repository = PresentationRepository(MerchantMenuPresentationPage(items=[original]))
    provider = PresentationProvider(output='{"items": []}')
    service = MenuPresentationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    )

    page = service.list_presentations(
        "session-1", "merchant-1", MerchantMenuPresentationRequest()
    )

    assert provider.calls == ["xai.grok-4.3"]
    assert page.items == [original]
    assert repository.saved == []


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
