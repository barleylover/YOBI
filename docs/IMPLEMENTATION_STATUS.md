# YOBI MVP implementation status

Last updated: 2026-08-08 KST

## Status

The audited Master Spec MVP is implemented and publicly deployed on the existing OCI
resources. Current release: `20260807T190544Z`. The public address is resolved from
OCI at runtime and is intentionally absent from this repository.

The 2026-08-07 frontend feedback pass is implemented, committed on
`codex/master-spec-completion`, deployed, and publicly verified. Repeated provider
list results are consolidated by grounded IDs so the UI renders one carousel per
tool type.

Confirmed live:

- Oracle runtime user `YOBI_APP`; migrations 001–004, including the append-only
  three-level spice migration.
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

## 2026-08-07 multilingual ordering iteration

- Compact no-scroll welcome screen restored the context-first product message and
  removed the speech-bubble/neighbourhood treatment.
- Locale selection and form-only food/delivery context are separate steps; locale
  change remains inside the profile form.
- Profile, address feedback, chat cards, evidence labels, option builder, cart,
  delivery, payment and confirmation use the selected language. Korean catalog names
  and country display names are localized while restaurant/hotel proper names remain
  catalog data.
- Expanded allergy selection uses one shared severity, and menu/category/seed/database
  spice values use the same 1–3 contract.
- Same-restaurant add-on browsing remains swipeable and the cart badge sums item
  quantities.
- Public Korean iPhone E2E passed the complete profile-to-confirmation flow on release
  `20260807T093233Z`.

## 2026-08-08 chat-room menu iteration

- A localized, collapsible menu above the chat composer exposes **Weekly ranking**,
  **K-POP Demon Hunters**, and **Edit my information** in all 16 supported languages.
- Weekly ranking is fixed to BBQ, BHC, No More Pizza, Hong Kong Banjeom, and Yeopgi
  Tteokbokki. The second collection is fixed to gimbap, gukbap, hotteok,
  seolleongtang, and eomuk. Both return deterministic assistant cards without an LLM
  call or a live ranking/data integration.
- Ten key-preserving catalog slots provide orderable preset restaurants and menus.
  Existing schema migrations remain unchanged; seed upsert adds five categories and
  updates only deterministic catalog rows.
- Existing-profile editing uses `PATCH /profiles/{profile_id}`, reuses the current
  confirmed address by default, preserves the session/chat/cards/cart/draft, and
  refreshes the server cart after return so new dietary conflicts block checkout.
- Oracle seed verification now synchronizes only seed-owned menu ingredient,
  allergen and dietary-attribute relations before their upserts, preventing stale
  historical links without deleting profiles, carts, orders or migration records.
- Public verification passed the focused chat-menu suite (2 tests), the Primary Demo
  three consecutive times, deployed Oracle deterministic fallback, exact seed/vector
  integrity, and release-window error-log review. The final NSG has no SSH ingress.

All merchants, reviews, hotels, payments and orders are synthetic. The deployment is
public HTTP for presentation and has no custom domain/TLS. Stored vectors are
deterministic `yobi-semantic-hash-v1`; OCI Cohere embedding is not claimed.
