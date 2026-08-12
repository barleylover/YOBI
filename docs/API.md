# API

All product endpoints are under `/api/v1`. OpenAPI is available at `/docs` while the
FastAPI service is reachable internally.

| Method | Path | Contract |
|---|---|---|
| GET | `/healthz` | Process liveness, no dependency check |
| GET | `/readyz` | Catalog, active knowledge/vector, and required production GenAI configuration readiness |
| POST/GET/PATCH/DELETE | `/api/v1/profiles[/{id}]` | Consent-gated browser-session profile; retained legacy fields are not v2 recommendation criteria |
| POST/GET | `/api/v1/sessions[/{id}]` | Explicit state-machine session |
| POST | `/api/v1/sessions/{id}/reset` | Reset one retained session without deleting its profile |
| GET | `/api/v1/recommendation/preferences/catalog` | Localized, versioned selectable preference catalog (ETag-aware) |
| PUT | `/api/v1/sessions/{id}/recommendation-criteria` | Idempotently commit structured preferences and dietary filters |
| POST | `/api/v1/sessions/{id}/recommendations` | Create or replay one bounded structured recommendation request |
| GET | `/api/v1/sessions/{id}/recommendation-requests/{request_id}` | Poll the persisted structured recommendation request/result |
| POST | `/api/v1/sessions/{id}/messages` | Deprecated v1 free-chat compatibility; not called by the structured UI |
| POST | `/api/v1/sessions/{id}/messages/stream` | Deprecated v1 SSE compatibility; not called by the structured UI |
| GET | `/api/v1/sessions/{id}/messages` | Historical visible message history; internal v2 audit rows are excluded |
| GET | `/api/v1/sessions/{id}/conversation` | Authoritative state, committed criteria, active/latest v2 request, historical messages, and latest snapshot |
| POST | `/api/v1/sessions/{id}/events` | Idempotent select/reject/compare/option-update compatibility API; current v2 browser posts menu selection only |
| GET | `/api/v1/menus/{id}/options` | DB-authoritative required options and deltas |
| GET | `/api/v1/menus/{id}/evidence` | Evidence status, source, excerpt, action |
| POST | `/api/v1/sessions/{id}/address/attachments` | Validated image; raw bytes not retained |
| POST | `/api/v1/sessions/{id}/address/resolve` | Resolve hotel/address text to signed confirmation candidates |
| POST | `/api/v1/sessions/{id}/address/confirm` | Signed candidate confirmation, or exact manual match to a supported service-area address |
| GET | `/api/v1/sessions/{id}/cart` | Server-side totals and missing slots |
| POST | `/api/v1/sessions/{id}/cart/items` | Add a server-priced menu/options line |
| PATCH/DELETE | `/api/v1/sessions/{id}/cart/items/{item_id}` | Update quantity/options or remove a cart line |
| PATCH | `/api/v1/sessions/{id}/delivery` | Handoff, cutlery, bell, translated note |
| POST | `/api/v1/sessions/{id}/cart/confirm` | Freezes a complete reviewable cart |
| POST | `/api/v1/sessions/{id}/checkout` | Idempotent mock checkout only |
| POST | `/api/v1/checkout/{id}/mock-success` | Creates at most one mock order |
| POST | `/api/v1/checkout/{id}/mock-failure` | Recoverable failure; cart preserved |
| POST | `/api/v1/checkout/{id}/cancel` | Cancel a pending mock checkout |
| GET | `/api/v1/orders/{id}` | Synthetic order and ETA |
| GET/POST | `/api/v1/demo/*` | Token-protected production controls |

## Legacy free-chat compatibility

The `/messages` paragraphs below describe the retained v1 endpoint only. The current
browser recommendation flow neither posts free text nor opens the SSE endpoint; its
request/recovery contract is the structured v2 section that follows.

Message responses include the server `dialogue_act`, readiness decision,
`RecommendationResult` when one exists, cards, fallback marker/reason, and the exact
assistant message ID persisted with any recommendation snapshot. A greeting or
need-collection response legitimately contains no cards and no snapshot.

Both message POST bodies accept an optional `request_id` (8-100 characters; it starts
with a letter or digit, followed by letters, digits, `.`, `_`, `:`, or `-`). Omitting
it preserves the previous one-shot API contract, so older clients remain compatible;
the current browser client supplies one.
Within one session, replaying the same `request_id` with the same `content` and
`intent` returns the originally persisted `AssistantTurn` instead of adding another
message pair, advancing state, creating another snapshot, or repeating a cart/delivery/
checkout mutation. Reusing that ID with a different payload is rejected as
`CHAT_REQUEST_ID_REUSED` (HTTP 409 on the non-stream endpoint; an SSE `error` event
with the same code on the stream endpoint).

The browser keeps an interrupted request's ID with its exact content/intent and reuses
it on retry. Server-generated agent mutation keys are derived from that stable request
identity rather than accepted from model arguments. Consequently, if a cart mutation
commits but the provider continuation or network response is lost, an exact retry can
recover the authoritative result without inserting the same cart line twice. This is
a lost-response recovery contract, not permission to reuse an ID for a new user action.

## Structured recommendation v2

`GET /api/v1/recommendation/preferences/catalog` publishes stable codes and localized
labels for selectable cuisine, flavor, main ingredient, food form, temperature, price,
texture, and cooking-method facets. A code is valid only when it is exposed by that
catalog version; clients must not invent labels or infer dietary rules from
nationality, language, religion, or a prior conversation.

`PUT /recommendation-criteria` stores a versioned criteria snapshot. Values selected
within a facet express `OR`; every non-empty subjective facet expresses the user's
cross-facet `AND` intent. This is not a SQL claim that prose has become a boolean
attribute: the evidence pool supplies per-facet passages and the model must support
each active facet when selecting a normal result. The current structural validator
checks those references, while semantic relevance remains a provider/evaluation
boundary. `max_spice_level` is a five-step ceiling with a Korean or US reference scale.
The public v2 dietary payload
contains only `halal_certified_only` and `vegan`: it accepts no allergy filters.
Halal eligibility requires an active, in-scope certification record. Vegan is a
conservative menu/Wiki-evidence rule and may return a warning rather than a safety
guarantee.

`POST /recommendations` validates availability, service area, price, spice, halal
scope, and vegan conflicts on the server. It then combines lexical and embedding
retrieval into an auditable evidence pool. One generation dispatch may choose final
menu order and produce explanations grounded by that pool; it cannot issue tools,
continue a conversation, or retrieve another menu. The server does not rerank the
model's valid final order. It validates menu/evidence IDs and does not treat generated
prose as server-owned certification, but it is not a general semantic-entailment
checker. If no eligible result exists, the request completes without a model call. If
the single dispatch fails or violates the structural pool contract, a clearly labelled
search-result fallback may be returned without a second model call.
Fallback results are proximity-ranked saved searches and are not presented as proof
that every subjective facet was semantically satisfied.

Before a selectable snapshot is committed, current server rows are revalidated against
the request's pinned release family; current price, delivery fee/ETA, halal, and vegan
fields replace request-time projections without changing valid model prose/order. A
terminal request GET/reload recomputes that live projection and can omit stale menus
without changing the persisted model output or invoking generation. `SELECT_MENU`, cart
review, and checkout revalidate the applicable current-meal v2 criteria; retained
profile allergy/religion fields do not silently re-enter the v2 ordering path.
If only the price moved outside the originally selected band, the result remains
selectable with the current price. Cart review shows a non-blocking updated-total
warning, and checkout uses the repriced total and cart fingerprint.

Structured requests are ledgered by session and `request_id`. A replay with the same
semantic request returns the stored state/result and never sends another generation
request. Its hash covers session/profile identity, criteria hash/version, mode,
expected state version, and locale; the request row separately pins release family,
eligibility time, and the dispatched evidence pool. A changed profile/address/history
state must use the new state version and request ID. A process loss after dispatch is
represented as `UNKNOWN_AFTER_DISPATCH`;
the application will not silently redispatch it because the provider may already have
processed the request. A stale `CREATED` reservation that never reached dispatch is
terminalized as `FAILED` with `RETRIEVAL_OWNER_LOST`, so it does not remain pending
forever; an explicit retry is a new request ID.

Conversation events require an `idempotency_key`. Snapshot-backed actions also
require the snapshot/menu identifiers and may include `expected_state_version` for
optimistic concurrency. Replaying the same key returns the original result; selecting
a menu that was not in that snapshot or writing against a stale state is rejected.

Errors use an HTTP status plus `{"detail":{"code":"STABLE_CODE"}}`. Missing
required options, incomplete carts, incompatible state versions, reused idempotency
keys with different meaning, and invalid state transitions return conflict responses
rather than being silently corrected.

Checkout creation is additionally bound to the confirmed cart snapshot. Migration
`008_checkout_cart_version.sql` adds `cart_version`, `cart_fingerprint`, and a unique
`(cart_id, cart_version)` index to `MOCK_CHECKOUT`. The server recomputes the
fingerprint from the cart ID, confirmed version, and current total; the same checkout
key may be replayed only for that exact snapshot. A changed/repriced cart must be
reviewed and confirmed again, receives a newer version, and therefore uses a new
checkout key. The browser constructs that key only after confirmation as
`checkout-{cart_id}-{confirmed.version}`. Existing rows remain compatible because the
new columns are nullable; Migration 008 is additive and does not rewrite prior orders.
Mock payment success revalidates the locked cart against that version and fingerprint
before creating an order. A changed, repriced, or no-longer-confirmed cart is rejected
as `CHECKOUT_STALE` and the pending checkout is not marked successful. Replaying an
already successful checkout still returns its original order.
Migration `009_cart_confirmation_fingerprint.sql` additionally stores the total-bound
fingerprint on `CART` when the user confirms it. This catches a delivery-fee change
even before the first checkout exists; legacy confirmed carts without the fingerprint
must be reviewed and confirmed once before checkout.

In the deprecated v1 path, the agent exposes a dialogue-act-routed subset of a
14-function allowlist. It may
apply cart, delivery-preference, or mock-checkout mutations only for an explicit user
request; arguments, options, prices, readiness, and idempotency are revalidated by
the server. Address confirmation and mock-payment success/failure remain explicit
API/UI actions. The agent cannot mark a payment successful or create a second order,
and model text alone is never treated as confirmation.

`/readyz` returns HTTP 503 when canonical catalog data or the active knowledge
release is not ready. The database payload reports the active knowledge release and
embedding metadata without exposing credentials or endpoint identifiers. In
production or dedicated serving mode it also validates the configured GenAI provider,
required Responses/Function Calling capabilities, model/endpoint configuration, and
compatible input/output/tool limits. Invalid configuration returns sanitized
`GENAI_NOT_READY` reason codes, never a key or endpoint identifier.

The current source does not yet make `/readyz` a complete structured-v2 release-family
manifest check. In particular, an HTTP 200 is not proof that independent catalog and
certification manifests were atomically validated and activated. Extending readiness
and proving the release-family activation/rollback against Oracle remain Phase 8
deployment gates.
