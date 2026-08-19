from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from scripts.generate_menu_localizations import _generate_batch

from app.genai.contracts import GenAIErrorCode, GenAIProviderError


def _batch() -> list[dict[str, Any]]:
    return [
        {
            "menu_id": "menu-1",
            "name_ko": "비빔밥",
            "wiki_passages": [{"evidence_id": "wiki-1", "content": "A mixed rice dish."}],
        }
    ]


def _valid() -> str:
    return json.dumps(
        {"items": [{"menu_id": "menu-1", "name_en": "Bibimbap", "name_ja": "ビビンバ"}]}
    )


class _Provider:
    capabilities = SimpleNamespace(max_output_tokens=4_000, structured_output=False)

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.models: list[str] = []

    def create_response(self, model: str, **_request: Any) -> Any:
        self.models.append(model)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return SimpleNamespace(output_text=response)


def _settings() -> Any:
    return SimpleNamespace(menu_localization_model="xai.grok-4.3", oci_genai_fallback_model="gpt-oss-120b")


def test_empty_response_retries_the_same_model() -> None:
    provider = _Provider(["", _valid()])

    result, model = _generate_batch(provider, _settings(), _batch())

    assert result.items[0].name_en == "Bibimbap"
    assert model == "xai.grok-4.3"
    assert provider.models == ["xai.grok-4.3", "xai.grok-4.3"]


def test_invalid_english_name_retries_before_database_write() -> None:
    invalid = json.dumps(
        {"items": [{"menu_id": "menu-1", "name_en": "비빔밥", "name_ja": "ビビンバ"}]}
    )
    provider = _Provider([invalid, _valid()])

    result, _ = _generate_batch(provider, _settings(), _batch())

    assert result.items[0].name_en == "Bibimbap"
    assert provider.models == ["xai.grok-4.3", "xai.grok-4.3"]


def test_rate_limit_uses_only_the_fallback_model() -> None:
    provider = _Provider(
        [
            GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True),
            _valid(),
        ]
    )

    _, model = _generate_batch(provider, _settings(), _batch())

    assert model == "gpt-oss-120b"
    assert provider.models == ["xai.grok-4.3", "gpt-oss-120b"]


def test_persistent_schema_failure_does_not_change_models() -> None:
    provider = _Provider([""] * 10)

    with pytest.raises(ValueError, match="LOCALIZATION_RESPONSE_INVALID"):
        _generate_batch(provider, _settings(), _batch())

    assert provider.models == ["xai.grok-4.3"] * 10
