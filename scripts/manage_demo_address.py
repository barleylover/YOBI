#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.demo_address import (
    DEMO_ADDRESS_PLACE_ID,
    DEMO_ADDRESS_SERVICE_AREA_ID,
    demo_address_status,
    upsert_demo_address,
)


def manage(settings: Settings, *, apply: bool) -> dict[str, object]:
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
        cursor.execute("SELECT SYS_CONTEXT('USERENV','CURRENT_USER') FROM dual")
        current_user = str(cursor.fetchone()[0])
        if current_user.upper() != settings.db_username.upper() or current_user.upper() == "ADMIN":
            raise RuntimeError("ORACLE_RUNTIME_USER_MISMATCH")
        cursor.execute(
            """
            SELECT COUNT(*) FROM catalog_import_batch
            WHERE status='ACTIVE' AND data_origin='YOGIYO_PUBLIC_WEB'
            """
        )
        if int(cursor.fetchone()[0]) != 1:
            raise RuntimeError("ACTIVE_EXTERNAL_CATALOG_REQUIRED")
        cursor.execute(
            """
            SELECT COUNT(*) FROM service_area
            WHERE service_area_id=:service_area_id AND active=1
            """,
            service_area_id=DEMO_ADDRESS_SERVICE_AREA_ID,
        )
        if int(cursor.fetchone()[0]) != 1:
            raise RuntimeError("DEMO_ADDRESS_SERVICE_AREA_NOT_ACTIVE")
        if apply:
            try:
                upsert_demo_address(cursor, oracle=True)
                status = demo_address_status(cursor)
                if status["ready"] is not True:
                    raise RuntimeError("DEMO_ADDRESS_APPLY_VERIFICATION_FAILED")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        status = demo_address_status(cursor)
        if status["ready"] is not True:
            raise RuntimeError("DEMO_ADDRESS_NOT_READY")
    return {
        "backend": "oracle-26ai",
        "database_user": current_user,
        "place_id": DEMO_ADDRESS_PLACE_ID,
        "service_area_id": DEMO_ADDRESS_SERVICE_AREA_ID,
        "status": status,
        "transaction_committed": apply,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply", action="store_true")
    action.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = manage(Settings(), apply=bool(args.apply))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
