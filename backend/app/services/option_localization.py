from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from app.core.config import Settings
from app.core.logging import log_event
from app.db.repository import YobiRepository
from app.domain.models import OptionGroup
from app.domain.preference_catalog import normalize_preference_locale
from app.genai.option_localization_generator import OptionLocalizationGenerator


class OptionLocalizationService:
    """Localize only the option labels of the menu the visitor chose."""

    def __init__(
        self,
        repository: YobiRepository,
        settings: Settings,
        *,
        generator: OptionLocalizationGenerator | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.generator = generator or OptionLocalizationGenerator(settings)
        self.logger = logging.getLogger("yobi")
        self._key_locks_guard = Lock()
        self._key_locks: dict[tuple[str, str, str], Lock] = {}

    def get_options(self, menu_id: str, session_id: str | None) -> list[OptionGroup]:
        groups = list(self.repository.get_options(menu_id, session_id=session_id))
        if not groups or session_id is None:
            return groups
        session = self.repository.get_session(session_id)
        if session is None:
            return groups
        profile = self.repository.get_profile(session.profile_id)
        if profile is None:
            return groups
        language_code = normalize_preference_locale(profile.preferred_language)
        if language_code == "ko":
            return groups

        group_ids = [group.option_group_id for group in groups]
        item_ids = [item.option_item_id for group in groups for item in group.items]
        try:
            cached = self._load_cached_options(
                groups,
                session_id,
                menu_id,
                group_ids,
                item_ids,
            )
            if cached is not None:
                return cached
        except Exception:
            pass

        locale = "日本語" if language_code == "ja" else "English"
        cache_key = (
            menu_id,
            language_code,
            self.settings.option_localization_prompt_version,
        )
        with self._key_locks_guard:
            localization_lock = self._key_locks.setdefault(cache_key, Lock())
        with localization_lock:
            try:
                cached = self._load_cached_options(
                    groups,
                    session_id,
                    menu_id,
                    group_ids,
                    item_ids,
                )
                if cached is not None:
                    return cached
            except Exception:
                pass
            return self._generate_and_cache(
                groups=groups,
                menu_id=menu_id,
                session_id=session_id,
                locale=locale,
                item_ids=item_ids,
            )

    def _generate_and_cache(
        self,
        *,
        groups: list[OptionGroup],
        menu_id: str,
        session_id: str,
        locale: str,
        item_ids: list[str],
    ) -> list[OptionGroup]:
        attempts: list[dict[str, Any]] = []

        def record_attempt(
            model_id: str,
            status: str,
            error_code: str | None,
            latency_ms: int,
            usage: dict[str, int],
        ) -> None:
            attempts.append(
                {
                    "model_id": model_id,
                    "status": status,
                    "error_code": error_code,
                    "latency_ms": latency_ms,
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                }
            )

        payload = [
            {
                "name_ko": group.name_ko,
                "items": [{"name_ko": item.name_ko} for item in group.items],
            }
            for group in groups
        ]
        try:
            generated = self.generator.generate(
                groups=payload,
                locale=locale,
                on_provider_attempt=record_attempt,
            )
            group_names = {
                group.option_group_id: generated_group.display_name
                for group, generated_group in zip(groups, generated.groups)
            }
            item_names = {
                item.option_item_id: display_name
                for group, generated_group in zip(groups, generated.groups)
                for item, display_name in zip(
                    group.items,
                    generated_group.item_display_names,
                )
            }
            model_id = generated.generation_model or self.settings.option_localization_model
            self.repository.save_option_localizations(
                session_id,
                menu_id,
                group_names,
                item_names,
                model_id,
                self.settings.option_localization_prompt_version,
            )
            localized = self._apply_localizations(groups, group_names, item_names)
            log_event(
                self.logger,
                event="option_localization_terminal",
                status="SUCCEEDED",
                menu_id_hash=self._hash_id(menu_id),
                group_count=len(groups),
                item_count=len(item_ids),
                attempts=attempts,
            )
            return localized
        except Exception as exc:
            log_event(
                self.logger,
                event="option_localization_terminal",
                status="FALLBACK",
                menu_id_hash=self._hash_id(menu_id),
                group_count=len(groups),
                item_count=len(item_ids),
                attempts=attempts,
                safe_error_code=getattr(exc, "safe_reason_code", None)
                or type(exc).__name__.upper(),
            )
            return groups

    def _load_cached_options(
        self,
        groups: list[OptionGroup],
        session_id: str,
        menu_id: str,
        group_ids: list[str],
        item_ids: list[str],
    ) -> list[OptionGroup] | None:
        group_names, item_names = self.repository.load_option_localizations(
            session_id,
            menu_id,
            self.settings.option_localization_prompt_version,
        )
        if set(group_names) != set(group_ids) or set(item_names) != set(item_ids):
            return None
        return self._apply_localizations(groups, group_names, item_names)

    @staticmethod
    def _apply_localizations(
        groups: list[OptionGroup],
        group_names: dict[str, str],
        item_names: dict[str, str],
    ) -> list[OptionGroup]:
        return [
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
            for group in groups
        ]

    @staticmethod
    def _hash_id(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()
