from __future__ import annotations

import hashlib
import json
from array import array
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, cast
from uuid import uuid4

import oracledb

from app.core.config import Settings
from app.db.browse_rankings import food_ranking_sql
from app.db.concept_query import (
    build_candidate_recall_channel_query,
    build_concept_candidate_query,
    build_concept_preview_count_query,
    build_semantic_candidate_query,
)
from app.db.demo_address import demo_address_status
from app.db.message_ordering import order_conversation_messages
from app.db.oracle_pool import OraclePool
from app.db.seed_data import CATALOG_VERSION
from app.domain.address import normalize_address_text
from app.domain.concept_ranking import (
    RANKING_POLICY_VERSION,
    ConceptRankCandidate,
    bayesian_review_prior,
    candidate_channel_fusion_trace,
    merge_candidate_channels,
    rank_concept_candidates,
)
from app.domain.dialogue import (
    ConstraintStrictness,
    ConversationEventInput,
    ConversationEventResult,
    ConversationEventType,
    DialogueAct,
    MealNeedState,
    RecommendationCandidate,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.domain.dietary import apply_profile_constraints, known_allergen_conflicts
from app.domain.knowledge import (
    ClaimStatus,
    GroundedMenuKnowledge,
    GroundedPassage,
    IngredientRole,
    KnowledgeSourceKind,
    SourceScope,
)
from app.domain.models import (
    AddressCandidate,
    AssistantTurn,
    CartItemInput,
    CartItemUpdate,
    CartLine,
    CartPreview,
    ChatState,
    Checkout,
    CheckoutCreate,
    DeliveryPreferenceInput,
    Evidence,
    EvidenceStatus,
    MenuSummary,
    MerchantComparison,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
    OptionGroup,
    OptionItem,
    Order,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    RestaurantNoteTranslation,
    Session,
)
from app.domain.preference_catalog import (
    localized_preference_catalog,
    normalize_preference_locale,
    preference_option_is_exposable,
    preference_query_aliases,
)
from app.domain.recommendation import (
    operational_menu_signal,
    rerank_menu_candidates,
    wiki_operational_retrieval_score,
)
from app.domain.recommendation_copy import deterministic_presentation_copy
from app.domain.structured_recommendation import (
    CriterionEvidence,
    EvidencePoolItem,
    EvidenceReference,
    FeaturedMenuCollection,
    FeaturedMenuEntry,
    FoodRankingCollection,
    FoodRankingEntry,
    FoodRankingSort,
    LiveRecommendationMenuState,
    RecommendationCriteriaCommit,
    RecommendationCriteriaRecord,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationPreviewV2,
    RecommendationReleaseFamily,
    RecommendationRequestInput,
    RecommendationRequestRecord,
    RecommendationRequestStatus,
)
from app.knowledge.catalog_seed import KNOWLEDGE_CATALOG_VERSION, KNOWLEDGE_RELEASE_ID
from app.knowledge.passage_ranking import rank_wiki_passages
from app.knowledge.resolver import (
    VEGAN_INGREDIENTS,
    allergen_constraint_conflicts,
    category_constraint_conflicts,
    confirmed_allergen_absence_signals,
    ingredient_constraint_conflicts,
    merchant_cross_contact_conflicts,
    resolve_allergen_claims,
    resolve_dietary_claims,
    resolve_ingredient_claims,
    resolve_merchant_ingredient_claims,
    resolve_preparation_claims,
    severe_allergy_conflicts,
)
from app.rag.embeddings import (
    FALLBACK_RECOMMENDATION_QUERY_ALIASES,
    HybridChunkCandidate,
    apply_soft_profile_retrieval_signal,
    hybrid_knowledge_chunk_score,
    rank_hybrid_chunks_rrf,
)
from app.rag.providers import choose_embedding_provider

# The demo corpus is intentionally bounded at 600 menus. Keep every hard-filtered
# candidate until the structured-preference reranker has applied its 25% share.
RECOMMENDATION_CANDIDATE_CAP = 600
RECOMMENDATION_PASSAGE_LIMIT = 3
EXPECTED_MAPPED_MENUS = 600
EXPECTED_ORIGIN_DECLARATIONS = 13
EXPECTED_MERCHANT_INGREDIENTS = 120
EXPECTED_OPTION_EFFECTS = 4


def _oracle_required_text(value: str) -> str:
    """Keep API-level empty strings non-NULL in Oracle VARCHAR2 columns."""

    return value or " "


def _oracle_logical_text(value: object) -> str:
    text = str(value or "")
    return "" if text == " " else text


def _catalog_text(value: object, fallback: object = "") -> str:
    return str(value) if value not in (None, "") else str(fallback or "")


def _optional_int(value: object) -> int | None:
    return None if value is None else int(cast(Any, value))


EXPECTED_RUNTIME_COUNTS = {
    "service_area": 3,
    "menu_category": 100,
    "merchant": 60,
    "menu": 600,
    "menu_knowledge": 600,
    "menu_option_group": 1202,
    "menu_option_item": 2405,
    "review_snippet": 2400,
    "evidence": 1200,
    "address_place": 20,
    "ingredient": 48,
    "menu_ingredient": 565,
    "allergen": 8,
    "menu_allergen": 48,
    "dietary_attribute": 15,
    "menu_dietary_attribute": 1217,
    "option_dietary_conflict": 1,
}
EXTERNAL_CATALOG_COUNT_TABLES = (
    "catalog_source_payload",
    "menu",
    "menu_option_group",
    "menu_option_item",
    "menu_source_detail",
    "menu_source_section",
    "menu_source_section_item",
    "merchant",
    "merchant_source_detail",
    "option_group_source_detail",
    "source_option",
)
UPGRADE_RETAINED_RUNTIME_COUNT_KEYS = frozenset(
    {"allergen", "dietary_attribute", "ingredient", "menu_allergen"}
)


def _runtime_counts_compatible(counts: dict[str, int]) -> bool:
    return set(counts) == set(EXPECTED_RUNTIME_COUNTS) and all(
        actual >= expected if key in UPGRADE_RETAINED_RUNTIME_COUNT_KEYS else actual == expected
        for key, expected in EXPECTED_RUNTIME_COUNTS.items()
        for actual in (counts[key],)
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _cart_fingerprint(cart_id: str, cart_version: int, total: int) -> str:
    return hashlib.sha256(f"{cart_id}:{cart_version}:{total}".encode()).hexdigest()


def _value(value: Any) -> Any:
    return value.read() if hasattr(value, "read") else value


def _json(value: Any) -> Any:
    raw = _value(value)
    return json.loads(raw) if isinstance(raw, str) else raw


def _json_text(value: Any) -> str:
    """Canonicalize Oracle JSON values whether returned as text or dict/list."""

    return json.dumps(
        _json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _row(cursor: oracledb.Cursor) -> dict[str, Any] | None:
    values = cursor.fetchone()
    if values is None:
        return None
    if cursor.description is None:
        raise RuntimeError("ORACLE_QUERY_HAS_NO_RESULT_DESCRIPTION")
    columns = [column[0].lower() for column in cursor.description]
    return {column: _value(value) for column, value in zip(columns, values)}


def _rows(cursor: oracledb.Cursor) -> list[dict[str, Any]]:
    if cursor.description is None:
        raise RuntimeError("ORACLE_QUERY_HAS_NO_RESULT_DESCRIPTION")
    columns = [column[0].lower() for column in cursor.description]
    return [
        {column: _value(value) for column, value in zip(columns, values)}
        for values in cursor.fetchall()
    ]


def _find_menu_projection(value: Any, menu_id: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if value.get("menu_id") == menu_id:
            return {str(key): item for key, item in value.items()}
        for item in value.values():
            match = _find_menu_projection(item, menu_id)
            if match is not None:
                return match
    elif isinstance(value, list):
        for item in value:
            match = _find_menu_projection(item, menu_id)
            if match is not None:
                return match
    return None


def _live_structured_menu_payload(
    row: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Overlay server-owned catalog fields without changing model prose."""
    return {
        **(existing or {}),
        "menu_id": str(row["menu_id"]),
        "merchant_id": str(row["merchant_id"]),
        "merchant_name": _catalog_text(row["merchant_name"]),
        "name_en": _catalog_text(row["name_en"], row["name_ko"]),
        "name_ko": str(row["name_ko"]),
        "category": str(row["category"]),
        "description": _catalog_text(row["description"]),
        "cultural_description": _catalog_text(row["cultural_description"]),
        "price": int(row["price"]),
        "delivery_fee": int(row["delivery_fee"]),
        "eta_min": int(row["eta_min"]),
        "eta_max": int(row["eta_max"]),
        "spice_level": _optional_int(row["spice_level"]),
        "serves_min": _optional_int(row["serves_min"]),
        "serves_max": _optional_int(row["serves_max"]),
    }


class OracleYobiRepository:
    """Production repository: Oracle owns catalog, state, cart, checkout, and audit data."""

    def __init__(self, settings: Settings) -> None:
        if settings.app_env == "production" and settings.embedding_provider != "oci":
            raise RuntimeError("PRODUCTION_ORACLE_REQUIRES_OCI_EMBEDDINGS")
        self.settings = settings
        self.pool = OraclePool(settings)
        self.embedding_provider = choose_embedding_provider(settings)
        self._recommendation_retrieval_metrics: dict[str, dict[str, Any]] = {}

    def get_recommendation_retrieval_metrics(self, session_id: str) -> dict[str, Any]:
        return dict(self._recommendation_retrieval_metrics.get(session_id, {}))

    def initialize(self) -> None:
        self.pool.initialize()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM schema_migration")
            cursor.fetchone()

    def create_profile(self, data: ProfileCreate) -> Profile:
        if not data.consent_demo_data:
            raise ValueError("Data processing consent is required to start a session")
        profile_id = _id("profile")
        created_at = _now()
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO user_profile (
                  profile_id, preferred_language, nationality, country_code, age_band, gender,
                  religion_selection, dietary_rules_json, allergy_severity,
                  spice_tolerance, favorite_foods_json, consent_demo_data,
                  remember_profile, created_at
                ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13,:14)
                """,
                [
                    profile_id,
                    data.preferred_language,
                    data.nationality,
                    data.country_code,
                    data.age_band,
                    data.gender,
                    data.religion_selection,
                    json.dumps(data.dietary_rules),
                    data.allergy_severity,
                    data.spice_tolerance,
                    json.dumps(data.favorite_foods),
                    int(data.consent_demo_data),
                    int(data.remember_profile),
                    created_at,
                ],
            )
        return Profile(profile_id=profile_id, created_at=created_at, **data.model_dump())

    def get_profile(self, profile_id: str) -> Profile | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM user_profile WHERE profile_id = :id", id=profile_id)
            row = _row(cursor)
        return self._profile(row) if row else None

    def update_profile(self, profile_id: str, data: ProfileUpdate) -> Profile | None:
        existing = self.get_profile(profile_id)
        if existing is None:
            return None
        merged = ProfileCreate.model_validate(
            {
                **existing.model_dump(exclude={"profile_id", "created_at"}),
                **data.model_dump(exclude_unset=True),
            }
        )
        if not merged.consent_demo_data:
            raise ValueError("Data processing consent is required to keep a profile")
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                UPDATE user_profile SET preferred_language=:preferred_language,
                  nationality=:nationality,country_code=:country_code,age_band=:age_band,gender=:gender,
                  religion_selection=:religion_selection,dietary_rules_json=:dietary_rules,
                  allergy_severity=:allergy_severity,spice_tolerance=:spice_tolerance,
                  favorite_foods_json=:favorite_foods,consent_demo_data=:consent,
                  remember_profile=:remember WHERE profile_id=:profile_id
                """,
                preferred_language=merged.preferred_language,
                nationality=merged.nationality,
                country_code=merged.country_code,
                age_band=merged.age_band,
                gender=merged.gender,
                religion_selection=merged.religion_selection,
                dietary_rules=json.dumps(merged.dietary_rules),
                allergy_severity=merged.allergy_severity,
                spice_tolerance=merged.spice_tolerance,
                favorite_foods=json.dumps(merged.favorite_foods),
                consent=int(merged.consent_demo_data),
                remember=int(merged.remember_profile),
                profile_id=profile_id,
            )
        return self.get_profile(profile_id)

    @staticmethod
    def _profile(row: dict[str, Any]) -> Profile:
        return Profile(
            profile_id=row["profile_id"],
            preferred_language=row["preferred_language"],
            nationality=row["nationality"],
            country_code=row.get("country_code"),
            age_band=row["age_band"],
            gender=row["gender"],
            religion_selection=row["religion_selection"],
            dietary_rules=_json(row["dietary_rules_json"]),
            allergy_severity=row["allergy_severity"],
            spice_tolerance=int(row["spice_tolerance"]),
            favorite_foods=_json(row["favorite_foods_json"]),
            consent_demo_data=bool(row["consent_demo_data"]),
            remember_profile=bool(row["remember_profile"]),
            created_at=row["created_at"],
        )

    def delete_profile(self, profile_id: str) -> bool:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT session_id FROM chat_session WHERE profile_id = :id", id=profile_id
            )
            for row in cursor.fetchall():
                self._reset(connection, row[0], True)
            cursor.execute("DELETE FROM user_profile WHERE profile_id = :id", id=profile_id)
            return cursor.rowcount > 0

    def create_session(self, profile_id: str) -> Session:
        if not self.get_profile(profile_id):
            raise KeyError("PROFILE_NOT_FOUND")
        session_id = _id("session")
        now = _now()
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO chat_session (
                  session_id, profile_id, state, state_stack_json, required_slots_json,
                  created_at, updated_at
                ) VALUES (:1,:2,:3,'[]',:4,:5,:6)
                """,
                [
                    session_id,
                    profile_id,
                    ChatState.DISCOVERY.value,
                    json.dumps(["order.menu_id", "delivery.address_confirmed"]),
                    now,
                    now,
                ],
            )
        return Session(
            session_id=session_id,
            profile_id=profile_id,
            state=ChatState.DISCOVERY,
            created_at=now,
            updated_at=now,
        )

    def get_session(self, session_id: str) -> Session | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM chat_session WHERE session_id = :id", id=session_id)
            row = _row(cursor)
        if not row:
            return None
        return Session(
            session_id=row["session_id"],
            profile_id=row["profile_id"],
            state=ChatState(row["state"]),
            selected_menu_id=row["selected_menu_id"],
            selected_merchant_id=row["selected_merchant_id"],
            dialogue_act=DialogueAct(row.get("dialogue_act") or DialogueAct.COLLECT_NEEDS.value),
            meal_need_state=MealNeedState.model_validate(
                _json(row.get("meal_need_state_json") or "{}")
            ),
            state_version=int(row.get("state_version") or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str,
        message_id: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> str:
        message_id = message_id or _id("msg")
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO chat_message(message_id, session_id, role, content, message_type,
                  safe_metadata_json, created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7)
                """,
                [
                    message_id,
                    session_id,
                    role,
                    content,
                    message_type,
                    json.dumps(safe_metadata or {}, ensure_ascii=False),
                    _now(),
                ],
            )
        return message_id

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT message_id, role, content, message_type, safe_metadata_json, created_at
                FROM chat_message
                WHERE session_id = :id
                  AND message_type <> 'structured_recommendation_audit'
                ORDER BY created_at, message_id
                """,
                id=session_id,
            )
            rows = _rows(cursor)
        messages: list[dict[str, Any]] = []
        for row in rows:
            messages.append(
                {
                    "message_id": str(row["message_id"]),
                    "role": str(row["role"]),
                    "content": str(row["content"]),
                    "message_type": str(row["message_type"]),
                    "safe_metadata": _json(row["safe_metadata_json"]),
                    "created_at": str(row["created_at"]),
                }
            )
        return order_conversation_messages(messages)

    def update_dialogue_state(
        self,
        session_id: str,
        dialogue_act: DialogueAct,
        meal_need_state: MealNeedState,
        state: str,
        expected_state_version: int,
    ) -> Session:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE chat_session SET state=:state, dialogue_act=:dialogue_act,
                  meal_need_state_json=:meal_need_state, state_version=state_version+1,
                  updated_at=:updated_at
                WHERE session_id=:session_id AND state_version=:expected_version
                """,
                state=state,
                dialogue_act=dialogue_act.value,
                meal_need_state=meal_need_state.model_dump_json(),
                updated_at=_now(),
                session_id=session_id,
                expected_version=expected_state_version,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
        updated = self.get_session(session_id)
        if updated is None:
            raise KeyError("SESSION_NOT_FOUND")
        return updated

    def commit_chat_turn(
        self,
        session_id: str,
        expected_state_version: int,
        user_message_id: str,
        user_text: str,
        user_created_at: datetime,
        assistant_turn: AssistantTurn,
        meal_need_state: MealNeedState,
        dialogue_act: DialogueAct,
        snapshot: RecommendationSnapshot | None = None,
        request_id: str | None = None,
        intent: str | None = None,
    ) -> Session:
        next_version = expected_state_version + 1
        persisted_turn = assistant_turn.model_copy(
            update={"state_version": next_version, "dialogue_act": dialogue_act}
        )
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE chat_session SET state=:state, dialogue_act=:dialogue_act,
                  meal_need_state_json=:meal_need_state,
                  selected_menu_id=:selected_menu_id,
                  selected_merchant_id=(
                    SELECT merchant_id FROM menu WHERE menu_id=:selected_menu_id
                  ), state_version=:next_version, updated_at=:updated_at
                WHERE session_id=:session_id AND state_version=:expected_version
                """,
                state=persisted_turn.state.value,
                dialogue_act=dialogue_act.value,
                meal_need_state=meal_need_state.model_dump_json(),
                selected_menu_id=meal_need_state.selected_menu_id,
                next_version=next_version,
                updated_at=_now(),
                session_id=session_id,
                expected_version=expected_state_version,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            user_metadata = (
                {
                    "client_request_id": request_id,
                    "intent": intent,
                }
                if request_id
                else {}
            )
            cursor.execute(
                """
                INSERT INTO chat_message(message_id,session_id,role,content,message_type,
                  safe_metadata_json,created_at)
                VALUES (:1,:2,'user',:3,'text',:4,:5)
                """,
                [
                    user_message_id,
                    session_id,
                    user_text,
                    json.dumps(user_metadata, ensure_ascii=False),
                    user_created_at,
                ],
            )
            assistant_metadata = persisted_turn.model_dump(mode="json")
            if request_id:
                assistant_metadata["client_request_id"] = request_id
            cursor.execute(
                """
                INSERT INTO chat_message(message_id,session_id,role,content,message_type,
                  safe_metadata_json,created_at)
                VALUES (:1,:2,'assistant',:3,'assistant_turn',:4,:5)
                """,
                [
                    persisted_turn.message_id,
                    session_id,
                    persisted_turn.text,
                    json.dumps(assistant_metadata, ensure_ascii=False),
                    persisted_turn.created_at,
                ],
            )
            if snapshot is not None:
                persisted_snapshot = snapshot.model_copy(
                    update={
                        "state_version": next_version,
                        "meal_need_state": meal_need_state,
                        "cards": [card.model_dump(mode="json") for card in persisted_turn.cards],
                    }
                )
                cursor.execute(
                    """
                    INSERT INTO recommendation_snapshot(snapshot_id,session_id,
                      assistant_message_id,state_version,meal_need_state_json,result_json,
                      cards_json,created_at)
                    VALUES (:1,:2,:3,:4,:5,:6,:7,:8)
                    """,
                    [
                        persisted_snapshot.snapshot_id,
                        session_id,
                        persisted_snapshot.assistant_message_id,
                        next_version,
                        meal_need_state.model_dump_json(),
                        persisted_snapshot.result.model_dump_json(),
                        json.dumps(persisted_snapshot.cards, ensure_ascii=False),
                        persisted_snapshot.created_at,
                    ],
                )
        updated = self.get_session(session_id)
        if updated is None:
            raise KeyError("SESSION_NOT_FOUND")
        return updated

    def save_recommendation_snapshot(self, snapshot: RecommendationSnapshot) -> None:
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO recommendation_snapshot(snapshot_id,session_id,assistant_message_id,
                  state_version,meal_need_state_json,result_json,cards_json,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8)
                """,
                [
                    snapshot.snapshot_id,
                    snapshot.session_id,
                    snapshot.assistant_message_id,
                    snapshot.state_version,
                    snapshot.meal_need_state.model_dump_json(),
                    snapshot.result.model_dump_json(),
                    json.dumps(snapshot.cards, ensure_ascii=False),
                    snapshot.created_at,
                ],
            )

    def get_recommendation_snapshot(
        self, session_id: str, snapshot_id: str | None = None
    ) -> RecommendationSnapshot | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            if snapshot_id:
                cursor.execute(
                    """
                    SELECT * FROM recommendation_snapshot
                    WHERE session_id=:session_id AND snapshot_id=:snapshot_id
                    """,
                    session_id=session_id,
                    snapshot_id=snapshot_id,
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM (
                      SELECT * FROM recommendation_snapshot WHERE session_id=:session_id
                      ORDER BY created_at DESC, snapshot_id DESC
                    ) WHERE ROWNUM=1
                    """,
                    session_id=session_id,
                )
            row = _row(cursor)
        if row is None:
            return None
        return RecommendationSnapshot.model_validate(
            {
                "snapshot_id": row["snapshot_id"],
                "session_id": row["session_id"],
                "assistant_message_id": row["assistant_message_id"],
                "state_version": row["state_version"],
                "meal_need_state": _json(row["meal_need_state_json"]),
                "result": _json(row["result_json"]),
                "cards": _json(row["cards_json"]),
                "created_at": row["created_at"],
            }
        )

    @staticmethod
    def _criteria_record_from_row(row: dict[str, Any]) -> RecommendationCriteriaRecord:
        return RecommendationCriteriaRecord(
            session_id=str(row["session_id"]),
            criteria=RecommendationCriteriaV2.model_validate(_json(row["criteria_json"])),
            criteria_version=int(row["criteria_version"]),
            state_version=int(row["state_version"]),
            criteria_hash=str(row["criteria_hash"]),
            request_id=str(row["request_id"]),
            created_at=_datetime(row["created_at"]),
        )

    @staticmethod
    def _request_record_from_row(
        row: dict[str, Any],
        *,
        duplicate: bool = False,
    ) -> RecommendationRequestRecord:
        return RecommendationRequestRecord(
            request_id=str(row["request_id"]),
            session_id=str(row["session_id"]),
            request_hash=str(row["request_hash"]),
            criteria_version=int(row["criteria_version"]),
            mode=RecommendationMode(str(row["request_mode"])),
            status=RecommendationRequestStatus(str(row["status"])),
            state_version=int(row["state_version"]),
            release_family_id=str(row["recommendation_release_family_id"]),
            eligibility_as_of=_datetime(row["eligibility_as_of"]),
            snapshot_id=str(row["snapshot_id"]) if row.get("snapshot_id") else None,
            evidence_pool_json=list(_json(row.get("evidence_pool_json") or "[]")),
            result_json=(
                dict(_json(row["result_json"])) if row.get("result_json") is not None else None
            ),
            final_candidates_json=list(_json(row.get("final_candidates_json") or "[]")),
            ranking_trace_json=dict(_json(row.get("ranking_trace_json") or "{}")),
            ranking_policy_version=str(row.get("ranking_policy_version") or "legacy-llm-rank-v2"),
            support_manifest_sha256=str(row.get("support_manifest_sha256") or "0" * 64),
            feature_manifest_sha256=str(row.get("feature_manifest_sha256") or "0" * 64),
            finalized_at=(_datetime(row["finalized_at"]) if row.get("finalized_at") else None),
            dispatch_count=int(row["dispatch_count"]),
            failure_code=str(row["failure_code"]) if row.get("failure_code") else None,
            created_at=_datetime(row["created_at"]),
            dispatched_at=(_datetime(row["dispatched_at"]) if row.get("dispatched_at") else None),
            completed_at=(_datetime(row["completed_at"]) if row.get("completed_at") else None),
            client_cancelled_at=(
                _datetime(row["client_cancelled_at"])
                if row.get("client_cancelled_at")
                else None
            ),
            duplicate=duplicate,
        )

    def save_recommendation_criteria(
        self,
        session_id: str,
        commit: RecommendationCriteriaCommit,
    ) -> RecommendationCriteriaRecord:
        canonical = json.dumps(
            {
                "catalog_version": commit.catalog_version,
                "criteria": commit.criteria.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        criteria_hash = hashlib.sha256(canonical.encode()).hexdigest()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM session_recommendation_criteria
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=commit.request_id,
            )
            existing = _row(cursor)
            if existing is not None:
                if str(existing["criteria_hash"]) != criteria_hash:
                    raise ValueError("CRITERIA_REQUEST_ID_REUSED")
                return self._criteria_record_from_row(existing)

            cursor.execute(
                "SELECT state_version FROM chat_session WHERE session_id=:session_id FOR UPDATE",
                session_id=session_id,
            )
            session = _row(cursor)
            if session is None:
                raise KeyError("SESSION_NOT_FOUND")
            # The request may have committed while this transaction waited for the
            # session lock. Re-read it before allocating a new immutable version.
            cursor.execute(
                """
                SELECT * FROM session_recommendation_criteria
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=commit.request_id,
            )
            existing = _row(cursor)
            if existing is not None:
                if str(existing["criteria_hash"]) != criteria_hash:
                    raise ValueError("CRITERIA_REQUEST_ID_REUSED")
                return self._criteria_record_from_row(existing)

            cursor.execute(
                """
                SELECT family.preference_catalog_version
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                """
            )
            active = _row(cursor)
            if active is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
            if str(active["preference_catalog_version"]) != commit.catalog_version:
                raise ValueError("PREFERENCE_CATALOG_CHANGED")
            cursor.execute(
                """
                SELECT option_code FROM recommendation_preference_option
                WHERE catalog_version=:catalog_version AND active=1
                """,
                catalog_version=commit.catalog_version,
            )
            available_codes = {str(row[0]) for row in cursor.fetchall()}
            selected_codes = {
                value
                for category in (
                    "cuisine_origins",
                    "flavors",
                    "main_ingredients",
                    "food_forms",
                    "temperatures",
                    "price_bands",
                    "textures",
                    "cooking_methods",
                )
                for value in getattr(commit.criteria, category)
            }
            unknown_codes = sorted(selected_codes - available_codes)
            if unknown_codes:
                raise ValueError(f"UNSUPPORTED_PREFERENCE_CODE:{unknown_codes[0]}")

            current_state_version = int(session["state_version"])
            if current_state_version != commit.expected_state_version:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            cursor.execute(
                """
                SELECT COALESCE(MAX(criteria_version),0)+1
                FROM session_recommendation_criteria WHERE session_id=:session_id
                """,
                session_id=session_id,
            )
            criteria_version = int(cursor.fetchone()[0])
            next_state_version = current_state_version + 1
            now = _now()
            cursor.execute(
                """
                UPDATE chat_session SET state_version=:next_version,updated_at=:updated_at
                WHERE session_id=:session_id AND state_version=:expected_version
                """,
                next_version=next_state_version,
                updated_at=now,
                session_id=session_id,
                expected_version=current_state_version,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            cursor.execute(
                """
                INSERT INTO session_recommendation_criteria(
                  session_id,criteria_version,criteria_json,criteria_hash,
                  request_id,state_version,created_at
                ) VALUES (:1,:2,:3,:4,:5,:6,:7)
                """,
                [
                    session_id,
                    criteria_version,
                    commit.criteria.model_dump_json(),
                    criteria_hash,
                    commit.request_id,
                    next_state_version,
                    now,
                ],
            )
            cursor.execute(
                """
                SELECT * FROM session_recommendation_criteria
                WHERE session_id=:session_id AND criteria_version=:criteria_version
                """,
                session_id=session_id,
                criteria_version=criteria_version,
            )
            stored = _row(cursor)
            if stored is None:
                raise RuntimeError("RECOMMENDATION_CRITERIA_WRITE_FAILED")
            return self._criteria_record_from_row(stored)

    def get_recommendation_criteria(
        self,
        session_id: str,
        version: int | None = None,
    ) -> RecommendationCriteriaRecord | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            if version is None:
                cursor.execute(
                    """
                    SELECT * FROM (
                      SELECT * FROM session_recommendation_criteria
                      WHERE session_id=:session_id
                      ORDER BY criteria_version DESC
                    ) WHERE ROWNUM=1
                    """,
                    session_id=session_id,
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM session_recommendation_criteria
                    WHERE session_id=:session_id AND criteria_version=:criteria_version
                    """,
                    session_id=session_id,
                    criteria_version=version,
                )
            row = _row(cursor)
        return self._criteria_record_from_row(row) if row else None

    def reserve_recommendation_request(
        self,
        session_id: str,
        data: RecommendationRequestInput,
        request_hash: str,
    ) -> RecommendationRequestRecord:
        if not request_hash or len(request_hash) > 160:
            raise ValueError("INVALID_RECOMMENDATION_REQUEST_HASH")
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=data.request_id,
            )
            existing = _row(cursor)
            if existing is not None:
                if (
                    str(existing["request_hash"]) != request_hash
                    or int(existing["criteria_version"]) != data.criteria_version
                    or str(existing["request_mode"]) != data.mode.value
                ):
                    raise ValueError("RECOMMENDATION_REQUEST_ID_REUSED")
                return self._request_record_from_row(existing, duplicate=True)

            cursor.execute(
                "SELECT state_version FROM chat_session WHERE session_id=:session_id FOR UPDATE",
                session_id=session_id,
            )
            session = _row(cursor)
            if session is None:
                raise KeyError("SESSION_NOT_FOUND")
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=data.request_id,
            )
            existing = _row(cursor)
            if existing is not None:
                if (
                    str(existing["request_hash"]) != request_hash
                    or int(existing["criteria_version"]) != data.criteria_version
                    or str(existing["request_mode"]) != data.mode.value
                ):
                    raise ValueError("RECOMMENDATION_REQUEST_ID_REUSED")
                return self._request_record_from_row(existing, duplicate=True)

            current_state_version = int(session["state_version"])
            if current_state_version != data.expected_state_version:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            cursor.execute(
                """
                SELECT 1 FROM session_recommendation_criteria
                WHERE session_id=:session_id AND criteria_version=:criteria_version
                """,
                session_id=session_id,
                criteria_version=data.criteria_version,
            )
            if cursor.fetchone() is None:
                raise ValueError("RECOMMENDATION_CRITERIA_VERSION_NOT_FOUND")
            now = _now()
            cursor.execute(
                """
                SELECT family.release_family_id,family.ranking_policy_version,
                       family.support_manifest_sha256,family.feature_manifest_sha256
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                JOIN knowledge_release release
                  ON release.release_id=family.knowledge_release_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                  AND release.status='READY'
                """
            )
            pinned_family = cursor.fetchone()
            if pinned_family is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
            cursor.execute(
                """
                INSERT INTO structured_recommendation_request(
                  session_id,request_id,request_hash,criteria_version,request_mode,status,state_version,
                  recommendation_release_family_id,eligibility_as_of,
                  snapshot_id,evidence_pool_json,result_json,final_candidates_json,
                  ranking_trace_json,ranking_policy_version,support_manifest_sha256,
                  feature_manifest_sha256,finalized_at,
                  dispatch_count,failure_code,
                  created_at,dispatched_at,completed_at
                ) VALUES (:1,:2,:3,:4,:5,'CREATED',:6,:7,:8,NULL,'[]',NULL,'[]','{}',:9,:10,:11,NULL,0,NULL,:12,NULL,NULL)
                """,
                [
                    session_id,
                    data.request_id,
                    request_hash,
                    data.criteria_version,
                    data.mode.value,
                    current_state_version,
                    str(pinned_family[0]),
                    now,
                    str(pinned_family[1]),
                    str(pinned_family[2]),
                    str(pinned_family[3]),
                    now,
                ],
            )
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=data.request_id,
            )
            stored = _row(cursor)
            if stored is None:
                raise RuntimeError("RECOMMENDATION_REQUEST_RESERVATION_FAILED")
            return self._request_record_from_row(stored)

    def mark_recommendation_dispatched(
        self,
        session_id: str,
        request_id: str,
        evidence_pool: list[EvidencePoolItem],
    ) -> RecommendationRequestRecord:
        if not evidence_pool:
            raise ValueError("EVIDENCE_POOL_EMPTY")
        serialized = json.dumps(
            [item.model_dump(mode="json") for item in evidence_pool],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        serialized_final = "[]"
        serialized_trace = json.dumps(
            {
                "ranking_policy_version": (
                    evidence_pool[0].ranking_trace.get("ranking_policy_version")
                    or RANKING_POLICY_VERSION
                ),
                "shortlist_count": len(evidence_pool),
                "selection_status": "PENDING",
                "candidates": [item.ranking_trace for item in evidence_pool],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id FOR UPDATE
                """,
                session_id=session_id,
                request_id=request_id,
            )
            row = _row(cursor)
            if row is None:
                raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
            if str(row["status"]) != RecommendationRequestStatus.CREATED.value:
                if _json_text(row["evidence_pool_json"]) != serialized:
                    raise ValueError("RECOMMENDATION_DISPATCH_PAYLOAD_CHANGED")
                return self._request_record_from_row(row, duplicate=True)
            now = _now()
            cursor.execute(
                """
                UPDATE structured_recommendation_request
                SET status='DISPATCHED',evidence_pool_json=:evidence_pool,
                    final_candidates_json=:final_candidates,ranking_trace_json=:ranking_trace,
                    dispatched_at=:dispatched_at
                WHERE session_id=:session_id AND request_id=:request_id
                  AND status='CREATED' AND dispatch_count=0
                """,
                evidence_pool=serialized,
                final_candidates=serialized_final,
                ranking_trace=serialized_trace,
                dispatched_at=now,
                session_id=session_id,
                request_id=request_id,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("RECOMMENDATION_DISPATCH_CONFLICT")
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=request_id,
            )
            stored = _row(cursor)
            if stored is None:
                raise RuntimeError("RECOMMENDATION_DISPATCH_WRITE_FAILED")
            return self._request_record_from_row(stored)

    def mark_recommendation_provider_called(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE structured_recommendation_request
                SET dispatch_count=1
                WHERE session_id=:session_id AND request_id=:request_id
                  AND status='DISPATCHED' AND dispatch_count=0
                """,
                session_id=session_id,
                request_id=request_id,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("RECOMMENDATION_PROVIDER_CALL_CONFLICT")
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=request_id,
            )
            stored = _row(cursor)
            if stored is None:
                raise RuntimeError("RECOMMENDATION_PROVIDER_CALL_WRITE_FAILED")
            return self._request_record_from_row(stored)

    def record_recommendation_provider_attempt(
        self,
        session_id: str,
        request_id: str,
        *,
        attempt_no: int,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        now = _now()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                MERGE INTO recommendation_provider_attempt target
                USING (
                  SELECT :session_id session_id,:request_id request_id,
                         :attempt_no attempt_no FROM dual
                ) source
                ON (target.session_id=source.session_id
                    AND target.request_id=source.request_id
                    AND target.attempt_no=source.attempt_no)
                WHEN MATCHED THEN UPDATE SET
                  target.status=:status,target.error_code=:error_code,
                  target.latency_ms=:latency_ms,target.input_tokens=:input_tokens,
                  target.output_tokens=:output_tokens,target.completed_at=:completed_at
                WHEN NOT MATCHED THEN INSERT (
                  session_id,request_id,attempt_no,provider,model_id,status,error_code,
                  latency_ms,input_tokens,output_tokens,created_at,completed_at
                ) VALUES (
                  :session_id,:request_id,:attempt_no,:provider,:model_id,:status,:error_code,
                  :latency_ms,:input_tokens,:output_tokens,:created_at,:completed_at
                )
                """,
                session_id=session_id,
                request_id=request_id,
                attempt_no=attempt_no,
                provider=provider,
                model_id=model_id,
                status=status,
                error_code=error_code,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                created_at=now,
                completed_at=now,
            )

    def cancel_recommendation_request(self, session_id: str, request_id: str) -> bool:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE structured_recommendation_request
                SET client_cancelled_at=COALESCE(client_cancelled_at,:cancelled_at)
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                cancelled_at=_now(),
                session_id=session_id,
                request_id=request_id,
            )
            return cursor.rowcount == 1

    @staticmethod
    def _restaurant_note_translation_from_row(
        row: dict[str, Any],
    ) -> RestaurantNoteTranslation:
        return RestaurantNoteTranslation(
            translation_id=str(row["translation_id"]),
            source_text=str(row["source_text"]),
            source_language=str(row["source_language"]),
            korean_text=str(row["korean_text"]) if row.get("korean_text") else None,
            back_translation=(
                str(row["back_translation"]) if row.get("back_translation") else None
            ),
            model_id=str(row["model_id"]),
            status=cast(Any, str(row["status"])),
            error_code=str(row["error_code"]) if row.get("error_code") else None,
            created_at=_datetime(row["created_at"]),
        )

    def get_restaurant_note_translation_by_hash(
        self, session_id: str, request_hash: str
    ) -> RestaurantNoteTranslation | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM restaurant_note_translation
                WHERE session_id=:session_id AND request_hash=:request_hash
                  AND status='SUCCEEDED'
                ORDER BY created_at DESC FETCH FIRST 1 ROWS ONLY
                """,
                session_id=session_id,
                request_hash=request_hash,
            )
            row = _row(cursor)
        return self._restaurant_note_translation_from_row(row) if row else None

    def save_restaurant_note_translation(
        self,
        session_id: str,
        *,
        translation_id: str,
        source_language: str,
        source_text: str,
        korean_text: str | None,
        back_translation: str | None,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        request_hash: str,
    ) -> RestaurantNoteTranslation:
        created_at = _now()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO restaurant_note_translation(
                  translation_id,session_id,source_language,source_text,korean_text,
                  back_translation,provider,model_id,status,error_code,request_hash,created_at
                ) VALUES (
                  :translation_id,:session_id,:source_language,:source_text,:korean_text,
                  :back_translation,:provider,:model_id,:status,:error_code,:request_hash,
                  :created_at
                )
                """,
                translation_id=translation_id,
                session_id=session_id,
                source_language=source_language,
                source_text=source_text,
                korean_text=korean_text,
                back_translation=back_translation,
                provider=provider,
                model_id=model_id,
                status=status,
                error_code=error_code,
                request_hash=request_hash,
                created_at=created_at,
            )
            cursor.execute(
                "SELECT * FROM restaurant_note_translation WHERE translation_id=:id",
                id=translation_id,
            )
            row = _row(cursor)
        if row is None:
            raise RuntimeError("RESTAURANT_NOTE_TRANSLATION_WRITE_FAILED")
        return self._restaurant_note_translation_from_row(row)

    def complete_recommendation_request(
        self,
        session_id: str,
        request_id: str,
        status: RecommendationRequestStatus,
        *,
        result_json: dict[str, Any] | None = None,
        snapshot: RecommendationSnapshot | None = None,
        failure_code: str | None = None,
        provider_metrics: dict[str, int] | None = None,
        grounding_rejection_code: str | None = None,
        grounding_rejection_stage: str | None = None,
        grounding_rejection_detail: str | None = None,
    ) -> RecommendationRequestRecord:
        terminal_statuses = {
            RecommendationRequestStatus.COMPLETED,
            RecommendationRequestStatus.NO_RESULTS,
            RecommendationRequestStatus.NO_MATCH,
            RecommendationRequestStatus.SEARCH_FALLBACK,
            RecommendationRequestStatus.FAILED,
            RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH,
        }
        if status not in terminal_statuses:
            raise ValueError("RECOMMENDATION_STATUS_NOT_TERMINAL")
        if snapshot is not None and snapshot.session_id != session_id:
            raise ValueError("RECOMMENDATION_SNAPSHOT_SESSION_MISMATCH")
        serialized_result = (
            json.dumps(result_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if result_json is not None
            else None
        )
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id FOR UPDATE
                """,
                session_id=session_id,
                request_id=request_id,
            )
            row = _row(cursor)
            if row is None:
                raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
            current_status = RecommendationRequestStatus(str(row["status"]))
            if current_status in terminal_statuses:
                canonicalized_snapshot_replay = snapshot is not None and (
                    str(row.get("snapshot_id") or "") == snapshot.snapshot_id
                    or str(row.get("failure_code") or "") == "LIVE_ELIGIBILITY_EMPTY"
                )
                if canonicalized_snapshot_replay:
                    return self._request_record_from_row(row, duplicate=True)
                stored_result = (
                    _json_text(row["result_json"]) if row.get("result_json") is not None else None
                )
                same_payload = (
                    current_status is status
                    and stored_result == serialized_result
                    and (row.get("failure_code") or None) == failure_code
                    and (row.get("snapshot_id") or None)
                    == (snapshot.snapshot_id if snapshot else None)
                )
                if not same_payload:
                    raise ValueError("RECOMMENDATION_COMPLETION_PAYLOAD_CHANGED")
                return self._request_record_from_row(row, duplicate=True)
            requires_dispatch = {
                RecommendationRequestStatus.COMPLETED,
                RecommendationRequestStatus.NO_MATCH,
                RecommendationRequestStatus.SEARCH_FALLBACK,
                RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH,
            }
            if (
                status in requires_dispatch
                and current_status is not RecommendationRequestStatus.DISPATCHED
            ):
                raise RuntimeError("RECOMMENDATION_NOT_DISPATCHED")

            resulting_state_version = int(row["state_version"])
            criteria_row: dict[str, Any] | None = None
            pinned_family: RecommendationReleaseFamily | None = None
            if snapshot is not None:
                cursor.execute(
                    """
                    SELECT * FROM session_recommendation_criteria
                    WHERE session_id=:session_id AND criteria_version=:criteria_version
                    """,
                    session_id=session_id,
                    criteria_version=int(row["criteria_version"]),
                )
                criteria_row = _row(cursor)
                pinned_family = self._recommendation_release_family_in_connection(
                    connection,
                    str(row["recommendation_release_family_id"]),
                )
                if criteria_row is None or pinned_family is None:
                    raise RuntimeError("RECOMMENDATION_SNAPSHOT_CONTEXT_MISSING")
                criteria = RecommendationCriteriaV2.model_validate(
                    _json(criteria_row["criteria_json"])
                )
                requested_menu_ids = [candidate.menu_id for candidate in snapshot.result.candidates]
                evidence_pool_menu_ids = {
                    str(item.get("menu", {}).get("menu_id") or item.get("menu_id") or "")
                    for item in _json(row.get("evidence_pool_json") or "[]")
                    if isinstance(item, dict)
                }
                if not set(requested_menu_ids) <= evidence_pool_menu_ids:
                    raise ValueError("SNAPSHOT_MENU_OUTSIDE_EVIDENCE_POOL")
                eligible_rows, live_certifications, live_vegan = (
                    self._structured_objective_candidates(
                        connection,
                        session_id,
                        criteria,
                        pinned_family,
                        exclude_history=False,
                        instant=_now(),
                        menu_ids=requested_menu_ids,
                        enforce_price_bands=False,
                    )
                )
                eligible_by_id = {str(menu["menu_id"]): menu for menu in eligible_rows}
                retained_candidates = [
                    candidate.model_copy(update={"rank": rank})
                    for rank, candidate in enumerate(
                        (
                            candidate
                            for candidate in snapshot.result.candidates
                            if candidate.menu_id in eligible_by_id
                            and str(eligible_by_id[candidate.menu_id]["merchant_id"])
                            == candidate.merchant_id
                        ),
                        start=1,
                    )
                ]
                if not retained_candidates:
                    snapshot = None
                    status = RecommendationRequestStatus.NO_RESULTS
                    failure_code = failure_code or "LIVE_ELIGIBILITY_EMPTY"
                    if result_json is not None:
                        result_json = {
                            **result_json,
                            "status": "NO_MATCH",
                            "recommendations": [],
                        }
                else:
                    retained_ids = {candidate.menu_id for candidate in retained_candidates}
                    retained_result = snapshot.result.model_copy(
                        update={
                            "candidates": retained_candidates,
                            "grounded_claim_ids": list(
                                dict.fromkeys(
                                    claim_id
                                    for candidate in retained_candidates
                                    for claim_id in candidate.claim_ids
                                )
                            ),
                            "grounded_passage_ids": list(
                                dict.fromkeys(
                                    passage_id
                                    for candidate in retained_candidates
                                    for passage_id in candidate.passage_ids
                                )
                            ),
                        }
                    )
                    retained_state = snapshot.meal_need_state.model_copy(deep=True)
                    retained_state.shown_menu_ids = [
                        menu_id
                        for menu_id in retained_state.shown_menu_ids
                        if menu_id not in requested_menu_ids or menu_id in retained_ids
                    ]
                    refreshed_menus: dict[str, dict[str, Any]] = {}
                    retained_recommendations: list[dict[str, Any]] = []
                    if result_json is not None:
                        for item in list(result_json.get("recommendations", [])):
                            if not isinstance(item, dict):
                                continue
                            menu_id = str(
                                item.get("menu_id")
                                or cast(dict[str, Any], item.get("menu") or {}).get("menu_id")
                                or ""
                            )
                            if menu_id not in retained_ids:
                                continue
                            menu_payload = _live_structured_menu_payload(
                                eligible_by_id[menu_id],
                                cast(dict[str, Any], item.get("menu") or {}),
                            )
                            refreshed_menus[menu_id] = menu_payload
                            certification = live_certifications.get(menu_id)
                            vegan_status, vegan_warning, _ = live_vegan.get(
                                menu_id, ("UNKNOWN", None, [])
                            )
                            retained_recommendations.append(
                                {
                                    **item,
                                    "menu_id": menu_id,
                                    "menu": menu_payload,
                                    "halal_certified": bool(certification),
                                    "halal_scope_label": (
                                        certification[1] if certification else None
                                    ),
                                    "vegan_status": vegan_status,
                                    "vegan_warning": vegan_warning,
                                }
                            )
                        retained_recommendations = [
                            {**item, "rank": rank}
                            for rank, item in enumerate(retained_recommendations, start=1)
                        ]
                        result_json = {
                            **result_json,
                            "recommendations": retained_recommendations,
                        }
                    retained_cards = [
                        {
                            "type": "structured_recommendation",
                            "data": {
                                "menu": refreshed_menus.get(candidate.menu_id)
                                or _live_structured_menu_payload(
                                    eligible_by_id[candidate.menu_id],
                                    _find_menu_projection(snapshot.cards, candidate.menu_id),
                                )
                            },
                        }
                        for candidate in retained_candidates
                    ]
                    snapshot = snapshot.model_copy(
                        update={
                            "result": retained_result,
                            "cards": retained_cards,
                            "meal_need_state": retained_state,
                        }
                    )

                    cursor.execute(
                        """
                        SELECT state_version FROM chat_session
                        WHERE session_id=:session_id FOR UPDATE
                        """,
                        session_id=session_id,
                    )
                    session = _row(cursor)
                    if session is None or int(session["state_version"]) != int(
                        row["state_version"]
                    ):
                        raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
                    resulting_state_version = int(row["state_version"]) + 1
                    snapshot = snapshot.model_copy(
                        update={
                            "assistant_message_id": (
                                "msg_a_v2_"
                                + hashlib.sha256(f"{session_id}:{request_id}".encode()).hexdigest()[
                                    :40
                                ]
                            ),
                            "state_version": resulting_state_version,
                        }
                    )
                    cursor.execute(
                        """
                        UPDATE chat_session
                        SET meal_need_state_json=:meal_need_state,
                            state_version=:next_version,updated_at=:updated_at
                        WHERE session_id=:session_id AND state_version=:expected_version
                        """,
                        meal_need_state=snapshot.meal_need_state.model_dump_json(),
                        next_version=resulting_state_version,
                        updated_at=_now(),
                        session_id=session_id,
                        expected_version=int(row["state_version"]),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")

            serialized_result = (
                json.dumps(
                    result_json,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if result_json is not None
                else None
            )
            final_candidates = []
            if result_json is not None:
                for rank, item in enumerate(result_json.get("recommendations", []), start=1):
                    if not isinstance(item, dict):
                        continue
                    menu = cast(dict[str, Any], item.get("menu") or {})
                    final_candidates.append(
                        {
                            "rank": rank,
                            "menu_id": str(item.get("menu_id") or menu.get("menu_id") or ""),
                            "merchant_id": str(menu.get("merchant_id") or ""),
                        }
                    )
            serialized_final = json.dumps(
                final_candidates,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            ranking_trace = dict(_json(row.get("ranking_trace_json") or "{}"))
            ranking_trace.update(
                {
                    "selection_status": (
                        "GROK_SELECTED"
                        if status is RecommendationRequestStatus.COMPLETED
                        else "DETERMINISTIC_FALLBACK"
                        if status is RecommendationRequestStatus.SEARCH_FALLBACK
                        else status.value
                    ),
                    "fallback_reason": failure_code,
                    "grounding_rejection_code": grounding_rejection_code,
                    "grounding_rejection_stage": grounding_rejection_stage,
                    "grounding_rejection_detail": grounding_rejection_detail,
                    "final_candidates": final_candidates,
                    "provider_metrics": dict(provider_metrics or {}),
                }
            )
            serialized_ranking_trace = json.dumps(
                ranking_trace,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if snapshot is not None:
                if criteria_row is None or pinned_family is None:
                    raise RuntimeError("RECOMMENDATION_SNAPSHOT_CONTEXT_MISSING")
                cursor.execute(
                    """
                    INSERT INTO chat_message(
                      message_id,session_id,role,content,message_type,
                      safe_metadata_json,created_at
                    ) VALUES (:1,:2,'assistant','Structured recommendation snapshot.',
                              'structured_recommendation_audit',:3,:4)
                    """,
                    [
                        snapshot.assistant_message_id,
                        session_id,
                        json.dumps(
                            {
                                "request_id": request_id,
                                "state_version": resulting_state_version,
                                "non_user_visible": True,
                            },
                            separators=(",", ":"),
                        ),
                        snapshot.created_at,
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO recommendation_snapshot(
                      snapshot_id,session_id,assistant_message_id,state_version,
                      meal_need_state_json,result_json,cards_json,structured_request_id,
                      criteria_version,criteria_json,criteria_hash,
                      recommendation_release_family_id,evidence_pool_json,
                      generation_status,generation_call_count,
                      grounding_validation_json,ranking_trace_json,ranking_policy_version,
                      support_manifest_sha256,feature_manifest_sha256,created_at
                    ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13,:14,:15,:16,:17,:18,:19,:20,:21)
                    """,
                    [
                        snapshot.snapshot_id,
                        snapshot.session_id,
                        snapshot.assistant_message_id,
                        resulting_state_version,
                        snapshot.meal_need_state.model_dump_json(),
                        snapshot.result.model_dump_json(),
                        json.dumps(snapshot.cards, ensure_ascii=False),
                        request_id,
                        int(row["criteria_version"]),
                        _json_text(criteria_row["criteria_json"]),
                        str(criteria_row["criteria_hash"]),
                        pinned_family.release_family_id,
                        _json_text(row["evidence_pool_json"]),
                        status.value,
                        int(row["dispatch_count"]),
                        json.dumps({"validated": True}, separators=(",", ":")),
                        serialized_ranking_trace,
                        str(
                            row.get("ranking_policy_version")
                            or pinned_family.ranking_policy_version
                        ),
                        str(
                            row.get("support_manifest_sha256")
                            or pinned_family.support_manifest_sha256
                        ),
                        str(
                            row.get("feature_manifest_sha256")
                            or pinned_family.feature_manifest_sha256
                        ),
                        snapshot.created_at,
                    ],
                )

            completed_at = _now()
            cursor.execute(
                """
                UPDATE structured_recommendation_request
                SET status=:status,result_json=:result_json,snapshot_id=:snapshot_id,
                    failure_code=:failure_code,completed_at=:completed_at,
                    state_version=:state_version,final_candidates_json=:final_candidates,
                    ranking_trace_json=:ranking_trace,finalized_at=:finalized_at
                WHERE session_id=:session_id AND request_id=:request_id
                  AND status=:expected_status
                """,
                status=status.value,
                result_json=serialized_result,
                snapshot_id=snapshot.snapshot_id if snapshot else None,
                failure_code=failure_code,
                completed_at=completed_at,
                state_version=resulting_state_version,
                final_candidates=serialized_final,
                ranking_trace=serialized_ranking_trace,
                finalized_at=completed_at,
                session_id=session_id,
                request_id=request_id,
                expected_status=current_status.value,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("RECOMMENDATION_COMPLETION_CONFLICT")
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=request_id,
            )
            stored = _row(cursor)
            if stored is None:
                raise RuntimeError("RECOMMENDATION_COMPLETION_WRITE_FAILED")
            return self._request_record_from_row(stored)

    def get_recommendation_request(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=request_id,
            )
            row = _row(cursor)
        return self._request_record_from_row(row) if row else None

    def get_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
    ) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT result_json FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                session_id=session_id,
                request_id=recommendation_request_id,
            )
            row = cursor.fetchone()
        if row is None or row[0] is None:
            return None
        result = _json(row[0])
        cache = result.get("comparison_cache", {}) if isinstance(result, dict) else {}
        cached = cache.get("canonical") if isinstance(cache, dict) else None
        if not isinstance(cached, dict) and isinstance(cache, dict):
            cached = next(
                (value for _key, value in sorted(cache.items()) if isinstance(value, dict)),
                None,
            )
        return dict(cached) if isinstance(cached, dict) else None

    def save_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT result_json,status FROM structured_recommendation_request
                WHERE session_id=:session_id AND request_id=:request_id FOR UPDATE
                """,
                session_id=session_id,
                request_id=recommendation_request_id,
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
            if str(row[1]) not in {"COMPLETED", "SEARCH_FALLBACK"}:
                raise ValueError("RECOMMENDATION_COMPARISON_NOT_AVAILABLE")
            result = _json(row[0]) if row[0] is not None else {}
            if not isinstance(result, dict):
                raise ValueError("RECOMMENDATION_COMPARISON_CACHE_INVALID")
            cache = result.setdefault("comparison_cache", {})
            if not isinstance(cache, dict):
                raise ValueError("RECOMMENDATION_COMPARISON_CACHE_INVALID")
            existing = cache.get("canonical")
            if not isinstance(existing, dict):
                existing = next(
                    (value for _key, value in sorted(cache.items()) if isinstance(value, dict)),
                    None,
                )
            if isinstance(existing, dict):
                return dict(existing), True
            cache["canonical"] = payload
            cursor.execute(
                """
                UPDATE structured_recommendation_request SET result_json=:result_json
                WHERE session_id=:session_id AND request_id=:request_id
                """,
                result_json=json.dumps(result, ensure_ascii=False, sort_keys=True),
                session_id=session_id,
                request_id=recommendation_request_id,
            )
        return dict(payload), False

    def get_latest_recommendation_request(
        self,
        session_id: str,
        *,
        active_only: bool = False,
    ) -> RecommendationRequestRecord | None:
        active_clause = (
            "AND status IN ('CREATED','DISPATCHED') AND client_cancelled_at IS NULL"
            if active_only
            else ""
        )
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"""
                SELECT * FROM (
                  SELECT * FROM structured_recommendation_request
                  WHERE session_id=:session_id {active_clause}
                  ORDER BY created_at DESC,request_id DESC
                ) WHERE ROWNUM=1
                """,
                session_id=session_id,
            )
            row = _row(cursor)
        return self._request_record_from_row(row) if row else None

    def get_active_recommendation_release_family(
        self,
    ) -> RecommendationReleaseFamily | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT family.* FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                """
            )
            row = _row(cursor)
        if row is None:
            return None
        return RecommendationReleaseFamily(
            release_family_id=str(row["release_family_id"]),
            knowledge_release_id=str(row["knowledge_release_id"]),
            catalog_release_id=str(row["catalog_release_id"]),
            preference_catalog_version=str(row["preference_catalog_version"]),
            spice_reference_version=str(row["spice_reference_version"]),
            certification_release_id=str(row["certification_release_id"]),
            embedding_model=str(row["embedding_model"]),
            embedding_version=str(row["embedding_version"]),
            support_manifest_sha256=str(row.get("support_manifest_sha256") or "0" * 64),
            feature_manifest_sha256=str(row.get("feature_manifest_sha256") or "0" * 64),
            ranking_policy_version=str(row.get("ranking_policy_version") or "legacy-llm-rank-v2"),
            ranking_policy_sha256=str(row.get("ranking_policy_sha256") or "0" * 64),
            synthetic_enrichment_release_id=(
                str(row["synthetic_enrichment_release_id"])
                if row.get("synthetic_enrichment_release_id")
                else None
            ),
            status=cast(Any, str(row["status"])),
            activated_at=_datetime(row["activated_at"]) if row.get("activated_at") else None,
        )

    @staticmethod
    def _recommendation_release_family_in_connection(
        connection: oracledb.Connection,
        release_family_id: str,
    ) -> RecommendationReleaseFamily | None:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT * FROM recommendation_release_family
            WHERE release_family_id=:release_family_id
              AND status IN ('READY','ACTIVE','RETIRED')
            """,
            release_family_id=release_family_id,
        )
        row = _row(cursor)
        if row is None:
            return None
        return RecommendationReleaseFamily(
            release_family_id=str(row["release_family_id"]),
            knowledge_release_id=str(row["knowledge_release_id"]),
            catalog_release_id=str(row["catalog_release_id"]),
            preference_catalog_version=str(row["preference_catalog_version"]),
            spice_reference_version=str(row["spice_reference_version"]),
            certification_release_id=str(row["certification_release_id"]),
            embedding_model=str(row["embedding_model"]),
            embedding_version=str(row["embedding_version"]),
            support_manifest_sha256=str(row.get("support_manifest_sha256") or "0" * 64),
            feature_manifest_sha256=str(row.get("feature_manifest_sha256") or "0" * 64),
            ranking_policy_version=str(row.get("ranking_policy_version") or "legacy-llm-rank-v2"),
            ranking_policy_sha256=str(row.get("ranking_policy_sha256") or "0" * 64),
            synthetic_enrichment_release_id=(
                str(row["synthetic_enrichment_release_id"])
                if row.get("synthetic_enrichment_release_id")
                else None
            ),
            status=cast(Any, str(row["status"])),
            activated_at=_datetime(row["activated_at"]) if row.get("activated_at") else None,
        )

    def list_valid_halal_certified_menu_ids(
        self,
        *,
        at: datetime | None = None,
    ) -> set[str]:
        instant = at or _now()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT certification.scope_type,certification.scope_ref,
                       certification.merchant_id
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                JOIN merchant_certification certification
                  ON certification.certification_release_id=family.certification_release_id
                WHERE state.state_key='ACTIVE'
                  AND certification.certification_type='HALAL'
                  AND certification.status='ACTIVE'
                  AND certification.valid_from<=:instant
                  AND (certification.valid_to IS NULL OR certification.valid_to>:instant)
                """,
                instant=instant,
            )
            rows = _rows(cursor)
            merchant_ids = [
                str(row["merchant_id"]) for row in rows if row["scope_type"] == "MERCHANT"
            ]
            menu_ids = {
                str(row["scope_ref"])
                for row in rows
                if row["scope_type"] == "MENU" and row.get("scope_ref")
            }
            if merchant_ids:
                bind_names = [f"merchant_{index}" for index in range(len(merchant_ids))]
                binds = dict(zip(bind_names, merchant_ids))
                cursor.execute(
                    f"""
                    SELECT menu_id FROM menu
                    WHERE merchant_id IN ({",".join(":" + name for name in bind_names)})
                      AND availability='AVAILABLE'
                    """,
                    binds,
                )
                menu_ids.update(str(row[0]) for row in cursor.fetchall())
        return menu_ids

    def get_preference_catalog(self, locale: str) -> dict[str, Any]:
        family = self.get_active_recommendation_release_family()
        if family is None:
            raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT option_code FROM recommendation_preference_option
                WHERE catalog_version=:catalog_version AND active=1
                ORDER BY category_code,display_order,option_code
                """,
                catalog_version=family.preference_catalog_version,
            )
            active_codes = frozenset(str(row[0]) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT support.option_code,
                       COUNT(DISTINCT mapping.menu_id),
                       COUNT(DISTINCT menu.merchant_id),
                       COUNT(DISTINCT document.document_id)
                FROM concept_preference_support support
                JOIN menu_concept_map mapping
                  ON mapping.release_id=support.knowledge_release_id
                 AND mapping.concept_id=support.concept_id
                 AND mapping.mapping_status='MAPPED'
                 AND mapping.confidence_band='high'
                JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
                JOIN knowledge_chunk chunk
                  ON chunk.release_id=support.knowledge_release_id
                 AND chunk.chunk_id=support.evidence_chunk_id
                JOIN knowledge_document document
                  ON document.release_id=chunk.release_id
                 AND document.document_id=chunk.document_id
                WHERE support.knowledge_release_id=:release_id
                  AND support.support_status='SUPPORTED'
                  AND support.review_status IN ('REVIEWED_DEMO','VERIFIED')
                  AND document.review_status IN ('REVIEWED_DEMO','VERIFIED')
                  AND menu.price>0 AND COALESCE(source_detail.liquor,0)=0
                  AND COALESCE(source_detail.is_adult,0)=0
                  AND COALESCE(source_detail.verified_adult,0)=0
                  AND COALESCE(source_detail.soldout,0)=0
                GROUP BY support.option_code
                """,
                release_id=family.knowledge_release_id,
            )
            metrics = {
                str(row[0]): (int(row[1]), int(row[2]), int(row[3])) for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT CASE
                         WHEN menu.price<10000 THEN 'UNDER_10000'
                         WHEN menu.price<20000 THEN 'FROM_10000_TO_19999'
                         WHEN menu.price<30000 THEN 'FROM_20000_TO_29999'
                         ELSE 'OVER_30000'
                       END option_code,
                       COUNT(DISTINCT menu.menu_id),COUNT(DISTINCT menu.merchant_id),
                       COUNT(DISTINCT document.document_id)
                FROM menu_concept_map mapping
                JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
                JOIN knowledge_document document
                  ON document.release_id=mapping.release_id
                 AND document.concept_id=mapping.concept_id
                 AND document.review_status IN ('REVIEWED_DEMO','VERIFIED')
                WHERE mapping.release_id=:release_id AND mapping.mapping_status='MAPPED'
                  AND mapping.confidence_band='high' AND menu.price>0
                  AND COALESCE(source_detail.liquor,0)=0
                  AND COALESCE(source_detail.is_adult,0)=0
                  AND COALESCE(source_detail.verified_adult,0)=0
                  AND COALESCE(source_detail.soldout,0)=0
                GROUP BY CASE
                           WHEN menu.price<10000 THEN 'UNDER_10000'
                           WHEN menu.price<20000 THEN 'FROM_10000_TO_19999'
                           WHEN menu.price<30000 THEN 'FROM_20000_TO_29999'
                           ELSE 'OVER_30000'
                         END
                """,
                release_id=family.knowledge_release_id,
            )
            metrics.update(
                {str(row[0]): (int(row[1]), int(row[2]), int(row[3])) for row in cursor.fetchall()}
            )
            cursor.execute(
                """
                SELECT
                  COUNT(DISTINCT CASE WHEN menu.spice_status IN ('REVIEWED','VERIFIED')
                    AND menu.spice_level IS NOT NULL THEN menu.menu_id END),
                  COUNT(DISTINCT CASE WHEN menu.spice_status IN ('REVIEWED','VERIFIED')
                    AND menu.spice_level IS NOT NULL THEN menu.merchant_id END),
                  COUNT(DISTINCT CASE WHEN EXISTS (
                    SELECT 1 FROM menu_dietary_attribute relation
                    JOIN dietary_attribute attribute
                      ON attribute.attribute_id=relation.attribute_id
                    WHERE relation.menu_id=menu.menu_id
                      AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                      AND upper(relation.status)='VERIFIED'
                  ) THEN menu.menu_id END),
                  COUNT(DISTINCT CASE WHEN EXISTS (
                    SELECT 1 FROM menu_dietary_attribute relation
                    JOIN dietary_attribute attribute
                      ON attribute.attribute_id=relation.attribute_id
                    WHERE relation.menu_id=menu.menu_id
                      AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                      AND upper(relation.status)='VERIFIED'
                  ) THEN menu.merchant_id END)
                FROM menu_concept_map mapping
                JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                WHERE mapping.release_id=:release_id AND mapping.mapping_status='MAPPED'
                  AND mapping.confidence_band='high'
                """,
                release_id=family.knowledge_release_id,
            )
            capability_row = cursor.fetchone()
            _halal_menus = len(
                self._valid_halal_certifications_in_connection(
                    connection,
                    instant=_now(),
                    certification_release_id=family.certification_release_id,
                )
            )
            synthetic_price_bounds: tuple[Any, ...] | None = None
            synthetic_country_rows: list[tuple[Any, ...]] = []
            synthetic_capability: tuple[Any, ...] | None = None
            if family.synthetic_enrichment_release_id:
                cursor.execute(
                    """
                    SELECT MIN(menu.price),MAX(menu.price)
                    FROM synthetic_menu_profile profile
                    JOIN menu ON menu.menu_id=profile.menu_id
                    WHERE profile.release_id=:release_id
                      AND menu.availability='AVAILABLE'
                    """,
                    release_id=family.synthetic_enrichment_release_id,
                )
                synthetic_price_bounds = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT country_code,spice_baseline
                    FROM synthetic_country_profile
                    WHERE release_id=:release_id ORDER BY country_code
                    """,
                    release_id=family.synthetic_enrichment_release_id,
                )
                synthetic_country_rows = list(cursor.fetchall())
                cursor.execute(
                    """
                    SELECT SUM(halal_fit),SUM(vegan_fit),COUNT(*)
                    FROM synthetic_menu_profile WHERE release_id=:release_id
                    """,
                    release_id=family.synthetic_enrichment_release_id,
                )
                synthetic_capability = cursor.fetchone()
        exposed_codes = (
            frozenset(
                code
                for code in active_codes
                if preference_option_is_exposable(
                    code,
                    menu_count=metrics.get(code, (0, 0, 0))[0],
                    merchant_count=metrics.get(code, (0, 0, 0))[1],
                    document_count=metrics.get(code, (0, 0, 0))[2],
                )
            )
            if family.ranking_policy_version == RANKING_POLICY_VERSION
            else active_codes
        )
        payload = localized_preference_catalog(locale, exposed_codes=exposed_codes)
        group_by_category = {
            "cuisine_origins": "core",
            "main_ingredients": "core",
            "food_forms": "core",
            "flavors": "additional",
            "textures": "additional",
            "cooking_methods": "additional",
            "temperatures": "additional",
            "price_bands": "exact",
        }
        for category in cast(list[dict[str, Any]], payload["categories"]):
            category["group"] = group_by_category[str(category["code"])]
            for option in cast(list[dict[str, Any]], category["options"]):
                menu_count, merchant_count, document_count = metrics.get(
                    str(option["code"]), (0, 0, 0)
                )
                option.update(
                    {
                        "eligible_menu_count": menu_count,
                        "eligible_merchant_count": merchant_count,
                        "reviewed_document_count": document_count,
                    }
                )
        _spice_enabled = bool(
            capability_row and int(capability_row[0] or 0) >= 3 and int(capability_row[1] or 0) >= 2
        )
        _vegan_enabled = bool(
            capability_row and int(capability_row[2] or 0) >= 3 and int(capability_row[3] or 0) >= 2
        )
        payload["capabilities"] = {
            "halal_certified_only": {
                "enabled": bool(
                    synthetic_capability and int(synthetic_capability[0] or 0) >= 3
                ),
                "disabled_reason": None
                if synthetic_capability and int(synthetic_capability[0] or 0) >= 3
                else "Enrichment data is not ready.",
            },
            "vegan": {
                "enabled": bool(
                    synthetic_capability and int(synthetic_capability[1] or 0) >= 3
                ),
                "disabled_reason": None
                if synthetic_capability and int(synthetic_capability[1] or 0) >= 3
                else "Enrichment data is not ready.",
            },
            "max_spice_level": {
                "enabled": bool(synthetic_country_rows),
                "disabled_reason": None
                if synthetic_country_rows
                else "Enrichment data is not ready.",
            },
        }
        if synthetic_price_bounds and synthetic_price_bounds[0] is not None:
            minimum = int(synthetic_price_bounds[0])
            maximum = int(synthetic_price_bounds[1])
            payload["price_range_krw"] = {
                "min": (minimum // 1000) * 1000,
                "max": ((maximum + 999) // 1000) * 1000,
                "step": 1000,
            }
        payload["country_spice_profiles"] = [
            {"country_code": str(row[0]), "spice_baseline": int(row[1])}
            for row in synthetic_country_rows
        ]
        payload["schema_version"] = "3"
        payload["synthetic_enrichment_release_id"] = family.synthetic_enrichment_release_id
        payload["spice_reference_version"] = family.spice_reference_version
        payload["knowledge_release_id"] = family.knowledge_release_id
        payload["support_manifest_sha256"] = family.support_manifest_sha256
        payload["feature_manifest_sha256"] = family.feature_manifest_sha256
        payload["ranking_policy_version"] = family.ranking_policy_version
        return dict(payload)

    def _save_browse_snapshot(
        self,
        session_id: str,
        menus: list[MenuSummary],
        *,
        query_summary: str,
    ) -> str:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError("SESSION_NOT_FOUND")
        snapshot_id = _id("snapshot_browse")
        assistant_message_id = _id("msg_a_browse")
        need_state = session.meal_need_state.model_copy(deep=True)
        need_state.shown_menu_ids = list(
            dict.fromkeys([*need_state.shown_menu_ids, *(menu.menu_id for menu in menus)])
        )
        result = RecommendationResult(
            snapshot_id=snapshot_id,
            candidates=[
                RecommendationCandidate(
                    menu_id=menu.menu_id,
                    merchant_id=menu.merchant_id,
                    rank=index,
                    score=round(max(0.0, 1.0 - (index - 1) * 0.01), 6),
                    match_reasons=list(menu.match_reasons),
                    risk_hints=list(menu.risk_hints),
                    evidence_ids=list(menu.evidence_ids),
                    claim_ids=list(menu.grounded_claim_ids),
                    passage_ids=list(menu.grounded_passage_ids),
                )
                for index, menu in enumerate(menus, start=1)
            ],
            query_summary=query_summary,
            grounded_claim_ids=list(
                dict.fromkeys(claim for menu in menus for claim in menu.grounded_claim_ids)
            ),
            grounded_passage_ids=list(
                dict.fromkeys(passage for menu in menus for passage in menu.grounded_passage_ids)
            ),
            synthetic_data=all(menu.is_synthetic for menu in menus),
        )
        cards = [
            {"type": "browse_menu", "data": {"menu": menu.model_dump(mode="json")}}
            for menu in menus
        ]
        created_at = _now()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO chat_message(
                  message_id,session_id,role,content,message_type,safe_metadata_json,created_at
                ) VALUES (:message_id,:session_id,'assistant',
                          'Browse collection authorization snapshot.',
                          'browse_snapshot_audit',:metadata,:created_at)
                """,
                message_id=assistant_message_id,
                session_id=session_id,
                metadata=json.dumps({"non_user_visible": True}, separators=(",", ":")),
                created_at=created_at,
            )
            cursor.execute(
                """
                INSERT INTO recommendation_snapshot(
                  snapshot_id,session_id,assistant_message_id,state_version,
                  meal_need_state_json,result_json,cards_json,generation_status,created_at
                ) VALUES (:snapshot_id,:session_id,:assistant_message_id,:state_version,
                          :meal_need_state_json,:result_json,:cards_json,'BROWSE',:created_at)
                """,
                snapshot_id=snapshot_id,
                session_id=session_id,
                assistant_message_id=assistant_message_id,
                state_version=session.state_version,
                meal_need_state_json=need_state.model_dump_json(),
                result_json=result.model_dump_json(),
                cards_json=json.dumps(cards, ensure_ascii=False),
                created_at=created_at,
            )
        return snapshot_id

    @staticmethod
    def _browse_profile_state(
        connection: oracledb.Connection,
        session_id: str,
    ) -> tuple[MealNeedState, str]:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT session.meal_need_state_json,profile.dietary_rules_json,
                   profile.religion_selection,profile.allergy_severity
            FROM chat_session session JOIN user_profile profile
              ON profile.profile_id=session.profile_id
            WHERE session.session_id=:session_id
            """,
            session_id=session_id,
        )
        row = _row(cursor)
        if row is None:
            raise KeyError("SESSION_NOT_FOUND")
        state = apply_profile_constraints(
            MealNeedState.model_validate(_json(row["meal_need_state_json"] or "{}")),
            list(_json(row["dietary_rules_json"] or "[]")),
            str(row["religion_selection"]),
        )
        return state, str(row["allergy_severity"])

    @staticmethod
    def _browse_exact_filter_sql(
        connection: oracledb.Connection,
        session_id: str,
    ) -> tuple[str, dict[str, Any]]:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT criteria_json FROM (
              SELECT criteria_json FROM session_recommendation_criteria
              WHERE session_id=:session_id ORDER BY criteria_version DESC
            ) WHERE ROWNUM=1
            """,
            session_id=session_id,
        )
        row = cursor.fetchone()
        if row is None:
            return "", {}
        criteria = RecommendationCriteriaV2.model_validate(_json(row[0]))
        conditions: list[str] = []
        parameters: dict[str, Any] = {}
        price_conditions = [
            {
                "UNDER_10000": "menu.price<10000",
                "FROM_10000_TO_19999": "menu.price BETWEEN 10000 AND 19999",
                "FROM_20000_TO_29999": "menu.price BETWEEN 20000 AND 29999",
                "OVER_30000": "menu.price>=30000",
            }[band]
            for band in criteria.price_bands
        ]
        if price_conditions:
            conditions.append("(" + " OR ".join(price_conditions) + ")")
        if criteria.max_spice_level < 5:
            parameters["browse_max_spice_level"] = criteria.max_spice_level
            conditions.extend(
                [
                    "menu.spice_status IN ('REVIEWED','VERIFIED')",
                    "menu.spice_level<=:browse_max_spice_level",
                ]
            )
        if criteria.dietary_filters.halal_certified_only:
            parameters["browse_eligibility_as_of"] = _now()
            conditions.append(
                """EXISTS (
                  SELECT 1 FROM merchant_certification certification
                  WHERE certification.certification_release_id=family.certification_release_id
                    AND certification.merchant_id=menu.merchant_id
                    AND certification.certification_type='HALAL'
                    AND certification.status='ACTIVE'
                    AND certification.valid_from<=:browse_eligibility_as_of
                    AND (certification.valid_to IS NULL
                         OR certification.valid_to>=:browse_eligibility_as_of)
                    AND (certification.scope_type='MERCHANT'
                         OR (certification.scope_type='MENU'
                             AND certification.scope_ref=menu.menu_id))
                )"""
            )
        if criteria.dietary_filters.vegan:
            conditions.append(
                """EXISTS (
                  SELECT 1 FROM menu_dietary_attribute relation
                  JOIN dietary_attribute attribute
                    ON attribute.attribute_id=relation.attribute_id
                  WHERE relation.menu_id=menu.menu_id
                    AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                    AND upper(relation.status)='VERIFIED'
                )"""
            )
        return (" AND " + " AND ".join(conditions) if conditions else ""), parameters

    def list_food_rankings(
        self,
        session_id: str,
        sort: FoodRankingSort,
        limit: int,
    ) -> FoodRankingCollection:
        bounded_limit = max(1, min(20, limit))
        order_expression = {
            "review_count": "ranking_review_count",
            "order_count": "ranking_order_count",
            "korean_popularity": "ranking_korean_popularity",
        }[sort]
        ranking_sql = food_ranking_sql(
            "oracle",
            menu_id="menu.menu_id",
            is_synthetic="menu.is_synthetic",
            menu_review_count="source.review_count",
            merchant_review_count="merchant_source.review_count",
        )
        with self.pool.connection() as connection:
            service_area_id, _excluded = self._structured_session_filters(
                connection, session_id, exclude_history=False
            )
            exact_clause, binds = self._browse_exact_filter_sql(connection, session_id)
            area_clause = ""
            if service_area_id:
                area_clause = "AND merchant.service_area_id=:service_area_id"
                binds["service_area_id"] = service_area_id
            cursor = connection.cursor()
            cursor.execute(
                f"""
                SELECT * FROM (
                  SELECT menu.menu_id,menu.merchant_id,
                         COALESCE(merchant.name_en,merchant.name_ko) merchant_name,
                         menu.name_en,menu.name_ko,menu.category,menu.description,
                         menu.cultural_description,menu.price,
                         COALESCE(merchant.delivery_fee,0) delivery_fee,
                         COALESCE(merchant.eta_min,0) eta_min,
                         COALESCE(merchant.eta_max,0) eta_max,
                         menu.spice_level,menu.serves_min,menu.serves_max,menu.is_synthetic,
                         COALESCE(source.review_count,0) source_menu_review_count,
                         COALESCE(merchant_source.review_count,0) source_merchant_review_count,
                         {ranking_sql.review_count} ranking_review_count,
                         {ranking_sql.order_count} ranking_order_count,
                         {ranking_sql.korean_popularity} ranking_korean_popularity,
                         {ranking_sql.basis} ranking_metric_basis,
                         mapping.concept_id,
                         (SELECT content FROM (
                            SELECT chunk.content FROM knowledge_chunk chunk
                            JOIN knowledge_document document
                              ON document.release_id=chunk.release_id
                             AND document.document_id=chunk.document_id
                            WHERE chunk.release_id=mapping.release_id
                              AND chunk.concept_id=mapping.concept_id
                              AND document.source_type='SYNTHETIC_WIKI'
                              AND document.review_status='REVIEWED_DEMO'
                              AND lower(chunk.facet)<>'safety'
                              AND (
                                JSON_VALUE(chunk.metadata_json,
                                           '$.recommendation_visibility')='PUBLIC_RAG'
                                OR JSON_VALUE(chunk.metadata_json,
                                              '$.recommendation_visibility') IS NULL
                              )
                            ORDER BY chunk.chunk_id
                          ) WHERE ROWNUM=1) concept_description
                  FROM recommendation_runtime_state state
                  JOIN recommendation_release_family family
                    ON family.release_family_id=state.active_release_family_id
                   AND family.status='ACTIVE'
                  JOIN menu_concept_map mapping
                    ON mapping.release_id=family.knowledge_release_id
                   AND mapping.mapping_status='MAPPED' AND mapping.confidence_band='high'
                  JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                  JOIN merchant ON merchant.merchant_id=menu.merchant_id
                  LEFT JOIN menu_source_detail source ON source.menu_id=menu.menu_id
                  LEFT JOIN merchant_source_detail merchant_source
                    ON merchant_source.merchant_id=menu.merchant_id
                  WHERE state.state_key='ACTIVE' AND menu.price>0
                    AND COALESCE(source.liquor,0)=0 AND COALESCE(source.is_adult,0)=0
                    AND COALESCE(source.verified_adult,0)=0 AND COALESCE(source.soldout,0)=0
                    {area_clause}
                    {exact_clause}
                  ORDER BY {order_expression} DESC,menu.merchant_id,menu.menu_id
                ) WHERE ROWNUM<=500
                """,
                binds,
            )
            rows = _rows(cursor)
            need_state, allergy_severity = self._browse_profile_state(connection, session_id)
            eligible_rows = [
                row
                for row in rows
                if not self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    need_state,
                    allergy_severity,
                )[0]
            ][:bounded_limit]
        items: list[FoodRankingEntry] = []
        menus: list[MenuSummary] = []
        for position, row in enumerate(eligible_rows, start=1):
            metric_value = {
                "review_count": int(row["ranking_review_count"] or 0),
                "order_count": int(row["ranking_order_count"] or 0),
                "korean_popularity": int(row["ranking_korean_popularity"] or 0),
            }[sort]
            if str(row["ranking_metric_basis"]) == "DETERMINISTIC_SYNTHETIC_FALLBACK":
                metric_label = {
                    "review_count": "Deterministic demo review score",
                    "order_count": "Deterministic demo order score",
                    "korean_popularity": "Deterministic demo Korean-popularity score",
                }[sort]
            else:
                metric_label = {
                    "review_count": "Source menu review count",
                    "order_count": "Deterministic demo order proxy",
                    "korean_popularity": "Deterministic demo Korean-popularity proxy",
                }[sort]
            menu = self._menu_summary(
                row,
                ["Available mapped menu in the current demo delivery area"],
                ["Ranking is a demo view, not a live platform-wide ranking"],
                EvidenceStatus.UNKNOWN,
                1.0,
            )
            if row.get("concept_description"):
                menu = menu.model_copy(
                    update={
                        "cultural_description": (
                            "General food reference: " + str(row["concept_description"])
                        )
                    }
                )
            menus.append(menu)
            items.append(
                FoodRankingEntry(
                    position=position,
                    metric_label=metric_label,
                    metric_value=metric_value,
                    menu=menu,
                )
            )
        snapshot_id = self._save_browse_snapshot(
            session_id, menus, query_summary=f"Deterministic demo food ranking: {sort}"
        )
        return FoodRankingCollection(
            snapshot_id=snapshot_id,
            demo_basis=(
                "YOBI demo only. Provided source counts take priority. Synthetic menus with "
                "no source counts use stable menu-ID-derived demo scores so sort controls "
                "remain demonstrable. No value is a live Yogiyo-wide statistic."
            ),
            sort=sort,
            items=items,
        )

    def list_kpop_demon_hunters_feature(
        self,
        session_id: str,
    ) -> FeaturedMenuCollection:
        feature_names = ("Gimbap", "Gukbap", "Hotteok", "Seolleongtang", "Eomuk")
        with self.pool.connection() as connection:
            service_area_id, _excluded = self._structured_session_filters(
                connection, session_id, exclude_history=False
            )
            exact_clause, binds = self._browse_exact_filter_sql(connection, session_id)
            binds.update({f"feature_{index}": name for index, name in enumerate(feature_names)})
            feature_binds = [f":feature_{index}" for index in range(len(feature_names))]
            area_clause = ""
            if service_area_id:
                area_clause = "AND merchant.service_area_id=:service_area_id"
                binds["service_area_id"] = service_area_id
            cursor = connection.cursor()
            cursor.execute(
                f"""
                SELECT * FROM (
                  SELECT menu.menu_id,menu.merchant_id,
                         COALESCE(merchant.name_en,merchant.name_ko) merchant_name,
                         menu.name_en,menu.name_ko,menu.category,menu.description,
                         menu.cultural_description,menu.price,
                         COALESCE(merchant.delivery_fee,0) delivery_fee,
                         COALESCE(merchant.eta_min,0) eta_min,
                         COALESCE(merchant.eta_max,0) eta_max,
                         menu.spice_level,menu.serves_min,menu.serves_max,menu.is_synthetic,
                         concept.canonical_name_en dish_name,
                         (SELECT content FROM (
                            SELECT chunk.content FROM knowledge_chunk chunk
                            JOIN knowledge_document document
                              ON document.release_id=chunk.release_id
                             AND document.document_id=chunk.document_id
                            WHERE chunk.release_id=mapping.release_id
                              AND chunk.concept_id=mapping.concept_id
                              AND document.source_type='SYNTHETIC_WIKI'
                              AND document.review_status='REVIEWED_DEMO'
                              AND lower(chunk.facet)<>'safety'
                              AND (
                                JSON_VALUE(chunk.metadata_json,
                                           '$.recommendation_visibility')='PUBLIC_RAG'
                                OR JSON_VALUE(chunk.metadata_json,
                                              '$.recommendation_visibility') IS NULL
                              )
                            ORDER BY chunk.chunk_id
                          ) WHERE ROWNUM=1) concept_description,
                         ROW_NUMBER() OVER (
                           PARTITION BY concept.canonical_name_en
                           ORDER BY COALESCE(source.review_count,0) DESC,
                                    menu.merchant_id,menu.menu_id
                         ) concept_rank
                  FROM recommendation_runtime_state state
                  JOIN recommendation_release_family family
                    ON family.release_family_id=state.active_release_family_id
                   AND family.status='ACTIVE'
                  JOIN menu_concept_map mapping
                    ON mapping.release_id=family.knowledge_release_id
                   AND mapping.mapping_status='MAPPED' AND mapping.confidence_band='high'
                  JOIN dish_concept concept
                    ON concept.release_id=mapping.release_id
                   AND concept.concept_id=mapping.concept_id
                  JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                  JOIN merchant ON merchant.merchant_id=menu.merchant_id
                  LEFT JOIN menu_source_detail source ON source.menu_id=menu.menu_id
                  WHERE state.state_key='ACTIVE' AND menu.price>0
                    AND concept.canonical_name_en IN ({",".join(feature_binds)})
                    AND COALESCE(source.liquor,0)=0 AND COALESCE(source.is_adult,0)=0
                    AND COALESCE(source.verified_adult,0)=0 AND COALESCE(source.soldout,0)=0
                    {area_clause}
                    {exact_clause}
                ) WHERE concept_rank<=20
                ORDER BY CASE dish_name
                  WHEN 'Gimbap' THEN 1 WHEN 'Gukbap' THEN 2 WHEN 'Hotteok' THEN 3
                  WHEN 'Seolleongtang' THEN 4 WHEN 'Eomuk' THEN 5 ELSE 6 END,concept_rank
                """,
                binds,
            )
            candidate_rows = _rows(cursor)
            need_state, allergy_severity = self._browse_profile_state(connection, session_id)
            rows: list[dict[str, Any]] = []
            seen_dishes: set[str] = set()
            for row in candidate_rows:
                dish_name = str(row["dish_name"])
                if dish_name in seen_dishes:
                    continue
                if self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    need_state,
                    allergy_severity,
                )[0]:
                    continue
                seen_dishes.add(dish_name)
                rows.append(row)
        menus = [
            self._menu_summary(
                row,
                ["Mapped to a food in the K-pop Demon Hunters demo feature"],
                ["General food knowledge does not verify this restaurant's recipe"],
                EvidenceStatus.UNKNOWN,
                1.0,
            ).model_copy(
                update={
                    "cultural_description": (
                        "General food reference: " + str(row.get("concept_description"))
                        if row.get("concept_description")
                        else ""
                    )
                }
            )
            for row in rows
        ]
        snapshot_id = self._save_browse_snapshot(
            session_id, menus, query_summary="K-pop Demon Hunters mapped food feature"
        )
        return FeaturedMenuCollection(
            snapshot_id=snapshot_id,
            items=[
                FeaturedMenuEntry(
                    dish_name=str(row["dish_name"]),
                    description=(
                        str(row.get("concept_description"))
                        if row.get("concept_description")
                        else "No reviewed general food description is available."
                    ),
                    menu=menu,
                )
                for row, menu in zip(rows, menus)
            ],
        )

    @staticmethod
    def _price_matches_v2(price: int, selected_bands: list[str]) -> bool:
        if not selected_bands:
            return True
        return any(
            (
                code == "UNDER_10000"
                and price < 10_000
                or code == "FROM_10000_TO_19999"
                and 10_000 <= price < 20_000
                or code == "FROM_20000_TO_29999"
                and 20_000 <= price < 30_000
                or code == "OVER_30000"
                and price >= 30_000
            )
            for code in selected_bands
        )

    @staticmethod
    def _valid_halal_certifications_in_connection(
        connection: oracledb.Connection,
        *,
        instant: datetime,
        certification_release_id: str,
    ) -> dict[str, tuple[str, str]]:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT certification_id,scope_type,scope_ref,merchant_id
            FROM merchant_certification
            WHERE certification_release_id=:certification_release_id
              AND certification_type='HALAL' AND status='ACTIVE'
              AND valid_from<=:instant
              AND (valid_to IS NULL OR valid_to>:instant)
            ORDER BY certification_id
            """,
            certification_release_id=certification_release_id,
            instant=instant,
        )
        rows = _rows(cursor)
        result: dict[str, tuple[str, str]] = {}
        merchant_certifications: dict[str, tuple[str, str]] = {}
        for row in rows:
            certification_id = str(row["certification_id"])
            if str(row["scope_type"]) == "MERCHANT":
                merchant_certifications[str(row["merchant_id"])] = (
                    certification_id,
                    "Restaurant certification applies to this menu.",
                )
                continue
            menu_id = str(row.get("scope_ref") or "")
            if not menu_id:
                continue
            cursor.execute(
                "SELECT merchant_id FROM menu WHERE menu_id=:menu_id",
                menu_id=menu_id,
            )
            owner = cursor.fetchone()
            if owner is not None and str(owner[0]) == str(row["merchant_id"]):
                result[menu_id] = (
                    certification_id,
                    "Certification applies specifically to this menu.",
                )
        if merchant_certifications:
            bind_names = [f"cert_merchant_{index}" for index in range(len(merchant_certifications))]
            binds = dict(zip(bind_names, merchant_certifications))
            cursor.execute(
                f"""
                SELECT menu_id,merchant_id FROM menu
                WHERE merchant_id IN ({",".join(":" + name for name in bind_names)})
                """,
                binds,
            )
            for row in cursor.fetchall():
                menu_id = str(row[0])
                result.setdefault(menu_id, merchant_certifications[str(row[1])])
        return result

    @staticmethod
    def _v2_vegan_classifications(
        connection: oracledb.Connection,
        menu_ids: list[str],
        knowledge_release_id: str,
    ) -> dict[str, tuple[str, str | None, list[EvidenceReference]]]:
        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        resolved = OracleYobiRepository._bulk_resolved_knowledge_claims(
            connection,
            unique_ids,
            release_id=knowledge_release_id,
        )
        bind_names = [f"vegan_menu_{index}" for index in range(len(unique_ids))]
        binds = dict(zip(bind_names, unique_ids))
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT relation.menu_id,attribute.code,relation.status,relation.evidence_id
            FROM menu_dietary_attribute relation
            JOIN dietary_attribute attribute
              ON attribute.attribute_id=relation.attribute_id
            WHERE relation.menu_id IN ({",".join(":" + name for name in bind_names)})
              AND lower(attribute.code) IN ('vegan_option','vegan_possible')
            """,
            binds,
        )
        dietary_signals: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
        for row in _rows(cursor):
            dietary_signals[str(row["menu_id"])].append(
                (
                    str(row["code"]).lower(),
                    str(row["status"]).upper(),
                    str(row["evidence_id"]) if row.get("evidence_id") else None,
                )
            )

        classifications: dict[str, tuple[str, str | None, list[EvidenceReference]]] = {}
        present = {ClaimStatus.CONFIRMED_PRESENT, ClaimStatus.PRESUMED_PRESENT}
        uncertain = {ClaimStatus.POSSIBLE, ClaimStatus.CONFLICTING}
        for menu_id in unique_ids:
            ingredient_claims = resolved.get(menu_id, ([], [], []))[0]
            vegan_claims = [
                claim for claim in ingredient_claims if claim.ingredient_id in VEGAN_INGREDIENTS
            ]
            confirmed_conflicts = [
                claim
                for claim in vegan_claims
                if claim.status in present
                and (
                    claim.source_scope is SourceScope.MENU
                    or claim.role in {IngredientRole.DEFINING, IngredientRole.CORE}
                )
            ]
            possible_conflicts = [
                claim
                for claim in vegan_claims
                if claim.status in uncertain
                or (claim.status in present and claim not in confirmed_conflicts)
            ]
            references = [
                EvidenceReference(
                    evidence_id=str(claim.source_id),
                    evidence_type="ESSENTIAL_FACT",
                    content=(
                        f"{claim.name_en} is recorded as {claim.status.value.lower()} "
                        f"({claim.role.value.lower()})."
                    ),
                )
                for claim in [*confirmed_conflicts, *possible_conflicts]
            ]
            positive_signals = [
                signal
                for signal in dietary_signals.get(menu_id, [])
                if signal[1] in {"PRESENT", "VERIFIED", "CONFIRMED_PRESENT"}
            ]
            references.extend(
                EvidenceReference(
                    evidence_id=evidence_id or f"fact_{menu_id}_{code}",
                    evidence_type="MENU_FACT",
                    content=f"Catalog signal: {code.replace('_', ' ')} ({status.lower()}).",
                )
                for code, status, evidence_id in positive_signals
            )
            if confirmed_conflicts:
                classifications[menu_id] = ("CONFLICT", None, references)
            elif possible_conflicts:
                classifications[menu_id] = (
                    "POSSIBLE_WITH_CHECKS",
                    "비건으로 주문하려면 옵션이나 재료를 확인해 주세요.",
                    references,
                )
            elif positive_signals:
                classifications[menu_id] = (
                    "LIKELY_FIT",
                    "비건으로 즐기기 좋은 메뉴예요.",
                    references,
                )
            else:
                classifications[menu_id] = ("UNKNOWN", None, references)
        return classifications

    @classmethod
    def _structured_objective_candidates(
        cls,
        connection: oracledb.Connection,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        family: RecommendationReleaseFamily,
        *,
        exclude_history: bool,
        instant: datetime | None = None,
        menu_ids: list[str] | None = None,
        enforce_price_bands: bool = True,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, tuple[str, str]],
        dict[str, tuple[str, str | None, list[EvidenceReference]]],
    ]:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT menu.menu_id,menu.merchant_id,menu.name_en,menu.name_ko,
                   menu.category,menu.description,menu.cultural_description,menu.price,
                   menu.spice_level,menu.serves_min,menu.serves_max,menu.is_synthetic,
                   COALESCE(merchant.name_en,merchant.name_ko) AS merchant_name,
                   merchant.delivery_fee,merchant.eta_min,merchant.eta_max,
                   merchant.service_area_id
            FROM menu
            JOIN merchant ON merchant.merchant_id=menu.merchant_id
            WHERE menu.availability='AVAILABLE'
              AND (menu.spice_level IS NULL OR menu.spice_level<=:max_spice_level)
            """,
            max_spice_level=criteria.max_spice_level,
        )
        rows = _rows(cursor)
        cursor.execute(
            "SELECT meal_need_state_json FROM chat_session WHERE session_id=:session_id",
            session_id=session_id,
        )
        session = _row(cursor)
        if session is None:
            raise KeyError("SESSION_NOT_FOUND")
        need_state = MealNeedState.model_validate(_json(session["meal_need_state_json"] or "{}"))
        cursor.execute(
            """
            SELECT address.service_area_id
            FROM cart
            JOIN address_ref address ON address.address_ref_id=cart.address_ref_id
            JOIN service_area area ON area.service_area_id=address.service_area_id
            WHERE cart.session_id=:session_id AND address.confirmed=1 AND area.active=1
            """,
            session_id=session_id,
        )
        confirmed_area = cursor.fetchone()
        service_area_id = (
            str(confirmed_area[0])
            if confirmed_area is not None and confirmed_area[0]
            else need_state.service_area_id
        )
        excluded_menu_ids = (
            {
                *need_state.shown_menu_ids,
                *need_state.rejected_menu_ids,
                *([need_state.selected_menu_id] if need_state.selected_menu_id else []),
            }
            if exclude_history
            else set()
        )
        rows = [
            row
            for row in rows
            if str(row["menu_id"]) not in excluded_menu_ids
            and (menu_ids is None or str(row["menu_id"]) in menu_ids)
            and (not service_area_id or str(row.get("service_area_id") or "") == service_area_id)
            and (
                not enforce_price_bands
                or cls._price_matches_v2(int(row["price"]), criteria.price_bands)
            )
        ]
        certifications = cls._valid_halal_certifications_in_connection(
            connection,
            instant=instant or _now(),
            certification_release_id=family.certification_release_id,
        )
        if criteria.dietary_filters.halal_certified_only:
            rows = [row for row in rows if str(row["menu_id"]) in certifications]
        vegan = cls._v2_vegan_classifications(
            connection,
            [str(row["menu_id"]) for row in rows],
            family.knowledge_release_id,
        )
        if criteria.dietary_filters.vegan:
            rows = [
                row
                for row in rows
                if vegan.get(str(row["menu_id"]), ("UNKNOWN", None, []))[0]
                in {"LIKELY_FIT", "POSSIBLE_WITH_CHECKS"}
            ]
        return rows, certifications, vegan

    def get_live_recommendation_menu_states(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        release_family_id: str,
        menu_ids: list[str],
        *,
        at: datetime,
    ) -> dict[str, LiveRecommendationMenuState]:
        with self.pool.connection() as connection:
            family = self._recommendation_release_family_in_connection(
                connection, release_family_id
            )
            if family is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_FOUND")
            rows, certifications, vegan = self._structured_objective_candidates(
                connection,
                session_id,
                criteria,
                family,
                exclude_history=False,
                instant=at,
                menu_ids=menu_ids,
                enforce_price_bands=False,
            )
        result: dict[str, LiveRecommendationMenuState] = {}
        for row in rows:
            menu_id = str(row["menu_id"])
            certification = certifications.get(menu_id)
            vegan_status, vegan_warning, _ = vegan.get(menu_id, ("UNKNOWN", None, []))
            result[menu_id] = LiveRecommendationMenuState(
                menu=self._menu_summary(
                    row,
                    [],
                    [],
                    EvidenceStatus.UNKNOWN,
                    0.0,
                ),
                halal_certified=bool(certification),
                halal_scope_label=certification[1] if certification else None,
                vegan_status=cast(Any, vegan_status),
                vegan_warning=vegan_warning,
            )
        return result

    @staticmethod
    def _public_rag_hits(
        connection: oracledb.Connection,
        release_id: str,
        menu_ids: list[str],
        query_vector: array[float],
    ) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return []
        bind_names = [f"rag_menu_{index}" for index in range(len(unique_ids))]
        binds: dict[str, Any] = {
            "release_id": release_id,
            "query_vector": query_vector,
        }
        binds.update(dict(zip(bind_names, unique_ids)))
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT mapping.menu_id,mapping.concept_id AS mapped_concept_id,
                   chunk.chunk_id,chunk.document_id,chunk.concept_id,chunk.facet,
                   chunk.content,concept.canonical_name_ko,concept.canonical_name_en,
                   concept.aliases_json,
                   VECTOR_DISTANCE(chunk.embedding_vector,:query_vector,COSINE) distance
            FROM menu_concept_map mapping
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
             AND closure.inherit_claims=1
            JOIN knowledge_chunk chunk
              ON chunk.release_id=closure.release_id
             AND chunk.concept_id=closure.ancestor_concept_id
            JOIN knowledge_document document
              ON document.release_id=chunk.release_id
             AND document.document_id=chunk.document_id
            JOIN dish_concept concept
              ON concept.release_id=chunk.release_id
             AND concept.concept_id=chunk.concept_id
            WHERE mapping.release_id=:release_id AND mapping.mapping_status='MAPPED'
              AND mapping.menu_id IN ({",".join(":" + name for name in bind_names)})
              AND chunk.embedding_vector IS NOT NULL
              AND document.review_status IN ('REVIEWED_DEMO','VERIFIED')
              AND (
                JSON_VALUE(chunk.metadata_json,'$.recommendation_visibility')='PUBLIC_RAG'
                OR (
                  JSON_VALUE(chunk.metadata_json,'$.recommendation_visibility') IS NULL
                  AND lower(chunk.facet)<>'safety'
                )
              )
            """,
            binds,
        )
        return _rows(cursor)

    def build_recommendation_evidence_pool(
        self,
        session_id: str,
        profile: Profile,
        criteria: RecommendationCriteriaV2,
        mode: RecommendationMode,
        limit: int,
        *,
        release_family_id: str,
        eligibility_as_of: datetime,
        raw_hits_per_value: int,
        passages_per_menu: int,
    ) -> list[EvidencePoolItem]:
        if limit < 1 or raw_hits_per_value < 1 or passages_per_menu < 1:
            return []
        with self.pool.connection() as connection:
            family = self._recommendation_release_family_in_connection(
                connection,
                release_family_id,
            )
            if family is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_FOUND")
            if family.ranking_policy_version == RANKING_POLICY_VERSION:
                concept_pool = self._build_concept_ranked_pool(
                    connection,
                    session_id=session_id,
                    criteria=criteria,
                    profile=profile,
                    mode=mode,
                    limit=limit,
                    family=family,
                    eligibility_as_of=eligibility_as_of,
                    passages_per_menu=passages_per_menu,
                )
                metrics = self._recommendation_retrieval_metrics.get(session_id)
                if metrics is not None:
                    metrics["query_count"] = int(metrics.get("query_count", 0)) + 1
                return concept_pool
            candidate_rows, certifications, vegan = self._structured_objective_candidates(
                connection,
                session_id,
                criteria,
                family,
                exclude_history=mode is RecommendationMode.SIMILAR,
                instant=eligibility_as_of,
            )
        candidate_rows = candidate_rows[:RECOMMENDATION_CANDIDATE_CAP]
        candidate_ids = [str(row["menu_id"]) for row in candidate_rows]
        if not candidate_ids:
            return []

        subjective_groups = criteria.subjective_groups()
        query_aliases_by_code: dict[str, tuple[str, ...]] = {}
        for selected in subjective_groups.values():
            for value_code in selected:
                query_aliases_by_code[value_code] = preference_query_aliases(
                    value_code,
                    profile.preferred_language,
                )
        if not subjective_groups:
            query_aliases_by_code["__fallback__"] = FALLBACK_RECOMMENDATION_QUERY_ALIASES
        query_items = [(code, " ".join(aliases)) for code, aliases in query_aliases_by_code.items()]
        query_vectors = self.embedding_provider.embed(
            [query for _, query in query_items],
            "SEARCH_QUERY",
        )
        if len(query_vectors) != len(query_items):
            raise RuntimeError("PREFERENCE_QUERY_EMBEDDING_COUNT_MISMATCH")
        vector_by_code = {
            code: array("f", vector) for (code, _), vector in zip(query_items, query_vectors)
        }

        hits_by_code: dict[str, list[dict[str, Any]]] = {}
        with self.pool.connection() as connection:
            for code, _ in query_items:
                hits_by_code[code] = self._public_rag_hits(
                    connection,
                    family.knowledge_release_id,
                    candidate_ids,
                    vector_by_code[code],
                )

        ranked_by_code_menu: dict[str, dict[str, list[tuple[float, dict[str, Any]]]]] = {}
        for code, hits in hits_by_code.items():
            rows_by_chunk: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for hit in hits:
                rows_by_chunk[str(hit["chunk_id"])].append(hit)
            unique_candidates: list[HybridChunkCandidate] = []
            for chunk_id, associated_rows in rows_by_chunk.items():
                hit = associated_rows[0]
                aliases = (
                    str(hit.get("canonical_name_ko") or ""),
                    str(hit.get("canonical_name_en") or ""),
                    *tuple(str(alias) for alias in _json(hit.get("aliases_json") or "[]")),
                )
                unique_candidates.append(
                    HybridChunkCandidate(
                        chunk_id=chunk_id,
                        content=str(hit.get("content") or ""),
                        facet=str(hit.get("facet") or ""),
                        aliases=aliases,
                        vector_similarity=max(0.0, 1.0 - float(hit["distance"])),
                    )
                )
            ranked_chunks = rank_hybrid_chunks_rrf(
                query_aliases_by_code[code],
                unique_candidates,
                limit=raw_hits_per_value,
            )
            by_menu: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
            for candidate, score in ranked_chunks:
                for hit in rows_by_chunk[candidate.chunk_id]:
                    by_menu[str(hit["menu_id"])].append((score, hit))
            for values in by_menu.values():
                values.sort(key=lambda item: (-item[0], str(item[1]["chunk_id"])))
            ranked_by_code_menu[code] = by_menu

        pool: list[EvidencePoolItem] = []
        for row in candidate_rows:
            menu_id = str(row["menu_id"])
            criterion_evidence: list[CriterionEvidence] = []
            passage_scores: dict[str, tuple[float, EvidenceReference]] = {}
            category_scores: list[float] = []
            mapped_concept_id: str | None = None
            for category_code, selected_codes in subjective_groups.items():
                selected_scores: list[float] = []
                for value_code in selected_codes:
                    ranked = ranked_by_code_menu.get(value_code, {}).get(menu_id, [])
                    if not ranked:
                        continue
                    best_score, best_hit = ranked[0]
                    mapped_concept_id = str(best_hit["mapped_concept_id"])
                    reference = EvidenceReference(
                        evidence_id=str(best_hit["chunk_id"]),
                        evidence_type=(
                            "ESSENTIAL_FACT"
                            if str(best_hit.get("facet") or "").casefold() == "essential_fact"
                            else "WIKI_PASSAGE"
                        ),
                        content=str(best_hit["content"]),
                        score=round(max(0.0, min(1.0, best_score)), 6),
                    )
                    criterion_evidence.append(
                        CriterionEvidence(
                            category_code=cast(Any, category_code),
                            selected_value_code=value_code,
                            evidence=[reference],
                        )
                    )
                    selected_scores.append(best_score)
                    current = passage_scores.get(reference.evidence_id)
                    if current is None or best_score > current[0]:
                        passage_scores[reference.evidence_id] = (best_score, reference)
                if selected_scores:
                    category_scores.append(max(selected_scores))
            if subjective_groups and len(category_scores) != len(subjective_groups):
                continue
            fallback_score: float | None = None
            if not subjective_groups:
                fallback = ranked_by_code_menu.get("__fallback__", {}).get(menu_id, [])
                for score, hit in fallback:
                    fallback_score = max(fallback_score or 0.0, score)
                    mapped_concept_id = str(hit["mapped_concept_id"])
                    reference = EvidenceReference(
                        evidence_id=str(hit["chunk_id"]),
                        evidence_type=(
                            "ESSENTIAL_FACT"
                            if str(hit.get("facet") or "").casefold() == "essential_fact"
                            else "WIKI_PASSAGE"
                        ),
                        content=str(hit["content"]),
                        score=round(max(0.0, min(1.0, score)), 6),
                    )
                    passage_scores[reference.evidence_id] = (score, reference)
            if not passage_scores:
                continue
            wiki_passages = [
                item[1]
                for item in sorted(
                    passage_scores.values(),
                    key=lambda item: (-item[0], item[1].evidence_id),
                )[:passages_per_menu]
            ]
            certification = certifications.get(menu_id)
            vegan_status, vegan_warning, vegan_facts = vegan.get(
                menu_id,
                ("UNKNOWN", None, []),
            )
            menu_facts = [
                EvidenceReference(
                    evidence_id=f"fact_{menu_id}_price",
                    evidence_type="MENU_FACT",
                    content=f"Current base price: KRW {int(row['price']):,}.",
                ),
                *vegan_facts,
            ]
            menu_facts.append(
                EvidenceReference(
                    evidence_id=f"fact_{menu_id}_spice",
                    evidence_type="MENU_FACT",
                    content=(
                        f"Reviewed spice level: {int(row['spice_level'])} of 5."
                        if row["spice_level"] is not None
                        else "The source did not provide a reviewed spice level."
                    ),
                )
            )
            if certification:
                menu_facts.append(
                    EvidenceReference(
                        evidence_id=certification[0],
                        evidence_type="CERTIFICATION",
                        content=certification[1],
                    )
                )
            primary_score = (
                sum(category_scores) / len(category_scores)
                if category_scores
                else fallback_score or 0.5
            )
            soft_ranked = ranked_by_code_menu.get("__profile_soft__", {}).get(
                menu_id,
                [],
            )
            retrieval_score = apply_soft_profile_retrieval_signal(
                primary_score,
                soft_ranked[0][0] if soft_ranked else None,
            )
            risks = [vegan_warning] if criteria.dietary_filters.vegan and vegan_warning else []
            reasons = [
                f"Matches selected {category.replace('_', ' ')}" for category in subjective_groups
            ] or ["Matches the selected objective filters"]
            menu = self._menu_summary(
                row,
                reasons,
                risks,
                EvidenceStatus.VERIFIED if certification else EvidenceStatus.UNKNOWN,
                retrieval_score,
            ).model_copy(
                update={
                    "dietary_summary": (
                        "A current halal certification applies to this menu."
                        if certification
                        else "No halal certification is asserted."
                    ),
                    "risk_hints": risks,
                    "evidence_ids": [fact.evidence_id for fact in menu_facts],
                    "grounded_claim_ids": [fact.evidence_id for fact in menu_facts],
                    "grounded_passage_ids": [item.evidence_id for item in wiki_passages],
                }
            )
            pool.append(
                EvidencePoolItem(
                    menu=menu,
                    knowledge_concept_id=mapped_concept_id,
                    criterion_evidence=criterion_evidence,
                    wiki_passages=wiki_passages,
                    menu_facts=menu_facts,
                    halal_certified=bool(certification),
                    halal_scope_label=certification[1] if certification else None,
                    vegan_status=cast(Any, vegan_status),
                    vegan_warning=vegan_warning,
                    retrieval_score=round(max(0.0, min(1.0, retrieval_score)), 6),
                    knowledge_release_id=family.knowledge_release_id,
                    catalog_release_id=family.catalog_release_id,
                    recommendation_release_family_id=family.release_family_id,
                )
            )
        return sorted(
            pool,
            key=lambda item: (-item.retrieval_score, item.menu.price, item.menu.menu_id),
        )[:limit]

    @staticmethod
    def _structured_session_filters(
        connection: oracledb.Connection,
        session_id: str,
        *,
        exclude_history: bool,
    ) -> tuple[str | None, set[str]]:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT meal_need_state_json FROM chat_session WHERE session_id=:session_id",
            session_id=session_id,
        )
        session = _row(cursor)
        if session is None:
            raise KeyError("SESSION_NOT_FOUND")
        need_state = MealNeedState.model_validate(_json(session["meal_need_state_json"] or "{}"))
        cursor.execute(
            """
            SELECT address.service_area_id
            FROM cart
            JOIN address_ref address ON address.address_ref_id=cart.address_ref_id
            JOIN service_area area ON area.service_area_id=address.service_area_id
            WHERE cart.session_id=:session_id AND address.confirmed=1 AND area.active=1
            """,
            session_id=session_id,
        )
        confirmed_area = cursor.fetchone()
        service_area_id = (
            str(confirmed_area[0])
            if confirmed_area is not None and confirmed_area[0]
            else need_state.service_area_id
        )
        excluded: set[str] = set()
        if exclude_history:
            excluded.update(need_state.shown_menu_ids)
            excluded.update(need_state.rejected_menu_ids)
            if need_state.selected_menu_id:
                excluded.add(need_state.selected_menu_id)
        return service_area_id, excluded

    @staticmethod
    def _concept_support_rows(
        connection: oracledb.Connection,
        *,
        release_id: str,
        menu_ids: list[str],
        criteria: RecommendationCriteriaV2,
    ) -> list[dict[str, Any]]:
        if not menu_ids or not criteria.subjective_groups():
            return []
        binds: dict[str, Any] = {"release_id": release_id}
        menu_binds = []
        for index, menu_id in enumerate(menu_ids):
            key = f"support_menu_{index}"
            binds[key] = menu_id
            menu_binds.append(f":{key}")
        predicates = []
        selected = [
            (category, option)
            for category, options in criteria.subjective_groups().items()
            for option in options
        ]
        for index, (category, option) in enumerate(selected):
            category_key = f"support_category_{index}"
            option_key = f"support_option_{index}"
            binds[category_key] = category
            binds[option_key] = option
            predicates.append(
                f"(support.category_code=:{category_key} AND support.option_code=:{option_key})"
            )
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT feature.menu_id,feature.category_code,feature.option_code,
                   feature.support_strength,evidence.evidence_id,
                   feature.review_status,evidence.excerpt AS content,
                   evidence.source_type AS facet,feature.evidence_scope
            FROM menu_preference_feature feature
            JOIN menu_preference_feature_evidence evidence
              ON evidence.knowledge_release_id=feature.knowledge_release_id
             AND evidence.feature_id=feature.feature_id
             AND evidence.evidence_role='SUPPORT'
            WHERE feature.knowledge_release_id=:release_id
              AND feature.support_status='SUPPORTED'
              AND feature.evidence_scope='MENU_DIRECT'
              AND feature.menu_id IN ({",".join(menu_binds)})
              AND ({" OR ".join(predicates).replace("support.", "feature.")})
            UNION ALL
            SELECT membership.menu_id,support.category_code,support.option_code,
                   support.support_strength*0.65 AS support_strength,
                   support.evidence_chunk_id AS evidence_id,
                   support.review_status,
                   DBMS_LOB.SUBSTR(chunk.content,2000,1) AS content,
                   chunk.facet,
                   'CONCEPT_GENERAL' AS evidence_scope
            FROM menu_concept_membership membership
            JOIN concept_preference_support support
              ON support.knowledge_release_id=membership.knowledge_release_id
             AND support.concept_id=membership.concept_id
             AND support.support_status='SUPPORTED'
            JOIN knowledge_chunk chunk
              ON chunk.release_id=support.knowledge_release_id
             AND chunk.chunk_id=support.evidence_chunk_id
            WHERE membership.knowledge_release_id=:release_id
              AND membership.menu_id IN ({",".join(menu_binds)})
              AND ({" OR ".join(predicates)})
              AND NOT EXISTS (
                SELECT 1 FROM menu_preference_feature contradiction
                WHERE contradiction.knowledge_release_id=membership.knowledge_release_id
                  AND contradiction.menu_id=membership.menu_id
                  AND contradiction.category_code=support.category_code
                  AND contradiction.option_code=support.option_code
                  AND contradiction.support_status='CONTRADICTED'
                  AND contradiction.evidence_scope='MENU_DIRECT'
              )
            ORDER BY menu_id,category_code,support_strength DESC,option_code,evidence_id
            """,
            binds,
        )
        return _rows(cursor)

    @staticmethod
    def _final_concept_wiki_rows(
        connection: oracledb.Connection,
        *,
        release_id: str,
        menu_ids: list[str],
        criteria: RecommendationCriteriaV2,
        preferred_evidence_ids_by_menu: dict[str, set[str]],
        passages_per_menu: int,
    ) -> dict[str, list[dict[str, Any]]]:
        if not menu_ids:
            return {}
        binds: dict[str, Any] = {"release_id": release_id}
        menu_binds = []
        for index, menu_id in enumerate(menu_ids):
            key = f"wiki_menu_{index}"
            binds[key] = menu_id
            menu_binds.append(f":{key}")
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT membership.menu_id,chunk.chunk_id,chunk.content,chunk.facet,
                   closure.depth,chunk.chunk_index
              FROM menu_concept_membership membership
              JOIN dish_concept_closure closure
                ON closure.release_id=membership.knowledge_release_id
               AND closure.descendant_concept_id=membership.concept_id
               AND closure.inherit_claims=1
              JOIN knowledge_chunk chunk
                ON chunk.release_id=closure.release_id
               AND chunk.concept_id=closure.ancestor_concept_id
              JOIN knowledge_document document
                ON document.release_id=chunk.release_id
               AND document.document_id=chunk.document_id
              WHERE membership.knowledge_release_id=:release_id
                AND membership.menu_id IN ({",".join(menu_binds)})
                AND document.source_type='SYNTHETIC_WIKI'
                AND document.review_status='REVIEWED_DEMO'
                AND lower(chunk.facet)<>'safety'
                AND (
                  JSON_VALUE(chunk.metadata_json,'$.recommendation_visibility')='PUBLIC_RAG'
                  OR JSON_VALUE(chunk.metadata_json,'$.recommendation_visibility') IS NULL
                )
            ORDER BY membership.menu_id,closure.depth,chunk.chunk_index,chunk.chunk_id
            """,
            binds,
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in _rows(cursor):
            grouped[str(row["menu_id"])].append(row)
        return {
            menu_id: rank_wiki_passages(
                rows,
                selected_groups=criteria.subjective_groups(),
                preferred_evidence_ids=preferred_evidence_ids_by_menu.get(menu_id, set()),
                limit=passages_per_menu,
            )
            for menu_id, rows in grouped.items()
        }

    def _build_concept_ranked_pool(
        self,
        connection: oracledb.Connection,
        *,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        profile: Profile,
        mode: RecommendationMode,
        limit: int,
        family: RecommendationReleaseFamily,
        eligibility_as_of: datetime,
        passages_per_menu: int,
    ) -> list[EvidencePoolItem]:
        pipeline_started = monotonic()
        query_count = 0
        session_filter_started = monotonic()
        service_area_id, excluded = self._structured_session_filters(
            connection,
            session_id,
            exclude_history=mode in {RecommendationMode.SIMILAR, RecommendationMode.RETRY},
        )
        query_count += 2
        session_filter_ms = int((monotonic() - session_filter_started) * 1000)
        channel_limit = max(3, limit)
        query_text = (
            " ".join(
                alias
                for selected_codes in criteria.subjective_groups().values()
                for code in selected_codes
                # Structured preference codes are language-neutral.  Use one
                # canonical bilingual alias pack so an otherwise identical Korean
                # and English request has the same semantic retrieval channel.
                for alias in preference_query_aliases(code, "English")
            )
            or "meal menu"
        )
        semantic_channel_active = bool(
            family.embedding_model == self.embedding_provider.model
            and family.embedding_version == self.embedding_provider.version
        )
        semantic_channel_status = "ACTIVE" if semantic_channel_active else "DISABLED_MODEL_MISMATCH"
        query_vector = (
            array("f", self.embedding_provider.embed([query_text], "SEARCH_QUERY")[0])
            if semantic_channel_active
            else None
        )
        objective_started = monotonic()
        cursor = connection.cursor()
        if criteria.subjective_groups():
            feature_query = build_candidate_recall_channel_query(
                dialect="oracle",
                criteria=criteria,
                knowledge_release_id=family.knowledge_release_id,
                certification_release_id=family.certification_release_id,
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of,
                candidate_limit=channel_limit,
                support_channel="MENU_FEATURE",
                synthetic_enrichment_release_id=family.synthetic_enrichment_release_id,
            )
            cursor.execute(feature_query.sql, feature_query.parameters)
            feature_rows = _rows(cursor)
            concept_query = build_candidate_recall_channel_query(
                dialect="oracle",
                criteria=criteria,
                knowledge_release_id=family.knowledge_release_id,
                certification_release_id=family.certification_release_id,
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of,
                candidate_limit=channel_limit,
                support_channel="CONCEPT_SUPPORT",
                synthetic_enrichment_release_id=family.synthetic_enrichment_release_id,
            )
            cursor.execute(concept_query.sql, concept_query.parameters)
            concept_rows = _rows(cursor)
            query_count += 2
        else:
            feature_rows = []
            concept_query = build_candidate_recall_channel_query(
                dialect="oracle",
                criteria=criteria,
                knowledge_release_id=family.knowledge_release_id,
                certification_release_id=family.certification_release_id,
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of,
                candidate_limit=channel_limit,
                support_channel="CONCEPT_SUPPORT",
                synthetic_enrichment_release_id=family.synthetic_enrichment_release_id,
            )
            cursor.execute(concept_query.sql, concept_query.parameters)
            concept_rows = _rows(cursor)
            query_count += 1
        if semantic_channel_active:
            semantic_query = build_semantic_candidate_query(
                dialect="oracle",
                criteria=criteria,
                knowledge_release_id=family.knowledge_release_id,
                certification_release_id=family.certification_release_id,
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of,
                candidate_limit=channel_limit,
                query_vector=query_vector,
                semantic_embedding_model=family.embedding_model,
                semantic_embedding_version=family.embedding_version,
                semantic_embedding_dimension=self.embedding_provider.dimension,
                catalog_release_id=family.catalog_release_id,
                synthetic_enrichment_release_id=family.synthetic_enrichment_release_id,
            )
            cursor.execute(semantic_query.sql, semantic_query.parameters)
            semantic_rows = _rows(cursor)
        else:
            semantic_rows = []
        feature_channel_ids = [str(row["menu_id"]) for row in feature_rows]
        concept_channel_ids = [str(row["menu_id"]) for row in concept_rows]
        semantic_channel_ids = [str(row["menu_id"]) for row in semantic_rows]
        named_channels = {
            "MENU_FEATURE": feature_channel_ids,
            "CONCEPT_SUPPORT": concept_channel_ids,
            "SEMANTIC": semantic_channel_ids,
        }
        channel_fusion_by_menu = candidate_channel_fusion_trace(named_channels)
        raw_channel_union_count = len(
            set(feature_channel_ids) | set(concept_channel_ids) | set(semantic_channel_ids)
        )
        channel_union_ids = merge_candidate_channels(
            list(named_channels.values()),
            limit=channel_limit,
        )
        candidate_rows: list[dict[str, Any]] = []
        if channel_union_ids:
            grounded_query = build_concept_candidate_query(
                dialect="oracle",
                criteria=criteria,
                knowledge_release_id=family.knowledge_release_id,
                certification_release_id=family.certification_release_id,
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of,
                candidate_limit=None,
                included_menu_ids=channel_union_ids,
                synthetic_enrichment_release_id=family.synthetic_enrichment_release_id,
            )
            cursor.execute(grounded_query.sql, grounded_query.parameters)
            candidate_rows = _rows(cursor)
        query_count += int(semantic_channel_active) + int(bool(channel_union_ids))
        objective_sql_ms = int((monotonic() - objective_started) * 1000)
        if not candidate_rows:
            self._recommendation_retrieval_metrics[session_id] = {
                "session_filter_ms": session_filter_ms,
                "objective_sql_ms": objective_sql_ms,
                "support_lookup_ms": 0,
                "scoring_rerank_ms": 0,
                "evidence_ms": 0,
                "query_count": query_count,
                "selected_category_count": len(criteria.subjective_groups()),
                "explicit_channel_count": len(set(feature_channel_ids) | set(concept_channel_ids)),
                "menu_feature_channel_count": len(feature_channel_ids),
                "concept_support_channel_count": len(concept_channel_ids),
                "semantic_channel_count": len(semantic_channel_ids),
                "semantic_channel_status": semantic_channel_status,
                "raw_channel_union_count": raw_channel_union_count,
                "channel_union_count": len(channel_union_ids),
                "fetched_candidate_count": 0,
                "candidate_merchant_count": 0,
                "candidate_concept_count": 0,
                "support_row_count": 0,
                "wiki_row_count": 0,
                "pipeline_ms": int((monotonic() - pipeline_started) * 1000),
            }
            return []
        candidate_by_id = {str(row["menu_id"]): row for row in candidate_rows}
        support_started = monotonic()
        support_rows = self._concept_support_rows(
            connection,
            release_id=family.knowledge_release_id,
            menu_ids=list(candidate_by_id),
            criteria=criteria,
        )
        if criteria.subjective_groups():
            query_count += 1
        support_lookup_ms = int((monotonic() - support_started) * 1000)
        supports_by_menu: dict[str, dict[str, tuple[float, dict[str, Any]]]] = defaultdict(dict)
        for support in support_rows:
            menu_id = str(support["menu_id"])
            category = str(support["category_code"])
            current = supports_by_menu[menu_id].get(category)
            strength = float(support["support_strength"])
            if current is None or strength > current[0]:
                supports_by_menu[menu_id][category] = (strength, support)
        signal_binds: dict[str, Any] = {}
        signal_menu_binds: list[str] = []
        for index, menu_id in enumerate(sorted(candidate_by_id)):
            key = f"signal_menu_{index}"
            signal_binds[key] = menu_id
            signal_menu_binds.append(f":{key}")
        if semantic_channel_active:
            signal_binds.update(
                {
                    "query_vector": query_vector,
                    "semantic_embedding_model": family.embedding_model,
                    "semantic_embedding_version": family.embedding_version,
                    "semantic_embedding_dimension": self.embedding_provider.dimension,
                    "semantic_catalog_release_id": family.catalog_release_id,
                }
            )
            semantic_signal_projection = """
              CASE WHEN semantic_embedding.embedding_vector IS NULL
                   THEN 0
                   ELSE 1-VECTOR_DISTANCE(
                     semantic_embedding.embedding_vector,:query_vector,COSINE
                   )
              END AS semantic_score
            """
            semantic_signal_join = """
              LEFT JOIN menu_semantic_embedding semantic_embedding
                ON semantic_embedding.menu_id=menu.menu_id
               AND semantic_embedding.catalog_release_id=:semantic_catalog_release_id
               AND semantic_embedding.embedding_model=:semantic_embedding_model
               AND semantic_embedding.embedding_version=:semantic_embedding_version
               AND semantic_embedding.embedding_dimension=:semantic_embedding_dimension
            """
        else:
            semantic_signal_projection = "0 AS semantic_score"
            semantic_signal_join = ""
        signal_cursor = connection.cursor()
        signal_cursor.execute(
            f"""
            SELECT menu.menu_id,
                   {semantic_signal_projection},
                   COALESCE(menu_source.review_count,merchant_source.review_count,0)
                     AS review_count,
                   merchant_source.review_average
            FROM menu
            {semantic_signal_join}
            LEFT JOIN menu_source_detail menu_source ON menu_source.menu_id=menu.menu_id
            LEFT JOIN merchant_source_detail merchant_source
              ON merchant_source.merchant_id=menu.merchant_id
            WHERE menu.menu_id IN ({",".join(signal_menu_binds)})
            ORDER BY menu.menu_id
            """,
            signal_binds,
        )
        signals_by_menu = {
            str(row["menu_id"]): (
                max(0.0, min(1.0, float(row["semantic_score"] or 0.0))),
                bayesian_review_prior(
                    int(row["review_count"] or 0),
                    float(row["review_average"]) if row.get("review_average") is not None else None,
                ),
            )
            for row in _rows(signal_cursor)
        }
        rank_inputs = []
        for row in candidate_rows:
            menu_id = str(row["menu_id"])
            category_supports = {
                category: strength
                for category, (strength, _support) in supports_by_menu.get(menu_id, {}).items()
            }
            if not category_supports:
                category_supports = {"__objective__": 1.0}
            semantic_score, review_prior = signals_by_menu.get(menu_id, (0.0, 0.5))
            rank_inputs.append(
                ConceptRankCandidate(
                    menu_id=menu_id,
                    merchant_id=str(row["merchant_id"]),
                    concept_id=str(row["concept_id"]),
                    category_supports=category_supports,
                    reviewed_evidence_count=int(row["reviewed_evidence_count"]),
                    semantic_score=semantic_score,
                    direct_evidence_ratio=float(row["direct_evidence_ratio"]),
                    review_prior=review_prior,
                )
            )
        scoring_started = monotonic()
        decisions = rank_concept_candidates(
            rank_inputs,
            has_soft_profile=False,
            limit=limit,
        )
        scoring_rerank_ms = int((monotonic() - scoring_started) * 1000)
        evidence_started = monotonic()
        wiki_by_menu = self._final_concept_wiki_rows(
            connection,
            release_id=family.knowledge_release_id,
            menu_ids=[decision.menu_id for decision in decisions],
            criteria=criteria,
            preferred_evidence_ids_by_menu={
                menu_id: {
                    str(support["evidence_id"])
                    for _category, (_strength, support) in supports.items()
                    if str(support["evidence_scope"]) == "CONCEPT_GENERAL"
                }
                for menu_id, supports in supports_by_menu.items()
            },
            passages_per_menu=passages_per_menu,
        )
        if decisions:
            query_count += 1
        synthetic_by_menu: dict[str, dict[str, Any]] = {}
        synthetic_reviews_by_menu: dict[str, list[dict[str, Any]]] = defaultdict(list)
        country_code = profile.country_code or criteria.spice_reference_country
        requested_locale = normalize_preference_locale(profile.preferred_language)
        presentation_locale = requested_locale if requested_locale in {"ko", "ja"} else "en"
        if decisions and family.synthetic_enrichment_release_id:
            synthetic_binds: dict[str, Any] = {
                "synthetic_release_id": family.synthetic_enrichment_release_id,
                "presentation_locale": presentation_locale,
                "country_code": country_code,
            }
            selected_binds: list[str] = []
            for index, decision in enumerate(decisions):
                key = f"synthetic_menu_{index}"
                synthetic_binds[key] = decision.menu_id
                selected_binds.append(f":{key}")
            synthetic_cursor = connection.cursor()
            synthetic_cursor.execute(
                f"""
                SELECT profile.menu_id,profile.spice_level,profile.halal_fit,
                       profile.vegan_fit,localization.display_name,
                       preference.preference_percent,preference.sample_size,
                       country.spice_baseline
                FROM synthetic_menu_profile profile
                JOIN synthetic_country_profile country
                  ON country.release_id=profile.release_id
                 AND country.country_code=:country_code
                LEFT JOIN menu_localization localization
                  ON localization.release_id=profile.release_id
                 AND localization.menu_id=profile.menu_id
                 AND localization.language_code=:presentation_locale
                 AND localization.validation_status='VALID'
                LEFT JOIN synthetic_menu_country_preference preference
                  ON preference.release_id=profile.release_id
                 AND preference.menu_id=profile.menu_id
                 AND preference.country_code=:country_code
                WHERE profile.release_id=:synthetic_release_id
                  AND profile.menu_id IN ({','.join(selected_binds)})
                """,
                synthetic_binds,
            )
            synthetic_by_menu = {
                str(item["menu_id"]): item for item in _rows(synthetic_cursor)
            }
            synthetic_cursor.execute(
                f"""
                SELECT review_id,menu_id,topic,rating,review_text,display_order
                FROM synthetic_review_snippet
                WHERE release_id=:synthetic_release_id
                  AND menu_id IN ({','.join(selected_binds)})
                ORDER BY menu_id,display_order,review_id
                """,
                synthetic_binds,
            )
            for review in _rows(synthetic_cursor):
                synthetic_reviews_by_menu[str(review["menu_id"])].append(
                    {
                        "review_id": str(review["review_id"]),
                        "topic": str(review["topic"]),
                        "rating": int(review["rating"]),
                        "review_text": str(review["review_text"]),
                    }
                )
            query_count += 2
        pool: list[EvidencePoolItem] = []
        for decision in decisions:
            row = candidate_by_id[decision.menu_id]
            synthetic = synthetic_by_menu.get(decision.menu_id)
            wiki_passages = [
                EvidenceReference(
                    evidence_id=str(chunk["chunk_id"]),
                    evidence_type="WIKI_PASSAGE",
                    content=str(chunk["content"]),
                )
                for chunk in wiki_by_menu.get(decision.menu_id, [])
            ]
            if not wiki_passages and not criteria.subjective_groups():
                continue
            criterion_evidence = []
            direct_feature_facts: list[EvidenceReference] = []
            for category, (_strength, support) in sorted(
                supports_by_menu.get(decision.menu_id, {}).items()
            ):
                reference = EvidenceReference(
                    evidence_id=str(support["evidence_id"]),
                    evidence_type=(
                        "MENU_FACT"
                        if str(support["evidence_scope"]) == "MENU_DIRECT"
                        else "WIKI_PASSAGE"
                    ),
                    content=str(support["content"]),
                    score=round(float(support["support_strength"]), 6),
                )
                criterion_evidence.append(
                    CriterionEvidence(
                        category_code=cast(Any, category),
                        selected_value_code=str(support["option_code"]),
                        evidence=[reference],
                    )
                )
                if reference.evidence_type == "MENU_FACT":
                    direct_feature_facts.append(reference)
            facts = [
                EvidenceReference(
                    evidence_id=f"fact_{decision.menu_id}_price",
                    evidence_type="MENU_FACT",
                    content=f"Current base price: KRW {int(row['price']):,}.",
                ),
                EvidenceReference(
                    evidence_id=f"fact_{decision.menu_id}_spice",
                    evidence_type="MENU_FACT",
                    content=(
                        f"Internal spice level: {int(synthetic['spice_level'])} of 5."
                        if synthetic is not None
                        else f"Reviewed spice level: {int(row['spice_level'])} of 5."
                        if row.get("spice_level") is not None
                        else "The source did not provide a reviewed spice level."
                    ),
                ),
                *direct_feature_facts,
            ]
            channel_fusion = channel_fusion_by_menu.get(
                decision.menu_id,
                {"channel_ranks": {}, "rrf_contributions": {}, "rrf_score": 0.0},
            )
            retrieval_channels = [
                channel for channel in named_channels if channel in channel_fusion["channel_ranks"]
            ]
            trace = {
                **decision.trace_payload(),
                "qualified_candidate_count": len(candidate_rows),
                "support_manifest_sha256": family.support_manifest_sha256,
                "feature_manifest_sha256": family.feature_manifest_sha256,
                "semantic_channel_status": semantic_channel_status,
                "retrieval_channels": retrieval_channels,
                "channel_fusion": channel_fusion,
                "channel_candidate_counts": {
                    "menu_feature": len(feature_channel_ids),
                    "concept_support": len(concept_channel_ids),
                    "semantic": len(semantic_channel_ids),
                    "raw_union": raw_channel_union_count,
                    "bounded_union_before_grounding": len(channel_union_ids),
                },
            }
            menu = self._menu_summary(
                row,
                [
                    f"Matches selected {item.category_code.replace('_', ' ')}"
                    for item in criterion_evidence
                ]
                or ["Matches the selected objective filters"],
                [],
                EvidenceStatus.UNKNOWN,
                decision.score,
            ).model_copy(
                update={
                    "evidence_ids": [fact.evidence_id for fact in facts],
                    "grounded_claim_ids": [fact.evidence_id for fact in facts],
                    "grounded_passage_ids": [passage.evidence_id for passage in wiki_passages],
                }
            )
            pool.append(
                EvidencePoolItem(
                    menu=menu,
                    knowledge_concept_id=decision.concept_id,
                    criterion_evidence=criterion_evidence,
                    wiki_passages=wiki_passages,
                    menu_facts=facts,
                    halal_certified=(
                        bool(synthetic["halal_fit"])
                        if synthetic is not None
                        else True if criteria.dietary_filters.halal_certified_only else None
                    ),
                    vegan_status=(
                        "LIKELY_FIT"
                        if synthetic is not None and bool(synthetic["vegan_fit"])
                        else "UNKNOWN"
                    ),
                    localized_title=(
                        str(synthetic["display_name"])
                        if synthetic is not None and synthetic.get("display_name")
                        else menu.name_ko if presentation_locale == "ko" else menu.name_en
                    ),
                    synthetic_spice_level=(
                        int(synthetic["spice_level"]) if synthetic is not None else None
                    ),
                    country_spice_baseline=(
                        int(synthetic["spice_baseline"]) if synthetic is not None else None
                    ),
                    country_preference=(
                        {
                            "country_code": country_code,
                            "preference_percent": int(synthetic["preference_percent"]),
                            "sample_size": int(synthetic["sample_size"]),
                        }
                        if synthetic is not None
                        and synthetic.get("preference_percent") is not None
                        else None
                    ),
                    synthetic_reviews=synthetic_reviews_by_menu.get(decision.menu_id, []),
                    retrieval_score=decision.score,
                    server_rank=decision.rank,
                    explicit_score=decision.explicit_score,
                    semantic_score=decision.semantic_score,
                    min_category_support=decision.min_category_support,
                    reviewed_evidence_count=decision.reviewed_evidence_count,
                    ranking_trace=trace,
                    knowledge_release_id=family.knowledge_release_id,
                    catalog_release_id=family.catalog_release_id,
                    recommendation_release_family_id=family.release_family_id,
                )
            )
        evidence_ms = int((monotonic() - evidence_started) * 1000)
        self._recommendation_retrieval_metrics[session_id] = {
            "session_filter_ms": session_filter_ms,
            "objective_sql_ms": objective_sql_ms,
            "support_lookup_ms": support_lookup_ms,
            "scoring_rerank_ms": scoring_rerank_ms,
            "evidence_ms": evidence_ms,
            "query_count": query_count,
            "selected_category_count": len(criteria.subjective_groups()),
            "explicit_channel_count": len(set(feature_channel_ids) | set(concept_channel_ids)),
            "menu_feature_channel_count": len(feature_channel_ids),
            "concept_support_channel_count": len(concept_channel_ids),
            "semantic_channel_count": len(semantic_channel_ids),
            "semantic_channel_status": semantic_channel_status,
            "raw_channel_union_count": raw_channel_union_count,
            "channel_union_count": len(channel_union_ids),
            "fetched_candidate_count": len(candidate_rows),
            "candidate_merchant_count": len({str(row["merchant_id"]) for row in candidate_rows}),
            "candidate_concept_count": len({str(row["concept_id"]) for row in candidate_rows}),
            "support_row_count": len(support_rows),
            "wiki_row_count": sum(len(rows) for rows in wiki_by_menu.values()),
            "pipeline_ms": int((monotonic() - pipeline_started) * 1000),
        }
        return pool

    def preview_recommendation(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        *,
        release_family_id: str | None = None,
        exclude_history: bool = False,
    ) -> RecommendationPreviewV2:
        started = monotonic()
        with self.pool.connection() as connection:
            family = (
                self._recommendation_release_family_in_connection(connection, release_family_id)
                if release_family_id is not None
                else None
            )
            if family is None and release_family_id is None:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    SELECT family.* FROM recommendation_runtime_state state
                    JOIN recommendation_release_family family
                      ON family.release_family_id=state.active_release_family_id
                    WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                    """
                )
                row = _row(cursor)
                if row is not None:
                    family = RecommendationReleaseFamily(
                        release_family_id=str(row["release_family_id"]),
                        knowledge_release_id=str(row["knowledge_release_id"]),
                        catalog_release_id=str(row["catalog_release_id"]),
                        preference_catalog_version=str(row["preference_catalog_version"]),
                        spice_reference_version=str(row["spice_reference_version"]),
                        certification_release_id=str(row["certification_release_id"]),
                        embedding_model=str(row["embedding_model"]),
                        embedding_version=str(row["embedding_version"]),
                        support_manifest_sha256=str(row.get("support_manifest_sha256") or "0" * 64),
                        feature_manifest_sha256=str(row.get("feature_manifest_sha256") or "0" * 64),
                        ranking_policy_version=str(
                            row.get("ranking_policy_version") or "legacy-llm-rank-v2"
                        ),
                        ranking_policy_sha256=str(row.get("ranking_policy_sha256") or "0" * 64),
                        synthetic_enrichment_release_id=(
                            str(row["synthetic_enrichment_release_id"])
                            if row.get("synthetic_enrichment_release_id")
                            else None
                        ),
                        status=cast(Any, str(row["status"])),
                        activated_at=_datetime(row["activated_at"])
                        if row.get("activated_at")
                        else None,
                    )
            if family is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
            cursor = connection.cursor()
            unsupported_reasons: list[str] = []
            if criteria.schema_version == "3" and not family.synthetic_enrichment_release_id:
                unsupported_reasons.append("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            if criteria.schema_version == "2" and criteria.dietary_filters.halal_certified_only:
                halal_menus = len(
                    self._valid_halal_certifications_in_connection(
                        connection,
                        certification_release_id=family.certification_release_id,
                        instant=_now(),
                    )
                )
                if halal_menus < 3:
                    unsupported_reasons.append("HALAL_CERTIFICATION_UNAVAILABLE")
            if criteria.schema_version == "2" and criteria.dietary_filters.vegan:
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT menu.menu_id),
                           COUNT(DISTINCT menu.merchant_id)
                    FROM menu_concept_map mapping
                    JOIN menu ON menu.menu_id=mapping.menu_id
                      AND menu.availability='AVAILABLE'
                    JOIN menu_dietary_attribute relation
                      ON relation.menu_id=menu.menu_id
                     AND upper(relation.status)='VERIFIED'
                    JOIN dietary_attribute attribute
                      ON attribute.attribute_id=relation.attribute_id
                     AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                    WHERE mapping.release_id=:release_id
                      AND mapping.mapping_status='MAPPED'
                      AND mapping.confidence_band='high'
                    """,
                    release_id=family.knowledge_release_id,
                )
                vegan_capability = cursor.fetchone()
                if not (
                    vegan_capability
                    and int(vegan_capability[0] or 0) >= 3
                    and int(vegan_capability[1] or 0) >= 2
                ):
                    unsupported_reasons.append("VEGAN_EVIDENCE_UNAVAILABLE")
            if criteria.schema_version == "2" and criteria.max_spice_level < 5:
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT menu.menu_id),
                           COUNT(DISTINCT menu.merchant_id)
                    FROM menu_concept_map mapping
                    JOIN menu ON menu.menu_id=mapping.menu_id
                      AND menu.availability='AVAILABLE'
                    WHERE mapping.release_id=:release_id
                      AND mapping.mapping_status='MAPPED'
                      AND mapping.confidence_band='high'
                      AND menu.spice_status IN ('REVIEWED','VERIFIED')
                      AND menu.spice_level IS NOT NULL
                    """,
                    release_id=family.knowledge_release_id,
                )
                spice_capability = cursor.fetchone()
                if not (
                    spice_capability
                    and int(spice_capability[0] or 0) >= 3
                    and int(spice_capability[1] or 0) >= 2
                ):
                    unsupported_reasons.append("SPICE_LEVEL_UNAVAILABLE")
            service_area_id, excluded = self._structured_session_filters(
                connection, session_id, exclude_history=exclude_history
            )
            if unsupported_reasons:
                menu_count = 0
                merchant_count = 0
                reasons = unsupported_reasons
            else:
                preview_query = build_concept_preview_count_query(
                    dialect="oracle",
                    criteria=criteria,
                    knowledge_release_id=family.knowledge_release_id,
                    certification_release_id=family.certification_release_id,
                    service_area_id=service_area_id,
                    excluded_menu_ids=excluded,
                    eligibility_as_of=_now(),
                    synthetic_enrichment_release_id=family.synthetic_enrichment_release_id,
                )
                cursor.execute(preview_query.sql, preview_query.parameters)
                row = cursor.fetchone()
                menu_count = int(row[0]) if row else 0
                merchant_count = int(row[1]) if row else 0
                reasons = ["NO_SUPPORTED_CONCEPT_COMBINATION"] if menu_count == 0 else []
        return RecommendationPreviewV2(
            eligible_menu_count=menu_count,
            eligible_merchant_count=merchant_count,
            zero_reason_codes=reasons,
            release_id=family.release_family_id,
            support_manifest_sha256=family.support_manifest_sha256,
            ranking_policy_version=family.ranking_policy_version,
            timing_ms=max(0, int((monotonic() - started) * 1000)),
        )

    def apply_conversation_event(
        self, session_id: str, event: ConversationEventInput
    ) -> ConversationEventResult:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT payload_json,result_json FROM conversation_event
                WHERE session_id=:session_id AND idempotency_key=:idempotency_key
                """,
                session_id=session_id,
                idempotency_key=event.idempotency_key,
            )
            duplicate = cursor.fetchone()
            if duplicate:
                if _json(duplicate[0]) != event.model_dump(mode="json"):
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                previous = ConversationEventResult.model_validate_json(_value(duplicate[1]))
                return previous.model_copy(update={"duplicate": True})

            cursor.execute(
                "SELECT * FROM chat_session WHERE session_id=:session_id FOR UPDATE",
                session_id=session_id,
            )
            session_row = _row(cursor)
            if session_row is None:
                raise KeyError("SESSION_NOT_FOUND")
            # A transaction with the same key may have committed while this request
            # waited for the session row lock. Recheck inside the serialised region.
            cursor.execute(
                """
                SELECT payload_json,result_json FROM conversation_event
                WHERE session_id=:session_id AND idempotency_key=:idempotency_key
                """,
                session_id=session_id,
                idempotency_key=event.idempotency_key,
            )
            duplicate = cursor.fetchone()
            if duplicate:
                if _json(duplicate[0]) != event.model_dump(mode="json"):
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                previous = ConversationEventResult.model_validate_json(_value(duplicate[1]))
                return previous.model_copy(update={"duplicate": True})
            version = int(session_row.get("state_version") or 0)
            if event.expected_state_version is not None and event.expected_state_version != version:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            need_state = MealNeedState.model_validate(
                _json(session_row.get("meal_need_state_json") or "{}")
            )
            cursor.execute(
                """
                SELECT dietary_rules_json,allergy_severity,religion_selection
                FROM user_profile WHERE profile_id=:profile_id
                """,
                profile_id=session_row["profile_id"],
            )
            profile_row = _row(cursor)
            if profile_row is None:
                raise KeyError("PROFILE_NOT_FOUND")
            cursor.execute(
                """
                SELECT ref.service_area_id
                FROM cart JOIN address_ref ref ON ref.address_ref_id=cart.address_ref_id
                JOIN service_area area ON area.service_area_id=ref.service_area_id
                WHERE cart.session_id=:session_id AND ref.confirmed=1 AND area.active=1
                """,
                session_id=session_id,
            )
            current_area = cursor.fetchone()
            if current_area and current_area[0]:
                need_state.service_area_id = str(current_area[0])
            snapshot: RecommendationSnapshot | None = None
            structured_criteria: RecommendationCriteriaV2 | None = None
            structured_family: RecommendationReleaseFamily | None = None
            if event.snapshot_id:
                cursor.execute(
                    """
                    SELECT * FROM recommendation_snapshot
                    WHERE session_id=:session_id AND snapshot_id=:snapshot_id
                    """,
                    session_id=session_id,
                    snapshot_id=event.snapshot_id,
                )
                snapshot_row = _row(cursor)
                if snapshot_row is None:
                    raise ValueError("RECOMMENDATION_SNAPSHOT_NOT_FOUND")
                if snapshot_row.get("structured_request_id") and snapshot_row.get("criteria_json"):
                    structured_criteria = RecommendationCriteriaV2.model_validate(
                        _json(snapshot_row["criteria_json"])
                    )
                    structured_family = self._recommendation_release_family_in_connection(
                        connection,
                        str(snapshot_row["recommendation_release_family_id"]),
                    )
                    if structured_family is None:
                        raise RuntimeError("RECOMMENDATION_RELEASE_NOT_FOUND")
                snapshot = RecommendationSnapshot.model_validate(
                    {
                        "snapshot_id": snapshot_row["snapshot_id"],
                        "session_id": snapshot_row["session_id"],
                        "assistant_message_id": snapshot_row["assistant_message_id"],
                        "state_version": snapshot_row["state_version"],
                        "meal_need_state": _json(snapshot_row["meal_need_state_json"]),
                        "result": _json(snapshot_row["result_json"]),
                        "cards": _json(snapshot_row["cards_json"]),
                        "created_at": snapshot_row["created_at"],
                    }
                )
            if structured_criteria is None:
                need_state = apply_profile_constraints(
                    need_state,
                    list(_json(profile_row["dietary_rules_json"])),
                    str(profile_row["religion_selection"]),
                )
            candidate_by_id = {
                candidate.menu_id: candidate
                for candidate in (snapshot.result.candidates if snapshot else [])
            }
            selected_menu_id = session_row.get("selected_menu_id")
            selected_merchant_id = session_row.get("selected_merchant_id")
            selected_menu: dict[str, Any] | None = None
            chat_state = str(session_row["state"])
            dialogue_act = DialogueAct(
                session_row.get("dialogue_act") or DialogueAct.COLLECT_NEEDS.value
            )

            if event.event_type == ConversationEventType.SELECT_MENU:
                if event.menu_id not in candidate_by_id:
                    raise ValueError("MENU_NOT_IN_RECOMMENDATION_SNAPSHOT")
                candidate = candidate_by_id[event.menu_id]
                if structured_criteria is not None and structured_family is not None:
                    eligible_rows, _, _ = self._structured_objective_candidates(
                        connection,
                        session_id,
                        structured_criteria,
                        structured_family,
                        exclude_history=False,
                        instant=_now(),
                        menu_ids=[candidate.menu_id],
                        enforce_price_bands=False,
                    )
                    live_menu = eligible_rows[0] if eligible_rows else None
                    conflicts: list[str] = [] if live_menu is not None else ["v2:ineligible"]
                    live_merchant_id = (
                        str(live_menu["merchant_id"]) if live_menu is not None else None
                    )
                else:
                    conflicts, _ = self._menu_hard_constraint_conflicts(
                        connection,
                        candidate.menu_id,
                        need_state,
                        str(profile_row["allergy_severity"]),
                    )
                    cursor.execute(
                        "SELECT merchant_id FROM menu WHERE menu_id=:menu_id",
                        menu_id=candidate.menu_id,
                    )
                    live_menu_row = cursor.fetchone()
                    live_menu = live_menu_row
                    live_merchant_id = str(live_menu_row[0]) if live_menu_row is not None else None
                if conflicts or live_menu is None or live_merchant_id != candidate.merchant_id:
                    raise ValueError("MENU_NO_LONGER_ELIGIBLE")
                selected_menu_id = candidate.menu_id
                selected_merchant_id = candidate.merchant_id
                need_state.selected_menu_id = candidate.menu_id
                selected_menu = (
                    _find_menu_projection(snapshot.cards, candidate.menu_id) if snapshot else None
                )
                dialogue_act = DialogueAct.SELECT
                chat_state = ChatState.MENU_SELECTION.value
            elif event.event_type == ConversationEventType.REJECT_MENU:
                if event.menu_id not in candidate_by_id:
                    raise ValueError("MENU_NOT_IN_RECOMMENDATION_SNAPSHOT")
                if event.menu_id not in need_state.rejected_menu_ids:
                    need_state.rejected_menu_ids.append(event.menu_id)
                if selected_menu_id == event.menu_id:
                    selected_menu_id = None
                    selected_merchant_id = None
                    need_state.selected_menu_id = None
                dialogue_act = DialogueAct.REJECT
                chat_state = ChatState.DISCOVERY.value
            elif event.event_type == ConversationEventType.COMPARE_MENUS:
                if any(menu_id not in candidate_by_id for menu_id in set(event.menu_ids)):
                    raise ValueError("MENU_NOT_IN_RECOMMENDATION_SNAPSHOT")
                need_state.compared_menu_ids = list(dict.fromkeys(event.menu_ids))
                dialogue_act = DialogueAct.COMPARE
                chat_state = ChatState.MERCHANT_COMPARISON.value
            elif event.event_type == ConversationEventType.UPDATE_OPTIONS:
                if event.menu_id != selected_menu_id:
                    raise ValueError("OPTIONS_REQUIRE_SELECTED_MENU")
                cursor.execute(
                    """
                    SELECT option_group_id,min_select,max_select FROM menu_option_group
                    WHERE option_group_id=:group_id AND menu_id=:menu_id
                    """,
                    group_id=event.option_group_id,
                    menu_id=event.menu_id,
                )
                group = cursor.fetchone()
                if group is None:
                    raise ValueError("OPTION_GROUP_NOT_FOUND")
                selected_option_ids = list(dict.fromkeys(event.option_item_ids))
                if not int(group[1]) <= len(selected_option_ids) <= int(group[2]):
                    raise ValueError("OPTION_SELECTION_CARDINALITY_INVALID")
                cursor.execute(
                    """
                    SELECT option_item_id FROM menu_option_item
                    WHERE option_group_id=:group_id AND availability='AVAILABLE'
                    """,
                    group_id=event.option_group_id,
                )
                available_items = {str(row[0]) for row in cursor.fetchall()}
                if not set(selected_option_ids).issubset(available_items):
                    raise ValueError("OPTION_ITEM_NOT_AVAILABLE")
                need_state.option_selections[event.option_group_id or ""] = selected_option_ids
                if event.risk_acknowledged and event.option_group_id:
                    if event.option_group_id not in need_state.option_risk_acknowledged:
                        need_state.option_risk_acknowledged.append(event.option_group_id)
                dialogue_act = DialogueAct.ORDER_ACTION
                chat_state = ChatState.MENU_OPTIONS.value

            next_version = version + 1
            cursor.execute(
                """
                UPDATE chat_session SET state=:state, selected_menu_id=:selected_menu_id,
                  selected_merchant_id=:selected_merchant_id, dialogue_act=:dialogue_act,
                  meal_need_state_json=:meal_need_state, state_version=:next_version,
                  updated_at=:updated_at
                WHERE session_id=:session_id AND state_version=:expected_version
                """,
                state=chat_state,
                selected_menu_id=selected_menu_id,
                selected_merchant_id=selected_merchant_id,
                dialogue_act=dialogue_act.value,
                meal_need_state=need_state.model_dump_json(),
                next_version=next_version,
                updated_at=_now(),
                session_id=session_id,
                expected_version=version,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            result = ConversationEventResult(
                event_id=_id("event"),
                event_type=event.event_type,
                state_version=next_version,
                state=need_state,
                selected_menu_id=str(selected_menu_id) if selected_menu_id else None,
                selected_merchant_id=(str(selected_merchant_id) if selected_merchant_id else None),
                selected_menu=selected_menu,
            )
            cursor.execute(
                """
                INSERT INTO conversation_event(event_id,session_id,snapshot_id,event_type,
                  payload_json,result_json,idempotency_key,resulting_state_version,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9)
                """,
                [
                    result.event_id,
                    session_id,
                    event.snapshot_id,
                    event.event_type.value,
                    event.model_dump_json(),
                    result.model_dump_json(),
                    event.idempotency_key,
                    next_version,
                    _now(),
                ],
            )
        return result

    def set_session_selection(
        self, session_id: str, state: str, menu_id: str | None, merchant_id: str | None
    ) -> None:
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                UPDATE chat_session SET state=:state, selected_menu_id=:menu_id,
                  selected_merchant_id=:merchant_id, updated_at=:updated_at
                WHERE session_id=:session_id
                """,
                state=state,
                menu_id=menu_id,
                merchant_id=merchant_id,
                updated_at=_now(),
                session_id=session_id,
            )

    def search_menus(
        self,
        query: str,
        profile: Profile,
        budget_krw: int | None,
        max_spiciness: int | None,
        excluded_ingredients: list[str],
        limit: int = 4,
        constraint_strictness: ConstraintStrictness = ConstraintStrictness.STRICT,
    ) -> list[MenuSummary]:
        budget = budget_krw or 30000
        spice = max_spiciness if max_spiciness is not None else max(profile.spice_tolerance, 1)
        safety_state = apply_profile_constraints(
            MealNeedState(
                budget_krw=budget,
                max_spiciness=spice,
                excluded_ingredients=excluded_ingredients,
            ),
            profile.dietary_rules,
            profile.religion_selection,
        )
        safety_state.strictness = constraint_strictness
        query_vector = array("f", self.embedding_provider.embed([query], "SEARCH_QUERY")[0])
        vegan_required = "vegan" in profile.dietary_rules
        severe_allergies = profile.allergy_severity == "severe"
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max,
                  VECTOR_DISTANCE(m.embedding_vector, :query_vector, COSINE) AS vector_distance
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE m.availability = 'AVAILABLE'
                  AND m.price <= :budget
                  AND (m.spice_level IS NULL OR m.spice_level <= :spice)
                  AND m.embedding_vector IS NOT NULL
                  AND (:vegan_required = 0 OR EXISTS (
                    SELECT 1 FROM menu_dietary_attribute mda
                    JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                    WHERE mda.menu_id=m.menu_id AND da.code='vegan_option'
                      AND mda.status='VERIFIED'
                  ))
                  AND (:exclude_pork = 0 OR NOT JSON_EXISTS(m.allergen_tags_json, '$?(@ == "pork")'))
                ORDER BY vector_distance, m.price
                """,
                query_vector=query_vector,
                budget=budget,
                spice=spice,
                vegan_required=int(vegan_required),
                exclude_pork=int("pork" in {item.lower() for item in excluded_ingredients}),
            )
            rows = _rows(cursor)
            candidate_ids = [str(row["menu_id"]) for row in rows]
            grounded = self._bulk_resolved_knowledge_claims(connection, candidate_ids)
            knowledge = self._bulk_knowledge_passages(
                connection,
                candidate_ids,
                query_vector,
                query=query,
            )
            evidence_by_menu: dict[str, list[str]] = defaultdict(list)
            if candidate_ids:
                bind_names = [f"evidence_menu_{index}" for index in range(len(candidate_ids))]
                evidence_binds = dict(zip(bind_names, candidate_ids))
                cursor.execute(
                    f"""
                    SELECT subject_id,evidence_id FROM evidence
                    WHERE subject_id IN ({",".join(":" + name for name in bind_names)})
                    ORDER BY subject_id,evidence_id
                    """,
                    evidence_binds,
                )
                for evidence_row in _rows(cursor):
                    evidence_by_menu[str(evidence_row["subject_id"])].append(
                        str(evidence_row["evidence_id"])
                    )

        scored: list[MenuSummary] = []
        for row in rows:
            menu_id = str(row["menu_id"])
            tags = set(_json(row["dietary_tags_json"]))
            allergens = set(_json(row["allergen_tags_json"]))
            if severe_allergies and known_allergen_conflicts(allergens, set(profile.dietary_rules)):
                continue
            menu_similarity = max(0.0, 1.0 - float(row["vector_distance"]))
            knowledge_similarity, passage_ids = knowledge.get(menu_id, (0.0, []))
            operational_signal = operational_menu_signal(
                menu_similarity,
                price=int(row["price"]),
                budget=budget,
                delivery_fee=int(row["delivery_fee"]),
                eta_max=int(row["eta_max"]),
            )
            spice_level = _optional_int(row["spice_level"])
            reasons = (
                [f"Matches your spice tolerance (level {spice_level} of 5)"]
                if spice_level is not None
                else ["Spice level was not provided by the source"]
            )
            risks: list[str] = (
                ["Confirm spice level with the merchant"] if spice_level is None else []
            )
            status = EvidenceStatus.UNKNOWN
            if "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
                reasons.append("Demo sauce specification has shellfish marked absent")
                risks.append("Cross-contamination is not verified")
            elif allergens:
                risks.append("Some dietary details are not verified")
            ingredient_claims, allergen_claims, merchant_claims = grounded.get(
                menu_id, ([], [], [])
            )
            conflicts = ingredient_constraint_conflicts(ingredient_claims, safety_state)
            conflicts.extend(allergen_constraint_conflicts(allergen_claims, safety_state))
            if profile.allergy_severity == "severe":
                conflicts.extend(
                    severe_allergy_conflicts(
                        ingredient_claims,
                        allergen_claims,
                        safety_state.dietary_rules,
                    )
                )
            conflicts.extend(
                merchant_cross_contact_conflicts(
                    merchant_claims,
                    safety_state,
                    allergy_severity=profile.allergy_severity,
                )
            )
            if conflicts:
                continue
            absent_allergies, cross_contact_unknown = confirmed_allergen_absence_signals(
                allergen_claims,
                safety_state.dietary_rules,
            )
            for allergy in absent_allergies:
                reasons.append(
                    f"Synthetic menu specification marks {allergy.replace('_', ' ')} absent"
                )
            if absent_allergies:
                status = EvidenceStatus.VERIFIED
            if cross_contact_unknown and "Cross-contamination is not verified" not in risks:
                risks.append("Cross-contamination is not verified")
            # Reviews remain display-only and intentionally contribute exactly zero.
            similarity = wiki_operational_retrieval_score(
                knowledge_similarity,
                operational_signal,
            )
            claim_ids = list(
                dict.fromkeys(
                    [claim.source_id for claim in ingredient_claims]
                    + [claim.source_id for claim in allergen_claims]
                    + [claim.source_id for claim in merchant_claims]
                )
            )
            scored.append(
                self._menu_summary(row, reasons, risks, status, similarity).model_copy(
                    update={
                        "evidence_ids": evidence_by_menu.get(menu_id, []),
                        "grounded_claim_ids": claim_ids,
                        "grounded_passage_ids": passage_ids,
                    }
                )
            )
        scored.sort(key=lambda item: (item.semantic_score, -item.price), reverse=True)
        return scored[: min(limit, RECOMMENDATION_CANDIDATE_CAP)]

    def recommend_menus(
        self,
        query: str,
        profile: Profile,
        meal_need_state: MealNeedState,
        limit: int = 4,
    ) -> list[MenuSummary]:
        meal_need_state = apply_profile_constraints(
            meal_need_state, profile.dietary_rules, profile.religion_selection
        )
        effective_profile = profile.model_copy(
            update={
                "dietary_rules": list(
                    dict.fromkeys([*profile.dietary_rules, *meal_need_state.dietary_rules])
                )
            }
        )
        expanded_query = " ".join(
            part
            for part in (
                query,
                *meal_need_state.temperature_preferences,
                *meal_need_state.texture_preferences,
                *meal_need_state.flavor_preferences,
                *meal_need_state.preferred_categories,
            )
            if part
        )
        candidates = self.search_menus(
            expanded_query,
            effective_profile,
            meal_need_state.budget_krw,
            meal_need_state.max_spiciness,
            meal_need_state.excluded_ingredients,
            limit=RECOMMENDATION_CANDIDATE_CAP,
            constraint_strictness=meal_need_state.strictness,
        )
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT merchant_id, service_area_id FROM merchant")
            merchant_areas = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
        return rerank_menu_candidates(candidates, meal_need_state, merchant_areas, limit)

    @staticmethod
    def _menu_summary(
        row: dict[str, Any],
        reasons: list[str],
        risks: list[str],
        status: EvidenceStatus,
        score: float,
    ) -> MenuSummary:
        return MenuSummary(
            menu_id=row["menu_id"],
            merchant_id=row["merchant_id"],
            merchant_name=_catalog_text(row["merchant_name"]),
            name_en=_catalog_text(row["name_en"], row["name_ko"]),
            name_ko=row["name_ko"],
            category=row["category"],
            description=_catalog_text(row["description"]),
            cultural_description=_catalog_text(row["cultural_description"]),
            price=int(row["price"]),
            delivery_fee=int(row["delivery_fee"]),
            eta_min=int(row["eta_min"]),
            eta_max=int(row["eta_max"]),
            spice_level=_optional_int(row["spice_level"]),
            serves_min=_optional_int(row["serves_min"]),
            serves_max=_optional_int(row["serves_max"]),
            dietary_summary=(
                "Synthetic evidence; see evidence details before ordering."
                if bool(row["is_synthetic"])
                else "Dietary details were not provided by the source; confirm with the merchant."
            ),
            evidence_status=status,
            match_reasons=reasons,
            risk_hints=risks,
            semantic_score=round(max(0.0, min(1.0, score)), 4),
            is_synthetic=bool(row["is_synthetic"]),
        )

    def get_menu(self, menu_id: str, profile: Profile) -> MenuSummary | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.menu_id=:id
                """,
                id=menu_id,
            )
            row = _row(cursor)
        if not row:
            return None
        tags = set(_json(row["dietary_tags_json"]))
        allergens = set(_json(row["allergen_tags_json"]))
        status = EvidenceStatus.UNKNOWN
        if "shellfish_risk" in allergens:
            status = EvidenceStatus.RISK_SIGNAL
        elif "shellfish_sauce_absent" in tags:
            status = EvidenceStatus.VERIFIED
        external_source = not bool(row["is_synthetic"])
        menu = self._menu_summary(
            row,
            [
                "Selected menu from the provided Yogiyo source catalog"
                if external_source
                else "Selected menu from the synthetic catalog"
            ],
            [
                "Ingredients, dietary suitability, and cross-contamination were not provided"
                if external_source
                else "Cross-contamination is not verified"
            ],
            status,
            1.0,
        )
        knowledge = self.get_grounded_menu_knowledge(menu_id)
        return menu.model_copy(
            update={
                "evidence_ids": [item.evidence_id for item in self.get_evidence(menu_id)],
                "grounded_claim_ids": knowledge.claim_ids,
                "grounded_passage_ids": [item.chunk_id for item in knowledge.passages],
            }
        )

    def get_category_knowledge_source(self, category: str) -> str | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT menu_id FROM menu
                WHERE lower(category)=lower(:category)
                ORDER BY CASE WHEN availability='AVAILABLE' THEN 0 ELSE 1 END, menu_id
                FETCH FIRST 1 ROWS ONLY
                """,
                category=category,
            )
            row = cursor.fetchone()
        return str(row[0]) if row else None

    def list_merchant_menus(
        self,
        merchant_id: str,
        profile: Profile,
        excluded_menu_ids: list[str],
        limit: int = 12,
        meal_need_state: MealNeedState | None = None,
    ) -> list[MenuSummary]:
        safety_state = apply_profile_constraints(
            meal_need_state.model_copy(deep=True)
            if meal_need_state is not None
            else MealNeedState(max_spiciness=profile.spice_tolerance),
            profile.dietary_rules,
            profile.religion_selection,
        )
        if safety_state.max_spiciness is None:
            safety_state.max_spiciness = profile.spice_tolerance
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max,
                  r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.merchant_id=:merchant_id AND m.availability='AVAILABLE'
                  AND (m.spice_level IS NULL OR m.spice_level<=:spice)
                ORDER BY m.price, m.menu_id
                """,
                merchant_id=merchant_id,
                spice=safety_state.max_spiciness,
            )
            rows = _rows(cursor)
            hard_conflicts = {
                str(row["menu_id"]): self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    safety_state,
                    profile.allergy_severity,
                )[0]
                for row in rows
            }
        excluded = set(excluded_menu_ids)
        rules = set(profile.dietary_rules)
        candidates: list[MenuSummary] = []
        merchant_areas: dict[str, str] = {}
        for index, row in enumerate(rows):
            if row["menu_id"] in excluded:
                continue
            if hard_conflicts.get(str(row["menu_id"])):
                continue
            tags = set(_json(row["dietary_tags_json"]))
            allergens = set(_json(row["allergen_tags_json"]))
            if profile.allergy_severity == "severe" and known_allergen_conflicts(allergens, rules):
                continue
            if "vegan" in rules and "vegan_option" not in tags:
                continue
            status = EvidenceStatus.UNKNOWN
            if "shellfish_risk" in allergens:
                status = EvidenceStatus.RISK_SIGNAL
            elif "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
            menu = self._menu_summary(
                row,
                ["More from the restaurant already selected"],
                ["Cross-contamination is not verified"],
                status,
                max(0.1, 0.6 - index * 0.001),
            )
            merchant_areas[menu.merchant_id] = str(row["merchant_service_area_id"])
            candidates.append(
                menu.model_copy(
                    update={
                        "evidence_ids": [
                            item.evidence_id for item in self.get_evidence(menu.menu_id)
                        ]
                    }
                )
            )
        return rerank_menu_candidates(candidates, safety_state, merchant_areas, limit)

    def list_merchant_menu_presentations(
        self,
        session_id: str,
        merchant_id: str,
        request: MerchantMenuPresentationRequest,
    ) -> MerchantMenuPresentationPage:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT profile.preferred_language,profile.country_code,
                       family.knowledge_release_id,family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=:session_id
                """,
                session_id=session_id,
            )
            context = _row(cursor)
            if context is None:
                raise KeyError("SESSION_NOT_FOUND")
            release_id = str(context.get("synthetic_enrichment_release_id") or "")
            if not release_id:
                raise RuntimeError("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            requested_locale = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested_locale if requested_locale in {"ko", "ja"} else "en"
            country_code = str(context.get("country_code") or "US")
            binds: dict[str, Any] = {
                "release_id": release_id,
                "language_code": language_code,
                "country_code": country_code,
                "knowledge_release_id": str(context["knowledge_release_id"]),
                "merchant_id": merchant_id,
                "cursor": request.cursor or "",
                "row_limit": request.limit + 1,
            }
            exclude_sql = ""
            if request.exclude_menu_ids:
                names = []
                for index, menu_id in enumerate(request.exclude_menu_ids):
                    key = f"exclude_menu_{index}"
                    binds[key] = menu_id
                    names.append(f":{key}")
                exclude_sql = f" AND menu.menu_id NOT IN ({','.join(names)})"
            cursor.execute(
                f"""
                SELECT * FROM (
                  SELECT menu.*,COALESCE(merchant.name_en,merchant.name_ko) merchant_name,
                         merchant.delivery_fee,merchant.eta_min,merchant.eta_max,
                         localization.display_name,preference.preference_percent,
                         preference.sample_size
                  FROM menu_wiki_eligibility eligibility
                  JOIN menu ON menu.menu_id=eligibility.menu_id
                  JOIN merchant ON merchant.merchant_id=menu.merchant_id
                  LEFT JOIN menu_localization localization
                    ON localization.release_id=:release_id
                   AND localization.menu_id=menu.menu_id
                   AND localization.language_code=:language_code
                   AND localization.validation_status='VALID'
                  LEFT JOIN synthetic_menu_country_preference preference
                    ON preference.release_id=:release_id
                   AND preference.menu_id=menu.menu_id
                   AND preference.country_code=:country_code
                  WHERE eligibility.knowledge_release_id=:knowledge_release_id
                    AND menu.merchant_id=:merchant_id AND menu.availability='AVAILABLE'
                    AND menu.menu_id>:cursor {exclude_sql}
                  ORDER BY menu.menu_id
                ) WHERE ROWNUM<=:row_limit
                """,
                binds,
            )
            rows = _rows(cursor)
            has_more = len(rows) > request.limit
            visible_rows = rows[: request.limit]
            items: list[MerchantMenuPresentation] = []
            for row in visible_rows:
                menu_id = str(row["menu_id"])
                cursor.execute(
                    """
                    SELECT * FROM (
                      SELECT chunk.chunk_id,chunk.content
                      FROM menu_concept_membership membership
                      JOIN dish_concept_closure closure
                        ON closure.release_id=membership.knowledge_release_id
                       AND closure.descendant_concept_id=membership.concept_id
                       AND closure.inherit_claims=1
                      JOIN knowledge_chunk chunk
                        ON chunk.release_id=closure.release_id
                       AND chunk.concept_id=closure.ancestor_concept_id
                      JOIN knowledge_document document
                        ON document.release_id=chunk.release_id
                       AND document.document_id=chunk.document_id
                      WHERE membership.knowledge_release_id=:knowledge_release_id
                        AND membership.menu_id=:menu_id
                        AND document.source_type='SYNTHETIC_WIKI'
                        AND document.review_status='REVIEWED_DEMO'
                        AND lower(chunk.facet)<>'safety'
                      ORDER BY closure.depth,chunk.chunk_index,chunk.chunk_id
                    ) WHERE ROWNUM<=2
                    """,
                    knowledge_release_id=str(context["knowledge_release_id"]),
                    menu_id=menu_id,
                )
                passage_rows = _rows(cursor)
                cursor.execute(
                    """
                    SELECT * FROM (
                      SELECT review_id,topic,rating,review_text FROM synthetic_review_snippet
                      WHERE release_id=:release_id AND menu_id=:menu_id
                      ORDER BY display_order
                    ) WHERE ROWNUM<=3
                    """,
                    release_id=release_id,
                    menu_id=menu_id,
                )
                reviews = _rows(cursor)
                title = str(
                    row.get("display_name")
                    or (row["name_ko"] if language_code == "ko" else row["name_en"])
                    or row["name_ko"]
                )
                passage_texts = [
                    _oracle_logical_text(passage["content"]) for passage in passage_rows
                ]
                presentation_copy = deterministic_presentation_copy(
                    language_code,
                    localized_title=title,
                    wiki_passages=passage_texts,
                    reviews=[
                        {"topic": review["topic"], "rating": review["rating"]}
                        for review in reviews
                    ],
                )
                short = presentation_copy.short_explanation
                long = presentation_copy.long_explanation
                review_summary = presentation_copy.review_summary
                source_description = _oracle_logical_text(row.get("description"))
                evidence_ids = [str(passage["chunk_id"]) for passage in passage_rows]
                review_ids = [str(review["review_id"]) for review in reviews]
                source_hash = hashlib.sha256(
                    json.dumps(
                        {
                            "localized_title": title,
                            "source_description": source_description,
                            "evidence_ids": evidence_ids,
                            "review_ids": review_ids,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                cursor.execute(
                    """
                    SELECT * FROM (
                      SELECT * FROM menu_presentation_cache
                      WHERE release_id=:release_id AND menu_id=:menu_id
                        AND language_code=:language_code AND country_code=:country_code
                        AND source_hash=:source_hash ORDER BY created_at DESC
                    ) WHERE ROWNUM=1
                    """,
                    release_id=release_id,
                    menu_id=menu_id,
                    language_code=language_code,
                    country_code=country_code,
                    source_hash=source_hash,
                )
                cached = _row(cursor)
                if cached is not None:
                    title = str(cached["localized_title"])
                    short = _oracle_logical_text(cached["short_explanation"])
                    long = _oracle_logical_text(cached["long_explanation"])
                    review_summary = _oracle_logical_text(cached["review_summary"])
                items.append(
                    MerchantMenuPresentation(
                        menu=self._menu_summary(
                            row,
                            ["More from this restaurant"],
                            [],
                            EvidenceStatus.UNKNOWN,
                            0.5,
                        ),
                        localized_title=title,
                        yobi_short_explanation=short,
                        yobi_long_explanation=long,
                        source_description=source_description,
                        review_summary=review_summary,
                        country_preference={
                            "country_code": country_code,
                            "preference_percent": int(row.get("preference_percent") or 54),
                            "sample_size": int(row.get("sample_size") or 120),
                        },
                        evidence_ids=evidence_ids,
                        review_ids=review_ids,
                        generation_model=(
                            str(cached["model_id"])
                            if cached is not None
                            else "DETERMINISTIC_WIKI_FALLBACK"
                        ),
                    )
                )
        return MerchantMenuPresentationPage(
            items=items,
            next_cursor=(str(visible_rows[-1]["menu_id"]) if has_more and visible_rows else None),
        )

    def save_menu_presentation_cache(
        self, session_id: str, presentation: MerchantMenuPresentation
    ) -> None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT profile.preferred_language,profile.country_code,
                       family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=:session_id
                """,
                session_id=session_id,
            )
            context = _row(cursor)
            if context is None or not context.get("synthetic_enrichment_release_id"):
                raise RuntimeError("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            release_id = str(context["synthetic_enrichment_release_id"])
            requested_locale = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested_locale if requested_locale in {"ko", "ja"} else "en"
            country_code = str(context.get("country_code") or "US")
            source_hash = hashlib.sha256(
                json.dumps(
                    {
                        "localized_title": presentation.localized_title,
                        "source_description": presentation.source_description,
                        "evidence_ids": presentation.evidence_ids,
                        "review_ids": presentation.review_ids,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            cache_key = hashlib.sha256(
                f"{release_id}|{presentation.menu.menu_id}|{language_code}|{country_code}".encode()
            ).hexdigest()
            cursor.execute(
                """
                MERGE INTO menu_presentation_cache target
                USING (SELECT :cache_key cache_key FROM dual) source
                ON (target.cache_key=source.cache_key)
                WHEN MATCHED THEN UPDATE SET
                  localized_title=:localized_title,short_explanation=:short_explanation,
                  long_explanation=:long_explanation,review_summary=:review_summary,
                  evidence_ids_json=:evidence_ids_json,review_ids_json=:review_ids_json,
                  model_id=:model_id,source_hash=:source_hash,created_at=:created_at
                WHEN NOT MATCHED THEN INSERT (
                  cache_key,release_id,menu_id,language_code,country_code,localized_title,
                  short_explanation,long_explanation,review_summary,evidence_ids_json,
                  review_ids_json,model_id,source_hash,created_at
                ) VALUES (
                  :cache_key,:release_id,:menu_id,:language_code,:country_code,:localized_title,
                  :short_explanation,:long_explanation,:review_summary,:evidence_ids_json,
                  :review_ids_json,:model_id,:source_hash,:created_at
                )
                """,
                cache_key=cache_key,
                release_id=release_id,
                menu_id=presentation.menu.menu_id,
                language_code=language_code,
                country_code=country_code,
                localized_title=presentation.localized_title,
                short_explanation=presentation.yobi_short_explanation,
                long_explanation=presentation.yobi_long_explanation,
                review_summary=presentation.review_summary,
                evidence_ids_json=json.dumps(presentation.evidence_ids),
                review_ids_json=json.dumps(presentation.review_ids),
                model_id=presentation.generation_model,
                source_hash=source_hash,
                created_at=_now(),
            )

    def get_evidence(self, menu_id: str) -> list[Evidence]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM evidence WHERE subject_id=:id ORDER BY evidence_id", id=menu_id
            )
            rows = _rows(cursor)
        return [Evidence(**row) for row in rows]

    @staticmethod
    def _resolved_knowledge_claims(
        connection: oracledb.Connection,
        menu_id: str,
        option_item_ids: list[str] | None = None,
    ) -> tuple[str | None, str | None, list[Any], list[Any]]:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT state.active_release_id, mapping.concept_id
            FROM knowledge_runtime_state state
            JOIN knowledge_release release ON release.release_id=state.active_release_id
            LEFT JOIN menu_concept_map mapping
              ON mapping.release_id=state.active_release_id AND mapping.menu_id=:menu_id
              AND mapping.mapping_status='MAPPED'
            WHERE state.state_key='ACTIVE' AND release.status='READY'
            """,
            menu_id=menu_id,
        )
        active = _row(cursor)
        if active is None:
            return None, None, [], []
        release_id = str(active["active_release_id"])
        concept_id = str(active["concept_id"]) if active.get("concept_id") else None
        wiki_ingredient_rows: list[dict[str, Any]] = []
        wiki_allergen_rows: list[dict[str, Any]] = []
        if concept_id:
            cursor.execute(
                """
                SELECT claim.*, ingredient.name_en, ingredient.name_ko, closure.depth,
                       claim.release_id AS source_version
                FROM dish_concept_closure closure
                JOIN concept_claim claim
                  ON claim.release_id=closure.release_id
                 AND claim.concept_id=closure.ancestor_concept_id
                JOIN ingredient ON ingredient.ingredient_id=claim.ingredient_id
                WHERE closure.release_id=:release_id
                  AND closure.descendant_concept_id=:concept_id
                  AND closure.inherit_claims=1 AND claim.claim_type='INGREDIENT'
                  AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                """,
                release_id=release_id,
                concept_id=concept_id,
            )
            wiki_ingredient_rows = _rows(cursor)
            cursor.execute(
                """
                SELECT claim.*, allergen.code, closure.depth,
                       claim.release_id AS source_version
                FROM dish_concept_closure closure
                JOIN concept_claim claim
                  ON claim.release_id=closure.release_id
                 AND claim.concept_id=closure.ancestor_concept_id
                JOIN allergen ON allergen.allergen_id=claim.allergen_id
                WHERE closure.release_id=:release_id
                  AND closure.descendant_concept_id=:concept_id
                  AND closure.inherit_claims=1 AND claim.claim_type='ALLERGEN'
                  AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                """,
                release_id=release_id,
                concept_id=concept_id,
            )
            wiki_allergen_rows = _rows(cursor)
        cursor.execute(
            """
            SELECT fact.*, ingredient.name_en, ingredient.name_ko,
                   fact.source_id AS source_version
            FROM menu_ingredient fact
            JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
            WHERE fact.menu_id=:menu_id
            """,
            menu_id=menu_id,
        )
        menu_ingredient_rows = _rows(cursor)
        cursor.execute(
            """
            SELECT fact.*, allergen.code, fact.evidence_id AS source_id,
                   'catalog' AS source_version
            FROM menu_allergen fact
            JOIN allergen ON allergen.allergen_id=fact.allergen_id
            WHERE fact.menu_id=:menu_id
            """,
            menu_id=menu_id,
        )
        menu_allergen_rows = _rows(cursor)
        option_rows: list[dict[str, Any]] = []
        selected_options = list(dict.fromkeys(option_item_ids or []))
        if selected_options:
            bind_names = [f"option_{index}" for index in range(len(selected_options))]
            binds: dict[str, Any] = {"release_id": release_id}
            binds.update(dict(zip(bind_names, selected_options)))
            cursor.execute(
                f"""
                SELECT effect.*, ingredient.name_en, ingredient.name_ko,
                       effect.option_item_id AS source_id,
                       effect.release_id AS source_version
                FROM option_ingredient_effect effect
                JOIN ingredient ON ingredient.ingredient_id=effect.ingredient_id
                WHERE effect.release_id=:release_id
                  AND effect.option_item_id IN ({",".join(":" + name for name in bind_names)})
                """,
                binds,
            )
            option_rows = _rows(cursor)
        return (
            release_id,
            concept_id,
            resolve_ingredient_claims(wiki_ingredient_rows, menu_ingredient_rows, option_rows),
            resolve_allergen_claims(wiki_allergen_rows, menu_allergen_rows),
        )

    @staticmethod
    def _bulk_resolved_knowledge_claims(
        connection: oracledb.Connection,
        menu_ids: list[str],
        *,
        release_id: str | None = None,
    ) -> dict[str, tuple[list[Any], list[Any], list[Any]]]:
        """Resolve candidate claims with bounded, set-based Oracle queries."""

        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        cursor = connection.cursor()
        if release_id is None:
            cursor.execute(
                """
                SELECT release.release_id
                FROM knowledge_runtime_state state
                JOIN knowledge_release release ON release.release_id=state.active_release_id
                WHERE state.state_key='ACTIVE' AND release.status='READY'
                """
            )
            active = cursor.fetchone()
            if active is None:
                return {menu_id: ([], [], []) for menu_id in unique_ids}
            release_id = str(active[0])
        menu_bind_names = [f"menu_{index}" for index in range(len(unique_ids))]
        binds: dict[str, Any] = {"release_id": release_id}
        binds.update(dict(zip(menu_bind_names, unique_ids)))
        in_clause = ",".join(":" + name for name in menu_bind_names)

        cursor.execute(
            f"""
            SELECT mapping.menu_id,claim.*,ingredient.name_en,ingredient.name_ko,closure.depth,
                   claim.release_id AS source_version
            FROM menu_concept_map mapping
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
            JOIN concept_claim claim
              ON claim.release_id=closure.release_id
             AND claim.concept_id=closure.ancestor_concept_id
            JOIN ingredient ON ingredient.ingredient_id=claim.ingredient_id
            WHERE mapping.release_id=:release_id AND mapping.mapping_status='MAPPED'
              AND mapping.menu_id IN ({in_clause})
              AND closure.inherit_claims=1 AND claim.claim_type='INGREDIENT'
              AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
            """,
            binds,
        )
        wiki_ingredients = _rows(cursor)
        cursor.execute(
            f"""
            SELECT mapping.menu_id,claim.*,allergen.code,closure.depth,
                   claim.release_id AS source_version
            FROM menu_concept_map mapping
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
            JOIN concept_claim claim
              ON claim.release_id=closure.release_id
             AND claim.concept_id=closure.ancestor_concept_id
            JOIN allergen ON allergen.allergen_id=claim.allergen_id
            WHERE mapping.release_id=:release_id AND mapping.mapping_status='MAPPED'
              AND mapping.menu_id IN ({in_clause})
              AND closure.inherit_claims=1 AND claim.claim_type='ALLERGEN'
              AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
            """,
            binds,
        )
        wiki_allergens = _rows(cursor)
        cursor.execute(
            f"""
            SELECT fact.menu_id,fact.*,ingredient.name_en,ingredient.name_ko,
                   fact.source_id AS source_version
            FROM menu_ingredient fact
            JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
            WHERE fact.menu_id IN ({in_clause})
            """,
            {name: binds[name] for name in menu_bind_names},
        )
        menu_ingredients = _rows(cursor)
        cursor.execute(
            f"""
            SELECT fact.menu_id,fact.*,allergen.code,fact.evidence_id AS source_id,
                   'catalog' AS source_version
            FROM menu_allergen fact
            JOIN allergen ON allergen.allergen_id=fact.allergen_id
            WHERE fact.menu_id IN ({in_clause})
            """,
            {name: binds[name] for name in menu_bind_names},
        )
        menu_allergens = _rows(cursor)
        cursor.execute(
            f"""
            SELECT menu.menu_id,fact.*,ingredient.name_en,ingredient.name_ko,
                   declaration.source_version
            FROM menu
            JOIN merchant_ingredient fact ON fact.merchant_id=menu.merchant_id
            JOIN merchant_origin_declaration declaration
              ON declaration.release_id=fact.release_id
             AND declaration.declaration_id=fact.declaration_id
            JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
            WHERE fact.release_id=:release_id AND menu.menu_id IN ({in_clause})
            """,
            binds,
        )
        merchant_ingredients = _rows(cursor)

        grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
            menu_id: defaultdict(list) for menu_id in unique_ids
        }
        for key, rows in (
            ("wiki_ingredients", wiki_ingredients),
            ("wiki_allergens", wiki_allergens),
            ("menu_ingredients", menu_ingredients),
            ("menu_allergens", menu_allergens),
            ("merchant_ingredients", merchant_ingredients),
        ):
            for source in rows:
                row = dict(source)
                menu_id = str(row.pop("menu_id"))
                if key == "merchant_ingredients":
                    row["source_id"] = f"{row['declaration_id']}:{row['ingredient_id']}"
                grouped[menu_id][key].append(row)
        return {
            menu_id: (
                resolve_ingredient_claims(
                    parts["wiki_ingredients"],
                    parts["menu_ingredients"],
                ),
                resolve_allergen_claims(
                    parts["wiki_allergens"],
                    parts["menu_allergens"],
                ),
                resolve_merchant_ingredient_claims(parts["merchant_ingredients"]),
            )
            for menu_id, parts in grouped.items()
        }

    @staticmethod
    def _bulk_knowledge_passages(
        connection: oracledb.Connection,
        menu_ids: list[str],
        query_vector: array[float],
        *,
        query: str = "",
    ) -> dict[str, tuple[float, list[str]]]:
        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        menu_bind_names = [f"menu_{index}" for index in range(len(unique_ids))]
        binds: dict[str, Any] = {"query_vector": query_vector}
        binds.update(dict(zip(menu_bind_names, unique_ids)))
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT mapping.menu_id,chunk.chunk_id,chunk.facet,chunk.content,
                   concept.canonical_name_ko,concept.canonical_name_en,concept.aliases_json,
                   VECTOR_DISTANCE(chunk.embedding_vector,:query_vector,COSINE) distance
            FROM knowledge_runtime_state state
            JOIN knowledge_release release ON release.release_id=state.active_release_id
            JOIN menu_concept_map mapping
              ON mapping.release_id=release.release_id AND mapping.mapping_status='MAPPED'
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
             AND closure.inherit_claims=1
            JOIN knowledge_chunk chunk
              ON chunk.release_id=closure.release_id
             AND chunk.concept_id=closure.ancestor_concept_id
            JOIN dish_concept concept
              ON concept.release_id=chunk.release_id
             AND concept.concept_id=chunk.concept_id
            WHERE state.state_key='ACTIVE' AND release.status='READY'
              AND mapping.menu_id IN ({",".join(":" + name for name in menu_bind_names)})
              AND chunk.embedding_vector IS NOT NULL
              AND chunk.embedding_model=release.embedding_model
              AND chunk.embedding_dimension=release.embedding_dimension
              AND chunk.embedding_version=release.embedding_version
            """,
            binds,
        )
        grouped: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for row in _rows(cursor):
            aliases = [
                str(row.get("canonical_name_ko") or ""),
                str(row.get("canonical_name_en") or ""),
            ]
            if row.get("aliases_json"):
                aliases.extend(str(alias) for alias in _json(row["aliases_json"]))
            vector_similarity = max(0.0, 1.0 - float(row["distance"]))
            grouped[str(row["menu_id"])].append(
                (
                    hybrid_knowledge_chunk_score(
                        query,
                        vector_similarity,
                        str(row.get("facet") or ""),
                        aliases,
                        str(row.get("content") or ""),
                    ),
                    str(row["chunk_id"]),
                )
            )
        result: dict[str, tuple[float, list[str]]] = {}
        for menu_id, values in grouped.items():
            ranked = sorted(values, key=lambda item: (-item[0], item[1]))
            result[menu_id] = (
                min(1.0, ranked[0][0]),
                [chunk_id for _, chunk_id in ranked[:RECOMMENDATION_PASSAGE_LIMIT]],
            )
        return result

    @staticmethod
    def _menu_hard_constraint_conflicts(
        connection: oracledb.Connection,
        menu_id: str,
        state: MealNeedState,
        allergy_severity: str,
        option_item_ids: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Oracle parity for current-state, grounded hard-constraint validation."""

        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT m.*, merchant.service_area_id
            FROM menu m JOIN merchant ON merchant.merchant_id=m.merchant_id
            WHERE m.menu_id=:menu_id
            """,
            menu_id=menu_id,
        )
        menu = _row(cursor)
        if menu is None or menu["availability"] != "AVAILABLE":
            return ["menu:unavailable"], []
        conflicts: list[str] = []
        if state.budget_krw is not None and int(menu["price"]) > state.budget_krw:
            conflicts.append("menu:over_budget")
        if (
            state.max_spiciness is not None
            and menu["spice_level"] is not None
            and int(menu["spice_level"]) > state.max_spiciness
        ):
            conflicts.append("menu:too_spicy")
        if menu_id in state.rejected_menu_ids:
            conflicts.append("menu:rejected")
        if state.service_area_id and menu.get("service_area_id") != state.service_area_id:
            conflicts.append("menu:service_area")
        conflicts.extend(category_constraint_conflicts(str(menu["category"]), state))

        _, _, ingredient_claims, allergen_claims = OracleYobiRepository._resolved_knowledge_claims(
            connection, menu_id, option_item_ids
        )
        cursor.execute(
            """
            SELECT fact.*,ingredient.name_en,ingredient.name_ko,declaration.source_version
            FROM menu
            JOIN knowledge_runtime_state state ON state.state_key='ACTIVE'
            JOIN merchant_ingredient fact
              ON fact.release_id=state.active_release_id
             AND fact.merchant_id=menu.merchant_id
            JOIN merchant_origin_declaration declaration
              ON declaration.release_id=fact.release_id
             AND declaration.declaration_id=fact.declaration_id
            JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
            WHERE menu.menu_id=:menu_id
            """,
            menu_id=menu_id,
        )
        merchant_claims = resolve_merchant_ingredient_claims(
            [
                {
                    **row,
                    "source_id": f"{row['declaration_id']}:{row['ingredient_id']}",
                }
                for row in _rows(cursor)
            ]
        )
        conflicts.extend(ingredient_constraint_conflicts(ingredient_claims, state))
        conflicts.extend(allergen_constraint_conflicts(allergen_claims, state))
        if allergy_severity == "severe":
            conflicts.extend(
                severe_allergy_conflicts(
                    ingredient_claims,
                    allergen_claims,
                    state.dietary_rules,
                )
            )
        conflicts.extend(
            merchant_cross_contact_conflicts(
                merchant_claims,
                state,
                allergy_severity=allergy_severity,
            )
        )
        claim_ids = list(
            dict.fromkeys(
                [claim.source_id for claim in ingredient_claims]
                + [claim.source_id for claim in allergen_claims]
                + [claim.source_id for claim in merchant_claims]
            )
        )
        return list(dict.fromkeys(conflicts)), claim_ids

    def get_grounded_menu_knowledge(
        self,
        menu_id: str,
        query: str = "",
        option_item_ids: list[str] | None = None,
    ) -> GroundedMenuKnowledge:
        # External embedding latency must not consume an Oracle pool connection.
        with self.pool.connection() as lookup_connection:
            lookup_cursor = lookup_connection.cursor()
            lookup_cursor.execute(
                "SELECT name_en,category FROM menu WHERE menu_id=:menu_id",
                menu_id=menu_id,
            )
            menu_row = _row(lookup_cursor)
        search_text = query.strip() or (
            f"{menu_row['name_en']} {menu_row['category']} description ingredients safety"
            if menu_row
            else f"{menu_id} description ingredients safety"
        )
        query_vector = array("f", self.embedding_provider.embed([search_text], "SEARCH_QUERY")[0])
        with self.pool.connection() as connection:
            release_id, concept_id, ingredient_claims, allergen_claims = (
                self._resolved_knowledge_claims(connection, menu_id, option_item_ids)
            )
            cursor = connection.cursor()
            passages: list[GroundedPassage] = []
            concept_lineage: list[str] = []
            available_facets: list[str] = []
            wiki_dietary_rows: list[dict[str, Any]] = []
            wiki_preparation_rows: list[dict[str, Any]] = []
            if release_id and concept_id:
                cursor.execute(
                    """
                    SELECT ancestor_concept_id FROM dish_concept_closure
                    WHERE release_id=:release_id AND descendant_concept_id=:concept_id
                      AND inherit_claims=1 ORDER BY depth,ancestor_concept_id
                    """,
                    release_id=release_id,
                    concept_id=concept_id,
                )
                concept_lineage = [str(row[0]) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT DISTINCT chunk.facet
                    FROM knowledge_chunk chunk
                    JOIN dish_concept_closure closure
                      ON closure.release_id=chunk.release_id
                     AND closure.ancestor_concept_id=chunk.concept_id
                    WHERE chunk.release_id=:release_id
                      AND closure.descendant_concept_id=:concept_id
                      AND closure.inherit_claims=1
                    ORDER BY chunk.facet
                    """,
                    release_id=release_id,
                    concept_id=concept_id,
                )
                available_facets = [str(row[0]) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT claim.*,da.code,da.display_name,closure.depth,
                           claim.release_id AS source_version
                    FROM dish_concept_closure closure
                    JOIN concept_claim claim
                      ON claim.release_id=closure.release_id
                     AND claim.concept_id=closure.ancestor_concept_id
                    JOIN dietary_attribute da ON da.attribute_id=claim.attribute_id
                    WHERE closure.release_id=:release_id
                      AND closure.descendant_concept_id=:concept_id
                      AND closure.inherit_claims=1 AND claim.claim_type='DIETARY'
                      AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                    """,
                    release_id=release_id,
                    concept_id=concept_id,
                )
                wiki_dietary_rows = _rows(cursor)
                cursor.execute(
                    """
                    SELECT claim.*,closure.depth,claim.release_id AS source_version
                    FROM dish_concept_closure closure
                    JOIN concept_claim claim
                      ON claim.release_id=closure.release_id
                     AND claim.concept_id=closure.ancestor_concept_id
                    WHERE closure.release_id=:release_id
                      AND closure.descendant_concept_id=:concept_id
                      AND closure.inherit_claims=1 AND claim.claim_type='PREPARATION'
                      AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                    """,
                    release_id=release_id,
                    concept_id=concept_id,
                )
                wiki_preparation_rows = _rows(cursor)
                cursor.execute(
                    """
                    SELECT chunk.chunk_id,chunk.document_id,chunk.concept_id,chunk.facet,
                           chunk.content,concept.canonical_name_ko,
                           concept.canonical_name_en,concept.aliases_json,
                           VECTOR_DISTANCE(chunk.embedding_vector,:query_vector,COSINE) distance
                    FROM knowledge_chunk chunk
                    JOIN dish_concept_closure closure
                      ON closure.release_id=chunk.release_id
                     AND closure.ancestor_concept_id=chunk.concept_id
                    JOIN dish_concept concept
                      ON concept.release_id=chunk.release_id
                     AND concept.concept_id=chunk.concept_id
                    WHERE chunk.release_id=:release_id
                      AND closure.descendant_concept_id=:concept_id
                      AND closure.inherit_claims=1
                      AND chunk.embedding_vector IS NOT NULL
                    ORDER BY chunk.chunk_id
                    """,
                    query_vector=query_vector,
                    release_id=release_id,
                    concept_id=concept_id,
                )
                ranked_passages: list[tuple[float, dict[str, Any]]] = []
                for row in _rows(cursor):
                    aliases = [
                        str(row["canonical_name_ko"]),
                        str(row["canonical_name_en"]),
                        *[str(alias) for alias in _json(row["aliases_json"])],
                    ]
                    ranked_passages.append(
                        (
                            hybrid_knowledge_chunk_score(
                                search_text,
                                max(0.0, 1.0 - float(row["distance"])),
                                str(row["facet"]),
                                aliases,
                                str(row["content"]),
                            ),
                            row,
                        )
                    )
                ranked_passages.sort(key=lambda item: (-item[0], str(item[1]["chunk_id"])))
                passages = [
                    GroundedPassage(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        concept_id=row["concept_id"],
                        facet=row["facet"],
                        content=row["content"],
                        source_kind=KnowledgeSourceKind.SYNTHETIC_WIKI,
                        source_version=release_id,
                        score=round(score, 4),
                    )
                    for score, row in ranked_passages[:5]
                ]
            else:
                cursor.execute(
                    """
                    SELECT * FROM (
                      SELECT knowledge_id,knowledge_type,content,updated_at
                      FROM menu_knowledge WHERE menu_id=:menu_id ORDER BY knowledge_id
                    ) WHERE ROWNUM<=3
                    """,
                    menu_id=menu_id,
                )
                passages = [
                    GroundedPassage(
                        chunk_id=row["knowledge_id"],
                        document_id=row["knowledge_id"],
                        facet=row["knowledge_type"],
                        content=row["content"],
                        source_kind=KnowledgeSourceKind.LEGACY_MENU_KNOWLEDGE,
                        source_version=str(row["updated_at"]),
                        score=0.0,
                    )
                    for row in _rows(cursor)
                ]
            cursor.execute(
                """
                SELECT fact.*,da.code,da.display_name,
                       fact.evidence_id AS source_id,'catalog' AS source_version
                FROM menu_dietary_attribute fact
                JOIN dietary_attribute da ON da.attribute_id=fact.attribute_id
                WHERE fact.menu_id=:menu_id
                ORDER BY fact.attribute_id
                """,
                menu_id=menu_id,
            )
            menu_dietary_rows = _rows(cursor)
            dietary_claims = resolve_dietary_claims(wiki_dietary_rows, menu_dietary_rows)
            preparation_claims = resolve_preparation_claims(wiki_preparation_rows)
            cursor.execute(
                """
                SELECT declaration.raw_text,declaration.declaration_id
                FROM menu
                JOIN merchant_origin_declaration declaration
                  ON declaration.merchant_id=menu.merchant_id
                JOIN knowledge_runtime_state state
                  ON state.active_release_id=declaration.release_id
                WHERE menu.menu_id=:menu_id
                ORDER BY declaration.declaration_id
                """,
                menu_id=menu_id,
            )
            origin_rows = _rows(cursor)
            cursor.execute(
                """
                SELECT fact.*,ingredient.name_en,ingredient.name_ko,declaration.source_version
                FROM menu
                JOIN knowledge_runtime_state state ON state.state_key='ACTIVE'
                JOIN merchant_ingredient fact
                  ON fact.release_id=state.active_release_id
                 AND fact.merchant_id=menu.merchant_id
                JOIN merchant_origin_declaration declaration
                  ON declaration.release_id=fact.release_id
                 AND declaration.declaration_id=fact.declaration_id
                JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
                WHERE menu.menu_id=:menu_id
                ORDER BY fact.ingredient_id,fact.declaration_id
                """,
                menu_id=menu_id,
            )
            merchant_claims = resolve_merchant_ingredient_claims(
                [
                    {
                        **row,
                        "source_id": f"{row['declaration_id']}:{row['ingredient_id']}",
                    }
                    for row in _rows(cursor)
                ]
            )
            cross_contact_unknowns = [
                (
                    f"{claim.code}: menu-specific absence is recorded, but cross-contact "
                    "is UNKNOWN; this is not a safety certification."
                )
                for claim in allergen_claims
                if claim.status is ClaimStatus.CONFIRMED_ABSENT
                and claim.cross_contamination_status == "UNKNOWN"
            ]
        return GroundedMenuKnowledge(
            menu_id=menu_id,
            release_id=release_id,
            concept_id=concept_id,
            concept_lineage=concept_lineage,
            available_facets=available_facets,
            ingredient_claims=ingredient_claims,
            allergen_claims=allergen_claims,
            dietary_claims=dietary_claims,
            preparation_claims=preparation_claims,
            merchant_ingredient_claims=merchant_claims,
            passages=passages,
            merchant_origin_notes=[str(row["raw_text"]) for row in origin_rows],
            unknowns=[
                "Merchant-specific recipe differences are unknown unless a menu fact overrides the Wiki.",
                "Shared-kitchen cross-contact is not confirmed by the synthetic Wiki or origin declaration.",
                *cross_contact_unknowns,
            ],
        )

    def compare_merchants(
        self,
        category: str,
        profile: Profile,
        limit: int = 3,
        meal_need_state: MealNeedState | None = None,
    ) -> list[MerchantComparison]:
        state = apply_profile_constraints(
            meal_need_state.model_copy(deep=True)
            if meal_need_state is not None
            else MealNeedState(max_spiciness=profile.spice_tolerance),
            profile.dietary_rules,
            profile.religion_selection,
        )
        if state.max_spiciness is None:
            state.max_spiciness = profile.spice_tolerance
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name, r.delivery_fee, r.eta_min,
                  r.eta_max, r.flavor_profile, r.packaging_signal,
                  r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE LOWER(m.category)=LOWER(:category) AND m.availability='AVAILABLE'
                ORDER BY m.price, r.eta_min
                """,
                category=category,
            )
            rows = _rows(cursor)
            hard_conflicts = {
                str(row["menu_id"]): self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    state,
                    profile.allergy_severity,
                )[0]
                for row in rows
            }
        summaries: list[MenuSummary] = []
        merchant_areas: dict[str, str] = {}
        rows_by_menu = {str(row["menu_id"]): row for row in rows}
        for index, row in enumerate(rows):
            if hard_conflicts[str(row["menu_id"])]:
                continue
            allergens = set(_json(row["allergen_tags_json"]))
            tags = set(_json(row["dietary_tags_json"]))
            status = EvidenceStatus.UNKNOWN
            if "shellfish_risk" in allergens:
                status = EvidenceStatus.RISK_SIGNAL
            elif "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
            summary = self._menu_summary(
                row,
                ["Comparable listing for the requested food"],
                ["Cross-contamination is not verified"],
                status,
                max(0.1, 0.6 - index * 0.001),
            )
            summaries.append(summary)
            merchant_areas[summary.merchant_id] = str(row["merchant_service_area_id"])
        ranked = rerank_menu_candidates(summaries, state, merchant_areas, limit)
        result: list[MerchantComparison] = []
        for menu in ranked:
            row = rows_by_menu[menu.menu_id]
            dietary_note = "Ingredient and cross-contamination details are not verified."
            if menu.evidence_status == EvidenceStatus.RISK_SIGNAL:
                dietary_note = "The synthetic menu specification contains a shellfish risk signal."
            elif menu.evidence_status == EvidenceStatus.VERIFIED:
                dietary_note = "Sauce marked seafood-free; cross-contamination remains unknown."
            result.append(
                MerchantComparison(
                    merchant_id=menu.merchant_id,
                    merchant_name=menu.merchant_name,
                    menu_id=menu.menu_id,
                    menu_name=menu.name_en,
                    price=menu.price,
                    delivery_fee=menu.delivery_fee,
                    eta=f"{int(row['eta_min'])}-{int(row['eta_max'])} min",
                    portion=(
                        "Portion information not provided"
                        if menu.serves_max is None
                        else "One-person portion"
                        if menu.serves_max == 1
                        else "Shareable portion"
                    ),
                    flavor=row["flavor_profile"],
                    packaging_signal=row["packaging_signal"],
                    dietary_status=menu.evidence_status,
                    dietary_note=dietary_note,
                    best_for="; ".join(menu.match_reasons),
                    evidence_ids=[
                        evidence.evidence_id for evidence in self.get_evidence(menu.menu_id)
                    ],
                )
            )
        return result

    def get_options(self, menu_id: str, session_id: str | None = None) -> list[OptionGroup]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            language_code = "en"
            if session_id:
                cursor.execute(
                    """
                    SELECT profile.preferred_language FROM chat_session session
                    JOIN user_profile profile ON profile.profile_id=session.profile_id
                    WHERE session.session_id=:session_id
                    """,
                    session_id=session_id,
                )
                language_row = cursor.fetchone()
                if language_row:
                    requested = normalize_preference_locale(str(language_row[0]))
                    language_code = requested if requested in {"ko", "ja"} else "en"
            cursor.execute(
                """
                SELECT family.knowledge_release_id,family.certification_release_id,
                       family.synthetic_enrichment_release_id
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                JOIN knowledge_release release
                  ON release.release_id=family.knowledge_release_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                  AND release.status='READY'
                """
            )
            family = _row(cursor)
            base_vegan_status: str | None = None
            base_vegan_warning: str | None = None
            halal_certification_preserved: bool | None = None
            option_effects: dict[str, list[dict[str, Any]]] = defaultdict(list)
            synthetic_option_states: dict[str, tuple[bool, bool]] = {}
            if family is not None:
                base_vegan_status, base_vegan_warning, _ = self._v2_vegan_classifications(
                    connection,
                    [menu_id],
                    str(family["knowledge_release_id"]),
                ).get(menu_id, ("UNKNOWN", None, []))
                valid_certifications = self._valid_halal_certifications_in_connection(
                    connection,
                    instant=_now(),
                    certification_release_id=str(family["certification_release_id"]),
                )
                if menu_id in valid_certifications:
                    halal_certification_preserved = True
                cursor.execute(
                    """
                    SELECT effect.option_item_id,effect.ingredient_id,
                           effect.effect,effect.assertion_status
                    FROM option_ingredient_effect effect
                    JOIN menu_option_item item
                      ON item.option_item_id=effect.option_item_id
                    JOIN menu_option_group option_group
                      ON option_group.option_group_id=item.option_group_id
                    WHERE option_group.menu_id=:menu_id AND effect.release_id=:release_id
                    """,
                    menu_id=menu_id,
                    release_id=str(family["knowledge_release_id"]),
                )
                for effect in _rows(cursor):
                    option_effects[str(effect["option_item_id"])].append(effect)
                if family.get("synthetic_enrichment_release_id"):
                    synthetic_release_id = str(family["synthetic_enrichment_release_id"])
                    cursor.execute(
                        """
                        SELECT halal_fit,vegan_fit FROM synthetic_menu_profile
                        WHERE release_id=:release_id AND menu_id=:menu_id
                        """,
                        release_id=synthetic_release_id,
                        menu_id=menu_id,
                    )
                    menu_profile = cursor.fetchone()
                    if menu_profile is not None:
                        halal_certification_preserved = bool(menu_profile[0])
                        base_vegan_status = "LIKELY_FIT" if menu_profile[1] else "CONFLICT"
                        base_vegan_warning = (
                            None
                            if menu_profile[1]
                            else "This menu is not marked as vegan-friendly."
                        )
                    cursor.execute(
                        """
                        SELECT profile.option_item_id,profile.halal_conflict,
                               profile.vegan_conflict
                        FROM synthetic_option_profile profile
                        JOIN menu_option_item item
                          ON item.option_item_id=profile.option_item_id
                        JOIN menu_option_group groups
                          ON groups.option_group_id=item.option_group_id
                        WHERE profile.release_id=:release_id AND groups.menu_id=:menu_id
                        """,
                        release_id=synthetic_release_id,
                        menu_id=menu_id,
                    )
                    synthetic_option_states = {
                        str(row["option_item_id"]): (
                            bool(row["halal_conflict"]),
                            bool(row["vegan_conflict"]),
                        )
                        for row in _rows(cursor)
                    }

            def v2_option_state(item_id: str) -> tuple[str | None, str | None]:
                synthetic_state = synthetic_option_states.get(item_id)
                if synthetic_state is not None:
                    return (
                        ("CONFLICT", "This option is not marked as vegan-friendly.")
                        if synthetic_state[1]
                        else (base_vegan_status, base_vegan_warning)
                    )
                animal_adds = [
                    effect
                    for effect in option_effects.get(item_id, [])
                    if str(effect["effect"]).upper() == "ADD"
                    and str(effect["ingredient_id"]) in VEGAN_INGREDIENTS
                ]
                if any(
                    str(effect["assertion_status"]).upper()
                    in {"CONFIRMED_PRESENT", "PRESENT", "VERIFIED"}
                    for effect in animal_adds
                ):
                    return (
                        "CONFLICT",
                        "This option adds a confirmed animal-derived ingredient and does not fit a vegan selection.",
                    )
                if any(
                    str(effect["assertion_status"]).upper() not in {"CONFIRMED_ABSENT", "ABSENT"}
                    for effect in animal_adds
                ):
                    return (
                        "POSSIBLE_WITH_CHECKS",
                        "This option may add an animal-derived ingredient; check before ordering vegan.",
                    )
                return base_vegan_status, base_vegan_warning

            cursor.execute(
                "SELECT * FROM menu_option_group WHERE menu_id=:id ORDER BY sort_order", id=menu_id
            )
            groups = _rows(cursor)
            group_localizations: dict[str, str] = {}
            item_localizations: dict[str, str] = {}
            if family is not None and family.get("synthetic_enrichment_release_id"):
                cursor.execute(
                    """
                    SELECT localization.option_group_id,localization.display_name
                    FROM option_group_localization localization
                    JOIN menu_option_group groups
                      ON groups.option_group_id=localization.option_group_id
                    WHERE localization.release_id=:release_id
                      AND localization.language_code=:language_code
                      AND groups.menu_id=:menu_id
                    """,
                    release_id=str(family["synthetic_enrichment_release_id"]),
                    language_code=language_code,
                    menu_id=menu_id,
                )
                group_localizations = {
                    str(row["option_group_id"]): str(row["display_name"])
                    for row in _rows(cursor)
                }
                cursor.execute(
                    """
                    SELECT localization.option_item_id,localization.display_name
                    FROM option_item_localization localization
                    JOIN menu_option_item item
                      ON item.option_item_id=localization.option_item_id
                    JOIN menu_option_group groups
                      ON groups.option_group_id=item.option_group_id
                    WHERE localization.release_id=:release_id
                      AND localization.language_code=:language_code
                      AND groups.menu_id=:menu_id
                    """,
                    release_id=str(family["synthetic_enrichment_release_id"]),
                    language_code=language_code,
                    menu_id=menu_id,
                )
                item_localizations = {
                    str(row["option_item_id"]): str(row["display_name"])
                    for row in _rows(cursor)
                }
            result = []
            for group in groups:
                cursor.execute(
                    """
                    SELECT i.*, (
                      SELECT LISTAGG(odc.rule_code, ',') WITHIN GROUP (ORDER BY odc.rule_code)
                      FROM option_dietary_conflict odc
                      WHERE odc.option_item_id=i.option_item_id
                    ) AS conflicting_rules_csv
                    FROM menu_option_item i
                    WHERE i.option_group_id=:id ORDER BY i.sort_order
                    """,
                    id=group["option_group_id"],
                )
                items = _rows(cursor)
                v2_states = {
                    str(item["option_item_id"]): v2_option_state(str(item["option_item_id"]))
                    for item in items
                }
                result.append(
                    OptionGroup(
                        option_group_id=group["option_group_id"],
                        name_en=_catalog_text(group["name_en"], group["name_ko"]),
                        name_ko=group["name_ko"],
                        display_name=group_localizations.get(
                            str(group["option_group_id"]),
                            str(group["name_ko"])
                            if language_code == "ko"
                            else _catalog_text(group["name_en"], group["name_ko"]),
                        ),
                        description=_catalog_text(group["description"]),
                        required=bool(group["required"]),
                        min_select=int(group["min_select"]),
                        max_select=int(group["max_select"]),
                        items=[
                            OptionItem(
                                option_item_id=item["option_item_id"],
                                name_en=_catalog_text(item["name_en"], item["name_ko"]),
                                name_ko=item["name_ko"],
                                display_name=item_localizations.get(
                                    str(item["option_item_id"]),
                                    str(item["name_ko"])
                                    if language_code == "ko"
                                    else _catalog_text(item["name_en"], item["name_ko"]),
                                ),
                                description=_catalog_text(item["description"]),
                                price_delta=int(item["price_delta"]),
                                available=item["availability"] == "AVAILABLE",
                                dietary_conflict=item["dietary_conflict"],
                                conflicting_rules=(
                                    str(item["conflicting_rules_csv"]).split(",")
                                    if item["conflicting_rules_csv"]
                                    else []
                                ),
                                halal_certification_preserved=(
                                    False
                                    if synthetic_option_states.get(
                                        str(item["option_item_id"]), (False, False)
                                    )[0]
                                    else halal_certification_preserved
                                ),
                                vegan_status=cast(
                                    Any,
                                    v2_states[str(item["option_item_id"])][0],
                                ),
                                vegan_warning=v2_states[str(item["option_item_id"])][1],
                            )
                            for item in items
                        ],
                    )
                )
        return result

    def option_localizations_complete(
        self,
        session_id: str,
        menu_id: str,
        group_ids: list[str],
        item_ids: list[str],
    ) -> bool:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT profile.preferred_language,family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=:session_id
                """,
                session_id=session_id,
            )
            context = _row(cursor)
            if context is None or not context.get("synthetic_enrichment_release_id"):
                return False
            requested = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested if requested in {"ko", "ja"} else "en"
            cursor.execute(
                """
                SELECT localization.option_group_id
                FROM option_group_localization localization
                JOIN menu_option_group groups
                  ON groups.option_group_id=localization.option_group_id
                WHERE localization.release_id=:release_id
                  AND localization.language_code=:language_code
                  AND groups.menu_id=:menu_id
                """,
                release_id=str(context["synthetic_enrichment_release_id"]),
                language_code=language_code,
                menu_id=menu_id,
            )
            localized_groups = {str(row[0]) for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT localization.option_item_id
                FROM option_item_localization localization
                JOIN menu_option_item item
                  ON item.option_item_id=localization.option_item_id
                JOIN menu_option_group groups
                  ON groups.option_group_id=item.option_group_id
                WHERE localization.release_id=:release_id
                  AND localization.language_code=:language_code
                  AND groups.menu_id=:menu_id
                """,
                release_id=str(context["synthetic_enrichment_release_id"]),
                language_code=language_code,
                menu_id=menu_id,
            )
            localized_items = {str(row[0]) for row in cursor.fetchall()}
        return localized_groups == set(group_ids) and localized_items == set(item_ids)

    def save_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        group_names: dict[str, str],
        item_names: dict[str, str],
        model_id: str,
    ) -> None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT profile.preferred_language,family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=:session_id
                """,
                session_id=session_id,
            )
            context = _row(cursor)
            if context is None or not context.get("synthetic_enrichment_release_id"):
                raise RuntimeError("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            requested = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested if requested in {"ko", "ja"} else "en"
            cursor.execute(
                """
                SELECT option_group_id,name_en,name_ko FROM menu_option_group
                WHERE menu_id=:menu_id
                """,
                menu_id=menu_id,
            )
            group_rows = _rows(cursor)
            cursor.execute(
                """
                SELECT item.option_item_id,item.name_en,item.name_ko
                FROM menu_option_item item
                JOIN menu_option_group groups
                  ON groups.option_group_id=item.option_group_id
                WHERE groups.menu_id=:menu_id
                """,
                menu_id=menu_id,
            )
            item_rows = _rows(cursor)
            if {str(row["option_group_id"]) for row in group_rows} != set(group_names):
                raise ValueError("OPTION_LOCALIZATION_GROUP_IDS_MISMATCH")
            if {str(row["option_item_id"]) for row in item_rows} != set(item_names):
                raise ValueError("OPTION_LOCALIZATION_ITEM_IDS_MISMATCH")
            release_id = str(context["synthetic_enrichment_release_id"])
            generated_at = _now()
            for row in group_rows:
                source_hash = hashlib.sha256(
                    json.dumps(
                        [row.get("name_ko"), row.get("name_en"), language_code],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                cursor.execute(
                    """
                    MERGE INTO option_group_localization target
                    USING (
                      SELECT :release_id release_id,:object_id option_group_id,
                             :language_code language_code FROM dual
                    ) source
                    ON (target.release_id=source.release_id
                        AND target.option_group_id=source.option_group_id
                        AND target.language_code=source.language_code)
                    WHEN MATCHED THEN UPDATE SET
                      display_name=:display_name,model_id=:model_id,
                      source_hash=:source_hash,generated_at=:generated_at
                    WHEN NOT MATCHED THEN INSERT (
                      release_id,option_group_id,language_code,display_name,
                      model_id,source_hash,generated_at
                    ) VALUES (
                      :release_id,:object_id,:language_code,:display_name,
                      :model_id,:source_hash,:generated_at
                    )
                    """,
                    release_id=release_id,
                    object_id=row["option_group_id"],
                    language_code=language_code,
                    display_name=group_names[str(row["option_group_id"])],
                    model_id=model_id,
                    source_hash=source_hash,
                    generated_at=generated_at,
                )
            for row in item_rows:
                source_hash = hashlib.sha256(
                    json.dumps(
                        [row.get("name_ko"), row.get("name_en"), language_code],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                cursor.execute(
                    """
                    MERGE INTO option_item_localization target
                    USING (
                      SELECT :release_id release_id,:object_id option_item_id,
                             :language_code language_code FROM dual
                    ) source
                    ON (target.release_id=source.release_id
                        AND target.option_item_id=source.option_item_id
                        AND target.language_code=source.language_code)
                    WHEN MATCHED THEN UPDATE SET
                      display_name=:display_name,model_id=:model_id,
                      source_hash=:source_hash,generated_at=:generated_at
                    WHEN NOT MATCHED THEN INSERT (
                      release_id,option_item_id,language_code,display_name,
                      model_id,source_hash,generated_at
                    ) VALUES (
                      :release_id,:object_id,:language_code,:display_name,
                      :model_id,:source_hash,:generated_at
                    )
                    """,
                    release_id=release_id,
                    object_id=row["option_item_id"],
                    language_code=language_code,
                    display_name=item_names[str(row["option_item_id"])],
                    model_id=model_id,
                    source_hash=source_hash,
                    generated_at=generated_at,
                )

    def resolve_address(self, text: str, file_hash: str | None = None) -> list[AddressCandidate]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT place.* FROM address_place place
                JOIN service_area area ON area.service_area_id=place.service_area_id
                WHERE area.active=1 ORDER BY place.place_id
                """
            )
            rows = _rows(cursor)
        normalized = normalize_address_text(text)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            aliases = _json(row["aliases_json"])
            haystack = " ".join([row["name_en"], row["name_ko"], *aliases]).lower()
            normalized_road = normalize_address_text(str(row["road_address"]))
            score = (
                0.98 if row["place_id"] == "hotel_demo_01" and "myeongdong" in normalized else 0.0
            )
            if normalized_road in normalized:
                score = max(score, 0.95)
            if normalized and any(token in haystack for token in normalized.split()):
                score = max(score, 0.82)
            if file_hash and row["fixture_sha256"] == file_hash:
                score = 1.0
            if score:
                scored.append((score, row))
        if not scored and rows:
            scored = [(0.35, rows[0])]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            AddressCandidate(
                place_id=row["place_id"],
                hotel_name=row["name_en"],
                road_address=row["road_address"],
                postal_code=row["postal_code"],
                city=row["city"],
                service_area_id=row.get("service_area_id"),
                delivery_hint=row["delivery_hint"],
                confidence=score,
                source="canonical_fixture" if score >= 0.98 else "manual",
                needs_confirmation=True,
            )
            for score, row in scored[:3]
        ]

    def get_address_candidate(self, place_id: str) -> AddressCandidate | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT place.* FROM address_place place
                JOIN service_area area ON area.service_area_id=place.service_area_id
                WHERE place.place_id=:id AND area.active=1
                """,
                id=place_id,
            )
            row = _row(cursor)
        if row is None:
            return None
        return AddressCandidate(
            place_id=row["place_id"],
            hotel_name=row["name_en"],
            road_address=row["road_address"],
            postal_code=row["postal_code"],
            city=row["city"],
            service_area_id=row.get("service_area_id"),
            delivery_hint=row["delivery_hint"],
            confidence=1.0,
            source="canonical_fixture",
            needs_confirmation=True,
        )

    def save_address(
        self,
        session_id: str,
        candidate: AddressCandidate,
        source_image_hash: str | None = None,
    ) -> str:
        address_ref_id = _id("address")
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT 1 FROM service_area
                WHERE service_area_id=:id AND active=1
                FOR UPDATE OF active
                """,
                id=candidate.service_area_id,
            )
            if cursor.fetchone() is None:
                raise ValueError("ADDRESS_OUTSIDE_SERVICE_AREA")
            cursor.execute(
                """
                INSERT INTO address_ref(address_ref_id,session_id,source_type,source_image_hash,
                  place_id,hotel_name,road_address,extraction_confidence,service_area_id,
                  confirmed,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,1,:10)
                """,
                [
                    address_ref_id,
                    session_id,
                    candidate.source,
                    source_image_hash,
                    candidate.place_id if candidate.place_id != "manual" else None,
                    candidate.hotel_name,
                    candidate.road_address,
                    candidate.confidence,
                    candidate.service_area_id,
                    _now(),
                ],
            )
            cart_id = self._ensure_cart(connection, session_id)
            cursor.execute(
                """
                UPDATE cart SET address_ref_id=:address,version=version+1,
                  confirmed=0,updated_at=:now WHERE cart_id=:cart
                """,
                address=address_ref_id,
                now=_now(),
                cart=cart_id,
            )
        return address_ref_id

    def get_session_service_area(self, session_id: str) -> str | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT ref.service_area_id
                FROM cart JOIN address_ref ref ON ref.address_ref_id=cart.address_ref_id
                JOIN service_area area ON area.service_area_id=ref.service_area_id
                WHERE cart.session_id=:session_id AND ref.confirmed=1 AND area.active=1
                """,
                session_id=session_id,
            )
            row = cursor.fetchone()
        return str(row[0]) if row and row[0] else None

    @staticmethod
    def _ensure_cart(connection: oracledb.Connection, session_id: str) -> str:
        cursor = connection.cursor()
        cursor.execute("SELECT cart_id FROM cart WHERE session_id=:id", id=session_id)
        row = cursor.fetchone()
        if row:
            return row[0]
        cart_id = _id("cart")
        now = _now()
        cursor.execute(
            "INSERT INTO cart(cart_id,session_id,created_at,updated_at) VALUES (:1,:2,:3,:4)",
            [cart_id, session_id, now, now],
        )
        return cart_id

    @staticmethod
    def _cart_item_values(
        connection: oracledb.Connection, item: CartItemInput
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM menu WHERE menu_id=:id AND availability='AVAILABLE'", id=item.menu_id
        )
        menu = _row(cursor)
        if not menu:
            raise KeyError("MENU_NOT_FOUND")
        options: list[dict[str, Any]] = []
        selected_counts: dict[str, int] = {}
        option_total = 0
        for option_id in item.option_item_ids:
            cursor.execute(
                """
                SELECT i.*,g.menu_id FROM menu_option_item i
                JOIN menu_option_group g ON g.option_group_id=i.option_group_id
                WHERE i.option_item_id=:id AND i.availability='AVAILABLE'
                """,
                id=option_id,
            )
            option = _row(cursor)
            if not option or option["menu_id"] != item.menu_id:
                raise ValueError("INVALID_MENU_OPTION")
            group_id = str(option["option_group_id"])
            selected_counts[group_id] = selected_counts.get(group_id, 0) + 1
            options.append(
                {
                    "option_item_id": option["option_item_id"],
                    "name_en": _catalog_text(option["name_en"], option["name_ko"]),
                    "name_ko": option["name_ko"],
                    "price_delta": int(option["price_delta"]),
                }
            )
            option_total += int(option["price_delta"])
        cursor.execute(
            """
            SELECT option_group_id,min_select,max_select
            FROM menu_option_group WHERE menu_id=:id
            """,
            id=item.menu_id,
        )
        groups = _rows(cursor)
        if any(
            selected_counts.get(str(group["option_group_id"]), 0) < int(group["min_select"])
            for group in groups
        ):
            raise ValueError("REQUIRED_MENU_OPTION_MISSING")
        if any(
            selected_counts.get(str(group["option_group_id"]), 0) > int(group["max_select"])
            for group in groups
        ):
            raise ValueError("OPTION_GROUP_MAX_EXCEEDED")
        return menu, options, (int(menu["price"]) + option_total) * item.quantity

    @staticmethod
    def _validated_note_translation(
        connection: oracledb.Connection,
        session_id: str,
        item: CartItemInput,
    ) -> tuple[str, str | None]:
        if not item.user_note.strip():
            return "", None
        if not item.note_translation_id:
            raise ValueError("RESTAURANT_NOTE_TRANSLATION_REQUIRED")
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT korean_text,source_text,status
            FROM restaurant_note_translation
            WHERE translation_id=:translation_id AND session_id=:session_id
            """,
            translation_id=item.note_translation_id,
            session_id=session_id,
        )
        row = cursor.fetchone()
        if (
            row is None
            or str(row[2]) != "SUCCEEDED"
            or _oracle_logical_text(row[1]) != item.user_note
            or not row[0]
        ):
            raise ValueError("RESTAURANT_NOTE_TRANSLATION_REQUIRED")
        return _oracle_logical_text(row[0]), item.note_translation_id

    def add_cart_item(
        self,
        session_id: str,
        item: CartItemInput,
        agent_request_key: str | None = None,
    ) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT session_id FROM chat_session WHERE session_id=:id FOR UPDATE",
                id=session_id,
            )
            if cursor.fetchone() is None:
                raise KeyError("SESSION_NOT_FOUND")
            cart_id = self._ensure_cart(connection, session_id)
            if agent_request_key:
                cursor.execute(
                    """
                    SELECT menu_id,quantity,option_snapshot_json,user_note FROM cart_item
                    WHERE cart_id=:cart_id AND agent_request_key=:request_key AND ROWNUM=1
                    """,
                    cart_id=cart_id,
                    request_key=agent_request_key,
                )
                duplicate = _row(cursor)
                if duplicate:
                    stored_option_ids = sorted(
                        str(option["option_item_id"])
                        for option in _json(duplicate["option_snapshot_json"])
                    )
                    if (
                        str(duplicate["menu_id"]) != item.menu_id
                        or int(duplicate["quantity"]) != item.quantity
                        or stored_option_ids != sorted(item.option_item_ids)
                        or _oracle_logical_text(duplicate.get("user_note")) != item.user_note
                    ):
                        raise ValueError("IDEMPOTENCY_KEY_REUSED")
                    return self.get_cart(session_id)
            menu, options, line_total = self._cart_item_values(connection, item)
            korean_note, note_translation_id = self._validated_note_translation(
                connection, session_id, item
            )
            cursor.execute(
                """
                SELECT 1 FROM cart_item WHERE cart_id=:cart_id AND merchant_id<>:merchant_id
                  AND ROWNUM=1
                """,
                cart_id=cart_id,
                merchant_id=menu["merchant_id"],
            )
            if cursor.fetchone():
                raise ValueError("CART_MULTIPLE_MERCHANTS")
            cursor.execute(
                """
                INSERT INTO cart_item(cart_item_id,cart_id,menu_id,merchant_id,quantity,unit_price,
                  menu_snapshot_json,option_snapshot_json,line_total,user_note,korean_note,
                  note_translation_id,agent_request_key,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13,:14)
                """,
                [
                    _id("cartitem"),
                    cart_id,
                    menu["menu_id"],
                    menu["merchant_id"],
                    item.quantity,
                    int(menu["price"]),
                    json.dumps(
                        {
                            "name_en": _catalog_text(menu["name_en"], menu["name_ko"]),
                            "price": int(menu["price"]),
                        }
                    ),
                    json.dumps(options),
                    line_total,
                    _oracle_required_text(item.user_note),
                    korean_note,
                    note_translation_id,
                    agent_request_key,
                    _now(),
                ],
            )
            cursor.execute(
                "UPDATE cart SET version=version+1,confirmed=0,updated_at=:now WHERE cart_id=:id",
                now=_now(),
                id=cart_id,
            )
        return self.get_cart(session_id)

    def update_cart_item(
        self, session_id: str, cart_item_id: str, item: CartItemUpdate
    ) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT ci.* FROM cart_item ci JOIN cart c ON c.cart_id=ci.cart_id
                WHERE ci.cart_item_id=:cart_item_id AND c.session_id=:session_id
                FOR UPDATE
                """,
                cart_item_id=cart_item_id,
                session_id=session_id,
            )
            existing = _row(cursor)
            if existing is None:
                raise KeyError("CART_ITEM_NOT_FOUND")
            current_options = _json(existing["option_snapshot_json"])
            replacement = CartItemInput(
                menu_id=existing["menu_id"],
                quantity=item.quantity if item.quantity is not None else int(existing["quantity"]),
                option_item_ids=(
                    item.option_item_ids
                    if item.option_item_ids is not None
                    else [str(option["option_item_id"]) for option in current_options]
                ),
                user_note=(
                    item.user_note
                    if item.user_note is not None
                    else _oracle_logical_text(existing["user_note"])
                ),
                note_translation_id=(
                    item.note_translation_id
                    if item.note_translation_id is not None
                    else existing.get("note_translation_id")
                ),
            )
            menu, options, line_total = self._cart_item_values(connection, replacement)
            korean_note, note_translation_id = self._validated_note_translation(
                connection, session_id, replacement
            )
            cursor.execute(
                """
                UPDATE cart_item SET quantity=:quantity,unit_price=:unit_price,
                  menu_snapshot_json=:menu_snapshot,option_snapshot_json=:option_snapshot,
                  line_total=:line_total,user_note=:user_note,korean_note=:korean_note,
                  note_translation_id=:note_translation_id
                WHERE cart_item_id=:cart_item_id
                """,
                quantity=replacement.quantity,
                unit_price=int(menu["price"]),
                menu_snapshot=json.dumps(
                    {
                        "name_en": _catalog_text(menu["name_en"], menu["name_ko"]),
                        "price": int(menu["price"]),
                    }
                ),
                option_snapshot=json.dumps(options),
                line_total=line_total,
                user_note=_oracle_required_text(replacement.user_note),
                korean_note=korean_note,
                note_translation_id=note_translation_id,
                cart_item_id=cart_item_id,
            )
            cursor.execute(
                """
                UPDATE cart SET version=version+1,confirmed=0,updated_at=:now WHERE cart_id=:id
                """,
                now=_now(),
                id=existing["cart_id"],
            )
        return self.get_cart(session_id)

    def delete_cart_item(self, session_id: str, cart_item_id: str) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT ci.cart_id FROM cart_item ci JOIN cart c ON c.cart_id=ci.cart_id
                WHERE ci.cart_item_id=:cart_item_id AND c.session_id=:session_id
                FOR UPDATE
                """,
                cart_item_id=cart_item_id,
                session_id=session_id,
            )
            existing = cursor.fetchone()
            if existing is None:
                raise KeyError("CART_ITEM_NOT_FOUND")
            cursor.execute("DELETE FROM cart_item WHERE cart_item_id=:id", id=cart_item_id)
            cursor.execute(
                """
                UPDATE cart SET version=version+1,confirmed=0,updated_at=:now WHERE cart_id=:id
                """,
                now=_now(),
                id=existing[0],
            )
        return self.get_cart(session_id)

    @staticmethod
    def _translate_note(note: str) -> str:
        lowered = note.lower()
        translations = []
        if "mild" in lowered or "not spicy" in lowered:
            translations.append("최대한 맵지 않게 부탁드립니다.")
        if "front desk" in lowered:
            translations.append("호텔 프런트에 맡겨 주세요.")
        if "no cutlery" in lowered or "no disposable" in lowered:
            translations.append("일회용 수저와 포크는 필요 없습니다.")
        return " ".join(translations) or "요청사항을 확인해 주세요."

    def get_cart(self, session_id: str) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM cart WHERE session_id=:id", id=session_id)
            cart = _row(cursor)
            if not cart:
                cart_id = self._ensure_cart(connection, session_id)
                cursor.execute("SELECT * FROM cart WHERE cart_id=:id", id=cart_id)
                cart = _row(cursor)
            if cart is None:
                raise RuntimeError("CART_CREATION_FAILED")
            cursor.execute(
                """
                SELECT ci.*,
                  COALESCE(m.name_en,m.name_ko,m.menu_id) AS menu_name,
                  COALESCE(m.name_ko,m.name_en,m.menu_id) AS menu_name_ko,
                  m.allergen_tags_json
                FROM cart_item ci
                JOIN menu m ON m.menu_id=ci.menu_id WHERE ci.cart_id=:id ORDER BY ci.created_at
                """,
                id=cart["cart_id"],
            )
            rows = _rows(cursor)
            cursor.execute(
                """
                SELECT NVL(MAX(r.delivery_fee),0) FROM cart_item ci
                JOIN merchant r ON r.merchant_id=ci.merchant_id WHERE ci.cart_id=:id
                """,
                id=cart["cart_id"],
            )
            delivery_fee = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT 1 FROM delivery_preference WHERE cart_id=:id", id=cart["cart_id"]
            )
            has_delivery = cursor.fetchone() is not None
            cursor.execute(
                """
                SELECT p.dietary_rules_json, p.allergy_severity,
                       p.religion_selection, p.country_code,p.preferred_language,
                       s.meal_need_state_json
                FROM chat_session s JOIN user_profile p ON p.profile_id=s.profile_id
                WHERE s.session_id=:id
                """,
                id=session_id,
            )
            profile_row = _row(cursor)
            cursor.execute(
                """
                SELECT criteria_json,release_family_id,knowledge_release_id,
                       certification_release_id,synthetic_enrichment_release_id FROM (
                    SELECT criteria.criteria_json,family.release_family_id,
                           family.knowledge_release_id,family.certification_release_id,
                           family.synthetic_enrichment_release_id
                  FROM recommendation_snapshot snapshot
                  JOIN session_recommendation_criteria criteria
                    ON criteria.session_id=snapshot.session_id
                   AND criteria.criteria_version=snapshot.criteria_version
                  JOIN recommendation_release_family family
                    ON family.release_family_id=snapshot.recommendation_release_family_id
                  WHERE snapshot.session_id=:session_id
                    AND snapshot.structured_request_id IS NOT NULL
                  ORDER BY snapshot.created_at DESC,snapshot.snapshot_id DESC
                ) WHERE ROWNUM=1
                """,
                session_id=session_id,
            )
            structured_criteria_row = cursor.fetchone()
            structured_criteria = (
                RecommendationCriteriaV2.model_validate(_json(structured_criteria_row[0]))
                if structured_criteria_row is not None
                else None
            )
            merchant_ids = {str(row["merchant_id"]) for row in rows}
            minimum_order_amount = 0
            if len(merchant_ids) == 1:
                cursor.execute(
                    "SELECT min_order_amount FROM merchant WHERE merchant_id=:id",
                    id=next(iter(merchant_ids)),
                )
                minimum_row = _row(cursor)
                minimum_order_amount = int(minimum_row["min_order_amount"]) if minimum_row else 0
            dietary_conflicts: list[str] = []
            blocking_dietary_conflicts: list[str] = []
            service_area_conflict = False
            address_service_area = ""
            if cart.get("address_ref_id"):
                cursor.execute(
                    """
                    SELECT ref.service_area_id FROM address_ref ref
                    JOIN service_area area ON area.service_area_id=ref.service_area_id
                    WHERE ref.address_ref_id=:address_ref_id AND ref.session_id=:session_id
                      AND ref.confirmed=1 AND area.active=1
                    """,
                    address_ref_id=cart["address_ref_id"],
                    session_id=session_id,
                )
                address_area_row = cursor.fetchone()
                if address_area_row:
                    address_service_area = str(address_area_row[0] or "")
            if profile_row and rows and structured_criteria is None:
                dietary_rules = set(_json(profile_row["dietary_rules_json"]))
                need_state = apply_profile_constraints(
                    MealNeedState.model_validate(
                        _json(profile_row["meal_need_state_json"] or "{}")
                    ),
                    list(dietary_rules),
                    str(profile_row["religion_selection"]),
                )
                severe_shellfish = (
                    "shellfish_allergy" in dietary_rules
                    and profile_row["allergy_severity"] == "severe"
                )
                vegan_required = "vegan" in dietary_rules
                for row in rows:
                    if vegan_required:
                        cursor.execute(
                            """
                            SELECT 1 FROM menu_dietary_attribute mda
                            JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                            WHERE mda.menu_id=:id AND da.code='vegan_option' AND mda.status='VERIFIED'
                            """,
                            id=row["menu_id"],
                        )
                        if cursor.fetchone() is None:
                            dietary_conflicts.append(
                                f"Remove {row['menu_name']} to continue; vegan status is not verified."
                            )
                    if severe_shellfish:
                        for option in _json(row["option_snapshot_json"]):
                            cursor.execute(
                                """
                                SELECT 1 FROM option_dietary_conflict
                                WHERE option_item_id=:id AND rule_code='shellfish_allergy'
                                """,
                                id=option["option_item_id"],
                            )
                            if cursor.fetchone() is not None:
                                dietary_conflicts.append(f"Remove {option['name_en']} to continue.")
                    selected_ids = [
                        str(option["option_item_id"])
                        for option in _json(row["option_snapshot_json"])
                    ]
                    hard_conflicts, _ = self._menu_hard_constraint_conflicts(
                        connection,
                        str(row["menu_id"]),
                        need_state,
                        str(profile_row["allergy_severity"]),
                        selected_ids,
                    )
                    if hard_conflicts:
                        dietary_conflicts.append(
                            f"Remove {row['menu_name']} to continue; it conflicts with current "
                            "meal constraints or grounded safety facts."
                        )
            elif (
                structured_criteria is not None
                and structured_criteria_row is not None
                and structured_criteria.schema_version == "3"
            ):
                synthetic_release_id = str(structured_criteria_row[4] or "")
                if not synthetic_release_id:
                    blocking_dietary_conflicts.append(
                        "The active menu profile is unavailable. Refresh the recommendation."
                    )
                else:
                    country_code = structured_criteria.spice_reference_country
                    cursor.execute(
                        """
                        SELECT spice_baseline FROM synthetic_country_profile
                        WHERE release_id=:release_id AND country_code=:country_code
                        """,
                        release_id=synthetic_release_id,
                        country_code=country_code,
                    )
                    baseline_row = cursor.fetchone()
                    spice_baseline = int(baseline_row[0]) if baseline_row else 3
                    price_range = structured_criteria.price_range_krw
                    for row in rows:
                        menu_id = str(row["menu_id"])
                        cursor.execute(
                            """
                            SELECT spice_level,halal_fit,vegan_fit
                            FROM synthetic_menu_profile
                            WHERE release_id=:release_id AND menu_id=:menu_id
                            """,
                            release_id=synthetic_release_id,
                            menu_id=menu_id,
                        )
                        profile = cursor.fetchone()
                        cursor.execute("SELECT price FROM menu WHERE menu_id=:menu_id", menu_id=menu_id)
                        current_menu = cursor.fetchone()
                        conflict = profile is None or current_menu is None
                        if price_range and current_menu is not None:
                            price = int(current_menu[0])
                            conflict = conflict or not (price_range.min <= price <= price_range.max)
                        if profile is not None:
                            spice = int(profile[0])
                            preference = structured_criteria.spice_preference or "SIMILAR"
                            spice_matches = (
                                spice < spice_baseline
                                if preference == "LESS"
                                else spice > spice_baseline
                                if preference == "MORE"
                                else spice == spice_baseline
                            )
                            conflict = conflict or not spice_matches
                            conflict = conflict or bool(
                                structured_criteria.dietary_filters.halal_certified_only
                                and not profile[1]
                            )
                            conflict = conflict or bool(
                                structured_criteria.dietary_filters.vegan and not profile[2]
                            )
                        selected_ids = [
                            str(option["option_item_id"])
                            for option in _json(row["option_snapshot_json"])
                        ]
                        if selected_ids:
                            bind_names = [f"synthetic_option_{index}" for index in range(len(selected_ids))]
                            binds: dict[str, Any] = {"release_id": synthetic_release_id}
                            binds.update(dict(zip(bind_names, selected_ids)))
                            cursor.execute(
                                f"""
                                SELECT halal_conflict,vegan_conflict
                                FROM synthetic_option_profile
                                WHERE release_id=:release_id AND option_item_id IN (
                                  {','.join(':' + name for name in bind_names)}
                                )
                                """,
                                binds,
                            )
                            conflict = conflict or any(
                                structured_criteria.dietary_filters.halal_certified_only
                                and option[0]
                                or structured_criteria.dietary_filters.vegan
                                and option[1]
                                for option in cursor.fetchall()
                            )
                        if conflict:
                            warning = (
                                f"Remove {row['menu_name']} to continue; it no longer matches "
                                "your saved price, spice, or dietary choices."
                            )
                            dietary_conflicts.append(warning)
                            blocking_dietary_conflicts.append(warning)
            elif structured_criteria is not None and structured_criteria_row is not None:
                menu_ids = [str(row["menu_id"]) for row in rows]
                valid_certifications = self._valid_halal_certifications_in_connection(
                    connection,
                    instant=_now(),
                    certification_release_id=str(structured_criteria_row[3]),
                )
                vegan = self._v2_vegan_classifications(
                    connection,
                    menu_ids,
                    str(structured_criteria_row[2]),
                )
                for row in rows:
                    menu_id = str(row["menu_id"])
                    menu_name = str(row["menu_name"])
                    if (
                        structured_criteria.dietary_filters.halal_certified_only
                        and menu_id not in valid_certifications
                    ):
                        warning = f"Remove {menu_name} to continue; its halal certification is no longer valid."
                        dietary_conflicts.append(warning)
                        blocking_dietary_conflicts.append(warning)
                    cursor.execute(
                        "SELECT price,spice_level FROM menu WHERE menu_id=:menu_id",
                        menu_id=menu_id,
                    )
                    current_menu = cursor.fetchone()
                    if not self._price_matches_v2(
                        int(current_menu[0]) if current_menu else -1,
                        structured_criteria.price_bands,
                    ):
                        warning = (
                            f"{menu_name}'s current price is outside your selected range; "
                            "review the updated total before checkout."
                        )
                        dietary_conflicts.append(warning)
                    if current_menu is None or (
                        current_menu[1] is not None
                        and int(current_menu[1]) > structured_criteria.max_spice_level
                    ):
                        warning = f"Remove {menu_name} to continue; its spice level no longer matches your selection."
                        dietary_conflicts.append(warning)
                        blocking_dietary_conflicts.append(warning)
                    if structured_criteria.dietary_filters.vegan:
                        vegan_status, vegan_warning, _ = vegan.get(menu_id, ("UNKNOWN", None, []))
                        if vegan_status != "LIKELY_FIT":
                            dietary_conflicts.append(
                                vegan_warning
                                or f"Check {menu_name}'s ingredients before ordering it as vegan."
                            )
                        selected_ids = [
                            str(option["option_item_id"])
                            for option in _json(row["option_snapshot_json"])
                        ]
                        if selected_ids:
                            bind_names = [
                                f"cart_option_{index}" for index in range(len(selected_ids))
                            ]
                            option_binds: dict[str, Any] = {
                                "release_id": str(structured_criteria_row[2])
                            }
                            option_binds.update(dict(zip(bind_names, selected_ids)))
                            cursor.execute(
                                f"""
                                SELECT ingredient_id,effect,assertion_status
                                FROM option_ingredient_effect
                                WHERE release_id=:release_id
                                  AND option_item_id IN (
                                    {",".join(":" + name for name in bind_names)}
                                  )
                                """,
                                option_binds,
                            )
                            option_effects = _rows(cursor)
                            if any(
                                str(effect["effect"]).upper() == "ADD"
                                and str(effect["ingredient_id"]) in VEGAN_INGREDIENTS
                                and str(effect["assertion_status"]).upper()
                                not in {"CONFIRMED_ABSENT", "ABSENT"}
                                for effect in option_effects
                            ):
                                dietary_conflicts.append(
                                    f"A selected option for {menu_name} may add an animal-derived ingredient."
                                )
            for row in rows:
                cursor.execute(
                    "SELECT service_area_id FROM merchant WHERE merchant_id=:merchant_id",
                    merchant_id=row["merchant_id"],
                )
                merchant_area = cursor.fetchone()
                if (
                    not address_service_area
                    or merchant_area is None
                    or merchant_area[0] != address_service_area
                ):
                    service_area_conflict = True
            if structured_criteria is None:
                blocking_dietary_conflicts = list(dietary_conflicts)
            cart_menu_localizations: dict[str, str] = {}
            cart_option_localizations: dict[str, str] = {}
            synthetic_release_id = (
                str(structured_criteria_row[4] or "")
                if structured_criteria_row is not None
                else ""
            )
            if synthetic_release_id and profile_row is not None:
                requested_locale = normalize_preference_locale(
                    str(profile_row["preferred_language"])
                )
                language_code = requested_locale if requested_locale in {"ko", "ja"} else "en"
                cursor.execute(
                    """
                    SELECT menu_id,display_name FROM menu_localization
                    WHERE release_id=:release_id AND language_code=:language_code
                      AND validation_status='VALID'
                    """,
                    release_id=synthetic_release_id,
                    language_code=language_code,
                )
                cart_menu_localizations = {
                    str(item["menu_id"]): str(item["display_name"]) for item in _rows(cursor)
                }
                cursor.execute(
                    """
                    SELECT option_item_id,display_name FROM option_item_localization
                    WHERE release_id=:release_id AND language_code=:language_code
                    """,
                    release_id=synthetic_release_id,
                    language_code=language_code,
                )
                cart_option_localizations = {
                    str(item["option_item_id"]): str(item["display_name"])
                    for item in _rows(cursor)
                }
        items = [
            CartLine(
                cart_item_id=row["cart_item_id"],
                menu_id=row["menu_id"],
                merchant_id=row["merchant_id"],
                menu_name=row["menu_name"],
                menu_name_ko=row["menu_name_ko"],
                display_name=cart_menu_localizations.get(str(row["menu_id"])),
                quantity=int(row["quantity"]),
                unit_price=int(row["unit_price"]),
                options=[
                    {
                        **option,
                        "display_name": cart_option_localizations.get(
                            str(option["option_item_id"])
                        ),
                    }
                    for option in _json(row["option_snapshot_json"])
                ],
                line_total=int(row["line_total"]),
            )
            for row in rows
        ]
        missing = []
        if not items:
            missing.append("menu")
        if not cart["address_ref_id"]:
            missing.append("address")
        if not has_delivery:
            missing.append("delivery_preferences")
        subtotal = sum(item.line_total for item in items)
        minimum_order_shortfall = max(0, minimum_order_amount - subtotal)
        if minimum_order_shortfall:
            missing.append("minimum_order_amount")
        if blocking_dietary_conflicts:
            missing.append("dietary_conflict")
        if service_area_conflict:
            missing.append("service_area")
        warnings = list(dict.fromkeys(dietary_conflicts))
        if service_area_conflict:
            warnings.append("The confirmed address is outside this merchant's service area.")
        if items and structured_criteria is None:
            warnings.append("Synthetic evidence only; cross-contamination may be unverified.")
        current_fingerprint = _cart_fingerprint(
            str(cart["cart_id"]), int(cart["version"]), subtotal + delivery_fee
        )
        return CartPreview(
            cart_id=cart["cart_id"],
            session_id=session_id,
            version=int(cart["version"]),
            items=items,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            total_price=subtotal + delivery_fee,
            missing_slots=missing,
            dietary_warnings=warnings,
            minimum_order_amount=minimum_order_amount,
            minimum_order_shortfall=minimum_order_shortfall,
            ready_to_checkout=not missing,
            confirmed=(
                bool(cart["confirmed"]) and cart.get("confirmed_fingerprint") == current_fingerprint
            ),
        )

    def update_delivery(self, session_id: str, preference: DeliveryPreferenceInput) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cart_id = self._ensure_cart(connection, session_id)
            if preference.address_ref_id:
                cursor.execute(
                    """
                    SELECT 1 FROM address_ref WHERE address_ref_id=:b_address AND session_id=:b_session_id
                      AND confirmed=1
                    """,
                    b_address=preference.address_ref_id,
                    b_session_id=session_id,
                )
                if not cursor.fetchone():
                    raise ValueError("ADDRESS_NOT_CONFIRMED")
                cursor.execute(
                    "UPDATE cart SET address_ref_id=:address WHERE cart_id=:cart",
                    address=preference.address_ref_id,
                    cart=cart_id,
                )
            korean = self._translate_note(preference.user_note)
            stored_user_note = _oracle_required_text(preference.user_note)
            cursor.execute(
                """
                MERGE INTO delivery_preference target
                USING (SELECT :b_cart_id AS cart_id FROM dual) source
                ON (target.cart_id=source.cart_id)
                WHEN MATCHED THEN UPDATE SET handoff_method=:b_handoff,cutlery=:b_cutlery,
                  ring_bell=:b_ring_bell,front_desk=:b_front_desk,user_note=:b_user_note,
                  korean_note=:b_korean_note,back_translation=:b_back_translation
                WHEN NOT MATCHED THEN INSERT (cart_id,handoff_method,cutlery,ring_bell,
                  front_desk,user_note,korean_note,back_translation)
                VALUES (:b_cart_id,:b_handoff,:b_cutlery,:b_ring_bell,:b_front_desk,:b_user_note,
                  :b_korean_note,:b_back_translation)
                """,
                b_cart_id=cart_id,
                b_handoff=preference.handoff_method,
                b_cutlery=int(preference.cutlery),
                b_ring_bell=int(preference.ring_bell),
                b_front_desk=int(preference.front_desk),
                b_user_note=stored_user_note,
                b_korean_note=korean,
                b_back_translation=stored_user_note,
            )
            cursor.execute(
                "UPDATE cart SET version=version+1,confirmed=0,updated_at=:now WHERE cart_id=:id",
                now=_now(),
                id=cart_id,
            )
        return self.get_cart(session_id)

    @staticmethod
    def _revalidate_cart(
        connection: oracledb.Connection,
        session_id: str,
        *,
        confirm: bool,
    ) -> tuple[str, bool, bool, int, int]:
        """Lock, validate, and reprice a cart from authoritative Oracle rows."""
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM cart WHERE session_id=:id FOR UPDATE", id=session_id)
        cart = _row(cursor)
        if not cart:
            raise ValueError("CART_INCOMPLETE")
        cursor.execute(
            """
            SELECT p.dietary_rules_json, p.allergy_severity,
                   p.religion_selection, s.meal_need_state_json
            FROM chat_session s JOIN user_profile p ON p.profile_id=s.profile_id
            WHERE s.session_id=:id
            """,
            id=session_id,
        )
        profile = _row(cursor)
        if profile is None:
            raise ValueError("CART_INCOMPLETE")
        cursor.execute(
            """
            SELECT ref.service_area_id FROM address_ref ref
            JOIN service_area area ON area.service_area_id=ref.service_area_id
            WHERE ref.address_ref_id=:address AND ref.session_id=:session_id
              AND ref.confirmed=1 AND area.active=1
            FOR UPDATE OF area.active
            """,
            address=cart["address_ref_id"],
            session_id=session_id,
        )
        address_row = cursor.fetchone()
        address_ok = address_row is not None
        cursor.execute("SELECT 1 FROM delivery_preference WHERE cart_id=:id", id=cart["cart_id"])
        delivery_ok = cursor.fetchone() is not None
        cursor.execute(
            "SELECT * FROM cart_item WHERE cart_id=:id ORDER BY created_at", id=cart["cart_id"]
        )
        lines = _rows(cursor)
        if not address_ok or not delivery_ok or not lines:
            raise ValueError("CART_INCOMPLETE")

        dietary_rules = set(_json(profile["dietary_rules_json"]))
        cursor.execute(
            """
            SELECT criteria_json,release_family_id,knowledge_release_id,
                   certification_release_id,synthetic_enrichment_release_id FROM (
              SELECT criteria.criteria_json,family.release_family_id,
                     family.knowledge_release_id,family.certification_release_id,
                     family.synthetic_enrichment_release_id
              FROM recommendation_snapshot snapshot
              JOIN session_recommendation_criteria criteria
                ON criteria.session_id=snapshot.session_id
               AND criteria.criteria_version=snapshot.criteria_version
              JOIN recommendation_release_family family
                ON family.release_family_id=snapshot.recommendation_release_family_id
              WHERE snapshot.session_id=:session_id
                AND snapshot.structured_request_id IS NOT NULL
              ORDER BY snapshot.created_at DESC,snapshot.snapshot_id DESC
            ) WHERE ROWNUM=1
            """,
            session_id=session_id,
        )
        structured_criteria_row = cursor.fetchone()
        structured_criteria = (
            RecommendationCriteriaV2.model_validate(_json(structured_criteria_row[0]))
            if structured_criteria_row is not None
            else None
        )
        need_state = MealNeedState.model_validate(_json(profile["meal_need_state_json"] or "{}"))
        if structured_criteria is None:
            need_state = apply_profile_constraints(
                need_state,
                list(dietary_rules),
                str(profile["religion_selection"]),
            )
        address_service_area = str(address_row[0] or "")
        if need_state.service_area_id and need_state.service_area_id != address_service_area:
            raise ValueError("CART_SERVICE_AREA_MISMATCH")
        severe_shellfish = structured_criteria is None and (
            "shellfish_allergy" in dietary_rules and profile["allergy_severity"] == "severe"
        )
        vegan_required = structured_criteria is None and "vegan" in dietary_rules
        valid_structured_halal = (
            OracleYobiRepository._valid_halal_certifications_in_connection(
                connection,
                instant=_now(),
                certification_release_id=str(structured_criteria_row[3]),
            )
            if structured_criteria is not None
            and structured_criteria.schema_version == "2"
            and structured_criteria_row is not None
            else {}
        )
        synthetic_release_id = (
            str(structured_criteria_row[4] or "")
            if structured_criteria is not None
            and structured_criteria.schema_version == "3"
            and structured_criteria_row is not None
            else ""
        )
        country_spice_baseline = 3
        if structured_criteria is not None and structured_criteria.schema_version == "3":
            if not synthetic_release_id:
                raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
            cursor.execute(
                """
                SELECT spice_baseline FROM synthetic_country_profile
                WHERE release_id=:release_id AND country_code=:country_code
                """,
                release_id=synthetic_release_id,
                country_code=structured_criteria.spice_reference_country,
            )
            baseline = cursor.fetchone()
            if baseline is None:
                raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
            country_spice_baseline = int(baseline[0])
        merchant_ids: set[str] = set()
        subtotal = 0
        changed = False
        for line in lines:
            cursor.execute(
                """
                SELECT m.*, r.delivery_fee, r.min_order_amount,
                       r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.menu_id=:id AND m.availability='AVAILABLE'
                FOR UPDATE OF m.price, m.availability, r.delivery_fee,
                  r.min_order_amount, r.service_area_id
                """,
                id=line["menu_id"],
            )
            menu = _row(cursor)
            if not menu:
                raise ValueError("CART_MENU_UNAVAILABLE")
            if menu["merchant_id"] != line["merchant_id"]:
                raise ValueError("CART_MERCHANT_MISMATCH")
            if (
                not address_service_area
                or menu.get("merchant_service_area_id") != address_service_area
            ):
                raise ValueError("CART_SERVICE_AREA_MISMATCH")
            merchant_ids.add(str(menu["merchant_id"]))
            if structured_criteria is not None and structured_criteria.schema_version == "3":
                cursor.execute(
                    """
                    SELECT spice_level,halal_fit,vegan_fit
                    FROM synthetic_menu_profile
                    WHERE release_id=:release_id AND menu_id=:menu_id
                    """,
                    release_id=synthetic_release_id,
                    menu_id=menu["menu_id"],
                )
                synthetic_profile = cursor.fetchone()
                if synthetic_profile is None:
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                price_range = structured_criteria.price_range_krw
                if price_range is None or not price_range.min <= int(menu["price"]) <= price_range.max:
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                spice_level = int(synthetic_profile[0])
                spice_matches = (
                    spice_level < country_spice_baseline
                    if structured_criteria.spice_preference == "LESS"
                    else spice_level > country_spice_baseline
                    if structured_criteria.spice_preference == "MORE"
                    else spice_level == country_spice_baseline
                )
                if not spice_matches:
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                if (
                    structured_criteria.dietary_filters.halal_certified_only
                    and not synthetic_profile[1]
                ) or (
                    structured_criteria.dietary_filters.vegan
                    and not synthetic_profile[2]
                ):
                    raise ValueError("CART_DIETARY_CONFLICT")
            elif structured_criteria is not None:
                if (
                    menu["spice_level"] is not None
                    and int(menu["spice_level"]) > structured_criteria.max_spice_level
                ):
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                if (
                    structured_criteria.dietary_filters.halal_certified_only
                    and str(menu["menu_id"]) not in valid_structured_halal
                ):
                    raise ValueError("CART_DIETARY_CONFLICT")
            if vegan_required:
                cursor.execute(
                    """
                    SELECT 1 FROM menu_dietary_attribute mda
                    JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                    WHERE mda.menu_id=:id AND da.code='vegan_option' AND mda.status='VERIFIED'
                    """,
                    id=menu["menu_id"],
                )
                if cursor.fetchone() is None:
                    raise ValueError("CART_DIETARY_CONFLICT")

            selected_ids = [
                str(option["option_item_id"]) for option in _json(line["option_snapshot_json"])
            ]
            selected_counts: dict[str, int] = {}
            current_options: list[dict[str, Any]] = []
            option_total = 0
            for option_id in selected_ids:
                cursor.execute(
                    """
                    SELECT i.*, g.menu_id FROM menu_option_item i
                    JOIN menu_option_group g ON g.option_group_id=i.option_group_id
                    WHERE i.option_item_id=:id AND i.availability='AVAILABLE'
                    FOR UPDATE OF i.price_delta, i.availability, g.menu_id
                    """,
                    id=option_id,
                )
                option = _row(cursor)
                if not option or option["menu_id"] != menu["menu_id"]:
                    raise ValueError("CART_OPTION_UNAVAILABLE")
                if severe_shellfish:
                    cursor.execute(
                        """
                        SELECT 1 FROM option_dietary_conflict
                        WHERE option_item_id=:id AND rule_code='shellfish_allergy'
                        """,
                        id=option_id,
                    )
                    if cursor.fetchone() is not None:
                        raise ValueError("CART_DIETARY_CONFLICT")
                if structured_criteria is not None and structured_criteria.schema_version == "3":
                    cursor.execute(
                        """
                        SELECT halal_conflict,vegan_conflict
                        FROM synthetic_option_profile
                        WHERE release_id=:release_id AND option_item_id=:option_item_id
                        """,
                        release_id=synthetic_release_id,
                        option_item_id=option_id,
                    )
                    synthetic_option = cursor.fetchone()
                    if synthetic_option is not None and (
                        structured_criteria.dietary_filters.halal_certified_only
                        and synthetic_option[0]
                        or structured_criteria.dietary_filters.vegan
                        and synthetic_option[1]
                    ):
                        raise ValueError("CART_DIETARY_CONFLICT")
                group_id = str(option["option_group_id"])
                selected_counts[group_id] = selected_counts.get(group_id, 0) + 1
                current_options.append(
                    {
                        "option_item_id": option["option_item_id"],
                        "name_en": _catalog_text(option["name_en"], option["name_ko"]),
                        "name_ko": option["name_ko"],
                        "price_delta": int(option["price_delta"]),
                    }
                )
                option_total += int(option["price_delta"])
            cursor.execute(
                """
                SELECT g.option_group_id, g.min_select, g.max_select
                FROM menu_option_group g WHERE g.menu_id=:id
                FOR UPDATE OF g.min_select, g.max_select
                """,
                id=menu["menu_id"],
            )
            groups = _rows(cursor)
            if any(
                selected_counts.get(str(group["option_group_id"]), 0) < int(group["min_select"])
                or selected_counts.get(str(group["option_group_id"]), 0) > int(group["max_select"])
                for group in groups
            ):
                raise ValueError("CART_OPTION_SELECTION_INVALID")

            if structured_criteria is None:
                hard_conflicts, _ = OracleYobiRepository._menu_hard_constraint_conflicts(
                    connection,
                    str(menu["menu_id"]),
                    need_state,
                    str(profile["allergy_severity"]),
                    selected_ids,
                )
                if hard_conflicts:
                    raise ValueError("CART_DIETARY_CONFLICT")

            unit_price = int(menu["price"])
            line_total = (unit_price + option_total) * int(line["quantity"])
            menu_snapshot_value = {
                "name_en": _catalog_text(menu["name_en"], menu["name_ko"]),
                "price": unit_price,
            }
            line_changed = (
                int(line["unit_price"]) != unit_price
                or int(line["line_total"]) != line_total
                or _json(line["menu_snapshot_json"]) != menu_snapshot_value
                or _json(line["option_snapshot_json"]) != current_options
            )
            if line_changed:
                changed = True
                cursor.execute(
                    """
                    UPDATE cart_item SET unit_price=:unit_price,
                      menu_snapshot_json=:menu_snapshot, option_snapshot_json=:option_snapshot,
                      line_total=:line_total WHERE cart_item_id=:cart_item_id
                    """,
                    unit_price=unit_price,
                    menu_snapshot=json.dumps(menu_snapshot_value),
                    option_snapshot=json.dumps(current_options),
                    line_total=line_total,
                    cart_item_id=line["cart_item_id"],
                )
            subtotal += line_total

        if len(merchant_ids) != 1:
            raise ValueError("CART_MULTIPLE_MERCHANTS")
        cursor.execute(
            """
            SELECT r.min_order_amount, r.delivery_fee FROM merchant r WHERE r.merchant_id=:id
            FOR UPDATE OF r.min_order_amount, r.delivery_fee
            """,
            id=next(iter(merchant_ids)),
        )
        merchant = _row(cursor)
        if merchant is None or subtotal < int(merchant["min_order_amount"]):
            raise ValueError("MINIMUM_ORDER_NOT_MET")

        current_total = subtotal + int(merchant["delivery_fee"])
        was_confirmed = bool(cart["confirmed"])
        current_fingerprint = _cart_fingerprint(
            str(cart["cart_id"]), int(cart["version"]), current_total
        )
        confirmation_stale = (
            was_confirmed and cart.get("confirmed_fingerprint") != current_fingerprint
        )
        changed = changed or confirmation_stale
        version_changed = False
        if confirm and (not was_confirmed or changed):
            confirmed_version = int(cart["version"]) + 1
            cursor.execute(
                """
                UPDATE cart SET confirmed=1,version=version+1,
                  confirmed_fingerprint=:fingerprint,updated_at=:now
                WHERE cart_id=:id
                """,
                fingerprint=_cart_fingerprint(
                    str(cart["cart_id"]), confirmed_version, current_total
                ),
                now=_now(),
                id=cart["cart_id"],
            )
            version_changed = True
        elif changed:
            cursor.execute(
                """
                UPDATE cart SET confirmed=0,version=version+1,
                  confirmed_fingerprint=NULL,updated_at=:now
                WHERE cart_id=:id
                """,
                now=_now(),
                id=cart["cart_id"],
            )
            version_changed = True
        return (
            str(cart["cart_id"]),
            changed,
            was_confirmed,
            current_total,
            int(cart["version"]) + int(version_changed),
        )

    def confirm_cart(self, session_id: str) -> CartPreview:
        with self.pool.connection() as connection:
            self._revalidate_cart(connection, session_id, confirm=True)
        return self.get_cart(session_id)

    def create_checkout(self, session_id: str, data: CheckoutCreate) -> Checkout:
        changed = False
        checkout: Checkout | None = None
        with self.pool.connection() as connection:
            cart_id, changed, was_confirmed, current_total, cart_version = self._revalidate_cart(
                connection, session_id, confirm=False
            )
            if not was_confirmed:
                raise ValueError("CART_NOT_CONFIRMED")
            if changed:
                # Let the transaction commit the refreshed snapshot and reset flag.
                pass
            else:
                cursor = connection.cursor()
                fingerprint = _cart_fingerprint(cart_id, cart_version, current_total)
                cursor.execute(
                    "SELECT * FROM mock_checkout WHERE idempotency_key=:key",
                    key=data.idempotency_key,
                )
                existing = _row(cursor)
                if existing:
                    if (
                        existing["cart_id"] != cart_id
                        or int(existing["cart_version"] or -1) != cart_version
                    ):
                        raise ValueError("IDEMPOTENCY_KEY_REUSED")
                    if existing["cart_fingerprint"] != fingerprint:
                        cursor.execute(
                            """
                            UPDATE cart SET confirmed=0,version=version+1,updated_at=:now
                            WHERE cart_id=:id AND confirmed=1
                            """,
                            now=_now(),
                            id=cart_id,
                        )
                        changed = True
                    else:
                        checkout = self._checkout(existing)
                else:
                    cursor.execute(
                        """
                        SELECT * FROM (
                          SELECT * FROM mock_checkout
                          WHERE cart_id=:cart_id AND cart_version=:cart_version
                          ORDER BY created_at,checkout_id
                        ) WHERE ROWNUM=1
                        """,
                        cart_id=cart_id,
                        cart_version=cart_version,
                    )
                    active = _row(cursor)
                    if active:
                        if active["cart_fingerprint"] != fingerprint:
                            cursor.execute(
                                """
                                UPDATE cart SET confirmed=0,version=version+1,updated_at=:now
                                WHERE cart_id=:id AND confirmed=1
                                """,
                                now=_now(),
                                id=cart_id,
                            )
                            changed = True
                        else:
                            checkout = self._checkout(active)
                    else:
                        checkout_id = _id("checkout")
                        now = _now()
                        try:
                            cursor.execute(
                                """
                                INSERT INTO mock_checkout(checkout_id,cart_id,idempotency_key,
                                  payment_method,status,amount,payment_url,cart_version,
                                  cart_fingerprint,created_at,updated_at)
                                VALUES (:1,:2,:3,:4,'PENDING',:5,:6,:7,:8,:9,:10)
                                """,
                                [
                                    checkout_id,
                                    cart_id,
                                    data.idempotency_key,
                                    data.payment_method,
                                    current_total,
                                    f"/pay/{checkout_id}",
                                    cart_version,
                                    fingerprint,
                                    now,
                                    now,
                                ],
                            )
                        except oracledb.IntegrityError as exc:
                            error = exc.args[0] if exc.args else None
                            if getattr(error, "code", None) != 1:
                                raise
                            cursor.execute(
                                "SELECT * FROM mock_checkout WHERE idempotency_key=:key",
                                key=data.idempotency_key,
                            )
                            raced = _row(cursor)
                            if raced is None:
                                raise
                            if (
                                raced["cart_id"] != cart_id
                                or int(raced["cart_version"] or -1) != cart_version
                            ):
                                raise ValueError("IDEMPOTENCY_KEY_REUSED") from exc
                            if raced["cart_fingerprint"] != fingerprint:
                                raise ValueError("CART_CHANGED_RECONFIRM_REQUIRED") from exc
                            checkout = self._checkout(raced)
                        else:
                            cursor.execute(
                                "SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id
                            )
                            created = _row(cursor)
                            if created is None:
                                raise RuntimeError("CHECKOUT_CREATION_FAILED")
                            checkout = self._checkout(created)
        if changed:
            raise ValueError("CART_CHANGED_RECONFIRM_REQUIRED")
        if checkout is None:
            raise RuntimeError("CHECKOUT_CREATION_FAILED")
        return checkout

    @staticmethod
    def _checkout(row: dict[str, Any], order_id: str | None = None) -> Checkout:
        return Checkout(
            checkout_id=row["checkout_id"],
            cart_id=row["cart_id"],
            status=row["status"],
            amount=int(row["amount"]),
            payment_method=row["payment_method"],
            payment_url=row["payment_url"],
            order_id=order_id,
        )

    def get_checkout(self, checkout_id: str) -> Checkout | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
            row = _row(cursor)
            if not row:
                return None
            cursor.execute("SELECT order_id FROM mock_order WHERE checkout_id=:id", id=checkout_id)
            order = cursor.fetchone()
        return self._checkout(row, order[0] if order else None)

    def update_checkout(self, checkout_id: str, status: str) -> Checkout:
        if status not in {"SUCCEEDED", "FAILED", "CANCELED"}:
            raise ValueError("INVALID_PAYMENT_STATUS")
        checkout_stale = False
        order_id = None
        updated: dict[str, Any] | None = None
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
            observed = _row(cursor)
            if not observed:
                raise KeyError("CHECKOUT_NOT_FOUND")

            cart_state: tuple[str, bool, bool, int, int] | None = None
            cart_error: ValueError | None = None
            if status == "SUCCEEDED" and observed["status"] != "SUCCEEDED":
                cursor.execute(
                    "SELECT session_id FROM cart WHERE cart_id=:id", id=observed["cart_id"]
                )
                cart_session = cursor.fetchone()
                if cart_session is None:
                    cart_error = ValueError("CART_INCOMPLETE")
                else:
                    try:
                        # Lock the cart before the checkout row, matching create_checkout's
                        # lock order and preventing a payment/order snapshot race.
                        cart_state = self._revalidate_cart(
                            connection, str(cart_session[0]), confirm=False
                        )
                    except ValueError as exc:
                        cart_error = exc

            cursor.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id=:id FOR UPDATE", id=checkout_id
            )
            row = _row(cursor)
            if not row:
                raise KeyError("CHECKOUT_NOT_FOUND")
            if row["status"] == "SUCCEEDED" and status != "SUCCEEDED":
                raise ValueError("PAYMENT_ALREADY_SUCCEEDED")
            if status == "SUCCEEDED":
                cursor.execute(
                    "SELECT order_id FROM mock_order WHERE checkout_id=:id", id=checkout_id
                )
                existing = cursor.fetchone()
                if row["status"] == "SUCCEEDED" and existing:
                    order_id = existing[0]
                else:
                    if cart_state is None and cart_error is None:
                        cursor.execute(
                            "SELECT session_id FROM cart WHERE cart_id=:id", id=row["cart_id"]
                        )
                        cart_session = cursor.fetchone()
                        if cart_session is None:
                            cart_error = ValueError("CART_INCOMPLETE")
                        else:
                            try:
                                cart_state = self._revalidate_cart(
                                    connection, str(cart_session[0]), confirm=False
                                )
                            except ValueError as exc:
                                cart_error = exc
                    if cart_error is not None or cart_state is None:
                        raise ValueError("CHECKOUT_STALE") from cart_error
                    (
                        current_cart_id,
                        cart_changed,
                        cart_confirmed,
                        current_total,
                        current_version,
                    ) = cart_state
                    current_fingerprint = _cart_fingerprint(
                        current_cart_id, current_version, current_total
                    )
                    fingerprint_changed = current_fingerprint != row["cart_fingerprint"]
                    checkout_version = (
                        int(row["cart_version"]) if row["cart_version"] is not None else -1
                    )
                    checkout_stale = (
                        current_cart_id != row["cart_id"]
                        or not cart_confirmed
                        or cart_changed
                        or current_version != checkout_version
                        or fingerprint_changed
                    )
                    if (
                        fingerprint_changed
                        and not cart_changed
                        and cart_confirmed
                        and current_version == checkout_version
                    ):
                        cursor.execute(
                            """
                            UPDATE cart SET confirmed=0,version=version+1,updated_at=:now
                            WHERE cart_id=:id AND confirmed=1
                            """,
                            now=_now(),
                            id=current_cart_id,
                        )
                    if not checkout_stale:
                        cursor.execute(
                            """
                            SELECT other.checkout_id FROM mock_checkout other
                            JOIN mock_order placed ON placed.checkout_id=other.checkout_id
                            WHERE other.cart_id=:cart_id AND other.checkout_id<>:checkout_id
                              AND ROWNUM=1
                            """,
                            cart_id=row["cart_id"],
                            checkout_id=checkout_id,
                        )
                        if cursor.fetchone() is not None:
                            raise ValueError("CART_ORDER_ALREADY_COMPLETED")
                        cursor.execute(
                            "UPDATE mock_checkout SET status=:status,updated_at=:now WHERE checkout_id=:id",
                            status=status,
                            now=_now(),
                            id=checkout_id,
                        )
                        if existing:
                            order_id = existing[0]
                        else:
                            order_id = _id("YOBI-DEMO")
                            cursor.execute(
                                "SELECT * FROM cart_item WHERE cart_id=:id ORDER BY created_at",
                                id=row["cart_id"],
                            )
                            snapshot = _rows(cursor)
                            for item in snapshot:
                                item["created_at"] = str(item["created_at"])
                            cursor.execute(
                                """
                                INSERT INTO mock_order(
                                  order_id,checkout_id,cart_snapshot_json,order_status,
                                  estimated_delivery_at,created_at
                                ) VALUES (:1,:2,:3,'CONFIRMED',:4,:5)
                                """,
                                [
                                    order_id,
                                    checkout_id,
                                    json.dumps(snapshot),
                                    _now() + timedelta(minutes=35),
                                    _now(),
                                ],
                            )
            else:
                cursor.execute(
                    "UPDATE mock_checkout SET status=:status,updated_at=:now WHERE checkout_id=:id",
                    status=status,
                    now=_now(),
                    id=checkout_id,
                )
            cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
            updated = _row(cursor)
        if checkout_stale:
            raise ValueError("CHECKOUT_STALE")
        if updated is None:
            raise RuntimeError("CHECKOUT_UPDATE_FAILED")
        return self._checkout(updated, order_id)

    def get_order(self, order_id: str) -> Order | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM mock_order WHERE order_id=:id", id=order_id)
            row = _row(cursor)
        if not row:
            return None
        return Order(
            order_id=row["order_id"],
            checkout_id=row["checkout_id"],
            order_status=row["order_status"],
            estimated_delivery_at=row["estimated_delivery_at"],
            summary={"items": _json(row["cart_snapshot_json"]), "payment": "Demo only"},
        )

    def reset_session(self, session_id: str) -> None:
        with self.pool.connection() as connection:
            self._reset(connection, session_id, False)

    def prewarm_explanation(self, menu_id: str) -> bool:
        profile = Profile(
            profile_id="prewarm",
            consent_demo_data=True,
            created_at=datetime.now(timezone.utc),
        )
        menu = self.get_menu(menu_id, profile)
        if menu is None:
            return False
        payload = json.dumps(
            {
                "menu_id": menu.menu_id,
                "cultural_description": menu.cultural_description,
                "description": menu.description,
                "dietary_summary": menu.dietary_summary,
            },
            ensure_ascii=False,
        )
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT active_release_id FROM knowledge_runtime_state
                WHERE state_key='ACTIVE'
                """
            )
            active_release = cursor.fetchone()
            knowledge_version = str(active_release[0]) if active_release else "legacy"
            source_version = f"{CATALOG_VERSION}:{knowledge_version}"
            cache_digest = hashlib.sha256(source_version.encode("utf-8")).hexdigest()[:16]
            cache_key = f"prewarm:{menu_id}:en:{cache_digest}"
            cursor.execute(
                """
                DELETE FROM explanation_cache
                WHERE menu_id=:menu_id AND language='en' AND profile_signature='prewarm'
                  AND source_version<>:source_version
                """,
                menu_id=menu_id,
                source_version=source_version,
            )
            cursor.execute(
                """
                MERGE INTO explanation_cache target
                USING (SELECT :cache_key AS cache_key FROM dual) source
                ON (target.cache_key = source.cache_key)
                WHEN MATCHED THEN UPDATE SET
                  target.explanation_json=:payload,
                  target.source_version=:source_version,
                  target.created_at=SYSTIMESTAMP
                WHEN NOT MATCHED THEN INSERT (
                  cache_key, menu_id, language, profile_signature,
                  explanation_json, source_version
                ) VALUES (:cache_key, :menu_id, 'en', 'prewarm', :payload, :source_version)
                """,
                cache_key=cache_key,
                menu_id=menu_id,
                payload=payload,
                source_version=source_version,
            )
        return True

    @staticmethod
    def _reset(connection: oracledb.Connection, session_id: str, delete_session: bool) -> None:
        cursor = connection.cursor()
        cursor.execute("SELECT cart_id FROM cart WHERE session_id=:id", id=session_id)
        row = cursor.fetchone()
        if row:
            cart_id = row[0]
            cursor.execute(
                "DELETE FROM mock_order WHERE checkout_id IN (SELECT checkout_id FROM mock_checkout WHERE cart_id=:id)",
                id=cart_id,
            )
            cursor.execute("DELETE FROM mock_checkout WHERE cart_id=:id", id=cart_id)
            cursor.execute("DELETE FROM cart WHERE cart_id=:id", id=cart_id)
        cursor.execute("DELETE FROM address_ref WHERE session_id=:id", id=session_id)
        cursor.execute("DELETE FROM conversation_event WHERE session_id=:id", id=session_id)
        cursor.execute("DELETE FROM recommendation_snapshot WHERE session_id=:id", id=session_id)
        cursor.execute("DELETE FROM chat_message WHERE session_id=:id", id=session_id)
        if delete_session:
            cursor.execute("DELETE FROM chat_session WHERE session_id=:id", id=session_id)
        else:
            cursor.execute(
                """
                UPDATE chat_session SET state=:state,selected_menu_id=NULL,
                  selected_merchant_id=NULL,meal_need_state_json='{}',
                  dialogue_act=:dialogue_act,state_version=state_version+1,
                  state_stack_json='[]',updated_at=:now WHERE session_id=:id
                """,
                state=ChatState.DISCOVERY.value,
                dialogue_act=DialogueAct.COLLECT_NEEDS.value,
                now=_now(),
                id=session_id,
            )

    def status(self) -> dict[str, object]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                " UNION ALL ".join(
                    f"SELECT '{table}' table_name,COUNT(*) row_count FROM {table}"
                    for table in EXPECTED_RUNTIME_COUNTS
                )
            )
            counts = {str(row[0]).lower(): int(row[1]) for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT * FROM catalog_import_batch
                WHERE status='ACTIVE' AND data_origin='YOGIYO_PUBLIC_WEB'
                ORDER BY completed_at DESC FETCH FIRST 1 ROWS ONLY
                """
            )
            external = _row(cursor)
            if external is not None:
                expected_external = {
                    str(key): int(value)
                    for key, value in _json(external["expected_counts_json"]).items()
                }
                if set(expected_external) != set(EXTERNAL_CATALOG_COUNT_TABLES):
                    expected_external = {}
                actual_external: dict[str, int] = {}
                for table in EXTERNAL_CATALOG_COUNT_TABLES:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    actual_external[table] = int(cursor.fetchone()[0])
                declared_external = {
                    str(key): int(value)
                    for key, value in _json(external["actual_counts_json"]).items()
                }
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM menu_option_group groups
                    WHERE groups.min_select<0 OR groups.max_select<groups.min_select
                      OR (groups.required=1 AND groups.min_select<1)
                      OR (SELECT COUNT(*) FROM menu_option_item item
                          WHERE item.option_group_id=groups.option_group_id
                            AND item.availability='AVAILABLE') < groups.min_select
                    """
                )
                invalid_required_options = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM menu
                    WHERE semantic_text IS NULL OR DBMS_LOB.GETLENGTH(semantic_text)=0
                    """
                )
                missing_semantic_text = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM menu
                    WHERE name_en IS NULL AND serves_min IS NULL AND serves_max IS NULL
                      AND spice_level IS NULL AND name_en_status='NOT_PROVIDED'
                      AND serves_status='NOT_PROVIDED' AND spice_status='NOT_PROVIDED'
                    """
                )
                unknown_fields_preserved = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT release.* FROM knowledge_runtime_state state
                    JOIN knowledge_release release ON release.release_id=state.active_release_id
                    WHERE state.state_key='ACTIVE'
                    """
                )
                source_release = _row(cursor)
                cursor.execute(
                    """
                    SELECT family.* FROM recommendation_runtime_state state
                    JOIN recommendation_release_family family
                      ON family.release_family_id=state.active_release_family_id
                    WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                      AND family.catalog_release_id=:catalog_release_id
                    """,
                    catalog_release_id=external["catalog_release_id"],
                )
                active_family_row = _row(cursor)
                semantic_embedding_count = 0
                semantic_embedding_manifest_count = 0
                semantic_embedding_invalid_count = 0
                if active_family_row is not None:
                    cursor.execute(
                        """
                        SELECT COUNT(*),COUNT(DISTINCT embedding_manifest_sha256),
                               SUM(CASE WHEN embedding_vector IS NULL
                                          OR LENGTH(semantic_text_sha256)<>64
                                          OR LENGTH(embedding_manifest_sha256)<>64
                                        THEN 1 ELSE 0 END)
                        FROM menu_semantic_embedding
                        WHERE catalog_release_id=:catalog_release_id
                          AND embedding_model=:embedding_model
                          AND embedding_version=:embedding_version
                          AND embedding_dimension=:embedding_dimension
                        """,
                        catalog_release_id=external["catalog_release_id"],
                        embedding_model=self.embedding_provider.model,
                        embedding_version=self.embedding_provider.version,
                        embedding_dimension=self.embedding_provider.dimension,
                    )
                    semantic_embedding_row = cursor.fetchone()
                    semantic_embedding_count = int(semantic_embedding_row[0] or 0)
                    semantic_embedding_manifest_count = int(semantic_embedding_row[1] or 0)
                    semantic_embedding_invalid_count = int(semantic_embedding_row[2] or 0)
                release_id = str(source_release["release_id"]) if source_release else ""
                cursor.execute(
                    """
                    SELECT
                      SUM(CASE WHEN mapping_status='MAPPED' AND confidence_band='high'
                        THEN 1 ELSE 0 END),
                      SUM(CASE WHEN mapping_status='UNMAPPED' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN mapping_status='UNMAPPED'
                        AND TRIM(COALESCE(unmapped_reason,'')) IS NULL THEN 1 ELSE 0 END),
                      COUNT(*)
                    FROM menu_concept_map WHERE release_id=:release_id
                    """,
                    release_id=release_id,
                )
                classification_row = cursor.fetchone()
                mapped_count = int(classification_row[0] or 0)
                unmapped_count = int(classification_row[1] or 0)
                blank_unmapped_reasons = int(classification_row[2] or 0)
                classified_count = int(classification_row[3] or 0)
                cursor.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM knowledge_document
                       WHERE release_id=:release_id AND source_type='SYNTHETIC_WIKI'
                         AND review_status='REVIEWED_DEMO' AND is_synthetic=1),
                      (SELECT COUNT(*) FROM knowledge_chunk
                       WHERE release_id=:release_id AND is_synthetic=1),
                      (SELECT COUNT(*) FROM concept_preference_support
                       WHERE knowledge_release_id=:release_id AND support_status='SUPPORTED'
                         AND evidence_chunk_id IS NOT NULL
                         AND provenance_type='SYNTHETIC_WIKI'
                         AND review_status='REVIEWED_DEMO'),
                      (SELECT COUNT(*) FROM menu_concept_map
                       WHERE release_id=:release_id AND mapping_status='MAPPED'
                         AND (confidence_band<>'high'
                           OR source_type<>'YOBI_DERIVED_DEMO_MAPPING'))
                    FROM dual
                    """,
                    release_id=release_id,
                )
                reviewed_knowledge = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) FROM menu_preference_feature "
                    "WHERE knowledge_release_id=:release_id",
                    release_id=release_id,
                )
                feature_count = int(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT COUNT(*) FROM menu_preference_feature_evidence "
                    "WHERE knowledge_release_id=:release_id",
                    release_id=release_id,
                )
                feature_evidence_count = int(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT COUNT(*),COUNT(DISTINCT menu_id) "
                    "FROM menu_concept_membership "
                    "WHERE knowledge_release_id=:release_id",
                    release_id=release_id,
                )
                membership_counts = cursor.fetchone()
                membership_count = int(membership_counts[0])
                membership_menu_count = int(membership_counts[1])
                cursor.execute(
                    "SELECT COUNT(*) FROM menu_wiki_eligibility "
                    "WHERE knowledge_release_id=:release_id",
                    release_id=release_id,
                )
                wiki_eligible_menu_count = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT (SELECT COUNT(*) FROM merchant WHERE is_synthetic<>0)
                         + (SELECT COUNT(*) FROM menu WHERE is_synthetic<>0)
                    FROM dual
                    """
                )
                synthetic_core = int(cursor.fetchone()[0])
                source_fact_rows = 0
                for table in (
                    "menu_ingredient",
                    "menu_allergen",
                    "menu_dietary_attribute",
                    "merchant_certification",
                ):
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    source_fact_rows += int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM menu
                    WHERE data_origin='YOGIYO_PUBLIC_WEB' AND is_synthetic=0
                    """
                )
                external_menu_count = int(cursor.fetchone()[0])
                address_status = demo_address_status(cursor)
                source_integrity_checks = {
                    "external_counts_exact": bool(
                        expected_external
                        and expected_external == declared_external == actual_external
                    ),
                    "external_provenance_exact": external_menu_count == actual_external["menu"]
                    and synthetic_core == 0,
                    "unknown_fields_preserved_as_null": unknown_fields_preserved
                    == actual_external["menu"],
                    "catalog_semantic_text_complete": missing_semantic_text == 0,
                    "required_options_valid": invalid_required_options == 0,
                    "source_release_catalog_compatible": bool(
                        source_release
                        and source_release["status"] == "READY"
                        and source_release["catalog_version"] == external["catalog_release_id"]
                    ),
                    "single_demo_address_ready": address_status["ready"] is True,
                    "package_hashes_present": all(
                        len(str(external[column])) == 64
                        for column in (
                            "source_zip_sha256",
                            "source_xlsx_sha256",
                            "source_summary_sha256",
                            "package_sha256",
                            "selection_manifest_sha256",
                        )
                    ),
                }
                recommendation_checks = {
                    "recommendation_family_active": active_family_row is not None,
                    "classification_coverage_complete": classified_count == actual_external["menu"],
                    "high_confidence_mapping_present": mapped_count > 0,
                    "unmapped_reasons_complete": blank_unmapped_reasons == 0,
                    "reviewed_wiki_documents_present": bool(
                        reviewed_knowledge and int(reviewed_knowledge[0] or 0) > 0
                    ),
                    "reviewed_wiki_chunks_present": bool(
                        reviewed_knowledge and int(reviewed_knowledge[1] or 0) > 0
                    ),
                    "reviewed_preference_support_present": bool(
                        reviewed_knowledge and int(reviewed_knowledge[2] or 0) > 0
                    ),
                    "mapping_provenance_exact": bool(
                        reviewed_knowledge and int(reviewed_knowledge[3] or 0) == 0
                    ),
                    "source_specific_facts_not_invented": source_fact_rows == 0,
                    "support_manifest_valid": bool(
                        active_family_row
                        and len(str(active_family_row.get("support_manifest_sha256") or "")) == 64
                        and str(active_family_row.get("support_manifest_sha256")) != "0" * 64
                    ),
                    "menu_preference_features_present": feature_count > 0,
                    "menu_preference_evidence_present": feature_evidence_count > 0,
                    "menu_concept_memberships_present": membership_count > 0,
                    "wiki_eligibility_exactly_covers_membership_menus": (
                        wiki_eligible_menu_count == membership_menu_count
                        and membership_menu_count > 0
                    ),
                    "feature_manifest_valid": bool(
                        active_family_row
                        and len(str(active_family_row.get("feature_manifest_sha256") or "")) == 64
                        and str(active_family_row.get("feature_manifest_sha256")) != "0" * 64
                    ),
                    "ranking_policy_active": bool(
                        active_family_row
                        and str(active_family_row.get("ranking_policy_version"))
                        == RANKING_POLICY_VERSION
                        and len(str(active_family_row.get("ranking_policy_sha256") or "")) == 64
                        and str(active_family_row.get("ranking_policy_sha256")) != "0" * 64
                    ),
                    "semantic_embedding_identity_compatible": bool(
                        active_family_row
                        and str(active_family_row["embedding_model"])
                        == self.embedding_provider.model
                        and str(active_family_row["embedding_version"])
                        == self.embedding_provider.version
                        and semantic_embedding_count == actual_external["menu"]
                        and semantic_embedding_manifest_count == 1
                        and semantic_embedding_invalid_count == 0
                    ),
                }
                external_checks = {**source_integrity_checks, **recommendation_checks}
                source_release_counts = (
                    _json(source_release["actual_counts_json"]) if source_release else {}
                )
                cursor.execute("SELECT MAX(updated_at) FROM menu")
                last_seed_time = cursor.fetchone()[0]
                return {
                    "backend": "oracle-26ai",
                    "catalog_mode": "EXTERNAL_SOURCE",
                    "data_origin": str(external["data_origin"]),
                    "catalog_import_id": str(external["catalog_import_id"]),
                    "catalog_version": str(external["catalog_release_id"]),
                    "knowledge_catalog_version": (
                        str(source_release["catalog_version"]) if source_release else None
                    ),
                    "counts": counts,
                    "external_counts": actual_external,
                    "demo_address": address_status,
                    "source_integrity_ready": all(source_integrity_checks.values()),
                    "recommendation_ready": all(recommendation_checks.values()),
                    "canonical_ready": all(source_integrity_checks.values()),
                    "vector_ready": recommendation_checks[
                        "semantic_embedding_identity_compatible"
                    ],
                    "semantic_channel_status": (
                        "READY"
                        if recommendation_checks["semantic_embedding_identity_compatible"]
                        else "DISABLED_MODEL_MISMATCH"
                    ),
                    "embedding_model": self.embedding_provider.model,
                    "last_seed_time": str(last_seed_time) if last_seed_time else None,
                    "knowledge_ready": all(recommendation_checks.values()),
                    "readiness_checks": external_checks,
                    "knowledge_expected_counts": source_release_counts,
                    "knowledge_actual_counts": source_release_counts,
                    "knowledge_supplemental_counts": {
                        "mapped_menus": mapped_count,
                        "unmapped_menus": unmapped_count,
                        "source_fact_rows": source_fact_rows,
                        "menu_preference_features": feature_count,
                        "menu_preference_feature_evidence": feature_evidence_count,
                        "menu_concept_memberships": membership_count,
                        "menu_concept_membership_menus": membership_menu_count,
                        "wiki_eligible_menus": wiki_eligible_menu_count,
                        "menu_semantic_embeddings": semantic_embedding_count,
                        "menu_semantic_embedding_manifests": (
                            semantic_embedding_manifest_count
                        ),
                    },
                    "feature_count": feature_count,
                    "wiki_eligible_menu_count": wiki_eligible_menu_count,
                    "feature_manifest_sha256": (
                        str(active_family_row.get("feature_manifest_sha256"))
                        if active_family_row
                        else None
                    ),
                    "ranking_policy_version": (
                        str(active_family_row.get("ranking_policy_version"))
                        if active_family_row
                        else None
                    ),
                    "knowledge_release_id": (
                        str(source_release["release_id"]) if source_release else None
                    ),
                    "knowledge_embedding_model": (
                        str(source_release["embedding_model"]) if source_release else None
                    ),
                    "knowledge_embedding_dimension": (
                        int(source_release["embedding_dimension"]) if source_release else None
                    ),
                    "knowledge_embedding_version": (
                        str(source_release["embedding_version"]) if source_release else None
                    ),
                    "source_limitations": [
                        "NO_REVIEWED_INGREDIENT_DATA",
                        "NO_FORMAL_CERTIFICATION_DATA",
                        "SPICE_AND_SERVES_NOT_PROVIDED",
                    ],
                }
            cursor.execute(
                "SELECT COUNT(*) FROM menu WHERE menu_id IN ('menu_001_01','menu_002_01','menu_003_01')"
            )
            canonical = int(cursor.fetchone()[0]) == 3
            cursor.execute(
                """
                SELECT COUNT(*) FROM menu
                WHERE embedding_vector IS NULL OR embedding_model IS NULL
                  OR embedding_dimension IS NULL OR embedding_version IS NULL
                  OR embedding_model<>:model OR embedding_dimension<>:dimension
                  OR embedding_version<>:version
                """,
                model=self.embedding_provider.model,
                dimension=self.embedding_provider.dimension,
                version=self.embedding_provider.version,
            )
            menu_vector_mismatches = int(cursor.fetchone()[0])
            cursor.execute("SELECT MAX(updated_at) FROM menu")
            last_seed_time = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT release.release_id,release.catalog_version,release.manifest_sha256,
                       release.status,release.expected_counts_json,release.actual_counts_json,
                       release.embedding_model,
                       release.embedding_dimension,release.embedding_version,
                       (SELECT COUNT(*) FROM menu_concept_map mapping
                        WHERE mapping.release_id=release.release_id
                          AND mapping.mapping_status='MAPPED') mapped_menus,
                       (SELECT COUNT(*) FROM knowledge_chunk chunk
                        WHERE chunk.release_id=release.release_id
                          AND chunk.embedding_vector IS NULL) null_vectors
                FROM knowledge_runtime_state state
                JOIN knowledge_release release ON release.release_id=state.active_release_id
                WHERE state.state_key='ACTIVE'
                """
            )
            knowledge = _row(cursor)
            expected_counts: dict[str, int] = {}
            declared_actual_counts: dict[str, int] = {}
            observed_counts: dict[str, int] = {}
            supplemental_counts = {
                "mapped_menus": 0,
                "origin_declarations": 0,
                "merchant_ingredients": 0,
                "option_effects": 0,
                "chunk_metadata_mismatches": 0,
            }
            if knowledge:
                release_id = str(knowledge["release_id"])
                expected_counts = {
                    str(key): int(value)
                    for key, value in _json(knowledge["expected_counts_json"]).items()
                }
                declared_actual_counts = {
                    str(key): int(value)
                    for key, value in _json(knowledge["actual_counts_json"]).items()
                }
                for key, table in (
                    ("concepts", "dish_concept"),
                    ("relations", "dish_relation"),
                    ("closure", "dish_concept_closure"),
                    ("claims", "concept_claim"),
                    ("documents", "knowledge_document"),
                    ("chunks", "knowledge_chunk"),
                ):
                    cursor.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE release_id=:release_id",
                        release_id=release_id,
                    )
                    observed_counts[key] = int(cursor.fetchone()[0])
                supplemental_counts["mapped_menus"] = int(knowledge["mapped_menus"])
                for key, table in (
                    ("origin_declarations", "merchant_origin_declaration"),
                    ("merchant_ingredients", "merchant_ingredient"),
                    ("option_effects", "option_ingredient_effect"),
                ):
                    cursor.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE release_id=:release_id",
                        release_id=release_id,
                    )
                    supplemental_counts[key] = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_chunk
                    WHERE release_id=:release_id AND (
                      embedding_model<>:model OR embedding_dimension<>:dimension
                      OR embedding_version<>:version
                    )
                    """,
                    release_id=release_id,
                    model=knowledge["embedding_model"],
                    dimension=int(knowledge["embedding_dimension"]),
                    version=knowledge["embedding_version"],
                )
                supplemental_counts["chunk_metadata_mismatches"] = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT COUNT(*) FROM menu_option_group g
                WHERE g.min_select<0 OR g.max_select<g.min_select
                  OR (g.required=1 AND g.min_select<1)
                  OR (SELECT COUNT(*) FROM menu_option_item item
                      WHERE item.option_group_id=g.option_group_id
                        AND item.availability='AVAILABLE') < g.min_select
                """
            )
            invalid_required_options = int(cursor.fetchone()[0])
            release_embedding_matches_runtime = bool(
                knowledge
                and knowledge["embedding_model"] == self.embedding_provider.model
                and int(knowledge["embedding_dimension"]) == self.embedding_provider.dimension
                and knowledge["embedding_version"] == self.embedding_provider.version
            )
            readiness_checks = {
                "base_catalog_counts_compatible": _runtime_counts_compatible(counts),
                "canonical_rows_present": canonical,
                "active_release_matches_runtime_corpus": bool(
                    knowledge
                    and knowledge["release_id"] == KNOWLEDGE_RELEASE_ID
                    and knowledge["catalog_version"] == KNOWLEDGE_CATALOG_VERSION
                ),
                "release_manifest_present": bool(
                    knowledge
                    and len(str(knowledge["manifest_sha256"])) == 64
                    and str(knowledge["manifest_sha256"]).strip("0") != ""
                ),
                "release_status_ready": bool(knowledge and knowledge["status"] == "READY"),
                "release_counts_exact": bool(
                    knowledge
                    and expected_counts
                    and expected_counts == declared_actual_counts == observed_counts
                ),
                "menu_mappings_exact": supplemental_counts["mapped_menus"] == EXPECTED_MAPPED_MENUS,
                "origin_declarations_exact": supplemental_counts["origin_declarations"]
                == EXPECTED_ORIGIN_DECLARATIONS,
                "merchant_ingredients_exact": supplemental_counts["merchant_ingredients"]
                == EXPECTED_MERCHANT_INGREDIENTS,
                "option_effects_exact": supplemental_counts["option_effects"]
                == EXPECTED_OPTION_EFFECTS,
                "knowledge_chunk_vectors_complete": bool(
                    knowledge
                    and int(knowledge["null_vectors"]) == 0
                    and supplemental_counts["chunk_metadata_mismatches"] == 0
                ),
                "embedding_runtime_compatible": release_embedding_matches_runtime,
                "menu_vectors_compatible": menu_vector_mismatches == 0,
                "required_options_valid": invalid_required_options == 0,
            }
            knowledge_ready = all(readiness_checks.values())
        return {
            "backend": "oracle-26ai",
            "catalog_version": CATALOG_VERSION,
            "knowledge_catalog_version": knowledge["catalog_version"] if knowledge else None,
            "counts": counts,
            "canonical_ready": canonical and _runtime_counts_compatible(counts),
            "vector_ready": menu_vector_mismatches == 0 and release_embedding_matches_runtime,
            "embedding_model": self.embedding_provider.model,
            "last_seed_time": str(last_seed_time) if last_seed_time else None,
            "knowledge_ready": knowledge_ready,
            "readiness_checks": readiness_checks,
            "knowledge_expected_counts": expected_counts,
            "knowledge_actual_counts": observed_counts,
            "knowledge_supplemental_counts": supplemental_counts,
            "knowledge_release_id": knowledge["release_id"] if knowledge else None,
            "knowledge_embedding_model": knowledge["embedding_model"] if knowledge else None,
            "knowledge_embedding_dimension": (
                int(knowledge["embedding_dimension"]) if knowledge else None
            ),
            "knowledge_embedding_version": knowledge["embedding_version"] if knowledge else None,
        }

    def record_audit(
        self,
        session_id: str | None,
        tool: str,
        input_payload: str,
        evidence_ids: list[str],
        output_status: str,
        latency_ms: int,
        fallback_used: bool,
        safe_error_code: str | None = None,
    ) -> None:
        safe_session = self.safe_input_hash(session_id) if session_id else None
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO audit_log (
                  log_id,session_id,tool,input_hash,evidence_ids_json,output_status,
                  latency_ms,fallback_used,safe_error_code,created_at
                ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10)
                """,
                [
                    _id("audit"),
                    safe_session,
                    tool[:120],
                    self.safe_input_hash(input_payload),
                    json.dumps(evidence_ids[:50]),
                    output_status[:40],
                    max(0, latency_ms),
                    int(fallback_used),
                    safe_error_code[:120] if safe_error_code else None,
                    _now(),
                ],
            )

    @staticmethod
    def safe_input_hash(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
