# YOBI MVP implementation status

Last updated: 2026-08-06 KST

## Status

The audited Master Spec MVP is implemented and publicly deployed on the existing OCI
resources. Current release: `20260806T085827Z`. The public address is resolved from
OCI at runtime and is intentionally absent from this repository.

Confirmed live:

- Oracle runtime user `YOBI_APP`; migrations 001, 002 and append-only 003.
- Exact catalog/normalized seed counts and non-NULL menu/review/knowledge vectors.
- Real Oracle hard filtering, hybrid `VECTOR_DISTANCE`, cart row locks and idempotent
  mock payment/order creation.
- Grok two-step smoke and final application Agent Loop. Latest aggregate: 9 normal,
  0 fallback, 25 provider responses and 16 DB-backed tool calls.
- Tesseract English/Korean OCR packages active; raw address images are not persisted.
- `yobi-api` and Nginx active; public and local health/readiness pass.
- Public full-order API smoke and Primary iPhone E2E three consecutive passes.
- `/etc/yobi/yobi.env` remains `root:root` mode `0600`; no values were printed.

## Product boundary

The product covers editable onboarding, conversational discovery, evidence-linked
recommendation/explanation, merchant comparison, menu options, translated notes,
three address methods, cart edit/remove/reprice, delivery confirmation, mock payment
failure/retry and one synthetic order.

All merchants, reviews, hotels, payments and orders are synthetic. The deployment is
public HTTP for presentation and has no custom domain/TLS. Stored vectors are
deterministic `yobi-semantic-hash-v1`; OCI Cohere embedding is not claimed.
