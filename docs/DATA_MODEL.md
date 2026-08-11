# Data model

> Counts below describe the 2026-08-11 local v3 seed contract. The existing OCI
> deployment was last verified with the historical v2 catalog and has not yet been
> migrated/seeded with this v3 data.

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

The deterministic Wiki-centric seed currently expects 3 service areas, 100 categories,
60 merchants, 600 menus, 600 legacy menu-knowledge rows, 1,200 evidence rows, 2,400
review snippets, 1,202 option groups, 2,405 option items, and 20 address fixtures. The
normalized taxonomy contains 54 ingredients, 10 allergens, and 20 dietary attributes.
Nine allergen codes match onboarding choices; the tenth legacy-compatible row is the
shared-kitchen `cross_contamination_unknown` marker, not an additional user allergy.
All demo-owned rows are synthetic. Exact counts are enforced in
`scripts/seed_demo.py`; changing the catalog requires changing its fixture and
integrity expectations together. The base catalog version is
`demo-2026.08.11-knowledge-v3`.

The seed deliberately does not pretend that every merchant publishes a complete
recipe or allergen specification. Menu-level ingredient facts cover 206 of 600 menus
(565 rows), allergen facts cover 221 menus (595 rows), and dietary attributes contain
1,217 menu links. The remaining gaps stay unknown and are resolved with reusable Wiki
family/variant knowledge, never fabricated merchant prose. The 2,400 reviews remain
available for display compatibility but carry ranking and safety weight `0`.
Each merchant has a ten-menu roster biased toward one dominant food family plus
related variants, rather than a random copy of the full catalog. Availability is 510
`AVAILABLE`, 60 `SOLD_OUT`, and 30 `PAUSED`, so the demo exercises availability
filtering without needing additional locations.

## Conversation state and recommendation snapshots

Migration `005_conversation_state.sql` extends `CHAT_SESSION` with:

- `meal_need_state_json`: cumulative, server-validated `MealNeedState`;
- `dialogue_act`: the current server-owned `DialogueAct`;
- `state_version`: optimistic concurrency version for state/event writes.

`MealNeedState` includes budget, spice, party size, service area, positive and
negative sensory preferences, excluded categories/ingredients, profile and
conversation dietary rules, recommendation hold, shown/rejected/selected menus, and
option selections. A turn produces a validated `PreferenceDelta`; it never replaces
unrelated earlier constraints merely because the latest message omits them.

`RECOMMENDATION_SNAPSHOT` stores the exact assistant message, state version,
`RecommendationResult`, candidate order, and rendered cards used for a recommendation.
`CONVERSATION_EVENT` stores select, reject, compare, and option-update events with a
per-session idempotency key and resulting state version. This is why references such
as “the second menu” are resolved from server state rather than from text or hidden
browser-only state.

## Versioned menu Wiki and knowledge graph

Migration `006_knowledge_graph.sql` introduces a release-scoped relational graph:

| Table | Purpose |
|---|---|
| `KNOWLEDGE_RELEASE` | Manifest, catalog version, embedding model/dimension/version, expected/actual counts, and release state |
| `DISH_CONCEPT` | Reusable cuisine, family, and variant nodes |
| `DISH_RELATION` | `IS_A`, `VARIANT_OF`, and `SIMILAR_TO` edges plus an inheritance flag |
| `DISH_CONCEPT_CLOSURE` | Deterministic ancestor lookup and inheritance depth |
| `CONCEPT_CLAIM` | Ingredient, allergen, dietary, preparation, and prose-facet claims with status, role, source, and review state |
| `KNOWLEDGE_DOCUMENT` | Validated Markdown source and front matter with content hash |
| `KNOWLEDGE_CHUNK` | Facet chunks and versioned 1,536-dimensional embeddings |
| `MENU_CONCEPT_MAP` | Every demo menu mapped to one reviewed concept, or an explicit `UNMAPPED` reason |
| `MERCHANT_ORIGIN_DECLARATION` | Versioned, source-labelled merchant-scope origin text |
| `MERCHANT_INGREDIENT` | Normalized facts extracted at merchant scope; not automatically promoted to every menu |
| `OPTION_INGREDIENT_EFFECT` | Menu-option `ADD`/`REMOVE` effects and assertion status |
| `KNOWLEDGE_RUNTIME_STATE` | The single active, ready knowledge release |

Authoring files live under `knowledge/dishes/`. Their front matter is JSON-compatible
YAML validated by Pydantic, and every document must contain the nine facets
`overview`, `taste`, `texture`, `temperature`, `satiety`, `culture`, `analogy`,
`ingredients`, and `safety`. The compiler rejects duplicate concepts, graph cycles,
dangling parents, unknown facets, unclassified ingredient/allergen IDs, and a
`DEFINING`/`CORE` claim that is not `PRESUMED_PRESENT`.

The compiled demo contract currently contains 102 concepts/documents (`2` cuisine,
`30` family, `70` variant), 100 relations, 281 closure rows, 1,997 claims, 918 facet
chunks, and 600 `MAPPED` menu rows. The claims break down into 361 ingredient, 371
allergen, 247 dietary, 100 preparation, and 918 facet claims. Supplemental release
data contains 13 merchant origin declarations, 119 merchant ingredient rows used only
as shared-kitchen cross-contact signals, and 4 option ingredient effects. Its
`knowledge-demo-<24 hex>` release ID is derived from the
normalized authored paths/content, catalog version, and compiler contract instead of
being a mutable hand-written version. Reusing an ID with a different manifest fails;
the loader never replaces release-scoped graph rows in place. The associated knowledge
catalog contract is `demo-knowledge-catalog-2026.08.11-v3`. The authoring default uses
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

## Claim resolution and safety semantics

Concept claims and specific facts do not have equal meaning:

1. `DEFINING` and `CORE` Wiki ingredients inherit through approved graph edges as
   `PRESUMED_PRESENT`.
2. Menu facts and option effects may override a matching inherited claim when their
   scope and source identify that exact menu/option.
3. Merchant origin facts remain merchant-scoped unless the declaration identifies a
   menu. They are not proof that every menu contains the ingredient; their normalized
   claims are instead conservative shared-kitchen/cross-contact signals for strict,
   explicit religious, and severe-allergy filtering.
4. A missing Wiki claim stays unknown. It never becomes `CONFIRMED_ABSENT`.
5. The explicit demo alternatives use menu-scoped absence backed by `VERIFIED`
   synthetic menu evidence, while keeping cross-contact `UNKNOWN`; this supports a
   qualified alternative, not an allergy-safe certification.
   The alternatives are distributed across the three demo areas and are not tied to
   a supposedly allergy-safe merchant or real-world certification.
6. `UNKNOWN`, possible cross-contact, and synthetic Wiki knowledge cannot be phrased
   as allergy-safe, halal-certified, or medically verified.

The legacy `MENU_KNOWLEDGE`, normalized menu relations, and `EVIDENCE` tables remain
available for existing API/UI consumers. The new resolver merges those specific facts
with the active concept release rather than deleting or silently redefining them.

## Search, service area, and mutation compatibility

Oracle menu and chunk vectors are `VECTOR(1536, FLOAT32)`. Search applies service
area, availability, spice, and dietary/ingredient hard safety filters before bulk
Wiki scoring. A cap of `600` preserves every surviving demo candidate through exact
alias, Korean facet, and vector matching. Party-sized budget and explicit negative
preferences are enforced before final output. Final ranking is exactly `60%` Wiki,
`25%` structured preference, and `15%` operational/menu metadata; the operational
signal uses menu semantic relevance, price, delivery fee, and ETA. Rating, merchant
prose, and reviews contribute `0`. Severe shellfish profiles retain the stricter
verified-sauce-absence rule and an independent cross-contact warning. SQLite stores
equivalent vectors as JSON and computes cosine similarity in application code.

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

Migrations `001`-`009` are append-only and checksum-protected. `005`-`009` use
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
