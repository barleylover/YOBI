# Data model

> Counts below describe the 2026-08-12 local structured-recommendation source
> contract. Migration `010` and the v4 prose-first knowledge catalog have not been
> applied to Oracle or activated on OCI. Historical live database evidence does not
> prove the current schema/runtime path.

YOBI keeps ordering facts, conversation state, and menu knowledge in one relational
contract. Oracle is the deployed database and SQLite is the local contract-compatible
implementation. Oracle schema changes are applied only by the sequential migration
runner; FastAPI uses `YOBI_APP`, and production configuration rejects `ADMIN`.

## Core catalog and ordering state

The base synthetic catalog is stored in `SERVICE_AREA`, `MENU_CATEGORY`, `MERCHANT`,
`MENU`, `MENU_OPTION_GROUP`, `MENU_OPTION_ITEM`, `EVIDENCE`, `MENU_KNOWLEDGE`, and
`ADDRESS_PLACE`. `REVIEW_SNIPPET` is retained for the demo UI and backward
compatibility, but it has recommendation and safety weight `0`.

User/runtime state is stored in `USER_PROFILE`, `CHAT_SESSION`, `CHAT_MESSAGE`,
`ADDRESS_REF`, `CART`, `CART_ITEM`, `DELIVERY_PREFERENCE`, `MOCK_CHECKOUT`, and
`MOCK_ORDER`. Prices, required options, cart totals, checkout transitions, and mock
order idempotency remain server-authoritative. `AUDIT_LOG` is the safe operational
event sink. `SCHEMA_MIGRATION` records each immutable migration filename, SHA-256
checksum, and application time.

`USER_PROFILE` retains the historical religion, dietary/allergy, and `1..3` spice
columns for additive-schema compatibility. The current structured recommendation UI
does not collect or consume allergy values, does not infer filters from religion or
nationality, and does not use the legacy profile spice value. Its current-meal
criteria have explicit halal/vegan booleans and an independent `1..5` maximum.

The deterministic Wiki-centric seed currently expects 3 service areas, 100 categories,
60 merchants, 600 menus, 600 legacy menu-knowledge rows, 1,200 evidence rows, 2,400
review snippets, 1,202 option groups, 2,405 option items, and 20 address fixtures. The
normalized taxonomy contains 48 ingredients, 8 legacy allergen identifiers, and 15
dietary attributes. The structured v2 public path does not expose allergy filtering;
all demo-owned rows are synthetic. Exact counts are enforced in
`scripts/seed_demo.py`; changing the catalog requires changing its fixture and
integrity expectations together. The base catalog version is
`demo-2026.08.11-knowledge-v3`.

The seed deliberately does not pretend that every merchant publishes a complete
recipe or allergen specification. Menu-level ingredient facts cover 206 of 600 menus
(565 rows), legacy allergen facts cover 39 menus (48 rows), and dietary attributes
contain 1,217 menu links. The remaining gaps stay unknown and are resolved with
reusable Wiki family/variant knowledge, never fabricated merchant prose. The 2,400
reviews remain available for display compatibility but carry ranking and safety weight
`0`.
Each merchant has a ten-menu roster biased toward one dominant food family plus
related variants, rather than a random copy of the full catalog. Availability is 510
`AVAILABLE`, 60 `SOLD_OUT`, and 30 `PAUSED`, so the demo exercises availability
filtering without needing additional locations.

## Legacy conversation state and shared snapshots

The migration-005 fields below remain because historical conversations, selection
events, and the existing order flow still read them. They are not the input model for
the new recommendation selector.

Migration `005_conversation_state.sql` extends `CHAT_SESSION` with:

- `meal_need_state_json`: cumulative, server-validated `MealNeedState`;
- `dialogue_act`: the current server-owned `DialogueAct`;
- `state_version`: optimistic concurrency version for state/event writes.

In the historical v1 path, `MealNeedState` includes budget, spice, party size,
service area, positive and negative sensory preferences, excluded
categories/ingredients, profile and
conversation dietary rules, recommendation hold, shown/rejected/selected menus, and
option selections. A turn produces a validated `PreferenceDelta`; it never replaces
unrelated earlier constraints merely because the latest message omits them.

The v2 path writes `SESSION_RECOMMENDATION_CRITERIA` instead. It reads only committed
stable selection codes, explicit halal/vegan choices, the five-level maximum, and the
KR/US reference choice. `MealNeedState` remains useful for server-owned
shown/rejected/selected history and order selection, but legacy free-text need
collection and readiness do not choose when v2 recommendations run.

Historical v1 `RECOMMENDATION_SNAPSHOT` rows are paired with the exact visible assistant
message. Structured v2 reuses the same snapshot authorization boundary but writes a
non-user-visible internal audit message ID instead of rendering a chat turn. The
snapshot still stores state version, `RecommendationResult`, candidate order, and card
payload. `CONVERSATION_EVENT` retains select, reject, compare, and option-update event
types with a per-session idempotency key and resulting state version. The current v2
browser writes `SELECT_MENU`; comparison/evidence are local views of the received
payload, and `SIMILAR` uses the recommendation-request API rather than a compare event.

## Versioned menu Wiki and knowledge graph

Migration `006_knowledge_graph.sql` introduces a release-scoped relational graph:

| Table | Purpose |
|---|---|
| `KNOWLEDGE_RELEASE` | Manifest, catalog version, embedding model/dimension/version, expected/actual counts, and release state |
| `DISH_CONCEPT` | Reusable cuisine, family, and variant nodes |
| `DISH_RELATION` | `IS_A`, `VARIANT_OF`, and `SIMILAR_TO` edges plus an inheritance flag |
| `DISH_CONCEPT_CLOSURE` | Deterministic ancestor lookup and inheritance depth |
| `CONCEPT_CLAIM` | Release-scoped essential claims; the table can still read legacy allergen/dietary/facet rows |
| `KNOWLEDGE_DOCUMENT` | Validated Markdown source and front matter with content hash |
| `KNOWLEDGE_CHUNK` | Paragraph, essential-fact, and legacy-facet chunks with versioned embeddings and metadata |
| `MENU_CONCEPT_MAP` | Every demo menu mapped to one reviewed concept, or an explicit `UNMAPPED` reason |
| `MERCHANT_ORIGIN_DECLARATION` | Versioned, source-labelled merchant-scope origin text |
| `MERCHANT_INGREDIENT` | Normalized facts extracted at merchant scope; not automatically promoted to every menu |
| `OPTION_INGREDIENT_EFFECT` | Menu-option `ADD`/`REMOVE` effects and assertion status |
| `KNOWLEDGE_RUNTIME_STATE` | The single active, ready knowledge release |

Authoring files live under `knowledge/dishes/`. Their front matter is JSON-compatible
YAML validated by Pydantic. Objective, essential facts such as defining ingredients
and preparation remain structured claims. Subjective qualities such as taste,
texture, cultural context, and comparisons are authored as natural
encyclopedic prose and compiled into paragraph passages for retrieval. The compiler
rejects duplicate concepts, graph cycles, dangling parents, unclassified
ingredient/allergen IDs, and a `DEFINING`/`CORE` claim that is not
`PRESUMED_PRESENT`; it does not require subjective prose to fit a rigid facet template.

Chunk metadata records `chunk_kind`, `heading_path`, `paragraph_index`, and
`recommendation_visibility` without requiring a destructive rewrite of the original
`facet` column. New public retrieval reads `PARAGRAPH` and `ESSENTIAL_FACT` content.
Converted legacy safety paragraphs remain `INTERNAL_ONLY`; a legacy chunk without a
visibility flag is public-compatible only when its old facet is not `safety`.

The compiled demo contract currently contains 102 concepts/documents (`2` cuisine,
`30` family, `70` variant), 100 relations, 281 closure rows, 345 essential claims,
1,263 chunks, and 600 `MAPPED` menu rows. The claims break down into 245 ingredient
and 100 preparation claims; the chunks contain 918 prose paragraphs and 345 essential
fact passages. Supplemental release data contains 13 merchant origin declarations,
120 merchant ingredient rows retained for legacy shared-kitchen context, and 4 option
ingredient effects. Its
`knowledge-demo-<24 hex>` release ID is derived from the
normalized authored paths/content, catalog version, and compiler contract instead of
being a mutable hand-written version. Reusing an ID with a different manifest fails;
the loader never replaces release-scoped graph rows in place. The associated knowledge
catalog contract is `demo-knowledge-catalog-2026.08.12-v4`. The authoring default uses
`yobi-semantic-hash-v1`, dimension 1536, embedding version `2026-08-06`; deployment
may re-embed the authored release with the separately configured embedding provider.
The active release is marked `READY` only after exact counts and non-null chunk
vectors are verified. Changing the deployment embedding model or version for the same
source release is fail-closed with `KNOWLEDGE_RELEASE_ID_COLLISION`; operators must
advance the catalog/compiler contract so the change receives a new immutable release
ID instead of overwriting the existing index.

`EXPLANATION_CACHE` remains a derived cache, not a knowledge authority. Prewarm rows
record `source_version` as `catalog_version:active_knowledge_release`; the key includes
a hash of that provenance, and prewarming deletes stale rows for the same menu/language
before writing the new explanation. A Wiki release change therefore cannot silently
reuse a description generated from the previous release.

## Claim resolution and current public scope

Concept claims and specific facts do not have equal meaning:

1. `DEFINING` and `CORE` Wiki ingredients inherit through approved graph edges as
   `PRESUMED_PRESENT`.
2. Menu facts and option effects may override a matching inherited claim when their
   scope and source identify that exact menu/option.
3. Merchant origin facts remain merchant-scoped unless the declaration identifies a
   menu. They are not proof that every menu contains the ingredient.
4. A missing Wiki claim stays unknown. It never becomes `CONFIRMED_ABSENT`.
5. Halal eligibility never comes from a general Wiki claim. It comes only from an
   active `MERCHANT_CERTIFICATION` row whose release, dates, status, merchant, and
   merchant/menu scope match the candidate.
6. When vegan is requested, confirmed animal-derived defining/core or menu-level
   conflicts are excluded. A supported changeable path can remain as
   `POSSIBLE_WITH_CHECKS`; missing evidence is excluded.
7. Legacy allergen, cross-contact, religious-rule, and absence rows remain readable by
   historical consumers, but v2 does not send them to retrieval/generation, expose
   allergy controls, or make allergy-safety claims.

The legacy `MENU_KNOWLEDGE`, normalized menu relations, and `EVIDENCE` tables remain
available for existing API/UI consumers. The new resolver merges those specific facts
with the active concept release rather than deleting or silently redefining them.

## Structured hybrid search and mutation compatibility

Oracle menu and chunk vectors are `VECTOR(1536, FLOAT32)`. V2 first applies confirmed
service area, availability, base-price band, maximum `1..5` spice, valid halal scope,
confirmed vegan conflict, and similar-history exclusions. It then builds a broad
pool from exact aliases/lexical routing and Wiki-passage embedding similarity. Each
pool item keeps evidence for the user's selected values plus the full server-owned
menu payload and release provenance. SQLite stores equivalent vectors as JSON and
computes cosine similarity in application code; Oracle uses
`VECTOR_DISTANCE(..., COSINE)`.

Retrieval score bounds the evidence pool but is not the final recommendation rank.
One generation response chooses and orders final menu IDs from the pool while writing
their explanations. The server validates pool membership and evidence and preserves a
valid model order. Rating, merchant prose, and reviews contribute `0` to this v2 pool
and are not supplied to the generation context.

Migration `007_service_area_and_mutation_idempotency.sql` adds `service_area_id` to
`ADDRESS_PLACE` and `ADDRESS_REF`, and `agent_request_key` to `CART_ITEM`. The unique
mutation key prevents a retried provider continuation from inserting the same cart
line twice. It does not replace existing checkout/payment/order idempotency.

Migration `008_checkout_cart_version.sql` adds nullable `cart_version` and
`cart_fingerprint` fields to `MOCK_CHECKOUT`, plus a unique `(cart_id, cart_version)`
index. New checkouts are bound to the exact confirmed cart version and total; nullable
columns keep historical checkout rows readable by older additive-schema-compatible
releases.

Migration `009_cart_confirmation_fingerprint.sql` adds nullable
`confirmed_fingerprint` to `CART`. Confirmation binds the current cart version and
server total (including delivery fee); checkout invalidates the confirmation if that
fingerprint no longer matches, including before a first `MOCK_CHECKOUT` row exists.

## Structured recommendation ledger and release family

Migration `010_structured_hybrid_rag_recommendation.sql` adds the v2 recommendation
boundary. `SESSION_RECOMMENDATION_CRITERIA` stores the immutable criteria version,
selection JSON, a criteria hash, request identity, and state version. The commit hash
binds the submitted catalog version together with the selection, and the commit is
accepted only against the active preference-catalog version, but this table has no
separate `catalog_version` column. The subsequent request row pins the active release
family that carries the preference-catalog identity.

`STRUCTURED_RECOMMENDATION_REQUEST` is the one-dispatch ledger: it records the request
hash, criteria version, pinned release family and eligibility time, evidence-pool
snapshot, terminal result/failure, dispatch count, and timestamps. Its internal status
records distinguish no eligible results, no model match, search-result fallback, a
completed response, and an unknown result after a dispatch interruption.
`RECOMMENDATION_SNAPSHOT` additionally keeps the criteria, release-family ID,
serialized evidence pool, generation status/count, and structural-grounding JSON used
by its resulting card. Snapshot completion re-checks the exact pinned family at
current UTC and rewrites only the server-owned menu projection (including current
price, fee/ETA, halal, and vegan state) while preserving valid model prose/order. A
terminal request GET can return an even newer live projection and remove a stale menu
without mutating the stored result row. There are no separate persisted columns for
every menu price/service-area version or for generation provider/model/prompt
identity; the live provider identity must be captured as release-specific operational
evidence.

`RECOMMENDATION_RELEASE_FAMILY`, `RECOMMENDATION_RUNTIME_STATE`,
`RECOMMENDATION_PREFERENCE_OPTION`, and `SPICE_REFERENCE` bind the active Wiki,
catalog, preference vocabulary, spice examples, certification release, and embedding
metadata. `MERCHANT_CERTIFICATION` holds merchant/menu-scoped halal evidence used by
objective eligibility. These synthetic rows remain demo data, not proof of a real
restaurant or certification.

The current local family has a foreign key to `KNOWLEDGE_RELEASE` and stores the
catalog, preference, spice, certification, and embedding version identities selected
for a request. The catalog/certification identities do not yet have independent
immutable release-table foreign keys or manifests. Their operational compatibility,
atomic activation, and rollback remain Phase 8 Oracle/readiness gates; an `ACTIVE`
local pointer is not evidence that those deployment gates passed.

Migrations `001`-`010` are append-only and checksum-protected. `005`-`010` use
already-exists-tolerant Oracle blocks so the same unmodified release can resume after
Oracle's implicit DDL commits. No rollback script drops these additive objects; an app
rollback must remain compatible with them.

## Synthetic and real-data boundary

Menus, merchants, reviews, origin declarations, menu facts, address fixtures,
payments, and orders are synthetic or Mock. `SYNTHETIC_WIKI` describes general food
concepts; `SYNTHETIC_MERCHANT_ORIGIN_DECLARATION` and `SYNTHETIC_MENU_SPEC` identify
their narrower scopes. No row is evidence of a real Yogiyo integration or a real
restaurant recipe. AI-authored knowledge remains versioned and review-labelled and
is not automatically promoted to verified real-world safety data.
