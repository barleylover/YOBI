#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.oracle_repository import OracleYobiRepository
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import Profile


def main() -> None:
    settings = Settings()
    repository = (
        OracleYobiRepository(settings)
        if settings.demo_db_backend == "oracle"
        else SQLiteYobiRepository(settings.sqlite_path)
    )
    try:
        repository.initialize()
        status = repository.status()
        profile = Profile(
            profile_id="prewarm",
            consent_demo_data=True,
            dietary_rules=["shellfish_allergy"],
            allergy_severity="severe",
            spice_tolerance=1,
            created_at=datetime.now(timezone.utc),
        )
        menus = repository.search_menus(
            "warm mild chicken noodle soup",
            profile,
            budget_krw=15_000,
            max_spiciness=1,
            excluded_ingredients=["pork"],
            limit=3,
        )
        if not menus:
            raise RuntimeError("PREWARM_CANONICAL_SEARCH_EMPTY")
        if not repository.prewarm_explanation("menu_003_01"):
            raise RuntimeError("PREWARM_EXPLANATION_CACHE_FAILED")

        genai = (
            "configured_no_duplicate_call"
            if settings.oci_genai_api_key.get_secret_value()
            else "not_configured"
        )

        nginx = "not_requested"
        health_base_url = os.getenv("YOBI_PREWARM_BASE_URL", "").rstrip("/")
        if health_base_url:
            for attempt in range(30):
                try:
                    response = httpx.get(f"{health_base_url}/healthz", timeout=5)
                    if response.status_code == 200 and response.json().get("status") == "ok":
                        nginx = "ready"
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                if attempt < 29:
                    time.sleep(1)
            if nginx != "ready":
                raise RuntimeError("PREWARM_NGINX_HEALTH_FAILED")

        print(
            json.dumps(
                {
                    "status": "ready",
                    "database": status.get("backend"),
                    "canonical_search_results": len(menus),
                    "genai": genai,
                    "explanation_cache": "ready",
                    "nginx": nginx,
                    "synthetic_data": True,
                },
                ensure_ascii=False,
            )
        )
    finally:
        close = getattr(repository, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
