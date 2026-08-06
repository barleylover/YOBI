#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings


def main() -> None:
    settings = Settings()
    checks = {
        "database_backend": settings.demo_db_backend,
        "runtime_user_is_least_privilege": settings.db_username.upper() != "ADMIN",
        "genai_endpoint_verified_path": settings.oci_genai_base_url.endswith(
            "/20231130/actions/v1"
        ),
        "embedding_dimension": settings.oci_embed_dimension,
        "genai_key_present": bool(settings.oci_genai_api_key.get_secret_value()),
        "adb_dsn_present": bool(settings.adb_dsn.get_secret_value()),
        "db_password_present": bool(settings.db_password.get_secret_value()),
        "frontend_built": (ROOT / "frontend" / "dist" / "index.html").exists(),
    }
    print(json.dumps(checks, indent=2))
    required = (
        checks["runtime_user_is_least_privilege"]
        and checks["genai_endpoint_verified_path"]
        and checks["embedding_dimension"] == 1536
        and checks["frontend_built"]
    )
    if not required:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
