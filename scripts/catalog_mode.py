#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.oracle_repository import OracleYobiRepository


def active_external_import(settings: Settings) -> dict[str, Any] | None:
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RuntimeError("ADB_DSN_AND_DB_PASSWORD_REQUIRED")
    with oracledb.connect(
        user=settings.db_username,
        password=password,
        dsn=dsn,
    ) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT catalog_import_id,catalog_release_id,data_origin,status,
                       package_sha256,completed_at
                FROM catalog_import_batch
                WHERE status='ACTIVE' AND data_origin='YOGIYO_PUBLIC_WEB'
                ORDER BY completed_at DESC FETCH FIRST 1 ROWS ONLY
                """
            )
        except oracledb.DatabaseError as exc:
            error = exc.args[0]
            if getattr(error, "code", None) == 942:
                return None
            raise
        row = cursor.fetchone()
    if row is None:
        return None
    return {
        "catalog_import_id": str(row[0]),
        "catalog_release_id": str(row[1]),
        "data_origin": str(row[2]),
        "status": str(row[3]),
        "package_sha256": str(row[4]),
        "completed_at": str(row[5]),
    }


def verify_external(settings: Settings) -> dict[str, Any]:
    active = active_external_import(settings)
    if active is None:
        raise RuntimeError("EXTERNAL_CATALOG_NOT_ACTIVE")
    status = OracleYobiRepository(settings).status()
    required = {
        "backend": status.get("backend") == "oracle-26ai",
        "catalog_mode": status.get("catalog_mode") == "EXTERNAL_SOURCE",
        "catalog_import_id": status.get("catalog_import_id") == active["catalog_import_id"],
        "source_integrity_ready": status.get("source_integrity_ready") is True,
        "recommendation_ready": status.get("recommendation_ready") is True,
        "canonical_ready": status.get("canonical_ready") is True,
        "knowledge_ready": status.get("knowledge_ready") is True,
        "vector_ready": status.get("vector_ready") is True,
        "data_origin": status.get("data_origin") == "YOGIYO_PUBLIC_WEB",
    }
    if not all(required.values()):
        raise RuntimeError(f"EXTERNAL_CATALOG_NOT_READY:{json.dumps(required, sort_keys=True)}")
    return {"active_import": active, "readiness": required}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("get-mode", "get-active", "verify-external"))
    args = parser.parse_args()
    settings = Settings()
    active = active_external_import(settings)
    if args.command == "get-mode":
        print("external" if active else "synthetic")
    elif args.command == "get-active":
        print(active["catalog_import_id"] if active else "")
    else:
        print(json.dumps(verify_external(settings), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
