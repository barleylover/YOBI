from __future__ import annotations

import json
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
    RecommendationCriteriaCommit,
    RecommendationCriteriaRecord,
    RecommendationCriteriaV2,
    RecommendationRequestInput,
    RecommendationRequestRecord,
    RecommendationRequestStatus,
)
from app.genai.contracts import GenAIServingMode, ProviderCapabilities
from app.genai.recommendation_generator import RecommendationGenerator
from app.main import app
from app.services.demo_control import DemoControl
from app.services.structured_recommendation import StructuredRecommendationService


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
                "dispatch_count": 1,
                "dispatched_at": datetime.now(timezone.utc),
            }
        )
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


def _pool_item(menu_id: str, *, score: float) -> EvidencePoolItem:
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
        wiki_passages=[
            EvidenceReference(
                evidence_id=wiki_id,
                evidence_type="WIKI_PASSAGE",
                content="The dish is commonly served as a satisfying meal.",
            )
        ],
        menu_facts=[],
        halal_certified=False,
        vegan_status="POSSIBLE_WITH_CHECKS",
        vegan_warning="Check the current preparation details.",
        retrieval_score=score,
        knowledge_release_id="knowledge-release-v1",
        catalog_release_id="catalog-release-v1",
        recommendation_release_family_id="recommendation-family-v1",
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
        "wiki_evidence_ids": [f"evidence-wiki-{suffix}"],
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


def _request(request_id: str = "recommendation-request-0001") -> RecommendationRequestInput:
    return RecommendationRequestInput(
        request_id=request_id,
        expected_state_version=1,
        criteria_version=1,
        mode="INITIAL",
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


def test_empty_evidence_pool_returns_no_match_without_generation() -> None:
    repository = FakeRecommendationRepository(_criteria())
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert result.status == "NO_MATCH"
    assert result.recommendations == []
    assert repository.completed_statuses == [RecommendationRequestStatus.NO_RESULTS]
    assert repository.pool_limits == (20, 4)
    assert provider.calls == []


def test_one_dispatch_preserves_model_order_instead_of_retrieval_order() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.99),
        _pool_item("menu-b", score=0.70),
    ]
    provider = FakeProvider(_recommended_output(["menu-b", "menu-a"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert len(provider.calls) == 1
    assert result.status == "RECOMMENDED"
    assert [item.menu.menu_id for item in result.recommendations] == [
        "menu-b",
        "menu-a",
    ]
    stored = repository.requests["recommendation-request-0001"]
    assert stored.dispatch_count == 1
    assert stored.status is RecommendationRequestStatus.COMPLETED


def test_same_request_replay_does_not_dispatch_again() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [_pool_item("menu-a", score=0.90)]
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)
    request = _request()

    first = service.request_recommendation(_session(), _profile(), request)
    replay = service.request_recommendation(_session(), _profile(), request)

    assert len(provider.calls) == 1
    assert replay == first
    assert repository.requests[request.request_id].dispatch_count == 1


def test_terminal_get_refreshes_server_fields_without_generation() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [
        _pool_item("menu-a", score=0.90),
        _pool_item("menu-b", score=0.80),
    ]
    provider = FakeProvider(_recommended_output(["menu-a", "menu-b"]))
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
    ]
    provider = FakeProvider(_recommended_output(["menu-outside-pool"]))
    service = _service(repository, provider)

    result = service.request_recommendation(_session(), _profile(), _request())

    assert len(provider.calls) == 1
    assert result.status == "SEARCH_FALLBACK"
    assert [item.menu.menu_id for item in result.recommendations] == [
        "menu-a",
        "menu-b",
    ]
    assert result.failure_code == "GROUNDING_REJECTED"
    assert repository.completed_statuses == [RecommendationRequestStatus.SEARCH_FALLBACK]


def test_generation_soft_profile_context_excludes_sensitive_legacy_fields() -> None:
    repository = FakeRecommendationRepository(_criteria())
    repository.evidence_pool = [_pool_item("menu-a", score=0.90)]
    provider = FakeProvider(_recommended_output(["menu-a"]))
    service = _service(repository, provider)

    service.request_recommendation(_session(), _profile(), _request())

    assert len(provider.calls) == 1
    generation_input = json.loads(provider.calls[0]["input"][0]["content"])
    assert generation_input["soft_profile_context"] == {
        "preferred_language": "English",
        "nationality": "United States",
        "age_band": "25-34",
        "favorite_foods": ["bibimbap"],
    }
    serialized_context = json.dumps(generation_input["soft_profile_context"])
    assert "dietary_rules" not in serialized_context
    assert "religion" not in serialized_context
    assert "allergy" not in serialized_context
    assert len(generation_input["evidence_pool"][0]["wiki_passages"]) <= 4
    criterion_payload = generation_input["evidence_pool"][0]["criterion_evidence"]
    assert all(
        "content" not in reference
        for category in criterion_payload.values()
        for value in category.values()
        for reference in value["evidence"]
    )


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


def test_stale_created_request_fails_without_dispatch() -> None:
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
    assert result.status == "FAILED"
    assert result.failure_code == "RETRIEVAL_OWNER_LOST"
    assert repository.requests[request.request_id].status is (RecommendationRequestStatus.FAILED)
    assert repository.requests[request.request_id].dispatch_count == 0
    assert provider.calls == []


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

    assert response.status_code == 200
    assert response.json()["status"] == "NO_MATCH"
    assert response.json()["phase"] == "COMPLETE"
    assert provider.calls == []
