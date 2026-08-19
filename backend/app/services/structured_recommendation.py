from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from app.core.config import Settings
from app.core.logging import log_event
from app.db.repository import YobiRepository
from app.domain.concept_ranking import RANKING_POLICY_VERSION
from app.domain.dialogue import (
    RecommendationCandidate,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.domain.models import Profile, Session
from app.domain.preference_catalog import PREFERENCE_OPTIONS, normalize_preference_locale
from app.domain.recommendation_copy import (
    deterministic_presentation_copy,
    localized_recommendation_fallback_copy,
)
from app.domain.structured_recommendation import (
    EvidencePoolItem,
    RecommendationBatchV2,
    RecommendationComparisonItemV2,
    RecommendationComparisonRequest,
    RecommendationComparisonV2,
    RecommendationCriteriaCommit,
    RecommendationCriteriaRecord,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationPreviewV2,
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


def _effective_display_language(preferred_language: str) -> tuple[str, str]:
    """Keep backend-generated copy aligned with the three UI display languages."""

    requested = normalize_preference_locale(preferred_language)
    if requested == "ko":
        return "ko", "한국어"
    if requested == "ja":
        return "ja", "日本語"
    return "en", "English"


def _utc_datetime(value: datetime) -> datetime:
    """Normalize Oracle TIMESTAMP values before comparing request deadlines."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def compact_generation_payload(
    item: EvidencePoolItem,
    *,
    max_wiki_passages: int,
) -> dict[str, Any]:
    """Keep grounding fields while dropping persistence-only ranking metadata."""

    payload = item.generation_payload()
    payload["wiki_passages"] = payload["wiki_passages"][:max_wiki_passages]
    for operational_key in (
        "ranking_trace",
        "knowledge_release_id",
        "catalog_release_id",
        "recommendation_release_family_id",
        "menu_facts",
    ):
        payload.pop(operational_key, None)
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
        self._preference_selection_metrics: dict[str, dict[str, float | int]] = {}
        self._comparison_locks: dict[str, Lock] = {}
        self._request_locks: dict[str, Lock] = {}
        self._request_registry_lock = Lock()
        self._active_request_keys: set[str] = set()

    def commit_criteria(
        self,
        session: Session,
        commit: RecommendationCriteriaCommit,
    ) -> RecommendationCriteriaRecord:
        if not commit.criteria.has_explicit_preference:
            raise ValueError("RECOMMENDATION_CRITERIA_EMPTY")
        preview = self.repository.preview_recommendation(
            session.session_id,
            commit.criteria,
        )
        safety_reasons = {
            "HALAL_CERTIFICATION_UNAVAILABLE",
            "VEGAN_EVIDENCE_UNAVAILABLE",
            "SPICE_LEVEL_UNAVAILABLE",
        }
        blocked = next(
            (reason for reason in preview.zero_reason_codes if reason in safety_reasons),
            None,
        )
        if blocked is not None and preview.ranking_policy_version == RANKING_POLICY_VERSION:
            raise ValueError(blocked)
        record = self.repository.save_recommendation_criteria(session.session_id, commit)
        metric = self._preference_selection_metrics.pop(session.session_id, None)
        selected_option_count = sum(
            len(values) for values in commit.criteria.subjective_groups().values()
        ) + len(commit.criteria.price_bands) + int(commit.criteria.price_range_krw is not None)
        log_event(
            logging.getLogger("yobi"),
            event="recommendation_preference_committed",
            session_id_hash=hashlib.sha256(session.session_id.encode()).hexdigest(),
            selected_category_count=len(commit.criteria.subjective_groups()),
            selected_option_count=selected_option_count,
            selection_elapsed_ms=(
                int((monotonic() - float(metric["started"])) * 1000) if metric else None
            ),
            criteria_version=record.criteria_version,
        )
        return record

    def preview(
        self,
        session: Session,
        criteria: RecommendationCriteriaV2,
    ) -> RecommendationPreviewV2:
        result = self.repository.preview_recommendation(session.session_id, criteria)
        selected_option_count = sum(
            len(values) for values in criteria.subjective_groups().values()
        ) + len(criteria.price_bands)
        previous = self._preference_selection_metrics.get(session.session_id)
        previous_count = int(previous["last_option_count"]) if previous else 0
        action = (
            "reset"
            if previous_count > 0 and selected_option_count == 0
            else (
                "remove"
                if selected_option_count < previous_count
                else ("add" if selected_option_count > previous_count else "no_change")
            )
        )
        self._preference_selection_metrics[session.session_id] = {
            "started": float(previous["started"]) if previous else monotonic(),
            "last_option_count": selected_option_count,
        }
        log_event(
            logging.getLogger("yobi"),
            event="recommendation_preference_preview",
            session_id_hash=hashlib.sha256(session.session_id.encode()).hexdigest(),
            action=action,
            selected_category_count=len(criteria.subjective_groups()),
            selected_option_count=selected_option_count,
            zero_result=result.eligible_menu_count == 0,
            zero_reason_codes=result.zero_reason_codes,
            eligible_menu_count=result.eligible_menu_count,
            eligible_merchant_count=result.eligible_merchant_count,
            preview_timing_ms=result.timing_ms,
            release_id=result.release_id,
        )
        return result

    def request_recommendation(
        self,
        session: Session,
        profile: Profile,
        request: RecommendationRequestInput,
    ) -> RecommendationBatchV2:
        """Run the recommendation synchronously for CLI/smoke compatibility.

        The public HTTP route uses :meth:`begin_recommendation` and schedules
        :meth:`process_reserved_recommendation` after returning ``PENDING``.
        Keeping this wrapper preserves deterministic unit tests and operational
        harnesses without making the browser hold one long-lived request open.
        """

        pending, should_process = self.begin_recommendation(session, profile, request)
        if not should_process:
            return pending
        return self.process_reserved_recommendation(session, profile, request)

    def begin_recommendation(
        self,
        session: Session,
        profile: Profile,
        request: RecommendationRequestInput,
    ) -> tuple[RecommendationBatchV2, bool]:
        """Reserve one idempotent request and return immediately.

        The boolean is true only when this process claims the request for
        background work. A duplicate POST can therefore resume a CREATED row
        after a process restart, while the database dispatch transition still
        prevents a second provider call.
        """

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
        should_process = (
            record.status is RecommendationRequestStatus.CREATED
            and self._claim_request_processing(session.session_id, request.request_id)
        )
        return self._live_batch(record), should_process

    def process_reserved_recommendation(
        self,
        session: Session,
        profile: Profile,
        request: RecommendationRequestInput,
    ) -> RecommendationBatchV2:
        """Finish one already-reserved request exactly once.

        FastAPI executes this synchronous function in its background thread
        pool. The per-request lock protects the single-worker deployment from
        accidental duplicate scheduling while the database reservation remains
        the cross-request idempotency boundary.
        """

        lock_key = self._request_lock_key(session.session_id, request.request_id)
        lock = self._request_locks.setdefault(lock_key, Lock())
        try:
            with lock:
                try:
                    return self._process_reserved_recommendation(session, profile, request)
                except Exception as exc:
                    return self._fail_unhandled_background_request(
                        session=session,
                        request=request,
                        exc=exc,
                    )
        finally:
            with self._request_registry_lock:
                self._active_request_keys.discard(lock_key)
                if self._request_locks.get(lock_key) is lock:
                    self._request_locks.pop(lock_key, None)

    @staticmethod
    def _request_lock_key(session_id: str, request_id: str) -> str:
        return f"{session_id}:{request_id}"

    def _claim_request_processing(self, session_id: str, request_id: str) -> bool:
        """Claim one process-local worker slot for a persisted CREATED row."""

        lock_key = self._request_lock_key(session_id, request_id)
        with self._request_registry_lock:
            if lock_key in self._active_request_keys:
                return False
            self._active_request_keys.add(lock_key)
            return True

    def _process_reserved_recommendation(
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
        criteria_ms = int((monotonic() - started) * 1000)
        if criteria_record is None:
            raise KeyError("RECOMMENDATION_CRITERIA_NOT_FOUND")
        record = self.repository.get_recommendation_request(
            session.session_id,
            request.request_id,
        )
        if record is None:
            raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
        if record.client_cancelled_at is not None:
            return self._live_batch(record)
        if record.status is not RecommendationRequestStatus.CREATED:
            return self._live_batch(record)

        retrieval_started = monotonic()
        evidence_pool = self.repository.build_recommendation_evidence_pool(
            session.session_id,
            profile,
            criteria_record.criteria,
            request.mode,
            self.settings.recommendation_candidate_limit,
            release_family_id=record.release_family_id,
            eligibility_as_of=record.eligibility_as_of,
            raw_hits_per_value=self.settings.recommendation_raw_hits_per_value,
            passages_per_menu=self.settings.recommendation_passages_per_menu,
        )
        retrieval_ms = int((monotonic() - retrieval_started) * 1000)
        metrics_reader = getattr(
            self.repository,
            "get_recommendation_retrieval_metrics",
            None,
        )
        retrieval_metrics = metrics_reader(session.session_id) if callable(metrics_reader) else {}
        freeze_started = monotonic()
        evidence_pool = self._freeze_server_candidates(
            evidence_pool,
            limit=self.settings.recommendation_llm_shortlist_limit,
        )
        freeze_ms = int((monotonic() - freeze_started) * 1000)
        if not evidence_pool:
            exhausted = request.mode in {
                RecommendationMode.SIMILAR,
                RecommendationMode.RETRY,
            }
            persistence_started = monotonic()
            completed = self.repository.complete_recommendation_request(
                session.session_id,
                request.request_id,
                RecommendationRequestStatus.NO_RESULTS,
                result_json={
                    "status": "NO_MATCH",
                    "criteria_summary": self._criteria_fallback_summary(
                        criteria_record,
                        profile.preferred_language,
                    ),
                    "recommendations": [],
                    "unmatched_category_codes": list(criteria_record.criteria.subjective_groups()),
                },
                failure_code="EXHAUSTED" if exhausted else None,
            )
            persistence_ms = int((monotonic() - persistence_started) * 1000)
            self._log_terminal_timing(
                session=session,
                request=request,
                record=completed,
                criteria_ms=criteria_ms,
                retrieval_ms=retrieval_ms,
                retrieval_metrics=retrieval_metrics,
                freeze_ms=freeze_ms,
                provider_ms=0,
                persistence_ms=persistence_ms,
                started=started,
                final_count=0,
            )
            return self._batch_from_record(completed)

        pool_payload = [self._generation_payload(item) for item in evidence_pool]
        dispatched = self.repository.mark_recommendation_dispatched(
            session.session_id,
            request.request_id,
            evidence_pool,
        )
        if (
            dispatched.status is not RecommendationRequestStatus.DISPATCHED
            or dispatched.duplicate
        ):
            return self._batch_from_record(dispatched)

        _display_locale, display_language = _effective_display_language(
            profile.preferred_language
        )
        soft_profile_context = {
            "preferred_language": display_language,
            "country_code": profile.country_code or criteria_record.criteria.spice_reference_country,
        }
        provider_started = monotonic()
        provider_metrics: dict[str, int] = {}

        def mark_provider_call() -> None:
            called = self.repository.mark_recommendation_provider_called(
                session.session_id,
                request.request_id,
            )
            if called.dispatch_count != 1:
                raise RuntimeError("RECOMMENDATION_PROVIDER_CALL_NOT_RECORDED")

        def record_provider_attempt(
            attempt_no: int,
            model_id: str,
            attempt_status: str,
            error_code: str | None,
            latency_ms: int,
            usage: dict[str, int],
        ) -> None:
            recorder = getattr(self.repository, "record_recommendation_provider_attempt", None)
            if callable(recorder):
                recorder(
                    session.session_id,
                    request.request_id,
                    attempt_no=attempt_no,
                    provider=self.settings.genai_provider,
                    model_id=model_id,
                    status=attempt_status,
                    error_code=error_code,
                    latency_ms=latency_ms,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                )

        try:
            if self.demo_control.mode in {"force_fallback", "force_genai_timeout"}:
                raise RuntimeError("DEMO_FORCED_RECOMMENDATION_FALLBACK")
            if not self.settings.recommendation_llm_selection_enabled:
                raise RuntimeError("RECOMMENDATION_LLM_SELECTION_DISABLED")
            generated = self.generator.generate(
                criteria=criteria_record.criteria.model_dump(mode="json"),
                soft_profile_context=soft_profile_context,
                evidence_pool=pool_payload,
                locale=display_language,
                before_provider_call=mark_provider_call,
                on_provider_attempt=record_provider_attempt,
            )
            provider_metrics = generated.provider_metrics
            if generated.status is RecommendationGenerationStatus.NO_MATCH:
                raise ValueError("GENERATOR_NO_MATCH_NOT_AUTHORIZED")
            result_json = self._validated_result_payload(
                generated,
                evidence_pool,
                max_wiki_passages=self.settings.recommendation_llm_passages_per_menu,
            )
            status = RecommendationRequestStatus.COMPLETED
            snapshot = self._snapshot_for_result(
                session=session,
                request_id=request.request_id,
                request_state_version=dispatched.state_version,
                result_json=result_json,
                evidence_pool=evidence_pool,
            )
            provider_ms = int((monotonic() - provider_started) * 1000)
            persistence_started = monotonic()
            completed = self.repository.complete_recommendation_request(
                session.session_id,
                request.request_id,
                status,
                result_json=result_json,
                snapshot=snapshot,
                provider_metrics=provider_metrics,
            )
            persistence_ms = int((monotonic() - persistence_started) * 1000)
        except Exception as exc:
            provider_ms = int((monotonic() - provider_started) * 1000)
            failure_code = self._failure_code(exc)
            grounding_rejection_code = getattr(exc, "safe_reason_code", None)
            grounding_rejection_stage = getattr(exc, "safe_reason_stage", None)
            grounding_rejection_detail = getattr(exc, "safe_reason_detail", None)
            safe_metadata = getattr(exc, "safe_metadata", None)
            if isinstance(safe_metadata, dict):
                provider_metrics = {
                    str(key): int(value)
                    for key, value in safe_metadata.items()
                    if isinstance(key, str)
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                }
            fallback_json = self._search_fallback_payload(
                criteria_record,
                evidence_pool,
                profile.preferred_language,
            )
            fallback_snapshot = self._snapshot_for_result(
                session=session,
                request_id=request.request_id,
                request_state_version=dispatched.state_version,
                result_json=fallback_json,
                evidence_pool=evidence_pool,
            )
            persistence_started = monotonic()
            completed = self.repository.complete_recommendation_request(
                session.session_id,
                request.request_id,
                RecommendationRequestStatus.SEARCH_FALLBACK,
                result_json=fallback_json,
                snapshot=fallback_snapshot,
                failure_code=failure_code,
                provider_metrics=provider_metrics,
                grounding_rejection_code=(
                    grounding_rejection_code if isinstance(grounding_rejection_code, str) else None
                ),
                grounding_rejection_stage=(
                    grounding_rejection_stage
                    if isinstance(grounding_rejection_stage, str)
                    else None
                ),
                grounding_rejection_detail=(
                    grounding_rejection_detail
                    if isinstance(grounding_rejection_detail, str)
                    else None
                ),
            )
            persistence_ms = int((monotonic() - persistence_started) * 1000)
        self._log_terminal_timing(
            session=session,
            request=request,
            record=completed,
            criteria_ms=criteria_ms,
            retrieval_ms=retrieval_ms,
            retrieval_metrics=retrieval_metrics,
            freeze_ms=freeze_ms,
            provider_ms=provider_ms,
            persistence_ms=persistence_ms,
            started=started,
            final_count=len((completed.result_json or {}).get("recommendations", [])),
        )
        return self._live_batch(completed)

    def _fail_unhandled_background_request(
        self,
        *,
        session: Session,
        request: RecommendationRequestInput,
        exc: Exception,
    ) -> RecommendationBatchV2:
        """Persist a safe terminal state when retrieval/setup fails unexpectedly."""

        record = self.repository.get_recommendation_request(
            session.session_id,
            request.request_id,
        )
        if record is None:
            raise exc
        if record.status in {
            RecommendationRequestStatus.COMPLETED,
            RecommendationRequestStatus.NO_RESULTS,
            RecommendationRequestStatus.NO_MATCH,
            RecommendationRequestStatus.SEARCH_FALLBACK,
            RecommendationRequestStatus.FAILED,
            RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH,
        }:
            return self._live_batch(record)

        provider_result_unknown = (
            record.status is RecommendationRequestStatus.DISPATCHED and record.dispatch_count == 1
        )
        terminal_status = (
            RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH
            if provider_result_unknown
            else RecommendationRequestStatus.FAILED
        )
        failure_code = (
            "DISPATCH_RESULT_UNKNOWN"
            if provider_result_unknown
            else (
                "GENERATION_SETUP_FAILED"
                if record.status is RecommendationRequestStatus.DISPATCHED
                else "RETRIEVAL_FAILED"
            )
        )
        try:
            completed = self.repository.complete_recommendation_request(
                session.session_id,
                request.request_id,
                terminal_status,
                failure_code=failure_code,
            )
        except (RuntimeError, ValueError):
            canonical = self.repository.get_recommendation_request(
                session.session_id,
                request.request_id,
            )
            if canonical is None:
                raise exc from None
            completed = canonical
        log_event(
            logging.getLogger("yobi"),
            event="structured_recommendation_background_failed",
            session_id_hash=hashlib.sha256(session.session_id.encode()).hexdigest(),
            request_id_hash=hashlib.sha256(request.request_id.encode()).hexdigest(),
            safe_error_code=failure_code,
            exception_type=type(exc).__name__,
        )
        return self._live_batch(completed)

    @staticmethod
    def _freeze_server_candidates(
        evidence_pool: list[EvidencePoolItem],
        *,
        limit: int,
    ) -> list[EvidencePoolItem]:
        frozen: list[EvidencePoolItem] = []
        wiki_grounded_pool = [item for item in evidence_pool if item.wiki_passages]
        for rank, item in enumerate(wiki_grounded_pool[:limit], start=1):
            trace = {
                **item.ranking_trace,
                "rank": rank,
                "menu_id": item.menu.menu_id,
                "merchant_id": item.menu.merchant_id,
                "ranking_policy_version": item.ranking_trace.get(
                    "ranking_policy_version", "legacy-retrieval-order-v1"
                ),
            }
            frozen.append(item.model_copy(update={"server_rank": rank, "ranking_trace": trace}))
        return frozen

    @staticmethod
    def _log_terminal_timing(
        *,
        session: Session,
        request: RecommendationRequestInput,
        record: RecommendationRequestRecord,
        criteria_ms: int,
        retrieval_ms: int,
        retrieval_metrics: dict[str, Any],
        freeze_ms: int,
        provider_ms: int,
        persistence_ms: int,
        started: float,
        final_count: int,
    ) -> None:
        fields: dict[str, Any] = {
            "event": "structured_recommendation_terminal",
            "session_id_hash": hashlib.sha256(session.session_id.encode()).hexdigest(),
            "request_id_hash": hashlib.sha256(request.request_id.encode()).hexdigest(),
            "mode": request.mode.value,
            "status": record.status.value,
            "criteria_ms": criteria_ms,
            "retrieval_total_ms": retrieval_ms,
            "freeze_ms": freeze_ms,
            "provider_ms": provider_ms,
            "persistence_ms": persistence_ms,
            "total_ms": int((monotonic() - started) * 1000),
            "final_count": final_count,
            "generation_dispatch_count": record.dispatch_count,
            "ranking_policy_version": record.ranking_policy_version,
            "support_manifest_sha256": record.support_manifest_sha256,
            "feature_manifest_sha256": record.feature_manifest_sha256,
            "safe_error_code": record.failure_code,
            "grounding_rejection_code": record.ranking_trace_json.get("grounding_rejection_code"),
            "grounding_rejection_stage": record.ranking_trace_json.get("grounding_rejection_stage"),
            "grounding_rejection_detail": record.ranking_trace_json.get(
                "grounding_rejection_detail"
            ),
        }
        # New-policy repositories expose measured SQL/support/rerank/evidence
        # stages.  Legacy/fake repositories omit them instead of emitting
        # misleading zero placeholders.
        for key in (
            "session_filter_ms",
            "objective_sql_ms",
            "support_lookup_ms",
            "scoring_rerank_ms",
            "evidence_ms",
            "pipeline_ms",
            "query_count",
            "selected_category_count",
            "fetched_candidate_count",
            "candidate_merchant_count",
            "candidate_concept_count",
            "support_row_count",
            "wiki_row_count",
            "semantic_channel_status",
        ):
            if key in retrieval_metrics:
                fields[key] = retrieval_metrics[key]
        log_event(logging.getLogger("yobi"), **fields)

    def get_request(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationBatchV2 | None:
        record = self.repository.get_recommendation_request(session_id, request_id)
        if (
            record is not None
            and record.status is RecommendationRequestStatus.DISPATCHED
            and record.dispatched_at is not None
            and _utc_datetime(record.dispatched_at)
            <= datetime.now(timezone.utc)
            - timedelta(seconds=self.settings.recommendation_request_orphan_seconds)
        ):
            try:
                provider_called = record.dispatch_count == 1
                record = self.repository.complete_recommendation_request(
                    session_id,
                    request_id,
                    (
                        RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH
                        if provider_called
                        else RecommendationRequestStatus.FAILED
                    ),
                    failure_code=(
                        "DISPATCH_RESULT_UNKNOWN" if provider_called else "PROVIDER_CALL_OWNER_LOST"
                    ),
                )
            except (RuntimeError, ValueError):
                # A concurrent owner may have committed while the stale read was
                # being handled. Return that canonical state; never redispatch.
                record = self.repository.get_recommendation_request(session_id, request_id)
        if record is None:
            return None
        return self._live_batch(record)

    def cancel_request(self, session_id: str, request_id: str) -> bool:
        """Detach the browser from a request without discarding audit results."""

        return self.repository.cancel_recommendation_request(session_id, request_id)

    def recover_request(
        self,
        session: Session,
        profile: Profile,
        request_id: str,
    ) -> tuple[RecommendationBatchV2 | None, RecommendationRequestInput | None]:
        """Read a request and claim resumable pre-dispatch work when necessary.

        A provider-dispatched request is never resumed: ``get_request`` keeps
        the existing unknown-result timeout contract for that state. Only a
        persisted CREATED row can be reconstructed and scheduled again, which
        makes browser polling recover a request after an app process restart.
        """

        record = self.repository.get_recommendation_request(session.session_id, request_id)
        if record is None:
            return None, None
        if record.client_cancelled_at is not None:
            return self._live_batch(record), None
        if record.status is RecommendationRequestStatus.CREATED:
            resumable = RecommendationRequestInput(
                request_id=record.request_id,
                expected_state_version=record.state_version,
                criteria_version=record.criteria_version,
                mode=record.mode,
            )
            should_process = self._claim_request_processing(
                session.session_id,
                request_id,
            )
            return self._live_batch(record), resumable if should_process else None
        return self.get_request(session.session_id, request_id), None

    def compare_recommendations(
        self,
        session: Session,
        profile: Profile,
        request: RecommendationComparisonRequest,
    ) -> RecommendationComparisonV2:
        lock_key = f"{session.session_id}:{request.request_id}"
        lock = self._comparison_locks.setdefault(lock_key, Lock())
        with lock:
            return self._compare_recommendations_locked(session, profile, request)

    def _compare_recommendations_locked(
        self,
        session: Session,
        profile: Profile,
        request: RecommendationComparisonRequest,
    ) -> RecommendationComparisonV2:
        record = self.repository.get_recommendation_request(
            session.session_id,
            request.request_id,
        )
        if record is None:
            raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
        if record.snapshot_id != request.snapshot_id:
            raise ValueError("RECOMMENDATION_SNAPSHOT_REQUEST_MISMATCH")
        cached = self.repository.get_recommendation_comparison(
            session.session_id,
            request.request_id,
            request.idempotency_key,
        )
        if cached is not None:
            return RecommendationComparisonV2.model_validate(cached)
        recommendations = list((record.result_json or {}).get("recommendations", []))
        if not 2 <= len(recommendations) <= 3:
            raise ValueError("RECOMMENDATION_COMPARISON_REQUIRES_TWO_MENUS")
        _display_locale, display_language = _effective_display_language(
            profile.preferred_language
        )
        copy = localized_recommendation_fallback_copy(display_language)
        evidence_items = [
            self._comparison_evidence(item, display_language) for item in recommendations
        ]
        try:
            if self.demo_control.mode in {"force_fallback", "force_genai_timeout"}:
                raise RuntimeError("DEMO_FORCED_COMPARISON_FALLBACK")
            generated = self.generator.compare(
                evidence_items=evidence_items,
                locale=display_language,
            )
            response = RecommendationComparisonV2(
                snapshot_id=request.snapshot_id,
                request_id=request.request_id,
                summary=generated.summary,
                items=[
                    RecommendationComparisonItemV2.model_validate(
                        {
                            **item.model_dump(mode="json"),
                            "name": evidence["name"],
                            "unverified_dietary_info": copy.dietary_warning,
                        }
                    )
                    for item, evidence in zip(generated.items, evidence_items)
                ],
                generated_by="LLM",
            )
        except Exception:
            response = self._deterministic_comparison(
                snapshot_id=request.snapshot_id,
                request_id=request.request_id,
                recommendations=recommendations,
                preferred_language=profile.preferred_language,
            )
        stored, _cached = self.repository.save_recommendation_comparison(
            session.session_id,
            request.request_id,
            request.idempotency_key,
            response.model_dump(mode="json"),
        )
        return RecommendationComparisonV2.model_validate(stored)

    @staticmethod
    def _comparison_evidence(
        item: dict[str, Any],
        preferred_language: str,
    ) -> dict[str, Any]:
        raw_menu = item.get("menu")
        menu: dict[str, Any] = raw_menu if isinstance(raw_menu, dict) else {}
        locale, _display_language = _effective_display_language(preferred_language)
        name = (
            str(menu.get("name_ko") or menu.get("name_en") or "MENU")
            if locale == "ko"
            else str(menu.get("name_en") or menu.get("name_ko") or "MENU")
        )
        return {
            "menu_id": str(item.get("menu_id") or menu.get("menu_id") or ""),
            "name": name,
            "category": str(menu.get("category") or ""),
            "description": str(menu.get("description") or ""),
            "cultural_description": str(menu.get("cultural_description") or ""),
            "price_krw": menu.get("price"),
            "spice_level": menu.get("spice_level"),
            "serves_min": menu.get("serves_min"),
            "serves_max": menu.get("serves_max"),
            "dietary_summary": str(menu.get("dietary_summary") or ""),
            "risk_hints": list(menu.get("risk_hints") or []),
            "wiki_passages": [
                {
                    "content": str(passage.get("content") or ""),
                    "evidence_type": str(passage.get("evidence_type") or "WIKI_PASSAGE"),
                }
                for passage in item.get("wiki_passages", [])
                if isinstance(passage, dict)
            ],
        }

    @staticmethod
    def _deterministic_comparison(
        *,
        snapshot_id: str,
        request_id: str,
        recommendations: list[dict[str, Any]],
        preferred_language: str,
    ) -> RecommendationComparisonV2:
        locale, display_language = _effective_display_language(preferred_language)
        copy = localized_recommendation_fallback_copy(display_language)
        items: list[RecommendationComparisonItemV2] = []
        for recommendation in recommendations:
            raw_menu = recommendation.get("menu")
            menu: dict[str, Any] = raw_menu if isinstance(raw_menu, dict) else {}
            menu_id = str(recommendation.get("menu_id") or menu.get("menu_id") or "")
            name = (
                str(menu.get("name_ko") or menu.get("name_en") or "MENU")
                if locale == "ko"
                else str(menu.get("name_en") or menu.get("name_ko") or "MENU")
            )
            passages = [
                str(passage.get("content") or "").strip()
                for passage in recommendation.get("wiki_passages", [])
                if isinstance(passage, dict) and passage.get("content")
            ]
            spice = menu.get("spice_level")
            serves_min = menu.get("serves_min")
            serves_max = menu.get("serves_max")
            eating_context = (
                copy.serves.format(minimum=serves_min, maximum=serves_max)
                if serves_min is not None and serves_max is not None
                else copy.serves_unavailable
            )
            items.append(
                RecommendationComparisonItemV2(
                    menu_id=menu_id,
                    name=name,
                    key_difference=copy.price_difference.format(price=int(menu.get("price") or 0)),
                    taste_texture=(
                        copy.general_reference.format(passage=passages[0])
                        if passages
                        else copy.general_reference_unavailable
                    ),
                    ingredients_form=copy.ingredients_unverified,
                    spice_heaviness=(
                        copy.spice_reviewed.format(level=int(spice))
                        if spice is not None
                        else copy.spice_unavailable
                    ),
                    eating_context=eating_context,
                    best_for=copy.best_for,
                    unverified_dietary_info=copy.dietary_warning,
                )
            )
        return RecommendationComparisonV2(
            snapshot_id=snapshot_id,
            request_id=request_id,
            summary=copy.comparison_summary,
            items=items,
            generated_by="DETERMINISTIC_FALLBACK",
        )

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
    def _criteria_fallback_summary(
        record: RecommendationCriteriaRecord,
        preferred_language: str,
    ) -> str:
        locale, display_language = _effective_display_language(preferred_language)
        copy = localized_recommendation_fallback_copy(display_language)
        groups = record.criteria.subjective_groups()
        values = [
            "/".join(PREFERENCE_OPTIONS[code].labels[locale] for code in selected)
            for selected in groups.values()
        ]
        if record.criteria.schema_version == "3" and record.criteria.price_range_krw:
            values.append(
                f"KRW {record.criteria.price_range_krw.min:,}–"
                f"{record.criteria.price_range_krw.max:,}"
            )
            values.append(record.criteria.spice_preference.lower())
        elif record.criteria.price_bands:
            values.append(
                "/".join(
                    PREFERENCE_OPTIONS[code].labels[locale] for code in record.criteria.price_bands
                )
            )
        if record.criteria.max_spice_level < 5:
            values.append(copy.max_spice.format(level=record.criteria.max_spice_level))
        if record.criteria.dietary_filters.halal_certified_only:
            values.append(copy.halal_only)
        if record.criteria.dietary_filters.vegan:
            values.append(copy.vegan)
        return "; ".join(values) or copy.criteria_default

    def _generation_payload(self, item: EvidencePoolItem) -> dict[str, Any]:
        """Send only fields needed for bounded selection and grounded prose."""

        return compact_generation_payload(
            item,
            max_wiki_passages=self.settings.recommendation_llm_passages_per_menu,
        )

    @staticmethod
    def _validated_result_payload(
        generated: Any,
        evidence_pool: list[EvidencePoolItem],
        *,
        max_wiki_passages: int,
    ) -> dict[str, Any]:
        pool_by_id = {item.menu.menu_id: item for item in evidence_pool}
        recommendations: list[dict[str, Any]] = []
        for rank, generated_item in enumerate(generated.recommendations, start=1):
            pool_item = pool_by_id.get(generated_item.menu_id)
            if pool_item is None:
                raise ValueError("GENERATED_MENU_OUTSIDE_SERVER_SHORTLIST")
            wiki_passages = pool_item.wiki_passages[:max_wiki_passages]
            if not wiki_passages:
                raise ValueError("GENERATED_MENU_WIKI_EVIDENCE_MISSING")
            recommendations.append(
                {
                    **generated_item.model_dump(mode="json"),
                    "rank": rank,
                    "menu_id": pool_item.menu.menu_id,
                    "menu": pool_item.menu.model_copy(
                        update={"localized_title": generated_item.localized_title}
                    ).model_dump(mode="json"),
                    "wiki_evidence_ids": [passage.evidence_id for passage in wiki_passages],
                    "wiki_passages": [passage.model_dump(mode="json") for passage in wiki_passages],
                    "localized_title": generated_item.localized_title,
                    "yobi_short_explanation": generated_item.yobi_short_explanation,
                    "yobi_long_explanation": generated_item.yobi_long_explanation,
                    "source_description": pool_item.menu.description,
                    "review_summary": generated_item.review_summary,
                    "country_preference": pool_item.country_preference,
                    "evidence_ids": [passage.evidence_id for passage in wiki_passages],
                    "review_ids": [
                        str(review.get("review_id"))
                        for review in pool_item.synthetic_reviews
                        if review.get("review_id")
                    ],
                    "generation_model": generated.generation_model,
                    "halal_certified": pool_item.halal_certified,
                    "halal_scope_label": pool_item.halal_scope_label,
                    "vegan_status": pool_item.vegan_status,
                    "vegan_warning": pool_item.vegan_warning,
                }
            )
        return {
            "status": "RECOMMENDED",
            "criteria_summary": generated.criteria_summary,
            "recommendations": recommendations,
            "unmatched_category_codes": generated.unmatched_category_codes,
        }

    @classmethod
    def _search_fallback_payload(
        cls,
        criteria_record: RecommendationCriteriaRecord,
        evidence_pool: list[EvidencePoolItem],
        preferred_language: str,
    ) -> dict[str, Any]:
        locale, display_language = _effective_display_language(preferred_language)
        copy = localized_recommendation_fallback_copy(display_language)
        recommendations: list[dict[str, Any]] = []
        for rank, item in enumerate(evidence_pool[:3], start=1):
            passages = item.wiki_passages[:2]
            description = " ".join(passage.content for passage in passages).strip()
            localized_title = item.localized_title or (
                item.menu.name_ko if locale == "ko" else item.menu.name_en
            )
            presentation_copy = deterministic_presentation_copy(
                locale,
                localized_title=localized_title,
                wiki_passages=[passage.content for passage in passages],
                reviews=item.synthetic_reviews,
            )
            matched_by_category: dict[str, dict[str, list[str]]] = {}
            for criterion in item.criterion_evidence:
                grouped = matched_by_category.setdefault(
                    criterion.category_code,
                    {"selected_value_codes": [], "evidence_ids": []},
                )
                if criterion.selected_value_code not in grouped["selected_value_codes"]:
                    grouped["selected_value_codes"].append(criterion.selected_value_code)
                for reference in criterion.evidence:
                    if reference.evidence_id not in grouped["evidence_ids"]:
                        grouped["evidence_ids"].append(reference.evidence_id)
            recommendations.append(
                {
                    "rank": rank,
                    "menu_id": item.menu.menu_id,
                    "menu": item.menu.model_copy(
                        update={"localized_title": localized_title}
                    ).model_dump(mode="json"),
                    "title": (
                        localized_title
                    ),
                    "selection_reason": copy.search_selection_reason,
                    "description": description or item.menu.description,
                    "localized_title": localized_title,
                    "yobi_short_explanation": presentation_copy.short_explanation,
                    "yobi_long_explanation": presentation_copy.long_explanation,
                    "source_description": item.menu.description,
                    "review_summary": presentation_copy.review_summary,
                    "country_preference": item.country_preference,
                    "evidence_ids": [passage.evidence_id for passage in passages],
                    "review_ids": [
                        str(review.get("review_id"))
                        for review in item.synthetic_reviews
                        if review.get("review_id")
                    ],
                    "generation_model": "DETERMINISTIC_FALLBACK",
                    "matched_criteria": [
                        {
                            "category_code": category_code,
                            "selected_value_codes": values["selected_value_codes"],
                            "evidence_ids": values["evidence_ids"],
                        }
                        for category_code, values in matched_by_category.items()
                    ],
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
            "criteria_summary": cls._criteria_fallback_summary(
                criteria_record,
                preferred_language,
            ),
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
