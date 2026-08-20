from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.rag.embeddings import deterministic_embedding

EMBEDDING_MODEL = "yobi-semantic-hash-v1"
EMBEDDING_DIMENSION = 1536
EMBEDDING_VERSION = "2026-08-06"

# Kept as a named compatibility contract for authored releases produced before
# the prose-first compiler. New documents do not have to provide these headings.
LEGACY_FACET_ORDER = (
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
FACET_ORDER = LEGACY_FACET_ORDER
REQUIRED_FACETS = frozenset(LEGACY_FACET_ORDER)

PARAGRAPH_FACET = "paragraph"
ESSENTIAL_FACT_FACET = "essential_fact"
PROSE_CONTENT_CONTRACT: Literal["PROSE_PARAGRAPHS_V2"] = "PROSE_PARAGRAPHS_V2"
LEGACY_CONTENT_CONTRACT: Literal["LEGACY_NINE_FACETS_V1"] = "LEGACY_NINE_FACETS_V1"

ChunkKind = Literal["PARAGRAPH", "ESSENTIAL_FACT", "LEGACY_FACET"]
ContentContract = Literal["PROSE_PARAGRAPHS_V2", "LEGACY_NINE_FACETS_V1"]

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


class DietaryClaimAuthoring(BaseModel):
    """A reusable dietary or religious-risk assertion about a universal dish concept."""

    model_config = ConfigDict(extra="forbid")

    attribute_id: str = Field(pattern=r"^diet_[a-z0-9_]+$")
    value_text: str = Field(min_length=1, max_length=300)
    status: WikiAssertionStatus
    source_ref: str = Field(min_length=1, max_length=1000)


class PreparationClaimAuthoring(BaseModel):
    """A stable preparation method, kept separate from free-form Wiki prose."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(pattern=r"^[a-z0-9_]+$", min_length=2, max_length=80)
    value_text: str = Field(min_length=1, max_length=300)
    status: WikiAssertionStatus = "PRESUMED_PRESENT"
    source_ref: str = Field(min_length=1, max_length=1000)


class EssentialIngredientFactAuthoring(BaseModel):
    """An ingredient without which the authored dish identity would materially change."""

    model_config = ConfigDict(extra="forbid")

    fact_type: Literal["INGREDIENT"]
    ingredient_id: str = Field(pattern=r"^ingredient_[a-z0-9_]+$")
    name_ko: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    role: Literal["DEFINING", "CORE"]
    status: Literal["PRESUMED_PRESENT"] = "PRESUMED_PRESENT"
    source_ref: str = Field(min_length=1, max_length=1000)


class EssentialPreparationFactAuthoring(BaseModel):
    """A defining preparation fact, not a subjective cooking-style preference tag."""

    model_config = ConfigDict(extra="forbid")

    fact_type: Literal["PREPARATION"]
    method: str = Field(pattern=r"^[a-z0-9_]+$", min_length=2, max_length=80)
    value_text: str = Field(min_length=1, max_length=300)
    status: Literal["PRESUMED_PRESENT"] = "PRESUMED_PRESENT"
    source_ref: str = Field(min_length=1, max_length=1000)


EssentialFactAuthoring = Annotated[
    Union[EssentialIngredientFactAuthoring, EssentialPreparationFactAuthoring],
    Field(discriminator="fact_type"),
]


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
    essential_facts: list[EssentialFactAuthoring] = Field(default_factory=list)
    # Legacy fields remain readable so an old authored release can still be
    # reconstructed. Prose-first sources use only ``essential_facts``.
    ingredients: list[IngredientClaimAuthoring] = Field(default_factory=list)
    allergens: list[AllergenClaimAuthoring] = Field(default_factory=list)
    dietary: list[DietaryClaimAuthoring] = Field(default_factory=list)
    preparation: list[PreparationClaimAuthoring] = Field(default_factory=list)
    source_type: Literal["SYNTHETIC_WIKI"] = "SYNTHETIC_WIKI"
    source_refs: list[str] = Field(min_length=1)
    license_state: Literal["SYNTHETIC"] = "SYNTHETIC"
    review_status: Literal["DRAFT", "REVIEWED_DEMO"]
    is_synthetic: Literal[True] = True
    updated_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def reject_duplicate_targets(self) -> DishFrontMatter:
        essential_ingredient_ids = [
            item.ingredient_id
            for item in self.essential_facts
            if isinstance(item, EssentialIngredientFactAuthoring)
        ]
        essential_preparation_methods = [
            item.method
            for item in self.essential_facts
            if isinstance(item, EssentialPreparationFactAuthoring)
        ]
        if len(essential_ingredient_ids) != len(set(essential_ingredient_ids)):
            raise ValueError("A concept cannot repeat the same essential ingredient fact")
        if len(essential_preparation_methods) != len(set(essential_preparation_methods)):
            raise ValueError("A concept cannot repeat the same essential preparation fact")

        # Project the new minimal facts into the legacy in-memory attributes.
        # Existing seed consumers can migrate independently without making new
        # source files duplicate the old front-matter structures.
        if self.essential_facts:
            projected_ingredients = [
                IngredientClaimAuthoring.model_validate(item.model_dump(exclude={"fact_type"}))
                for item in self.essential_facts
                if isinstance(item, EssentialIngredientFactAuthoring)
            ]
            projected_preparation = [
                PreparationClaimAuthoring.model_validate(item.model_dump(exclude={"fact_type"}))
                for item in self.essential_facts
                if isinstance(item, EssentialPreparationFactAuthoring)
            ]
            if self.allergens or self.dietary:
                raise ValueError("ESSENTIAL_FACTS_CANNOT_MIX_WITH_LEGACY_CLAIMS")
            if self.ingredients and self.ingredients != projected_ingredients:
                raise ValueError("ESSENTIAL_FACTS_CANNOT_MIX_WITH_LEGACY_CLAIMS")
            if self.preparation and self.preparation != projected_preparation:
                raise ValueError("ESSENTIAL_FACTS_CANNOT_MIX_WITH_LEGACY_CLAIMS")
            self.ingredients = projected_ingredients
            self.preparation = projected_preparation

        parent_ids = [item.concept_id for item in self.parents]
        ingredient_ids = [item.ingredient_id for item in self.ingredients]
        allergen_ids = [item.allergen_id for item in self.allergens]
        dietary_ids = [item.attribute_id for item in self.dietary]
        preparation_methods = [item.method for item in self.preparation]
        if len(parent_ids) != len(set(parent_ids)):
            raise ValueError("A concept cannot repeat the same parent")
        if len(ingredient_ids) != len(set(ingredient_ids)):
            raise ValueError("A concept cannot repeat the same ingredient claim")
        if len(allergen_ids) != len(set(allergen_ids)):
            raise ValueError("A concept cannot repeat the same allergen claim")
        if len(dietary_ids) != len(set(dietary_ids)):
            raise ValueError("A concept cannot repeat the same dietary claim")
        if len(preparation_methods) != len(set(preparation_methods)):
            raise ValueError("A concept cannot repeat the same preparation method")
        if self.concept_id in parent_ids:
            raise ValueError("A concept cannot be its own parent")
        return self


class AuthoredParagraph(BaseModel):
    model_config = ConfigDict(frozen=True)

    heading_path: tuple[str, ...]
    paragraph_index: int = Field(ge=0)
    content: str = Field(min_length=1)


class AuthoredDocument(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    front_matter: DishFrontMatter
    front_matter_payload: dict[str, Any]
    body: str
    content_contract: ContentContract
    paragraphs: list[AuthoredParagraph]
    # Compatibility projection for the old menu seed. The prose compiler does
    # not consume this mapping and future documents need not provide nine parts.
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


def _parse_legacy_facets(body: str, path: Path) -> dict[str, str] | None:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = _facet_key(line[3:])
            if current in sections:
                return None
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    normalized = {key: "\n".join(lines).strip() for key, lines in sections.items()}
    if set(normalized) != REQUIRED_FACETS:
        return None
    if any(not normalized[key].strip() for key in REQUIRED_FACETS):
        return None
    return normalized


def _parse_paragraphs(body: str, path: Path) -> list[AuthoredParagraph]:
    """Parse natural Markdown headings and paragraphs without imposing a facet taxonomy."""

    headings: list[tuple[int, str]] = []
    blocks: list[tuple[tuple[str, ...], str]] = []
    current_lines: list[str] = []

    def flush() -> None:
        if not current_lines:
            return
        content = "\n".join(current_lines).strip()
        current_lines.clear()
        if content:
            blocks.append((tuple(value for _, value in headings), content))

    for line in body.splitlines():
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            headings[:] = [
                (item_level, value) for item_level, value in headings if item_level < level
            ]
            headings.append((level, title))
            continue
        if not line.strip():
            flush()
            continue
        current_lines.append(line.rstrip())
    flush()

    if not blocks:
        raise ValueError(f"WIKI_PROSE_PARAGRAPH_REQUIRED:{path}")
    return [
        AuthoredParagraph(
            heading_path=heading_path,
            paragraph_index=index,
            content=content,
        )
        for index, (heading_path, content) in enumerate(blocks)
    ]


_MIGRATED_SECTION_PATHS = (
    "Character and experience",
    "Context and comparisons",
    "Ingredients and variations",
)


def _legacy_seed_projection(paragraphs: list[AuthoredParagraph]) -> dict[str, str]:
    """Temporarily project the migrated corpus for legacy seed consumers.

    The new compiler never consumes this mapping. It exists only because the
    current menu seed still derives a short description from the old prose.
    Once that consumer moves to paragraph summaries this function can be removed.
    """

    if len(paragraphs) != len(LEGACY_FACET_ORDER):
        return {}
    second_level_headings = tuple(
        dict.fromkeys(
            paragraph.heading_path[-1] for paragraph in paragraphs if paragraph.heading_path
        )
    )
    if second_level_headings != _MIGRATED_SECTION_PATHS:
        return {}
    return {facet: paragraph.content for facet, paragraph in zip(LEGACY_FACET_ORDER, paragraphs)}


def _migrated_source_facet(document: AuthoredDocument, paragraph: AuthoredParagraph) -> str | None:
    """Return migration provenance without making facets a v2 authoring requirement."""

    if (
        document.content_contract != PROSE_CONTENT_CONTRACT
        or tuple(document.facets) != LEGACY_FACET_ORDER
        or len(document.paragraphs) != len(LEGACY_FACET_ORDER)
    ):
        return None
    return LEGACY_FACET_ORDER[paragraph.paragraph_index]


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
    legacy_facets = _parse_legacy_facets(body, path)
    paragraphs = _parse_paragraphs(body, path)
    content_contract: ContentContract = (
        LEGACY_CONTENT_CONTRACT if legacy_facets is not None else PROSE_CONTENT_CONTRACT
    )
    compatibility_facets = legacy_facets or _legacy_seed_projection(paragraphs)
    return AuthoredDocument(
        path=path,
        front_matter=front_matter,
        front_matter_payload=payload,
        body=body,
        content_contract=content_contract,
        paragraphs=paragraphs,
        facets=compatibility_facets,
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
        for dietary in front.dietary:
            claims.append(
                {
                    "release_id": release_id,
                    "claim_id": f"claim_{_sha256(f'{concept_id}:dietary:{dietary.attribute_id}')[:24]}",
                    "concept_id": concept_id,
                    "claim_type": "DIETARY",
                    "ingredient_id": None,
                    "allergen_id": None,
                    "attribute_id": dietary.attribute_id,
                    "facet_key": None,
                    "value_text": dietary.value_text,
                    "ingredient_role": None,
                    "assertion_status": dietary.status,
                    "inheritance_mode": "INHERIT",
                    "source_ref": dietary.source_ref,
                    "review_status": front.review_status,
                    "is_synthetic": 1,
                    "updated_at": front.updated_at,
                }
            )
        for preparation in front.preparation:
            claims.append(
                {
                    "release_id": release_id,
                    "claim_id": f"claim_{_sha256(f'{concept_id}:preparation:{preparation.method}')[:24]}",
                    "concept_id": concept_id,
                    "claim_type": "PREPARATION",
                    "ingredient_id": None,
                    "allergen_id": None,
                    "attribute_id": None,
                    "facet_key": preparation.method,
                    "value_text": preparation.value_text,
                    "ingredient_role": None,
                    "assertion_status": preparation.status,
                    "inheritance_mode": "INHERIT",
                    "source_ref": preparation.source_ref,
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
                # Preserve the exact authored schema. Prose-first documents must
                # not be expanded back into the deprecated legacy claim arrays.
                "front_matter_json": _canonical_json(document.front_matter_payload),
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
        for paragraph in document.paragraphs:
            chunk_index = paragraph.paragraph_index
            content = paragraph.content
            heading_path = list(paragraph.heading_path)
            heading_text = " > ".join(heading_path)
            chunk_kind: ChunkKind = (
                "LEGACY_FACET"
                if document.content_contract == LEGACY_CONTENT_CONTRACT
                else "PARAGRAPH"
            )
            if chunk_kind == "LEGACY_FACET":
                facet = _facet_key(heading_path[-1]) if heading_path else "overview"
                embedding_text = f"{front.name_en}\nFacet: {facet}\n{content}"
            else:
                facet = PARAGRAPH_FACET
                embedding_text = f"{front.name_en}\n{heading_text}\n{content}"
            content_hash = _sha256(content)
            chunk_seed = f"{document_id}:{chunk_kind}:{chunk_index}:{heading_text}:{content_hash}"
            chunk_id = f"chunk_{_sha256(chunk_seed)[:24]}"
            vector = deterministic_embedding(f"document: {embedding_text}", EMBEDDING_DIMENSION)
            metadata = {
                "chunk_kind": chunk_kind,
                "concept_id": concept_id,
                "heading_path": heading_path,
                "paragraph_index": chunk_index,
                "review_status": front.review_status,
                "source_path": source_path,
                "source_ref": source_ref,
            }
            if chunk_kind == "LEGACY_FACET":
                metadata["facet"] = facet
            else:
                migrated_source_facet = _migrated_source_facet(document, paragraph)
                metadata["migrated_source_facet"] = migrated_source_facet
                # Allergy is no longer a user feature. Preserve the original
                # prose inside the immutable Wiki document and chunk, but keep
                # the migrated Safety paragraph out of public recommendation
                # evidence. Other prose remains prose, never a structured fact.
                metadata["recommendation_visibility"] = (
                    "INTERNAL_ONLY" if migrated_source_facet == "safety" else "PUBLIC_RAG"
                )
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
                    "metadata_json": _canonical_json(metadata),
                    "embedding_text": embedding_text,
                    "embedding_vector_json": _canonical_json(vector),
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimension": EMBEDDING_DIMENSION,
                    "embedding_version": EMBEDDING_VERSION,
                    "is_synthetic": 1,
                    "updated_at": front.updated_at,
                }
            )
            # Existing releases retain their historical FACET claim rows. New
            # prose is retrieval evidence, not an objective factual assertion.
            if chunk_kind == "LEGACY_FACET":
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

        if document.content_contract == PROSE_CONTENT_CONTRACT:
            for fact_offset, fact in enumerate(
                front.essential_facts, start=len(document.paragraphs)
            ):
                if isinstance(fact, EssentialIngredientFactAuthoring):
                    fact_key = fact.ingredient_id
                    content = f"{fact.role.title()} ingredient: {fact.name_en} ({fact.name_ko})."
                    source_ref_for_fact = fact.source_ref
                else:
                    fact_key = fact.method
                    content = f"Defining preparation: {fact.value_text}"
                    source_ref_for_fact = fact.source_ref
                content_hash = _sha256(content)
                chunk_seed = f"{document_id}:ESSENTIAL_FACT:{fact.fact_type}:{fact_key}"
                chunk_id = f"chunk_{_sha256(chunk_seed)[:24]}"
                aliases = " | ".join([front.name_en, front.name_ko, *front.aliases])
                embedding_text = f"{aliases}\nEssential {fact.fact_type.lower()}\n{content}"
                vector = deterministic_embedding(f"document: {embedding_text}", EMBEDDING_DIMENSION)
                chunks.append(
                    {
                        "release_id": release_id,
                        "chunk_id": chunk_id,
                        "document_id": document_id,
                        "concept_id": concept_id,
                        "language": front.language,
                        # Non-null compatibility sentinel for the current v1 DB
                        # column. V2 retrieval reads chunk_kind from metadata.
                        "facet": ESSENTIAL_FACT_FACET,
                        "chunk_index": fact_offset,
                        "content": content,
                        "content_sha256": content_hash,
                        "metadata_json": _canonical_json(
                            {
                                "chunk_kind": "ESSENTIAL_FACT",
                                "concept_id": concept_id,
                                "fact_key": fact_key,
                                "fact_type": fact.fact_type,
                                "heading_path": [],
                                "paragraph_index": None,
                                "review_status": front.review_status,
                                "recommendation_visibility": "PUBLIC_RAG",
                                "source_path": source_path,
                                "source_ref": source_ref_for_fact,
                            }
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
