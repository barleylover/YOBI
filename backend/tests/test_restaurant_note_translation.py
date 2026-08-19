from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import CartItemInput, ProfileCreate, RestaurantNoteTranslationInput
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)
from app.services.restaurant_note_translation import RestaurantNoteTranslationService


class PlannedProvider:
    configured = True
    capabilities = ProviderCapabilities(
        provider="fake",
        serving_mode=GenAIServingMode.ON_DEMAND,
        responses_api=True,
        function_calling=True,
        structured_output=True,
        native_streaming=False,
        client_managed_continuation=True,
        server_managed_continuation=False,
        max_input_tokens=32_768,
        max_output_tokens=4_096,
        max_tools_per_request=4,
        max_tool_calls_per_response=4,
    )

    def __init__(self, plan: dict[str, Any]) -> None:
        self.plan = plan
        self.calls: list[str] = []

    def supports_model(self, model: str) -> bool:
        return model in {"openai.gpt-oss-20b", "openai.gpt-oss-120b"}

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        del kwargs
        self.calls.append(model)
        result = self.plan[model]
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(output_text=json.dumps(result, ensure_ascii=False))


def _session(repository: SQLiteYobiRepository) -> str:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    return repository.create_session(profile.profile_id).session_id


def _payload() -> dict[str, str]:
    return {
        "korean_text": "가능한 한 맵지 않게 해 주세요.",
        "back_translation": "Please make it as mild as possible.",
    }


def test_note_translation_uses_20b_and_enables_cart_note(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider({"openai.gpt-oss-20b": _payload()})
    service = RestaurantNoteTranslationService(repository, Settings(), provider=provider)

    translated = service.translate(
        session_id,
        RestaurantNoteTranslationInput(
            source_text="Please make it as mild as possible.",
            source_language="en",
        ),
    )

    assert translated.status == "SUCCEEDED"
    assert provider.calls == ["openai.gpt-oss-20b"]
    preview = repository.add_cart_item(
        session_id,
        CartItemInput(
            menu_id="menu_001_01",
            option_item_ids=["oi_001_01_spice_mild", "oi_001_01_size_regular"],
            user_note=translated.source_text,
            note_translation_id=translated.translation_id,
        ),
    )
    assert len(preview.items) == 1
    with repository._connection() as connection:
        row = connection.execute(
            "SELECT korean_note,note_translation_id FROM cart_item WHERE cart_item_id=?",
            (preview.items[0].cart_item_id,),
        ).fetchone()
    assert row["korean_note"] == _payload()["korean_text"]
    assert row["note_translation_id"] == translated.translation_id


def test_note_translation_falls_back_from_20b_to_120b_on_rate_limit(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "openai.gpt-oss-20b": GenAIProviderError(
                GenAIErrorCode.RATE_LIMIT, retryable=True
            ),
            "openai.gpt-oss-120b": _payload(),
        }
    )
    service = RestaurantNoteTranslationService(repository, Settings(), provider=provider)

    translated = service.translate(
        session_id,
        RestaurantNoteTranslationInput(source_text="No onions, please.", source_language="en"),
    )

    assert translated.status == "SUCCEEDED"
    assert translated.model_id == "openai.gpt-oss-120b"
    assert provider.calls == ["openai.gpt-oss-20b", "openai.gpt-oss-120b"]


def test_failed_note_translation_blocks_nonempty_cart_note(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "openai.gpt-oss-20b": GenAIProviderError(
                GenAIErrorCode.TIMEOUT, retryable=True
            ),
            "openai.gpt-oss-120b": GenAIProviderError(
                GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=True
            ),
        }
    )
    service = RestaurantNoteTranslationService(repository, Settings(), provider=provider)
    failed = service.translate(
        session_id,
        RestaurantNoteTranslationInput(source_text="No onions, please.", source_language="en"),
    )

    assert failed.status == "FAILED"
    assert provider.calls == ["openai.gpt-oss-20b", "openai.gpt-oss-120b"]
    with pytest.raises(ValueError, match="RESTAURANT_NOTE_TRANSLATION_REQUIRED"):
        repository.add_cart_item(
            session_id,
            CartItemInput(
                menu_id="menu_001_01",
                option_item_ids=["oi_001_01_spice_mild", "oi_001_01_size_regular"],
                user_note=failed.source_text,
                note_translation_id=failed.translation_id,
            ),
        )
