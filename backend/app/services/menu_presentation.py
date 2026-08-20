from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, cast
from uuid import uuid4

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import (
    MenuPresentationCacheEntry,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
)
from app.domain.recommendation_copy import deterministic_presentation_copy
from app.domain.structured_recommendation import EvidencePoolItem
from app.genai.contracts import GenAIErrorCode, GenAIProviderError
from app.genai.presentation_generator import MenuPresentationGenerator


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(value: Any) -> str:
    return _sha(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def deterministic_localized_subtitle(
    language_code: str,
    *,
    title_ko: str,
    localized_title: str,
    components: list[dict[str, str]] | None = None,
) -> str:
    effective_language = language_code if language_code in {"ko", "ja"} else "en"
    component_rows = components or []
    label_key = "name_ko" if effective_language == "ko" else "name_en"
    labels = list(
        dict.fromkeys(
            str(component.get(label_key) or component.get("name_en") or "").strip()
            for component in component_rows
            if str(component.get(label_key) or component.get("name_en") or "").strip()
        )
    )
    if len(labels) >= 2:
        joined = "、".join(labels) if effective_language == "ja" else ", ".join(labels)
        if effective_language == "ko":
            return f"{joined}로 구성된 세트"
        if effective_language == "ja":
            return f"{joined}を組み合わせたセット"
        return f"A set featuring {joined}"
    return localized_title


class MenuPresentationService:
    """Shared cache-aside presentation layer for recommendations and merchant pages."""

    def __init__(
        self,
        repository: YobiRepository,
        settings: Settings,
        *,
        generator: MenuPresentationGenerator | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.generator = generator or MenuPresentationGenerator(settings)

    def present_selected(
        self,
        evidence_items: list[EvidencePoolItem],
        *,
        session_id: str,
        language_code: str,
        country_code: str,
        on_provider_attempt: (
            Callable[[int, str, str, str | None, int, dict[str, int]], None] | None
        ) = None,
    ) -> dict[str, MerchantMenuPresentation]:
        normalized_language = cast(
            Literal["ko", "en", "ja"],
            language_code if language_code in {"ko", "ja"} else "en",
        )
        presentations = [
            self._from_evidence_item(
                item,
                menu_options=self._get_options(item.menu.menu_id, session_id),
                language_code=normalized_language,
                country_code=country_code or "ZZ",
            )
            for item in evidence_items
        ]
        resolved = self._resolve(
            presentations,
            locale={"ko": "한국어", "ja": "日本語"}.get(normalized_language, "English"),
            session_id=session_id,
            on_provider_attempt=on_provider_attempt,
        )
        return {item.menu.menu_id: item for item in resolved}

    def list_presentations(
        self,
        session_id: str,
        merchant_id: str,
        request: MerchantMenuPresentationRequest,
    ) -> MerchantMenuPresentationPage:
        page = self.repository.list_merchant_menu_presentations(session_id, merchant_id, request)
        if not page.items:
            return page
        language_code = page.items[0].language_code or "en"
        locale = {"ko": "한국어", "ja": "日本語"}.get(language_code, "English")
        prepared: list[MerchantMenuPresentation] = []
        for item in page.items:
            menu_options = self._get_options(item.menu.menu_id, session_id)
            evidence_map = {
                **item.evidence_map,
                "menu_options": self._menu_options_payload(menu_options),
            }
            prepared.append(
                self._with_cache_identity(
                    item.model_copy(
                        update={
                            "localized_title": item.menu.name_ko,
                            "localized_subtitle": deterministic_localized_subtitle(
                                language_code,
                                title_ko=item.menu.name_ko,
                                localized_title=item.menu.name_ko,
                                components=list(evidence_map.get("menu_components", [])),
                            ),
                            "source_description": item.menu.description,
                            "evidence_map": evidence_map,
                        }
                    )
                )
            )
        return page.model_copy(
            update={"items": self._resolve(prepared, locale=locale, session_id=session_id)}
        )

    def _with_cache_identity(self, item: MerchantMenuPresentation) -> MerchantMenuPresentation:
        if item.cache_key or not item.release_id:
            return item
        language_code = item.language_code or "en"
        country_code = str(item.country_preference.get("country_code") or "ZZ")
        source_identity = item.evidence_map.get("source_identity", {})
        wiki_passages = item.evidence_map.get("wiki_passages", [])
        menu_facts = item.evidence_map.get("menu_facts", [])
        reviews = item.evidence_map.get("synthetic_reviews", [])
        components = item.evidence_map.get("menu_components", [])
        source_hash = _canonical_hash(
            {
                "menu_title_ko": item.menu.name_ko,
                "source_description_ko": item.menu.description,
                "wiki_passages": [
                    {
                        "evidence_id": str(value.get("evidence_id", "")),
                        "content_hash": _sha(str(value.get("content", ""))),
                    }
                    for value in wiki_passages
                ],
                "menu_facts": [
                    {
                        "evidence_id": str(value.get("evidence_id", "")),
                        "content_hash": _sha(str(value.get("content", ""))),
                    }
                    for value in menu_facts
                ],
                "reviews": [
                    {
                        "review_id": str(value.get("review_id", "")),
                        "content_hash": _sha(str(value.get("review_text", ""))),
                    }
                    for value in reviews
                ],
                "country_preference": item.country_preference,
                "menu_components": components,
                "menu_options": item.evidence_map.get("menu_options", []),
                "knowledge_release_id": source_identity.get("knowledge_release_id"),
                "enrichment_release_id": item.release_id,
            }
        )
        cache_key = _sha(
            "|".join(
                (
                    item.release_id,
                    item.menu.menu_id,
                    language_code,
                    country_code,
                    self.settings.menu_presentation_prompt_version,
                    self.settings.menu_presentation_schema_version,
                    source_hash,
                )
            )
        )
        return item.model_copy(
            update={
                "cache_key": cache_key,
                "source_hash": source_hash,
                "prompt_version": self.settings.menu_presentation_prompt_version,
                "content_schema_version": self.settings.menu_presentation_schema_version,
            }
        )

    def _from_evidence_item(
        self,
        item: EvidencePoolItem,
        *,
        menu_options: list[Any],
        language_code: Literal["ko", "en", "ja"],
        country_code: str,
    ) -> MerchantMenuPresentation:
        title = item.menu.name_ko
        source_description = item.menu.description
        wiki_passages = [passage.model_dump(mode="json") for passage in item.wiki_passages]
        menu_facts = [fact.model_dump(mode="json") for fact in item.menu_facts]
        reviews = list(item.synthetic_reviews)
        components = list(item.menu_components) or self._components_from_wiki(wiki_passages)
        evidence_map = {
            "wiki_passages": wiki_passages,
            "menu_facts": menu_facts,
            "synthetic_reviews": reviews,
            "menu_components": components,
            "menu_options": self._menu_options_payload(menu_options),
        }
        source_hash = _canonical_hash(
            {
                "menu_title_ko": item.menu.name_ko,
                "source_description_ko": item.menu.description,
                "wiki_passages": [
                    {
                        "evidence_id": value["evidence_id"],
                        "content_hash": _sha(str(value["content"])),
                    }
                    for value in wiki_passages
                ],
                "menu_facts": [
                    {
                        "evidence_id": value["evidence_id"],
                        "content_hash": _sha(str(value["content"])),
                    }
                    for value in menu_facts
                ],
                "reviews": [
                    {
                        "review_id": str(value.get("review_id", "")),
                        "content_hash": _sha(str(value.get("review_text", ""))),
                    }
                    for value in reviews
                ],
                "country_preference": item.country_preference,
                "menu_components": components,
                "menu_options": evidence_map["menu_options"],
                "knowledge_release_id": item.knowledge_release_id,
                "enrichment_release_id": item.synthetic_enrichment_release_id,
            }
        )
        release_id = item.synthetic_enrichment_release_id
        cache_key = (
            _sha(
                "|".join(
                    (
                        release_id,
                        item.menu.menu_id,
                        language_code,
                        country_code,
                        self.settings.menu_presentation_prompt_version,
                        self.settings.menu_presentation_schema_version,
                        source_hash,
                    )
                )
            )
            if release_id
            else None
        )
        deterministic = deterministic_presentation_copy(
            language_code,
            localized_title=title,
            wiki_passages=[passage.content for passage in item.wiki_passages],
            reviews=reviews,
        )
        return MerchantMenuPresentation(
            menu=item.menu.model_copy(update={"localized_title": title}),
            localized_title=title,
            localized_subtitle=deterministic_localized_subtitle(
                language_code,
                title_ko=item.menu.name_ko,
                localized_title=title,
                components=components,
            ),
            yobi_short_explanation=deterministic.short_explanation,
            yobi_long_explanation=deterministic.long_explanation,
            source_description=source_description,
            review_summary=deterministic.review_summary,
            country_preference=item.country_preference
            or {
                "country_code": country_code,
                "preference_percent": 54,
                "sample_size": 120,
            },
            evidence_ids=[passage.evidence_id for passage in item.wiki_passages],
            review_ids=[
                str(review.get("review_id")) for review in reviews if review.get("review_id")
            ],
            generation_model="DETERMINISTIC_GROUNDED_FALLBACK",
            release_id=release_id,
            language_code=language_code,
            cache_key=cache_key,
            source_hash=source_hash,
            prompt_version=self.settings.menu_presentation_prompt_version,
            content_schema_version=self.settings.menu_presentation_schema_version,
            evidence_map=evidence_map,
        )

    def _resolve(
        self,
        presentations: list[MerchantMenuPresentation],
        *,
        locale: str,
        session_id: str,
        on_provider_attempt: (
            Callable[[int, str, str, str | None, int, dict[str, int]], None] | None
        ) = None,
    ) -> list[MerchantMenuPresentation]:
        cache_reader = getattr(self.repository, "get_menu_presentation_cache", None)
        lease_acquirer = getattr(self.repository, "acquire_menu_presentation_lease", None)
        lease_finisher = getattr(self.repository, "finish_menu_presentation_lease", None)
        cache_writer = getattr(self.repository, "save_menu_presentation_cache_entry", None)
        resolved: dict[str, MerchantMenuPresentation] = {}
        misses: list[MerchantMenuPresentation] = []
        for item in presentations:
            try:
                cached = (
                    cache_reader(item.cache_key)
                    if callable(cache_reader) and item.cache_key
                    else None
                )
            except Exception:
                # Presentation caching is an acceleration layer. A cache read
                # failure must not replace the already validated selection.
                resolved[item.menu.menu_id] = item
                continue
            if cached is not None:
                resolved[item.menu.menu_id] = self._apply_cache(item, cached)
            else:
                misses.append(item)
        if not misses:
            return [resolved[item.menu.menu_id] for item in presentations]

        owner_token = f"presentation_{uuid4().hex}"
        owned: list[MerchantMenuPresentation] = []
        waiting: list[MerchantMenuPresentation] = []
        lease_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=self.settings.llm_timeout_seconds + 30
        )
        for item in misses:
            if not item.cache_key or not callable(lease_acquirer):
                owned.append(item)
            else:
                try:
                    acquired = lease_acquirer(
                        item.cache_key,
                        owner_token,
                        expires_at=lease_expiry,
                    )
                except Exception:
                    resolved[item.menu.menu_id] = item
                    continue
                if acquired:
                    owned.append(item)
                else:
                    waiting.append(item)

        generatable = [item for item in owned if item.cache_key and item.release_id]
        deterministic_only = [item for item in owned if item not in generatable]
        for item in deterministic_only:
            resolved[item.menu.menu_id] = item

        if generatable and self.generator.configured:
            generated_by_id, generation_errors = self._generate_resilient(
                generatable,
                locale=locale,
                on_provider_attempt=on_provider_attempt,
            )
            for item in generatable:
                generated_value = generated_by_id.get(item.menu.menu_id)
                if generated_value is None:
                    resolved[item.menu.menu_id] = item
                    if callable(lease_finisher) and item.cache_key:
                        try:
                            lease_finisher(
                                item.cache_key,
                                owner_token,
                                error_code=generation_errors.get(
                                    item.menu.menu_id, "PRESENTATION_GENERATION_FAILED"
                                ),
                            )
                        except Exception:
                            pass
                    continue
                value, generation_model = generated_value
                updated = item.model_copy(
                    update={
                        "localized_title": value.localized_title,
                        "localized_subtitle": value.localized_subtitle,
                        "source_description": value.localized_source_description,
                        "yobi_short_explanation": value.yobi_short_explanation,
                        "yobi_long_explanation": value.yobi_long_explanation,
                        "review_summary": value.review_summary,
                        "generation_model": generation_model,
                        "personalization_applied": value.personalization_applied,
                        "evidence_map": {
                            **item.evidence_map,
                            "used_evidence_ids": value.used_evidence_ids,
                            "used_source_fields": value.used_source_fields,
                            "covered_component_ids": value.covered_component_ids,
                            "localized_source_description": value.localized_source_description,
                        },
                    }
                )
                resolved[item.menu.menu_id] = updated
                cache_error: str | None = None
                try:
                    self.repository.save_menu_runtime_localizations(
                        session_id,
                        item.menu.menu_id,
                        value.localized_title,
                        value.localized_source_description,
                        generation_model,
                        self.settings.menu_presentation_prompt_version,
                    )
                    self.repository.save_option_localizations(
                        session_id,
                        item.menu.menu_id,
                        {
                            option.object_id: option.display_name
                            for option in value.option_group_localizations
                        },
                        {
                            option.object_id: option.display_name
                            for option in value.option_item_localizations
                        },
                        generation_model,
                    )
                except Exception as exc:
                    cache_error = f"OPTION_CACHE_{type(exc).__name__.upper()}"
                if (
                    cache_error is None
                    and callable(cache_writer)
                    and updated.cache_key
                    and updated.release_id
                ):
                    try:
                        cache_writer(self._cache_entry(updated))
                    except Exception as exc:
                        cache_error = type(exc).__name__.upper()
                elif cache_error is None and updated.cache_key:
                    cache_error = "PRESENTATION_CACHE_WRITER_UNAVAILABLE"
                if callable(lease_finisher) and item.cache_key:
                    try:
                        lease_finisher(
                            item.cache_key,
                            owner_token,
                            error_code=cache_error,
                        )
                    except Exception:
                        pass
        else:
            for item in generatable:
                resolved[item.menu.menu_id] = item
                if callable(lease_finisher) and item.cache_key:
                    try:
                        lease_finisher(
                            item.cache_key,
                            owner_token,
                            error_code="PRESENTATION_PROVIDER_UNAVAILABLE",
                        )
                    except Exception:
                        pass

        if waiting and callable(cache_reader):
            deadline = time.monotonic() + self.settings.menu_presentation_wait_seconds
            pending = list(waiting)
            while pending and time.monotonic() < deadline:
                next_pending: list[MerchantMenuPresentation] = []
                for item in pending:
                    try:
                        cached = cache_reader(item.cache_key) if item.cache_key else None
                    except Exception:
                        resolved[item.menu.menu_id] = item
                        continue
                    if cached is None:
                        next_pending.append(item)
                    else:
                        resolved[item.menu.menu_id] = self._apply_cache(item, cached)
                pending = next_pending
                if pending:
                    time.sleep(self.settings.menu_presentation_poll_seconds)
            for item in pending:
                resolved[item.menu.menu_id] = item
        else:
            for item in waiting:
                resolved[item.menu.menu_id] = item
        return [resolved.get(item.menu.menu_id, item) for item in presentations]

    def _generate_resilient(
        self,
        items: list[MerchantMenuPresentation],
        *,
        locale: str,
        on_provider_attempt: (
            Callable[[int, str, str, str | None, int, dict[str, int]], None] | None
        ),
    ) -> tuple[dict[str, tuple[Any, str]], dict[str, str]]:
        """Split a schema-truncated batch without changing model fallback rules."""

        try:
            generated = self.generator.generate(
                items=[self._generation_payload(item) for item in items],
                locale=locale,
                on_provider_attempt=on_provider_attempt,
            )
            model = generated.generation_model or "UNKNOWN"
            return ({value.menu_id: (value, model) for value in generated.items}, {})
        except GenAIProviderError as exc:
            if exc.code is GenAIErrorCode.GROUNDING_REJECTED and len(items) > 1:
                midpoint = len(items) // 2
                left_values, left_errors = self._generate_resilient(
                    items[:midpoint],
                    locale=locale,
                    on_provider_attempt=on_provider_attempt,
                )
                right_values, right_errors = self._generate_resilient(
                    items[midpoint:],
                    locale=locale,
                    on_provider_attempt=on_provider_attempt,
                )
                return (
                    {**left_values, **right_values},
                    {**left_errors, **right_errors},
                )
            error_code = exc.code.value
        except Exception as exc:
            error_code = str(exc)[:160] or type(exc).__name__.upper()
        return ({}, {item.menu.menu_id: error_code for item in items})

    @staticmethod
    def _generation_payload(item: MerchantMenuPresentation) -> dict[str, Any]:
        return {
            "menu_id": item.menu.menu_id,
            "menu_title_ko": item.menu.name_ko,
            "localized_title": item.localized_title,
            "source_description_ko": item.menu.description,
            "wiki_passages": item.evidence_map.get("wiki_passages", []),
            "menu_facts": item.evidence_map.get("menu_facts", []),
            "synthetic_reviews": item.evidence_map.get("synthetic_reviews", []),
            "country_preference": item.country_preference,
            "menu_components": item.evidence_map.get("menu_components", []),
            "menu_options": item.evidence_map.get("menu_options", []),
        }

    @staticmethod
    def _menu_options_payload(menu_options: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "option_group_id": group.option_group_id,
                "name_ko": group.name_ko,
                "required": group.required,
                "min_select": group.min_select,
                "max_select": group.max_select,
                "items": [
                    {
                        "option_item_id": option.option_item_id,
                        "name_ko": option.name_ko,
                        "price_delta": option.price_delta,
                    }
                    for option in group.items
                ],
            }
            for group in menu_options
        ]

    def _get_options(self, menu_id: str, session_id: str) -> list[Any]:
        reader = getattr(self.repository, "get_options", None)
        if not callable(reader):
            return []
        try:
            return list(reader(menu_id, session_id=session_id))
        except Exception:
            # Option localization is presentation enrichment. A transient option
            # read must not replace an already validated three-menu selection.
            return []

    @staticmethod
    def _components_from_wiki(
        wiki_passages: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        components: dict[str, dict[str, str]] = {}
        for passage in wiki_passages:
            if passage.get("membership_role") != "COMPONENT":
                continue
            component_id = str(passage.get("component_id") or "").strip()
            if not component_id:
                continue
            components[component_id] = {
                "component_id": component_id,
                "name_ko": str(passage.get("component_name_ko") or "").strip(),
                "name_en": str(passage.get("component_name_en") or "").strip(),
            }
        return [components[key] for key in sorted(components)]

    @staticmethod
    def _apply_cache(
        item: MerchantMenuPresentation,
        cached: MenuPresentationCacheEntry,
    ) -> MerchantMenuPresentation:
        return item.model_copy(
            update={
                "localized_title": cached.localized_title,
                "localized_subtitle": cached.localized_subtitle,
                "source_description": cached.evidence_map.get(
                    "localized_source_description", item.source_description
                ),
                "yobi_short_explanation": cached.short_explanation,
                "yobi_long_explanation": cached.long_explanation,
                "review_summary": cached.review_summary,
                "generation_model": cached.model_id,
                "personalization_applied": cached.personalization_applied,
                "evidence_map": cached.evidence_map,
            }
        )

    @staticmethod
    def _cache_entry(item: MerchantMenuPresentation) -> MenuPresentationCacheEntry:
        if not item.cache_key or not item.release_id or not item.source_hash:
            raise ValueError("PRESENTATION_CACHE_IDENTITY_REQUIRED")
        now = datetime.now(timezone.utc)
        return MenuPresentationCacheEntry(
            cache_key=item.cache_key,
            release_id=item.release_id,
            menu_id=item.menu.menu_id,
            language_code=item.language_code or "en",
            country_code=str(item.country_preference.get("country_code") or "ZZ"),
            localized_title=item.localized_title,
            localized_subtitle=item.localized_subtitle or item.localized_title,
            short_explanation=item.yobi_short_explanation,
            long_explanation=item.yobi_long_explanation,
            review_summary=item.review_summary,
            evidence_ids=item.evidence_ids,
            review_ids=item.review_ids,
            evidence_map=item.evidence_map,
            model_id=item.generation_model,
            prompt_version=item.prompt_version or "unknown",
            content_schema_version=item.content_schema_version or "1",
            source_hash=item.source_hash,
            personalization_applied=item.personalization_applied,
            created_at=now,
            updated_at=now,
        )
