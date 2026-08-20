from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import BackgroundTasks

from app.core.config import Settings
from app.domain.models import ChatState, OptionGroup, OptionItem, Profile, Session
from app.genai.contracts import GenAIServingMode, ProviderCapabilities
from app.main import get_menu_options
from app.services.option_localization import OptionLocalizationService


class OptionRepository:
    def __init__(self, language: str = "日本語") -> None:
        now = datetime.now(timezone.utc)
        self.session = Session(
            session_id="session-localized",
            profile_id="profile-localized",
            state=ChatState.DISCOVERY,
            created_at=now,
            updated_at=now,
        )
        self.profile = Profile(
            profile_id="profile-localized",
            preferred_language=language,
            nationality="Japan",
            country_code="JP",
            consent_demo_data=True,
            created_at=now,
        )
        self.group_names: dict[str, str] = {}
        self.item_names: dict[str, str] = {}
        self.saved_model_id = ""

    def get_session(self, session_id: str) -> Session | None:
        return self.session if session_id == self.session.session_id else None

    def get_profile(self, profile_id: str) -> Profile | None:
        return self.profile if profile_id == self.profile.profile_id else None

    def get_options(self, menu_id: str, session_id: str | None = None) -> list[OptionGroup]:
        del menu_id, session_id
        return [
            OptionGroup(
                option_group_id="group-spice",
                name_en="Spice level",
                name_ko="맵기 단계",
                display_name=self.group_names.get("group-spice", "Spice level"),
                description="",
                required=True,
                min_select=1,
                max_select=1,
                items=[
                    OptionItem(
                        option_item_id="item-mild",
                        name_en="Mild",
                        name_ko="순한맛",
                        display_name=self.item_names.get("item-mild", "Mild"),
                        description="",
                        price_delta=0,
                        available=True,
                    )
                ],
            )
        ]

    def option_localizations_complete(
        self,
        session_id: str,
        menu_id: str,
        group_ids: list[str],
        item_ids: list[str],
    ) -> bool:
        del session_id, menu_id
        return set(self.group_names) == set(group_ids) and set(self.item_names) == set(item_ids)

    def save_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        group_names: dict[str, str],
        item_names: dict[str, str],
        model_id: str,
    ) -> None:
        del session_id, menu_id
        self.saved_model_id = model_id
        self.group_names = group_names
        self.item_names = item_names


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
        max_output_tokens=4_096,
        max_tools_per_request=4,
        max_tool_calls_per_response=4,
    )

    def __init__(self, *, group_name: str = "辛さレベル", item_name: str = "マイルド") -> None:
        self.calls = 0
        self.models: list[str] = []
        self.group_name = group_name
        self.item_name = item_name
        self.instructions = ""
        self.max_output_tokens = 0

    def supports_model(self, model: str) -> bool:
        return model in {"xai.grok-4.3", "openai.gpt-oss-120b"}

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.calls += 1
        self.models.append(model)
        self.instructions = str(kwargs["instructions"])
        self.max_output_tokens = int(kwargs["max_output_tokens"])
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "items": [
                        {
                            "kind": "GROUP",
                            "object_id": "group-spice",
                            "display_name": self.group_name,
                        },
                        {
                            "kind": "ITEM",
                            "object_id": "item-mild",
                            "display_name": self.item_name,
                        },
                    ]
                },
                ensure_ascii=False,
            )
        )


def test_japanese_options_are_generated_once_then_read_from_cache() -> None:
    repository = OptionRepository()
    provider = OptionProvider()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    )

    first = service.get_options("menu-1", "session-localized")
    second = service.get_options("menu-1", "session-localized")

    assert provider.calls == 1
    assert "Japanese" in provider.instructions
    assert provider.max_output_tokens == 4_096
    assert first[0].display_name == second[0].display_name == "辛さレベル"
    assert first[0].items[0].display_name == "マイルド"


def test_cached_options_never_wait_for_provider_generation() -> None:
    repository = OptionRepository(language="English")
    provider = OptionProvider(group_name="Spice choice", item_name="Not spicy")
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    )

    result = service.get_cached_options("menu-1", "session-localized")

    assert provider.calls == 0
    assert result[0].display_name == "Spice level"
    assert result[0].items[0].display_name == "Mild"


def test_options_endpoint_returns_cached_names_before_background_localization() -> None:
    repository = OptionRepository(language="English")
    provider = OptionProvider(group_name="Spice choice", item_name="Not spicy")
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    )
    background_tasks = BackgroundTasks()

    result = get_menu_options(
        "menu-1",
        background_tasks,
        session_id="session-localized",
        repository=repository,  # type: ignore[arg-type]
        option_service=service,
    )

    assert provider.calls == 0
    assert result[0]["display_name"] == "Spice level"
    assert len(background_tasks.tasks) == 1


def test_english_options_are_generated_once_then_read_from_cache() -> None:
    repository = OptionRepository(language="English")
    provider = OptionProvider(group_name="Spice choice", item_name="Not spicy")
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    )

    first = service.get_options("menu-1", "session-localized")
    second = service.get_options("menu-1", "session-localized")

    assert provider.calls == 1
    assert "English" in provider.instructions
    assert first[0].display_name == second[0].display_name == "Spice choice"
    assert first[0].items[0].display_name == "Not spicy"


def test_invalid_grok_payload_falls_back_to_120b() -> None:
    class InvalidGrokProvider(OptionProvider):
        def create_response(self, model: str, **kwargs: Any) -> Any:
            if model == "xai.grok-4.3":
                self.calls += 1
                self.models.append(model)
                batch = json.loads(kwargs["input"][0]["content"])
                return SimpleNamespace(
                    output_text=json.dumps(
                        {
                            "items": [
                                {
                                    "kind": item["kind"],
                                    "object_id": item["object_id"],
                                    "display_name": item["name_ko"],
                                }
                                for item in batch
                            ]
                        },
                        ensure_ascii=False,
                    )
                )
            return super().create_response(model, **kwargs)

    repository = OptionRepository()
    provider = InvalidGrokProvider()
    service = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        Settings(oci_genai_fallback_model="openai.gpt-oss-120b"),
        provider=provider,
    )

    result = service.get_options("menu-1", "session-localized")

    assert provider.models == ["xai.grok-4.3", "openai.gpt-oss-120b"]
    assert repository.saved_model_id == "openai.gpt-oss-120b"
    assert result[0].display_name == "辛さレベル"


def test_cached_korean_copy_is_regenerated_for_japanese() -> None:
    repository = OptionRepository()
    repository.group_names = {"group-spice": "맵기 단계"}
    repository.item_names = {"item-mild": "순한맛"}
    provider = OptionProvider()

    result = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    ).get_options("menu-1", "session-localized")

    assert provider.calls == 1
    assert result[0].display_name == "辛さレベル"
    assert result[0].items[0].display_name == "マイルド"


def test_large_option_menu_is_localized_in_bounded_batches() -> None:
    class LargeOptionRepository(OptionRepository):
        def get_options(
            self, menu_id: str, session_id: str | None = None
        ) -> list[OptionGroup]:
            del menu_id, session_id
            return [
                OptionGroup(
                    option_group_id="group-large",
                    name_en="Add-ons",
                    name_ko="추가 선택",
                    display_name=self.group_names.get("group-large", "Add-ons"),
                    description="",
                    required=False,
                    min_select=0,
                    max_select=40,
                    items=[
                        OptionItem(
                            option_item_id=f"item-{index}",
                            name_en=f"Option {index}",
                            name_ko=f"옵션 {index}",
                            display_name=self.item_names.get(f"item-{index}", f"Option {index}"),
                            description="",
                            price_delta=0,
                            available=True,
                        )
                        for index in range(40)
                    ],
                )
            ]

    class EchoProvider(OptionProvider):
        def create_response(self, model: str, **kwargs: Any) -> Any:
            self.calls += 1
            self.models.append(model)
            batch = json.loads(kwargs["input"][0]["content"])
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "items": [
                            {
                                "kind": item["kind"],
                                "object_id": item["object_id"],
                                "display_name": f"翻訳 {item['name_ko']}",
                            }
                            for item in batch
                        ]
                    },
                    ensure_ascii=False,
                )
            )

    repository = LargeOptionRepository()
    provider = EchoProvider()
    result = OptionLocalizationService(
        repository,  # type: ignore[arg-type]
        Settings(),
        provider=provider,
    ).get_options("menu-large", "session-localized")

    assert provider.calls == 2
    assert result[0].display_name == "翻訳 추가 선택"
    assert result[0].items[-1].display_name == "翻訳 옵션 39"
