# Structured recommendation RAG design

> Current product authority: [`STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`](STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md).
> This document describes the 2026-08-16 server-ranked source contract. The older
> free-chat design, allergy filtering, three-level spice scale, and model-selected
> final-order contract are historical and do not govern this path. Source code and a
> local mirror are not evidence of Oracle/OCI activation.

## Core contract

YOBI separates objective eligibility, reviewed semantic support, deterministic
ranking, and explanation:

1. The user commits structured preferences. Values inside a category use `OR`; every
   non-empty category expresses an `AND` intent for a normal recommendation.
2. The server removes objectively ineligible menus.
3. The repository joins release-bound, reviewed `CONCEPT_PREFERENCE_SUPPORT` rows.
4. The server computes an explicit score, applies stable tie-breaks and diversity, and
   freezes at most three menu IDs/order before any provider call.
5. One bounded generation request may explain exactly those frozen menus. The server
   rejects any changed or reordered menu and never silently weakens a condition.

The model owns wording only. It does not own preference eligibility, final choice or
order, serviceability, availability, price truth, spice truth, certification validity,
or confirmed vegan conflicts.

## Criteria and objective eligibility

`RecommendationCriteriaV2` contains cuisine origin, flavor, main ingredient, food
form, temperature, price band, texture, cooking method, a maximum spice level from
`1` to `5`, a `KR` or `US` spice-reference display, and the two explicit dietary
toggles `halal_certified_only` and `vegan`.

Those three safety/exact controls are capability-gated by the active preference
catalog. Halal needs current scoped certification coverage; vegan needs reviewed
menu-level ingredient coverage; spice needs reviewed menu-level `1..5` values. If the
minimum coverage is absent, the catalog returns `enabled=false` and a visible reason,
the browser submits the neutral value, and the server reports the unsupported control
rather than pretending that unknown data passed a filter. The external
`YOGIYO_PUBLIC_WEB` source currently supplies none of those reviewed facts.

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

The external merchant/menu/price/option catalog is a versioned
`YOGIYO_PUBLIC_WEB` observation, not a live Yogiyo API. The food Wiki describes
reusable cuisine, family, and variant concepts rather than a merchant's branded menu.
External general-food documents are `SYNTHETIC_WIKI` and `REVIEWED_DEMO`; derived
menu-name mappings are `YOBI_DERIVED_DEMO_MAPPING`. Only essential facts that remain true for the food identity
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

Reviews and merchant descriptions are not used for recommendation ranking,
eligibility, or model grounding. Source review counts may power the separately
labelled browse ranking view, but never the structured recommendation score. Changing
display prose or ranking proxies must not change the v2 evidence pool.

## Reviewed support, ranking, and evidence construction

The preference catalog owns stable codes and localized labels. A release builder
authors reviewed concept-to-preference support edges with explicit provenance,
strength, review status, and one evidence chunk. Same-category selected values use
maximum/`OR` support; a menu must have reviewed support for every selected category
(`AND`). Missing support is not manufactured from a nearest embedding hit.

The repository first runs one bounded SQL candidate query across the confirmed
service area, active high-confidence menu-to-concept mappings, objective filters, and
reviewed support. Candidate intake is capped and merchant-balanced so one merchant
cannot occupy more than 25% of the pre-freeze candidate set. The shared ranking policy
then uses explicit category support, minimum category support, reviewed-evidence
count, stable IDs, and diversity to freeze at most three menus. Rating, review text,
merchant marketing, and soft profile data have recommendation weight `0`.

Only after freeze does the repository fetch the bounded reviewed Wiki passages needed
to explain those menus. The current public form collects no age, religion, or favorite
foods, and the structured service sends only preferred language as soft provider
context. Nationality and hidden neutral placeholders do not affect candidate score or
category coverage.

Each pool item includes:

- an eligibility-checked, orderable `MenuSummary` with server-owned price, ETA, fee,
  and five-level spice value; raw address/service-area identifiers and an availability
  flag are not part of the generation payload;
- mapped Wiki concept and active knowledge/catalog/recommendation release IDs;
- selected category/value to evidence-ID mappings;
- public Wiki passages and objective menu facts;
- halal certification status/scope and vegan status/warning;
- explicit score, minimum category support, reviewed-evidence count, server rank, and
  versioned ranking trace.

The bounded candidate limit is `24`, the pre-freeze merchant share is at most 25%, and
at most three public passages are retained per frozen menu. Category/value evidence
references sent to generation retain IDs and scores without duplicating unbounded
source text. SQLite and Oracle share the same candidate/ranking policy; query-plan and
latency parity are release gates. Vector columns remain available for bounded
explanation retrieval and legacy compatibility, but a Vector Search hit cannot create
reviewed category support or choose final order. Static code checks do not prove that
live Oracle plans or data were exercised.

## Single generation dispatch

`RecommendationGenerator` receives only:

- committed criteria;
- minimal soft profile context (preferred language only);
- the frozen, ordered evidence payload;
- the requested locale and prompt version.

It performs at most one provider `generate` call per new recommendation request with
strict JSON schema output. There are no
tool schemas, agent loop, continuation request, automatic retry, or automatic model
fallback. The normal output returns `RECOMMENDED` with a criteria summary and exactly
the already frozen one-to-three recommendations. Provider `NO_MATCH`, omission,
replacement, or reordering is invalid because the server has already finalized the
result. Each recommendation must include the frozen menu ID and rank, reason,
description, active-category
matches, evidence IDs, Wiki passage IDs, and caution codes.

`RecommendationGenerationValidator` rejects:

- a menu ID/rank list different from the frozen candidates;
- missing evidence for an active preference category;
- a matched value that the user did not select;
- category or Wiki evidence IDs outside that menu's pool item;
- non-contiguous/duplicate result ranks; and
- internal IDs leaked into user-visible prose.

The service maps the validated echo back to server-owned menu data and keeps the
server's order. Objective
conditions are revalidated at current UTC against the pinned family before the
snapshot is committed. Newly ineligible menus are removed, while current price,
delivery fee/ETA, halal, and vegan fields replace their request-time projections; the
explanation prose and server relative order are retained. A later terminal-result GET applies
the same live projection without modifying the persisted model result or issuing a
generation call.

This validator proves structural grounding, not arbitrary natural-language
entailment. The prompt prohibits claims beyond supplied evidence, and halal/vegan
states shown by the product are mapped from server-owned pool fields rather than model
prose. A fluent but unsupported sentence that uses otherwise valid evidence IDs is a
model-quality/evaluation failure; the current code does not claim to detect every such
sentence deterministically.

## Empty, no-match, and failure behavior

- Empty objective/support result: complete as no result and make zero generation
  calls.
- Timeout, provider `NO_MATCH`, provider error, or invalid grounding: render the same
  frozen server-ranked menus as `SEARCH_FALLBACK`, with deterministic explanation and
  no second generation call.
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
price, spice, certification, and vegan eligibility. Wiki evidence opens the already
received payload; comparison uses the dedicated snapshot-bound endpoint. Editing
commits a new criteria version and `SIMILAR` creates a new recommendation request.
`SIMILAR` retains
the same objective and subjective criteria, excludes server-recorded
shown/rejected/selected menu IDs, builds a new pool, and may perform one generation
dispatch for that new request. The recommendation surface has no free-text input.

Comparison is an explicit optional operation, not part of the ranking call. Given a
completed 2-3-menu snapshot, the server may make one separate bounded comparison-
writing call, validates the unchanged menu IDs, and caches the result by idempotency
key. Failure returns a deterministic comparison of the same frozen menus without a
retry. Wiki evidence expansion makes no provider call. The ranking and featured-food
browse APIs make no recommendation-generation call and save only snapshot-authorized
menu selections.

## Evaluation boundary

Local source evidence covers the prose-first compiler/catalog, reviewed support and
server ranking, request ledger and one-dispatch service behavior, frozen-order
validator, comparison cache/fallback, browse APIs, frontend contracts, and SQLite
integration. Fake-provider tests can prove exact dispatch counts and server-order
enforcement; they cannot prove live model quality. Deterministic SQLite vectors
prove data/contract continuity, not semantic quality or Oracle query behavior.

Live Oracle migration and vector execution, OCI provider one-call behavior, Nginx and
systemd activation, and the public browser flow remain separate deployment gates.
Only dated, release-specific results in [`TEST_REPORT.md`](TEST_REPORT.md) may be used
as evidence for those boundaries.
