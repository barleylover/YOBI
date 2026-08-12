# YOBI test and deployment evidence ledger

- Structured-recommendation local checkpoint: 2026-08-12 KST
- Historical public baseline verification: 2026-08-08 KST
- Chatbot-improvement worktree checkpoint: 2026-08-09 KST
- Wiki-centric local worktree checkpoint: 2026-08-11 KST
- Current flow authority: `docs/STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`
- Historical master spec: `YOBI_FINAL_MVP_CODEX_MASTER_PROMPT.md`
- Historical chatbot goal: `YOBI_CHATBOT_IMPROVEMENT_CODEX_GOAL.md`
- Improvement branch: `codex/master-spec-completion`
- Historical deployed baseline release: `20260807T194921Z`
- Chatbot-improvement deployed release: `20260809T084353Z-704f74712d9d`
- Verified rollback target: `20260809T083629Z-bfb59275b93f`
- Public address: resolved from OCI at runtime; not stored in Git
- Evidence boundary: only the first section below applies to the 2026-08-12 structured
  flow. Every Oracle/OCI/public result later in the file is historical evidence for
  its named 2026-08-09-or-earlier release and does not prove the current revision.

## 2026-08-12 structured recommendation checkpoint — local only

This section records the current working-tree contract and completed local checks. It
does **not** record a deployment. Migration `010` has not been applied to Oracle, the
new recommendation release family has not been activated on OCI, and the structured
flow has not been verified through the public site.

### Implemented source contract

| Boundary | Current source contract | Evidence status |
|---|---|---|
| User flow | Confirmed profile/address → structured multi-select → result buttons → existing order flow; no recommendation composer | Local React/API implementation and focused tests |
| Selection | Same category `OR`; non-empty subjective categories express cross-category `AND`; stable catalog codes and localized labels | Local structural/domain/frontend contract; semantic passage fit needs provider/golden-set evaluation |
| Dietary scope | Explicit halal-certification and vegan choices only; no public v2 allergy filter or safety guarantee | Local domain/UI/API contract |
| Spice | Reviewed menu maximum and KR/US reference examples use `1..5` | Local seed/domain/frontend contract |
| Eligibility | Merchant service area, menu availability, base price, maximum spice, valid halal scope, confirmed vegan conflict, and similar-history exclusion are server owned | SQLite implementation exercised; Oracle implementation statically checked only |
| Retrieval | Per-value exact/essential, lexical, and vector ranks are fused; bounded raw hits require real category coverage, while a lower-weight profile query cannot count as evidence | SQLite deterministic-vector contract exercised; live Oracle vector query **NOT RUN** |
| Generation | One no-tool/no-continuation dispatch chooses final pool menus and explanations; valid model order is preserved | Fake-provider/service/generator contract exercised; live OCI provider **NOT RUN** |
| Replay | Request ledger prevents duplicate dispatch; post-dispatch uncertainty does not auto-redispatch | Local repository/service contract |
| Data | 60 synthetic merchants, 600 menus, 100 categories, 102 Wiki documents, 345 essential claims, 918 prose paragraphs, and 1,263 total chunks | Local compiler/seed contract only |
| Migration package | Additive/checksum migration set `001`–`010` | Parser/deploy-source checks pass; live Oracle application **NOT RUN** |

The local release family foreign-keys its knowledge release and stores versioned
catalog/preference/spice/certification/embedding identities. Independent immutable
catalog/certification manifest FKs and live atomic family activation/rollback have not
been implemented and verified as an Oracle deployment gate. A current local
`/readyz` success would cover its existing catalog/knowledge/provider configuration
checks, not those missing family-manifest gates.

The prose-first Wiki keeps 245 ingredient and 100 preparation essential claims.
Subjective material is represented by 918 natural paragraphs; the total 1,263 chunks
combine those paragraphs with 345 readable essential-fact chunks. Legacy allergy
tables/identifiers remain for storage compatibility but are excluded from the public
v2 recommendation context and acceptance contract. Reviews and merchant promotional
prose remain synthetic display data with recommendation and grounding weight `0`.

### Completed local checks at this checkpoint

These scopes overlap and must not be summed into one test total.

| Local check | Result | What it proves |
|---|---:|---|
| Wiki, preference-catalog, prose compiler, and recommendation-generator targeted Pytest | **PASS — 26 tests** | Prose/essential chunk contract, catalog vocabulary/labels, and bounded generator validation |
| Deploy, migration, bootstrap, seed, and documentation-contract targeted Pytest | **PASS — 75 tests** | Migration package/parser and local seed/release expectations; not live Oracle DDL |
| Structured service, generator, and migration targeted Pytest | **PASS — 21 tests** | Empty-pool zero call, one-dispatch result, replay/fallback, order preservation, and request-ledger behavior |
| Hybrid retrieval targeted Pytest | **PASS — 30 tests** | SQLite/Oracle source parity for per-value vector/lexical/exact-essential RRF, raw-hit and passage limits, category OR/coverage, and non-authoritative soft-profile scoring; no live Oracle query |
| Post-review structured persistence/service targeted Pytest | **PASS — 21 tests** | Current-UTC snapshot/live projection, stale removal, v2 selection/order boundary, open-end certification validity, and SQLite/Oracle contract hardening |
| Updated legacy fallback/golden acceptance scope | **PASS — 29 tests; 369 acceptance assertions** | Five-level spice, prose-first public facets, catalog gating, and no public allergy-list copy in retained regression paths |
| Updated catalog/safety/readiness regression scope | **PASS — 23 tests** | Current sparse legacy-allergy expectations, essential Wiki claim types, menu distribution, and shared Oracle hybrid-weighting contract |
| Frontend ESLint | **PASS** | Current structured UI lint contract |
| Full backend Pytest | **PASS — 386 tests; 1 StarletteDeprecationWarning; 266.62s** | Whole local SQLite/backend regression for the current working tree; no live Oracle execution |
| Whole-tree Ruff | **PASS** | Backend, tests, scripts, and deployment-source lint contract |
| Whole-source MyPy | **PASS — 72 source files** | Static type contract only; no live Oracle/provider execution |
| Frontend Vitest | **PASS — 19/19 tests** | Structured selector/result/API/order component contracts |
| Frontend production build | **PASS** | TypeScript and Vite compilation of the current structured UI; the existing chunk-size warning is non-fatal |
| Local Playwright on dedicated ports `15173/18000` | **PASS — 20 tests; 24 intentional duplicate-viewport skips; 34.8s** | iPhone core structured flow 11/11 plus Pixel 7, 1366×768, and 1920×1080 core paths; local browser evidence only |
| Structured backend MyPy | **PASS — 7 source files** | SQLite/Oracle/service type consistency after the post-review hardening; no Oracle connection, SQL execution, or vector result |

The first default-port browser launch could not start because port `5173` was already
held by a CashFlow application SSH forward. The same YOBI checkout passed on isolated
ports `15173/18000`; the default-port attempt is therefore an environment collision,
not a YOBI test failure. The production build retained its existing non-fatal
546.57 kB chunk warning.

Local Playwright does not prove the public site or live OCI provider. Fake-provider
dispatch-count tests prove application
behavior and structural ID grounding, not the semantic faithfulness, output quality,
or latency of the configured live model. The current validator is not a general
natural-language entailment detector.

For subjective categories, current tests prove selected-code validation and per-
category evidence-reference coverage. They do not prove that every best-scoring
passage semantically entails its category. Normal-result cross-category `AND` quality
and `NO_MATCH` judgment therefore remain live-provider/golden-set evaluation work;
`SEARCH_FALLBACK` is intentionally only a labelled proximity result.

### Explicitly unverified for this revision

- applying and checksum-recording `010` on Oracle, including resume behavior;
- seeding/activating the v2 recommendation release family and exact Oracle readiness;
- executing the v2 query through live Oracle `VECTOR_DISTANCE`;
- a real OCI generation request that selects and explains pool menus in one dispatch;
- Nginx/systemd activation, protected-route checks, and public mobile/desktop flow;
- live rollback of the application plus compatible active release-family pointer.

Until those gates are run and appended with an exact release ID and commands, the
verified public boundary remains the historical 2026-08-09 free-chat release below.

---

The remaining sections are historical records. Their free-form chat, allergy, three-
level spice, server-final-candidate, model/tool-loop, and public deployment statements
must not be used as the current structured-flow contract.

## Historical: 2026-08-11 Wiki-centric local checkpoint — not deployed

This historical section records that checkpoint's local data and code contract, not a
live environment result. The v3 catalog had not been seeded into the existing OCI
Oracle database, activated as an OCI release, or checked through public health,
readiness, or browser flows.
The public evidence in the next section still belongs only to the 2026-08-09 v2
release and migration ledger `001`–`008`.

| Boundary | Current local contract | Evidence status |
|---|---|---|
| Migration package | Exactly `001`–`009`, including `009_cart_confirmation_fingerprint.sql` | Repository files present; OCI application **NOT RUN** |
| Catalog | 60 merchants, 600 menus/maps, 100 categories, 1,200 evidence, 1,202 option groups, 2,405 option items | Local generated-seed contract; OCI seed **NOT RUN** |
| Incomplete menu facts | 54 ingredients/565 rows/206 menus; 10 allergen rows (9 onboarding + cross-contact marker)/595 rows/221 menus; 20 dietary attributes/1,217 rows | Deliberate demo realism contract |
| Wiki | 102 concepts/documents (`CUISINE` 2/`FAMILY` 30/`VARIANT` 70), 100 relations, 281 closure rows, 1,997 claims, 918 chunks | Local compiler contract; no active OCI release claimed |
| Claim types | ingredient 361, allergen 371, dietary 247, preparation 100, facet 918 | Local compiler contract |
| Scoped facts | 13 origin declarations, 119 merchant cross-contact ingredient rows, 4 option effects | Merchant rows cannot prove menu contents |
| Reviews/prose | 2,400 synthetic reviews; review and merchant prose weights are `0` | Display compatibility only |
| Ranking | Safety/availability filter, then exact alias + Korean facet + vector under cap `600`; party budget/negative preferences before output; Wiki `60%`, structured preference `25%`, operational/menu `15%` | Operational signal is menu relevance, price, delivery fee, ETA; rating weight `0` |
| LLM grounding | `OPTION > MENU > VARIANT_WIKI > FAMILY_WIKI`; passage IDs, scope, uncertainty codes required | Local prompt/parser/validator contract |
| Local final gates | Backend, evaluation, frontend, static checks, fresh SQLite readiness | **PASS** — details below |
| Oracle/OCI/public gates | Live Oracle seed/migration, OCI GenAI, routes, browser E2E | **NOT RUN** for v3; historical v2 evidence does not prove v3 |

Base catalog is `demo-2026.08.11-knowledge-v3`; knowledge catalog contract is
`demo-knowledge-catalog-2026.08.11-v3`. Menu-specific ingredient and allergen gaps
remain `UNKNOWN`/`NOT_PROVIDED`; they are not filled from reviews, merchant
descriptions, or shared-kitchen declarations. Before this revision can be called
deployed, the exact `001`–`009` Oracle ledger, active release counts, vectors,
`/healthz`, `/readyz`, cart confirmation/stale-payment safeguards, chatbot basics, and
public product flow must all be verified on one release and appended here.

Explicit absence alternatives in this local contract have `VERIFIED` synthetic menu
evidence and retain `UNKNOWN` cross-contact. They are distributed across all three
demo areas. This is qualified demo evidence, not an allergy-safe merchant or a
real-world certification.

### 2026-08-11 local final-gate evidence

| Gate | Verified result |
|---|---|
| Backend Pytest | **PASS** — 348 passed, 1 third-party Starlette/httpx deprecation warning, 276.59s |
| Recommendation evaluation | **PASS** — 100 queries; constraint, canonical top-3, evidence, unsafe reassurance, price, option, and recommendation-contract failures all 0 |
| Chatbot acceptance | **PASS** — 9 transcripts, 16 message turns, 2 events, 3 knowledge cases, 369 assertions; every failure counter 0 |
| Ruff | **PASS** — `backend`, `scripts`, and deploy Python files, 0 errors |
| Mypy | **PASS** — 64 source files, 0 errors |
| Frontend | **PASS** — ESLint, 6 Vitest files/16 tests, TypeScript and Vite production build; 1,796 modules built; three concurrent full Vitest runs also exited 0 after timer cleanup |
| Fresh SQLite readiness | **PASS** — 60 merchants, 600 menus/maps, all readiness checks true, `canonical_ready=true`, `knowledge_ready=true`, FK violations 0 |
| Existing DB upgrade | **PASS locally** — bundled 150-menu demo DB copy upgraded without `--fresh`; runtime profile/session/cart/order rows preserved and exact v3 readiness restored |

These results prove the local SQLite/deterministic demo path. Oracle SQL parity,
seed bind generation, migration safety contracts, and repository mocks are covered by
the local suite, but an actual Oracle connection, OCI embedding/generation, v3
migration ledger, public readiness, and browser journey were not run in this change.

## Historical: 2026-08-09 chatbot-improvement final gate (live evidence for that release)

This table is frozen evidence for the 2026-08-09 v2 release. At that time Phase 0–7
was connected, locally verified, deployed to the existing OCI VM/ADB, and independently
checked through the public product surface. It must not be used as proof for the
2026-08-11 v3 working tree.

| Gate | Required final evidence | 2026-08-09 verified status |
|---|---|---:|
| Ruff | `.venv/bin/ruff check backend scripts deploy/*.py` | **PASS** — zero errors |
| MyPy | `MYPYPATH=backend:scripts:. .venv/bin/mypy --explicit-package-bases --python-version 3.12 backend/app backend/evaluation scripts deploy/release_state.py deploy/run_with_runtime_env.py deploy/secure_bootstrap.py` | **PASS** — 62 source files, zero errors |
| Pytest | `cd backend && ../.venv/bin/pytest -q` | **PASS** — 223 passed, 1 Starlette deprecation warning, 47.11s |
| Legacy evaluation | `make evaluate` legacy retrieval run | **PASS** — 100 queries; every failure counter zero |
| Chatbot acceptance | `make evaluate` chatbot acceptance run | **PASS** — 8 transcripts, 15 turns, 2 events, 3 knowledge cases, 345 assertions; every safety/state counter zero |
| Frontend | `pnpm lint`, Vitest, TypeScript/Vite build | **PASS** — 4 Vitest files/11 tests; 1,796 modules built |
| Local product E2E | Playwright across configured viewports | **PASS** — 21 passed, 27 intentional viewport skips; four-viewport Primary flow plus complete iPhone flow |
| Release/static safety | changed shell syntax, diff/conflict scan, provider/cache/deploy contract tests | **PASS** — all checks passed |
| Repository hygiene | tracked `.env`, credential/private-key patterns, production debug flags | **PASS** — 0 files for each scan |
| Oracle migration/seed | Applied 001–008, exact catalog/graph/mapping/vector integrity | **PASS** — exact ledger; 29 concepts, 27 relations, 66 closure rows, 411 claims, 29 documents, 261 chunks, 150 menu mappings |
| OCI GenAI | On-demand normal, classified failure, grounded fallback smoke | **PASS** — Grok Function Calling/continuation, GPT-OSS fallback model, invalid-model classification, Oracle deterministic fallback |
| Public routes/auth | root, health, readiness, QR 200; unauth demo control 403 | **PASS** — exact status codes and four security headers |
| Public conversation | `hi` no cards, readiness, correction, snapshot event/reload, grounded explanation | **PASS** — configured public Playwright suite |
| Public ordering regression | options, cart, delivery, Mock checkout/payment/order/idempotency | **PASS** — configured public Playwright suite, 21 passed/27 intentional skips in 2.4m |
| Public Primary Demo | Same new release, three consecutive passes | **PASS** — iPhone 13, worker 1, 3/3 in 26.7s |
| Git/Draft PR | Current branch pushed; Draft PR #1 head equals remote branch | **PASS** — `codex/master-spec-completion`, OPEN/Draft, not merged |

### 2026-08-09 deployed improvement evidence

Release `20260809T084353Z-704f74712d9d` was built from an archive SHA-256 identity,
verified on the VM, imported under Python 3.9 before any database write, migrated,
seeded, activated, and checked by local health/readiness. The exact live migration
ledger is `001`–`008`. The active catalog is `demo-2026.08.09-knowledge-v2`; the
immutable knowledge release is `knowledge-demo-1c7dd5378736fc75567ba871`, catalog
`demo-knowledge-catalog-2026.08.09-v2`. Runtime and stored embeddings are independently
pinned to deterministic `yobi-semantic-hash-v1`, dimension `1536`, version
`2026-08-06`; generation is OCI on-demand with logical primary `xai.grok-4.3` and
fallback `openai.gpt-oss-120b`.

The Oracle seed verified 29 concepts, 27 relations, 66 closure rows, 411 claims,
29 documents, 261 chunks, 150 menu mappings, 30 origin declarations, 266 merchant
ingredient rows, and 4 option effects. All knowledge readiness checks are true, chunk
metadata mismatches are zero, and required base catalog/vector/option counts are exact.

Public `/`, `/healthz`, `/readyz`, and `/demo/qr` returned HTTP `200`; unauthenticated
`/api/v1/demo/status` returned `403`. Readiness reports production GenAI required,
OCI/on-demand configured, the exact catalog and knowledge release above, and every
database readiness check true. `X-Content-Type-Options`, `Referrer-Policy`,
`X-Frame-Options`, and `Permissions-Policy` were present.

The public configured Playwright suite passed 21 tests with 27 intentional viewport
skips in 2.4 minutes. It covers card-free greeting and multi-turn readiness, rejection
events, grounded explanation/comparison, profile correction, option risk handling,
cart/delivery, localized flow, Mock payment failure/retry, and Mock order completion.
The Primary iPhone flow then passed three additional consecutive runs in 26.7 seconds.
The HTTP-only public environment also verified the `getRandomValues` client-key
fallback used when `randomUUID` is unavailable.

Actual OCI smoke passed the primary Grok function call and two-step continuation after
one provider-directed rate-limit wait, the GPT-OSS fallback-model response, an invalid
model classified as `PROVIDER_UNAVAILABLE`, and deterministic fallback over the real
Oracle repository with dietary evidence. The release window contains zero Traceback,
CRITICAL, Oracle, HTTP 5xx, or systemd-priority error lines; two classified rate-limit
events were recovered. `yobi-api` and Nginx are active, and the runtime environment is
`root:root` mode `0600`.

The user-approved temporary current-source `/32` TCP 22 rule was added only for each
SSH deployment/verification window and removed by exact rule identity on every exit.
The final independent NSG query reports TCP 22 rules `0` and the pre-existing TCP 80
rule `1`. No IAM, security-list, credential, secret, database resource, or paid-resource
expansion was made. The trusted rollback target is
`20260809T083629Z-bfb59275b93f`; rollback uses
`sudo /opt/yobi/current/deploy/rollback.sh` and restores the app and bound knowledge
pointer before rechecking health/readiness.

The complete backend suite passed `223` tests in 47.11 seconds with one third-party
Starlette deprecation warning. Ruff reported zero errors and MyPy passed all 62 checked
source files. The 8-transcript, 15-turn acceptance suite passed all 345 assertions,
including 2 events and 3 knowledge cases, with every safety/state counter at zero.
The legacy 100-query evaluation also reported zero constraint, grounding, safety,
price, and option failures. Frontend ESLint, 4-file/11-test Vitest, TypeScript, and the
1,796-module Vite build passed.

The final repository-hygiene pass found zero tracked `.env` files, zero files matching
credential/private-key/credential-bearing-URL patterns, zero production debug flags,
and zero merge-conflict markers. All changed shell scripts passed `bash -n`. Synthetic
placeholder identifiers in tests are not credentials and remain confined to fixtures.

Catalog, knowledge release, embedding identity, generation model/serving mode, app
release, and rollback target above were checked independently. The live evidence is
for OCI on-demand only; dedicated adapter fixtures are not evidence of a live dedicated
endpoint.

Locally evaluated quality counters are all zero: hard-constraint violations, unsafe
severe-allergy reassurance, Wiki-missing-as-absent errors, review-influenced
ranking/safety, body/card/price/option contradictions, ungrounded menu facts, core
menu mapping gaps, and required-option gaps. Public route and product regressions are
also zero in the recorded suite. Review snippets are synthetic display data with
recommendation and safety weight `0`.

## Historical: release baseline before chatbot improvement

| Gate | Result | Verified evidence |
|---|---:|---|
| Master Spec implementation audit | PASS with stated demo boundaries | Initial audit plus remediation record in `CODEX_HANDOFF_AUDIT.md` |
| Ruff | PASS | Backend and scripts |
| MyPy | PASS | 31 application source files |
| Pytest | 61 PASS | API, agent, preset intent, OCR, seed, cart/payment integrity, fallback, security and migration parser |
| Frontend ESLint | PASS | React/TypeScript source and tests |
| Frontend unit | 2 PASS | Evidence status rendering |
| TypeScript/Vite build | PASS | 1,796 modules; production assets generated |
| Local Playwright | 18 PASS | 18 additional intentional cross-viewport skips |
| Retrieval evaluation | 100 PASS | Every mismatch/unsafe-reassurance counter is zero |
| Oracle runtime connection | PASS | Runtime user `YOBI_APP`; readiness HTTP 200 |
| Oracle migration | PASS | `SCHEMA_MIGRATION` versions 001–004; append-only three-level spice migration applied |
| Oracle seed integrity | PASS | All exact normalized/catalog counts verified |
| Oracle Vector Search data | PASS | Menu 150, review 600 and knowledge 150 vectors; NULL count zero for all three |
| Grok Function Calling | PASS | Independent two-step continuation smoke after one provider-directed 429 wait |
| Runtime Agent Loop | PASS | Public grounded-card flow passed; repeated list-producing tool results are merged by grounded ID |
| Deterministic fallback | PASS | Forced fallback over the deployed Oracle repository returned dietary evidence |
| Address OCR | PASS | VM Tesseract English/Korean packs active; public bundled-image journey passed |
| Public API smoke | PASS | Health, grounded evidence IDs, cart, OCR address, delivery, payment and order |
| Public focused UI E2E | 3 PASS | Initial chat, fixed collections, ordering, profile/cart restoration and Korean full order |
| Public Primary E2E | 3 PASS consecutively | iPhone 13, worker 1, 9.1s / 8.0s / 9.6s |
| Systemd/Nginx | PASS | Both active; local health and ready checks passed after activation |
| Runtime env protection | PASS | `/etc/yobi/yobi.env` is `root:root`, mode `0600`; values were not printed |

## Historical: Oracle data integrity snapshot for the recorded baseline

Exact verified row counts after non-destructive upsert:

- 3 service areas, 20 categories, 30 merchants and 150 menus
- 150 knowledge records, 300 evidence records and 600 review snippets
- 302 option groups and 605 option items
- 20 ingredients / 150 menu-ingredient links
- 9 allergens / 162 menu-allergen links
- 15 dietary attributes / 317 menu-dietary links
- 1 explicit option dietary conflict and 20 synthetic address fixtures

Required option groups without available items: zero. Canonical menus: present. Menu,
review and knowledge vectors: no NULL values.

## Historical: 2026-08-09 GenAI and RAG truth boundary

The deployed Grok path is a real bounded Function Calling loop. It uses a small
intent-routed subset of the complete 14-tool allowlist, validates arguments with
Pydantic, executes Oracle-backed tools, returns a bounded untrusted-data payload,
and receives the final model response. The prior recorded runtime aggregate contained
9 normal turns, 0 fallback turns, 25 provider responses and 16 DB-backed tool calls.

Fallback remains mandatory because the provider can return 429. The independent
Grok smoke honored the provider `Retry-After` once and then completed. A forced or
failed provider turn uses the same Oracle repository and domain policies; it does
not switch to a second fake catalog.

Oracle `VECTOR_DISTANCE` is used for menu, review and knowledge hybrid ranking after
SQL hard filters. The stored 1,536-dimensional vectors are currently generated by
`yobi-semantic-hash-v1`, not OCI Cohere. OCI's current region matrix did not confirm
on-demand Cohere Embed 4 in Seoul, so no cross-region resource or IAM expansion was
invented. This is a transparent quality limitation, not a missing Vector Search path.

## Historical: remaining boundaries recorded for the 2026-08-09 release

- The public demo is HTTP on the already-approved TCP 80 boundary. It has no custom
  domain or TLS certificate and must not be described as production-ready.
- Restaurants, reviews, hotels, payments and orders are synthetic. No real restaurant,
  courier, Yogiyo API or payment processor is contacted.
- SSE opens immediately and emits lifecycle/status/card/text events, but provider
  token-level streaming is not claimed.
- The one warning in Pytest is a third-party Starlette TestClient deprecation warning;
  it does not affect the application contract.

## Historical: 2026-08-08 chat-room menu — deployed verification

- Release `20260807T190544Z` serves the localized three-action chat-room menu and
  deterministic Weekly ranking and K-POP Demon Hunters collections. These two
  shortcuts intentionally do not call an LLM or a live ranking service.
- The focused public iPhone suite passed both tests: fixed card order, an orderable
  BHC card, profile editing, same-session chat/card/cart restoration, server-side
  dietary revalidation after adding a milk allergy, and Korean menu/response labels.
- The public Primary Demo completed three consecutive full mock orders. Public root,
  health, readiness and QR routes returned HTTP 200; protected demo status returned
  HTTP 403 without its token.
- A deployed forced-fallback smoke used the real Oracle repository and returned a
  dietary-evidence card. Release-window `ERROR`, `Traceback` and `CRITICAL` log lines
  were zero.
- The first activation attempt stopped before switching `/opt/yobi/current` because
  historical menu relation rows made the seed count check fail. The seed now replaces
  only the three relation sets owned by the 150 synthetic menu IDs, one table per
  transaction; profiles, carts, orders and migrations are untouched. A generated-seed
  count regression test was added, and the final Oracle verification passed exact
  counts with zero NULL menu, review or knowledge vectors.
- Runtime user `YOBI_APP`, `SCHEMA_MIGRATION` 001–004, `root:root` mode `0600` for
  `/etc/yobi/yobi.env`, and active `yobi-api`/Nginx were reconfirmed without printing
  secret values. The temporary source-specific SSH rule was removed; the final NSG
  contains only the approved public TCP 80 rule and no TCP 22 rule.

## Historical: 2026-08-08 initial-chat polish — deployed verification

- Release `20260807T194921Z` changes **Add to mock cart** to **Add to cart** and
  removes the equivalent demo-cart wording from all 16 supported language packs.
- The delivery-context summary card is absent. A fresh chat opens directly with the
  localized YOBI welcome bubble and a compact **Try the demo question** action directly
  beneath it; the composer no longer contains that action.
- The chat-menu chevron now points upward while collapsed and downward while open.
  Mobile 390×844 browser inspection confirmed both states, no horizontal overflow,
  and zero console errors.
- ESLint, two Vitest tests, TypeScript and the 1,796-module Vite build passed. Local
  Playwright passed 18 tests with 18 intentional cross-viewport skips.
- Public iPhone verification passed three focused tests, including the complete Korean
  order, followed by three consecutive Primary Demo orders. Root, health, readiness
  and QR returned HTTP 200; protected demo status remained HTTP 403 without a token.
- Oracle `SCHEMA_MIGRATION` remains 001–004, seed/vector verification passed unchanged,
  and release-window `ERROR`, `Traceback` and `CRITICAL` log lines were zero. The final
  NSG contains one public TCP 80 rule and no TCP 22 rule.

## Historical: 2026-08-07 UI/UX verification addendum

- ESLint, Vitest 2 tests, TypeScript and Vite build all passed; 1,788 modules built.
- Playwright passed the revised address-first primary order on iPhone 13, Pixel 7,
  desktop 1366 and desktop 1920.
- Focused E2E verifies 16 language options, selected-language country priority,
  gender removal, vegan/religion inputs, three spice radios, the address-first flow,
  dietary option lock/reason/unlock, and the complete mock order.
- In-app browser QA verified swipe/arrow carousel navigation, direct Order Builder
  scroll, checkout dietary/minimum readiness, 390px and 1366px width containment,
  and zero browser console errors.
- The new `make dev` launcher started SQLite/fixture/fallback mode, selected 8001 and
  5174 without disturbing existing 8000/5173 listeners, returned health/readiness
  HTTP 200, passed the Primary Demo on all four Playwright viewports, and released
  both selected ports and PID files after `Ctrl-C`.
- Public provider verification exposed one repeated `search_menus` tool result. The
  server now merges repeated list-producing tool results by their grounded IDs and
  emits one deduplicated carousel per tool type; a focused regression test covers it.
- OCI release `20260807T063338Z` passed public `/healthz`, `/readyz`, `/`, and
  `/demo/qr`; unauthenticated demo status remained HTTP 403, the served bundle
  contained the new UI, and the Primary Demo then passed three consecutive times.
- Deployment used one temporary current-source `/32` TCP 22 rule. The exact rule was
  removed after verification, and the final current-source SSH rule count is zero.

## Historical: 2026-08-07 second UI iteration — deployed verification

This section covers the current working tree after the separate welcome screen,
locale/profile split, multilingual ordering controls, expanded allergies, three-level
database spice contract, and same-restaurant add-on loop. It is included in release
`20260807T093233Z`.

- Ruff passed for backend, tests, scripts and deployment code; MyPy passed 31 source
  files.
- Pytest passed 58 tests. This includes the same-merchant profile filter, 1–3 seed
  invariant, generic severe-allergen conflict handling, option-rule targeting, and
  the PL/SQL migration parser.
- ESLint, 2 Vitest tests, TypeScript and Vite production build passed; 1,793 modules
  built.
- Local Playwright passed 12 tests with 12 intentional cross-viewport skips. The full
  primary flow passed on iPhone 13, Pixel 7, desktop 1366 and desktop 1920.
- The revised iPhone primary flow passed three consecutive runs. It adds a first menu,
  opens the same-restaurant carousel, adds a second menu, verifies the repeat prompt,
  checks cart badge totals 2 → 3 → 2 as quantity changes, and completes a ₩24,900
  mock checkout without a real charge.
- Mobile visual QA confirmed the revised, speech-bubble-free welcome page fits both
  390×844 and 375×667 viewports with no page scroll or internal dead space. The
  profile page now renders only the input card, with locale change inside that card.
- A new full Korean localization E2E covers profile step 2, address confirmation,
  chat/fallback cards, menu and option labels, restaurant note, delivery, cart
  readiness, payment and order confirmation. The iPhone 13 plus desktop-1366 suite
  passed 10 tests with 4 intentional cross-viewport skips in 20.3 seconds.
- Existing local SQLite catalog rows were updated through key-preserving upsert; user,
  session and cart rows were not deleted. The observed catalog spice range is 1–3 and
  category min/max is 1–3.
- `004_three_level_spice.sql` is append-only, parser-tested and recorded in live
  `SCHEMA_MIGRATION`; the live menu spice range is 1–3 and normalized dietary seed
  count is 305.
- Public `/healthz`, `/readyz`, `/`, and `/demo/qr` returned HTTP 200; unauthenticated
  demo status remained HTTP 403. The served bundle contains the new welcome and
  Korean locale copy.
- The public iPhone Primary Demo passed three consecutive full orders in 37.6 seconds,
  and the public Korean iPhone flow independently passed profile through mock payment
  and confirmation. Release-window logs contained 7 normal assistant turns, 18 tool
  calls and zero HTTP 5xx or fallback turns.
- After remote verification, the two temporary TCP 22 `/32` rules were removed. The
  final NSG state has zero SSH rules and retains the single approved public TCP 80
  rule; health, readiness and the public root remained HTTP 200 after cleanup.
