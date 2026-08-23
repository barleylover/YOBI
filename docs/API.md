# API

All product endpoints are under `/api/v1`. OpenAPI is available at `/docs` while the
FastAPI service is reachable internally.

> 2026-08-17 contract update: migration `012`, preference catalog
> `preference-catalog-2026.08.17-v3`, the expanded external data family, and the
> server-owned ranking/preview contract are active in Oracle and served by final
> application `20260816T201131Z-29fbc2f9fd32`. Public API/browser closure is recorded
> in `TEST_REPORT.md`.

| Method | Path | Contract |
|---|---|---|
| GET | `/healthz` | Process liveness, no dependency check |
| GET | `/readyz` | Catalog, active knowledge/vector, and required production GenAI configuration readiness |
| POST/GET/PATCH/DELETE | `/api/v1/profiles[/{id}]` | Consent-gated browser-session profile; retained legacy fields are not v2 recommendation criteria |
| POST/GET | `/api/v1/sessions[/{id}]` | Explicit state-machine session |
| POST | `/api/v1/sessions/{id}/reset` | Reset one retained session without deleting its profile |
| GET | `/api/v1/recommendation/preferences/catalog` | Localized, versioned selectable preference catalog (ETag-aware) |
| POST | `/api/v1/sessions/{id}/structured-recommendations/preview` | Read-only SQL/support preview; no criteria/session mutation, vector retrieval, Wiki generation, or provider call |
| PUT | `/api/v1/sessions/{id}/recommendation-criteria` | Idempotently commit structured preferences and dietary filters |
| POST | `/api/v1/sessions/{id}/recommendations` | Create or replay one bounded structured recommendation request |
| GET | `/api/v1/sessions/{id}/recommendation-requests/{request_id}` | Poll the persisted structured recommendation request/result |
| POST | `/api/v1/sessions/{id}/recommendation-comparisons` | Idempotent, grounded comparison of the 2-3 menus in one completed snapshot |
| GET | `/api/v1/sessions/{id}/food-rankings` | Session/service-area-filtered demo ranking (`review_count`, `order_count`, or `korean_popularity`; limit 1-20) |
| GET | `/api/v1/sessions/{id}/featured/kpop-demon-hunters` | Five-concept, general-Wiki-backed feature mapped to currently available menus |
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

Active catalog `preference-catalog-2026.08.17-v3` exposes cuisine codes `KOREAN`,
`CHINESE`, `SOUTHEAST_ASIAN`, `MEXICAN`, `JAPANESE`, `ITALIAN`, and `AMERICAN`.
The order is presentation metadata; selection semantics remain same-category OR and
cross-category AND.

The catalog also publishes `capabilities` for `halal_certified_only`, `vegan`, and
`max_spice_level`. Each capability carries `enabled` and a human-readable
`disabled_reason`. A false value means the active release lacks the minimum reviewed
menu/merchant coverage; the client disables the control, displays the reason, clears
any stale draft value, and submits the neutral value (`false`, `false`, or spice
ceiling `5`). Disabled does not mean the underlying menu is certified, vegan, mild, or
unsafe—it means YOBI cannot support that filter from the active evidence.

`POST /sessions/{id}/structured-recommendations/preview` accepts the same
`RecommendationCriteriaV2` body used by the selector. It performs only server-owned
objective SQL and reviewed concept-support joins. It returns
`eligible_menu_count`, `eligible_merchant_count`, `zero_reason_codes`, `release_id`,
`support_manifest_sha256`, `ranking_policy_version`, and `timing_ms`. It is read-only:
it does not commit criteria, advance session state, retrieve vectors/Wiki passages,
dispatch a provider request, or expose raw SQL/menu/session identifiers.

`PUT /recommendation-criteria` stores a versioned criteria snapshot. Values selected
within a facet express `OR`; every non-empty facet expresses the user's cross-facet
`AND` intent. Migration `012` binds reviewed `CONCEPT_PREFERENCE_SUPPORT` rows to the
active release. The server uses those rows for eligibility and an explicit,
versioned deterministic score; prose is not silently converted into unreviewed
merchant facts. `max_spice_level` is a five-step ceiling with a Korean or US reference scale.
The public v2 dietary payload
contains only `halal_certified_only` and `vegan`: it accepts no allergy filters.
Halal eligibility requires an active, in-scope certification record. Vegan is a
conservative menu/Wiki-evidence rule and may return a warning rather than a safety
guarantee.

`POST /recommendations` validates availability, service area, price, spice, halal
scope, vegan conflicts, active concept mapping, and selected-option support on the
server. SQL/support retrieval produces eligible candidates; deterministic scoring,
stable tie-breaks, and diversity freeze the final top three before generation. One
generation dispatch may produce explanations for exactly those frozen menus. It
cannot choose, replace, or reorder a menu, issue tools, continue a conversation, or
retrieve another candidate. The server validates exact frozen order and evidence IDs
and does not treat generated prose as certification; semantic entailment remains an
evaluation boundary. If no eligible result exists, the request completes without a
model call. If the single dispatch fails, a clearly labelled deterministic rendering
of the same server-ranked menus may be returned without a second model call.
Fallback results preserve server eligibility and rank; they are not presented as a
provider-authored explanation.

`POST /recommendation-comparisons` requires the completed recommendation
`snapshot_id`, its recommendation `request_id`, and an `idempotency_key`. It compares
exactly the frozen 2-3 menus; it cannot change their IDs/order or create a replacement
recommendation. The first request may make one separate, bounded comparison-writing
provider call. Provider failure returns a deterministic comparison of the same menus,
and an exact idempotency replay returns the cached comparison without another call.
This optional comparison call is separate from the recommendation batch's single
explanation dispatch and does not write a legacy `COMPARE_MENUS` event.

`GET /food-rankings` applies the session's confirmed demo delivery area and current
menu availability, returns a browse snapshot usable by `SELECT_MENU`, and supports
three sort keys. For the external catalog, review ranking uses the source menu review
count; order and Korean-popularity are deterministic demo proxies calculated from
source menu/merchant review counts. Only synthetic fixture menus with neither source
count use stable menu-ID-derived demo values. `demo_basis` makes this boundary
explicit. The prepared rows remain in metric order while the returned membership favors
different merchants and mapped dish concepts so one restaurant cannot fill the demo.
The API accepts a bounded limit up to 20; the English discovery screen requests and
displays 10. The response is not a live or platform-wide Yogiyo ranking.

`GET /featured/kpop-demon-hunters` returns at most one available mapped menu for each
of Gimbap, Tteokbokki, Hotteok, Naengmyeon, and Eomuk, plus a browse snapshot and
general-Wiki evidence IDs. The endpoint uses reviewed synthetic general-food prose and
high-confidence concept mappings; it does not verify a merchant recipe or use general
Wiki facts as merchant-specific dietary evidence. The English UI always keeps these
five story slots visible and marks a missing local match unavailable rather than
substituting an unrelated menu.

Before a selectable snapshot is committed, current server rows are revalidated against
the request's pinned release family; current price, delivery fee/ETA, halal, and vegan
fields replace request-time projections without changing valid generated prose or
server-owned order. A
terminal request GET/reload recomputes that live projection and can omit stale menus
without changing the persisted explanation output or invoking generation. `SELECT_MENU`, cart
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

The current source reports `source_integrity_ready` and `recommendation_ready`
separately and `/readyz` requires both. The external release verifier additionally
checks the active support/ranking manifest. This is stronger than the old canonical
catalog/knowledge aliases, but HTTP 200 alone still does not prove that the candidate
Oracle plan, normal generation/order smoke, isolated provider-fallback smoke,
performance sample, rollback, and final redeployment were executed. Those remain
standard deployment evidence gates.

The visible 2026-08-16 browser flow is welcome+locale → supported demo address →
selector → chat-style one-card result carousel → options/cart/delivery/review →
explicit Yogiyo handoff mock. The handoff button changes only local presentation
state: it neither opens an external Yogiyo URL nor creates an order. The mock-checkout
and synthetic-order endpoints remain supported for backend integrity/regression and
are exercised by the release smoke; they are not a Yogiyo integration and are not
exposed as an internal payment-success/order-complete product flow.
