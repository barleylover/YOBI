from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.domain.models import OptionGroup, OptionItem
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)
from app.genai.option_localization_generator import OptionLocalizationGenerator
from app.services.option_localization import OptionLocalizationService

ROOT = Path(__file__).resolve().parents[2]


class OptionProvider:
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
        max_output_tokens=16_384,
        max_tools_per_request=4,
        max_tool_calls_per_response=4,
    )

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def supports_model(self, model: str) -> bool:
        return model in {"openai.gpt-oss-20b", "openai.gpt-oss-120b"}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        return SimpleNamespace(
            output_text=json.dumps(self.output),
            usage={"input_tokens": 120, "output_tokens": 40},
        )


class SlowOptionProvider(OptionProvider):
    def create_response(self, model: str, **kwargs: Any) -> Any:
        time.sleep(0.05)
        return super().create_response(model, **kwargs)


class FallbackOptionProvider(OptionProvider):
    def __init__(self, plan: dict[str, Any]) -> None:
        super().__init__({})
        self.plan = plan

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model, **kwargs})
        result = self.plan[model]
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(
            output_text=json.dumps(result),
            usage={"input_tokens": 120, "output_tokens": 40},
        )


def _groups() -> list[OptionGroup]:
    return [
        OptionGroup(
            option_group_id="group-1",
            name_en="Eumryo chugaseontaek",
            name_ko="음료 추가선택",
            display_name="음료 추가선택",
            description="",
            required=False,
            min_select=0,
            max_select=2,
            items=[
                OptionItem(
                    option_item_id="item-1",
                    name_en="Koka kola 355ml chuga",
                    name_ko="코카콜라 355ml 추가",
                    display_name="코카콜라 355ml 추가",
                    description="",
                    price_delta=2000,
                    available=True,
                ),
                OptionItem(
                    option_item_id="item-2",
                    name_en="Seontaek anham",
                    name_ko="선택 안함",
                    display_name="선택 안함",
                    description="",
                    price_delta=0,
                    available=True,
                ),
            ],
        )
    ]


class OptionRepository:
    def __init__(self) -> None:
        self.groups = _groups()
        self.saved = False
        self.saved_prompt: str | None = None

    def get_options(self, menu_id: str, session_id: str | None = None) -> list[OptionGroup]:
        del menu_id, session_id
        return self.groups

    def get_session(self, session_id: str) -> Any:
        del session_id
        return SimpleNamespace(profile_id="profile-1")

    def get_profile(self, profile_id: str) -> Any:
        del profile_id
        return SimpleNamespace(preferred_language="English")

    def option_localizations_complete(
        self,
        session_id: str,
        menu_id: str,
        group_ids: list[str],
        item_ids: list[str],
        prompt_version: str,
    ) -> bool:
        del session_id, menu_id, group_ids, item_ids
        return self.saved and self.saved_prompt == prompt_version

    def load_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        prompt_version: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        del session_id, menu_id
        if not self.saved or self.saved_prompt != prompt_version:
            return {}, {}
        return (
            {group.option_group_id: group.display_name for group in self.groups},
            {
                item.option_item_id: item.display_name
                for group in self.groups
                for item in group.items
            },
        )

    def save_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        group_names: dict[str, str],
        item_names: dict[str, str],
        model_id: str,
        prompt_version: str,
    ) -> None:
        del session_id, menu_id, model_id
        group = self.groups[0]
        self.groups = [
            group.model_copy(
                update={
                    "display_name": group_names[group.option_group_id],
                    "items": [
                        item.model_copy(
                            update={"display_name": item_names[item.option_item_id]}
                        )
                        for item in group.items
                    ],
                }
            )
        ]
        self.saved = True
        self.saved_prompt = prompt_version


def test_generator_maps_ordered_strings_without_model_owned_ids() -> None:
    provider = OptionProvider(
        {
            "groups": [
                {
                    "display_name": "Drink add-ons",
                    "item_display_names": ["Add Coca-Cola 355ml", "None"],
                }
            ]
        }
    )
    generator = OptionLocalizationGenerator(Settings(), provider=provider)

    result = generator.generate(
        groups=[
            {
                "name_ko": "음료 추가선택",
                "items": [
                    {"name_ko": "코카콜라 355ml 추가"},
                    {"name_ko": "선택 안함"},
                ],
            }
        ],
        locale="English",
    )

    assert result.generation_model == "openai.gpt-oss-20b"
    assert result.groups[0].item_display_names == ["Add Coca-Cola 355ml", "None"]
    request_payload = json.loads(provider.calls[0]["input"][0]["content"])
    assert "option_group_id" not in json.dumps(request_payload)
    assert provider.calls[0]["max_output_tokens"] == 16_384


def test_generator_falls_back_from_20b_to_120b() -> None:
    translated = {
        "groups": [
            {
                "display_name": "Drink add-ons",
                "item_display_names": ["Add Coca-Cola 355ml", "None"],
            }
        ]
    }
    provider = FallbackOptionProvider(
        {
            "openai.gpt-oss-20b": GenAIProviderError(
                GenAIErrorCode.RATE_LIMIT,
                retryable=True,
            ),
            "openai.gpt-oss-120b": translated,
        }
    )

    result = OptionLocalizationGenerator(Settings(), provider=provider).generate(
        groups=[
            {
                "name_ko": "음료 추가선택",
                "items": [
                    {"name_ko": "코카콜라 355ml 추가"},
                    {"name_ko": "선택 안함"},
                ],
            }
        ],
        locale="English",
    )

    assert result.generation_model == "openai.gpt-oss-120b"
    assert [call["model"] for call in provider.calls] == [
        "openai.gpt-oss-20b",
        "openai.gpt-oss-120b",
    ]


def test_generator_merges_complementary_valid_labels_across_model_chain() -> None:
    provider = FallbackOptionProvider(
        {
            "openai.gpt-oss-20b": {
                "groups": [
                    {
                        "display_name": "Drink options",
                        "item_display_names": ["Add cola", "Soda"],
                    }
                ]
            },
            "openai.gpt-oss-120b": {
                "groups": [
                    {
                        "display_name": "Drink options",
                        "item_display_names": ["Add 1 cola", "Cider"],
                    }
                ]
            },
        }
    )
    attempts: list[tuple[str, str, str | None]] = []

    result = OptionLocalizationGenerator(Settings(), provider=provider).generate(
        groups=[
            {
                "name_ko": "음료 선택",
                "items": [
                    {"name_ko": "콜라 1개 추가"},
                    {"name_ko": "사이다"},
                ],
            }
        ],
        locale="English",
        on_provider_attempt=lambda model, status, error, _latency, _usage: attempts.append(
            (model, status, error)
        ),
    )

    assert result.groups[0].item_display_names == ["Add 1 cola", "Soda"]
    assert result.generation_model == "openai.gpt-oss-20b+openai.gpt-oss-120b"
    assert [attempt[1] for attempt in attempts] == ["FAILED", "SUCCEEDED"]
    assert attempts[0][2] == "OPTION_LOCALIZATION_NUMBER_MISMATCH:G0:I0"


def test_generator_accepts_spelled_number_with_preserved_quantity_unit() -> None:
    provider = OptionProvider(
        {
            "groups": [
                {
                    "display_name": "Drink options",
                    "item_display_names": ["Add one item of cola"],
                }
            ]
        }
    )

    result = OptionLocalizationGenerator(Settings(), provider=provider).generate(
        groups=[
            {
                "name_ko": "음료 선택",
                "items": [{"name_ko": "콜라 1개 추가"}],
            }
        ],
        locale="English",
    )

    assert result.groups[0].item_display_names == ["Add one item of cola"]


def test_selected_menu_options_generate_once_then_use_prompt_versioned_cache() -> None:
    repository = OptionRepository()
    provider = OptionProvider(
        {
            "groups": [
                {
                    "display_name": "Drink add-ons",
                    "item_display_names": ["Add Coca-Cola 355ml", "None"],
                }
            ]
        }
    )
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    first = service.get_options("menu-1", "session-1")
    second = service.get_options("menu-1", "session-1")

    assert first[0].display_name == "Drink add-ons"
    assert first[0].items[0].display_name == "Add Coca-Cola 355ml"
    assert second == first
    assert len(provider.calls) == 1
    assert repository.saved_prompt == settings.option_localization_prompt_version


def test_missing_option_string_is_rejected_without_cache_write() -> None:
    repository = OptionRepository()
    provider = OptionProvider(
        {
            "groups": [
                {
                    "display_name": "Drink add-ons",
                    "item_display_names": ["Add Coca-Cola 355ml"],
                }
            ]
        }
    )
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    result = service.get_options("menu-1", "session-1")

    assert result[0].display_name == "음료 추가선택"
    assert repository.saved is False


def test_concurrent_duplicate_option_requests_share_one_generation() -> None:
    repository = OptionRepository()
    provider = SlowOptionProvider(
        {
            "groups": [
                {
                    "display_name": "Drink add-ons",
                    "item_display_names": ["Add Coca-Cola 355ml", "None"],
                }
            ]
        }
    )
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: service.get_options("menu-1", "session-1"),
                range(2),
            )
        )

    assert [result[0].display_name for result in results] == [
        "Drink add-ons",
        "Drink add-ons",
    ]
    assert len(provider.calls) == 1


def test_oracle_merge_never_updates_prompt_version_used_by_its_on_clause() -> None:
    source = (ROOT / "backend" / "app" / "db" / "oracle_repository.py").read_text(
        encoding="utf-8"
    )
    runtime_section = source.split("def save_option_localizations", maxsplit=1)[1].split(
        "def save_menu_runtime_localizations", maxsplit=1
    )[0]

    assert runtime_section.count("target.prompt_version=:prompt_version") == 2
    assert "UPDATE SET\n                      prompt_version=:prompt_version" not in runtime_section
    assert "model_id=:model_id,\n                      prompt_version=:prompt_version" not in runtime_section
