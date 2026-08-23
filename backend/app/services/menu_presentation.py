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
    CountryAwareMenuPresentationCacheEntry,
    MenuPresentationCacheEntry,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
    RuntimeMenuSourceDescriptionLocalizationEntry,
)
from app.domain.presentation_localization import (
    SupportedPresentationLocale,
    build_presentation_country_context,
    is_generic_localized_title,
    normalize_country_code,
    normalize_presentation_locale,
    source_translation_is_safe,
)
from app.domain.recommendation_copy import deterministic_presentation_copy
from app.domain.structured_recommendation import EvidencePoolItem
from app.genai.contracts import GenAIProviderError
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


def deterministic_localized_title(
    language_code: str,
    *,
    title_ko: str,
    candidates: list[str | None],
) -> str:
    if language_code == "ko":
        return title_ko
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value and not any("가" <= character <= "힣" for character in value):
            return value
    return "韓国料理メニュー" if language_code == "ja" else "Korean menu"


def deterministic_localized_source_description(
    language_code: str,
    *,
    source_ko: str,
    candidates: list[str | None],
) -> str:
    """Return source copy only when it is already valid for the requested language.

    The deterministic path must never expose Korean source prose in an English/Japanese UI,
    but it should preserve a validated repository localization when generation is unavailable.
    """

    if language_code == "ko":
        return source_ko.strip()
    for candidate in candidates:
        value = str(candidate or "").strip()
        if source_translation_is_safe(source_ko, value, language_code):
            return value
    return ""


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
        country_aware = self.settings.country_aware_presentation_enabled
        normalized_language: SupportedPresentationLocale = (
            normalize_presentation_locale(language_code)
            if country_aware
            else cast(
                SupportedPresentationLocale,
                language_code if language_code in {"ko", "ja"} else "en",
            )
        )
        presentations = [
            self._from_evidence_item(
                item,
                language_code=normalized_language,
                country_code=country_code or "ZZ",
                country_aware=country_aware,
            )
            for item in evidence_items
        ]
        resolved = self._resolve(
            presentations,
            locale=(
                normalized_language
                if country_aware
                else {"ko": "한국어", "ja": "日本語"}.get(
                    normalized_language, "English"
                )
            ),
            session_id=session_id,
            country_aware=country_aware,
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
        country_aware = self.settings.country_aware_presentation_enabled
        language_code: SupportedPresentationLocale
        profile = None
        if country_aware:
            session = self.repository.get_session(session_id)
            profile = self.repository.get_profile(session.profile_id) if session is not None else None
            language_code = normalize_presentation_locale(
                profile.preferred_language if profile is not None else "en"
            )
        else:
            language_code = cast(
                SupportedPresentationLocale, page.items[0].language_code or "en"
            )
        locale = (
            language_code
            if country_aware
            else {"ko": "한국어", "ja": "日本語"}.get(language_code, "English")
        )
        prepared: list[MerchantMenuPresentation] = []
        for item in page.items:
            fallback_title = deterministic_localized_title(
                language_code,
                title_ko=item.menu.name_ko,
                candidates=[
                    item.localized_title,
                    item.menu.localized_title,
                    item.menu.name_en,
                ],
            )
            evidence_map = dict(item.evidence_map)
            if country_aware:
                country_context = build_presentation_country_context(
                    user_country_code=(profile.country_code if profile is not None else None),
                    spice_reference_country_code=None,
                    representative_dish_en=None,
                    spice_baseline=None,
                    menu_spice_level=None,
                )
                context_payload = country_context.model_dump(mode="json")
                context_payload["comparison_is_complete"] = False
                evidence_map["presentation_country_context"] = context_payload
                english_source_fallback = deterministic_localized_source_description(
                    "en",
                    source_ko=item.menu.description,
                    candidates=[item.source_description],
                )
                if english_source_fallback:
                    evidence_map[
                        "english_source_description_fallback"
                    ] = english_source_fallback
            prepared.append(
                self._with_cache_identity(
                    item.model_copy(
                        update={
                            "localized_title": fallback_title,
                            "localized_subtitle": deterministic_localized_subtitle(
                                language_code,
                                title_ko=item.menu.name_ko,
                                localized_title=fallback_title,
                                components=list(evidence_map.get("menu_components", [])),
                            ),
                            "source_description": deterministic_localized_source_description(
                                language_code,
                                source_ko=item.menu.description,
                                candidates=[item.source_description],
                            ),
                            "language_code": language_code,
                            "evidence_map": evidence_map,
                        }
                    ),
                    country_aware=country_aware,
                )
            )
        return page.model_copy(
            update={
                "items": self._resolve(
                    prepared,
                    locale=locale,
                    session_id=session_id,
                    country_aware=country_aware,
                )
            }
        )

    def _with_cache_identity(
        self,
        item: MerchantMenuPresentation,
        *,
        country_aware: bool = False,
    ) -> MerchantMenuPresentation:
        if item.cache_key or not item.release_id:
            return item
        language_code = item.language_code or "en"
        raw_country_context = item.evidence_map.get("presentation_country_context", {})
        country_context = (
            raw_country_context if isinstance(raw_country_context, dict) else {}
        )
        country_code = str(
            (
                country_context.get("user_country_code")
                if country_aware
                else item.country_preference.get("country_code")
            )
            or "ZZ"
        ).upper()
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
                **(
                    {
                        "presentation_country_context": item.evidence_map.get(
                            "presentation_country_context", {}
                        )
                    }
                    if country_aware
                    else {"country_preference": item.country_preference}
                ),
                "menu_components": components,
                "knowledge_release_id": source_identity.get("knowledge_release_id"),
                "enrichment_release_id": item.release_id,
            }
        )
        spice_reference_country = str(
            country_context.get("spice_reference_country_code") or "ZZ"
        )
        prompt_version = (
            self.settings.country_aware_presentation_prompt_version
            if country_aware
            else self.settings.menu_presentation_prompt_version
        )
        schema_version = (
            self.settings.country_aware_presentation_schema_version
            if country_aware
            else self.settings.menu_presentation_schema_version
        )
        cache_key = _sha(
            "|".join(
                (
                    item.release_id,
                    item.menu.menu_id,
                    language_code,
                    country_code,
                    *([spice_reference_country] if country_aware else []),
                    prompt_version,
                    schema_version,
                    source_hash,
                )
            )
        )
        return item.model_copy(
            update={
                "cache_key": cache_key,
                "source_hash": source_hash,
                "prompt_version": prompt_version,
                "content_schema_version": schema_version,
            }
        )

    def _from_evidence_item(
        self,
        item: EvidencePoolItem,
        *,
        language_code: SupportedPresentationLocale,
        country_code: str,
        country_aware: bool = False,
    ) -> MerchantMenuPresentation:
        title = deterministic_localized_title(
            language_code,
            title_ko=item.menu.name_ko,
            candidates=[
                item.localized_title,
                item.menu.localized_title,
                item.menu.name_en,
            ],
        )
        source_description = deterministic_localized_source_description(
            language_code,
            source_ko=item.menu.description,
            candidates=[item.localized_source_description],
        )
        wiki_passages = [passage.model_dump(mode="json") for passage in item.wiki_passages]
        menu_facts = [fact.model_dump(mode="json") for fact in item.menu_facts]
        reviews = list(item.synthetic_reviews)
        components = list(item.menu_components) or self._components_from_wiki(wiki_passages)
        evidence_map: dict[str, Any] = {
            "wiki_passages": wiki_passages,
            "menu_facts": menu_facts,
            "synthetic_reviews": reviews,
            "menu_components": components,
        }
        if country_aware:
            country_context = build_presentation_country_context(
                user_country_code=country_code,
                spice_reference_country_code=item.spice_reference_country_code,
                representative_dish_en=item.spice_reference_dish_en,
                spice_baseline=item.country_spice_baseline,
                menu_spice_level=item.synthetic_spice_level,
            )
            country_context_payload = country_context.model_dump(mode="json")
            country_context_payload["comparison_is_complete"] = (
                country_context.comparison_is_complete
            )
            evidence_map["presentation_country_context"] = country_context_payload
            english_source_fallback = deterministic_localized_source_description(
                "en",
                source_ko=item.menu.description,
                candidates=[item.localized_source_description],
            )
            if english_source_fallback:
                evidence_map["english_source_description_fallback"] = english_source_fallback
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
                **(
                    {
                        "presentation_country_context": evidence_map.get(
                            "presentation_country_context", {}
                        )
                    }
                    if country_aware
                    else {"country_preference": item.country_preference}
                ),
                "menu_components": components,
                "knowledge_release_id": item.knowledge_release_id,
                "enrichment_release_id": item.synthetic_enrichment_release_id,
            }
        )
        release_id = item.synthetic_enrichment_release_id
        normalized_country_code = normalize_country_code(country_code) or "ZZ"
        spice_reference_country_code = str(
            evidence_map.get("presentation_country_context", {}).get(
                "spice_reference_country_code"
            )
            or "ZZ"
        )
        prompt_version = (
            self.settings.country_aware_presentation_prompt_version
            if country_aware
            else self.settings.menu_presentation_prompt_version
        )
        schema_version = (
            self.settings.country_aware_presentation_schema_version
            if country_aware
            else self.settings.menu_presentation_schema_version
        )
        cache_key = (
            _sha(
                "|".join(
                    (
                        release_id,
                        item.menu.menu_id,
                        language_code,
                        normalized_country_code,
                        *([spice_reference_country_code] if country_aware else []),
                        prompt_version,
                        schema_version,
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
            prompt_version=prompt_version,
            content_schema_version=schema_version,
            evidence_map=evidence_map,
        )

    def _resolve(
        self,
        presentations: list[MerchantMenuPresentation],
        *,
        locale: str,
        session_id: str,
        country_aware: bool = False,
        on_provider_attempt: (
            Callable[[int, str, str, str | None, int, dict[str, int]], None] | None
        ) = None,
    ) -> list[MerchantMenuPresentation]:
        cache_reader = getattr(
            self.repository,
            (
                "get_country_aware_menu_presentation_cache"
                if country_aware
                else "get_menu_presentation_cache"
            ),
            None,
        )
        lease_acquirer = getattr(self.repository, "acquire_menu_presentation_lease", None)
        lease_finisher = getattr(self.repository, "finish_menu_presentation_lease", None)
        cache_writer = getattr(
            self.repository,
            (
                "save_country_aware_menu_presentation_cache_entry"
                if country_aware
                else "save_menu_presentation_cache_entry"
            ),
            None,
        )
        resolved: dict[str, MerchantMenuPresentation] = {}
        misses: list[MerchantMenuPresentation] = []
        hydrated_presentations = [
            self._with_runtime_source_translation(item) if country_aware else item
            for item in presentations
        ]
        for item in hydrated_presentations:
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
                resolved[item.menu.menu_id] = (
                    self._apply_country_aware_cache(item, cached)
                    if country_aware
                    else self._apply_cache(item, cached)
                )
            else:
                misses.append(item)
        if not misses:
            return [resolved[item.menu.menu_id] for item in hydrated_presentations]

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
                country_aware=country_aware,
                on_provider_attempt=on_provider_attempt,
            )
            for item in generatable:
                generated_value = generated_by_id.get(item.menu.menu_id)
                if generated_value is None:
                    resolved[item.menu.menu_id] = (
                        self._provider_failure_fallback(item) if country_aware else item
                    )
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
                value, generation_model, fallback_fields = generated_value
                effective_model = (
                    f"{generation_model}+SAFE_FIELD_FALLBACK"
                    if fallback_fields
                    else generation_model
                )
                localized_subtitle = (
                    value.localized_subtitle or item.localized_subtitle or item.localized_title
                )
                generated_source_description = str(
                    value.localized_source_description or ""
                ).strip()
                safe_generated_source = (
                    generated_source_description
                    if source_translation_is_safe(
                        item.menu.description,
                        generated_source_description,
                        item.language_code or "en",
                    )
                    else ""
                )
                safe_existing_source = (
                    item.source_description
                    if source_translation_is_safe(
                        item.menu.description,
                        item.source_description,
                        item.language_code or "en",
                    )
                    else ""
                )
                safe_source_translation = (
                    safe_existing_source or safe_generated_source
                    if country_aware
                    else safe_generated_source or safe_existing_source
                )
                should_save_generated_source = bool(
                    country_aware and safe_generated_source and not safe_existing_source
                )
                localized_source_description = (
                    safe_source_translation or self._display_source_fallback(item)
                )
                invalid_extended_narrative = bool(
                    country_aware
                    and item.language_code not in {"en", "ko", "ja"}
                    and {
                        "localized_subtitle",
                        "yobi_short_explanation",
                        "yobi_long_explanation",
                        "review_summary",
                    }.intersection(fallback_fields)
                )
                if invalid_extended_narrative:
                    if should_save_generated_source:
                        try:
                            self._save_runtime_source_translation(
                                item,
                                safe_source_translation,
                                generation_model,
                            )
                        except Exception:
                            pass
                    fallback_item = (
                        item.model_copy(
                            update={"source_description": safe_source_translation}
                        )
                        if safe_source_translation
                        else item
                    )
                    resolved[item.menu.menu_id] = self._provider_failure_fallback(
                        fallback_item
                    )
                    if callable(lease_finisher) and item.cache_key:
                        try:
                            lease_finisher(
                                item.cache_key,
                                owner_token,
                                error_code="PRESENTATION_TARGET_LANGUAGE_INVALID",
                            )
                        except Exception:
                            pass
                    continue
                yobi_short_explanation = value.yobi_short_explanation or item.yobi_short_explanation
                yobi_long_explanation = value.yobi_long_explanation or item.yobi_long_explanation
                review_summary = value.review_summary or item.review_summary
                evidence_map = {
                    **item.evidence_map,
                    "used_evidence_ids": value.used_evidence_ids,
                    "used_source_fields": value.used_source_fields,
                    "yobi_used_evidence_ids": value.yobi_used_evidence_ids,
                    "review_used_ids": value.review_used_ids,
                    "yobi_used_source_fields": value.yobi_used_source_fields,
                    "review_used_source_fields": value.review_used_source_fields,
                    "covered_component_ids": value.covered_component_ids,
                    "component_mentions": [
                        mention.model_dump(mode="json")
                        for mention in value.component_mentions
                    ],
                    "safe_field_fallbacks": fallback_fields,
                }
                if safe_source_translation and not country_aware:
                    evidence_map["localized_source_description"] = safe_source_translation
                else:
                    evidence_map.pop("localized_source_description", None)
                country_context = item.evidence_map.get(
                    "presentation_country_context", {}
                )
                updated = item.model_copy(
                    update={
                        "localized_title": value.localized_title,
                        "localized_subtitle": localized_subtitle,
                        "source_description": localized_source_description,
                        "yobi_short_explanation": yobi_short_explanation,
                        "yobi_long_explanation": yobi_long_explanation,
                        "review_summary": review_summary,
                        "generation_model": effective_model,
                        "personalization_applied": bool(
                            value.personalization_applied
                            and country_context.get("user_country_code")
                        )
                        if country_aware
                        else value.personalization_applied,
                        "evidence_map": evidence_map,
                    }
                )
                resolved[item.menu.menu_id] = updated
                cache_error: str | None = None
                if country_aware:
                    if should_save_generated_source:
                        try:
                            self._save_runtime_source_translation(
                                updated,
                                safe_source_translation,
                                effective_model,
                            )
                        except Exception as exc:
                            cache_error = (
                                f"SOURCE_LOCALIZATION_{type(exc).__name__.upper()}"
                            )
                else:
                    try:
                        self.repository.save_menu_runtime_localizations(
                            session_id,
                            item.menu.menu_id,
                            (
                                None
                                if is_generic_localized_title(updated.localized_title)
                                else updated.localized_title
                            ),
                            safe_source_translation or None,
                            effective_model,
                            self.settings.menu_presentation_prompt_version,
                        )
                    except Exception as exc:
                        cache_error = f"MENU_LOCALIZATION_{type(exc).__name__.upper()}"
                if callable(cache_writer) and updated.cache_key and updated.release_id:
                    try:
                        cache_writer(
                            self._country_aware_cache_entry(updated)
                            if country_aware
                            else self._cache_entry(updated)
                        )
                    except Exception as exc:
                        cache_error = cache_error or type(exc).__name__.upper()
                elif updated.cache_key:
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
                resolved[item.menu.menu_id] = (
                    self._provider_failure_fallback(item) if country_aware else item
                )
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
                        resolved[item.menu.menu_id] = (
                            self._provider_failure_fallback(item) if country_aware else item
                        )
                        continue
                    if cached is None:
                        next_pending.append(item)
                    else:
                        resolved[item.menu.menu_id] = (
                            self._apply_country_aware_cache(item, cached)
                            if country_aware
                            else self._apply_cache(item, cached)
                        )
                pending = next_pending
                if pending:
                    time.sleep(self.settings.menu_presentation_poll_seconds)
            for item in pending:
                resolved[item.menu.menu_id] = (
                    self._provider_failure_fallback(item) if country_aware else item
                )
        else:
            for item in waiting:
                resolved[item.menu.menu_id] = (
                    self._provider_failure_fallback(item) if country_aware else item
                )
        return [resolved.get(item.menu.menu_id, item) for item in hydrated_presentations]

    def _generate_resilient(
        self,
        items: list[MerchantMenuPresentation],
        *,
        locale: str,
        country_aware: bool = False,
        on_provider_attempt: (
            Callable[[int, str, str, str | None, int, dict[str, int]], None] | None
        ),
    ) -> tuple[dict[str, tuple[Any, str, list[str]]], dict[str, str]]:
        """Generate one presentation batch without retrying grounding failures."""

        try:
            payload = [
                self._generation_payload(item, country_aware=country_aware)
                for item in items
            ]
            generated = (
                self.generator.generate_country_aware(
                    items=payload,
                    locale=locale,
                    on_provider_attempt=on_provider_attempt,
                )
                if country_aware
                else self.generator.generate(
                    items=payload,
                    locale=locale,
                    on_provider_attempt=on_provider_attempt,
                )
            )
            model = generated.generation_model or "UNKNOWN"
            return (
                {
                    value.menu_id: (
                        value,
                        model,
                        generated.field_fallbacks.get(value.menu_id, []),
                    )
                    for value in generated.items
                },
                generated.item_errors,
            )
        except GenAIProviderError as exc:
            error_code = exc.safe_reason_code or exc.code.value
        except Exception as exc:
            error_code = str(exc)[:160] or type(exc).__name__.upper()
        return ({}, {item.menu.menu_id: error_code for item in items})

    @staticmethod
    def _generation_payload(
        item: MerchantMenuPresentation, *, country_aware: bool = False
    ) -> dict[str, Any]:
        def compact_evidence(rows: Any) -> list[dict[str, Any]]:
            if not isinstance(rows, list):
                return []
            allowed = (
                "evidence_id",
                "content",
                "component_id",
                "component_name_ko",
                "component_name_en",
                "membership_role",
            )
            return [
                {key: row[key] for key in allowed if row.get(key) not in (None, "")}
                for row in rows
                if isinstance(row, dict)
            ]

        def compact_reviews(rows: Any) -> list[dict[str, Any]]:
            if not isinstance(rows, list):
                return []
            allowed = ("review_id", "topic", "rating", "review_text")
            return [
                {key: row[key] for key in allowed if row.get(key) not in (None, "")}
                for row in rows
                if isinstance(row, dict)
            ]

        payload = {
            "menu_id": item.menu.menu_id,
            "menu_title_ko": item.menu.name_ko,
            "localized_title": item.localized_title,
            "source_description_ko": item.menu.description,
            "wiki_passages": compact_evidence(item.evidence_map.get("wiki_passages", [])),
            "menu_facts": compact_evidence(item.evidence_map.get("menu_facts", [])),
            "synthetic_reviews": compact_reviews(
                item.evidence_map.get("synthetic_reviews", [])
            ),
            "menu_components": item.evidence_map.get("menu_components", []),
        }
        if country_aware:
            context = dict(item.evidence_map.get("presentation_country_context", {}))
            if context.get("user_country_code"):
                payload["presentation_country_context"] = context
        else:
            payload["country_preference"] = item.country_preference
        return payload

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

    def _translation_source_hash(self, item: MerchantMenuPresentation) -> str:
        return _canonical_hash(
            {
                "source_description_ko": item.menu.description,
                "language_code": item.language_code or "en",
                "prompt_version": self.settings.country_aware_presentation_prompt_version,
            }
        )

    def _with_runtime_source_translation(
        self, item: MerchantMenuPresentation
    ) -> MerchantMenuPresentation:
        if not item.release_id or not item.language_code:
            return item
        if source_translation_is_safe(
            item.menu.description, item.source_description, item.language_code
        ):
            return item
        reader = getattr(
            self.repository,
            "get_runtime_menu_source_description_localization",
            None,
        )
        if not callable(reader):
            return item
        try:
            cached = reader(
                item.release_id,
                item.menu.menu_id,
                item.language_code,
                self.settings.country_aware_presentation_prompt_version,
                self._translation_source_hash(item),
            )
        except Exception:
            return item
        if cached is None or not source_translation_is_safe(
            item.menu.description,
            cached.description_text,
            item.language_code,
        ):
            return item
        return item.model_copy(update={"source_description": cached.description_text})

    def _save_runtime_source_translation(
        self,
        item: MerchantMenuPresentation,
        description_text: str,
        model_id: str,
    ) -> None:
        if not item.release_id or not item.language_code:
            return
        if not source_translation_is_safe(
            item.menu.description, description_text, item.language_code
        ):
            return
        self.repository.save_runtime_menu_source_description_localization(
            RuntimeMenuSourceDescriptionLocalizationEntry(
                release_id=item.release_id,
                menu_id=item.menu.menu_id,
                language_code=item.language_code,
                prompt_version=self.settings.country_aware_presentation_prompt_version,
                description_text=description_text,
                model_id=model_id,
                source_hash=self._translation_source_hash(item),
                generated_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _display_source_fallback(item: MerchantMenuPresentation) -> str:
        if source_translation_is_safe(
            item.menu.description,
            item.source_description,
            item.language_code or "en",
        ):
            return item.source_description
        return str(
            item.evidence_map.get("english_source_description_fallback") or ""
        ).strip()

    def _provider_failure_fallback(
        self, item: MerchantMenuPresentation
    ) -> MerchantMenuPresentation:
        return item.model_copy(
            update={
                "source_description": self._display_source_fallback(item),
                "personalization_applied": False,
            }
        )

    @staticmethod
    def _apply_cache(
        item: MerchantMenuPresentation,
        cached: MenuPresentationCacheEntry,
    ) -> MerchantMenuPresentation:
        cached_evidence_map = dict(cached.evidence_map)
        cached_source = str(
            cached_evidence_map.get("localized_source_description") or ""
        ).strip()
        cached_source_is_safe = source_translation_is_safe(
            item.menu.description,
            cached_source,
            item.language_code or "en",
        )
        source_description = cached_source if cached_source_is_safe else item.source_description
        if not cached_source_is_safe:
            cached_evidence_map.pop("localized_source_description", None)
        return item.model_copy(
            update={
                "localized_title": cached.localized_title,
                "localized_subtitle": cached.localized_subtitle,
                "source_description": source_description,
                "yobi_short_explanation": cached.short_explanation,
                "yobi_long_explanation": cached.long_explanation,
                "review_summary": cached.review_summary,
                "generation_model": cached.model_id,
                "personalization_applied": cached.personalization_applied,
                "evidence_map": {**item.evidence_map, **cached_evidence_map},
            }
        )

    def _apply_country_aware_cache(
        self,
        item: MerchantMenuPresentation,
        cached: CountryAwareMenuPresentationCacheEntry,
    ) -> MerchantMenuPresentation:
        return item.model_copy(
            update={
                "localized_subtitle": cached.localized_subtitle,
                "source_description": self._display_source_fallback(item),
                "yobi_short_explanation": cached.short_explanation,
                "yobi_long_explanation": cached.long_explanation,
                "review_summary": cached.review_summary,
                "generation_model": cached.model_id,
                "personalization_applied": cached.personalization_applied,
                "evidence_map": {**item.evidence_map, **cached.evidence_map},
            }
        )

    @staticmethod
    def _cache_entry(item: MerchantMenuPresentation) -> MenuPresentationCacheEntry:
        if not item.cache_key or not item.release_id or not item.source_hash:
            raise ValueError("PRESENTATION_CACHE_IDENTITY_REQUIRED")
        now = datetime.now(timezone.utc)
        evidence_map = dict(item.evidence_map)
        cached_source = str(
            evidence_map.get("localized_source_description") or ""
        ).strip()
        if not source_translation_is_safe(
            item.menu.description,
            cached_source,
            item.language_code or "en",
        ):
            evidence_map.pop("localized_source_description", None)
        return MenuPresentationCacheEntry(
            cache_key=item.cache_key,
            release_id=item.release_id,
            menu_id=item.menu.menu_id,
            language_code=cast(
                Literal["ko", "en", "ja"], item.language_code or "en"
            ),
            country_code=str(item.country_preference.get("country_code") or "ZZ"),
            localized_title=item.localized_title,
            localized_subtitle=item.localized_subtitle or item.localized_title,
            short_explanation=item.yobi_short_explanation,
            long_explanation=item.yobi_long_explanation,
            review_summary=item.review_summary,
            evidence_ids=item.evidence_ids,
            review_ids=item.review_ids,
            evidence_map=evidence_map,
            model_id=item.generation_model,
            prompt_version=item.prompt_version or "unknown",
            content_schema_version=item.content_schema_version or "1",
            source_hash=item.source_hash,
            personalization_applied=item.personalization_applied,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _country_aware_cache_entry(
        item: MerchantMenuPresentation,
    ) -> CountryAwareMenuPresentationCacheEntry:
        if not item.cache_key or not item.release_id or not item.source_hash:
            raise ValueError("PRESENTATION_CACHE_IDENTITY_REQUIRED")
        context = item.evidence_map.get("presentation_country_context", {})
        evidence_map = dict(item.evidence_map)
        evidence_map.pop("localized_source_description", None)
        now = datetime.now(timezone.utc)
        return CountryAwareMenuPresentationCacheEntry(
            cache_key=item.cache_key,
            release_id=item.release_id,
            menu_id=item.menu.menu_id,
            language_code=item.language_code or "en",
            user_country_code=str(context.get("user_country_code") or "ZZ"),
            spice_reference_country_code=str(
                context.get("spice_reference_country_code") or "ZZ"
            ),
            localized_subtitle=item.localized_subtitle or item.localized_title,
            short_explanation=item.yobi_short_explanation,
            long_explanation=item.yobi_long_explanation,
            review_summary=item.review_summary,
            evidence_ids=item.evidence_ids,
            review_ids=item.review_ids,
            evidence_map=evidence_map,
            model_id=item.generation_model,
            prompt_version=item.prompt_version or "unknown",
            content_schema_version=item.content_schema_version or "1",
            source_hash=item.source_hash,
            personalization_applied=item.personalization_applied,
            created_at=now,
            updated_at=now,
        )
