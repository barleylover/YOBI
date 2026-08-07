#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import oracledb

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings

DELIMITER = "-- +YOBI STATEMENT"


def split_statements(sql: str) -> list[str]:
    statements = []
    for raw_statement in sql.split(DELIMITER):
        statement = raw_statement.strip()
        if not statement:
            continue
        if statement.upper().startswith(("BEGIN", "DECLARE")):
            statements.append(statement)
        else:
            statements.append(statement.rstrip(";"))
    return statements


def ensure_migration_table(connection: oracledb.Connection) -> None:
    cursor = connection.cursor()
    cursor.execute(
        """
        BEGIN
          EXECUTE IMMEDIATE 'CREATE TABLE schema_migration (
            version VARCHAR2(32) PRIMARY KEY,
            filename VARCHAR2(255) NOT NULL,
            checksum VARCHAR2(64) NOT NULL,
            applied_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
          )';
        EXCEPTION
          WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
        END;
        """
    )
    connection.commit()


def migrate(settings: Settings) -> list[str]:
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RuntimeError("ADB_DSN and DB_PASSWORD are required")
    applied_now: list[str] = []
    with oracledb.connect(user=settings.db_username, password=password, dsn=dsn) as connection:
        ensure_migration_table(connection)
        cursor = connection.cursor()
        for path in sorted((ROOT / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql")):
            version = path.name.split("_", 1)[0]
            raw = path.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            cursor.execute(
                "SELECT checksum FROM schema_migration WHERE version = :version",
                version=version,
            )
            row = cursor.fetchone()
            if row:
                if row[0] != checksum:
                    raise RuntimeError(f"MIGRATION_CHECKSUM_MISMATCH:{path.name}")
                continue
            for statement in split_statements(raw.decode("utf-8")):
                cursor.execute(statement)
            cursor.execute(
                """
                INSERT INTO schema_migration(version, filename, checksum, applied_at)
                VALUES (:version, :filename, :checksum, SYSTIMESTAMP)
                """,
                version=version,
                filename=path.name,
                checksum=checksum,
            )
            connection.commit()
            applied_now.append(path.name)
    return applied_now


if __name__ == "__main__":
    result = migrate(Settings())
    print("Applied:", ", ".join(result) if result else "none; schema is current")
