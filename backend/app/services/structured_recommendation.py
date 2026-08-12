from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from app.core.config import Settings
from app.core.logging import log_event
from app.db.repository import YobiRepository
from app.domain.dialogue import (
    RecommendationCandidate,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.domain.models import Profile, Session
from app.domain.structured_recommendation import (
    EvidencePoolItem,
    RecommendationBatchV2,
    RecommendationCriteriaCommit,
    RecommendationCriteriaRecord,
    RecommendationRequestInput,
    RecommendationRequestRecord,
    RecommendationRequestStatus,
    StructuredRecommendationView,
)
from app.genai.contracts import GenAIProviderError
from app.genai.recommendation_generator import (
    RecommendationGenerationStatus,
    RecommendationGenerator,
)
from app.services.demo_control import DemoControl


class StructuredRecommendationService:
    """V2 orchestration: eligibility/retrieval first, one generation dispatch second."""

    def __init__(
        self,
        repository: YobiRepository,
        settings: Settings,
        demo_control: DemoControl,
        *,
        generator: RecommendationGenerator | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.demo_control = demo_control
        self.generator = generator or RecommendationGenerator(settings)

    def commit_criteria(
        self,
        session: Session,
        commit: RecommendationCriteriaCommit,
    ) -> RecommendationCriteriaRecord:
        if not commit.criteria.has_explicit_preference:
            raise ValueError("RECOMMENDATION_CRITERIA_EMPTY")
        return self.repository.save_recommendation_criteria(session.session_id, commit)

    def request_recommendation(
        self,
        session: Session,
        profile: Profile,
        request: RecommendationRequestInput,
    ) -> RecommendationBatchV2:
        started = monotonic()
        criteria_record = self.repository.get_recommendation_criteria(
            session.session_id,
            request.criteria_version,
        )
        if criteria_record is None:
            raise KeyError("RECOMMENDATION_CRITERIA_NOT_FOUND")
        request_hash = self._request_hash(session, profile, criteria_record, request)
        record = self.repository.reserve_recommendation_request(
            session.session_id,
            request,
            request_hash,
        )
        if record.duplicate or record.status is not RecommendationRequestStatus.CREATED:
            return self._live_batch(record)

        evidence_pool = self.repository.build_recommendation_evidence_pool(
            session.session_id,
            profile,
            criteria_record.criteria,
            request.mode,
            self.settings.recommendation_evidence_pool_limit,
            release_family_id=record.release_family_id,
            eligibility_as_of=record.eligibility_as_of,
            raw_hits_per_value=self.settings.recommendation_raw_hits_per_value,
            passages_per_menu=self.settings.recommendation_passages_per_menu,
        )
        if not evidence_pool:
            completed = self.repository.complete_recommendation_request(
                session.session_id,
                request.request_id,
                RecommendationRequestStatus.NO_RESULTS,
                result_json={
                    "status": "NO_MATCH",
                    "criteria_summary": self._criteria_fallback_summary(criteria_record),
                    "recommendations": [],
                    "unmatched_category_codes": list(criteria_record.criteria.subjective_groups()),
                },
            )
            return self._batch_from_record(completed)

        pool_payload = [self._generation_payload(item) for item in evidence_pool]
        dispatched = self.repository.mark_recommendation_dispatched(
            session.session_id,
            request.request_id,
            evidence_pool,
        )
        if dispatched.status is not RecommendationRequestStatus.DISPATCHED:
            return self._batch_from_record(dispatched)

        soft_profile_context = {
            "preferred_language": profile.preferred_language,
            "nationality": profile.nationality,
            "age_band": profile.age_band,
            "favorite_foods": profile.favorite_foods,
        }
        try:
            if self.demo_control.mode in {"force_fallback", "force_genai_timeout"}:
                raise RuntimeError("DEMO_FORCED_RECOMMENDATION_FALLBACK")
            generated = self.generator.generate(
                criteria=criteria_record.criteria.model_dump(mode="json"),
                soft_profile_context=soft_profile_context,
                evidence_pool=pool_payload,
                locale=profile.preferred_language,
            )
            if generated.status is RecommendationGenerationStatus.NO_MATCH:
                result_json = generated.model_dump(mode="json")
                status = RecommendationRequestStatus.NO_MATCH
                snapshot = None
            else:
                result_json = self._validated_result_payload(generated, evidence_pool)
                status = RecommendationRequestStatus.COMPLETED
                snapshot = self._snapshot_for_result(
                    session=session,
                    request_id=request.request_id,
                    request_state_version=dispatched.state_version,
                    result_json=result_json,
                    evidence_pool=evidence_pool,
                )
            completed = self.repository.complete_recommendation_request(
                session.session_id,
                request.request_id,
                status,
                result_json=result_json,
                snapshot=snapshot,
            )
        except Exception as exc:
            failure_code = self._failure_code(exc)
            fallback_json = self._search_fallback_payload(criteria_record, evidence_pool)
            fallback_snapshot = self._snapshot_for_result(
                session=session,
                request_id=request.request_id,
                request_state_version=dispatched.state_version,
                result_json=fallback_json,
                evidence_pool=evidence_pool,
            )
            completed = self.repository.complete_recommendation_request(
                session.session_id,
                request.request_id,
                RecommendationRequestStatus.SEARCH_FALLBACK,
                result_json=fallback_json,
                snapshot=fallback_snapshot,
                failure_code=failure_code,
            )
        log_event(
            logging.getLogger("yobi"),
            event="structured_recommendation_completed",
            session_id_hash=hashlib.sha256(session.session_id.encode()).hexdigest(),
            request_id=request.request_id,
            mode=request.mode.value,
            eligible_pool_count=len(evidence_pool),
            generation_dispatch_count=completed.dispatch_count,
            generation_status=completed.status.value,
            latency_ms=int((monotonic() - started) * 1000),
            safe_error_code=completed.failure_code,
        )
        return self._live_batch(completed)

    def get_request(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationBatchV2 | None:
        record = self.repository.get_recommendation_request(session_id, request_id)
        if (
            record is not None
            and record.status is RecommendationRequestStatus.CREATED
            and record.created_at
            <= datetime.now(timezone.utc)
            - timedelta(seconds=self.settings.recommendation_request_orphan_seconds)
        ):
            try:
                record = self.repository.complete_recommendation_request(
                    session_id,
                    request_id,
                    RecommendationRequestStatus.FAILED,
                    failure_code="RETRIEVAL_OWNER_LOST",
                )
            except (RuntimeError, ValueError):
                record = self.repository.get_recommendation_request(session_id, request_id)
        if (
            record is not None
            and record.status is RecommendationRequestStatus.DISPATCHED
            and record.dispatched_at is not None
            and record.dispatched_at
            <= datetime.now(timezone.utc)
            - timedelta(seconds=self.settings.recommendation_request_orphan_seconds)
        ):
            try:
                record = self.repository.complete_recommendation_request(
                    session_id,
                    request_id,
                    RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH,
                    failure_code="DISPATCH_RESULT_UNKNOWN",
                )
            except (RuntimeError, ValueError):
                # A concurrent owner may have committed while the stale read was
                # being handled. Return that canonical state; never redispatch.
                record = self.repository.get_recommendation_request(session_id, request_id)
        if record is None:
            return None
        return self._live_batch(record)

    def _live_batch(self, record: RecommendationRequestRecord) -> RecommendationBatchV2:
        session_id = record.session_id
        batch = self._batch_from_record(record)
        if (
            record.status
            not in {
                RecommendationRequestStatus.COMPLETED,
                RecommendationRequestStatus.SEARCH_FALLBACK,
            }
            or not batch.recommendations
        ):
            return batch
        criteria_record = self.repository.get_recommendation_criteria(
            session_id, record.criteria_version
        )
        if criteria_record is None:
            return batch
        live_states = self.repository.get_live_recommendation_menu_states(
            session_id,
            criteria_record.criteria,
            record.release_family_id,
            [item.menu.menu_id for item in batch.recommendations],
            at=datetime.now(timezone.utc),
        )
        refreshed: list[StructuredRecommendationView] = []
        for item in batch.recommendations:
            state = live_states.get(item.menu.menu_id)
            if state is None:
                continue
            live_menu = state.menu.model_copy(
                update={
                    "dietary_summary": item.menu.dietary_summary,
                    "evidence_status": item.menu.evidence_status,
                    "match_reasons": item.menu.match_reasons,
                    "risk_hints": item.menu.risk_hints,
                    "semantic_score": item.menu.semantic_score,
                    "evidence_ids": item.menu.evidence_ids,
                    "grounded_claim_ids": item.menu.grounded_claim_ids,
                    "grounded_passage_ids": item.menu.grounded_passage_ids,
                    "is_synthetic": item.menu.is_synthetic,
                }
            )
            refreshed.append(
                item.model_copy(
                    update={
                        "rank": len(refreshed) + 1,
                        "menu": live_menu,
                        "halal_certified": state.halal_certified,
                        "halal_scope_label": state.halal_scope_label,
                        "vegan_status": state.vegan_status,
                        "vegan_warning": state.vegan_warning,
                    }
                )
            )
        if not refreshed:
            return batch.model_copy(
                update={
                    "snapshot_id": None,
                    "status": "NO_MATCH",
                    "recommendations": [],
                    "failure_code": "LIVE_ELIGIBILITY_EMPTY",
                }
            )
        return batch.model_copy(update={"recommendations": refreshed})

    @staticmethod
    def _request_hash(
        session: Session,
        profile: Profile,
        criteria_record: RecommendationCriteriaRecord,
        request: RecommendationRequestInput,
    ) -> str:
        payload = {
            "session_id": session.session_id,
            "profile_id": profile.profile_id,
            "criteria_hash": criteria_record.criteria_hash,
            "criteria_version": request.criteria_version,
            "mode": request.mode.value,
            "expected_state_version": request.expected_state_version,
            "locale": profile.preferred_language,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _criteria_fallback_summary(record: RecommendationCriteriaRecord) -> str:
        groups = record.criteria.subjective_groups()
        values = ["/".join(selected) for selected in groups.values()]
        return "; ".join(values) or "Your selected meal preferences"

    def _generation_payload(self, item: EvidencePoolItem) -> dict[str, Any]:
        """Bound Wiki prose bodies while retaining criterion-to-evidence IDs."""

        payload = item.generation_payload()
        payload["wiki_passages"] = payload["wiki_passages"][
            : self.settings.recommendation_passages_per_menu
        ]
        criterion_evidence = payload.get("criterion_evidence", {})
        if isinstance(criterion_evidence, dict):
            for category in criterion_evidence.values():
                if not isinstance(category, dict):
                    continue
                for value in category.values():
                    if not isinstance(value, dict):
                        continue
                    references = value.get("evidence", [])
                    if isinstance(references, list):
                        value["evidence"] = [
                            {key: field for key, field in reference.items() if key != "content"}
                            for reference in references
                            if isinstance(reference, dict)
                        ]
        return payload

    @staticmethod
    def _validated_result_payload(
        generated: Any,
        evidence_pool: list[EvidencePoolItem],
    ) -> dict[str, Any]:
        pool_by_id = {item.menu.menu_id: item for item in evidence_pool}
        recommendations: list[dict[str, Any]] = []
        for generated_item in generated.recommendations:
            pool_item = pool_by_id[generated_item.menu_id]
            recommendations.append(
                {
                    **generated_item.model_dump(mode="json"),
                    "menu": pool_item.menu.model_dump(mode="json"),
                    "wiki_passages": [
                        passage.model_dump(mode="json")
                        for passage in pool_item.wiki_passages
                        if passage.evidence_id in generated_item.wiki_evidence_ids
                    ],
                    "halal_certified": pool_item.halal_certified,
                    "halal_scope_label": pool_item.halal_scope_label,
                    "vegan_status": pool_item.vegan_status,
                    "vegan_warning": pool_item.vegan_warning,
                }
            )
        return {
            "status": generated.status.value,
            "criteria_summary": generated.criteria_summary,
            "recommendations": recommendations,
            "unmatched_category_codes": generated.unmatched_category_codes,
        }

    @classmethod
    def _search_fallback_payload(
        cls,
        criteria_record: RecommendationCriteriaRecord,
        evidence_pool: list[EvidencePoolItem],
    ) -> dict[str, Any]:
        recommendations: list[dict[str, Any]] = []
        for rank, item in enumerate(evidence_pool[:3], start=1):
            passages = item.wiki_passages[:2]
            description = " ".join(passage.content for passage in passages).strip()
            recommendations.append(
                {
                    "rank": rank,
                    "menu_id": item.menu.menu_id,
                    "menu": item.menu.model_dump(mode="json"),
                    "title": item.menu.name_en,
                    "selection_reason": "This search result is close to your selected preferences.",
                    "description": description or item.menu.description,
                    "matched_criteria": [],
                    "wiki_evidence_ids": [passage.evidence_id for passage in passages],
                    "wiki_passages": [passage.model_dump(mode="json") for passage in passages],
                    "caution_codes": ["GENERATION_UNAVAILABLE"],
                    "halal_certified": item.halal_certified,
                    "halal_scope_label": item.halal_scope_label,
                    "vegan_status": item.vegan_status,
                    "vegan_warning": item.vegan_warning,
                }
            )
        return {
            "status": "SEARCH_FALLBACK",
            "criteria_summary": cls._criteria_fallback_summary(criteria_record),
            "recommendations": recommendations,
            "unmatched_category_codes": [],
        }

    @staticmethod
    def _failure_code(exc: Exception) -> str:
        if isinstance(exc, GenAIProviderError):
            return exc.code.value
        return str(exc)[:100] or type(exc).__name__.upper()

    @staticmethod
    def _snapshot_for_result(
        *,
        session: Session,
        request_id: str,
        request_state_version: int,
        result_json: dict[str, Any],
        evidence_pool: list[EvidencePoolItem],
    ) -> RecommendationSnapshot:
        """Bridge v2 results to the existing server-owned selection snapshot.

        The snapshot is an authorization boundary for SELECT_MENU, not a chat
        message. Its assistant row is an internal, non-user-visible audit record
        written atomically by the repository.
        """

        snapshot_id = f"snapshot_{uuid4().hex}"
        pool_by_id = {item.menu.menu_id: item for item in evidence_pool}
        recommendations = list(result_json.get("recommendations", []))
        candidates: list[RecommendationCandidate] = []
        cards: list[dict[str, Any]] = []
        grounded_claim_ids: list[str] = []
        grounded_passage_ids: list[str] = []
        shown_menu_ids: list[str] = []
        for index, item in enumerate(recommendations, start=1):
            menu_payload = item.get("menu") or {}
            menu_id = str(item.get("menu_id") or menu_payload.get("menu_id") or "")
            pool_item = pool_by_id.get(menu_id)
            if pool_item is None:
                raise ValueError("SNAPSHOT_MENU_OUTSIDE_EVIDENCE_POOL")
            matched_evidence_ids = [
                str(evidence_id)
                for matched in item.get("matched_criteria", [])
                for evidence_id in matched.get("evidence_ids", [])
            ]
            passage_ids = [str(value) for value in item.get("wiki_evidence_ids", [])]
            claim_ids = [reference.evidence_id for reference in pool_item.menu_facts]
            grounded_claim_ids.extend(claim_ids)
            grounded_passage_ids.extend(passage_ids)
            shown_menu_ids.append(menu_id)
            candidates.append(
                RecommendationCandidate(
                    menu_id=menu_id,
                    merchant_id=pool_item.menu.merchant_id,
                    rank=index,
                    score=round(pool_item.retrieval_score, 6),
                    match_reasons=[str(item.get("selection_reason", ""))],
                    risk_hints=[
                        *[str(value) for value in item.get("caution_codes", [])],
                        *([pool_item.vegan_warning] if pool_item.vegan_warning else []),
                    ],
                    evidence_ids=list(dict.fromkeys([*matched_evidence_ids, *passage_ids])),
                    claim_ids=claim_ids,
                    passage_ids=passage_ids,
                )
            )
            cards.append({"type": "structured_recommendation", "data": {"menu": menu_payload}})

        if not candidates:
            raise ValueError("SNAPSHOT_REQUIRES_SELECTABLE_RESULT")
        need_state = session.meal_need_state.model_copy(deep=True)
        need_state.shown_menu_ids = list(
            dict.fromkeys([*need_state.shown_menu_ids, *shown_menu_ids])
        )
        result = RecommendationResult(
            snapshot_id=snapshot_id,
            candidates=candidates,
            query_summary=str(result_json.get("criteria_summary") or "Selected meal preferences"),
            grounded_claim_ids=list(dict.fromkeys(grounded_claim_ids)),
            grounded_passage_ids=list(dict.fromkeys(grounded_passage_ids)),
            synthetic_data=True,
        )
        return RecommendationSnapshot(
            snapshot_id=snapshot_id,
            session_id=session.session_id,
            assistant_message_id=(
                "msg_a_v2_"
                + hashlib.sha256(f"{session.session_id}:{request_id}".encode()).hexdigest()[:40]
            ),
            state_version=request_state_version + 1,
            meal_need_state=need_state,
            result=result,
            cards=cards,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _batch_from_record(record: RecommendationRequestRecord) -> RecommendationBatchV2:
        result = record.result_json or {}
        status_map: dict[
            RecommendationRequestStatus,
            Literal["PENDING", "RECOMMENDED", "NO_MATCH", "SEARCH_FALLBACK", "FAILED"],
        ] = {
            RecommendationRequestStatus.CREATED: "PENDING",
            RecommendationRequestStatus.DISPATCHED: "PENDING",
            RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH: "FAILED",
            RecommendationRequestStatus.COMPLETED: "RECOMMENDED",
            RecommendationRequestStatus.NO_RESULTS: "NO_MATCH",
            RecommendationRequestStatus.NO_MATCH: "NO_MATCH",
            RecommendationRequestStatus.SEARCH_FALLBACK: "SEARCH_FALLBACK",
            RecommendationRequestStatus.FAILED: "FAILED",
        }
        phase: Literal["RETRIEVING", "GENERATING", "COMPLETE"] = (
            "RETRIEVING"
            if record.status is RecommendationRequestStatus.CREATED
            else (
                "GENERATING"
                if record.status is RecommendationRequestStatus.DISPATCHED
                else "COMPLETE"
            )
        )
        recommendations = [
            StructuredRecommendationView.model_validate(item)
            for item in result.get("recommendations", [])
        ]
        return RecommendationBatchV2(
            session_id=record.session_id,
            request_id=record.request_id,
            snapshot_id=record.snapshot_id,
            state_version=record.state_version,
            criteria_version=record.criteria_version,
            status=status_map[record.status],
            phase=phase,
            criteria_summary=result.get("criteria_summary"),
            recommendations=recommendations,
            unmatched_category_codes=result.get("unmatched_category_codes", []),
            failure_code=record.failure_code,
        )
