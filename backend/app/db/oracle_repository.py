from __future__ import annotations

import hashlib
import json
from array import array
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import oracledb

from app.core.config import Settings
from app.db.oracle_pool import OraclePool
from app.db.seed_data import CATALOG_VERSION
from app.domain.dietary import known_allergen_conflicts
from app.domain.models import (
    AddressCandidate,
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
from app.rag.providers import choose_embedding_provider


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


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
            cursor.execute("SELECT session_id FROM chat_session WHERE profile_id = :id", id=profile_id)
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
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_message(self, session_id: str, role: str, content: str, message_type: str) -> str:
        message_id = _id("msg")
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO chat_message(message_id, session_id, role, content, message_type, created_at)
                VALUES (:1,:2,:3,:4,:5,:6)
                """,
                [message_id, session_id, role, content, message_type, _now()],
            )
        return message_id

    def list_messages(self, session_id: str) -> list[dict[str, str]]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT message_id, role, content, message_type, created_at
                FROM chat_message WHERE session_id = :id ORDER BY created_at, message_id
                """,
                id=session_id,
            )
            rows = _rows(cursor)
        return [{key: str(value) for key, value in row.items()} for row in rows]

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
    ) -> list[MenuSummary]:
        budget = budget_krw or 30000
        spice = max_spiciness if max_spiciness is not None else max(profile.spice_tolerance, 1)
        query_vector = array(
            "f", self.embedding_provider.embed([query], "SEARCH_QUERY")[0]
        )
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
                    VECTOR_DISTANCE(m.embedding_vector, :query_vector, COSINE) AS vector_distance,
                    NVL((
                      SELECT MIN(VECTOR_DISTANCE(rv.embedding_vector, :query_vector, COSINE))
                      FROM review_snippet rv
                      WHERE rv.menu_id=m.menu_id AND rv.embedding_vector IS NOT NULL
                    ), 1) AS review_distance,
                    NVL((
                      SELECT MIN(VECTOR_DISTANCE(k.embedding_vector, :query_vector, COSINE))
                      FROM menu_knowledge k
                      WHERE k.menu_id=m.menu_id AND k.embedding_vector IS NOT NULL
                    ), 1) AS knowledge_distance
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
                candidate_limit=max(limit * 5, 20),
            )
            rows = _rows(cursor)

        lowered = query.lower()
        scored: list[tuple[float, dict[str, Any], list[str], list[str], EvidenceStatus]] = []
        for row in rows:
            tags = set(_json(row["dietary_tags_json"]))
            allergens = set(_json(row["allergen_tags_json"]))
            if severe_allergies and known_allergen_conflicts(
                allergens, set(profile.dietary_rules)
            ):
                continue
            menu_similarity = max(0.0, 1.0 - float(row["vector_distance"]))
            review_similarity = max(0.0, 1.0 - float(row["review_distance"]))
            knowledge_similarity = max(0.0, 1.0 - float(row["knowledge_distance"]))
            similarity = (
                0.6 * menu_similarity + 0.25 * review_similarity + 0.15 * knowledge_similarity
            )
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
            scored.append((similarity + boost, row, reasons, risks, status))
        scored.sort(key=lambda item: (item[0], -int(item[1]["price"])), reverse=True)
        menus = [
            self._menu_summary(row, reasons, risks, status, score)
            for score, row, reasons, risks, status in scored[:limit]
        ]
        return [
            menu.model_copy(
                update={"evidence_ids": [item.evidence_id for item in self.get_evidence(menu.menu_id)]}
            )
            for menu in menus
        ]

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
        return menu.model_copy(
            update={"evidence_ids": [item.evidence_id for item in self.get_evidence(menu_id)]}
        )

    def list_merchant_menus(
        self,
        merchant_id: str,
        profile: Profile,
        excluded_menu_ids: list[str],
        limit: int = 12,
    ) -> list[MenuSummary]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM (
                  SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
                  FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                  WHERE m.merchant_id=:merchant_id AND m.availability='AVAILABLE'
                    AND m.spice_level<=:spice
                  ORDER BY m.price, m.menu_id
                ) WHERE ROWNUM<=:candidate_limit
                """,
                merchant_id=merchant_id,
                spice=profile.spice_tolerance,
                candidate_limit=max(limit * 3, 24),
            )
            rows = _rows(cursor)
        excluded = set(excluded_menu_ids)
        rules = set(profile.dietary_rules)
        output: list[MenuSummary] = []
        for row in rows:
            if row["menu_id"] in excluded:
                continue
            tags = set(_json(row["dietary_tags_json"]))
            allergens = set(_json(row["allergen_tags_json"]))
            if profile.allergy_severity == "severe" and known_allergen_conflicts(allergens, rules):
                continue
            if "shellfish_allergy" in rules and profile.allergy_severity == "severe" and "shellfish_sauce_absent" not in tags:
                continue
            if "vegan" in rules and "vegan_option" not in tags:
                continue
            status = EvidenceStatus.VERIFIED if "shellfish_sauce_absent" in tags else EvidenceStatus.UNKNOWN
            menu = self._menu_summary(
                row,
                ["More from the restaurant already selected"],
                ["Cross-contamination is not verified"],
                status,
                1.0,
            )
            output.append(menu.model_copy(update={"evidence_ids": [item.evidence_id for item in self.get_evidence(menu.menu_id)]}))
            if len(output) >= limit:
                break
        return output

    def get_evidence(self, menu_id: str) -> list[Evidence]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM evidence WHERE subject_id=:id ORDER BY evidence_id", id=menu_id
            )
            rows = _rows(cursor)
        return [Evidence(**row) for row in rows]

    def compare_merchants(
        self, category: str, profile: Profile, limit: int = 3
    ) -> list[MerchantComparison]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM (
                  SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min,
                    r.eta_max, r.flavor_profile, r.packaging_signal
                  FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                  WHERE LOWER(m.category)=LOWER(:category) AND m.availability='AVAILABLE'
                  ORDER BY m.price, r.eta_min
                ) WHERE ROWNUM <= :limit
                """,
                category=category,
                limit=limit,
            )
            rows = _rows(cursor)
        result = []
        for index, row in enumerate(rows):
            allergens = set(_json(row["allergen_tags_json"]))
            tags = set(_json(row["dietary_tags_json"]))
            status = EvidenceStatus.UNKNOWN
            note = "Ingredient and cross-contamination details are not verified."
            if "shellfish_risk" in allergens:
                status = EvidenceStatus.RISK_SIGNAL
                note = "Synthetic reviews contain a shellfish risk signal."
            elif "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
                note = "Sauce marked seafood-free; cross-contamination remains unknown."
            result.append(
                MerchantComparison(
                    merchant_id=row["merchant_id"],
                    merchant_name=row["merchant_name"],
                    menu_id=row["menu_id"],
                    menu_name=row["name_en"],
                    price=int(row["price"]),
                    delivery_fee=int(row["delivery_fee"]),
                    eta=f"{int(row['eta_min'])}-{int(row['eta_max'])} min",
                    portion=("One-person portion" if row["serves_max"] == 1 else "Shareable portion"),
                    flavor=row["flavor_profile"],
                    packaging_signal=row["packaging_signal"],
                    dietary_status=status,
                    dietary_note=note,
                    best_for=(
                        "First-time visitors who prefer a milder, creamier dish"
                        if index == 0
                        else "Travellers prioritising value and a larger portion"
                    ),
                )
            )
        return [
            item.model_copy(
                update={
                    "evidence_ids": [
                        evidence.evidence_id for evidence in self.get_evidence(item.menu_id)
                    ]
                }
            )
            for item in result
        ]

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
            cursor.execute("SELECT * FROM address_place ORDER BY place_id")
            rows = _rows(cursor)
        normalized = text.lower().strip()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            aliases = _json(row["aliases_json"])
            haystack = " ".join([row["name_en"], row["name_ko"], *aliases]).lower()
            score = 0.98 if row["place_id"] == "hotel_demo_01" and "myeongdong" in normalized else 0.0
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
            cursor.execute("SELECT * FROM address_place WHERE place_id=:id", id=place_id)
            row = _row(cursor)
        if row is None:
            return None
        return AddressCandidate(
            place_id=row["place_id"],
            hotel_name=row["name_en"],
            road_address=row["road_address"],
            postal_code=row["postal_code"],
            city=row["city"],
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
                INSERT INTO address_ref(address_ref_id,session_id,source_type,source_image_hash,
                  place_id,hotel_name,road_address,extraction_confidence,confirmed,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,1,:9)
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
                    _now(),
                ],
            )
            cart_id = self._ensure_cart(connection, session_id)
            cursor.execute(
                "UPDATE cart SET address_ref_id=:address,version=version+1,updated_at=:now WHERE cart_id=:cart",
                address=address_ref_id,
                now=_now(),
                cart=cart_id,
            )
        return address_ref_id

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

    def add_cart_item(self, session_id: str, item: CartItemInput) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            menu, options, line_total = self._cart_item_values(connection, item)
            cart_id = self._ensure_cart(connection, session_id)
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
                  menu_snapshot_json,option_snapshot_json,line_total,user_note,korean_note,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12)
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
                    item.user_note,
                    self._translate_note(item.user_note),
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
                user_note=item.user_note if item.user_note is not None else existing["user_note"],
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
                menu_snapshot=json.dumps(
                    {"name_en": menu["name_en"], "price": int(menu["price"])}
                ),
                option_snapshot=json.dumps(options),
                line_total=line_total,
                user_note=replacement.user_note,
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
            cursor.execute("SELECT 1 FROM delivery_preference WHERE cart_id=:id", id=cart["cart_id"])
            has_delivery = cursor.fetchone() is not None
            cursor.execute(
                """
                SELECT p.dietary_rules_json, p.allergy_severity
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
            if profile_row and rows:
                dietary_rules = set(_json(profile_row["dietary_rules_json"]))
                severe_shellfish = (
                    "shellfish_allergy" in dietary_rules
                    and profile_row["allergy_severity"] == "severe"
                )
                vegan_required = "vegan" in dietary_rules
                for row in rows:
                    conflicts = known_allergen_conflicts(
                        set(_json(row["allergen_tags_json"])), dietary_rules
                    ) if profile_row["allergy_severity"] == "severe" else set()
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
                                dietary_conflicts.append(
                                    f"Remove {option['name_en']} to continue."
                                )
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
        warnings = list(dict.fromkeys(dietary_conflicts))
        if items:
            warnings.append("Synthetic evidence only; cross-contamination may be unverified.")
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
            confirmed=bool(cart["confirmed"]),
        )

    def update_delivery(
        self, session_id: str, preference: DeliveryPreferenceInput
    ) -> CartPreview:
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
                b_user_note=preference.user_note,
                b_korean_note=korean,
                b_back_translation=preference.user_note,
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
    ) -> tuple[str, bool, bool, int]:
        """Lock, validate, and reprice a cart from authoritative Oracle rows."""
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM cart WHERE session_id=:id FOR UPDATE", id=session_id)
        cart = _row(cursor)
        if not cart:
            raise ValueError("CART_INCOMPLETE")
        cursor.execute(
            """
            SELECT p.dietary_rules_json, p.allergy_severity
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
            SELECT 1 FROM address_ref
            WHERE address_ref_id=:address AND session_id=:session_id AND confirmed=1
            """,
            address=cart["address_ref_id"],
            session_id=session_id,
        )
        address_ok = cursor.fetchone() is not None
        cursor.execute("SELECT 1 FROM delivery_preference WHERE cart_id=:id", id=cart["cart_id"])
        delivery_ok = cursor.fetchone() is not None
        cursor.execute(
            "SELECT * FROM cart_item WHERE cart_id=:id ORDER BY created_at", id=cart["cart_id"]
        )
        lines = _rows(cursor)
        if not address_ok or not delivery_ok or not lines:
            raise ValueError("CART_INCOMPLETE")

        dietary_rules = set(_json(profile["dietary_rules_json"]))
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
                SELECT m.*, r.delivery_fee, r.min_order_amount
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.menu_id=:id AND m.availability='AVAILABLE'
                """,
                id=line["menu_id"],
            )
            menu = _row(cursor)
            if not menu:
                raise ValueError("CART_MENU_UNAVAILABLE")
            if menu["merchant_id"] != line["merchant_id"]:
                raise ValueError("CART_MERCHANT_MISMATCH")
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
                SELECT option_group_id, min_select, max_select
                FROM menu_option_group WHERE menu_id=:id
                """,
                id=menu["menu_id"],
            )
            groups = _rows(cursor)
            if any(
                selected_counts.get(str(group["option_group_id"]), 0) < int(group["min_select"])
                or selected_counts.get(str(group["option_group_id"]), 0)
                > int(group["max_select"])
                for group in groups
            ):
                raise ValueError("CART_OPTION_SELECTION_INVALID")

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
            "SELECT min_order_amount, delivery_fee FROM merchant WHERE merchant_id=:id",
            id=next(iter(merchant_ids)),
        )
        merchant = _row(cursor)
        if merchant is None or subtotal < int(merchant["min_order_amount"]):
            raise ValueError("MINIMUM_ORDER_NOT_MET")

        was_confirmed = bool(cart["confirmed"])
        if confirm:
            cursor.execute(
                """
                UPDATE cart SET confirmed=1,version=version+1,updated_at=:now
                WHERE cart_id=:id
                """,
                now=_now(),
                id=cart["cart_id"],
            )
        elif changed:
            cursor.execute(
                """
                UPDATE cart SET confirmed=0,version=version+1,updated_at=:now
                WHERE cart_id=:id
                """,
                now=_now(),
                id=cart["cart_id"],
            )
        return (
            str(cart["cart_id"]),
            changed,
            was_confirmed,
            subtotal + int(merchant["delivery_fee"]),
        )

    def confirm_cart(self, session_id: str) -> CartPreview:
        with self.pool.connection() as connection:
            self._revalidate_cart(connection, session_id, confirm=True)
        return self.get_cart(session_id)

    def create_checkout(self, session_id: str, data: CheckoutCreate) -> Checkout:
        changed = False
        checkout: Checkout | None = None
        with self.pool.connection() as connection:
            cart_id, changed, was_confirmed, current_total = self._revalidate_cart(
                connection, session_id, confirm=False
            )
            if not was_confirmed:
                raise ValueError("CART_NOT_CONFIRMED")
            if changed:
                # Let the transaction commit the refreshed snapshot and reset flag.
                pass
            else:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT * FROM mock_checkout WHERE idempotency_key=:key",
                    key=data.idempotency_key,
                )
                existing = _row(cursor)
                if existing:
                    if existing["cart_id"] != cart_id:
                        raise ValueError("IDEMPOTENCY_KEY_REUSED")
                    checkout = self._checkout(existing)
                else:
                    checkout_id = _id("checkout")
                    now = _now()
                    cursor.execute(
                        """
                        INSERT INTO mock_checkout(checkout_id,cart_id,idempotency_key,payment_method,
                          status,amount,payment_url,created_at,updated_at)
                        VALUES (:1,:2,:3,:4,'PENDING',:5,:6,:7,:8)
                        """,
                        [
                            checkout_id,
                            cart_id,
                            data.idempotency_key,
                            data.payment_method,
                            current_total,
                            f"/pay/{checkout_id}",
                            now,
                            now,
                        ],
                    )
                    cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
                    row = _row(cursor)
                    if row is None:
                        raise RuntimeError("CHECKOUT_CREATION_FAILED")
                    checkout = self._checkout(row)
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
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id=:id FOR UPDATE", id=checkout_id
            )
            row = _row(cursor)
            if not row:
                raise KeyError("CHECKOUT_NOT_FOUND")
            if row["status"] == "SUCCEEDED" and status != "SUCCEEDED":
                raise ValueError("PAYMENT_ALREADY_SUCCEEDED")
            cursor.execute(
                "UPDATE mock_checkout SET status=:status,updated_at=:now WHERE checkout_id=:id",
                status=status,
                now=_now(),
                id=checkout_id,
            )
            order_id = None
            if status == "SUCCEEDED":
                cursor.execute("SELECT order_id FROM mock_order WHERE checkout_id=:id", id=checkout_id)
                existing = cursor.fetchone()
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
                        INSERT INTO mock_order(order_id,checkout_id,cart_snapshot_json,order_status,
                          estimated_delivery_at,created_at)
                        VALUES (:1,:2,:3,'CONFIRMED',:4,:5)
                        """,
                        [
                            order_id,
                            checkout_id,
                            json.dumps(snapshot),
                            _now() + timedelta(minutes=35),
                            _now(),
                        ],
                    )
            cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
            updated = _row(cursor)
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
            connection.cursor().execute(
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
                cache_key=f"prewarm:{menu_id}:en",
                menu_id=menu_id,
                payload=payload,
                source_version=CATALOG_VERSION,
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
        cursor.execute("DELETE FROM chat_message WHERE session_id=:id", id=session_id)
        if delete_session:
            cursor.execute("DELETE FROM chat_session WHERE session_id=:id", id=session_id)
        else:
            cursor.execute(
                """
                UPDATE chat_session SET state=:state,selected_menu_id=NULL,
                  selected_merchant_id=NULL,updated_at=:now WHERE session_id=:id
                """,
                state=ChatState.DISCOVERY.value,
                now=_now(),
                id=session_id,
            )

    def status(self) -> dict[str, object]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            counts = {}
            for table in (
                "merchant",
                "menu",
                "menu_option_item",
                "review_snippet",
                "evidence",
                "address_place",
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM menu WHERE menu_id IN ('menu_001_01','menu_002_01','menu_003_01')"
            )
            canonical = int(cursor.fetchone()[0]) == 3
            cursor.execute(
                """
                SELECT VECTOR_DISTANCE(embedding_vector, embedding_vector, COSINE)
                FROM menu WHERE embedding_vector IS NOT NULL FETCH FIRST 1 ROW ONLY
                """
            )
            vector_ready = cursor.fetchone() is not None
            cursor.execute("SELECT MAX(updated_at) FROM menu")
            last_seed_time = cursor.fetchone()[0]
        return {
            "backend": "oracle-26ai",
            "catalog_version": CATALOG_VERSION,
            "counts": counts,
            "canonical_ready": canonical,
            "vector_ready": vector_ready,
            "embedding_model": self.embedding_provider.model,
            "last_seed_time": str(last_seed_time) if last_seed_time else None,
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
