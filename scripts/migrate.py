#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import NamedTuple

import oracledb

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings

DELIMITER = "-- +YOBI STATEMENT"


class MigrationFile(NamedTuple):
    path: Path
    version: str
    checksum: str
    statements: tuple[str, ...]


def split_statements(sql: str) -> list[str]:
    statements = []
    for raw_statement in sql.split(DELIMITER):
        statement = raw_statement.strip()
        if not statement:
            continue
        first_code_line = next(
            (
                line.lstrip().upper()
                for line in statement.splitlines()
                if line.strip() and not line.lstrip().startswith("--")
            ),
            "",
        )
        if first_code_line.startswith(("BEGIN", "DECLARE")):
            statements.append(statement)
        else:
            statements.append(statement.rstrip(";"))
    return statements


def discover_migrations(directory: Path | None = None) -> list[MigrationFile]:
    migration_directory = directory or ROOT / "database" / "migrations"
    migrations: list[MigrationFile] = []
    seen_versions: set[str] = set()
    for path in sorted(migration_directory.glob("[0-9][0-9][0-9]_*.sql")):
        version = path.name.split("_", 1)[0]
        if version in seen_versions:
            raise RuntimeError(f"DUPLICATE_MIGRATION_VERSION:{version}")
        seen_versions.add(version)
        raw = path.read_bytes()
        statements = tuple(split_statements(raw.decode("utf-8")))
        if not statements:
            raise RuntimeError(f"EMPTY_MIGRATION:{path.name}")
        migrations.append(
            MigrationFile(
                path=path,
                version=version,
                checksum=hashlib.sha256(raw).hexdigest(),
                statements=statements,
            )
        )
    if not migrations:
        raise RuntimeError("NO_MIGRATIONS_FOUND")
    versions = [migration.version for migration in migrations]
    expected_versions = [f"{number:03d}" for number in range(1, len(migrations) + 1)]
    if versions != expected_versions:
        raise RuntimeError("NON_SEQUENTIAL_MIGRATION_SET")
    return migrations


def validate_migration_ledger(
    migrations: list[MigrationFile],
    applied: dict[str, tuple[str, str]],
) -> None:
    """Validate every known applied migration before executing pending DDL.

    Oracle DDL commits implicitly, so checksum or filename drift must be detected
    before the runner begins a new migration. Unknown newer ledger rows remain
    allowed so an older, backward-compatible application release can be restored.
    """

    for migration in migrations:
        record = applied.get(migration.version)
        if record is None:
            continue
        filename, checksum = record
        if filename != migration.path.name:
            raise RuntimeError(f"MIGRATION_FILENAME_MISMATCH:{migration.version}:{filename}")
        if checksum != migration.checksum:
            raise RuntimeError(f"MIGRATION_CHECKSUM_MISMATCH:{migration.path.name}")


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
    migrations = discover_migrations()
    applied_now: list[str] = []
    with oracledb.connect(user=settings.db_username, password=password, dsn=dsn) as connection:
        ensure_migration_table(connection)
        cursor = connection.cursor()
        cursor.execute("SELECT version, filename, checksum FROM schema_migration")
        applied = {
            str(version): (str(filename), str(checksum))
            for version, filename, checksum in cursor.fetchall()
        }
        validate_migration_ledger(migrations, applied)
        for migration in migrations:
            if migration.version in applied:
                continue
            for statement_index, statement in enumerate(migration.statements, start=1):
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    connection.rollback()
                    raise RuntimeError(
                        f"MIGRATION_STATEMENT_FAILED:{migration.path.name}:{statement_index}"
                    ) from exc
            try:
                cursor.execute(
                    """
                    INSERT INTO schema_migration(version, filename, checksum, applied_at)
                    VALUES (:version, :filename, :checksum, SYSTIMESTAMP)
                    """,
                    version=migration.version,
                    filename=migration.path.name,
                    checksum=migration.checksum,
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise RuntimeError(f"MIGRATION_LEDGER_WRITE_FAILED:{migration.path.name}") from exc
            applied_now.append(migration.path.name)
    return applied_now


if __name__ == "__main__":
    result = migrate(Settings())
    print("Applied:", ", ".join(result) if result else "none; schema is current")
