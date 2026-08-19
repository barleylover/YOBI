from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.domain.models import ChatState, OptionGroup, OptionItem, Profile, Session
from app.genai.contracts import GenAIServingMode, ProviderCapabilities
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
        assert model_id == "xai.grok-4.3"
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
        self.group_name = group_name
        self.item_name = item_name
        self.instructions = ""

    def supports_model(self, model: str) -> bool:
        return model in {"xai.grok-4.3", "openai.gpt-oss-120b"}

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": model, **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        del model
        self.calls += 1
        self.instructions = str(kwargs["instructions"])
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
    assert first[0].display_name == second[0].display_name == "辛さレベル"
    assert first[0].items[0].display_name == "マイルド"


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
