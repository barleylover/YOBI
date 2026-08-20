# YOBI MVP implementation status

Last updated: 2026-08-17 KST

## 2026-08-17 Wiki expansion and UI refinement (FINAL ACTIVE)

Application `20260816T201131Z-29fbc2f9fd32` is the final public release. The release
keeps the deterministic server-owned recommendation structure while adding a more
conversational assistant/user-bubble presentation, stronger visual hierarchy, sticky
quick replies, refined carousel/order messages, and seven public cuisine choices.
Public browser verification covered welcome+locale, fixed address, the expanded
selector, and horizontal-overflow safety without submitting another recommendation.

The active Oracle knowledge family now contains 198 concepts/documents, 154
relations, 430 closure rows, 345 claims, 1,551 chunks, 3,922 high-confidence mappings,
15,085/15,085 classifications, and 1,499 preference-support rows. This is +84 Wiki
documents and +1,967 mapped menus over the previous family. Active identities:

- knowledge `external-knowledge-0ffd2f53ba2e2539ee9c5a27`
- recommendation family
  `external-recommendation-0ffd2f53ba2e2539ee9c5a27-71a41f074c-5515c9c687`
- support manifest
  `71a41f074cb7fa0693b2d92009bcdf708ac0a335a08802171c5f1a408066d5f4`
- preference catalog `preference-catalog-2026.08.17-v3`

The expanded-cuisine quality run executed exactly five live provider requests. Four
were normal grounded results. The Italian case produced three valid server-frozen
menus but used the safety fallback; strict review found that the fallback response
discarded existing selected-cuisine evidence. The serializer now preserves that
evidence, and expanded SQLite plus live Oracle regression checks passed with zero
additional provider calls. The final deploy also made zero provider calls. This is a
reviewed 4-normal/1-safe-fallback observation, not a false 5/5 normal-generation claim
and not a percentile benchmark.

| Partition | Final evidence |
|---|---|
| `LOCAL` | Focused final gate 85/85 PASS; Ruff PASS; MyPy 86 sources PASS; Python 3.9 AST 87 files PASS; frontend 47/47, build, and Playwright 24/36-skip/0-fail remain unchanged after the UI build. |
| `ORACLE-OCI` | Exact migrations `001`–`012`; staged and active query plans; 3,922 mappings/1,499 supports; Italian zero-provider fallback regression; reviewed-five binding; health/readiness PASS. |
| `PUBLIC API` | Root, health, readiness, QR, and preference catalog HTTP 200; protected demo status 403; readiness reports 198 documents, 1,551 chunks, and 3,922 mapped menus. |
| `PUBLIC BROWSER` | Welcome+locale → fixed address → expanded selector PASS; seven cuisine buttons and no horizontal overflow; generated test profile/session deleted. |
| `NETWORK` | Temporary Bastion removed; TCP 22 ingress 0; TCP 80 unchanged; temporary Bastion/LB/NLB absence verified. |

Detailed evidence: [`evidence/KNOWLEDGE_EXPANSION_20260817.md`](evidence/KNOWLEDGE_EXPANSION_20260817.md).

## Historical 2026-08-16 external catalog recommendation release (superseded)

The status below records the predecessor and is retained for chronology. It is not the
current application or active knowledge identity.

The implementation scope is complete locally. It includes migration `012`, a reviewed
external concept/Wiki release, preference support manifest, server-owned deterministic
ranking/diversity, frozen top-three candidates, explanation-only one-dispatch
generation, preview/capabilities/readiness APIs, the combined welcome+locale flow,
fixed demo address, button-only preference collection, chat-card carousel, common
navigation, KDH/ranking, options/cart/review and explicit Yogiyo handoff. The UI does
not expose a payment-success or order-complete screen; the synthetic checkout/order
API is retained only for backend release integrity.

The initial public baseline served 200 merchants, 15,085 menus, 31,293 option groups
and 208,513 option items but had zero active recommendation knowledge/mappings. The
active Oracle data family now contains 114 concepts/documents, 107 relations, 300
closure rows, 345 claims, 1,299 chunks, 1,955 high-confidence mappings, 15,085/15,085
classifications and 1,073 preference-support rows, with zero invented merchant-specific
facts. The source is a supplied `YOGIYO_PUBLIC_WEB` snapshot, not a live Yogiyo API.

### Evidence partitions

| Partition | Current state | Evidence boundary |
|---|---|---|
| `LOCAL` | **PASS** | `make test`: Ruff, MyPy 83, backend 478/478 in 1,026.07s, frontend 47/47, ESLint. Build: 1,805 modules. Evaluation: 100 queries and 369 chatbot assertions with 0 failures. Playwright: 24 pass/36 intentional skip/0 fail. Local desktop/mobile/Arabic RTL browser flows passed. |
| `ORACLE-OCI` | **PASS** | Migration/data/support/ranking identities are active. Exactly five final quality requests passed: median 7,336.520 ms, max 7,860.266 ms, no percentile claim, 5/5 grounded/diverse/stable. |
| `PUBLIC API` | **PASS** | Final health/readiness/root/demo QR 200, protected route 403, source and recommendation readiness true. |
| `PUBLIC BROWSER` | **PASS** | Final combined welcome+locale/start UI rechecked; the user independently observed recommendation results, while the five-case HTTP gate verified internal criteria/evidence/order contracts. |

The active catalog is
`yogiyo-public-web:20260814:yobi-diverse-merchant-selection-v2:8a9d54b7230a`;
knowledge is `external-knowledge-fe97d5a7bf7205681f75aeb5`; recommendation family is
`external-recommendation-fe97d5a7bf7205681f75aeb5-78909a764a-5515c9c687`.
The support manifest is
`78909a764a01935850f615cd5f35bc8095e16455ea8fcc8611bb3dcebb94111`
and ranking-policy hash is
`5515c9c6877641a111e29ba418890b166b84374101877005749257eae826e191`.

### Candidate failure chronology and recovery

| Candidate | Result |
|---|---|
| `20260815T231001Z-b32f68c7353f` | Staged Oracle plan proof failed; no ready marker; old app retained, exact SSH rule cleaned. |
| `20260815T231426Z-64ea3e65938c` | Plan/source/structured passed, performance hit `DPY-4008`; no ready marker. It is now the verified active recovery checkpoint with public health/readiness 200. |
| `20260815T232437Z-50c1721d66b5` | Bind fixed and plan/source/structured passed; performance stopped at `PERFORMANCE_NORMAL_RECOMMENDATION_REQUIRED` after a provider rate-limit sample; automatic rollback restored the recovery checkpoint and cleaned SSH ingress. |
| `20260816T031853Z-e469d49d03b0` | Provisional query-plan/source/structured gates passed; a non-portable provisional-marker write failed and automatic rollback restored the recovery checkpoint. |
| `20260816T032847Z-2d9eab12f72a` | The marker write was fixed; an inverted provisional success condition still triggered automatic rollback after all three provisional gates passed. |
| `20260816T034237Z-e9417303ad55` | **ACTIVE PROVISIONAL** — query-plan, source-integrity, normal structured order and isolated fallback passed; performance was explicitly deferred; ready and provisional markers were written; public API/browser and final network cleanup passed. |

The invalid bind is fixed, and structured generation now uses
`openai.gpt-oss-120b`, output cap 2,048, provider concurrency 2, exactly one dispatch,
and no automatic retry/model fallback. The release benchmark counts exactly 30 paced
normal requests and a separate barrier concurrency-3 gate.

Historical checkpoint claim: **PASS — superseded deployment complete at that time**.

- historical application: `20260816T034237Z-e9417303ad55`
- quality evidence SHA-256:
  `868d35c331de63f4de3b600fd68e0628a3a2e26dd009f038b4a968adaad006a3`
- final cleanup: TCP 22 `0`, TCP 80 unchanged at `1`, temporary LB count restored
- the previously required full30/concurrency3 benchmark was explicitly superseded by
  the user's focused five-case quality acceptance; five samples support correctness
  inspection, not statistical percentile claims

> The 2026-08-12 structured-recommendation revision is deployed as release
> `20260812T141008Z-8418f92b7e37`. Migration `010`, the prose-first Wiki, persisted
> criteria/request ledger, bounded hybrid-RAG retrieval, one-dispatch OCI generation,
> public product flow, and rollback/redeploy path were verified against the live OCI
> environment. Historical sections remain labelled and are not the current contract.

## 2026-08-12 structured recommendation refactor (deployed and verified)

The new discovery screen replaces the free-text recommendation composer with
multi-select meal preferences. Selected values within a category use OR semantics;
non-empty categories express the user's cross-category AND intent. The v2 path offers
a five-level spice ceiling (with Korean and US reference examples), active halal-
certification filtering, and vegan guidance. Allergy filters are deliberately absent
from this public path.

The server performs objective eligibility and broad hybrid lexical/vector retrieval.
One bounded LLM generation request then selects final menus from the captured evidence
pool and writes their explanations; retrieval order is not final recommendation order.
There are no generation tools, follow-up turns, or automatic retries. A request ledger
prevents a replay from producing another dispatch and exposes an interrupted dispatch
as an unknown result rather than silently duplicating it.

Snapshot completion and later terminal-result reads re-check current menu state
against the request's pinned family. They remove newly ineligible menus and refresh
price, fee/ETA, halal, and vegan projections without rerunning or rewriting the model;
selection, cart review, and checkout use current-meal v2 criteria instead of retained
profile allergy/religion rules.

Wiki documents now retain only essential objective facts as structured claims while
subjective descriptions are natural prose passages. The release family pins the Wiki,
catalog, preference vocabulary, spice reference, certification data, and embedding
metadata used for an auditable recommendation result. All current merchant and
certification rows remain synthetic demo data.

The release family pins all version identities; knowledge has a release-table foreign
key while catalog and certification identities remain versioned family fields rather
than independent immutable manifest tables. Deployment readiness verifies their
compatible seeded state and active family. The live rollback rehearsal restored a
compatible application and data pointers, retained the additive migration ledger,
and passed health/readiness before the final release was redeployed.

The current selector starts each new meal with halal/vegan disabled and maximum spice
`3/5`; Korean profiles initially display KR examples and other locales US examples,
with an explicit switch. The preceding profile form no longer collects allergy or
spice values. Nationality, language, and optional religion do not activate dietary
filters. After results, choose, similar, edit, compare, and Wiki-evidence actions are
buttons; delivery notes remain a separate order-stage text input.

## Current local Wiki and catalog contract

The current local catalog makes reusable menu knowledge—not merchant descriptions or
reviews—the primary source for recommendation and explanation. It contains 60
synthetic merchants and 600 synthetic menus across 100 categories, all mapped to
family/variant concepts. The Wiki contains 102 concepts/documents (`2` cuisine, `30`
family, `70` variant), 100 relations, 281 closure rows, 345 essential claims, and
1,263 chunks. Claim totals are 245 ingredient and 100 preparation; chunks contain 918
prose paragraphs plus 345 essential-fact passages.

The catalog intentionally resembles an incomplete marketplace feed. Menu-specific
ingredient declarations cover 206 menus (565 rows), legacy allergen declarations cover
39 menus (48 rows), and dietary links contain 1,217 rows across 15 attributes. Thirteen
merchant origin declarations and 120 merchant ingredient rows are limited to
shared-kitchen cross-contact context. Four option effects remain menu-option specific.
The 2,400 review rows are display-compatible synthetic data with ranking and safety
weight `0`; merchant free-text descriptions also contribute `0`.

The compiled public corpus has 918 natural prose paragraphs and 345 readable
essential-fact passages. Legacy safety paragraphs are retained as `INTERNAL_ONLY` and
are not supplied to the v2 evidence pool or LLM. The recommendation pool uses public
Wiki passage vector, lexical, and exact/essential ranks fused per selected value only
after objective eligibility. Configured raw-hit and per-menu passage limits prevent
zero-score passages from manufacturing category coverage. A lower-weight profile query
can adjust recall but never supplies category evidence. Retrieval order bounds the
pool; it is not the final menu order. Reviews, merchant promotional prose, legacy
allergy data, religion, and raw addresses are not generation context.

The current source packages checksum migrations `001`–`010` and uses base catalog
`demo-2026.08.11-knowledge-v3` plus knowledge catalog contract
`demo-knowledge-catalog-2026.08.12-v4`. Focused local checks have been rerun during
integration. Oracle migration/seed, OCI GenAI, deployed `/readyz`, public browser, and
rollback results are recorded in `TEST_REPORT.md` for the exact active release.

Focused local checks currently pass for the prose Wiki/catalog/generator (26 tests),
deploy/migration/bootstrap/seed/document contracts (75 tests), structured
service/generator/migration behavior (21 tests), hybrid retrieval (30 tests), and the
post-review structured persistence/service hardening scope (21 tests), plus frontend
ESLint, Vitest (19 tests), the frontend production build, local Playwright (20 pass
with 24 intentional duplicate-viewport skips), and structured-backend MyPy (7 source
files). Retained fallback/golden acceptance checks also pass 29 tests and 369
assertions, and the updated catalog/safety/readiness regression scope passes 23 tests.
These targeted scopes overlap and are not a combined test total. Live Oracle
migration/vector execution, OCI generation, `/readyz`, public browser E2E, and rollback
were subsequently verified; see `TEST_REPORT.md` for the exact boundary.

The final deployed-source whole-backend run passes **392 tests** with one third-party
Starlette deprecation warning; whole-tree Ruff passes and MyPy passes **69 source files**.
Frontend ESLint, **19/19 Vitest tests**, and the production build pass (with the
existing non-fatal 546.57 kB chunk warning). The isolated local Playwright run passes
**20 tests** with **24 intentional duplicate-viewport skips** in 34.8 seconds. An
initial default-port launch failure came from port 5173 already being occupied by a
CashFlow app SSH forward; rerunning this checkout on dedicated ports 15173/18000
passed, so that collision is recorded as an environment conflict rather than a YOBI
product failure.

## Historical public baseline status

Everything from this heading to the end of the file is release history. Free-text
conversation, allergy controls, three-level profile spice, server-final ranking, and
agent-loop behavior described below are not current structured-flow requirements.

The audited Master Spec MVP was implemented and publicly deployed on the existing OCI
resources. Recorded release: `20260807T194921Z`. The public address is resolved from
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

## Historical product boundary

The product covers editable onboarding, conversational discovery, evidence-linked
recommendation/explanation, merchant comparison, menu options, translated notes,
three onboarding address methods, cart edit/remove/reprice, delivery confirmation, mock payment
failure/retry and one synthetic order.

## Historical 2026-08-07 frontend feedback pass

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

## Historical 2026-08-07 multilingual ordering iteration

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

## Historical 2026-08-08 chat-room menu iteration

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

## Historical 2026-08-08 initial-chat polish

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
