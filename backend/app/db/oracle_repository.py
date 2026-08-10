from __future__ import annotations

import hashlib
import json
from array import array
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import oracledb

from app.core.config import Settings
from app.db.oracle_pool import OraclePool
from app.db.seed_data import CATALOG_VERSION
from app.domain.address import normalize_address_text
from app.domain.dialogue import (
    ConstraintStrictness,
    ConversationEventInput,
    ConversationEventResult,
    ConversationEventType,
    DialogueAct,
    MealNeedState,
    RecommendationSnapshot,
)
from app.domain.dietary import apply_profile_constraints, known_allergen_conflicts
from app.domain.knowledge import (
    GroundedMenuKnowledge,
    GroundedPassage,
    KnowledgeSourceKind,
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
    OptionGroup,
    OptionItem,
    Order,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    Session,
)
from app.domain.recommendation import rerank_menu_candidates
from app.knowledge.catalog_seed import KNOWLEDGE_CATALOG_VERSION, KNOWLEDGE_RELEASE_ID
from app.knowledge.resolver import (
    allergen_constraint_conflicts,
    category_constraint_conflicts,
    ingredient_constraint_conflicts,
    merchant_cross_contact_conflicts,
    resolve_allergen_claims,
    resolve_ingredient_claims,
    resolve_merchant_ingredient_claims,
    severe_allergy_conflicts,
)
from app.rag.providers import choose_embedding_provider

RECOMMENDATION_CANDIDATE_CAP = 40
RECOMMENDATION_PASSAGE_LIMIT = 3
EXPECTED_MAPPED_MENUS = 150
EXPECTED_ORIGIN_DECLARATIONS = 30
EXPECTED_MERCHANT_INGREDIENTS = 266
EXPECTED_OPTION_EFFECTS = 4


def _oracle_required_text(value: str) -> str:
    """Keep API-level empty strings non-NULL in Oracle VARCHAR2 columns."""

    return value or " "


def _oracle_logical_text(value: object) -> str:
    text = str(value or "")
    return "" if text == " " else text


EXPECTED_RUNTIME_COUNTS = {
    "service_area": 3,
    "menu_category": 20,
    "merchant": 30,
    "menu": 150,
    "menu_knowledge": 150,
    "menu_option_group": 302,
    "menu_option_item": 605,
    "review_snippet": 600,
    "evidence": 300,
    "address_place": 20,
    "ingredient": 47,
    "menu_ingredient": 7,
    "allergen": 10,
    "menu_allergen": 162,
    "dietary_attribute": 15,
    "menu_dietary_attribute": 317,
    "option_dietary_conflict": 1,
}


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


class OracleYobiRepository:
    """Production repository: Oracle owns catalog, state, cart, checkout, and audit data."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool = OraclePool(settings)
        self.embedding_provider = choose_embedding_provider(settings)

    def initialize(self) -> None:
        self.pool.initialize()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM schema_migration")
            cursor.fetchone()

    def create_profile(self, data: ProfileCreate) -> Profile:
        if not data.consent_demo_data:
            raise ValueError("Demo data processing consent is required to start a session")
        profile_id = _id("profile")
        created_at = _now()
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO user_profile (
                  profile_id, preferred_language, nationality, age_band, gender,
                  religion_selection, dietary_rules_json, allergy_severity,
                  spice_tolerance, favorite_foods_json, consent_demo_data,
                  remember_profile, created_at
                ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13)
                """,
                [
                    profile_id,
                    data.preferred_language,
                    data.nationality,
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
            raise ValueError("Demo data processing consent is required to keep a profile")
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                UPDATE user_profile SET preferred_language=:preferred_language,
                  nationality=:nationality,age_band=:age_band,gender=:gender,
                  religion_selection=:religion_selection,dietary_rules_json=:dietary_rules,
                  allergy_severity=:allergy_severity,spice_tolerance=:spice_tolerance,
                  favorite_foods_json=:favorite_foods,consent_demo_data=:consent,
                  remember_profile=:remember WHERE profile_id=:profile_id
                """,
                preferred_language=merged.preferred_language,
                nationality=merged.nationality,
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
                FROM chat_message WHERE session_id = :id ORDER BY created_at, message_id
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
        return messages

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
            user_metadata = {
                "client_request_id": request_id,
                "intent": intent,
            } if request_id else {}
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
            need_state = apply_profile_constraints(
                need_state,
                list(_json(profile_row["dietary_rules_json"])),
                str(profile_row["religion_selection"]),
            )
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
                live_menu = cursor.fetchone()
                if conflicts or live_menu is None or str(live_menu[0]) != candidate.merchant_id:
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
        severe_shellfish = (
            "shellfish_allergy" in profile.dietary_rules and profile.allergy_severity == "severe"
        )
        vegan_required = "vegan" in profile.dietary_rules
        severe_allergies = profile.allergy_severity == "severe"
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM (
                  SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max,
                    VECTOR_DISTANCE(m.embedding_vector, :query_vector, COSINE) AS vector_distance
                  FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                  WHERE m.availability = 'AVAILABLE'
                    AND m.price <= :budget
                    AND m.spice_level <= :spice
                    AND m.embedding_vector IS NOT NULL
                    AND (:severe_shellfish = 0 OR (
                      EXISTS (
                        SELECT 1 FROM menu_dietary_attribute mda
                        JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                        WHERE mda.menu_id=m.menu_id AND da.code='shellfish_sauce_absent'
                          AND mda.status='VERIFIED'
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM menu_allergen ma
                        JOIN allergen a ON a.allergen_id=ma.allergen_id
                        WHERE ma.menu_id=m.menu_id AND a.code='shellfish_risk'
                      )
                    ))
                    AND (:vegan_required = 0 OR EXISTS (
                      SELECT 1 FROM menu_dietary_attribute mda
                      JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                      WHERE mda.menu_id=m.menu_id AND da.code='vegan_option'
                        AND mda.status='VERIFIED'
                    ))
                    AND (:exclude_pork = 0 OR NOT JSON_EXISTS(m.allergen_tags_json, '$?(@ == "pork")'))
                  ORDER BY vector_distance, m.price
                ) WHERE ROWNUM <= :candidate_limit
                """,
                query_vector=query_vector,
                budget=budget,
                spice=spice,
                severe_shellfish=int(severe_shellfish),
                vegan_required=int(vegan_required),
                exclude_pork=int("pork" in {item.lower() for item in excluded_ingredients}),
                candidate_limit=min(
                    RECOMMENDATION_CANDIDATE_CAP,
                    max(16, min(limit, RECOMMENDATION_CANDIDATE_CAP) * 4),
                ),
            )
            rows = _rows(cursor)
            candidate_ids = [str(row["menu_id"]) for row in rows]
            grounded = self._bulk_resolved_knowledge_claims(connection, candidate_ids)
            knowledge = self._bulk_knowledge_passages(connection, candidate_ids, query_vector)
            evidence_by_menu: dict[str, list[str]] = defaultdict(list)
            if candidate_ids:
                bind_names = [f"evidence_menu_{index}" for index in range(len(candidate_ids))]
                evidence_binds = dict(zip(bind_names, candidate_ids))
                cursor.execute(
                    f"""
                    SELECT subject_id,evidence_id FROM evidence
                    WHERE subject_id IN ({','.join(':' + name for name in bind_names)})
                    ORDER BY subject_id,evidence_id
                    """,
                    evidence_binds,
                )
                for evidence_row in _rows(cursor):
                    evidence_by_menu[str(evidence_row["subject_id"])].append(
                        str(evidence_row["evidence_id"])
                    )

        lowered = query.lower()
        scored: list[MenuSummary] = []
        for row in rows:
            menu_id = str(row["menu_id"])
            tags = set(_json(row["dietary_tags_json"]))
            allergens = set(_json(row["allergen_tags_json"]))
            if severe_allergies and known_allergen_conflicts(allergens, set(profile.dietary_rules)):
                continue
            menu_similarity = max(0.0, 1.0 - float(row["vector_distance"]))
            knowledge_similarity, passage_ids = knowledge.get(menu_id, (0.0, []))
            boost = 0.0
            if "red rice cake" in lowered and "tteokbokki" in row["category"].lower():
                boost += 0.45
            if any(term in lowered for term in ("rain", "broth", "noodle", "soup")) and row[
                "category"
            ] in {"Chicken kalguksu", "Samgyetang", "Sundubu"}:
                boost += 0.18
            if any(term in lowered for term in ("mild", "not spicy")) and row["spice_level"] <= 1:
                boost += 0.16
            if "vegan" in lowered and "vegan_option" in tags:
                boost += 0.4
            reasons = [f"Matches your spice tolerance (level {int(row['spice_level'])} of 3)"]
            if "creamy pasta" in profile.favorite_foods and "rose" in row["category"].lower():
                boost += 0.2
                reasons.append("Creamy profile connects with a favourite food you selected")
            risks: list[str] = []
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
            mastered_shellfish = (
                "shellfish_sauce_absent" in tags and "shellfish_risk" not in allergens
            )
            ignored_allergies = (
                {"shellfish"}
                if mastered_shellfish
                and "shellfish_allergy"
                in {*safety_state.dietary_rules, *safety_state.profile_dietary_rules}
                else set()
            )
            conflicts.extend(
                allergen_constraint_conflicts(
                    allergen_claims,
                    safety_state,
                    ignored_allergies=ignored_allergies,
                )
            )
            if profile.allergy_severity == "severe":
                conflicts.extend(
                    severe_allergy_conflicts(
                        ingredient_claims,
                        allergen_claims,
                        safety_state.dietary_rules,
                        shellfish_mastered_absence=mastered_shellfish,
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
            # Reviews remain display-only and intentionally contribute exactly zero.
            similarity = 0.75 * menu_similarity + 0.25 * knowledge_similarity + boost
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
        return scored[:limit]

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
            merchant_name=row["merchant_name"],
            name_en=row["name_en"],
            name_ko=row["name_ko"],
            category=row["category"],
            description=row["description"],
            cultural_description=row["cultural_description"],
            price=int(row["price"]),
            delivery_fee=int(row["delivery_fee"]),
            eta_min=int(row["eta_min"]),
            eta_max=int(row["eta_max"]),
            spice_level=int(row["spice_level"]),
            serves_min=int(row["serves_min"]),
            serves_max=int(row["serves_max"]),
            dietary_summary="Synthetic evidence; see evidence details before ordering.",
            evidence_status=status,
            match_reasons=reasons,
            risk_hints=risks,
            semantic_score=round(max(0.0, min(1.0, score)), 4),
        )

    def get_menu(self, menu_id: str, profile: Profile) -> MenuSummary | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
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
        menu = self._menu_summary(
            row,
            ["Selected menu from the synthetic catalog"],
            ["Cross-contamination is not verified"],
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
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max,
                  r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.merchant_id=:merchant_id AND m.availability='AVAILABLE'
                  AND m.spice_level<=:spice
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
            if (
                "shellfish_allergy" in rules
                and profile.allergy_severity == "severe"
                and "shellfish_sauce_absent" not in tags
            ):
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
                SELECT claim.*, ingredient.name_en, closure.depth,
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
            SELECT fact.*, ingredient.name_en, fact.source_id AS source_version
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
                SELECT effect.*, ingredient.name_en, effect.option_item_id AS source_id,
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
    ) -> dict[str, tuple[list[Any], list[Any], list[Any]]]:
        """Resolve candidate claims with bounded, set-based Oracle queries."""

        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        cursor = connection.cursor()
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
            SELECT mapping.menu_id,claim.*,ingredient.name_en,closure.depth,
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
            SELECT fact.menu_id,fact.*,ingredient.name_en,fact.source_id AS source_version
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
            SELECT menu.menu_id,fact.*,ingredient.name_en,declaration.source_version
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
            SELECT mapping.menu_id,chunk.chunk_id,
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
            WHERE state.state_key='ACTIVE' AND release.status='READY'
              AND mapping.menu_id IN ({','.join(':' + name for name in menu_bind_names)})
              AND chunk.embedding_vector IS NOT NULL
              AND chunk.embedding_model=release.embedding_model
              AND chunk.embedding_dimension=release.embedding_dimension
              AND chunk.embedding_version=release.embedding_version
            """,
            binds,
        )
        grouped: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for row in _rows(cursor):
            grouped[str(row["menu_id"])].append(
                (max(0.0, 1.0 - float(row["distance"])), str(row["chunk_id"]))
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
        if state.max_spiciness is not None and int(menu["spice_level"]) > state.max_spiciness:
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
            SELECT fact.*,ingredient.name_en,declaration.source_version
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
        cursor.execute(
            """
            SELECT CASE WHEN EXISTS (
              SELECT 1 FROM menu_dietary_attribute mda
              JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
              WHERE mda.menu_id=:menu_id AND da.code='shellfish_sauce_absent'
                AND mda.status='VERIFIED'
            ) AND NOT EXISTS (
              SELECT 1 FROM menu_allergen ma
              JOIN allergen a ON a.allergen_id=ma.allergen_id
              WHERE ma.menu_id=:menu_id AND a.code='shellfish_risk'
            ) THEN 1 ELSE 0 END FROM dual
            """,
            menu_id=menu_id,
        )
        mastered_shellfish = int(cursor.fetchone()[0]) == 1
        ignored_allergies = (
            {"shellfish"}
            if mastered_shellfish
            and "shellfish_allergy" in {*state.dietary_rules, *state.profile_dietary_rules}
            else set()
        )
        conflicts.extend(
            allergen_constraint_conflicts(
                allergen_claims,
                state,
                ignored_allergies=ignored_allergies,
            )
        )
        if allergy_severity == "severe":
            conflicts.extend(
                severe_allergy_conflicts(
                    ingredient_claims,
                    allergen_claims,
                    state.dietary_rules,
                    shellfish_mastered_absence=mastered_shellfish,
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
        query_vector = array(
            "f", self.embedding_provider.embed([search_text], "SEARCH_QUERY")[0]
        )
        with self.pool.connection() as connection:
            release_id, concept_id, ingredient_claims, allergen_claims = (
                self._resolved_knowledge_claims(connection, menu_id, option_item_ids)
            )
            cursor = connection.cursor()
            passages: list[GroundedPassage] = []
            concept_lineage: list[str] = []
            available_facets: list[str] = []
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
                    SELECT * FROM (
                      SELECT chunk.chunk_id,chunk.document_id,chunk.concept_id,chunk.facet,
                             chunk.content,
                             VECTOR_DISTANCE(chunk.embedding_vector,:query_vector,COSINE) distance
                      FROM knowledge_chunk chunk
                      JOIN dish_concept_closure closure
                        ON closure.release_id=chunk.release_id
                       AND closure.ancestor_concept_id=chunk.concept_id
                      WHERE chunk.release_id=:release_id
                        AND closure.descendant_concept_id=:concept_id
                        AND closure.inherit_claims=1
                        AND chunk.embedding_vector IS NOT NULL
                      ORDER BY distance,chunk.chunk_id
                    ) WHERE ROWNUM<=5
                    """,
                    query_vector=query_vector,
                    release_id=release_id,
                    concept_id=concept_id,
                )
                passages = [
                    GroundedPassage(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        concept_id=row["concept_id"],
                        facet=row["facet"],
                        content=row["content"],
                        source_kind=KnowledgeSourceKind.SYNTHETIC_WIKI,
                        source_version=release_id,
                        score=round(max(0.0, 1.0 - float(row["distance"])), 4),
                    )
                    for row in _rows(cursor)
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
                SELECT fact.*,ingredient.name_en,declaration.source_version
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
        return GroundedMenuKnowledge(
            menu_id=menu_id,
            release_id=release_id,
            concept_id=concept_id,
            concept_lineage=concept_lineage,
            available_facets=available_facets,
            ingredient_claims=ingredient_claims,
            allergen_claims=allergen_claims,
            merchant_ingredient_claims=merchant_claims,
            passages=passages,
            merchant_origin_notes=[str(row["raw_text"]) for row in origin_rows],
            unknowns=[
                "Merchant-specific recipe differences are unknown unless a menu fact overrides the Wiki.",
                "Shared-kitchen cross-contact is not confirmed by the synthetic Wiki or origin declaration.",
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
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min,
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
                        "One-person portion" if menu.serves_max == 1 else "Shareable portion"
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

    def get_options(self, menu_id: str) -> list[OptionGroup]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM menu_option_group WHERE menu_id=:id ORDER BY sort_order", id=menu_id
            )
            groups = _rows(cursor)
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
                result.append(
                    OptionGroup(
                        option_group_id=group["option_group_id"],
                        name_en=group["name_en"],
                        name_ko=group["name_ko"],
                        description=group["description"],
                        required=bool(group["required"]),
                        min_select=int(group["min_select"]),
                        max_select=int(group["max_select"]),
                        items=[
                            OptionItem(
                                option_item_id=item["option_item_id"],
                                name_en=item["name_en"],
                                name_ko=item["name_ko"],
                                description=item["description"],
                                price_delta=int(item["price_delta"]),
                                available=item["availability"] == "AVAILABLE",
                                dietary_conflict=item["dietary_conflict"],
                                conflicting_rules=(
                                    str(item["conflicting_rules_csv"]).split(",")
                                    if item["conflicting_rules_csv"]
                                    else []
                                ),
                            )
                            for item in items
                        ],
                    )
                )
        return result

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
                    "name_en": option["name_en"],
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
                        or _oracle_logical_text(duplicate.get("user_note"))
                        != item.user_note
                    ):
                        raise ValueError("IDEMPOTENCY_KEY_REUSED")
                    return self.get_cart(session_id)
            menu, options, line_total = self._cart_item_values(connection, item)
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
                  agent_request_key,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13)
                """,
                [
                    _id("cartitem"),
                    cart_id,
                    menu["menu_id"],
                    menu["merchant_id"],
                    item.quantity,
                    int(menu["price"]),
                    json.dumps({"name_en": menu["name_en"], "price": int(menu["price"])}),
                    json.dumps(options),
                    line_total,
                    _oracle_required_text(item.user_note),
                    self._translate_note(item.user_note),
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
            )
            menu, options, line_total = self._cart_item_values(connection, replacement)
            cursor.execute(
                """
                UPDATE cart_item SET quantity=:quantity,unit_price=:unit_price,
                  menu_snapshot_json=:menu_snapshot,option_snapshot_json=:option_snapshot,
                  line_total=:line_total,user_note=:user_note,korean_note=:korean_note
                WHERE cart_item_id=:cart_item_id
                """,
                quantity=replacement.quantity,
                unit_price=int(menu["price"]),
                menu_snapshot=json.dumps({"name_en": menu["name_en"], "price": int(menu["price"])}),
                option_snapshot=json.dumps(options),
                line_total=line_total,
                user_note=_oracle_required_text(replacement.user_note),
                korean_note=self._translate_note(replacement.user_note),
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
                SELECT ci.*,m.name_en AS menu_name,m.name_ko AS menu_name_ko,m.allergen_tags_json FROM cart_item ci
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
                       p.religion_selection, s.meal_need_state_json
                FROM chat_session s JOIN user_profile p ON p.profile_id=s.profile_id
                WHERE s.session_id=:id
                """,
                id=session_id,
            )
            profile_row = _row(cursor)
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
            if profile_row and rows:
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
                    conflicts = (
                        known_allergen_conflicts(
                            set(_json(row["allergen_tags_json"])), dietary_rules
                        )
                        if profile_row["allergy_severity"] == "severe"
                        else set()
                    )
                    for conflict in sorted(conflicts - {"shellfish"}):
                        dietary_conflicts.append(
                            f"Remove {row['menu_name']} to continue; it is flagged for {conflict.replace('_', ' ')}."
                        )
                    if severe_shellfish:
                        cursor.execute(
                            """
                            SELECT CASE WHEN EXISTS (
                              SELECT 1 FROM menu_dietary_attribute mda
                              JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                              WHERE mda.menu_id=:id AND da.code='shellfish_sauce_absent'
                                AND mda.status='VERIFIED'
                            ) AND NOT EXISTS (
                              SELECT 1 FROM menu_allergen ma
                              JOIN allergen a ON a.allergen_id=ma.allergen_id
                              WHERE ma.menu_id=:id AND a.code='shellfish_risk'
                            ) THEN 1 ELSE 0 END FROM dual
                            """,
                            id=row["menu_id"],
                        )
                        if int(cursor.fetchone()[0]) != 1:
                            dietary_conflicts.append(
                                f"Remove {row['menu_name']} to continue; its shellfish safety is not verified."
                            )
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
        items = [
            CartLine(
                cart_item_id=row["cart_item_id"],
                menu_id=row["menu_id"],
                merchant_id=row["merchant_id"],
                menu_name=row["menu_name"],
                menu_name_ko=row["menu_name_ko"],
                quantity=int(row["quantity"]),
                unit_price=int(row["unit_price"]),
                options=_json(row["option_snapshot_json"]),
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
        if dietary_conflicts:
            missing.append("dietary_conflict")
        if service_area_conflict:
            missing.append("service_area")
        warnings = list(dict.fromkeys(dietary_conflicts))
        if service_area_conflict:
            warnings.append("The confirmed address is outside this merchant's service area.")
        if items:
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
                bool(cart["confirmed"])
                and cart.get("confirmed_fingerprint") == current_fingerprint
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
        need_state = apply_profile_constraints(
            MealNeedState.model_validate(_json(profile["meal_need_state_json"] or "{}")),
            list(dietary_rules),
            str(profile["religion_selection"]),
        )
        address_service_area = str(address_row[0] or "")
        if need_state.service_area_id and need_state.service_area_id != address_service_area:
            raise ValueError("CART_SERVICE_AREA_MISMATCH")
        severe_shellfish = (
            "shellfish_allergy" in dietary_rules and profile["allergy_severity"] == "severe"
        )
        vegan_required = "vegan" in dietary_rules
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
            if profile["allergy_severity"] == "severe" and (
                known_allergen_conflicts(set(_json(menu["allergen_tags_json"])), dietary_rules)
                - {"shellfish"}
            ):
                raise ValueError("CART_DIETARY_CONFLICT")
            if severe_shellfish:
                cursor.execute(
                    """
                    SELECT CASE WHEN
                      EXISTS (
                        SELECT 1 FROM menu_dietary_attribute mda
                        JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                        WHERE mda.menu_id=:id AND da.code='shellfish_sauce_absent'
                          AND mda.status='VERIFIED'
                      ) AND NOT EXISTS (
                        SELECT 1 FROM menu_allergen ma
                        JOIN allergen a ON a.allergen_id=ma.allergen_id
                        WHERE ma.menu_id=:id AND a.code='shellfish_risk'
                      ) THEN 1 ELSE 0 END FROM dual
                    """,
                    id=menu["menu_id"],
                )
                if int(cursor.fetchone()[0]) != 1:
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
                group_id = str(option["option_group_id"])
                selected_counts[group_id] = selected_counts.get(group_id, 0) + 1
                current_options.append(
                    {
                        "option_item_id": option["option_item_id"],
                        "name_en": option["name_en"],
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
            menu_snapshot_value = {"name_en": menu["name_en"], "price": unit_price}
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
                "base_catalog_counts_exact": counts == EXPECTED_RUNTIME_COUNTS,
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
                "menu_mappings_exact": supplemental_counts["mapped_menus"]
                == EXPECTED_MAPPED_MENUS,
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
            "canonical_ready": canonical and counts == EXPECTED_RUNTIME_COUNTS,
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
