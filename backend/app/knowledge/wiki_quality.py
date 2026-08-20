from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.knowledge.authoring import AuthoredDocument, CompiledKnowledgeRelease
from app.knowledge.passage_ranking import normalized_tokens, rank_wiki_passages

WIKI_QUALITY_POLICY_VERSION = "yobi-wiki-quality-v1"

_BOILERPLATE_MARKERS = (
    "not a statement about one merchant",
    "reviewed synthetic general-food description",
    "check the current merchant information",
)
_POSITIVE_OVERCLAIM_PATTERNS = (
    re.compile(
        r"\b(?:this dish|the dish|the recipe|the product)\s+(?:always\s+contains|guarantees)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:this dish|the dish|the recipe|the product)\s+(?:is|are)\s+"
        r"(?:allergen[- ]free|certified halal|safe for everyone)\b",
        re.IGNORECASE,
    ),
)


def is_wiki_boilerplate(value: object) -> bool:
    normalized = " ".join(str(value or "").casefold().split())
    return any(marker in normalized for marker in _BOILERPLATE_MARKERS)


def _public_chunks(
    compiled: CompiledKnowledgeRelease,
) -> dict[str, list[dict[str, Any]]]:
    reviewed_document_ids = {
        str(row["document_id"])
        for row in compiled.documents
        if row["source_type"] == "SYNTHETIC_WIKI" and row["review_status"] == "REVIEWED_DEMO"
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in compiled.chunks:
        metadata = json.loads(str(chunk["metadata_json"]))
        if str(chunk["document_id"]) not in reviewed_document_ids:
            continue
        if metadata.get("recommendation_visibility") == "INTERNAL_ONLY":
            continue
        grouped[str(chunk["concept_id"])].append(chunk)
    for rows in grouped.values():
        rows.sort(key=lambda row: (int(row["chunk_index"]), str(row["chunk_id"])))
    return grouped


def audit_wiki_quality(
    documents: Sequence[AuthoredDocument],
    compiled: CompiledKnowledgeRelease,
    supports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Audit authored Wiki truthfulness and query-time grounding usefulness."""

    public_chunks = _public_chunks(compiled)
    chunks_by_id = {str(row["chunk_id"]): row for row in compiled.chunks}
    source_by_concept = {document.front_matter.concept_id: document for document in documents}
    document_issues: list[dict[str, str]] = []
    duplicate_sources: dict[frozenset[str], list[str]] = defaultdict(list)
    disclaimer_count = 0
    metadata_source_boundary_count = 0
    informative_token_counts: list[int] = []

    for concept_id, document in sorted(source_by_concept.items()):
        front = document.front_matter
        source_path = document.path.as_posix()
        provenance_contract_invalid = (
            front.source_type != "SYNTHETIC_WIKI"
            or front.review_status != "REVIEWED_DEMO"
            or front.license_state != "SYNTHETIC"
            or not front.is_synthetic
        )
        if provenance_contract_invalid:
            document_issues.append(
                {
                    "concept_id": concept_id,
                    "source_path": source_path,
                    "code": "PROVENANCE_CONTRACT_INVALID",
                }
            )
        else:
            metadata_source_boundary_count += 1
        informative = [
            paragraph
            for paragraph in document.paragraphs
            if not is_wiki_boilerplate(paragraph.content)
        ]
        if any(is_wiki_boilerplate(paragraph.content) for paragraph in document.paragraphs):
            disclaimer_count += 1
        else:
            document_issues.append(
                {
                    "concept_id": concept_id,
                    "source_path": source_path,
                    "code": "SOURCE_BOUNDARY_DISCLAIMER_MISSING",
                }
            )
        informative_tokens = sum(
            len(normalized_tokens(paragraph.content)) for paragraph in informative
        )
        informative_token_counts.append(informative_tokens)
        if len(informative) < 2 or informative_tokens < 30:
            document_issues.append(
                {
                    "concept_id": concept_id,
                    "source_path": source_path,
                    "code": "GENERAL_DESCRIPTION_TOO_THIN",
                }
            )
        if len(public_chunks.get(concept_id, [])) < 2:
            document_issues.append(
                {
                    "concept_id": concept_id,
                    "source_path": source_path,
                    "code": "PUBLIC_PASSAGE_COVERAGE_TOO_THIN",
                }
            )
        for paragraph in informative:
            signature = normalized_tokens(paragraph.content)
            # Short facts such as "It is served hot" are legitimately shared
            # across dishes and are not template-quality failures. Only flag a
            # duplicated informative paragraph when it is substantial enough
            # to indicate copied prose rather than one atomic food fact.
            if len(signature) >= 20:
                duplicate_sources[signature].append(source_path)
            if any(pattern.search(paragraph.content) for pattern in _POSITIVE_OVERCLAIM_PATTERNS):
                document_issues.append(
                    {
                        "concept_id": concept_id,
                        "source_path": source_path,
                        "code": "UNSUPPORTED_POSITIVE_SAFETY_OVERCLAIM",
                    }
                )

    exact_duplicates = [
        sorted(set(paths)) for paths in duplicate_sources.values() if len(set(paths)) > 1
    ]
    for paths in exact_duplicates[:20]:
        document_issues.append(
            {
                "concept_id": "MULTIPLE",
                "source_path": ",".join(paths),
                "code": "DUPLICATE_INFORMATIVE_PARAGRAPH",
            }
        )

    evidence_missing = 0
    evidence_boilerplate = 0
    preferred_top1 = 0
    lexical_top2 = 0
    support_examples: list[dict[str, str]] = []
    supports_by_category: Counter[str] = Counter()
    for support in supports:
        category = str(support["category_code"])
        option = str(support["option_code"])
        concept_id = str(support["concept_id"])
        evidence_id = str(support["evidence_chunk_id"])
        supports_by_category[category] += 1
        evidence = chunks_by_id.get(evidence_id)
        rows = public_chunks.get(concept_id, [])
        if evidence is None or evidence not in rows:
            evidence_missing += 1
            support_examples.append(
                {
                    "concept_id": concept_id,
                    "category_code": category,
                    "option_code": option,
                    "code": "EVIDENCE_NOT_PUBLIC_OR_MISSING",
                }
            )
            continue
        if is_wiki_boilerplate(evidence["content"]):
            evidence_boilerplate += 1
            support_examples.append(
                {
                    "concept_id": concept_id,
                    "category_code": category,
                    "option_code": option,
                    "code": "BOILERPLATE_USED_AS_SUPPORT",
                }
            )
        selected_groups = {category: [option]}
        preferred = rank_wiki_passages(
            rows,
            selected_groups=selected_groups,
            preferred_evidence_ids=[evidence_id],
            limit=1,
        )
        if preferred and str(preferred[0]["chunk_id"]) == evidence_id:
            preferred_top1 += 1
        lexical = rank_wiki_passages(
            rows,
            selected_groups=selected_groups,
            limit=2,
        )
        if evidence_id in {str(row["chunk_id"]) for row in lexical}:
            lexical_top2 += 1
        elif len(support_examples) < 50:
            support_examples.append(
                {
                    "concept_id": concept_id,
                    "category_code": category,
                    "option_code": option,
                    "code": "LEXICAL_TOP2_MISS",
                }
            )

    support_count = len(supports)
    preferred_rate = preferred_top1 / support_count if support_count else 0.0
    lexical_rate = lexical_top2 / support_count if support_count else 0.0
    critical_issue_codes = {
        "PROVENANCE_CONTRACT_INVALID",
        "UNSUPPORTED_POSITIVE_SAFETY_OVERCLAIM",
    }
    critical_issue_count = (
        sum(issue["code"] in critical_issue_codes for issue in document_issues)
        + evidence_missing
        + evidence_boilerplate
    )
    document_issues_by_code = Counter(issue["code"] for issue in document_issues)
    ordered_document_samples = sorted(
        document_issues,
        key=lambda issue: (
            0 if issue["code"] in critical_issue_codes else 1,
            0 if issue["code"] == "DUPLICATE_INFORMATIVE_PARAGRAPH" else 1,
            issue["code"],
            issue["source_path"],
        ),
    )
    gates = {
        "critical_issue_count_zero": critical_issue_count == 0,
        "all_support_evidence_public": evidence_missing == 0,
        "support_evidence_not_boilerplate": evidence_boilerplate == 0,
        "preferred_evidence_top1_rate_1_0": preferred_rate == 1.0,
        "lexical_evidence_top2_rate_at_least_0_90": lexical_rate >= 0.90,
        "all_general_descriptions_have_minimum_depth": min(
            informative_token_counts, default=0
        )
        >= 30,
    }
    return {
        "policy_version": WIKI_QUALITY_POLICY_VERSION,
        "pass": all(gates.values()),
        "gates": gates,
        "counts": {
            "documents": len(documents),
            "compiled_chunks": len(compiled.chunks),
            "public_concepts": len(public_chunks),
            "supports": support_count,
            "document_issues": len(document_issues),
            "document_warnings": len(document_issues) - sum(
                issue["code"] in critical_issue_codes for issue in document_issues
            ),
            "critical_issues": critical_issue_count,
            "exact_duplicate_informative_paragraph_groups": len(exact_duplicates),
            "evidence_missing_or_internal": evidence_missing,
            "evidence_boilerplate": evidence_boilerplate,
        },
        "quality": {
            "in_body_disclaimer_coverage": round(disclaimer_count / len(documents), 6)
            if documents
            else 0.0,
            "metadata_source_boundary_coverage": round(
                metadata_source_boundary_count / len(documents),
                6,
            )
            if documents
            else 0.0,
            "minimum_informative_token_count": min(informative_token_counts, default=0),
            "median_informative_token_count": sorted(informative_token_counts)[
                len(informative_token_counts) // 2
            ]
            if informative_token_counts
            else 0,
            "preferred_evidence_top1_rate": round(preferred_rate, 6),
            "lexical_evidence_top2_rate": round(lexical_rate, 6),
            "supports_by_category": dict(sorted(supports_by_category.items())),
            "document_issues_by_code": dict(sorted(document_issues_by_code.items())),
        },
        "document_issue_samples": ordered_document_samples[:50],
        "support_issue_samples": support_examples[:50],
    }
