# Structured recommendation RAG design

> Current product authority: [`STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`](STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md).
> This document describes the local 2026-08-12 v2 source contract. The older
> free-chat design, allergy filtering, three-level spice scale, and server-final-
> shortlist contract are historical and do not govern this path.

## Core contract

YOBI separates objective eligibility, broad evidence retrieval, and final subjective
choice:

1. The user commits structured preferences. Values inside a category use `OR`; every
   non-empty category expresses an `AND` intent for a normal recommendation.
2. The server removes objectively ineligible menus.
3. The server combines lexical and embedding evidence to build a broad, auditable
   Wiki evidence pool.
4. One bounded generation request chooses the final menu IDs from that pool and
   writes grounded explanations in the same response.
5. The server validates the response and preserves the valid model order. It never
   substitutes a menu from outside the pool or silently weakens a condition.

The model therefore owns final preference judgment only inside a server-owned pool.
It does not own serviceability, availability, price truth, spice truth, certification
validity, or confirmed vegan conflicts.

## Criteria and objective eligibility

`RecommendationCriteriaV2` contains cuisine origin, flavor, main ingredient, food
form, temperature, price band, texture, cooking method, a maximum spice level from
`1` to `5`, a `KR` or `US` spice-reference display, and the two explicit dietary
toggles `halal_certified_only` and `vegan`.

Before retrieval, the repository checks:

- confirmed address service area matching the merchant service area;
- menu availability (`AVAILABLE`); the current merchant row has no separate active flag;
- server-owned base price against any selected price bands;
- reviewed menu spice level against the user's maximum;
- an active, in-scope merchant or menu halal certification when requested;
- confirmed animal-derived conflicts for vegan requests;
- menu history exclusions for a `SIMILAR` request.

Vegan candidates with a supported but changeable option path may remain with a
check-before-ordering warning. Candidates with no usable vegan evidence are excluded
when the vegan filter is active. Halal and vegan are never inferred from nationality,
locale, religion, or legacy profile rules. Allergy inputs and claims are not part of
the public v2 retrieval, generation context, result, or checkout contract.

## Prose-first Wiki

The food Wiki describes reusable cuisine, family, and variant concepts rather than a
merchant's branded menu. Only essential facts that remain true for the food identity
are structured: stable IDs and aliases, concept relationships, defining ingredients
or preparation, mappings, sources, and review status. Subjective taste, texture,
temperature impressions, cultural context, and serving situations remain natural
Markdown paragraphs.

Compilation produces two public chunk kinds:

- `PARAGRAPH` for prose passages;
- `ESSENTIAL_FACT` for allowlisted objective facts rendered as readable evidence.

The compiler also retains `LEGACY_FACET` compatibility. Each chunk carries the
document/concept/release identity, heading path, paragraph index, source/review
metadata, content hash, and embedding identity. Legacy safety paragraphs are marked
`INTERNAL_ONLY`; v2 retrieval admits only `PUBLIC_RAG` content, with a compatibility
fallback that excludes an old `safety` facet when visibility metadata is absent.

Reviews and merchant descriptions are not used for ranking, eligibility, or model
grounding. Changing that synthetic display prose must not change the v2 evidence pool.

## Hybrid evidence-pool construction

The preference catalog owns stable selection codes, locale labels, and query aliases.
For each selected value, the repository creates a localized search string and embeds
it with the embedding contract pinned by the active release family. Nationality,
age band, and stored favorite foods may form one lower-weight soft-profile query. That
query can adjust pool recall but never counts toward category coverage and cannot
override explicit criteria or objective eligibility.

For every selected value, retrieval scores unique public passages inherited through
objectively eligible menus' mapped Wiki concepts. Vector, lexical, and exact/essential
signals produce independent stable ranks that are fused with reciprocal-rank fusion;
only the configured `raw_hits_per_selected_value` enter menu evidence. Values in the
same category compete with max/`OR` semantics, while a menu must retain hit evidence
for every active category before entering a normal-generation pool. Stable chunk and
menu IDs break ties. This avoids manufacturing category coverage from a zero-score
“best” passage, but it is still structural coverage rather than proof of semantic
entailment. The one-call model is instructed to choose only when those passages
genuinely support the cross-category `AND`, and live quality evaluation must measure
that judgment. A bounded set of the strongest passages, current menu facts, and any
applicable certification evidence forms one `EvidencePoolItem`.

Each pool item includes:

- an eligibility-checked, orderable `MenuSummary` with server-owned price, ETA, fee,
  and five-level spice value; raw address/service-area identifiers and an availability
  flag are not part of the generation payload;
- mapped Wiki concept and active knowledge/catalog/recommendation release IDs;
- selected category/value to evidence-ID mappings;
- public Wiki passages and objective menu facts;
- halal certification status/scope and vegan status/warning;
- a retrieval score used only to bound the broad pool.

The configured default pool limit is `24`, with at most four public passages retained
per menu. Category/value evidence references sent to generation retain IDs and scores,
not duplicate passage bodies; prose content is available only through that bounded
Wiki-passage list. This retrieval order is an input-bounding mechanism, not the final
result order. SQLite computes deterministic embeddings and cosine similarity in the
application for local parity. The Oracle implementation calls
`VECTOR_DISTANCE(..., COSINE)` with the configured search-query embedding provider.
Static Oracle code checks do not prove that live Oracle Vector Search has run.

## Single generation dispatch

`RecommendationGenerator` receives only:

- committed criteria;
- minimal soft profile context (language, nationality, age band, favorite foods);
- the bounded evidence-pool payload;
- the requested locale and prompt version.

It performs one provider `generate` call with strict JSON schema output. There are no
tool schemas, agent loop, continuation request, automatic retry, or automatic model
fallback. The normal output returns `RECOMMENDED` with a criteria summary and up to
three ordered recommendations, or `NO_MATCH` with no menu. Each recommendation must
include its pool menu ID, contiguous rank, reason, description, active-category
matches, evidence IDs, Wiki passage IDs, and caution codes.

`RecommendationGenerationValidator` rejects:

- more than the configured result limit;
- a menu ID outside the stored pool;
- missing evidence for an active preference category;
- a matched value that the user did not select;
- category or Wiki evidence IDs outside that menu's pool item;
- non-contiguous/duplicate result ranks; and
- internal IDs leaked into user-visible prose.

The service maps the validated IDs back to server-owned menu data and keeps the
model's order. It does not rerank a valid result using retrieval score. Objective
conditions are revalidated at current UTC against the pinned family before the
snapshot is committed. Newly ineligible menus are removed, while current price,
delivery fee/ETA, halal, and vegan fields replace their request-time projections; the
model prose and valid relative order are retained. A later terminal-result GET applies
the same live projection without modifying the persisted model result or issuing a
generation call.

This validator proves structural grounding, not arbitrary natural-language
entailment. The prompt prohibits claims beyond supplied evidence, and halal/vegan
states shown by the product are mapped from server-owned pool fields rather than model
prose. A fluent but unsupported sentence that uses otherwise valid evidence IDs is a
model-quality/evaluation failure; the current code does not claim to detect every such
sentence deterministically.

## Empty, no-match, and failure behavior

- Empty objective/retrieval pool: complete as no result and make zero generation
  calls.
- Model `NO_MATCH`: show no recommendation; do not relax criteria and do not issue a
  second call.
- Timeout, provider error, or invalid grounding: return the nearest saved search
  results as `SEARCH_FALLBACK`, with distinct UI copy, no claim that every subjective
  category is satisfied, and no second generation call.
- Stale `CREATED` before dispatch: mark failed with `RETRIEVAL_OWNER_LOST`; do not leave
  a permanent pending request. An explicit retry uses a new request ID.
- Crash after `DISPATCHED`: expose `UNKNOWN_AFTER_DISPATCH`; never guess that the
  provider did not process the request and never redispatch automatically.
- Explicit retry: the user creates a new request ID, which is a new permitted
  generation attempt.

## Snapshots, replay, and follow-up actions

The request ledger stores request hash, criteria version, evidence-pool payload,
dispatch count, status, result/failure, and timestamps. An identical replay returns
the saved result with no additional generation. Reusing an ID for a different
semantic request is rejected.

A selectable result is persisted with its `RecommendationSnapshot`. `SELECT_MENU` is a
snapshot-backed server event that revalidates current UTC availability, service area,
price, spice, certification, and vegan eligibility. Evidence and comparison open the
already received snapshot/menu payload in the browser, while editing commits a new
criteria version and `SIMILAR` creates a new recommendation request. `SIMILAR` retains
the same objective and subjective criteria, excludes server-recorded
shown/rejected/selected menu IDs, builds a new pool, and may perform one generation
dispatch for that new request. The recommendation surface has no free-text input.

## Evaluation boundary

Local source evidence currently covers the prose-first compiler/catalog, request
ledger and one-dispatch service behavior, grounding validator, API/frontend contracts,
and SQLite integration. Fake-provider tests can prove exact dispatch counts and model
order preservation; they cannot prove live model quality. Deterministic SQLite vectors
prove data/contract continuity, not semantic quality or Oracle query behavior.

Live Oracle migration and vector execution, OCI provider one-call behavior, Nginx and
systemd activation, and the public browser flow remain separate deployment gates.
Only dated, release-specific results in [`TEST_REPORT.md`](TEST_REPORT.md) may be used
as evidence for those boundaries.
