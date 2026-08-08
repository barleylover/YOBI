from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.rag.embeddings import deterministic_embedding

EMBEDDING_MODEL = "yobi-semantic-hash-v1"
EMBEDDING_DIMENSION = 1536
EMBEDDING_VERSION = "2026-08-06"

FACET_ORDER = (
    "overview",
    "taste",
    "texture",
    "temperature",
    "satiety",
    "culture",
    "analogy",
    "ingredients",
    "safety",
)
REQUIRED_FACETS = frozenset(FACET_ORDER)

IngredientRole = Literal["DEFINING", "CORE", "COMMON", "OPTIONAL", "REGIONAL_VARIANT", "UNKNOWN"]
WikiAssertionStatus = Literal["PRESUMED_PRESENT", "POSSIBLE", "UNKNOWN", "CONFLICTING"]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ParentAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: str = Field(pattern=r"^dish_[a-z0-9_]+$")
    relation_type: Literal["IS_A", "VARIANT_OF", "SIMILAR_TO"] = "IS_A"
    inherit_claims: bool = True
    source_ref: str = Field(min_length=1, max_length=1000)


class IngredientClaimAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: str = Field(pattern=r"^ingredient_[a-z0-9_]+$")
    name_ko: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    role: IngredientRole
    status: WikiAssertionStatus
    source_ref: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def core_claims_are_positive_presumptions(self) -> IngredientClaimAuthoring:
        if self.role in {"DEFINING", "CORE"} and self.status != "PRESUMED_PRESENT":
            raise ValueError("DEFINING and CORE Wiki ingredients must be PRESUMED_PRESENT")
        return self


class AllergenClaimAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allergen_id: str = Field(pattern=r"^allergen_[a-z0-9_]+$")
    status: WikiAssertionStatus
    source_ref: str = Field(min_length=1, max_length=1000)


class DishFrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: str = Field(pattern=r"^dish_[a-z0-9_]+$")
    concept_type: Literal["CUISINE", "FAMILY", "VARIANT"]
    name_ko: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    version: str = Field(min_length=1, max_length=80)
    language: str = Field(default="en", min_length=2, max_length=16)
    parents: list[ParentAuthoring] = Field(default_factory=list)
    ingredients: list[IngredientClaimAuthoring] = Field(default_factory=list)
    allergens: list[AllergenClaimAuthoring] = Field(default_factory=list)
    source_type: Literal["SYNTHETIC_WIKI"] = "SYNTHETIC_WIKI"
    source_refs: list[str] = Field(min_length=1)
    license_state: Literal["SYNTHETIC"] = "SYNTHETIC"
    review_status: Literal["DRAFT", "REVIEWED_DEMO"]
    is_synthetic: Literal[True] = True
    updated_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def reject_duplicate_targets(self) -> DishFrontMatter:
        parent_ids = [item.concept_id for item in self.parents]
        ingredient_ids = [item.ingredient_id for item in self.ingredients]
        allergen_ids = [item.allergen_id for item in self.allergens]
        if len(parent_ids) != len(set(parent_ids)):
            raise ValueError("A concept cannot repeat the same parent")
        if len(ingredient_ids) != len(set(ingredient_ids)):
            raise ValueError("A concept cannot repeat the same ingredient claim")
        if len(allergen_ids) != len(set(allergen_ids)):
            raise ValueError("A concept cannot repeat the same allergen claim")
        if self.concept_id in parent_ids:
            raise ValueError("A concept cannot be its own parent")
        return self


class AuthoredDocument(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    front_matter: DishFrontMatter
    body: str
    facets: dict[str, str]


class CompiledKnowledgeRelease(BaseModel):
    release_id: str
    catalog_version: str
    manifest_sha256: str
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimension: int = EMBEDDING_DIMENSION
    embedding_version: str = EMBEDDING_VERSION
    expected_counts: dict[str, int]
    concepts: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    closure: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    chunks: list[dict[str, Any]]


def _facet_key(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", heading.strip().lower()).strip("_")


def _parse_body(body: str, path: Path) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = _facet_key(line[3:])
            if current in sections:
                raise ValueError(f"DUPLICATE_FACET:{path}:{current}")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    normalized = {key: "\n".join(lines).strip() for key, lines in sections.items()}
    missing = sorted(REQUIRED_FACETS - normalized.keys())
    empty = sorted(key for key in REQUIRED_FACETS if not normalized.get(key, "").strip())
    extra = sorted(normalized.keys() - REQUIRED_FACETS)
    if missing:
        raise ValueError(f"MISSING_FACETS:{path}:{','.join(missing)}")
    if empty:
        raise ValueError(f"EMPTY_FACETS:{path}:{','.join(empty)}")
    if extra:
        raise ValueError(f"UNKNOWN_FACETS:{path}:{','.join(extra)}")
    return normalized


def parse_document(path: Path) -> AuthoredDocument:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"FRONT_MATTER_START_REQUIRED:{path}")
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"FRONT_MATTER_END_REQUIRED:{path}") from exc
    front_matter_raw = "\n".join(lines[1:closing]).strip()
    try:
        payload = json.loads(front_matter_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"FRONT_MATTER_MUST_BE_JSON_AS_YAML:{path}") from exc
    front_matter = DishFrontMatter.model_validate(payload)
    body = "\n".join(lines[closing + 1 :]).strip()
    return AuthoredDocument(
        path=path,
        front_matter=front_matter,
        body=body,
        facets=_parse_body(body, path),
    )


def _validate_graph(documents: list[AuthoredDocument]) -> dict[str, AuthoredDocument]:
    by_id: dict[str, AuthoredDocument] = {}
    for document in documents:
        concept_id = document.front_matter.concept_id
        if concept_id in by_id:
            raise ValueError(f"DUPLICATE_CONCEPT_ID:{concept_id}")
        by_id[concept_id] = document
    for document in documents:
        for parent in document.front_matter.parents:
            if parent.concept_id not in by_id:
                raise ValueError(
                    f"DANGLING_PARENT:{document.front_matter.concept_id}:{parent.concept_id}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(concept_id: str) -> None:
        if concept_id in visiting:
            raise ValueError(f"CONCEPT_CYCLE:{concept_id}")
        if concept_id in visited:
            return
        visiting.add(concept_id)
        for parent in by_id[concept_id].front_matter.parents:
            visit(parent.concept_id)
        visiting.remove(concept_id)
        visited.add(concept_id)

    for concept_id in sorted(by_id):
        visit(concept_id)
    return by_id


def _build_closure(release_id: str, by_id: dict[str, AuthoredDocument]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for descendant in sorted(by_id):
        best: dict[str, tuple[int, bool]] = {descendant: (0, True)}
        queue: deque[tuple[str, int, bool]] = deque([(descendant, 0, True)])
        while queue:
            current, depth, inherited = queue.popleft()
            for parent in by_id[current].front_matter.parents:
                next_value = (depth + 1, inherited and parent.inherit_claims)
                previous = best.get(parent.concept_id)
                if previous is None or next_value[0] < previous[0]:
                    best[parent.concept_id] = next_value
                    queue.append((parent.concept_id, *next_value))
        for ancestor, (depth, inherited) in sorted(best.items()):
            rows.append(
                {
                    "release_id": release_id,
                    "descendant_concept_id": descendant,
                    "ancestor_concept_id": ancestor,
                    "depth": depth,
                    "inherit_claims": int(inherited),
                }
            )
    return rows


def compile_documents(
    documents: list[AuthoredDocument], *, release_id: str, catalog_version: str
) -> CompiledKnowledgeRelease:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", release_id):
        raise ValueError("INVALID_RELEASE_ID")
    by_id = _validate_graph(documents)
    concepts: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    document_rows: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []

    for concept_id, document in sorted(by_id.items()):
        front = document.front_matter
        source_path = document.path.as_posix()
        source_ref = front.source_refs[0]
        concepts.append(
            {
                "release_id": release_id,
                "concept_id": concept_id,
                "concept_type": front.concept_type,
                "canonical_name_ko": front.name_ko,
                "canonical_name_en": front.name_en,
                "aliases_json": _canonical_json(front.aliases),
                "source_type": front.source_type,
                "source_ref": source_ref,
                "review_status": front.review_status,
                "is_synthetic": 1,
                "updated_at": front.updated_at,
            }
        )
        for parent in front.parents:
            relation_seed = f"{concept_id}:{parent.relation_type}:{parent.concept_id}"
            relations.append(
                {
                    "release_id": release_id,
                    "relation_id": f"rel_{_sha256(relation_seed)[:24]}",
                    "source_concept_id": concept_id,
                    "target_concept_id": parent.concept_id,
                    "relation_type": parent.relation_type,
                    "inherit_claims": int(parent.inherit_claims),
                    "source_ref": parent.source_ref,
                    "is_synthetic": 1,
                    "updated_at": front.updated_at,
                }
            )
        for ingredient in front.ingredients:
            claims.append(
                {
                    "release_id": release_id,
                    "claim_id": f"claim_{_sha256(f'{concept_id}:ingredient:{ingredient.ingredient_id}')[:24]}",
                    "concept_id": concept_id,
                    "claim_type": "INGREDIENT",
                    "ingredient_id": ingredient.ingredient_id,
                    "allergen_id": None,
                    "attribute_id": None,
                    "facet_key": None,
                    "value_text": ingredient.name_en,
                    "ingredient_role": ingredient.role,
                    "assertion_status": ingredient.status,
                    "inheritance_mode": "INHERIT",
                    "source_ref": ingredient.source_ref,
                    "review_status": front.review_status,
                    "is_synthetic": 1,
                    "updated_at": front.updated_at,
                }
            )
        for allergen in front.allergens:
            claims.append(
                {
                    "release_id": release_id,
                    "claim_id": f"claim_{_sha256(f'{concept_id}:allergen:{allergen.allergen_id}')[:24]}",
                    "concept_id": concept_id,
                    "claim_type": "ALLERGEN",
                    "ingredient_id": None,
                    "allergen_id": allergen.allergen_id,
                    "attribute_id": None,
                    "facet_key": None,
                    "value_text": None,
                    "ingredient_role": None,
                    "assertion_status": allergen.status,
                    "inheritance_mode": "INHERIT",
                    "source_ref": allergen.source_ref,
                    "review_status": front.review_status,
                    "is_synthetic": 1,
                    "updated_at": front.updated_at,
                }
            )

        document_id = f"doc_{_sha256(f'{concept_id}:{front.language}:{front.version}')[:24]}"
        content_sha256 = _sha256(document.body)
        document_rows.append(
            {
                "release_id": release_id,
                "document_id": document_id,
                "concept_id": concept_id,
                "language": front.language,
                "title": front.name_en,
                "source_path": source_path,
                "front_matter_json": _canonical_json(front.model_dump(mode="json")),
                "content_markdown": document.body,
                "content_sha256": content_sha256,
                "source_type": front.source_type,
                "source_ref": source_ref,
                "license_state": front.license_state,
                "review_status": front.review_status,
                "is_synthetic": 1,
                "updated_at": front.updated_at,
            }
        )
        for chunk_index, facet in enumerate(FACET_ORDER):
            content = document.facets[facet]
            embedding_text = f"{front.name_en}\nFacet: {facet}\n{content}"
            content_hash = _sha256(content)
            chunk_id = f"chunk_{_sha256(f'{document_id}:{facet}:{content_hash}')[:24]}"
            vector = deterministic_embedding(f"document: {embedding_text}", EMBEDDING_DIMENSION)
            chunks.append(
                {
                    "release_id": release_id,
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "concept_id": concept_id,
                    "language": front.language,
                    "facet": facet,
                    "chunk_index": chunk_index,
                    "content": content,
                    "content_sha256": content_hash,
                    "metadata_json": _canonical_json(
                        {"concept_id": concept_id, "facet": facet, "source_path": source_path}
                    ),
                    "embedding_text": embedding_text,
                    "embedding_vector_json": _canonical_json(vector),
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimension": EMBEDDING_DIMENSION,
                    "embedding_version": EMBEDDING_VERSION,
                    "is_synthetic": 1,
                    "updated_at": front.updated_at,
                }
            )
            claims.append(
                {
                    "release_id": release_id,
                    "claim_id": f"claim_{_sha256(f'{concept_id}:facet:{facet}')[:24]}",
                    "concept_id": concept_id,
                    "claim_type": "FACET",
                    "ingredient_id": None,
                    "allergen_id": None,
                    "attribute_id": None,
                    "facet_key": facet,
                    "value_text": content,
                    "ingredient_role": None,
                    "assertion_status": "PRESUMED_PRESENT",
                    "inheritance_mode": "LOCAL_ONLY",
                    "source_ref": source_path,
                    "review_status": front.review_status,
                    "is_synthetic": 1,
                    "updated_at": front.updated_at,
                }
            )

    closure = _build_closure(release_id, by_id)
    counts = {
        "concepts": len(concepts),
        "relations": len(relations),
        "closure": len(closure),
        "claims": len(claims),
        "documents": len(document_rows),
        "chunks": len(chunks),
    }
    manifest_payload = {
        "release_id": release_id,
        "catalog_version": catalog_version,
        "embedding": {
            "model": EMBEDDING_MODEL,
            "dimension": EMBEDDING_DIMENSION,
            "version": EMBEDDING_VERSION,
        },
        "counts": counts,
        "documents": sorted((row["document_id"], row["content_sha256"]) for row in document_rows),
        "chunks": sorted((row["chunk_id"], row["content_sha256"]) for row in chunks),
    }
    return CompiledKnowledgeRelease(
        release_id=release_id,
        catalog_version=catalog_version,
        manifest_sha256=_sha256(_canonical_json(manifest_payload)),
        expected_counts=counts,
        concepts=concepts,
        relations=relations,
        closure=closure,
        claims=claims,
        documents=document_rows,
        chunks=chunks,
    )


def compile_directory(
    root: Path, *, release_id: str, catalog_version: str
) -> CompiledKnowledgeRelease:
    paths = sorted(root.rglob("*.md"))
    if not paths:
        raise ValueError(f"NO_KNOWLEDGE_DOCUMENTS:{root}")
    documents = [
        parse_document(path).model_copy(update={"path": path.relative_to(root)}) for path in paths
    ]
    return compile_documents(documents, release_id=release_id, catalog_version=catalog_version)


def reembed_release(
    compiled: CompiledKnowledgeRelease,
    vectors: list[list[float]],
    *,
    model: str,
    dimension: int,
    version: str,
) -> CompiledKnowledgeRelease:
    """Return the same authored release with a deployment-specific embedding index."""

    if dimension != EMBEDDING_DIMENSION:
        raise ValueError("KNOWLEDGE_EMBEDDING_DIMENSION_MISMATCH")
    if len(vectors) != len(compiled.chunks) or any(len(vector) != dimension for vector in vectors):
        raise ValueError("KNOWLEDGE_EMBEDDING_COUNT_OR_DIMENSION_MISMATCH")
    chunks = [
        {
            **chunk,
            "embedding_vector_json": _canonical_json(vector),
            "embedding_model": model,
            "embedding_dimension": dimension,
            "embedding_version": version,
        }
        for chunk, vector in zip(compiled.chunks, vectors)
    ]
    manifest_payload = {
        "release_id": compiled.release_id,
        "catalog_version": compiled.catalog_version,
        "embedding": {"model": model, "dimension": dimension, "version": version},
        "counts": compiled.expected_counts,
        "documents": sorted(
            (row["document_id"], row["content_sha256"]) for row in compiled.documents
        ),
        "chunks": sorted((row["chunk_id"], row["content_sha256"]) for row in chunks),
    }
    return compiled.model_copy(
        update={
            "manifest_sha256": _sha256(_canonical_json(manifest_payload)),
            "embedding_model": model,
            "embedding_dimension": dimension,
            "embedding_version": version,
            "chunks": chunks,
        }
    )
