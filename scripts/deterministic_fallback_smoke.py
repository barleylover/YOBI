#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.oracle_repository import OracleYobiRepository
from app.domain.models import ProfileCreate
from app.services.chat_service import ChatService
from app.services.demo_control import DemoControl


def main() -> None:
    settings = Settings()
    if settings.demo_db_backend != "oracle":
        raise SystemExit("Deterministic deployment smoke requires the Oracle runtime backend")
    repository = OracleYobiRepository(settings)
    profile_id: str | None = None
    try:
        repository.initialize()
        profile = repository.create_profile(
            ProfileCreate(
                consent_demo_data=True,
                dietary_rules=["shellfish_allergy"],
                allergy_severity="severe",
                spice_tolerance=1,
            )
        )
        profile_id = profile.profile_id
        session = repository.create_session(profile.profile_id)
        control = DemoControl()
        control.set_mode("force_fallback")
        turn = ChatService(repository, settings, control).respond(
            session,
            profile,
            "I saw a red rice cake dish on the street. Can I order it?",
        )
        if not turn.fallback_used:
            raise RuntimeError("DETERMINISTIC_FALLBACK_NOT_USED")
        if "avoid" not in turn.text.lower():
            raise RuntimeError("DETERMINISTIC_SAFETY_WARNING_MISSING")
        if not any(card.type == "dietary_evidence" for card in turn.cards):
            raise RuntimeError("DETERMINISTIC_EVIDENCE_CARD_MISSING")
        print("PASS: deterministic fallback over Oracle with dietary evidence")
    finally:
        if profile_id is not None:
            repository.delete_profile(profile_id)
        repository.pool.close()


if __name__ == "__main__":
    main()
