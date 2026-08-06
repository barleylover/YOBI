#!/usr/bin/env python3
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import oracledb
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ENV = Path("/etc/yobi/yobi.env")
CHECKPOINT = Path("/opt/yobi/shared/bootstrap_state.json")
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core.config import Settings


def secret(prompt: str) -> str:
    value = getpass.getpass(prompt)
    if not value:
        raise SystemExit("A required secret was empty; no runtime configuration was written.")
    return value


def validate_app_password(password: str) -> None:
    if "\n" in password or "\x00" in password or '"' in password:
        raise SystemExit("YOBI_APP password contains an unsupported character")
    if len(password) < 12 or not re.search(r"[A-Za-z]", password) or not re.search(
        r"[0-9]", password
    ):
        raise SystemExit("YOBI_APP password must be at least 12 characters with letters and digits")


def ensure_app_user(dsn: str, admin_password: str, app_password: str) -> None:
    with oracledb.connect(user="ADMIN", password=admin_password, dsn=dsn) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM dba_users WHERE username='YOBI_APP'")
        if cursor.fetchone()[0] == 0:
            quoted = app_password.replace('"', '""')
            cursor.execute(f'CREATE USER YOBI_APP IDENTIFIED BY "{quoted}"')
            cursor.execute("ALTER USER YOBI_APP QUOTA UNLIMITED ON DATA")
            cursor.execute("GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW TO YOBI_APP")
            connection.commit()
            print("Created YOBI_APP with schema-local privileges.")
        else:
            print("YOBI_APP already exists; credentials and grants were left unchanged.")


def write_env(dsn: str, app_password: str, api_key: str, control_token: str) -> None:
    def quote(value: str) -> str:
        if "\n" in value or "\x00" in value:
            raise SystemExit("A runtime value contains an unsupported control character")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    target = Path("/etc/yobi/yobi.env")
    lines = [
        f"APP_ENV={quote('production')}",
        f"APP_BASE_URL={quote('http://127.0.0.1')}",
        f"DEMO_MODE={quote('true')}",
        f"DEMO_FALLBACK_ENABLED={quote('true')}",
        f"DEMO_DB_BACKEND={quote('oracle')}",
        "OCI_GENAI_BASE_URL="
        + quote("https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/v1"),
        f"OCI_GENAI_API_KEY={quote(api_key)}",
        f"OCI_GENAI_MODEL={quote('xai.grok-4.3')}",
        f"OCI_GENAI_FALLBACK_MODEL={quote('openai.gpt-oss-120b')}",
        f"OCI_EMBED_MODEL={quote('cohere.embed-v4.0')}",
        f"OCI_EMBED_DIMENSION={quote('1536')}",
        f"ADB_DSN={quote(dsn)}",
        f"DB_USERNAME={quote('YOBI_APP')}",
        f"DB_PASSWORD={quote(app_password)}",
        f"LLM_TIMEOUT_SECONDS={quote('120')}",
        f"LLM_MAX_RETRIES={quote('0')}",
        f"TOOL_CALL_MAX_STEPS={quote('6')}",
        f"MAX_UPLOAD_MB={quote('8')}",
        f"ADDRESS_OCR_PROVIDER={quote('fixture')}",
        f"LOG_LEVEL={quote('INFO')}",
        f"DEMO_CONTROL_TOKEN={quote(control_token)}",
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)
    os.chown(target, 0, 0)


def checkpoint(step: str, status: str, **safe_details: object) -> None:
    state: dict[str, object] = {}
    if CHECKPOINT.is_file():
        try:
            loaded = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, json.JSONDecodeError):
            state = {}
    state[step] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **safe_details,
    }
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    temporary = CHECKPOINT.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.chown(temporary, 0, 0)
    temporary.replace(CHECKPOINT)


def checkpoint_complete(step: str) -> bool:
    if not CHECKPOINT.is_file():
        return False
    try:
        state = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    value = state.get(step, {}) if isinstance(state, dict) else {}
    return isinstance(value, dict) and value.get("status") == "complete"


def checkpoint_status(step: str) -> str | None:
    if not CHECKPOINT.is_file():
        return None
    try:
        state = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = state.get(step, {}) if isinstance(state, dict) else {}
    status = value.get("status") if isinstance(value, dict) else None
    return str(status) if status else None


def load_runtime_env() -> bool:
    if not RUNTIME_ENV.is_file():
        return False
    values = dotenv_values(RUNTIME_ENV)
    required = {"ADB_DSN", "DB_PASSWORD", "OCI_GENAI_API_KEY", "DEMO_CONTROL_TOKEN"}
    if any(not values.get(key) for key in required):
        raise SystemExit("Runtime environment exists but is missing a required value")
    os.environ.update({key: value for key, value in values.items() if value is not None})
    return True


def verify_database(settings: Settings) -> dict[str, object]:
    dsn = settings.adb_dsn.get_secret_value()
    username = settings.db_username
    password = settings.db_password.get_secret_value()
    required_tables = {"CHAT_SESSION", "MENU", "EXPLANATION_CACHE", "AUDIT_LOG"}
    with oracledb.connect(user=username, password=password, dsn=dsn) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT USER FROM dual")
        current_user = str(cursor.fetchone()[0])
        cursor.execute(
            "SELECT version, filename FROM schema_migration ORDER BY applied_at, version"
        )
        migration_rows = [(str(row[0]), str(row[1])) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT table_name FROM user_tables WHERE table_name IN "
            "('CHAT_SESSION','MENU','EXPLANATION_CACHE','AUDIT_LOG')"
        )
        tables = {str(row[0]) for row in cursor.fetchall()}
    migrations = {version for version, _ in migration_rows}
    expected_migrations = {"001", "002", "003"}
    if current_user != "YOBI_APP":
        raise RuntimeError("BOOTSTRAP_RUNTIME_USER_MISMATCH")
    if not expected_migrations.issubset(migrations):
        raise RuntimeError("BOOTSTRAP_MIGRATION_RECORD_MISSING")
    if not required_tables.issubset(tables):
        raise RuntimeError("BOOTSTRAP_REQUIRED_TABLE_MISSING")
    return {
        "runtime_user": current_user,
        "migration_records": [filename for _, filename in migration_rows],
        "required_tables_verified": len(required_tables),
    }


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run on yobi-app-01 with sudo /opt/yobi/current/venv/bin/python ...")
    resumed = load_runtime_env()
    if resumed:
        print("Protected runtime environment found; resuming without secret prompts.")
    else:
        dsn = os.getenv("ADB_DSN") or input("ADB TLS DSN (private endpoint): ").strip()
        if not dsn:
            raise SystemExit("ADB DSN is required")
        admin_password = secret("ADB ADMIN password (not stored): ")
        app_password = secret("YOBI_APP password: ")
        validate_app_password(app_password)
        api_key = secret("OCI Generative AI API key secret: ")
        control_token = secret("Demo control token: ")
        ensure_app_user(dsn, admin_password, app_password)
        os.environ.update(
            {
                "APP_ENV": "production",
                "DEMO_DB_BACKEND": "oracle",
                "ADB_DSN": dsn,
                "DB_USERNAME": "YOBI_APP",
                "DB_PASSWORD": app_password,
                "OCI_GENAI_API_KEY": api_key,
                "OCI_GENAI_FALLBACK_MODEL": "openai.gpt-oss-120b",
                "LLM_MAX_RETRIES": "0",
            }
        )
    from migrate import migrate

    settings = Settings()
    applied = migrate(settings)
    print("Migrations:", ", ".join(applied) if applied else "already current")
    database_status = verify_database(settings)
    checkpoint("database", "complete", **database_status)
    if not resumed:
        write_env(dsn, app_password, api_key, control_token)
        print(
            "Runtime configuration written root:root with mode 0600; "
            "ADMIN password was not stored."
        )

    primary_status = checkpoint_status("genai_smoke")
    if primary_status not in {"complete", "degraded"}:
        smoke = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "genai_smoke.py")], check=False
        )
        if smoke.returncode != 0:
            checkpoint(
                "genai_smoke",
                "degraded",
                safe_error_code="PRIMARY_MODEL_SMOKE_UNAVAILABLE",
                fallback_required=True,
            )
            print(
                "Primary Grok smoke is degraded; continuing to the verified fallback model "
                "and deterministic continuity checkpoints.",
                file=sys.stderr,
            )
            primary_status = "degraded"
        else:
            checkpoint("genai_smoke", "complete")
            primary_status = "complete"
    else:
        print(
            f"GenAI smoke checkpoint already {primary_status}; skipped duplicate API calls."
        )

    if not checkpoint_complete("fallback_model_smoke"):
        fallback_smoke = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "genai_fallback_smoke.py")],
            check=False,
        )
        if fallback_smoke.returncode != 0:
            checkpoint(
                "fallback_model_smoke",
                "pending",
                safe_error_code="FALLBACK_MODEL_SMOKE_FAILED",
            )
            print(
                "Fallback-model smoke remains pending; completed checkpoints were retained. "
                "Re-run this same script to resume without secret prompts.",
                file=sys.stderr,
            )
            raise SystemExit(75)
        checkpoint("fallback_model_smoke", "complete")
    else:
        print("Fallback-model smoke checkpoint already complete; skipped duplicate API calls.")

    if not checkpoint_complete("seed"):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "seed_demo.py"), "--upsert"], check=True
        )
        checkpoint("seed", "complete")
    else:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "seed_demo.py"), "--verify-only"],
            check=True,
        )
        print("Seed checkpoint already complete; integrity verification passed.")

    if not checkpoint_complete("deterministic_fallback_smoke"):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "deterministic_fallback_smoke.py")],
            check=True,
        )
        checkpoint("deterministic_fallback_smoke", "complete")
    else:
        print("Deterministic fallback checkpoint already complete; skipped duplicate smoke.")
    try:
        subprocess.run(["systemctl", "restart", "yobi-api", "nginx"], check=True)
        prewarm_env = {**os.environ, "YOBI_PREWARM_BASE_URL": "http://127.0.0.1"}
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prewarm.py")],
            check=True,
            env=prewarm_env,
        )
        checkpoint("prewarm", "complete")
        subprocess.run(
            ["curl", "--fail", "--silent", "http://127.0.0.1/healthz"], check=True
        )
        subprocess.run(
            ["curl", "--fail", "--silent", "http://127.0.0.1/readyz"], check=True
        )
    except (subprocess.CalledProcessError, RuntimeError):
        checkpoint("services", "pending", safe_error_code="SERVICE_READINESS_FAILED")
        raise
    checkpoint("health_ready", "complete", health="ok", ready="ready")
    checkpoint("services", "complete")
    checkpoint(
        "bootstrap",
        "complete",
        primary_model_status=primary_status,
        fallback_model_status="complete",
        deterministic_fallback_status="complete",
    )
    print("Bootstrap complete: seed, services, prewarm, and local readiness passed.")


if __name__ == "__main__":
    main()
