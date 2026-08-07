# YOBI MVP implementation status

Last updated: 2026-08-07 KST

## Status

The audited Master Spec MVP is implemented and publicly deployed on the existing OCI
resources. Current release: `20260807T063338Z`. The public address is resolved from
OCI at runtime and is intentionally absent from this repository.

The 2026-08-07 frontend feedback pass is implemented, committed on
`codex/master-spec-completion`, deployed, and publicly verified. Repeated provider
list results are consolidated by grounded IDs so the UI renders one carousel per
tool type.

Confirmed live:

- Oracle runtime user `YOBI_APP`; migrations 001, 002 and append-only 003.
- Exact catalog/normalized seed counts and non-NULL menu/review/knowledge vectors.
- Real Oracle hard filtering, hybrid `VECTOR_DISTANCE`, cart row locks and idempotent
  mock payment/order creation.
- Grok two-step smoke and final application Agent Loop. The prior recorded aggregate
  was 9 normal, 0 fallback, 25 provider responses and 16 DB-backed tool calls.
- Tesseract English/Korean OCR packages active; raw address images are not persisted.
- `yobi-api` and Nginx active; public and local health/readiness pass.
- Public full-order API smoke and Primary iPhone E2E three consecutive passes.
- `/etc/yobi/yobi.env` remains `root:root` mode `0600`; no values were printed.

## Product boundary

The product covers editable onboarding, conversational discovery, evidence-linked
recommendation/explanation, merchant comparison, menu options, translated notes,
three onboarding address methods, cart edit/remove/reprice, delivery confirmation, mock payment
failure/retry and one synthetic order.

## 2026-08-07 frontend feedback pass

- 16 language choices and language-prioritized country ordering.
- Gender removed; explicit vegan and religion context added without nationality,
  language or religion-based dietary inference.
- Three radio-based spice levels and address confirmation moved before chat.
- Context rail and `Discover / Choose / Deliver / Pay` strip removed.
- Swipeable one-card menu carousel with accessible previous/next controls.
- `Choose this menu` scrolls directly to the Order Builder.
- Dietary-risk options start disabled with a reason and explicit unlock control;
  authoritative server dietary checks remain enforced.
- Review readiness now includes dietary conflicts and the restaurant minimum, with
  shortfall amounts and actionable server-error copy.
- Local browser QA confirmed no horizontal overflow at 390px and 1366px, and no
  console errors.
- The public iPhone Primary Demo passed three consecutive end-to-end orders on the
  latest release.

All merchants, reviews, hotels, payments and orders are synthetic. The deployment is
public HTTP for presentation and has no custom domain/TLS. Stored vectors are
deterministic `yobi-semantic-hash-v1`; OCI Cohere embedding is not claimed.
