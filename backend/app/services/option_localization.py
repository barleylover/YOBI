from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import OptionGroup
from app.domain.preference_catalog import normalize_preference_locale
from app.genai.contracts import GenAIProvider, GenAIProviderError
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
_OPTION_LOCALIZATION_BATCH_SIZE = 32


def _localized_name_is_usable(
    display_name: str | None, source_name_ko: str, locale: str
) -> bool:
    normalized_display = " ".join((display_name or "").split()).casefold()
    normalized_source = " ".join(source_name_ko.split()).casefold()
    if not normalized_display:
        return False
    if locale != "ko" and normalized_display == normalized_source:
        return not any("가" <= character <= "힣" for character in source_name_ko)
    return True


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

    def get_cached_options(
        self, menu_id: str, session_id: str | None
    ) -> list[OptionGroup]:
        """Return persisted names immediately without waiting for a model call."""

        return self.repository.get_options(menu_id, session_id=session_id)

    def get_options(self, menu_id: str, session_id: str | None) -> list[OptionGroup]:
        groups = self.get_cached_options(menu_id, session_id)
        if not session_id or not groups:
            return groups
        session = self.repository.get_session(session_id)
        profile = self.repository.get_profile(session.profile_id) if session else None
        locale = normalize_preference_locale(profile.preferred_language) if profile else "en"
        if profile is None or locale == "ko":
            return groups
        group_ids = [group.option_group_id for group in groups]
        item_ids = [item.option_item_id for group in groups for item in group.items]
        cached_names_usable = all(
            _localized_name_is_usable(group.display_name, group.name_ko, locale)
            and all(
                _localized_name_is_usable(item.display_name, item.name_ko, locale)
                for item in group.items
            )
            for group in groups
        )
        cache_complete = self.repository.option_localizations_complete(
            session_id, menu_id, group_ids, item_ids
        )
        if cached_names_usable and cache_complete:
            return groups
        if not self.provider.configured:
            return groups

        models = [self.settings.menu_localization_model]
        fallback = self.settings.oci_genai_fallback_model.strip()
        if fallback and fallback != models[0] and self.provider.supports_model(fallback):
            models.append(fallback)
        if not self.provider.supports_model(models[0]):
            return groups
        if cache_complete and not cached_names_usable and len(models) > 1:
            # A prior primary-model response passed the schema but copied Korean
            # source text. Retry directly with the alternate model so a repair
            # request stays within the synchronous UI deadline.
            models = [models[1]]
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
        base_request: dict[str, Any] = {
            "instructions": (
                "Translate every restaurant option group and option item into concise, natural "
                f"{target_language}. Preserve quantities, sizes, negation, brand names, and "
                "ingredient names. "
                "Do not add claims or marketing language. Return each kind and object_id exactly once."
            ),
            "max_output_tokens": min(
                max(self.settings.structured_recommendation_max_output_tokens, 4_096),
                self.provider.capabilities.max_output_tokens,
            ),
        }
        if self.provider.capabilities.structured_output:
            base_request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "yobi_option_localization_v1",
                    "schema": _OPTION_LOCALIZATION_SCHEMA,
                    "strict": True,
                }
            }
        generated_items: list[_LocalizedOptionName] = []
        selected_model = models[0]
        for offset in range(0, len(input_items), _OPTION_LOCALIZATION_BATCH_SIZE):
            batch = input_items[offset : offset + _OPTION_LOCALIZATION_BATCH_SIZE]
            expected = {
                (str(item["kind"]), str(item["object_id"])) for item in batch
            }
            request = {
                **base_request,
                "input": [
                    {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}
                ],
            }
            generated_batch: _OptionLocalizationPayload | None = None
            for index, model_id in enumerate(models):
                try:
                    response = self.provider.create_response(model_id, **request)
                    parsed = _OptionLocalizationPayload.model_validate_json(
                        str(getattr(response, "output_text", ""))
                    )
                    returned = [(item.kind, item.object_id) for item in parsed.items]
                    source_names = {
                        (str(item["kind"]), str(item["object_id"])): str(item["name_ko"])
                        for item in batch
                    }
                    names_usable = all(
                        _localized_name_is_usable(
                            item.display_name,
                            source_names[(item.kind, item.object_id)],
                            locale,
                        )
                        for item in parsed.items
                        if (item.kind, item.object_id) in source_names
                    )
                    if (
                        len(returned) != len(set(returned))
                        or set(returned) != expected
                        or not names_usable
                    ):
                        if index + 1 < len(models):
                            continue
                        return groups
                    generated_batch = parsed
                    if model_id != models[0]:
                        selected_model = model_id
                    break
                except GenAIProviderError:
                    if index + 1 < len(models):
                        continue
                    return groups
                except (ValidationError, ValueError, TypeError):
                    if index + 1 < len(models):
                        continue
                    return groups
            if generated_batch is None:
                return groups
            generated_items.extend(generated_batch.items)
        group_names = {
            item.object_id: item.display_name
            for item in generated_items
            if item.kind == "GROUP"
        }
        item_names = {
            item.object_id: item.display_name
            for item in generated_items
            if item.kind == "ITEM"
        }
        self.repository.save_option_localizations(
            session_id, menu_id, group_names, item_names, selected_model
        )
        return self.repository.get_options(menu_id, session_id=session_id)
