#!/usr/bin/env python3
"""Verify the SQL-first recommendation candidate plan without exposing SQL or IDs.

The Oracle mode is a release gate: it explains the same shared candidate query used
by the repository against the active release family, checks the bounded shape and
required indexes, and returns only aggregate plan metadata.  It never executes the
candidate SELECT, commits data, or prints DSNs, release IDs, bind values, or raw SQL.
SQLite mode provides a local shape regression; Oracle remains the deployment proof.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.concept_query import (
    build_concept_candidate_query,
    build_concept_preview_query,
)
from app.domain.structured_recommendation import RecommendationCriteriaV2
from build_external_knowledge_release import (
    build_plan as build_external_plan,
)
from build_external_knowledge_release import (
    verify_release_family,
)

CANDIDATE_LIMIT = 24
CORE_CATEGORIES = (
    "cuisine_origins",
    "flavors",
    "main_ingredients",
    "food_forms",
    "temperatures",
    "textures",
    "cooking_methods",
)
EXPECTED_INDEXES = (
    "IDX_CONCEPT_PREF_LOOKUP",
    "IDX_CONCEPT_PREF_CONCEPT",
    "IDX_MENU_CONCEPT_HIGH",
    "IDX_MENU_RECOMMEND_FILTER",
    "IDX_MENU_SOURCE_RESTRICT",
)
REQUIRED_PLAN_TABLES = (
    "CONCEPT_PREFERENCE_SUPPORT",
    "MENU_CONCEPT_MAP",
    "MENU",
    "MERCHANT",
)
_BIND_PATTERN = re.compile(r":([A-Za-z][A-Za-z0-9_]*)")


def _oracle_required_tables_planned(object_names: set[str]) -> bool:
    explicit_tables = set(REQUIRED_PLAN_TABLES) - {"MENU_CONCEPT_MAP"}
    mapping_access_present = bool(
        {"MENU_CONCEPT_MAP", "IDX_MENU_CONCEPT_HIGH"} & object_names
    )
    return explicit_tables <= object_names and mapping_access_present


def _criteria(category_code: str, option_code: str) -> RecommendationCriteriaV2:
    selections: dict[str, Any] = {
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
    if category_code not in CORE_CATEGORIES:
        raise RuntimeError("QUERY_PLAN_CORE_CATEGORY_INVALID")
    selections[category_code] = [option_code]
    return RecommendationCriteriaV2.model_validate(selections)


def _source_checks(sql: str, *, backend: str) -> dict[str, bool]:
    normalized = " ".join(sql.lower().split())
    support_position = normalized.find("from menu_concept_map mapping")
    menu_position = normalized.find("from menu join merchant")
    limit_text = (
        "fetch first :candidate_limit rows only"
        if backend == "oracle"
        else "limit :candidate_limit"
    )
    return {
        "menu_star_absent": "menu.*" not in normalized,
        "concept_support_first": (
            support_position >= 0
            and menu_position >= 0
            and support_position < menu_position
            and "join concept_preference_support support" in normalized
        ),
        "database_limit_bound": limit_text in normalized,
    }


def _binds(sql: str, parameters: dict[str, Any]) -> dict[str, Any]:
    names = set(_BIND_PATTERN.findall(sql))
    if not names <= parameters.keys():
        raise RuntimeError("QUERY_PLAN_BIND_MISSING")
    return {name: parameters[name] for name in names}


def _representative_context(
    cursor: Any,
    *,
    oracle: bool,
    scope: str,
) -> tuple[str, str, str, str, str]:
    if scope == "staged":
        external_plan = build_external_plan(cursor)
        staged_verification = verify_release_family(
            cursor,
            oracle,
            family_id=str(external_plan["release_family_id"]),
            require_active=False,
        )
        if not staged_verification["pass"]:
            raise RuntimeError("QUERY_PLAN_STAGED_FAMILY_INVALID")
        cursor.execute(
            """
            SELECT knowledge_release_id,certification_release_id
            FROM recommendation_release_family
            WHERE release_family_id=:family_id AND status IN ('READY','ACTIVE')
            """
            if oracle
            else """
            SELECT knowledge_release_id,certification_release_id
            FROM recommendation_release_family
            WHERE release_family_id=? AND status IN ('READY','ACTIVE')
            """,
            {"family_id": str(external_plan["release_family_id"])}
            if oracle
            else (str(external_plan["release_family_id"]),),
        )
    elif oracle:
        active_verification = verify_release_family(
            cursor,
            oracle,
            require_active=True,
        )
        if not active_verification["pass"]:
            raise RuntimeError("QUERY_PLAN_ACTIVE_FAMILY_INVALID")
        cursor.execute(
            """
            SELECT family.knowledge_release_id,family.certification_release_id
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
            """
        )
    else:
        active_verification = verify_release_family(
            cursor,
            oracle,
            require_active=True,
        )
        if not active_verification["pass"]:
            raise RuntimeError("QUERY_PLAN_ACTIVE_FAMILY_INVALID")
        cursor.execute(
            """
            SELECT family.knowledge_release_id,family.certification_release_id
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
            """
        )
    family = cursor.fetchone()
    if family is None:
        raise RuntimeError("QUERY_PLAN_ACTIVE_FAMILY_MISSING")
    knowledge_release_id, certification_release_id = map(str, family)

    category_binds = ",".join(f":category_{index}" for index in range(len(CORE_CATEGORIES)))
    category_parameters = {
        f"category_{index}": value for index, value in enumerate(CORE_CATEGORIES)
    }
    option_sql = f"""
        SELECT support.category_code,support.option_code,
               COUNT(DISTINCT mapping.menu_id) eligible_count
        FROM concept_preference_support support
        JOIN menu_concept_map mapping
          ON mapping.release_id=support.knowledge_release_id
         AND mapping.concept_id=support.concept_id
         AND mapping.mapping_status='MAPPED'
         AND mapping.confidence_band='high'
        JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
        WHERE support.knowledge_release_id=:knowledge_release_id
          AND support.support_status='SUPPORTED'
          AND support.category_code IN ({category_binds})
        GROUP BY support.category_code,support.option_code
        HAVING COUNT(DISTINCT mapping.menu_id)>=3
        ORDER BY eligible_count DESC,support.category_code,support.option_code
        {"FETCH FIRST 1 ROWS ONLY" if oracle else "LIMIT 1"}
    """
    cursor.execute(
        option_sql,
        {
            "knowledge_release_id": knowledge_release_id,
            **category_parameters,
        },
    )
    option = cursor.fetchone()
    if option is None:
        raise RuntimeError("QUERY_PLAN_REPRESENTATIVE_OPTION_MISSING")

    cursor.execute(
        """
        SELECT service_area_id,COUNT(*) merchant_count
        FROM merchant
        WHERE service_area_id IS NOT NULL
        GROUP BY service_area_id
        ORDER BY merchant_count DESC,service_area_id
        FETCH FIRST 1 ROWS ONLY
        """
        if oracle
        else """
        SELECT service_area_id,COUNT(*) merchant_count
        FROM merchant
        WHERE service_area_id IS NOT NULL
        GROUP BY service_area_id
        ORDER BY merchant_count DESC,service_area_id
        LIMIT 1
        """
    )
    area = cursor.fetchone()
    if area is None:
        raise RuntimeError("QUERY_PLAN_SERVICE_AREA_MISSING")
    return (
        knowledge_release_id,
        certification_release_id,
        str(option[0]),
        str(option[1]),
        str(area[0]),
    )


def _candidate_query(
    *,
    backend: str,
    knowledge_release_id: str,
    certification_release_id: str,
    category_code: str,
    option_code: str,
    service_area_id: str,
) -> tuple[
    str,
    dict[str, Any],
    str,
    dict[str, Any],
    dict[str, bool],
]:
    query = build_concept_candidate_query(
        dialect="oracle" if backend == "oracle" else "sqlite",
        criteria=_criteria(category_code, option_code),
        knowledge_release_id=knowledge_release_id,
        certification_release_id=certification_release_id,
        service_area_id=service_area_id,
        excluded_menu_ids=set(),
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=CANDIDATE_LIMIT,
    )
    preview = build_concept_preview_query(query)
    checks = _source_checks(query.sql, backend=backend)
    return (
        query.sql,
        _binds(query.sql, query.parameters),
        preview.sql,
        _binds(preview.sql, preview.parameters),
        checks,
    )


def _oracle_plan(connection: oracledb.Connection, *, scope: str) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        context = _representative_context(cursor, oracle=True, scope=scope)
        sql, parameters, preview_sql, preview_parameters, checks = _candidate_query(
            backend="oracle",
            knowledge_release_id=context[0],
            certification_release_id=context[1],
            category_code=context[2],
            option_code=context[3],
            service_area_id=context[4],
        )
        statement_id = "YOBI" + uuid4().hex[:20].upper()
        cursor.execute(
            f"EXPLAIN PLAN SET STATEMENT_ID = '{statement_id}' FOR {sql}",
            parameters,
        )
        cursor.execute(
            """
            SELECT id,parent_id,operation,options,object_name,object_type,
                   cardinality,cost
            FROM plan_table
            WHERE statement_id=:statement_id
            ORDER BY id
            """,
            statement_id=statement_id,
        )
        rows = cursor.fetchall()
        if not rows:
            raise RuntimeError("QUERY_PLAN_ROWS_MISSING")
        cursor.execute(preview_sql, preview_parameters)
        preview_row = cursor.fetchone()
        if preview_row is None:
            raise RuntimeError("QUERY_PLAN_CANDIDATE_COUNT_MISSING")
        eligible_menu_count = int(preview_row[0])
        eligible_merchant_count = int(preview_row[1])

        cursor.execute(
            """
            SELECT index_name FROM user_indexes
            WHERE index_name IN (
              'IDX_CONCEPT_PREF_LOOKUP','IDX_CONCEPT_PREF_CONCEPT',
              'IDX_MENU_CONCEPT_HIGH','IDX_MENU_RECOMMEND_FILTER',
              'IDX_MENU_SOURCE_RESTRICT'
            )
            """
        )
        available_indexes = {str(row[0]).upper() for row in cursor.fetchall()}
        object_names = {str(row[4]).upper() for row in rows if row[4]}
        used_expected = sorted(object_names & set(EXPECTED_INDEXES))
        index_access_count = sum(
            1
            for row in rows
            if "INDEX" in str(row[2] or "").upper()
            or str(row[5] or "").upper().startswith("INDEX")
        )
        root = next((row for row in rows if int(row[0] or 0) == 0), rows[0])
        root_cardinality = int(root[6]) if root[6] is not None else None
        table_estimates: dict[str, int] = {}
        for row in rows:
            object_name = str(row[4] or "").upper()
            cardinality = row[6]
            if object_name in REQUIRED_PLAN_TABLES and cardinality is not None:
                table_estimates[object_name.lower()] = max(
                    table_estimates.get(object_name.lower(), 0),
                    int(cardinality),
                )
        checks.update(
            {
                "actual_plan_present": bool(rows),
                "required_tables_planned": _oracle_required_tables_planned(
                    object_names
                ),
                "expected_indexes_available": available_indexes == set(EXPECTED_INDEXES),
                "expected_index_access_present": bool(used_expected),
                "candidate_estimate_bounded": (
                    root_cardinality is not None
                    and 0 <= root_cardinality <= CANDIDATE_LIMIT
                ),
                "representative_candidate_count_positive": eligible_menu_count >= 3,
            }
        )
        return {
            "backend": "oracle",
            "scope": scope,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "candidate_limit": CANDIDATE_LIMIT,
            "actual": {
                "eligible_menu_count": eligible_menu_count,
                "eligible_merchant_count": eligible_merchant_count,
            },
            "plan": {
                "operator_count": len(rows),
                "index_access_count": index_access_count,
                "used_expected_indexes": used_expected,
                "root_estimated_rows": root_cardinality,
                "table_estimated_rows": table_estimates,
            },
        }
    finally:
        connection.rollback()
        cursor.close()


def _sqlite_index_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    return {str(row[0]).upper() for row in rows}


def _sqlite_plan(path: Path, *, scope: str) -> dict[str, Any]:
    uri = f"file:{path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        cursor = connection.cursor()
        context = _representative_context(cursor, oracle=False, scope=scope)
        sql, parameters, preview_sql, preview_parameters, checks = _candidate_query(
            backend="sqlite",
            knowledge_release_id=context[0],
            certification_release_id=context[1],
            category_code=context[2],
            option_code=context[3],
            service_area_id=context[4],
        )
        rows = connection.execute("EXPLAIN QUERY PLAN " + sql, parameters).fetchall()
        preview_row = connection.execute(preview_sql, preview_parameters).fetchone()
        if preview_row is None:
            raise RuntimeError("QUERY_PLAN_CANDIDATE_COUNT_MISSING")
        eligible_menu_count = int(preview_row[0])
        eligible_merchant_count = int(preview_row[1])
        details = [str(row[3]).upper() for row in rows]
        available_indexes = _sqlite_index_names(connection)
        used_expected = sorted(
            index
            for index in EXPECTED_INDEXES
            if any(index in detail for detail in details)
        )
        checks.update(
            {
                "actual_plan_present": bool(rows),
                "required_tables_planned": all(
                    any(token in detail for detail in details)
                    for token in ("SUPPORT", "MAPPING", "MENU", "MERCHANT")
                ),
                "expected_indexes_available": set(EXPECTED_INDEXES)
                <= available_indexes,
                "expected_index_access_present": bool(used_expected),
                "representative_candidate_count_positive": eligible_menu_count >= 3,
            }
        )
        return {
            "backend": "sqlite",
            "scope": scope,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "candidate_limit": CANDIDATE_LIMIT,
            "actual": {
                "eligible_menu_count": eligible_menu_count,
                "eligible_merchant_count": eligible_merchant_count,
            },
            "plan": {
                "operator_count": len(rows),
                "index_access_count": sum("INDEX" in detail for detail in details),
                "used_expected_indexes": used_expected,
                "root_estimated_rows": None,
                "table_estimated_rows": {},
                "estimate_boundary": "sqlite_explain_query_plan_has_no_row_estimates",
            },
        }
    finally:
        connection.close()


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, oracledb.DatabaseError) and exc.args:
        code = getattr(exc.args[0], "code", None)
        return f"ORACLE_{code}" if isinstance(code, int) else "ORACLE_DATABASE_ERROR"
    value = str(exc)
    if value and len(value) <= 100 and all(
        character.isupper() or character.isdigit() or character == "_"
        for character in value
    ):
        return value
    return type(exc).__name__.upper()


def _oracle_connection(settings: Settings) -> oracledb.Connection:
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RuntimeError("ADB_DSN_AND_DB_PASSWORD_REQUIRED")
    return oracledb.connect(
        user=settings.db_username,
        password=password,
        dsn=dsn,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the bounded recommendation candidate query plan."
    )
    parser.add_argument("--backend", choices=("oracle", "sqlite"), required=True)
    parser.add_argument("--sqlite-path", type=Path)
    parser.add_argument("--scope", choices=("active", "staged"), default="active")
    parser.add_argument("--verify", action="store_true", required=True)
    args = parser.parse_args()
    try:
        if args.backend == "oracle":
            if args.sqlite_path is not None:
                raise RuntimeError("SQLITE_PATH_NOT_ALLOWED_FOR_ORACLE")
            with _oracle_connection(Settings()) as connection:
                payload = _oracle_plan(connection, scope=args.scope)
        else:
            if args.sqlite_path is None or not args.sqlite_path.is_file():
                raise RuntimeError("SQLITE_PATH_REQUIRED")
            payload = _sqlite_plan(args.sqlite_path, scope=args.scope)
        exit_code = 0 if payload["status"] == "PASS" else 1
    except Exception as exc:  # noqa: BLE001 - one sanitized JSON failure only
        payload = {"status": "FAIL", "error_code": _safe_error_code(exc)}
        exit_code = 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
