from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Literal

FEATURE_EXTRACTOR_VERSION = "yobi-menu-preference-feature-v4"
MEMBERSHIP_EXTRACTOR_VERSION = "yobi-menu-concept-membership-v2"

FeatureStatus = Literal["SUPPORTED", "CONTRADICTED", "REVIEW_REQUIRED"]
EvidenceScope = Literal[
    "MENU_DIRECT",
    "SECTION_CONTEXT",
    "OPTION_AVAILABILITY",
    "CONCEPT_GENERAL",
]

_TOKEN_PATTERN = re.compile(r"[0-9a-z]+|[가-힣]+|[ぁ-んァ-ヶ一-龥]+", re.IGNORECASE)
_LATIN_PATTERN = re.compile(r"[a-z]", re.IGNORECASE)
_HANGUL_PATTERN = re.compile(r"[가-힣]")
_SPACE_PATTERN = re.compile(r"\s+")
_COMPOSITE_SPLIT = re.compile(r"(?:\+|＋|＆|&|/|,|·|\bset\b|세트|셋트|반반|콤보)", re.IGNORECASE)

# These aliases are valid food terms but unsafe as unrestricted compound
# substrings.  In particular, ``스프`` must not match ``에스프레소`` and
# dessert ``cake`` must not turn a savory ``fish cake`` into a bakery item.
_EXACT_HANGUL_ALIASES = {"스프"}
_LATIN_LEFT_CONTEXT_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "cake": ("fish", "rice", "crab", "seafood"),
}

# Direct extraction is intentionally conservative. These terms assert only what
# is literally present in catalog text. General food properties come from the
# lower-specificity concept channel and options remain REVIEW_REQUIRED.
DIRECT_OPTION_TERMS: dict[str, tuple[str, ...]] = {
    "KOREAN": ("korean", "한식", "한국 음식", "한국식"),
    "CHINESE": ("chinese", "중식", "중국 음식", "중화"),
    "WESTERN": ("western", "양식", "서양식"),
    "SOUTHEAST_ASIAN": ("southeast asian", "동남아", "태국식", "베트남식"),
    "MEXICAN": ("mexican", "멕시칸", "멕시코식"),
    "JAPANESE": ("japanese", "일식", "일본식"),
    "ITALIAN": ("italian", "이탈리안", "이탈리아식"),
    "AMERICAN": ("american", "아메리칸", "미국식"),
    "SPICY": ("spicy", "chilli", "chili", "peppery", "매운", "매콤", "불닭"),
    "SWEET": ("sweet", "sugary", "honey", "달콤", "단맛", "꿀"),
    "SALTY": ("salty", "salted", "짠맛", "짭짤"),
    "SOUR": ("sour", "tangy", "acidic", "새콤", "신맛", "산미"),
    "NUTTY_SAVORY": ("nutty", "savory", "savoury", "umami", "고소", "감칠맛"),
    "CLEAN_MILD": ("clean flavor", "mild", "delicate", "담백", "순한맛"),
    "BEEF": ("beef", "소고기", "쇠고기", "우육"),
    "PORK": ("pork", "돼지고기", "돈육", "돈까스", "돈가스", "삼겹살"),
    "CHICKEN": (
        "chicken",
        "닭고기",
        "치킨",
        "닭",
        "닭갈비",
        "닭강정",
        "닭발",
        "닭볶음탕",
        "닭죽",
        "닭곰탕",
    ),
    "FISH_SEAFOOD": (
        "fish",
        "seafood",
        "shellfish",
        "생선",
        "해산물",
        "새우",
        "오징어",
        "연어",
        "참치",
        "조개",
    ),
    "VEGETABLE": ("vegetable", "vegetables", "veggie", "채소", "야채"),
    "RICE": ("rice", "밥", "볶음밥", "덮밥", "비빔밥", "국밥"),
    "NOODLES": (
        "noodle",
        "noodles",
        "pasta",
        "면",
        "국수",
        "우동",
        "라면",
        "냉면",
        "쫄면",
        "당면",
    ),
    "SOUP": (
        "soup",
        "broth",
        "국물",
        "국",
        "탕",
        "국밥",
        "해장국",
        "곰탕",
        "설렁탕",
        "삼계탕",
        "마라탕",
        "감자탕",
        "갈비탕",
        "매운탕",
        "육개장",
        "수프",
        "스프",
    ),
    "STEW_HOTPOT": ("stew", "hot pot", "hotpot", "찌개", "전골", "스튜"),
    "BREAD": ("bread", "sandwich", "toast", "빵", "샌드위치", "토스트"),
    "SALAD": ("salad", "샐러드"),
    "GRILLED_DISH": ("grilled dish", "barbecue", "bbq", "구이", "바비큐"),
    "BOWL_POKE": ("rice bowl", "poke", "덮밥", "포케"),
    "DESSERT_BAKERY": (
        "dessert",
        "bakery",
        "cake",
        "pastry",
        "cookie",
        "donut",
        "디저트",
        "베이커리",
        "케이크",
        "쿠키",
        "도넛",
    ),
    "FRIED_SNACK": ("fried snack", "tempura", "튀김", "감자튀김", "텐푸라"),
    "HOT": ("piping hot", "steaming hot", "뜨거운", "열탕"),
    "WARM": ("served warm", "warm", "따뜻한"),
    "ROOM_TEMPERATURE": ("room temperature", "상온"),
    "COOL": ("served cool", "chilled", "cold dish", "시원한", "차가운"),
    "FROZEN": ("frozen", "icy", "냉동", "얼린"),
    "CRISPY": ("crispy", "crisp", "바삭"),
    "CHEWY": ("chewy", "springy", "쫄깃"),
    "SOFT": ("soft", "tender", "silky", "부드러운", "연한"),
    "CRUNCHY": ("crunchy", "아삭"),
    "THICK_RICH": ("thick", "rich", "creamy", "dense", "걸쭉", "진한"),
    "GRILLED": ("grilled", "charred", "barbecue", "구운", "구이"),
    "BOILED": ("boiled", "poached", "삶은", "데친"),
    "SIMMERED": ("simmered", "stewed", "braised", "푹 끓인", "조린"),
    "STEAMED": ("steamed", "찐", "증숙"),
    "FRIED": ("deep fried", "deep-fried", "fried", "튀긴", "튀김"),
    "STIR_FRIED": ("stir fried", "stir-fried", "sauteed", "볶은", "볶음"),
    "BAKED": ("baked", "oven baked", "oven-baked", "오븐에 구운", "베이크드"),
}

_EXPLICIT_CONTRADICTION_TERMS: dict[str, tuple[str, ...]] = {
    "SPICY": ("not spicy", "non spicy", "non-spicy", "mild only", "안 매운", "맵지 않은"),
    "PORK": ("no pork", "pork free", "pork-free", "돼지고기 없음", "돈육 없음"),
    "BEEF": ("no beef", "beef free", "beef-free", "소고기 없음"),
    "CHICKEN": ("no chicken", "chicken free", "chicken-free", "닭고기 없음"),
    "FISH_SEAFOOD": (
        "no seafood",
        "seafood free",
        "seafood-free",
        "해산물 없음",
        "생선 없음",
    ),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@lru_cache(maxsize=32768)
def normalize_preference_text(value: str) -> str:
    """NFKC/casefold text with punctuation converted to token separators."""

    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(_TOKEN_PATTERN.findall(normalized))


@lru_cache(maxsize=65536)
def preference_term_matches(value: str, term: str) -> bool:
    """Match explicit aliases without raw substring comparisons.

    Latin aliases must match complete normalized tokens. Korean aliases are
    explicit and may match inside a single agglutinative/compound token (for
    example ``매운떡볶이``), never across punctuation-normalization artifacts.
    """

    normalized_value = normalize_preference_text(value)
    normalized_term = normalize_preference_text(term)
    if not normalized_value or not normalized_term:
        return False
    return _normalized_term_matches(normalized_value.split(), normalized_term)


_UNCERTAIN_GENERAL_SUPPORT = re.compile(
    r"\b(?:may|might|can|could|sometimes|possibly|possible|optional|optionally|"
    r"varies|vary|varied|depending|ranges?|some|not|never|no|without|"
    r"doesn['’]?t|does\s+not|isn['’]?t|is\s+not|aren['’]?t|are\s+not|"
    r"cannot|can['’]?t|guarantee[ds]?)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=65536)
def reviewed_general_support_matches(value: str, term: str) -> bool:
    """Accept a Wiki term only when its local clause states positive support.

    General culinary prose often lists alternatives or explicitly warns that a
    property is not guaranteed for every merchant. Raw lexical matching turns
    those caveats into false positive recommendation edges. Evaluate the local
    clause and reject modal, variable, and negated language while still
    accepting typical statements such as ``commonly served hot``.
    """

    clauses = re.split(
        r"(?<=[.!?;])\s+|[,;]|\b(?:although|but|whereas|while)\b",
        unicodedata.normalize("NFKC", value or ""),
        flags=re.IGNORECASE,
    )
    for clause in clauses:
        if not preference_term_matches(clause, term):
            continue
        if _UNCERTAIN_GENERAL_SUPPORT.search(clause):
            continue
        return True
    return False


def _normalized_term_matches(value_tokens: list[str], normalized_term: str) -> bool:
    term_tokens = normalized_term.split()
    if _LATIN_PATTERN.search(normalized_term):
        width = len(term_tokens)
        return any(value_tokens[index : index + width] == term_tokens for index in range(len(value_tokens) - width + 1))
    if _HANGUL_PATTERN.search(normalized_term):
        if len(term_tokens) > 1:
            width = len(term_tokens)
            if any(value_tokens[index : index + width] == term_tokens for index in range(len(value_tokens) - width + 1)):
                return True
        compact_term = "".join(term_tokens)
        return len(compact_term) >= 2 and any(compact_term in token for token in value_tokens)
    width = len(term_tokens)
    return any(value_tokens[index : index + width] == term_tokens for index in range(len(value_tokens) - width + 1))


def any_preference_term_matches(value: str, terms: Sequence[str]) -> bool:
    value_tokens = normalize_preference_text(value).split()
    return any(
        _normalized_term_matches(value_tokens, normalize_preference_text(term))
        for term in terms
    )


@lru_cache(maxsize=1)
def _compiled_direct_matchers() -> dict[str, re.Pattern[str]]:
    return {
        option: _compile_terms(terms) for option, terms in DIRECT_OPTION_TERMS.items()
    }


@lru_cache(maxsize=1)
def _compiled_contradiction_matchers() -> dict[str, re.Pattern[str]]:
    return {
        option: _compile_terms(terms)
        for option, terms in _EXPLICIT_CONTRADICTION_TERMS.items()
    }


def _compile_terms(terms: Sequence[str]) -> re.Pattern[str]:
    patterns: list[str] = []
    for term in terms:
        normalized = normalize_preference_text(term)
        escaped = re.escape(normalized).replace(r"\ ", r"\s+")
        if _LATIN_PATTERN.search(normalized):
            exclusions = "".join(
                rf"(?<!{re.escape(prefix)}\s)"
                for prefix in _LATIN_LEFT_CONTEXT_EXCLUSIONS.get(normalized, ())
            )
            patterns.append(rf"{exclusions}(?<![0-9a-z]){escaped}(?![0-9a-z])")
        elif _HANGUL_PATTERN.search(normalized) and (
            len(normalized.replace(" ", "")) < 2
            or normalized in _EXACT_HANGUL_ALIASES
        ):
            # Single-syllable aliases such as 국/탕/면/밥 are too ambiguous for
            # compound substring matching (for example 탕 in 빙탕설리). Longer
            # compounds are supported only through the explicit aliases above.
            patterns.append(rf"(?<![가-힣]){escaped}(?![가-힣])")
        else:
            patterns.append(escaped)
    return re.compile("|".join(patterns) or r"(?!)")


@dataclass(frozen=True)
class _EvidenceCandidate:
    source_type: str
    excerpt: str
    source_ref: str
    provenance_type: str
    evidence_role: str
    is_synthetic: int


@dataclass(frozen=True)
class _FeatureCandidate:
    menu_id: str
    category_code: str
    option_code: str
    support_status: FeatureStatus
    support_strength: float
    confidence: float
    specificity: float
    evidence_scope: EvidenceScope
    provenance_type: str
    source_ref: str
    review_status: str
    is_synthetic: int
    evidence: tuple[_EvidenceCandidate, ...]


def _candidate_priority(candidate: _FeatureCandidate) -> tuple[int, float, float, str]:
    if candidate.support_status == "CONTRADICTED":
        level = 5
    elif candidate.evidence_scope == "MENU_DIRECT":
        level = 4
    elif candidate.evidence_scope == "CONCEPT_GENERAL":
        level = 3
    elif candidate.evidence_scope == "SECTION_CONTEXT":
        level = 2
    else:
        level = 1
    return (level, candidate.specificity, candidate.confidence, candidate.source_ref)


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{_sha(canonical_json([str(part) for part in parts]))[:40]}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def compile_menu_preference_features(
    *,
    knowledge_release_id: str,
    menus: Sequence[Mapping[str, Any]],
    mappings: Sequence[Mapping[str, Any]],
    concept_supports: Sequence[Mapping[str, Any]],
    chunks: Sequence[Mapping[str, Any]],
    sections_by_menu: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    options_by_menu: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile immutable menu-level preference facts and their evidence rows."""

    sections_by_menu = sections_by_menu or {}
    options_by_menu = options_by_menu or {}
    mapping_by_menu = {
        str(row["menu_id"]): row
        for row in mappings
        if row.get("mapping_status") == "MAPPED" and row.get("concept_id")
    }
    supports_by_concept: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for support in concept_supports:
        if support.get("support_status") == "SUPPORTED":
            supports_by_concept[str(support["concept_id"])].append(support)
    chunks_by_id = {str(row["chunk_id"]): row for row in chunks}
    candidates: dict[tuple[str, str, str], list[_FeatureCandidate]] = defaultdict(list)

    def add_text_candidates(
        menu_id: str,
        *,
        text: str,
        source_type: str,
        source_ref: str,
        scope: EvidenceScope,
        status: FeatureStatus,
        strength: float,
        confidence: float,
        specificity: float,
        provenance: str,
        is_synthetic: int,
    ) -> None:
        excerpt = _SPACE_PATTERN.sub(" ", str(text or "")).strip()[:2000]
        if not excerpt:
            return
        normalized_excerpt = normalize_preference_text(excerpt)
        direct_matchers = _compiled_direct_matchers()
        contradiction_matchers = _compiled_contradiction_matchers()
        for category_code, option_codes in _category_options().items():
            for option_code in option_codes:
                matched = bool(direct_matchers[option_code].search(normalized_excerpt))
                contradiction_matcher = contradiction_matchers.get(option_code)
                contradicted = bool(
                    contradiction_matcher and contradiction_matcher.search(normalized_excerpt)
                )
                if not matched and not contradicted:
                    continue
                resolved_status: FeatureStatus = "CONTRADICTED" if contradicted else status
                role = "CONTRADICTION" if contradicted else (
                    "SUPPORT" if status == "SUPPORTED" else "CONTEXT"
                )
                candidates[(menu_id, category_code, option_code)].append(
                    _FeatureCandidate(
                        menu_id=menu_id,
                        category_code=category_code,
                        option_code=option_code,
                        support_status=resolved_status,
                        support_strength=1.0 if contradicted else strength,
                        confidence=max(confidence, 0.95) if contradicted else confidence,
                        specificity=1.0 if contradicted else specificity,
                        evidence_scope="MENU_DIRECT" if contradicted else scope,
                        provenance_type=provenance,
                        source_ref=source_ref,
                        review_status="SOURCE_DERIVED",
                        is_synthetic=is_synthetic,
                        evidence=(
                            _EvidenceCandidate(
                                source_type=source_type,
                                excerpt=excerpt,
                                source_ref=source_ref,
                                provenance_type=provenance,
                                evidence_role=role,
                                is_synthetic=is_synthetic,
                            ),
                        ),
                    )
                )

    for menu in menus:
        menu_id = str(menu["menu_id"])
        provenance = str(menu.get("data_origin") or "YOGIYO_PUBLIC_WEB")
        is_synthetic = int(menu.get("is_synthetic") or 0)
        for field, source_type, confidence in (
            ("name_ko", "MENU_NAME", 0.98),
            ("name_en", "MENU_NAME", 0.98),
            ("description", "MENU_DESCRIPTION", 0.90),
            ("cultural_description", "MENU_DESCRIPTION", 0.82),
        ):
            add_text_candidates(
                menu_id,
                text=str(menu.get(field) or ""),
                source_type=source_type,
                source_ref=f"menu:{menu_id}:{field}",
                scope="MENU_DIRECT",
                status="SUPPORTED",
                strength=0.98 if source_type == "MENU_NAME" else 0.88,
                confidence=confidence,
                specificity=1.0 if source_type == "MENU_NAME" else 0.90,
                provenance=provenance,
                is_synthetic=is_synthetic,
            )
        # Merchant sections and categories are context, never recipe proof.
        add_text_candidates(
            menu_id,
            text=str(menu.get("category") or ""),
            source_type="MENU_SECTION",
            source_ref=f"menu:{menu_id}:category",
            scope="SECTION_CONTEXT",
            status="REVIEW_REQUIRED",
            strength=0.40,
            confidence=0.60,
            specificity=0.35,
            provenance=provenance,
            is_synthetic=is_synthetic,
        )
        for section in sections_by_menu.get(menu_id, ()):
            add_text_candidates(
                menu_id,
                text=" ".join(str(section.get(key) or "") for key in ("title", "description")),
                source_type="MENU_SECTION",
                source_ref=str(section.get("source_ref") or f"menu:{menu_id}:section"),
                scope="SECTION_CONTEXT",
                status="REVIEW_REQUIRED",
                strength=0.40,
                confidence=0.60,
                specificity=0.35,
                provenance=provenance,
                is_synthetic=is_synthetic,
            )
        for option in options_by_menu.get(menu_id, ()):
            add_text_candidates(
                menu_id,
                text=" ".join(str(option.get(key) or "") for key in ("name_ko", "name_en", "description")),
                source_type="MENU_OPTION",
                source_ref=str(option.get("source_ref") or f"menu:{menu_id}:option"),
                scope="OPTION_AVAILABILITY",
                status="REVIEW_REQUIRED",
                strength=0.30,
                confidence=0.50,
                specificity=0.20,
                provenance=provenance,
                is_synthetic=is_synthetic,
            )

        mapping = mapping_by_menu.get(menu_id)
        if mapping is not None:
            for support in supports_by_concept.get(str(mapping["concept_id"]), ()):
                chunk = chunks_by_id.get(str(support.get("evidence_chunk_id") or ""))
                if chunk is None:
                    continue
                category_code = str(support["category_code"])
                option_code = str(support["option_code"])
                excerpt = str(chunk.get("content") or "")[:2000]
                source_ref = str(support["source_ref"])
                candidates[(menu_id, category_code, option_code)].append(
                    _FeatureCandidate(
                        menu_id=menu_id,
                        category_code=category_code,
                        option_code=option_code,
                        support_status="SUPPORTED",
                        support_strength=round(float(support["support_strength"]) * 0.65, 6),
                        confidence=0.65,
                        specificity=0.25,
                        evidence_scope="CONCEPT_GENERAL",
                        provenance_type=str(support["provenance_type"]),
                        source_ref=source_ref,
                        review_status=str(support["review_status"]),
                        is_synthetic=int(
                            support["is_synthetic"]
                            if support.get("is_synthetic") is not None
                            else 1
                        ),
                        evidence=(
                            _EvidenceCandidate(
                                source_type="WIKI_CHUNK",
                                excerpt=excerpt,
                                source_ref=source_ref,
                                provenance_type=str(support["provenance_type"]),
                                evidence_role="SUPPORT",
                                is_synthetic=int(
                                    support["is_synthetic"]
                                    if support.get("is_synthetic") is not None
                                    else 1
                                ),
                            ),
                        ),
                    )
                )

    timestamp = _timestamp()
    feature_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for key in sorted(candidates):
        menu_id, category_code, option_code = key
        ordered = sorted(candidates[key], key=_candidate_priority, reverse=True)
        winner = ordered[0]
        feature_id = _stable_id("mpf", knowledge_release_id, *key)
        feature_rows.append(
            {
                "knowledge_release_id": knowledge_release_id,
                "feature_id": feature_id,
                "menu_id": menu_id,
                "category_code": category_code,
                "option_code": option_code,
                "support_status": winner.support_status,
                "support_strength": round(winner.support_strength, 6),
                "confidence": round(winner.confidence, 6),
                "specificity": round(winner.specificity, 6),
                "evidence_scope": winner.evidence_scope,
                "provenance_type": winner.provenance_type,
                "source_ref": winner.source_ref,
                "review_status": winner.review_status,
                "extractor_version": FEATURE_EXTRACTOR_VERSION,
                "is_synthetic": winner.is_synthetic,
                "updated_at": timestamp,
            }
        )
        seen_evidence: set[tuple[str, str, str]] = set()
        for candidate in ordered:
            for evidence in candidate.evidence:
                identity = (evidence.source_type, evidence.source_ref, evidence.excerpt)
                if identity in seen_evidence:
                    continue
                seen_evidence.add(identity)
                role = evidence.evidence_role
                if (
                    candidate.evidence_scope == "CONCEPT_GENERAL"
                    and winner.support_status == "CONTRADICTED"
                ):
                    role = "OVERRIDDEN_GENERAL"
                elif candidate is not winner and role == "SUPPORT":
                    role = "CONTEXT"
                excerpt_sha = _sha(evidence.excerpt)
                evidence_rows.append(
                    {
                        "knowledge_release_id": knowledge_release_id,
                        "evidence_id": _stable_id(
                            "mpfe", feature_id, evidence.source_type, evidence.source_ref, excerpt_sha
                        ),
                        "feature_id": feature_id,
                        "evidence_role": role,
                        "source_type": evidence.source_type,
                        "excerpt": evidence.excerpt,
                        "excerpt_sha256": excerpt_sha,
                        "source_ref": evidence.source_ref,
                        "provenance_type": evidence.provenance_type,
                        "is_synthetic": evidence.is_synthetic,
                        "updated_at": timestamp,
                    }
                )
    evidence_rows.sort(key=lambda row: (row["feature_id"], row["evidence_id"]))
    return feature_rows, evidence_rows


@lru_cache(maxsize=1)
def _category_options() -> dict[str, tuple[str, ...]]:
    # Local import avoids turning preference_catalog into a knowledge-module cycle.
    from app.domain.preference_catalog import PREFERENCE_CATEGORIES

    return {
        category.code: tuple(option.code for option in category.options)
        for category in PREFERENCE_CATEGORIES
        if category.code != "price_bands"
    }


def build_menu_concept_memberships(
    *,
    knowledge_release_id: str,
    menus: Sequence[Mapping[str, Any]],
    mappings: Sequence[Mapping[str, Any]],
    concepts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve primary mappings and add explicit components for composite menus."""

    menu_by_id = {str(row["menu_id"]): row for row in menus}
    timestamp = _timestamp()
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for mapping in mappings:
        if mapping.get("mapping_status") != "MAPPED" or not mapping.get("concept_id"):
            continue
        menu_id = str(mapping["menu_id"])
        concept_id = str(mapping["concept_id"])
        rows[(menu_id, concept_id)] = {
            "knowledge_release_id": knowledge_release_id,
            "menu_id": menu_id,
            "concept_id": concept_id,
            "membership_role": "PRIMARY",
            "confidence": 1.0,
            "provenance_type": str(mapping["source_type"]),
            "source_ref": str(mapping["source_ref"]),
            "review_status": str(mapping["review_status"]),
            "extractor_version": MEMBERSHIP_EXTRACTOR_VERSION,
            "is_synthetic": int(
                mapping["is_synthetic"]
                if mapping.get("is_synthetic") is not None
                else 1
            ),
            "updated_at": timestamp,
        }

    aliases: list[tuple[str, str]] = []
    for concept in concepts:
        if str(concept.get("concept_type")) == "CUISINE":
            continue
        raw_aliases = [
            str(concept.get("canonical_name_ko") or ""),
            str(concept.get("canonical_name_en") or ""),
            *[str(value) for value in json.loads(str(concept.get("aliases_json") or "[]"))],
        ]
        for alias in raw_aliases:
            if len(normalize_preference_text(alias).replace(" ", "")) >= 2:
                aliases.append((alias, str(concept["concept_id"])))
    aliases.sort(key=lambda item: (-len(normalize_preference_text(item[0])), item[1], item[0]))

    for menu_id, menu in menu_by_id.items():
        name = str(menu.get("name_ko") or menu.get("name_en") or "")
        components = [part.strip() for part in _COMPOSITE_SPLIT.split(name) if part.strip()]
        if len(components) < 2:
            continue
        for index, component in enumerate(components):
            hit = next(
                ((alias, concept_id) for alias, concept_id in aliases if preference_term_matches(component, alias)),
                None,
            )
            if hit is None:
                continue
            alias, concept_id = hit
            rows.setdefault(
                (menu_id, concept_id),
                {
                    "knowledge_release_id": knowledge_release_id,
                    "menu_id": menu_id,
                    "concept_id": concept_id,
                    "membership_role": "COMPONENT",
                    "confidence": 0.85,
                    "provenance_type": "YOBI_DERIVED_DEMO_MAPPING",
                    "source_ref": (
                        f"{MEMBERSHIP_EXTRACTOR_VERSION}:component={index}:alias={alias}"
                    ),
                    "review_status": "CLASSIFIED_DEMO",
                    "extractor_version": MEMBERSHIP_EXTRACTOR_VERSION,
                    "is_synthetic": 1,
                    "updated_at": timestamp,
                },
            )
    return [rows[key] for key in sorted(rows)]


def feature_manifest_sha256(
    features: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    memberships: Sequence[Mapping[str, Any]],
) -> str:
    excluded = {"updated_at"}
    stable = {
        "features": [
            {key: row[key] for key in sorted(row) if key not in excluded} for row in features
        ],
        "evidence": [
            {key: row[key] for key in sorted(row) if key not in excluded} for row in evidence
        ],
        "memberships": [
            {key: row[key] for key in sorted(row) if key not in excluded}
            for row in memberships
        ],
    }
    return _sha(canonical_json(stable))
