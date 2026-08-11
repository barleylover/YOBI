# YOBI MVP implementation status

Last updated: 2026-08-11 KST

> The 2026-08-11 Wiki-centric catalog and recommendation changes described first are
> present only in the local working tree. They have not been committed, pushed,
> deployed to OCI, or verified through the public demo in this checkpoint. Do not
> combine them with the older live evidence below.

> Historical release `20260809T084353Z-704f74712d9d` remains live on the existing
> OCI VM/ADB. Migrations `001`–`008`, catalog
> `demo-2026.08.09-knowledge-v2`, immutable knowledge release
> `knowledge-demo-1c7dd5378736fc75567ba871`, public readiness/security, full public
> Playwright, and three consecutive Primary runs passed. Final local gates passed Ruff,
> MyPy (62 files), backend Pytest (223), legacy evaluation (100 queries), chatbot
> acceptance (345 assertions), frontend lint/Vitest (11 tests), and the 1,796-module
> build. Draft PR #1 remains OPEN/Draft; it is not merged.

## 2026-08-11 local Wiki-centric demo refactor

The current local catalog makes reusable menu knowledge—not merchant descriptions or
reviews—the primary source for recommendation and explanation. It contains 60
synthetic merchants and 600 synthetic menus across 100 categories, all mapped to
family/variant concepts. The Wiki contains 102 concepts/documents (`2` cuisine, `30`
family, `70` variant), 100 relations, 281 closure rows, 1,997 claims, and 918 chunks.
Claim totals are 361 ingredient, 371 allergen, 247 dietary, 100 preparation, and 918
facet claims.

The catalog intentionally resembles an incomplete marketplace feed. Menu-specific
ingredient declarations cover 206 menus (565 rows), allergen declarations cover 221
menus (595 rows), and dietary links contain 1,217 rows across 20 attributes. Thirteen
merchant origin declarations and 119 merchant ingredient rows are limited to
shared-kitchen cross-contact context. Four option effects remain menu-option specific.
The 2,400 review rows are display-compatible synthetic data with ranking and safety
weight `0`; merchant free-text descriptions also contribute `0`.

Retrieval applies hard safety and availability filters before bulk Wiki scoring. A
`600` cap retains every surviving demo candidate through exact Korean/English aliases,
Korean facets, vectors, and structured reranking. Party-sized budget and negative
preferences are enforced before final output. The final score is exactly `60%` Wiki,
`25%` structured preference, and `15%` operational/menu metadata; that operational
signal uses menu semantic relevance, price, delivery fee, and ETA—not rating. The LLM
contract uses evidence precedence
`OPTION > MENU > VARIANT_WIKI > FAMILY_WIKI` and carries referenced passage IDs,
grounding scope, and uncertainty codes so possible, unknown, and not-provided facts
cannot be strengthened into certainty.

Ingredient, allergen/dietary, and preparation questions now preserve their requested
facet through deterministic and model-tool paths. Korean server text uses taxonomy
names and scoped status labels rather than exposing English Wiki prose, while the
frontend renders the structured claims and keeps raw English passages in a collapsed
supporting-evidence section. All nine onboarding allergens and five safety dietary
signals remain visible; operational tags are excluded from the risk section.

Explicit absence alternatives are backed by `VERIFIED` synthetic menu evidence while
cross-contact remains `UNKNOWN`. They can support a qualified alternative but cannot
be described as allergy-safe.

The local source packages checksum migrations `001`–`009` and uses base catalog
`demo-2026.08.11-knowledge-v3` plus knowledge catalog contract
`demo-knowledge-catalog-2026.08.11-v3`. Local final gates passed: backend Pytest 348,
100-query recommendation evaluation, 369-assertion chatbot acceptance, Ruff, Mypy
(64 files), frontend lint/6 files/16 tests/production build, and fresh SQLite exact readiness
with zero FK violations. No 2026-08-11 Oracle migration, seed, OCI GenAI, `/readyz`,
public browser, or rollback result is claimed here; full details are in `TEST_REPORT.md`.

## Historical public baseline status

The audited Master Spec MVP is implemented and publicly deployed on the existing OCI
resources. Current release: `20260807T194921Z`. The public address is resolved from
OCI at runtime and is intentionally absent from this repository.

The 2026-08-07 frontend feedback pass is implemented, committed on
`codex/master-spec-completion`, deployed, and publicly verified. Repeated provider
list results are consolidated by grounded IDs so the UI renders one carousel per
tool type.

Confirmed live for the historical baseline only:

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

## Historical 2026-08-09 chatbot-improvement status

The multi-turn dialogue, knowledge graph, grounded hybrid retrieval, provider
capability/readiness, and release-safety implementation is deployed from
`codex/master-spec-completion` and tracked by Draft PR #1. Oracle migration/seed,
on-demand OCI primary/fallback/error classification, public conversation/order
regression, and three consecutive Primary runs are verified. The approved temporary
current-source SSH rules were removed after every window; the final independent NSG
state is TCP 22 `0`, existing TCP 80 `1`. The trusted rollback target is
`20260809T083629Z-bfb59275b93f`.

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

## 2026-08-08 initial-chat polish

- Cart action copy is now **Add to cart**; all supported localized action/result labels
  likewise omit demo/mock-cart wording. The payment and synthetic-order boundaries
  remain visibly labeled as demo behavior.
- Chat starts directly with YOBI's welcome bubble. The removed delivery-context card
  no longer repeats language, country, spice, allergy count or confirmed address.
- **Try the demo question** is a compact action beneath the initial welcome bubble and
  disappears after the conversation starts instead of occupying the composer area.
- The collapsed chat-menu chevron points upward and the expanded chevron points
  downward. Release `20260807T194921Z` passed mobile browser review, public focused
  English/Korean E2E, and three consecutive public Primary Demo orders.

All merchants, reviews, hotels, payments and orders are synthetic. The deployment is
public HTTP for presentation and has no custom domain/TLS. Stored vectors are
deterministic `yobi-semantic-hash-v1`; OCI Cohere embedding is not claimed.
