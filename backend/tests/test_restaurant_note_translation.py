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
from app.services.restaurant_note_translation import (
    _TRANSLATION_SCHEMA,
    RestaurantNoteTranslationService,
)


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
        self.requests: list[dict[str, Any]] = []

    def supports_model(self, model: str) -> bool:
        return model in {
            "meta.llama-4-maverick-17b-128e-instruct-fp8",
            "openai.gpt-oss-20b",
            "openai.gpt-oss-120b",
        }

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append(model)
        self.requests.append(kwargs)
        result = self.plan[model]
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(
            output_text=result
            if isinstance(result, str)
            else json.dumps(result, ensure_ascii=False)
        )


def _session(repository: SQLiteYobiRepository) -> str:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    return repository.create_session(profile.profile_id).session_id


def _payload() -> dict[str, str]:
    return {
        "korean_text": "가능한 한 맵지 않게 해 주세요.",
        "back_translation": "Please make it as mild as possible.",
    }


def test_note_translation_uses_first_available_model_and_enables_cart_note(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider({"meta.llama-4-maverick-17b-128e-instruct-fp8": _payload()})
    service = RestaurantNoteTranslationService(repository, Settings(), provider=provider)

    translated = service.translate(
        session_id,
        RestaurantNoteTranslationInput(
            source_text="Please make it as mild as possible.",
            source_language="en",
        ),
    )

    assert translated.status == "SUCCEEDED"
    assert provider.calls == ["meta.llama-4-maverick-17b-128e-instruct-fp8"]
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


def test_note_translation_falls_back_to_next_model_on_rate_limit(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "meta.llama-4-maverick-17b-128e-instruct-fp8": GenAIProviderError(
                GenAIErrorCode.RATE_LIMIT, retryable=True
            ),
            "openai.gpt-oss-20b": _payload(),
        }
    )
    service = RestaurantNoteTranslationService(repository, Settings(), provider=provider)

    translated = service.translate(
        session_id,
        RestaurantNoteTranslationInput(source_text="No onions, please.", source_language="en"),
    )

    assert translated.status == "SUCCEEDED"
    assert translated.model_id == "openai.gpt-oss-20b"
    assert provider.calls == [
        "meta.llama-4-maverick-17b-128e-instruct-fp8",
        "openai.gpt-oss-20b",
    ]
    with repository._connection() as connection:
        attempts = connection.execute(
            "SELECT attempt_no,model_id,status,error_code "
            "FROM restaurant_note_translation_attempt "
            "WHERE session_id=? ORDER BY attempt_no",
            (session_id,),
        ).fetchall()
    assert [tuple(row) for row in attempts] == [
        (1, "meta.llama-4-maverick-17b-128e-instruct-fp8", "FAILED", "RATE_LIMIT"),
        (2, "openai.gpt-oss-20b", "SUCCEEDED", None),
    ]


def test_failed_note_translation_blocks_nonempty_note_but_allows_note_free_cart(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "meta.llama-4-maverick-17b-128e-instruct-fp8": GenAIProviderError(
                GenAIErrorCode.TIMEOUT, retryable=True
            ),
            "openai.gpt-oss-20b": GenAIProviderError(
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
    assert provider.calls == [
        "meta.llama-4-maverick-17b-128e-instruct-fp8",
        "openai.gpt-oss-20b",
    ]
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
    preview = repository.add_cart_item(
        session_id,
        CartItemInput(
            menu_id="menu_001_01",
            option_item_ids=["oi_001_01_spice_mild", "oi_001_01_size_regular"],
            user_note="",
            note_translation_id=None,
        ),
    )
    assert len(preview.items) == 1


def test_invalid_fenced_response_advances_to_next_model(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "meta.llama-4-maverick-17b-128e-instruct-fp8": "not json",
            "openai.gpt-oss-20b": f"```json\n{json.dumps(_payload(), ensure_ascii=False)}\n```",
        }
    )
    translated = RestaurantNoteTranslationService(
        repository, Settings(), provider=provider
    ).translate(
        session_id,
        RestaurantNoteTranslationInput(source_text="No onions, please.", source_language="en"),
    )

    assert translated.status == "SUCCEEDED"
    assert translated.model_id == "openai.gpt-oss-20b"


def test_non_structured_provider_receives_explicit_translation_contract(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider({"meta.llama-4-maverick-17b-128e-instruct-fp8": _payload()})
    provider.capabilities = provider.capabilities.model_copy(update={"structured_output": False})

    translated = RestaurantNoteTranslationService(
        repository, Settings(), provider=provider
    ).translate(
        session_id,
        RestaurantNoteTranslationInput(source_text="No onions, please.", source_language="en"),
    )

    assert translated.status == "SUCCEEDED"
    content = json.loads(provider.requests[0]["input"][0]["content"])
    assert content["response_contract"] == _TRANSLATION_SCHEMA


def test_note_translation_prompt_explains_restaurant_context_and_examples(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider({"meta.llama-4-maverick-17b-128e-instruct-fp8": _payload()})
    settings = Settings()

    RestaurantNoteTranslationService(repository, settings, provider=provider).translate(
        session_id,
        RestaurantNoteTranslationInput(
            source_text="Please pack the sauce separately.",
            source_language="en",
        ),
    )

    instructions = provider.requests[0]["instructions"]
    content = json.loads(provider.requests[0]["input"][0]["content"])
    assert "restaurant's kitchen or packing staff" in instructions
    assert "It is not a restaurant review" in instructions
    assert '"Please pack the sauce separately."' in instructions
    assert '"양파는 빼 주세요."' in instructions
    assert settings.restaurant_note_prompt_version in instructions
    assert content["message_stage"] == "restaurant_order_preparation"
    assert content["recipient"] == "restaurant kitchen or packing staff"


def test_note_translation_ignores_harmless_extra_json_fields(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "meta.llama-4-maverick-17b-128e-instruct-fp8": {
                **_payload(),
                "confidence": 0.98,
            }
        }
    )

    translated = RestaurantNoteTranslationService(
        repository, Settings(), provider=provider
    ).translate(
        session_id,
        RestaurantNoteTranslationInput(
            source_text="Please make it as mild as possible.",
            source_language="en",
        ),
    )

    assert translated.status == "SUCCEEDED"


def test_non_korean_translation_is_rejected_and_20b_can_recover(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "meta.llama-4-maverick-17b-128e-instruct-fp8": {
                "korean_text": "No onions, please.",
                "back_translation": "No onions, please.",
            },
            "openai.gpt-oss-20b": _payload(),
        }
    )

    translated = RestaurantNoteTranslationService(
        repository, Settings(), provider=provider
    ).translate(
        session_id,
        RestaurantNoteTranslationInput(source_text="No onions, please.", source_language="en"),
    )

    assert translated.status == "SUCCEEDED"
    assert translated.model_id == "openai.gpt-oss-20b"


def test_unsupported_configured_model_advances_to_a_working_model(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _session(repository)
    provider = PlannedProvider(
        {
            "meta.llama-4-maverick-17b-128e-instruct-fp8": GenAIProviderError(
                GenAIErrorCode.PROVIDER_UNAVAILABLE,
                retryable=False,
            ),
            "openai.gpt-oss-20b": _payload(),
        }
    )

    translated = RestaurantNoteTranslationService(
        repository,
        Settings(),
        provider=provider,
    ).translate(
        session_id,
        RestaurantNoteTranslationInput(
            source_text="Please leave it at reception.",
            source_language="en",
        ),
    )

    assert translated.status == "SUCCEEDED"
    assert provider.calls == [
        "meta.llama-4-maverick-17b-128e-instruct-fp8",
        "openai.gpt-oss-20b",
    ]
