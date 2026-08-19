from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import OptionGroup
from app.domain.preference_catalog import normalize_preference_locale
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider


class _LocalizedOptionName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["GROUP", "ITEM"]
    object_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=300)


class _OptionLocalizationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[_LocalizedOptionName] = Field(min_length=1, max_length=200)


_OPTION_LOCALIZATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 200,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["GROUP", "ITEM"]},
                    "object_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "display_name": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                "required": ["kind", "object_id", "display_name"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


class OptionLocalizationService:
    """Localize visible option names once and reuse the active release cache."""

    def __init__(
        self,
        repository: YobiRepository,
        settings: Settings,
        *,
        provider: GenAIProvider | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.provider = provider or choose_genai_provider(settings)

    def get_options(self, menu_id: str, session_id: str | None) -> list[OptionGroup]:
        groups = self.repository.get_options(menu_id, session_id=session_id)
        if not session_id or not groups:
            return groups
        session = self.repository.get_session(session_id)
        profile = self.repository.get_profile(session.profile_id) if session else None
        locale = normalize_preference_locale(profile.preferred_language) if profile else "en"
        if profile is None or locale == "ko":
            return groups
        group_ids = [group.option_group_id for group in groups]
        item_ids = [item.option_item_id for group in groups for item in group.items]
        if self.repository.option_localizations_complete(
            session_id, menu_id, group_ids, item_ids
        ):
            return groups
        if not self.provider.configured:
            return groups

        models = [self.settings.menu_localization_model]
        fallback = self.settings.oci_genai_fallback_model.strip()
        if fallback and fallback != models[0] and self.provider.supports_model(fallback):
            models.append(fallback)
        if not self.provider.supports_model(models[0]):
            return groups
        input_items = [
            {
                "kind": "GROUP",
                "object_id": group.option_group_id,
                "name_ko": group.name_ko,
                "name_en": group.name_en,
            }
            for group in groups
        ] + [
            {
                "kind": "ITEM",
                "object_id": item.option_item_id,
                "name_ko": item.name_ko,
                "name_en": item.name_en,
            }
            for group in groups
            for item in group.items
        ]
        target_language = "Japanese" if locale == "ja" else "English"
        request: dict[str, Any] = {
            "instructions": (
                "Translate every restaurant option group and option item into concise, natural "
                f"{target_language}. Preserve quantities, sizes, negation, brand names, and "
                "ingredient names. "
                "Do not add claims or marketing language. Return each kind and object_id exactly once."
            ),
            "input": [
                {"role": "user", "content": json.dumps(input_items, ensure_ascii=False)}
            ],
            "max_output_tokens": min(
                self.settings.structured_recommendation_max_output_tokens,
                self.provider.capabilities.max_output_tokens,
            ),
        }
        if self.provider.capabilities.structured_output:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "yobi_option_localization_v1",
                    "schema": _OPTION_LOCALIZATION_SCHEMA,
                    "strict": True,
                }
            }
        expected = {
            (str(item["kind"]), str(item["object_id"])) for item in input_items
        }
        generated: _OptionLocalizationPayload | None = None
        selected_model = models[0]
        for index, model_id in enumerate(models):
            try:
                response = self.provider.create_response(model_id, **request)
                parsed = _OptionLocalizationPayload.model_validate_json(
                    str(getattr(response, "output_text", ""))
                )
                returned = [(item.kind, item.object_id) for item in parsed.items]
                if len(returned) != len(set(returned)) or set(returned) != expected:
                    return groups
                generated = parsed
                selected_model = model_id
                break
            except GenAIProviderError as exc:
                if exc.code is GenAIErrorCode.RATE_LIMIT and index + 1 < len(models):
                    continue
                return groups
            except (ValidationError, ValueError, TypeError):
                return groups
        if generated is None:
            return groups
        group_names = {
            item.object_id: item.display_name
            for item in generated.items
            if item.kind == "GROUP"
        }
        item_names = {
            item.object_id: item.display_name
            for item in generated.items
            if item.kind == "ITEM"
        }
        self.repository.save_option_localizations(
            session_id, menu_id, group_names, item_names, selected_model
        )
        return self.repository.get_options(menu_id, session_id=session_id)
