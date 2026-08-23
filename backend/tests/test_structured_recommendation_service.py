from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.dependencies import get_repository, get_structured_recommendation_service
from app.domain.models import (
    ChatState,
    EvidenceStatus,
    MenuSummary,
    Profile,
    Session,
)
from app.domain.structured_recommendation import (
    CriterionEvidence,
    EvidencePoolItem,
    EvidenceReference,
    LiveRecommendationMenuState,
    RecommendationComparisonRequest,
    RecommendationCriteriaCommit,
    RecommendationCriteriaRecord,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationRequestInput,
    RecommendationRequestRecord,
    RecommendationRequestStatus,
)
from app.genai.contracts import GenAIServingMode, ProviderCapabilities
from app.genai.recommendation_generator import RecommendationGenerator
from app.main import app
from app.services.demo_control import DemoControl
from app.services.menu_presentation import MenuPresentationService
from app.services.structured_recommendation import (
    StructuredRecommendationService,
    _effective_display_language,
    compact_generation_payload,
)


def test_backend_generation_uses_only_the_three_effective_display_languages() -> None:
    assert _effective_display_language("한국어") == ("ko", "한국어")
    assert _effective_display_language("日本語") == ("ja", "日本語")
    for language in (
        "English",
        "中文（简体）",
        "中文（繁體）",
        "Español",
        "Français",
        "Deutsch",
        "Italiano",
        "Português",
        "ไทย",
        "Tiếng Việt",
        "Bahasa Indonesia",
        "العربية",
        "हिन्दी",
        "Русский",
    ):
        assert _effective_display_language(language) == ("en", "English")


def test_selection_payload_excludes_country_context_fields() -> None:
    item = _pool_item("menu-a", score=0.9).model_copy(
        update={
            "country_preference": {
                "country_code": "US",
                "preference_percent": 71,
                "sample_size": 220,
            },
            "spice_reference_country_code": "GB",
            "spice_reference_dish_en": "Chicken tikka masala",
        }
    )

    payload = compact_generation_payload(item, max_wiki_passages=2)

    assert "country_preference" not in payload
    assert "spice_reference_country_code" not in payload
    assert "spice_reference_dish_en" not in payload


class FakeProvider:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []
        self._capabilities = ProviderCapabilities(
            provider="fake",
            serving_mode=GenAIServingMode.ON_DEMAND,
            responses_api=True,
            function_calling=True,
            structured_output=True,
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


class FailingProvider(FakeProvider):
    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        raise TimeoutError("provider timeout")


class FakeRecommendationRepository:
    def __init__(self, criteria: RecommendationCriteriaV2) -> None:
        now = datetime.now(timezone.utc)
        self.criteria_record = RecommendationCriteriaRecord(
            session_id="session-structured",
            criteria=criteria,
            criteria_version=1,
            state_version=1,
            criteria_hash="criteria-hash-v1",
            request_id="criteria-request-0001",
            created_at=now,
        )
        self.evidence_pool: list[EvidencePoolItem] = []
        self.requests: dict[str, RecommendationRequestRecord] = {}
        self.saved_criteria_count = 0
        self.completed_statuses: list[RecommendationRequestStatus] = []
        self.pool_limits: tuple[int, int] | None = None
        self.live_states: dict[str, LiveRecommendationMenuState] | None = None
        self.session = _session()
        self.profile = _profile()
        self.comparison_cache: dict[str, Any] | None = None
        self.preview_zero_reasons: list[str] = []

    def preview_recommendation(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
    ) -> Any:
        del criteria
        assert session_id == self.session.session_id
        return SimpleNamespace(
            eligible_menu_count=len(self.evidence_pool),
            eligible_merchant_count=len({item.menu.merchant_id for item in self.evidence_pool}),
            zero_reason_codes=list(self.preview_zero_reasons),
            release_id="knowledge-demo-v1",
            support_manifest_sha256="a" * 64,
            ranking_policy_version="yobi-hybrid-rank-v2",
            timing_ms=0,
        )

    def get_session(self, session_id: str) -> Session | None:
        return self.session if session_id == self.session.session_id else None

    def get_profile(self, profile_id: str) -> Profile | None:
        return self.profile if profile_id == self.profile.profile_id else None

    def save_recommendation_criteria(
        self,
        session_id: str,
        commit: RecommendationCriteriaCommit,
    ) -> RecommendationCriteriaRecord:
        self.saved_criteria_count += 1
        self.criteria_record = self.criteria_record.model_copy(
            update={
                "session_id": session_id,
                "criteria": commit.criteria,
                "request_id": commit.request_id,
            }
        )
        return self.criteria_record

    def get_recommendation_criteria(
        self,
        session_id: str,
        version: int | None = None,
    ) -> RecommendationCriteriaRecord | None:
        if session_id != self.criteria_record.session_id:
            return None
        if version is not None and version != self.criteria_record.criteria_version:
            return None
        return self.criteria_record

    def reserve_recommendation_request(
        self,
        session_id: str,
        data: RecommendationRequestInput,
        request_hash: str,
    ) -> RecommendationRequestRecord:
        existing = self.requests.get(data.request_id)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("RECOMMENDATION_REQUEST_ID_REUSED")
            return existing.model_copy(update={"duplicate": True})
        record = RecommendationRequestRecord(
            request_id=data.request_id,
            session_id=session_id,
            request_hash=request_hash,
            criteria_version=data.criteria_version,
            mode=data.mode,
            status=RecommendationRequestStatus.CREATED,
            state_version=data.expected_state_version,
            release_family_id="recommendation-family-v1",
            eligibility_as_of=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        self.requests[data.request_id] = record
        return record

    def build_recommendation_evidence_pool(
        self,
        session_id: str,
        profile: Profile,
        criteria: RecommendationCriteriaV2,
        mode: Any,
        limit: int,
        *,
        release_family_id: str,
        eligibility_as_of: datetime,
        raw_hits_per_value: int,
        passages_per_menu: int,
    ) -> list[EvidencePoolItem]:
        del session_id, profile, criteria, mode, eligibility_as_of
        assert release_family_id == "recommendation-family-v1"
        self.pool_limits = (raw_hits_per_value, passages_per_menu)
        return self.evidence_pool[:limit]

    def mark_recommendation_dispatched(
        self,
        session_id: str,
        request_id: str,
        evidence_pool: list[EvidencePoolItem],
    ) -> RecommendationRequestRecord:
        record = self.requests[request_id]
        assert record.session_id == session_id
        assert record.status is RecommendationRequestStatus.CREATED
        updated = record.model_copy(
            update={
                "status": RecommendationRequestStatus.DISPATCHED,
                "evidence_pool_json": [item.model_dump(mode="json") for item in evidence_pool],
                "dispatch_count": 0,
                "dispatched_at": datetime.now(timezone.utc),
            }
        )
        self.requests[request_id] = updated
        return updated

    def mark_recommendation_provider_called(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord:
        record = self.requests[request_id]
        assert record.session_id == session_id
        assert record.status is RecommendationRequestStatus.DISPATCHED
        assert record.dispatch_count == 0
        updated = record.model_copy(update={"dispatch_count": 1})
        self.requests[request_id] = updated
        return updated

    def complete_recommendation_request(
        self,
        session_id: str,
        request_id: str,
        status: RecommendationRequestStatus,
        *,
        result_json: dict[str, Any] | None = None,
        snapshot: Any | None = None,
        failure_code: str | None = None,
        provider_metrics: dict[str, int] | None = None,
        grounding_rejection_code: str | None = None,
        grounding_rejection_stage: str | None = None,
        grounding_rejection_detail: str | None = None,
    ) -> RecommendationRequestRecord:
        record = self.requests[request_id]
        assert record.session_id == session_id
        self.completed_statuses.append(status)
        updated = record.model_copy(
            update={
                "status": status,
                "state_version": snapshot.state_version if snapshot else record.state_version,
                "snapshot_id": snapshot.snapshot_id if snapshot else None,
                "result_json": result_json,
                "failure_code": failure_code,
                "ranking_trace_json": {
                    **record.ranking_trace_json,
                    "provider_metrics": dict(provider_metrics or {}),
                    "grounding_rejection_code": grounding_rejection_code,
                    "grounding_rejection_stage": grounding_rejection_stage,
                    "grounding_rejection_detail": grounding_rejection_detail,
                },
                "completed_at": datetime.now(timezone.utc),
            }
        )
        self.requests[request_id] = updated
        return updated

    def get_recommendation_request(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord | None:
        record = self.requests.get(request_id)
        return record if record and record.session_id == session_id else None

    def get_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
    ) -> dict[str, Any] | None:
        del comparison_request_id
        assert session_id == self.session.session_id
        assert recommendation_request_id in self.requests
        return dict(self.comparison_cache) if self.comparison_cache else None

    def save_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        del comparison_request_id
        assert session_id == self.session.session_id
        assert recommendation_request_id in self.requests
        if self.comparison_cache is not None:
            return dict(self.comparison_cache), True
        self.comparison_cache = dict(payload)
        return dict(payload), False

    def get_live_recommendation_menu_states(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        release_family_id: str,
        menu_ids: list[str],
        *,
        at: datetime,
    ) -> dict[str, LiveRecommendationMenuState]:
        del session_id, criteria, release_family_id, at
        if self.live_states is not None:
            return {
                menu_id: state for menu_id, state in self.live_states.items() if menu_id in menu_ids
            }
        pool_by_id = {item.menu.menu_id: item for item in self.evidence_pool}
        return {
            menu_id: LiveRecommendationMenuState(
                menu=pool_by_id[menu_id].menu,
                halal_certified=pool_by_id[menu_id].halal_certified,
                halal_scope_label=pool_by_id[menu_id].halal_scope_label,
                vegan_status=pool_by_id[menu_id].vegan_status,
                vegan_warning=pool_by_id[menu_id].vegan_warning,
            )
            for menu_id in menu_ids
            if menu_id in pool_by_id
        }


def _criteria() -> RecommendationCriteriaV2:
    return RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        flavors=["SPICY"],
        price_bands=["UNDER_10000"],
        max_spice_level=3,
        spice_reference_country="KR",
    )


def _session() -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        session_id="session-structured",
        profile_id="profile-structured",
        state=ChatState.DISCOVERY,
        state_version=1,
        created_at=now,
        updated_at=now,
    )


def _profile() -> Profile:
    return Profile(
        profile_id="profile-structured",
        preferred_language="English",
        nationality="United States",
        age_band="25-34",
        gender="Prefer not to say",
        religion_selection="Islam",
        dietary_rules=["shellfish_allergy", "vegan"],
        allergy_severity="severe",
        spice_tolerance=1,
        favorite_foods=["bibimbap"],
        consent_demo_data=True,
        remember_profile=False,
        created_at=datetime.now(timezone.utc),
    )


def test_server_owned_criteria_summary_is_clear_and_usable_in_korean() -> None:
    repository = FakeRecommendationRepository(_criteria())

    summary = StructuredRecommendationService._criteria_fallback_summary(
        repository.criteria_record,
        "한국어",
    )

    assert summary.startswith("선택한 식사 선호 조건:")
    assert "한식" in summary
    assert len(summary.strip()) >= 4


def _menu(menu_id: str, *, score: float) -> MenuSummary:
    suffix = menu_id.rsplit("-", maxsplit=1)[-1].upper()
    return MenuSummary(
        menu_id=menu_id,
        merchant_id=f"merchant-{suffix}",
        merchant_name=f"Kitchen {suffix}",
        name_en=f"Dish {suffix}",
        name_ko=f"메뉴 {suffix}",
        category="Korean",
        description="A warm Korean rice dish.",
        cultural_description="A familiar Korean meal.",
        price=9000,
        delivery_fee=2000,
        eta_min=20,
        eta_max=35,
        spice_level=2,
        serves_min=1,
        serves_max=1,
        dietary_summary="See the current menu details.",
        evidence_status=EvidenceStatus.VERIFIED,
        match_reasons=[],
        risk_hints=[],
        semantic_score=score,
    )


def _pool_item(
    menu_id: str,
    *,
    score: float,
    has_wiki_passage: bool = True,
) -> EvidencePoolItem:
    suffix = menu_id.rsplit("-", maxsplit=1)[-1]
    cuisine_id = f"evidence-cuisine-{suffix}"
    flavor_id = f"evidence-flavor-{suffix}"
    wiki_id = f"evidence-wiki-{suffix}"
    return EvidencePoolItem(
        menu=_menu(menu_id, score=score),
        knowledge_concept_id=f"concept-{suffix}",
        criterion_evidence=[
            CriterionEvidence(
                category_code="cuisine_origins",
                selected_value_code="KOREAN",
                evidence=[
                    EvidenceReference(
                        evidence_id=cuisine_id,
                        evidence_type="ESSENTIAL_FACT",
                        content="This is a Korean dish.",
                    )
                ],
            ),
            CriterionEvidence(
                category_code="flavors",
                selected_value_code="SPICY",
                evidence=[
                    EvidenceReference(
                        evidence_id=flavor_id,
                        evidence_type="ESSENTIAL_FACT",
                        content="This variation has a spicy flavor.",
                    )
                ],
            ),
        ],
        wiki_passages=(
            [
                EvidenceReference(
                    evidence_id=wiki_id,
                    evidence_type="WIKI_PASSAGE",
                    content="The dish is commonly served as a satisfying meal.",
                )
            ]
            if has_wiki_passage
            else []
        ),
        menu_facts=[],
        halal_certified=False,
        vegan_status="POSSIBLE_WITH_CHECKS",
        vegan_warning="Check the current preparation details.",
        retrieval_score=score,
        knowledge_release_id="knowledge-release-v1",
        catalog_release_id="catalog-release-v1",
        recommendation_release_family_id="recommendation-family-v1",
    )


def test_freeze_server_candidates_keeps_only_wiki_grounded_menus_and_backfills() -> None:
    evidence_pool = [
        _pool_item("menu-without-wiki-a", score=0.99, has_wiki_passage=False),
        _pool_item("menu-with-wiki-a", score=0.90),
        _pool_item("menu-without-wiki-b", score=0.89, has_wiki_passage=False),
        _pool_item("menu-with-wiki-b", score=0.80),
        _pool_item("menu-with-wiki-c", score=0.70),
    ]

    frozen = StructuredRecommendationService._freeze_server_candidates(
        evidence_pool,
        limit=2,
    )

    assert [item.menu.menu_id for item in frozen] == [
        "menu-with-wiki-a",
        "menu-with-wiki-b",
    ]
    assert [item.server_rank for item in frozen] == [1, 2]
    assert all(item.wiki_passages for item in frozen)


def test_synthetic_vegan_runtime_guard_rejects_obvious_animal_aliases() -> None:
    gopchang = _menu("menu-gopchang", score=0.9).model_copy(
        update={"name_en": "Gopchang Daechang Rice Bowl", "name_ko": "곱창대창덮밥"}
    )
    vegetables = _menu("menu-vegetable", score=0.8).model_copy(
        update={"name_en": "Tofu vegetable bibimbap", "name_ko": "두부 채소 비빔밥"}
    )

    assert StructuredRecommendationService._has_obvious_animal_ingredient(gopchang)
    assert not StructuredRecommendationService._has_obvious_animal_ingredient(vegetables)
    assert not StructuredRecommendationService._has_obvious_animal_ingredient(
        vegetables.model_copy(update={"name_en": "Eggplant and champignon bibimbap"})
    )


def _generated_recommendation(menu_id: str, rank: int) -> dict[str, Any]:
    suffix = menu_id.rsplit("-", maxsplit=1)[-1]
    return {
        "rank": rank,
        "menu_id": menu_id,
        "title": f"Choice {rank}",
        "selection_reason": "It matches the selected cuisine and flavor.",
        "description": "The Wiki describes it as a satisfying Korean meal.",
        "matched_criteria": [
            {
                "category_code": "cuisine_origins",
                "selected_value_codes": ["KOREAN"],
                "evidence_ids": [f"evidence-cuisine-{suffix}"],
            },
            {
                "category_code": "flavors",
                "selected_value_codes": ["SPICY"],
                "evidence_ids": [f"evidence-flavor-{suffix}"],
            },
        ],
        "caution_codes": [],
    }


def _recommended_output(menu_ids: list[str]) -> dict[str, Any]:
    return {
        "status": "RECOMMENDED",
        "criteria_summary": "Korean and spicy under KRW 10,000",
        "recommendations": [
            _generated_recommendation(menu_id, rank)
            for rank, menu_id in enumerate(menu_ids, start=1)
        ],
        "unmatched_category_codes": [],
    }


def _service(
    repository: FakeRecommendationRepository,
    provider: FakeProvider,
) -> StructuredRecommendationService:
    settings = Settings(_env_file=None)
    generator = RecommendationGenerator(settings, provider=provider)
    return StructuredRecommendationService(
        repository,  # type: ignore[arg-type]
        settings,
        DemoControl(),
        generator=generator,
    )


class CapturingPresentationService(MenuPresentationService):
    last_language_code: str | None = None
    last_country_code: str | None = None

    def present_selected(self, evidence_items: list[EvidencePoolItem], **kwargs: Any):  # type: ignore[no-untyped-def]
        self.last_language_code = str(kwargs["language_code"])
        self.last_country_code = str(kwargs["country_code"])
        return super().present_selected(evidence_items, **kwargs)


def test_country_aware_flag_passes_full_locale_only_to_presentation() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    settings = Settings(_env_file=None, country_aware_presentation_enabled=True)
    presentation_service = CapturingPresentationService(repository, settings)  # type: ignore[arg-type]
    service = StructuredRecommendationService(
        repository,  # type: ignore[arg-type]
        settings,
        DemoControl(),
        generator=RecommendationGenerator(settings, provider=provider),
        presentation_service=presentation_service,
    )
    profile = _profile().model_copy(
        update={"preferred_language": "Español", "country_code": "US"}
    )

    result = service.request_recommendation(_session(), profile, _request())

    assert result.status == "RECOMMENDED"
    assert presentation_service.last_language_code == "es"
    assert presentation_service.last_country_code == "US"
    assert len(provider.calls) == 1
    assert "English" in provider.calls[0]["instructions"]


def test_english_us_and_gb_keep_identical_selection_input_and_menu_order() -> None:
    def run(country_code: str) -> tuple[list[str], str]:
        repository = FakeRecommendationRepository(_criteria())
        repository.evidence_pool = [
            _pool_item("menu-a", score=0.90),
            _pool_item("menu-b", score=0.80),
            _pool_item("menu-c", score=0.70),
        ]
        provider = FakeProvider(_recommended_output(["menu-b", "menu-a", "menu-c"]))
        settings = Settings(_env_file=None, country_aware_presentation_enabled=True)
        service = StructuredRecommendationService(
            repository,  # type: ignore[arg-type]
            settings,
            DemoControl(),
            generator=RecommendationGenerator(settings, provider=provider),
            presentation_service=MenuPresentationService(repository, settings),  # type: ignore[arg-type]
        )
        profile = _profile().model_copy(
            update={"preferred_language": "English", "country_code": country_code}
        )

        result = service.request_recommendation(_session(), profile, _request())

        return (
            [item.menu.menu_id for item in result.recommendations],
            str(provider.calls[0]["input"][0]["content"]),
        )

    us_menu_ids, us_selection_input = run("US")
    gb_menu_ids, gb_selection_input = run("GB")

    assert us_menu_ids == gb_menu_ids == ["menu-b", "menu-a", "menu-c"]
    assert us_selection_input == gb_selection_input


def _request(
    request_id: str = "recommendation-request-0001",
    mode: RecommendationMode = RecommendationMode.INITIAL,
) -> RecommendationRequestInput:
    return RecommendationRequestInput(
        request_id=request_id,
        expected_state_version=1,
        criteria_version=1,
        mode=mode,
    )


def test_criteria_commit_does_not_dispatch_generation() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    commit = RecommendationCriteriaCommit(
        criteria=_criteria(),
        catalog_version="preference-catalog-v1",
        expected_state_version=0,
        request_id="criteria-request-0002",
    )

    result = service.commit_criteria(_session(), commit)

    assert result.criteria == commit.criteria
    assert repository.saved_criteria_count == 1
    assert provider.calls == []


def test_unsupported_control_is_visible_in_preview_and_commit_returns_422() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.preview_zero_reasons = ["SPICE_LEVEL_UNAVAILABLE"]
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_structured_recommendation_service] = lambda: service
    client = TestClient(app)
    try:
        preview = client.post(
            "/api/v1/sessions/session-structured/structured-recommendations/preview",
            json=_criteria().model_dump(mode="json"),
        )
        committed = client.put(
            "/api/v1/sessions/session-structured/recommendation-criteria",
            json={
                "criteria": _criteria().model_dump(mode="json"),
                "catalog_version": "preference-catalog-v1",
                "expected_state_version": 0,
                "request_id": "criteria-unsupported-0001",
            },
        )
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert preview.status_code == 200
    assert preview.json()["eligible_menu_count"] == 0
    assert preview.json()["zero_reason_codes"] == ["SPICE_LEVEL_UNAVAILABLE"]
    assert committed.status_code == 422
    assert committed.json()["detail"]["code"] == "SPICE_LEVEL_UNAVAILABLE"
    assert repository.saved_criteria_count == 0


def test_preference_preview_and_commit_emit_privacy_safe_selection_events(
    monkeypatch: Any,
) -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    events: list[dict[str, Any]] = []

    def capture_event(_logger: Any, **fields: Any) -> None:
        events.append(fields)

    monkeypatch.setattr(
        "app.services.structured_recommendation.log_event",
        capture_event,
    )
    empty = RecommendationCriteriaV2(max_spice_level=5)
    korean = RecommendationCriteriaV2(cuisine_origins=["KOREAN"], max_spice_level=5)
    korean_spicy = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        flavors=["SPICY"],
        max_spice_level=5,
    )
    service.preview(_session(), empty)
    repository.evidence_pool = [_pool_item("menu-a", score=0.90)]
    service.preview(_session(), korean)
    service.preview(_session(), empty)
    service.preview(_session(), korean_spicy)
    service.preview(_session(), korean)
    service.commit_criteria(
        _session(),
        RecommendationCriteriaCommit(
            criteria=korean,
            catalog_version="preference-catalog-v1",
            expected_state_version=0,
            request_id="criteria-analytics-0001",
        ),
    )

    previews = [event for event in events if event["event"] == "recommendation_preference_preview"]
    committed = next(
        event for event in events if event["event"] == "recommendation_preference_committed"
    )
    assert [event["action"] for event in previews] == [
        "no_change",
        "add",
        "reset",
        "add",
        "remove",
    ]
    assert previews[0]["zero_result"] is True
    assert previews[-1]["selected_category_count"] == 1
    assert committed["selected_category_count"] == 1
    assert committed["selection_elapsed_ms"] is not None
    serialized = json.dumps(events)
    assert _session().session_id not in serialized
    assert "session_id_hash" in serialized


def test_empty_evidence_pool_returns_no_match_without_generation() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert result.status == "NO_MATCH"
    assert result.recommendations == []
    assert result.failure_code is None
    assert repository.completed_statuses == [RecommendationRequestStatus.NO_RESULTS]
    assert repository.pool_limits == (20, 4)
    assert provider.calls == []


def test_empty_history_excluding_request_persists_canonical_exhausted_code() -> None:
    for mode in (RecommendationMode.SIMILAR, RecommendationMode.RETRY):
        repository = FakeRecommendationRepository(_criteria())
        provider = FakeProvider(_recommended_output(["menu-a"]))
        service = _service(repository, provider)
        request = _request(f"recommendation-{mode.value.lower()}-0001", mode)

        result = service.request_recommendation(_session(), _profile(), request)

        assert result.status == "NO_MATCH"
        assert result.failure_code == "EXHAUSTED"
        assert repository.requests[request.request_id].failure_code == "EXHAUSTED"
        assert provider.calls == []


def test_underfilled_strict_match_skips_llm_and_keeps_source_language_safe() -> None:
    repository = FakeRecommendationRepository(_criteria())
    first = _pool_item("menu-a", score=0.90).model_copy(
        update={
            "menu": _menu("menu-a", score=0.90).model_copy(
                update={"description": "엄선된 돼지 원육으로 끓였습니다."}
            ),
        }
    )
    second = _pool_item("menu-b", score=0.80).model_copy(
        update={
            "menu": _menu("menu-b", score=0.80).model_copy(
                update={"description": "매콤한 떡볶이를 정성껏 준비했습니다."}
            ),
            "localized_source_description": "Spicy tteokbokki prepared with care.",
        }
    )
    repository.evidence_pool = [first, second]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert result.status == "SEARCH_FALLBACK"
    assert result.failure_code == "STRICT_MATCH_UNDERFILLED"
    assert [item.menu.menu_id for item in result.recommendations] == ["menu-a", "menu-b"]
    assert result.recommendations[0].source_description == ""
    assert result.recommendations[1].source_description == "Spicy tteokbokki prepared with care."
    assert all(
        item.caution_codes == ["STRICT_MATCH_UNDERFILLED"] for item in result.recommendations
    )
    assert provider.calls == []
    assert repository.requests[result.request_id].dispatch_count == 0


def test_model_can_select_and_reorder_three_from_the_frozen_shortlist() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.99),
        _pool_item("menu-b", score=0.70),
        _pool_item("menu-c", score=0.69),
    ]
    provider = FakeProvider(_recommended_output(["menu-b", "menu-c", "menu-a"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert len(provider.calls) == 1
    assert result.status == "RECOMMENDED"
    assert [item.menu.menu_id for item in result.recommendations] == [
        "menu-b",
        "menu-c",
        "menu-a",
    ]
    stored = repository.requests["recommendation-request-0001"]
    assert stored.dispatch_count == 1
    assert stored.status is RecommendationRequestStatus.COMPLETED
    assert stored.result_json is not None
    for item in stored.result_json["recommendations"]:
        passage_ids = [passage["evidence_id"] for passage in item["wiki_passages"]]
        assert passage_ids
        assert item["wiki_evidence_ids"] == passage_ids


def test_same_request_replay_does_not_dispatch_again() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    service = _service(repository, provider)
    request = _request()

    first = service.request_recommendation(_session(), _profile(), request)
    replay = service.request_recommendation(_session(), _profile(), request)

    assert len(provider.calls) == 1
    assert replay == first
    assert repository.requests[request.request_id].dispatch_count == 1


def test_pre_provider_failure_is_not_counted_as_an_oci_dispatch() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    settings = Settings(_env_file=None, recommendation_llm_selection_enabled=False)
    service = StructuredRecommendationService(
        repository,  # type: ignore[arg-type]
        settings,
        DemoControl(),
        generator=RecommendationGenerator(settings, provider=provider),
    )

    result = service.request_recommendation(_session(), _profile(), _request())

    assert result.status == "SEARCH_FALLBACK"
    assert provider.calls == []
    assert repository.requests["recommendation-request-0001"].dispatch_count == 0


def test_terminal_get_refreshes_server_fields_without_generation() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    service = _service(repository, provider)
    created = service.request_recommendation(_session(), _profile(), _request())
    assert created.status == "RECOMMENDED"
    original = created.recommendations[1]
    updated_menu = original.menu.model_copy(
        update={"price": 12_345, "delivery_fee": 777, "eta_min": 9, "eta_max": 18}
    )
    repository.live_states = {
        "menu-b": LiveRecommendationMenuState(
            menu=updated_menu,
            halal_certified=True,
            halal_scope_label="Certification applies specifically to this menu.",
            vegan_status="LIKELY_FIT",
        )
    }

    reloaded = service.get_request(_session().session_id, _request().request_id)

    assert reloaded is not None
    assert [item.menu.menu_id for item in reloaded.recommendations] == ["menu-b"]
    refreshed = reloaded.recommendations[0]
    assert refreshed.rank == 1
    assert refreshed.menu.price == 12_345
    assert refreshed.menu.delivery_fee == 777
    assert refreshed.menu.eta_min == 9
    assert refreshed.menu.eta_max == 18
    assert refreshed.halal_certified is True
    assert refreshed.title == original.title
    assert refreshed.selection_reason == original.selection_reason
    assert refreshed.description == original.description
    assert refreshed.wiki_passages == original.wiki_passages
    assert len(provider.calls) == 1

    repository.live_states = {}
    empty = service.get_request(_session().session_id, _request().request_id)
    assert empty is not None
    assert empty.status == "NO_MATCH"
    assert empty.snapshot_id is None
    assert empty.recommendations == []
    assert empty.failure_code == "LIVE_ELIGIBILITY_EMPTY"
    assert len(provider.calls) == 1


def test_invalid_provider_output_falls_back_without_second_dispatch() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-outside-pool", "menu-b", "menu-c"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert len(provider.calls) == 1
    assert result.status == "SEARCH_FALLBACK"
    assert [item.menu.menu_id for item in result.recommendations] == [
        "menu-a",
        "menu-b",
        "menu-c",
    ]
    assert result.failure_code == "GROUNDING_REJECTED"
    assert (
        repository.requests[result.request_id].ranking_trace_json["grounding_rejection_code"]
        == "MENU_OUTSIDE_SHORTLIST"
    )
    assert (
        repository.requests[result.request_id].ranking_trace_json["grounding_rejection_stage"]
        == "SELECTION_POLICY"
    )
    assert repository.completed_statuses == [RecommendationRequestStatus.SEARCH_FALLBACK]


def test_provider_failure_keeps_the_same_frozen_top_three_and_order() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.99),
        _pool_item("menu-b", score=0.98),
        _pool_item("menu-c", score=0.97),
        _pool_item("menu-d", score=0.96),
    ]
    provider = FailingProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert len(provider.calls) == 1
    assert result.status == "SEARCH_FALLBACK"
    assert [item.menu.menu_id for item in result.recommendations] == [
        "menu-a",
        "menu-b",
        "menu-c",
    ]
    assert result.failure_code == "PROVIDER_UNAVAILABLE"
    for item in result.recommendations:
        assert 1 <= len(re.findall(r"[.!?。！？]", item.yobi_short_explanation or "")) <= 2
        assert 3 <= len(re.findall(r"[.!?。！？]", item.yobi_long_explanation or "")) <= 5
        assert 2 <= len(re.findall(r"[.!?。！？]", item.review_summary or "")) <= 3
        assert not re.search(r"[가-힣]", item.review_summary or "")
    assert all(
        item.matched_criteria
        == [
            {
                "category_code": "cuisine_origins",
                "selected_value_codes": ["KOREAN"],
                "evidence_ids": [
                    f"evidence-cuisine-{item.menu.menu_id.rsplit('-', maxsplit=1)[-1]}"
                ],
            },
            {
                "category_code": "flavors",
                "selected_value_codes": ["SPICY"],
                "evidence_ids": [
                    f"evidence-flavor-{item.menu.menu_id.rsplit('-', maxsplit=1)[-1]}"
                ],
            },
        ]
        for item in result.recommendations
    )


def test_comparison_is_cached_once_per_snapshot_across_idempotency_keys() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    service = _service(repository, provider)
    batch = service.request_recommendation(_session(), _profile(), _request())
    assert batch.snapshot_id is not None
    provider.output = {
        "summary": "A grounded comparison.",
        "items": [
            {
                "menu_id": menu_id,
                "name": "Untrusted model name",
                "key_difference": "A current menu fact differs.",
                "taste_texture": "A reviewed general passage is summarized.",
                "ingredients_form": "Restaurant ingredients are not verified.",
                "spice_heaviness": "The server spice value is used.",
                "eating_context": "The server serving range is used.",
                "best_for": "Choose according to the grounded card.",
                "unverified_dietary_info": "Untrusted model dietary prose.",
            }
            for menu_id in ("menu-a", "menu-b", "menu-c")
        ],
    }
    first = service.compare_recommendations(
        _session(),
        _profile(),
        RecommendationComparisonRequest(
            snapshot_id=batch.snapshot_id,
            request_id=_request().request_id,
            idempotency_key="comparison-key-one",
        ),
    )
    replay = service.compare_recommendations(
        _session(),
        _profile(),
        RecommendationComparisonRequest(
            snapshot_id=batch.snapshot_id,
            request_id=_request().request_id,
            idempotency_key="comparison-key-two",
        ),
    )

    assert len(provider.calls) == 2  # one recommendation call and one comparison call
    assert replay == first
    assert [item.name for item in first.items] == ["Dish A", "Dish B", "Dish C"]
    assert all(
        item.unverified_dietary_info
        == (
            "Restaurant ingredients, certification, and cross-contact are unverified "
            "unless shown in current server facts."
        )
        for item in first.items
    )


def test_invalid_comparison_output_falls_back_with_same_ids_names_and_order() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    service = _service(repository, provider)
    batch = service.request_recommendation(_session(), _profile(), _request())
    assert batch.snapshot_id is not None
    provider.output = {
        "summary": "The model tried to reorder the frozen batch.",
        "items": [
            {
                "menu_id": menu_id,
                "name": "Invented name",
                "key_difference": "Difference",
                "taste_texture": "Taste",
                "ingredients_form": "Ingredients",
                "spice_heaviness": "Spice",
                "eating_context": "Context",
                "best_for": "Best for",
                "unverified_dietary_info": "Unverified",
            }
            for menu_id in ("menu-c", "menu-b", "menu-a")
        ],
    }

    comparison = service.compare_recommendations(
        _session(),
        _profile(),
        RecommendationComparisonRequest(
            snapshot_id=batch.snapshot_id,
            request_id=_request().request_id,
            idempotency_key="comparison-invalid-0001",
        ),
    )

    assert len(provider.calls) == 2
    assert comparison.generated_by == "DETERMINISTIC_FALLBACK"
    assert [item.menu_id for item in comparison.items] == ["menu-a", "menu-b", "menu-c"]
    assert [item.name for item in comparison.items] == ["Dish A", "Dish B", "Dish C"]


def test_korean_and_arabic_fallbacks_follow_effective_display_language() -> None:
    expected = {
        "한국어": {
            "selection": "선택한 선호 조건에 가장 가까운 서버 정렬 결과입니다.",
            "summary": "현재 메뉴 정보와 검토된 일반 음식 자료만으로 비교했습니다. 추천 순서는 그대로입니다.",
            "warning": (
                "현재 서버 정보에 명시되지 않은 식당별 재료, 인증, 교차접촉 가능성은 "
                "확인되지 않았습니다."
            ),
        },
        "العربية": {
            "selection": "The closest server-ranked match to your selected preferences.",
            "summary": (
                "Compared with current menu facts and reviewed general food references. "
                "The recommendation order is unchanged."
            ),
            "warning": (
                "Restaurant ingredients, certification, and cross-contact are unverified "
                "unless shown in current server facts."
            ),
        },
    }
    for index, language in enumerate(("한국어", "العربية"), start=1):
        profile = _profile().model_copy(update={"preferred_language": language})
        repository = FakeRecommendationRepository(_criteria())
        repository.evidence_pool = [
            _pool_item("menu-a", score=0.90),
            _pool_item("menu-b", score=0.80),
            _pool_item("menu-c", score=0.70),
        ]
        provider = FailingProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
        service = _service(repository, provider)
        request = _request(f"recommendation-localized-fallback-{index:04d}")

        batch = service.request_recommendation(_session(), profile, request)

        assert batch.status == "SEARCH_FALLBACK"
        assert all(
            item.selection_reason == expected[language]["selection"]
            for item in batch.recommendations
        )
        assert batch.snapshot_id is not None
        comparison = service.compare_recommendations(
            _session(),
            profile,
            RecommendationComparisonRequest(
                snapshot_id=batch.snapshot_id,
                request_id=request.request_id,
                idempotency_key=f"comparison-localized-fallback-{index:04d}",
            ),
        )
        assert comparison.generated_by == "DETERMINISTIC_FALLBACK"
        assert comparison.summary == expected[language]["summary"]
        assert all(
            item.unverified_dietary_info == expected[language]["warning"]
            for item in comparison.items
        )
        localized_fields = [
            comparison.summary,
            *[
                value
                for item in comparison.items
                for value in (
                    item.key_difference,
                    item.ingredients_form,
                    item.spice_heaviness,
                    item.eating_context,
                    item.best_for,
                    item.unverified_dietary_info,
                )
            ],
        ]
        assert all("=" not in value for value in localized_fields)
        if language == "한국어":
            assert all("unverified" not in value.lower() for value in localized_fields)
        if language == "한국어":
            assert [item.name for item in comparison.items] == ["메뉴 A", "메뉴 B", "메뉴 C"]

        normal_repository = FakeRecommendationRepository(_criteria())
        normal_repository.evidence_pool = list(repository.evidence_pool)
        normal_provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
        normal_service = _service(normal_repository, normal_provider)
        normal_request = _request(f"recommendation-localized-normal-{index:04d}")
        normal_batch = normal_service.request_recommendation(_session(), profile, normal_request)
        assert normal_batch.snapshot_id is not None
        assert "locale is English" in normal_provider.calls[0]["instructions"]
        normal_provider.output = {
            "summary": "Locale-specific provider summary.",
            "items": [
                {
                    "menu_id": menu_id,
                    "name": "Provider name",
                    "key_difference": "Provider comparison",
                    "taste_texture": "Provider comparison",
                    "ingredients_form": "Provider comparison",
                    "spice_heaviness": "Provider comparison",
                    "eating_context": "Provider comparison",
                    "best_for": "Provider comparison",
                    "unverified_dietary_info": "Provider warning",
                }
                for menu_id in ("menu-a", "menu-b", "menu-c")
            ],
        }
        normal_comparison = normal_service.compare_recommendations(
            _session(),
            profile,
            RecommendationComparisonRequest(
                snapshot_id=normal_batch.snapshot_id,
                request_id=normal_request.request_id,
                idempotency_key=f"comparison-localized-normal-{index:04d}",
            ),
        )
        assert normal_comparison.generated_by == "LLM"
        assert all(
            item.unverified_dietary_info == expected[language]["warning"]
            for item in normal_comparison.items
        )
        if language == "한국어":
            assert [item.name for item in normal_comparison.items] == [
                "메뉴 A",
                "메뉴 B",
                "메뉴 C",
            ]


def test_generation_soft_profile_context_excludes_sensitive_legacy_fields() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
        _pool_item("menu-c", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b", "menu-c"]))
    service = _service(repository, provider)

    service.request_recommendation(_session(), _profile(), _request())

    assert len(provider.calls) == 1
    generation_input = json.loads(provider.calls[0]["input"][0]["content"])
    assert generation_input["soft_profile_context"] == {}
    serialized_context = json.dumps(generation_input["soft_profile_context"])
    assert "dietary_rules" not in serialized_context
    assert "religion" not in serialized_context
    assert "allergy" not in serialized_context
    assert "nationality" not in serialized_context
    assert "age_band" not in serialized_context
    assert "favorite_foods" not in serialized_context
    compact_item = generation_input["evidence_pool"][0]
    assert len(compact_item["wiki_passages"]) <= 2
    assert {
        "ranking_trace",
        "knowledge_release_id",
        "catalog_release_id",
        "recommendation_release_family_id",
        "menu_facts",
    }.isdisjoint(compact_item)
    criterion_payload = compact_item["criterion_evidence"]
    assert criterion_payload == {
        "cuisine_origins": ["KOREAN"],
        "flavors": ["SPICY"],
    }
    assert set(compact_item["wiki_passages"][0]) == {"content"}


def test_stale_dispatched_request_becomes_unknown_without_redispatch() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    request = _request()
    repository.requests[request.request_id] = RecommendationRequestRecord(
        request_id=request.request_id,
        session_id=_session().session_id,
        request_hash="a" * 64,
        criteria_version=request.criteria_version,
        mode=request.mode,
        status=RecommendationRequestStatus.DISPATCHED,
        state_version=request.expected_state_version,
        release_family_id="recommendation-family-v1",
        eligibility_as_of=datetime.now(timezone.utc) - timedelta(minutes=5),
        evidence_pool_json=[],
        dispatch_count=1,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=4),
    )

    result = service.get_request(_session().session_id, request.request_id)

    assert result is not None
    assert result.status == "FAILED"
    assert result.failure_code == "DISPATCH_RESULT_UNKNOWN"
    assert repository.requests[request.request_id].status is (
        RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH
    )
    assert provider.calls == []


def test_oracle_naive_dispatched_timestamp_is_compared_as_utc() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    request = _request()
    repository.requests[request.request_id] = RecommendationRequestRecord(
        request_id=request.request_id,
        session_id=_session().session_id,
        request_hash="d" * 64,
        criteria_version=request.criteria_version,
        mode=request.mode,
        status=RecommendationRequestStatus.DISPATCHED,
        state_version=request.expected_state_version,
        release_family_id="recommendation-family-v1",
        eligibility_as_of=datetime.now(timezone.utc) - timedelta(minutes=5),
        evidence_pool_json=[],
        dispatch_count=1,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        dispatched_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=4),
    )

    result = service.get_request(_session().session_id, request.request_id)

    assert result is not None
    assert result.failure_code == "DISPATCH_RESULT_UNKNOWN"


def test_stale_shortlist_owner_loss_is_not_reported_as_a_provider_dispatch() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    request = _request()
    repository.requests[request.request_id] = RecommendationRequestRecord(
        request_id=request.request_id,
        session_id=_session().session_id,
        request_hash="c" * 64,
        criteria_version=request.criteria_version,
        mode=request.mode,
        status=RecommendationRequestStatus.DISPATCHED,
        state_version=request.expected_state_version,
        release_family_id="recommendation-family-v1",
        eligibility_as_of=datetime.now(timezone.utc) - timedelta(minutes=5),
        evidence_pool_json=[],
        dispatch_count=0,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=4),
    )

    result = service.get_request(_session().session_id, request.request_id)

    assert result is not None
    assert result.status == "FAILED"
    assert result.failure_code == "PROVIDER_CALL_OWNER_LOST"
    assert repository.requests[request.request_id].dispatch_count == 0
    assert provider.calls == []


def test_stale_created_request_stays_resumable_without_dispatch() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    request = _request()
    repository.requests[request.request_id] = RecommendationRequestRecord(
        request_id=request.request_id,
        session_id=_session().session_id,
        request_hash="b" * 64,
        criteria_version=request.criteria_version,
        mode=request.mode,
        status=RecommendationRequestStatus.CREATED,
        state_version=request.expected_state_version,
        release_family_id="recommendation-family-v1",
        eligibility_as_of=datetime.now(timezone.utc) - timedelta(minutes=5),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    result = service.get_request(_session().session_id, request.request_id)

    assert result is not None
    assert result.status == "PENDING"
    assert result.failure_code is None
    assert repository.requests[request.request_id].status is (RecommendationRequestStatus.CREATED)
    assert repository.requests[request.request_id].dispatch_count == 0
    assert provider.calls == []


def test_created_request_can_be_claimed_once_for_poll_recovery() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    request = _request()
    repository.requests[request.request_id] = RecommendationRequestRecord(
        request_id=request.request_id,
        session_id=_session().session_id,
        request_hash="b" * 64,
        criteria_version=request.criteria_version,
        mode=request.mode,
        status=RecommendationRequestStatus.CREATED,
        state_version=request.expected_state_version,
        release_family_id="recommendation-family-v1",
        eligibility_as_of=datetime.now(timezone.utc) - timedelta(minutes=5),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    first, resumable = service.recover_request(
        _session(),
        _profile(),
        request.request_id,
    )
    second, duplicate_work = service.recover_request(
        _session(),
        _profile(),
        request.request_id,
    )

    assert first is not None and first.status == "PENDING"
    assert second is not None and second.status == "PENDING"
    assert resumable == request
    assert duplicate_work is None


def test_cross_worker_duplicate_dispatch_never_reaches_provider() -> None:
    class DuplicateDispatchRepository(FakeRecommendationRepository):
        def mark_recommendation_dispatched(
            self,
            session_id: str,
            request_id: str,
            evidence_pool: list[EvidencePoolItem],
        ) -> RecommendationRequestRecord:
            dispatched = super().mark_recommendation_dispatched(
                session_id,
                request_id,
                evidence_pool,
            )
            duplicate = dispatched.model_copy(update={"duplicate": True})
            self.requests[request_id] = duplicate
            return duplicate

    repository = DuplicateDispatchRepository(_criteria())
    repository.evidence_pool = [_pool_item("menu-a", score=0.9)]
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    request = _request()
    pending, should_process = service.begin_recommendation(
        _session(),
        _profile(),
        request,
    )

    result = service.process_reserved_recommendation(
        _session(),
        _profile(),
        request,
    )

    assert pending.status == "PENDING"
    assert should_process is True
    assert result.status == "PENDING"
    assert result.phase == "GENERATING"
    assert provider.calls == []
    assert repository.requests[request.request_id].dispatch_count == 0


def test_recommendation_endpoint_uses_overridden_service_contract() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_structured_recommendation_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/sessions/session-structured/recommendations",
            json=_request("recommendation-request-api-0001").model_dump(mode="json"),
        )
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert response.json()["phase"] == "RETRIEVING"
    completed = service.get_request("session-structured", "recommendation-request-api-0001")
    assert completed is not None
    assert completed.status == "NO_MATCH"
    assert provider.calls == []
