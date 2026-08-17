#!/usr/bin/env python3
"""Verify the structured provider-failure fallback against the runtime repository.

The smoke uses a private ``DemoControl`` instance in this process.  It never
changes the public application's failure mode and it never dispatches a provider
request: the server-owned candidate set is frozen first, then the forced timeout
exercises the same deterministic fallback branch used for provider failures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings
from app.db.oracle_repository import OracleYobiRepository
from app.db.repository import YobiRepository
from app.domain.models import ProfileCreate
from app.domain.structured_recommendation import (
    EvidencePoolItem,
    RecommendationCriteriaCommit,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationRequestInput,
    RecommendationRequestStatus,
)
from app.services.demo_control import DemoControl
from app.services.structured_recommendation import StructuredRecommendationService


def _criteria(category_code: str, option_code: str) -> RecommendationCriteriaV2:
    fields: dict[str, Any] = {
        "schema_version": "2",
        "cuisine_origins": [],
        "flavors": [],
        "main_ingredients": [],
        "food_forms": [],
        "temperatures": [],
        "price_bands": [],
        "textures": [],
        "cooking_methods": [],
        "dietary_filters": {
            "halal_certified_only": False,
            "vegan": False,
        },
        "max_spice_level": 5,
        "spice_reference_country": "KR",
    }
    fields[category_code] = [option_code]
    return RecommendationCriteriaV2.model_validate(fields)


def _supported_criteria(
    repository: YobiRepository,
    session_id: str,
    *,
    required_category_code: str | None = None,
    required_option_code: str | None = None,
) -> tuple[RecommendationCriteriaV2, str, str, str]:
    catalog = repository.get_preference_catalog("en")
    if (required_category_code is None) != (required_option_code is None):
        raise RuntimeError("STRUCTURED_FALLBACK_REQUIRED_CRITERIA_INCOMPLETE")
    for category in catalog.get("categories", []):
        category_code = str(category.get("code") or "")
        if not category_code or category_code == "price_bands":
            continue
        if required_category_code is not None and category_code != required_category_code:
            continue
        for option in category.get("options", []):
            option_code = str(option.get("code") or "")
            if not option_code or option.get("active", True) is False:
                continue
            if required_option_code is not None and option_code != required_option_code:
                continue
            criteria = _criteria(category_code, option_code)
            preview = repository.preview_recommendation(session_id, criteria)
            if preview.eligible_menu_count >= 3:
                if not preview.support_manifest_sha256 or not preview.ranking_policy_version:
                    raise RuntimeError("STRUCTURED_FALLBACK_RELEASE_IDENTITY_MISSING")
                return (
                    criteria,
                    str(catalog["catalog_version"]),
                    category_code,
                    option_code,
                )
    if required_category_code is not None:
        raise RuntimeError("STRUCTURED_FALLBACK_REQUIRED_OPTION_UNAVAILABLE")
    raise RuntimeError("STRUCTURED_FALLBACK_ACTIVE_CORE_OPTION_UNAVAILABLE")


def run(
    repository: YobiRepository,
    settings: Settings,
    *,
    required_category_code: str | None = None,
    required_option_code: str | None = None,
) -> dict[str, Any]:
    profile_id: str | None = None
    session_id: str | None = None
    try:
        profile = repository.create_profile(
            ProfileCreate(
                preferred_language="English",
                nationality="United States",
                age_band="Prefer not to say",
                gender="Prefer not to say",
                religion_selection="Prefer not to say",
                dietary_rules=[],
                allergy_severity="mild",
                spice_tolerance=1,
                favorite_foods=[],
                consent_demo_data=True,
                remember_profile=False,
            )
        )
        profile_id = profile.profile_id
        session = repository.create_session(profile.profile_id)
        session_id = session.session_id
        candidates = [
            candidate
            for candidate in repository.resolve_address("YOBI Myeongdong Hotel")
            if candidate.service_area_id
        ]
        if not candidates:
            raise RuntimeError("STRUCTURED_FALLBACK_ADDRESS_CANDIDATE_MISSING")
        repository.save_address(session.session_id, candidates[0], None)

        criteria, catalog_version, category_code, option_code = _supported_criteria(
            repository,
            session.session_id,
            required_category_code=required_category_code,
            required_option_code=required_option_code,
        )
        isolated_control = DemoControl()
        isolated_control.set_mode("force_genai_timeout")
        service = StructuredRecommendationService(
            repository,
            settings,
            isolated_control,
        )
        committed = service.commit_criteria(
            session,
            RecommendationCriteriaCommit(
                criteria=criteria,
                catalog_version=catalog_version,
                expected_state_version=session.state_version,
                request_id=f"fallback-criteria-{uuid4().hex}",
            ),
        )
        current_session = repository.get_session(session.session_id)
        if current_session is None:
            raise RuntimeError("STRUCTURED_FALLBACK_SESSION_MISSING")
        request = RecommendationRequestInput(
            request_id=f"fallback-recommendation-{uuid4().hex}",
            expected_state_version=committed.state_version,
            criteria_version=committed.criteria_version,
            mode=RecommendationMode.INITIAL,
        )
        batch = service.request_recommendation(current_session, profile, request)
        record = repository.get_recommendation_request(session.session_id, request.request_id)
        criteria_record = repository.get_recommendation_criteria(
            session.session_id,
            committed.criteria_version,
        )
        if record is None or criteria_record is None:
            raise RuntimeError("STRUCTURED_FALLBACK_LEDGER_MISSING")
        if (
            batch.status != "SEARCH_FALLBACK"
            or record.status is not RecommendationRequestStatus.SEARCH_FALLBACK
            or record.dispatch_count != 1
            or record.failure_code != "DEMO_FORCED_RECOMMENDATION_FALLBACK"
            or record.snapshot_id != batch.snapshot_id
        ):
            raise RuntimeError("STRUCTURED_FALLBACK_TERMINAL_LEDGER_INVALID")

        frozen_pool = [
            EvidencePoolItem.model_validate(item) for item in record.evidence_pool_json
        ]
        frozen_ids = [item.menu.menu_id for item in frozen_pool[:3]]
        result_ids = [item.menu.menu_id for item in batch.recommendations]
        if not 1 <= len(result_ids) <= 3 or result_ids != frozen_ids:
            raise RuntimeError("STRUCTURED_FALLBACK_SERVER_ORDER_CHANGED")
        expected_payload = service._search_fallback_payload(
            criteria_record,
            frozen_pool,
            profile.preferred_language,
        )
        deterministic_fields = (
            "title",
            "selection_reason",
            "description",
            "matched_criteria",
            "wiki_evidence_ids",
            "wiki_passages",
            "caution_codes",
        )
        stored_result = record.result_json or {}
        expected_items = list(expected_payload.get("recommendations", []))
        stored_items = list(stored_result.get("recommendations", []))
        if (
            stored_result.get("status") != expected_payload.get("status")
            or stored_result.get("criteria_summary")
            != expected_payload.get("criteria_summary")
            or stored_result.get("unmatched_category_codes")
            != expected_payload.get("unmatched_category_codes")
            or len(stored_items) != len(expected_items)
            or any(
                stored.get(field) != expected.get(field)
                for stored, expected in zip(stored_items, expected_items)
                for field in deterministic_fields
            )
        ):
            raise RuntimeError("STRUCTURED_FALLBACK_PAYLOAD_NOT_DETERMINISTIC")
        if not all(
            item.caution_codes == ["GENERATION_UNAVAILABLE"]
            and item.title
            and item.description
            and item.selection_reason
            and any(
                matched.get("category_code") == category_code
                and option_code in matched.get("selected_value_codes", [])
                and bool(matched.get("evidence_ids"))
                for matched in item.matched_criteria
            )
            and "=" not in item.selection_reason
            for item in batch.recommendations
        ):
            raise RuntimeError("STRUCTURED_FALLBACK_EXPLANATION_INVALID")
        replay = service.get_request(session.session_id, request.request_id)
        replay_record = repository.get_recommendation_request(
            session.session_id,
            request.request_id,
        )
        if (
            replay is None
            or [item.menu.menu_id for item in replay.recommendations] != result_ids
            or replay_record is None
            or replay_record.dispatch_count != 1
        ):
            raise RuntimeError("STRUCTURED_FALLBACK_REPLAY_INVALID")

        return {
            "status": "PASS",
            "gate": "structured-provider-fallback",
            "repository_backend": settings.demo_db_backend,
            "exercised_category_code": category_code,
            "exercised_option_code": option_code,
            "result_count": len(result_ids),
            "server_order_preserved": True,
            "deterministic_explanation": True,
            "generation_dispatch_count": 1,
            "failure_mode_scope": "isolated-process-control",
            "profile_cascade_cleanup": True,
        }
    finally:
        primary_error = sys.exc_info()[0] is not None
        cleanup_ok = True
        if profile_id is not None:
            cleanup_ok = repository.delete_profile(profile_id)
            if session_id is not None and repository.get_session(session_id) is not None:
                cleanup_ok = False
        if not cleanup_ok and not primary_error:
            raise RuntimeError("STRUCTURED_FALLBACK_PROFILE_CASCADE_CLEANUP_FAILED")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify deterministic structured recommendation fallback."
    )
    parser.add_argument("--category-code")
    parser.add_argument("--option-code")
    args = parser.parse_args()
    settings = Settings()
    if settings.demo_db_backend != "oracle":
        raise SystemExit("STRUCTURED_FALLBACK_ORACLE_RUNTIME_REQUIRED")
    repository = OracleYobiRepository(settings)
    try:
        repository.initialize()
        print(
            json.dumps(
                run(
                    repository,
                    settings,
                    required_category_code=args.category_code,
                    required_option_code=args.option_code,
                ),
                sort_keys=True,
            )
        )
    finally:
        repository.pool.close()


if __name__ == "__main__":
    main()
