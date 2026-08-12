from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from app.db.sqlite_repository import SQLiteYobiRepository
from app.dependencies import get_repository
from app.domain.dialogue import (
    ConversationEventInput,
    ConversationEventType,
    RecommendationCandidate,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.domain.models import ProfileCreate
from app.domain.preference_catalog import PREFERENCE_CATALOG_VERSION
from app.domain.structured_recommendation import (
    RecommendationCriteriaCommit,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationRequestInput,
    RecommendationRequestStatus,
)
from app.main import app
from app.rag.embeddings import deterministic_embedding


class RecordingEmbeddingProvider:
    model = "yobi-semantic-hash-v1"
    dimension = 1536
    version = "2026-08-06"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def embed(
        self,
        texts: list[str],
        mode: Literal["SEARCH_DOCUMENT", "SEARCH_QUERY"],
    ) -> list[list[float]]:
        self.calls.append((list(texts), mode))
        prefix = "document: " if mode == "SEARCH_DOCUMENT" else "query: "
        return [deterministic_embedding(prefix + text, self.dimension) for text in texts]


def _profile(repository: SQLiteYobiRepository, **overrides: object):
    values = {
        "consent_demo_data": True,
        "preferred_language": "English",
        **overrides,
    }
    return repository.create_profile(ProfileCreate.model_validate(values))


def _commit(
    repository: SQLiteYobiRepository,
    session_id: str,
    criteria: RecommendationCriteriaV2,
    *,
    request_id: str = "criteria-request-0001",
    expected_state_version: int = 0,
):
    return repository.save_recommendation_criteria(
        session_id,
        RecommendationCriteriaCommit(
            criteria=criteria,
            catalog_version=PREFERENCE_CATALOG_VERSION,
            expected_state_version=expected_state_version,
            request_id=request_id,
        ),
    )


def _active_pin(repository: SQLiteYobiRepository) -> tuple[str, datetime]:
    family = repository.get_active_recommendation_release_family()
    assert family is not None
    return family.release_family_id, datetime.now(timezone.utc)


def test_criteria_and_request_ledger_state_and_idempotency(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(repository)
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        price_bands=["UNDER_10000"],
        max_spice_level=5,
    )

    committed = _commit(repository, session.session_id, criteria)
    assert committed.criteria_version == 1
    assert committed.state_version == 1
    assert repository.get_session(session.session_id).state_version == 1  # type: ignore[union-attr]
    assert _commit(repository, session.session_id, criteria) == committed
    assert repository.get_session(session.session_id).state_version == 1  # type: ignore[union-attr]

    request_input = RecommendationRequestInput(
        request_id="recommendation-request-0001",
        expected_state_version=1,
        criteria_version=1,
    )
    reserved = repository.reserve_recommendation_request(
        session.session_id,
        request_input,
        "request-hash-0001",
    )
    assert reserved.state_version == 1
    assert repository.get_session(session.session_id).state_version == 1  # type: ignore[union-attr]
    duplicate = repository.reserve_recommendation_request(
        session.session_id,
        request_input,
        "request-hash-0001",
    )
    assert duplicate.duplicate is True
    assert duplicate.request_id == reserved.request_id

    with repository._connection() as connection:
        connection.execute(
            """
            INSERT INTO recommendation_release_family(
              release_family_id,knowledge_release_id,catalog_release_id,
              preference_catalog_version,spice_reference_version,
              certification_release_id,embedding_model,embedding_version,status,activated_at
            )
            SELECT 'family-after-reservation',knowledge_release_id,catalog_release_id,
                   preference_catalog_version,spice_reference_version,
                   'certification-release-after-reservation',embedding_model,
                   embedding_version,'ACTIVE',?
            FROM recommendation_release_family WHERE release_family_id=?
            """,
            (datetime.now(timezone.utc).isoformat(), reserved.release_family_id),
        )
        connection.execute(
            """
            UPDATE recommendation_runtime_state
            SET active_release_family_id='family-after-reservation',updated_at=?
            WHERE state_key='ACTIVE'
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
    replay_after_release_change = repository.reserve_recommendation_request(
        session.session_id,
        request_input,
        "request-hash-0001",
    )
    assert replay_after_release_change.duplicate is True
    assert replay_after_release_change.release_family_id == reserved.release_family_id
    assert replay_after_release_change.eligibility_as_of == reserved.eligibility_as_of
    pinned_pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        request_input.mode,
        3,
        release_family_id=reserved.release_family_id,
        eligibility_as_of=reserved.eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert pinned_pool
    assert all(
        item.recommendation_release_family_id == reserved.release_family_id for item in pinned_pool
    )

    with pytest.raises(ValueError, match="PREFERENCE_CATALOG_CHANGED"):
        repository.save_recommendation_criteria(
            session.session_id,
            RecommendationCriteriaCommit(
                criteria=criteria,
                catalog_version="stale-catalog-version",
                expected_state_version=1,
                request_id="criteria-request-0002",
            ),
        )


def test_legacy_request_rows_receive_additive_release_pin() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE recommendation_runtime_state(
          state_key TEXT PRIMARY KEY,
          active_release_family_id TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE structured_recommendation_request(
          session_id TEXT NOT NULL,
          request_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY(session_id,request_id)
        );
        INSERT INTO recommendation_runtime_state
          VALUES ('ACTIVE','family-migration-pin','now');
        INSERT INTO structured_recommendation_request
          VALUES ('session-old','request-old','2026-08-12T00:00:00+00:00');
        """
    )

    SQLiteYobiRepository._upgrade_structured_request_pin(connection)

    row = connection.execute("SELECT * FROM structured_recommendation_request").fetchone()
    assert row is not None
    assert row["recommendation_release_family_id"] == "family-migration-pin"
    assert row["eligibility_as_of"] == "2026-08-12T00:00:00+00:00"
    SQLiteYobiRepository._upgrade_structured_request_pin(connection)
    assert (
        connection.execute("SELECT COUNT(*) FROM structured_recommendation_request").fetchone()[0]
        == 1
    )
    connection.close()


def test_preference_catalog_exposes_only_supported_reviewed_options(
    repository: SQLiteYobiRepository,
) -> None:
    catalog = repository.get_preference_catalog("ko")
    family = repository.get_active_recommendation_release_family()
    assert family is not None
    assert catalog["knowledge_release_id"] == family.knowledge_release_id
    exposed = {
        option["code"] for category in catalog["categories"] for option in category["options"]
    }
    assert {"SOUTHEAST_ASIAN", "MEXICAN", "WESTERN", "OVER_30000"}.isdisjoint(exposed)
    assert {"KOREAN", "CHINESE", "UNDER_10000"} <= exposed

    with repository._connection() as connection:
        metrics = repository._preference_support_metrics(connection)
    for code in exposed:
        menu_count, merchant_count, wiki_document_count = metrics[code]
        assert menu_count >= 3
        assert merchant_count >= 2
        assert wiki_document_count >= 1


def test_evidence_pool_uses_one_embedding_batch_public_wiki_and_v2_filters(
    repository: SQLiteYobiRepository,
) -> None:
    recording_provider = RecordingEmbeddingProvider()
    repository.embedding_provider = recording_provider
    profile = _profile(
        repository,
        religion_selection="Islam",
        dietary_rules=["shellfish_allergy", "vegan"],
        allergy_severity="severe",
    )
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        flavors=["SPICY"],
        price_bands=["UNDER_10000"],
        max_spice_level=1,
    )
    release_family_id, eligibility_as_of = _active_pin(repository)
    pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.INITIAL,
        8,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=2,
    )

    assert pool
    assert len(recording_provider.calls) == 1
    texts, mode = recording_provider.calls[0]
    assert mode == "SEARCH_QUERY"
    assert len(texts) == 3
    assert "United States" in texts[-1]
    assert "25-34" in texts[-1]
    assert "creamy pasta" in texts[-1]
    assert all(len(item.wiki_passages) <= 2 for item in pool)
    assert all(item.menu.price < 10_000 and item.menu.spice_level <= 1 for item in pool)
    assert all(
        {evidence.category_code for evidence in item.criterion_evidence}
        == {"cuisine_origins", "flavors"}
        for item in pool
    )

    passage_ids = {passage.evidence_id for item in pool for passage in item.wiki_passages}
    with repository._connection() as connection:
        rows = connection.execute(
            f"""
            SELECT chunk_id,facet,metadata_json FROM knowledge_chunk
            WHERE chunk_id IN ({",".join("?" for _ in passage_ids)})
            """,
            tuple(passage_ids),
        ).fetchall()
    assert {str(row["chunk_id"]) for row in rows} == passage_ids
    assert all(
        (
            __import__("json").loads(str(row["metadata_json"])).get("recommendation_visibility")
            == "PUBLIC_RAG"
        )
        or (
            "recommendation_visibility" not in __import__("json").loads(str(row["metadata_json"]))
            and str(row["facet"]).lower() != "safety"
        )
        for row in rows
    )

    vegan_pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        RecommendationCriteriaV2(
            dietary_filters={"vegan": True},
            max_spice_level=5,
        ),
        RecommendationMode.INITIAL,
        24,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert vegan_pool
    assert all(item.vegan_status in {"LIKELY_FIT", "POSSIBLE_WITH_CHECKS"} for item in vegan_pool)

    halal_pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        RecommendationCriteriaV2(
            dietary_filters={"halal_certified_only": True},
            max_spice_level=5,
        ),
        RecommendationMode.INITIAL,
        8,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert halal_pool and all(item.halal_certified is True for item in halal_pool)


def test_live_projection_keeps_current_price_but_removes_unavailable_menu(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(repository)
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        price_bands=["UNDER_10000"],
        max_spice_level=5,
    )
    release_family_id, eligibility_as_of = _active_pin(repository)
    pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.INITIAL,
        8,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert len(pool) >= 2
    repriced, unavailable = pool[:2]
    with repository._connection() as connection:
        connection.execute(
            "UPDATE menu SET price=40000 WHERE menu_id=?", (repriced.menu_id,)
        )
        connection.execute(
            "UPDATE menu SET availability='UNAVAILABLE' WHERE menu_id=?",
            (unavailable.menu_id,),
        )

    states = repository.get_live_recommendation_menu_states(
        session.session_id,
        criteria,
        release_family_id,
        [repriced.menu_id, unavailable.menu_id],
        at=datetime.now(timezone.utc),
    )

    assert states[repriced.menu_id].menu.price == 40_000
    assert unavailable.menu_id not in states


def test_snapshot_completion_revalidates_filters_increments_once_and_hides_audit(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(
        repository,
        religion_selection="Islam",
        dietary_rules=["shellfish_allergy"],
        allergy_severity="severe",
    )
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        main_ingredients=["PORK"],
        max_spice_level=5,
    )
    committed = _commit(repository, session.session_id, criteria)
    request = RecommendationRequestInput(
        request_id="recommendation-request-0002",
        expected_state_version=committed.state_version,
        criteria_version=committed.criteria_version,
    )
    reserved = repository.reserve_recommendation_request(
        session.session_id,
        request,
        "request-hash-0002",
    )
    pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        request.mode,
        24,
        release_family_id=reserved.release_family_id,
        eligibility_as_of=reserved.eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert pool
    dispatched = repository.mark_recommendation_dispatched(
        session.session_id,
        request.request_id,
        pool,
    )
    selected = pool[0]
    unavailable = pool[1]
    with repository._connection() as connection:
        connection.execute(
            "UPDATE menu SET availability='UNAVAILABLE' WHERE menu_id=?",
            (unavailable.menu_id,),
        )
        connection.execute(
            "UPDATE menu SET price=price+321 WHERE menu_id=?",
            (selected.menu_id,),
        )
        current_price = int(
            connection.execute(
                "SELECT price FROM menu WHERE menu_id=?", (selected.menu_id,)
            ).fetchone()[0]
        )

    candidates = [
        RecommendationCandidate(
            menu_id=item.menu_id,
            merchant_id=item.menu.merchant_id,
            rank=rank,
            score=item.retrieval_score,
        )
        for rank, item in enumerate((unavailable, selected), start=1)
    ]
    need_state = repository.get_session(session.session_id).meal_need_state  # type: ignore[union-attr]
    need_state.shown_menu_ids = [item.menu_id for item in (unavailable, selected)]
    snapshot = RecommendationSnapshot(
        snapshot_id="snapshot-structured-0001",
        session_id=session.session_id,
        assistant_message_id="untrusted-shared-message-id",
        state_version=dispatched.state_version + 1,
        meal_need_state=need_state,
        result=RecommendationResult(
            snapshot_id="snapshot-structured-0001",
            candidates=candidates,
            query_summary="Pork dishes",
        ),
        cards=[
            {
                "type": "structured_recommendation",
                "data": {"menu": item.menu.model_dump(mode="json")},
            }
            for item in (unavailable, selected)
        ],
        created_at=datetime.now(timezone.utc),
    )
    result_json = {
        "status": "RECOMMENDED",
        "criteria_summary": "Pork dishes",
        "recommendations": [
            {
                "rank": rank,
                "menu_id": item.menu_id,
                "menu": item.menu.model_dump(mode="json"),
            }
            for rank, item in enumerate((unavailable, selected), start=1)
        ],
        "unmatched_category_codes": [],
    }
    completed = repository.complete_recommendation_request(
        session.session_id,
        request.request_id,
        RecommendationRequestStatus.COMPLETED,
        result_json=result_json,
        snapshot=snapshot,
    )

    assert completed.state_version == committed.state_version + 1
    assert completed.result_json is not None
    assert [item["menu_id"] for item in completed.result_json["recommendations"]] == [
        selected.menu_id
    ]
    assert completed.result_json["recommendations"][0]["menu"]["price"] == current_price
    saved = repository.get_recommendation_snapshot(
        session.session_id,
        completed.snapshot_id,
    )
    assert saved is not None
    assert [item.menu_id for item in saved.result.candidates] == [selected.menu_id]
    assert saved.result.candidates[0].rank == 1
    assert saved.cards[0]["data"]["menu"]["price"] == current_price
    assert unavailable.menu_id not in saved.meal_need_state.shown_menu_ids
    assert repository.list_messages(session.session_id) == []
    with repository._connection() as connection:
        audit = connection.execute(
            """
            SELECT message_id FROM chat_message
            WHERE session_id=? AND message_type='structured_recommendation_audit'
            """,
            (session.session_id,),
        ).fetchone()
    assert audit is not None
    assert str(audit["message_id"]) != snapshot.assistant_message_id

    duplicate = repository.complete_recommendation_request(
        session.session_id,
        request.request_id,
        RecommendationRequestStatus.COMPLETED,
        result_json=result_json,
        snapshot=snapshot,
    )
    assert duplicate.duplicate is True
    assert duplicate.state_version == completed.state_version

    event = repository.apply_conversation_event(
        session.session_id,
        ConversationEventInput(
            event_type=ConversationEventType.SELECT_MENU,
            snapshot_id=saved.snapshot_id,
            menu_id=selected.menu_id,
            expected_state_version=completed.state_version,
            idempotency_key="select-v2-menu-0001",
        ),
    )
    assert event.selected_menu_id == selected.menu_id
    assert event.state_version == completed.state_version + 1


def test_options_api_returns_v2_halal_and_vegan_state_contract(
    repository: SQLiteYobiRepository,
) -> None:
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            certified_response = client.get("/api/v1/menus/menu_001_01/options")
            uncertified_response = client.get("/api/v1/menus/menu_059_01/options")
    finally:
        app.dependency_overrides.clear()

    assert certified_response.status_code == 200
    certified_items = {
        item["option_item_id"]: item
        for group in certified_response.json()
        for item in group["items"]
    }
    assert certified_items
    for item in certified_items.values():
        assert {
            "halal_certification_preserved",
            "vegan_status",
            "vegan_warning",
        } <= item.keys()
        assert item["halal_certification_preserved"] is True
        assert item["vegan_status"] in {
            "LIKELY_FIT",
            "POSSIBLE_WITH_CHECKS",
            "CONFLICT",
            "UNKNOWN",
            None,
        }

    cheese_add = certified_items["oi_001_01_cheese_add"]
    fishcake_keep = certified_items["oi_001_01_fishcake_keep"]
    assert cheese_add["vegan_status"] == "CONFLICT"
    assert fishcake_keep["vegan_status"] == "CONFLICT"
    assert "adds a confirmed animal-derived ingredient" in cheese_add["vegan_warning"]

    # Removing one ingredient keeps this menu's base conflict; it must not be
    # upgraded to a vegan-safe claim from the option effect alone.
    assert certified_items["oi_001_01_cheese_none"]["vegan_status"] == "CONFLICT"
    assert certified_items["oi_001_01_fishcake_remove"]["vegan_status"] == "CONFLICT"

    assert uncertified_response.status_code == 200
    uncertified_items = [item for group in uncertified_response.json() for item in group["items"]]
    assert uncertified_items
    assert all(item["halal_certification_preserved"] is None for item in uncertified_items)
    assert all(item["halal_certification_preserved"] is not False for item in uncertified_items)
