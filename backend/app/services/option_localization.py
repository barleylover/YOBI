from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Any

from app.core.config import Settings
from app.core.logging import log_event
from app.db.repository import YobiRepository
from app.domain.models import OptionGroup
from app.domain.preference_catalog import normalize_preference_locale
from app.genai.option_localization_generator import OptionLocalizationGenerator

_NONE_OPTION_PATTERN = re.compile(
    r"선택\s*안함|미선택|안함|없음|\bnone\b|\bno\s*option\b|選択しない|なし",
    re.IGNORECASE,
)


def _is_none_option(item: Any) -> bool:
    return bool(
        _NONE_OPTION_PATTERN.search(
            " ".join(str(value or "") for value in (item.name_ko, item.name_en, item.display_name))
        )
    )


def _option_priority(item: Any, source_index: int) -> tuple[int, int, int, int]:
    has_dietary_risk = bool(
        item.dietary_conflict
        or item.conflicting_rules
        or item.vegan_status == "CONFLICT"
        or item.halal_certification_preserved is False
    )
    return (
        0 if _is_none_option(item) else 1,
        0 if not has_dietary_risk else 1,
        0 if item.price_delta == 0 else 1,
        source_index,
    )


def project_demo_options(
    groups: list[OptionGroup],
    *,
    group_limit: int,
    items_per_group_limit: int,
    total_item_limit: int,
) -> list[OptionGroup]:
    """Return a deterministic, order-safe option subset for the demo UI.

    Required groups and enough items to satisfy each min_select are never
    hidden, even when malformed source data exceeds a configured presentation
    ceiling. Optional groups are admitted only while their minimum display
    footprint fits the total ceiling.
    """

    available_by_group: list[tuple[int, OptionGroup, list[Any]]] = []
    for group_index, group in enumerate(groups):
        available_items = [item for item in group.items if item.available]
        if available_items:
            available_by_group.append((group_index, group, available_items))

    required = [
        entry for entry in available_by_group if entry[1].required or entry[1].min_select > 0
    ]
    selected = list(required)
    selected_indexes = {entry[0] for entry in selected}
    reserved_items = sum(min(len(items), max(1, group.min_select)) for _, group, items in selected)
    for entry in available_by_group:
        group_index, group, items = entry
        if group_index in selected_indexes:
            continue
        if len(selected) >= group_limit or reserved_items + 1 > total_item_limit:
            continue
        selected.append(entry)
        selected_indexes.add(group_index)
        reserved_items += min(len(items), max(1, group.min_select))
    selected.sort(key=lambda entry: entry[0])

    ranked_items: dict[str, list[Any]] = {}
    allocations: dict[str, int] = {}
    for _, group, items in selected:
        ranked = [
            item
            for _, item in sorted(
                enumerate(items),
                key=lambda pair: _option_priority(pair[1], pair[0]),
            )
        ]
        ranked_items[group.option_group_id] = ranked
        allocations[group.option_group_id] = min(len(ranked), max(1, group.min_select))

    remaining = max(0, total_item_limit - sum(allocations.values()))
    while remaining:
        added = False
        for _, group, _ in selected:
            group_id = group.option_group_id
            per_group_ceiling = max(items_per_group_limit, group.min_select)
            if allocations[group_id] >= min(len(ranked_items[group_id]), per_group_ceiling):
                continue
            allocations[group_id] += 1
            remaining -= 1
            added = True
            if remaining == 0:
                break
        if not added:
            break

    projected: list[OptionGroup] = []
    for _, group, items in selected:
        chosen_ids = {
            item.option_item_id
            for item in ranked_items[group.option_group_id][: allocations[group.option_group_id]]
        }
        chosen_items = [item for item in items if item.option_item_id in chosen_ids]
        projected.append(
            group.model_copy(
                update={
                    "max_select": min(group.max_select, len(chosen_items)),
                    "items": chosen_items,
                }
            )
        )
    return projected


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
        groups = self._project_groups(
            list(self.repository.get_options(menu_id, session_id=session_id))
        )
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
            self._cache_prompt_version(),
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

    def _project_groups(self, groups: list[OptionGroup]) -> list[OptionGroup]:
        if not self.settings.demo_mode:
            return groups
        return project_demo_options(
            groups,
            group_limit=self.settings.demo_option_group_limit,
            items_per_group_limit=self.settings.demo_option_items_per_group_limit,
            total_item_limit=self.settings.demo_option_item_total_limit,
        )

    def _cache_prompt_version(self) -> str:
        base = self.settings.option_localization_prompt_version
        if not self.settings.demo_mode:
            return base
        return (
            f"{base}:g{self.settings.demo_option_group_limit}"
            f":i{self.settings.demo_option_items_per_group_limit}"
            f":t{self.settings.demo_option_item_total_limit}"
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
                "name_en": group.name_en,
                "items": [
                    {"name_ko": item.name_ko, "name_en": item.name_en} for item in group.items
                ],
            }
            for group in groups
        ]
        try:
            generated = self.generator.generate(
                groups=payload,
                locale=locale,
                on_provider_attempt=record_attempt,
            )
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
        localized = self._apply_localizations(groups, group_names, item_names)
        model_id = generated.generation_model or self.settings.option_localization_model
        cache_error: str | None = None
        if not generated.unresolved_paths:
            try:
                self.repository.save_option_localizations(
                    session_id,
                    menu_id,
                    group_names,
                    item_names,
                    model_id,
                    self._cache_prompt_version(),
                )
            except Exception as exc:
                cache_error = f"OPTION_LOCALIZATION_CACHE_{type(exc).__name__.upper()}"
        log_event(
            self.logger,
            event="option_localization_terminal",
            status="PARTIAL" if generated.unresolved_paths else "SUCCEEDED",
            menu_id_hash=self._hash_id(menu_id),
            group_count=len(groups),
            item_count=len(item_ids),
            attempts=attempts,
            unresolved_paths=generated.unresolved_paths,
            cache_error=cache_error,
        )
        return localized

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
            self._cache_prompt_version(),
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
                        item.model_copy(update={"display_name": item_names[item.option_item_id]})
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
