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
from app.genai.option_localization_generator import (
    OptionLocalizationGenerator,
    _option_translation_error,
)
from app.services.option_localization import OptionLocalizationService, project_demo_options

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
        self.preferred_language = "English"
        self.release_group_names: dict[str, str] = {}
        self.release_item_names: dict[str, str] = {}
        self.runtime_override: tuple[dict[str, str], dict[str, str]] | None = None

    def get_options(self, menu_id: str, session_id: str | None = None) -> list[OptionGroup]:
        del menu_id, session_id
        return self.groups

    def get_session(self, session_id: str) -> Any:
        del session_id
        return SimpleNamespace(profile_id="profile-1")

    def get_profile(self, profile_id: str) -> Any:
        del profile_id
        return SimpleNamespace(preferred_language=self.preferred_language)

    def load_release_option_localizations(
        self,
        session_id: str,
        menu_id: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        del session_id, menu_id
        return dict(self.release_group_names), dict(self.release_item_names)

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
        if self.runtime_override is not None:
            return self.runtime_override
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
                        item.model_copy(update={"display_name": item_names[item.option_item_id]})
                        for item in group.items
                    ],
                }
            )
        ]
        self.saved = True
        self.saved_prompt = prompt_version


class BrokenOptionCacheRepository(OptionRepository):
    def save_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        group_names: dict[str, str],
        item_names: dict[str, str],
        model_id: str,
        prompt_version: str,
    ) -> None:
        del session_id, menu_id, group_names, item_names, model_id, prompt_version
        raise RuntimeError("OPTION_CACHE_WRITE_UNAVAILABLE")


def _catalog_fallback_groups(language_code: str) -> list[OptionGroup]:
    return [
        group.model_copy(
            update={
                "display_name": group.name_ko if language_code == "ko" else group.name_en,
                "items": [
                    item.model_copy(
                        update={
                            "display_name": (
                                item.name_ko if language_code == "ko" else item.name_en
                            )
                        }
                    )
                    for item in group.items
                ],
            }
        )
        for group in _groups()
    ]


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


def test_number_validation_accepts_natural_one_per_order_compression() -> None:
    assert (
        _option_translation_error(
            "주문 1건당 1개 제공",
            "One item provided per order",
            "en",
        )
        is None
    )
    assert (
        _option_translation_error(
            "주문 1건당 1개 제공",
            "Two items provided per order",
            "en",
        )
        == "OPTION_LOCALIZATION_NUMBER_MISMATCH"
    )


def test_option_control_validation_distinguishes_uncooked_from_cooked() -> None:
    assert _option_translation_error("비조리", "Uncooked", "en") is None
    assert (
        _option_translation_error("비조리", "Cooked", "en")
        == "OPTION_LOCALIZATION_CONTROL_MEANING_LOST"
    )
    assert _option_translation_error("맛 선택", "Flavor", "en") is None
    assert _option_translation_error("선택 안함", "Skip", "en") is None
    assert _option_translation_error("곱빼기", "Large serving", "en") is None
    assert (
        _option_translation_error("양파 빼기", "With onions", "en")
        == "OPTION_LOCALIZATION_CONTROL_MEANING_LOST"
    )


def test_yogiyo_domain_terms_reject_literal_or_phonetic_mistranslations() -> None:
    assert (
        _option_translation_error("찜 + 사진 이벤트", "Steam + Photo Event", "en")
        == "OPTION_LOCALIZATION_SEMANTIC_ANCHOR_LOST"
    )
    assert _option_translation_error("찜 + 사진 이벤트", "Favorite + Photo Event", "en") is None
    assert (
        _option_translation_error("[찜 + 사진] 핫봉 3P", "[Favorite + Photo] Hot Bon 3p", "en")
        == "OPTION_LOCALIZATION_SEMANTIC_ANCHOR_LOST"
    )
    assert (
        _option_translation_error(
            "[찜 + 사진] 핫봉 3P",
            "[Favorite + Photo] Hot Chicken Drumettes 3p",
            "en",
        )
        is None
    )
    assert (
        _option_translation_error("매콤라구파스타 1인분", "Spicy Rago Pasta 1 serving", "en")
        == "OPTION_LOCALIZATION_SEMANTIC_ANCHOR_LOST"
    )
    assert (
        _option_translation_error("매콤라구파스타 1인분", "Spicy Ragu Pasta 1 serving", "en")
        is None
    )


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
    assert repository.saved_prompt == service._cache_prompt_version()


def test_demo_projection_caps_groups_and_items_while_preserving_required_choices() -> None:
    groups: list[OptionGroup] = []
    for group_index in range(7):
        items = [
            OptionItem(
                option_item_id=f"g{group_index}-item-{item_index}",
                name_en="None" if item_index == 9 else f"Option {item_index}",
                name_ko="선택 안함" if item_index == 9 else f"옵션 {item_index}",
                display_name=None,
                description="",
                price_delta=0 if item_index in {0, 9} else item_index * 100,
                available=True,
            )
            for item_index in range(10)
        ]
        groups.append(
            OptionGroup(
                option_group_id=f"group-{group_index}",
                name_en=f"Group {group_index}",
                name_ko=f"그룹 {group_index}",
                description="",
                required=group_index == 6,
                min_select=1 if group_index == 6 else 0,
                max_select=3,
                items=items,
            )
        )

    projected = project_demo_options(
        groups,
        group_limit=5,
        items_per_group_limit=6,
        total_item_limit=20,
    )

    assert len(projected) == 5
    assert sum(len(group.items) for group in projected) == 20
    assert all(len(group.items) <= 6 for group in projected)
    assert projected[-1].option_group_id == "group-6"
    assert all(any(item.name_ko == "선택 안함" for item in group.items) for group in projected)


def test_demo_projection_may_exceed_item_cap_only_to_preserve_required_minimum() -> None:
    source = _groups()[0]
    required_items = [
        source.items[0].model_copy(update={"option_item_id": f"required-{index}"})
        for index in range(7)
    ]
    required_group = source.model_copy(
        update={
            "required": True,
            "min_select": 7,
            "max_select": 7,
            "items": required_items,
        }
    )

    projected = project_demo_options(
        [required_group],
        group_limit=5,
        items_per_group_limit=6,
        total_item_limit=5,
    )

    assert len(projected[0].items) == 7
    assert projected[0].min_select == 7


def test_server_catalog_fallback_recovers_even_when_models_contribute_no_label() -> None:
    provider = FallbackOptionProvider(
        {
            model: {
                "groups": [
                    {
                        "display_name": "음료 추가선택",
                        "item_display_names": ["코카콜라 355ml 추가", "선택 안함"],
                    }
                ]
            }
            for model in ("openai.gpt-oss-20b", "openai.gpt-oss-120b")
        }
    )

    result = OptionLocalizationGenerator(Settings(), provider=provider).generate(
        groups=[
            {
                "name_ko": "음료 추가선택",
                "name_en": "Drink add-ons",
                "items": [
                    {
                        "name_ko": "코카콜라 355ml 추가",
                        "name_en": "Add Coca-Cola 355ml",
                    },
                    {"name_ko": "선택 안함", "name_en": "None"},
                ],
            }
        ],
        locale="English",
    )

    assert result.groups[0].display_name == "Drink add-ons"
    assert result.groups[0].item_display_names == ["Add Coca-Cola 355ml", "None"]
    assert result.generation_model == "SERVER_SAFE_FALLBACK"
    assert result.unresolved_paths == []


def test_runtime_cache_repositories_accept_only_valid_demo_projection_subsets() -> None:
    for repository_name in ("sqlite_repository.py", "oracle_repository.py"):
        source = (ROOT / "backend" / "app" / "db" / repository_name).read_text(encoding="utf-8")
        runtime_section = source.split("def save_option_localizations", maxsplit=1)[1].split(
            "def save_menu_runtime_localizations", maxsplit=1
        )[0]

        assert runtime_section.count(".issubset(") == 2
        assert "OPTION_LOCALIZATION_ITEM_GROUP_MISMATCH" in runtime_section
        assert "not in group_names" in runtime_section
        assert "not in item_names" in runtime_section


def test_generator_returns_safe_partial_translation_for_one_unresolved_label() -> None:
    provider = FallbackOptionProvider(
        {
            "openai.gpt-oss-20b": {
                "groups": [
                    {
                        "display_name": "Drink add-ons",
                        "item_display_names": ["Add Coca-Cola 355ml", "새콤달콤"],
                    }
                ]
            },
            "openai.gpt-oss-120b": {
                "groups": [
                    {
                        "display_name": "Drink add-ons",
                        "item_display_names": ["Add Coca-Cola 355ml", "새콤달콤"],
                    }
                ]
            },
        }
    )

    result = OptionLocalizationGenerator(Settings(), provider=provider).generate(
        groups=[
            {
                "name_ko": "음료 추가선택",
                "name_en": "Drink add-ons",
                "items": [
                    {
                        "name_ko": "코카콜라 355ml 추가",
                        "name_en": "Add Coca-Cola 355ml",
                    },
                    {"name_ko": "새콤달콤", "name_en": ""},
                ],
            }
        ],
        locale="English",
    )

    assert result.groups[0].display_name == "Drink add-ons"
    assert result.groups[0].item_display_names == ["Add Coca-Cola 355ml", "새콤달콤"]
    assert result.unresolved_paths == ["G0:I1"]
    assert result.generation_model == "openai.gpt-oss-20b+PARTIAL_SAFE_FALLBACK"
    assert [call["model"] for call in provider.calls] == [
        "openai.gpt-oss-20b",
        "openai.gpt-oss-120b",
    ]


def test_partial_translation_is_returned_but_not_cached() -> None:
    repository = OptionRepository()
    source_group = repository.groups[0]
    repository.groups = [
        source_group.model_copy(
            update={
                "items": [
                    source_group.items[0],
                    source_group.items[1].model_copy(
                        update={
                            "name_ko": "새콤달콤",
                            "name_en": "",
                            "display_name": "새콤달콤",
                        }
                    ),
                ]
            }
        )
    ]
    provider = FallbackOptionProvider(
        {
            model: {
                "groups": [
                    {
                        "display_name": "Drink add-ons",
                        "item_display_names": ["Add Coca-Cola 355ml", "새콤달콤"],
                    }
                ]
            }
            for model in ("openai.gpt-oss-20b", "openai.gpt-oss-120b")
        }
    )
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    result = service.get_options("menu-1", "session-1")

    assert result[0].display_name == "Drink add-ons"
    assert result[0].items[0].display_name == "Add Coca-Cola 355ml"
    assert result[0].items[1].display_name == "새콤달콤"
    assert repository.saved is False


def test_known_control_label_uses_server_safe_fallback_and_is_cached() -> None:
    repository = OptionRepository()
    provider = FallbackOptionProvider(
        {
            model: {
                "groups": [
                    {
                        "display_name": "Drink add-ons",
                        "item_display_names": ["Add Coca-Cola 355ml", "선택 안함"],
                    }
                ]
            }
            for model in ("openai.gpt-oss-20b", "openai.gpt-oss-120b")
        }
    )
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    result = service.get_options("menu-1", "session-1")

    assert result[0].items[1].display_name == "None"
    assert repository.saved is True


def test_cache_write_failure_does_not_discard_generated_option_translation() -> None:
    repository = BrokenOptionCacheRepository()
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

    result = service.get_options("menu-1", "session-1")

    assert result[0].display_name == "Drink add-ons"
    assert [item.display_name for item in result[0].items] == [
        "Add Coca-Cola 355ml",
        "None",
    ]
    assert repository.saved is False


def test_missing_option_string_preserves_safe_partial_recovery_without_cache() -> None:
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

    assert result[0].display_name == "Drink add-ons"
    assert [item.display_name for item in result[0].items] == [
        "코카콜라 355ml 추가",
        "None",
    ]
    assert repository.saved is False


def test_precomputed_only_uses_complete_runtime_cache_without_provider_call() -> None:
    repository = OptionRepository()
    repository.preferred_language = "日本語"
    repository.groups = _catalog_fallback_groups("en")
    repository.runtime_override = (
        {"group-1": "ドリンク追加"},
        {"item-1": "コカ・コーラ355ml追加", "item-2": "選択しない"},
    )
    provider = OptionProvider({"groups": []})
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    result = service.get_options("menu-1", "session-1", precomputed_only=True)

    assert result[0].display_name == "ドリンク追加"
    assert [item.display_name for item in result[0].items] == [
        "コカ・コーラ355ml追加",
        "選択しない",
    ]
    assert provider.calls == []


def test_precomputed_only_ignores_incomplete_runtime_cache_as_one_bundle() -> None:
    repository = OptionRepository()
    repository.preferred_language = "日本語"
    repository.groups = _catalog_fallback_groups("en")
    repository.runtime_override = (
        {"group-1": "ドリンク追加"},
        {"item-1": "コカ・コーラ355ml追加"},
    )
    provider = OptionProvider({"groups": []})
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    result = service.get_options("menu-1", "session-1", precomputed_only=True)

    assert result[0].display_name == repository.groups[0].name_en
    assert [item.display_name for item in result[0].items] == [
        item.name_en for item in repository.groups[0].items
    ]
    assert provider.calls == []


def test_precomputed_only_keeps_release_localizations_ahead_of_runtime() -> None:
    repository = OptionRepository()
    repository.preferred_language = "日本語"
    repository.groups = _catalog_fallback_groups("en")
    repository.runtime_override = (
        {"group-1": "runtime group"},
        {"item-1": "runtime item 1", "item-2": "runtime item 2"},
    )
    repository.release_group_names = {"group-1": "release group"}
    repository.release_item_names = {"item-1": "release item 1"}
    provider = OptionProvider({"groups": []})
    settings = Settings()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        settings,
        generator=OptionLocalizationGenerator(settings, provider=provider),
    )

    result = service.get_options("menu-1", "session-1", precomputed_only=True)

    assert result[0].display_name == "release group"
    assert [item.display_name for item in result[0].items] == [
        "release item 1",
        "runtime item 2",
    ]
    assert provider.calls == []


def test_precomputed_only_preserves_english_and_korean_catalog_fallbacks() -> None:
    provider = OptionProvider({"groups": []})
    settings = Settings()
    for preferred_language, language_code in (("English", "en"), ("한국어", "ko")):
        repository = OptionRepository()
        repository.preferred_language = preferred_language
        repository.groups = _catalog_fallback_groups(language_code)
        service = OptionLocalizationService(
            repository,  # type: ignore[arg-type]
            settings,
            generator=OptionLocalizationGenerator(settings, provider=provider),
        )

        result = service.get_options("menu-1", "session-1", precomputed_only=True)

        assert result[0].display_name == (
            result[0].name_ko if language_code == "ko" else result[0].name_en
        )
    assert provider.calls == []


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
    source = (ROOT / "backend" / "app" / "db" / "oracle_repository.py").read_text(encoding="utf-8")
    runtime_section = source.split("def save_option_localizations", maxsplit=1)[1].split(
        "def save_menu_runtime_localizations", maxsplit=1
    )[0]

    assert runtime_section.count("target.prompt_version=:prompt_version") == 2
    assert "UPDATE SET\n                      prompt_version=:prompt_version" not in runtime_section
    assert (
        "model_id=:model_id,\n                      prompt_version=:prompt_version"
        not in runtime_section
    )
