# API

All product endpoints are under `/api/v1`. OpenAPI is available at `/docs` while the
FastAPI service is reachable internally.

| Method | Path | Contract |
|---|---|---|
| GET | `/healthz` | Process liveness, no dependency check |
| GET | `/readyz` | Oracle/catalog/vector readiness |
| POST/GET/DELETE | `/api/v1/profiles` | Consent-gated browser-session profile |
| POST/GET | `/api/v1/sessions` | Explicit state-machine session |
| POST | `/api/v1/sessions/{id}/messages` | Grounded agent or deterministic fallback turn |
| POST | `/api/v1/sessions/{id}/messages/stream` | SSE start, status, text, cards, end |
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

Errors use an HTTP status plus `{"detail":{"code":"STABLE_CODE"}}`. Missing
required options, incomplete carts, reused idempotency keys, and invalid state
transitions return conflict responses rather than being silently corrected.

The Grok loop exposes only read-oriented functions. Mutating cart, address,
checkout, mock payment, and order endpoints are intentionally kept behind explicit
user actions and server-side state validation; model text alone is never treated as
confirmation.
