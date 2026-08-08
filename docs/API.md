# API

All product endpoints are under `/api/v1`. OpenAPI is available at `/docs` while the
FastAPI service is reachable internally.

| Method | Path | Contract |
|---|---|---|
| GET | `/healthz` | Process liveness, no dependency check |
| GET | `/readyz` | Catalog, active knowledge/vector, and required production GenAI configuration readiness |
| POST/GET/DELETE | `/api/v1/profiles` | Consent-gated browser-session profile |
| POST/GET | `/api/v1/sessions` | Explicit state-machine session |
| POST | `/api/v1/sessions/{id}/messages` | Grounded agent or deterministic fallback turn; optional replay-safe `request_id` |
| POST | `/api/v1/sessions/{id}/messages/stream` | SSE start, status, text, cards, end; optional replay-safe `request_id` |
| GET | `/api/v1/sessions/{id}/messages` | Persisted message history |
| GET | `/api/v1/sessions/{id}/conversation` | Authoritative state version, meal needs, messages, and latest recommendation snapshot |
| POST | `/api/v1/sessions/{id}/events` | Idempotent menu select/reject/compare and option-update event |
| GET | `/api/v1/menus/{id}/options` | DB-authoritative required options and deltas |
| GET | `/api/v1/menus/{id}/evidence` | Evidence status, source, excerpt, action |
| POST | `/api/v1/sessions/{id}/address/attachments` | Validated image; raw bytes not retained |
| POST | `/api/v1/sessions/{id}/address/confirm` | Required candidate confirmation |
| GET/POST | `/api/v1/sessions/{id}/cart` | Server-side totals and missing slots |
| PATCH | `/api/v1/sessions/{id}/delivery` | Handoff, cutlery, bell, translated note |
| POST | `/api/v1/sessions/{id}/cart/confirm` | Freezes a complete reviewable cart |
| POST | `/api/v1/sessions/{id}/checkout` | Idempotent mock checkout only |
| POST | `/api/v1/checkout/{id}/mock-success` | Creates at most one mock order |
| POST | `/api/v1/checkout/{id}/mock-failure` | Recoverable failure; cart preserved |
| GET | `/api/v1/orders/{id}` | Synthetic order and ETA |
| GET/POST | `/api/v1/demo/*` | Token-protected production controls |

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

The agent exposes a dialogue-act-routed subset of a 14-function allowlist. It may
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
