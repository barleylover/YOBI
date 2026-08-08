# YOBI test and deployment evidence ledger

- Historical public baseline verification: 2026-08-08 KST
- Chatbot-improvement worktree checkpoint: 2026-08-09 KST
- Source of truth: `YOBI_FINAL_MVP_CODEX_MASTER_PROMPT.md`
- Improvement goal: `YOBI_CHATBOT_IMPROVEMENT_CODEX_GOAL.md`
- Improvement branch: `codex/master-spec-completion`
- Historical deployed baseline release: `20260807T194921Z`
- Public address: resolved from OCI at runtime; not stored in Git
- Evidence boundary: the long-form sections below prove the historical UI/order
  release only. They do not prove that migrations `005`–`008`, the menu knowledge
  graph, new multi-turn chatbot, or current worktree are deployed.

## Chatbot-improvement final gate

The implementation matrix is in `CHATBOT_IMPROVEMENT_IMPLEMENTATION.md`. The current
worktree contains the Phase 0–6 runtime paths and Phase 7 deployment safeguards. The
final local quality gates below were rerun against the completed local implementation.
The branch and existing Draft PR are current; the new Oracle/OCI/Public release remains
separate and pending. A local or Git PASS is not substituted for live deployment proof.

| Gate | Required final evidence | Current status |
|---|---|---:|
| Ruff | `.venv/bin/ruff check backend scripts deploy/*.py` | **PASS** — zero errors |
| MyPy | `MYPYPATH=backend:scripts:. .venv/bin/mypy --explicit-package-bases --python-version 3.12 backend/app backend/evaluation scripts deploy/release_state.py deploy/run_with_runtime_env.py deploy/secure_bootstrap.py` | **PASS** — 62 source files, zero errors |
| Pytest | `cd backend && ../.venv/bin/pytest -q` | **PASS** — 217 passed, 1 Starlette deprecation warning, 43.97s |
| Legacy evaluation | `make evaluate` legacy retrieval run | **PASS** — 100 queries; every failure counter zero |
| Chatbot acceptance | `make evaluate` chatbot acceptance run | **PASS** — 8 transcripts, 15 turns, 2 events, 3 knowledge cases, 345 assertions; every safety/state counter zero |
| Frontend | `pnpm lint`, Vitest, TypeScript/Vite build | **PASS** — 4 Vitest files/10 tests; 1,796 modules built |
| Local product E2E | Playwright across configured viewports | **PASS** — 21 passed, 27 intentional viewport skips, 1.0m; four-viewport Primary flow plus complete iPhone flow |
| Release/static safety | changed shell syntax, diff/conflict scan, provider/cache/deploy contract tests | **PASS** — all checks passed |
| Repository hygiene | tracked `.env`, credential/private-key patterns, production debug flags | **PASS** — 0 files for each scan |
| Oracle migration/seed | Applied 001–008, exact catalog/graph/mapping/vector integrity | NOT YET RECORDED |
| OCI GenAI | On-demand normal, classified failure, grounded fallback smoke | NOT YET RECORDED |
| Public routes/auth | root, health, readiness, QR 200; unauth demo control 403 | NOT YET RECORDED |
| Public conversation | `hi` no cards, readiness, correction, snapshot event/reload, grounded explanation | NOT YET RECORDED |
| Public ordering regression | options, cart, delivery, Mock checkout/payment/order/idempotency | NOT YET RECORDED |
| Public Primary Demo | Same new release, three consecutive passes | NOT YET RECORDED |
| Git/Draft PR | Current branch pushed; Draft PR #1 head equals remote branch | **PASS** — `codex/master-spec-completion`, OPEN/Draft, not merged |

### Current pre-deployment boundary

Read-only OCI/public checks still describe the historical release only: public root,
health, readiness, and QR respond, while unauthenticated demo control remains denied.
The readiness payload still identifies the pre-improvement catalog, and the last
verified live migration ledger remains `001`–`004`. Migrations `005`–`008`, the new
knowledge release, provider-readiness contract, and Nginx header revision are not live.

The 2026-08-09 preflight returned HTTP `200` for `/`, `/healthz`, `/readyz`, and
`/demo/qr`, HTTP `403` for unauthenticated `/api/v1/demo/status`, catalog
`demo-2026.08.08-chat-menu-v1`, no active knowledge release field, and
`genai_required=false`. The attached NSG had zero TCP 22 ingress rules and one TCP 80
ingress rule. No public address or infrastructure identifier was written to Git.

No IAM, NSG, security-list, credential, database, or paid-resource change was made.
Harmless Compute Run Command probes remained accepted/visible but were never consumed
by the VM, so they do not establish a deployment path. The existing SSH/SCP path has
no TCP 22 ingress. A temporary current-source `/32` TCP 22 rule is therefore a separate
approval item; if approved it must be removed by exact rule identity and the final
SSH-rule count must be verified as zero while TCP 80 remains unchanged.

Final local checkpoint (not Oracle/public proof): the complete backend suite passed
`217` tests in 43.97 seconds with one third-party Starlette deprecation warning. Ruff
reported zero errors and MyPy passed all 62 checked source files. The 8-transcript,
15-turn acceptance suite passed all 345 assertions, including 2 event and 3 knowledge
cases, with every safety/state counter at zero. The legacy 100-query evaluation also
reported zero constraint, grounding, safety, price, and option failures. Frontend
ESLint, 4-file/10-test Vitest, TypeScript, and the 1,796-module Vite build passed.
Local Playwright passed 21 tests with 27 intentional cross-viewport skips in 1.0
minute, covering the Primary flow on four viewports and the complete iPhone flow.
The branch is pushed and the existing Draft PR is updated without creating a duplicate
PR. Oracle/OCI/Public rows remain pending because they require distinct live evidence.

The final repository-hygiene pass found zero tracked `.env` files, zero files matching
credential/private-key/credential-bearing-URL patterns, zero production debug flags,
and zero merge-conflict markers. All changed shell scripts passed `bash -n`. Synthetic
placeholder identifiers in tests are not credentials and remain confined to fixtures.

The final entry must separately report catalog version, knowledge release, active
embedding model/dimension/version, generation provider/model/serving mode, app release
ID, and rollback target. Do not infer one from another. Dedicated adapter fixture
tests are not evidence of a live dedicated OCI endpoint.

Locally evaluated quality counters are all zero: hard-constraint violations, unsafe
severe-allergy reassurance, Wiki-missing-as-absent errors, review-influenced
ranking/safety, body/card/price/option contradictions, ungrounded menu facts, core
menu mapping gaps, and required-option gaps. Public route failures are a separate
zero-tolerance deployment criterion and remain unmeasured for the improvement
release. Review snippets are synthetic display data with recommendation and safety
weight `0`.

## Historical release baseline (before chatbot improvement)

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

## Oracle data integrity snapshot

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

## GenAI and RAG truth boundary

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

## Remaining non-blocking boundaries

- The public demo is HTTP on the already-approved TCP 80 boundary. It has no custom
  domain or TLS certificate and must not be described as production-ready.
- Restaurants, reviews, hotels, payments and orders are synthetic. No real restaurant,
  courier, Yogiyo API or payment processor is contacted.
- SSE opens immediately and emits lifecycle/status/card/text events, but provider
  token-level streaming is not claimed.
- The one warning in Pytest is a third-party Starlette TestClient deprecation warning;
  it does not affect the application contract.

## 2026-08-08 chat-room menu — deployed verification

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

## 2026-08-08 initial-chat polish — deployed verification

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

## 2026-08-07 UI/UX verification addendum

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

## 2026-08-07 second UI iteration — deployed verification

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
