#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings


def _required_secret(prompt: str) -> str:
    value = getpass.getpass(prompt)
    if not value:
        raise SystemExit("A required secret was empty; no database change was made.")
    return value


def main() -> None:
    dsn = os.getenv("ADB_DSN") or input("ADB DSN: ").strip()
    if not dsn:
        raise SystemExit("ADB DSN is required")
    admin_password = _required_secret("ADB ADMIN password: ")
    app_password = _required_secret("New YOBI_APP password: ")
    if len(app_password) < 12 or not re.search(r"[A-Za-z]", app_password) or not re.search(
        r"[0-9]", app_password
    ):
        raise SystemExit("YOBI_APP password must be at least 12 characters with letters and digits")

    with oracledb.connect(user="ADMIN", password=admin_password, dsn=dsn) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM dba_users WHERE username = 'YOBI_APP'")
        exists = bool(cursor.fetchone()[0])
        if not exists:
            cursor.execute('CREATE USER YOBI_APP IDENTIFIED BY "' + app_password.replace('"', '""') + '"')
            cursor.execute("ALTER USER YOBI_APP QUOTA UNLIMITED ON DATA")
            cursor.execute("GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW TO YOBI_APP")
            connection.commit()
            print("Created YOBI_APP with least runtime schema privileges.")
        else:
            print("YOBI_APP already exists; password and grants were not changed.")

    if input("Run migrations now? [Y/n]: ").strip().lower() not in {"n", "no"}:
        os.environ["ADB_DSN"] = dsn
        os.environ["DB_USERNAME"] = "YOBI_APP"
        os.environ["DB_PASSWORD"] = app_password
        from migrate import migrate

        applied = migrate(Settings())
        print("Migrations:", ", ".join(applied) if applied else "already current")
    print("Bootstrap complete. No secret was printed or written to a file.")


if __name__ == "__main__":
    main()

