# YOBI test and deployment evidence ledger

- Final deployment: 2026-08-17 KST — application
  `20260816T201131Z-29fbc2f9fd32` active with reviewed expansion-five marker
- Structured-recommendation deployment verification: 2026-08-12 KST
- Historical public baseline verification: 2026-08-08 KST
- Chatbot-improvement worktree checkpoint: 2026-08-09 KST
- Wiki-centric local worktree checkpoint: 2026-08-11 KST
- Current recommendation recovery authority: `docs/RECOMMENDATION_PERFORMANCE_DIAGNOSIS_AND_IMPROVEMENT_PLAN.md`
- Structured UI/product authority: `docs/STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`
- Historical master spec: `YOBI_FINAL_MVP_CODEX_MASTER_PROMPT.md`
- Historical chatbot goal: `YOBI_CHATBOT_IMPROVEMENT_CODEX_GOAL.md`
- Improvement branch: `codex/master-spec-completion`
- Historical deployed baseline release: `20260807T194921Z`
- Chatbot-improvement deployed release: `20260809T084353Z-704f74712d9d`
- Structured-recommendation deployed release: `20260812T141008Z-8418f92b7e37`
- Recorded rollback predecessor: `20260812T135513Z-8f91a6c7120a`
- Public address: resolved from OCI at runtime; not stored in Git
- Evidence boundary: the 2026-08-17 section is current deployment evidence. Named
  2026-08-16 and 2026-08-12 sections are retained as historical evidence only.

## 2026-08-17 final deployment — expanded Wiki and reviewed five-call acceptance

### Final release identity and data

| Check | Result |
|---|---|
| Application | `20260816T201131Z-29fbc2f9fd32`; archive SHA-256 `29fbc2f9fd325e7c4e15c88a5abde9c8c12b7f5bdfb394fa50a5de244757fa25` |
| Oracle ledger | Exact migrations `001`–`012` |
| Knowledge | `external-knowledge-0ffd2f53ba2e2539ee9c5a27`; 198 concepts/documents, 154 relations, 430 closure, 345 claims, 1,551 chunks |
| Recommendation family | `external-recommendation-0ffd2f53ba2e2539ee9c5a27-71a41f074c-5515c9c687` |
| Support/ranking | 1,499 support rows; support manifest `71a41f074cb7fa0693b2d92009bcdf708ac0a335a08802171c5f1a408066d5f4`; ranking policy SHA unchanged at `5515c9c6877641a111e29ba418890b166b84374101877005749257eae826e191` |
| Mapping | 3,922 high-confidence mappings (+1,967); 4,673 concept-not-authored; 420 ambiguous; 4,217 non-food/promotion; 1,853 unsupported composite; total 15,085 |
| Preference catalog | `preference-catalog-2026.08.17-v3`; seven public cuisine options |

### Exactly five live provider observations

The expanded release made exactly five provider calls: Japanese PASS (6,469.304 ms),
Italian strict FAIL/safe fallback (6,405.549 ms), American PASS (6,179.516 ms),
Southeast Asian PASS (6,407.546 ms), and Mexican PASS (6,542.866 ms). Every request
returned three menus from three merchants. Median was 6,407.546 ms and maximum was
6,542.866 ms; no percentile claim is made.

The Italian server pool and Wiki support were valid, but the generated response did
not satisfy the strict contract and the deterministic fallback emitted an empty
`matched_criteria`. The fallback serializer was corrected to preserve selected option
codes and reviewed evidence IDs from the frozen server pool. Focused service tests,
the expanded SQLite mirror, and the final live Oracle `ITALIAN` fallback all passed
with three results, stable order, and selected-cuisine evidence on every result.
These remediation checks and the final deploy made **zero additional provider calls**.

Machine evidence:
[`deploy/evidence/recommendation_quality_expansion_five_20260817.json`](../deploy/evidence/recommendation_quality_expansion_five_20260817.json), SHA-256
`59a442314d6c22b5fe301d02e829e662f4b661e05dbe3f5af83e2dad0eeaa501`.

### Final validation partitions

| Partition | Result | Evidence |
|---|---:|---|
| `LOCAL` | **PASS** | Final focused scope 85/85; Ruff; MyPy 86 sources; Python 3.9 AST 87 files; Bash syntax and diff check. Existing final frontend evidence remains Vitest 47/47, ESLint, 1,805-module build, Playwright 24 pass/36 intentional skips/0 fail. |
| `ORACLE-OCI` | **PASS** | Staged and active query plans, source-integrity checks, 3,922 mappings, 1,499 supports, Italian zero-provider fallback, reviewed-five evidence binding, health/readiness. |
| `PUBLIC API` | **PASS** | Root, health, readiness, QR, and preference catalog HTTP 200; protected demo status HTTP 403. Readiness returned 198 documents, 1,551 chunks, and 3,922 mapped menus. |
| `PUBLIC BROWSER` | **PASS** | Welcome+locale, fixed address, and expanded selector rendered; seven cuisine buttons present; document width 1,280 equals client width 1,280; no recommendation submitted. Test profile/session deleted with 204/404 cleanup evidence. |
| `NETWORK` | **PASS** | Temporary Bastion path removed; TCP 22=0, TCP 80 unchanged, temporary Bastion/LB/NLB absent. |

The strict live observation is truthfully 4 normal results plus 1 safety fallback,
followed by a deterministic zero-provider fix. It is not recorded as 5/5 normal LLM
generation. Full details are in
[`evidence/KNOWLEDGE_EXPANSION_20260817.md`](evidence/KNOWLEDGE_EXPANSION_20260817.md).

## Historical 2026-08-16 final deployment — five-case quality acceptance

This section records only evidence actually obtained for the external-catalog
worktree and OCI attempts. Migration `012` and the external
knowledge/recommendation data family are active. By explicit operator choice the
paced 30-request/concurrency-3 performance gate was superseded by the user's explicit
five-case quality acceptance. All five strict cases passed and application
`20260816T034237Z-e9417303ad55` was final at that checkpoint; it is superseded by the
2026-08-17 expanded release above.

Evidence in this section is partitioned strictly as `LOCAL`, `ORACLE-OCI`,
`PUBLIC API`, and `PUBLIC BROWSER`. A PASS in one partition never closes another.

### LOCAL

| Command/check | Result | Boundary |
|---|---:|---|
| `make test` | **PASS** | Ruff; MyPy 83 files; backend Pytest 478/478 in 1,026.07s; frontend Vitest 47/47; ESLint. Warnings: two Starlette deprecations and Vitest localStorage only. |
| `make build` | **PASS** | 1,805 modules, JS 631.19 kB / gzip 210.20 kB; bundle-size warning only. |
| `make evaluate` | **PASS** | 100 queries, all recorded violations/failures 0; chatbot acceptance 369 assertions, failures 0. |
| Playwright matrix | **PASS** | 24 pass, 36 intentional skips, 0 fail across iPhone, Pixel, 1366px and 1920px profiles. |
| Local in-app browser | **PASS** | Desktop/mobile/Arabic RTL plus fixed address, chat carousel/card, navigation, KDH/ranking, options/cart/review/handoff. Not public-browser evidence. |
| Python 3.9 AST | **PASS** | 129 source files, parse failures 0. |
| Post-cache-exclusion archive target | **PASS** | 34 tests; archive contract 353 members and 3,630,171 bytes. |
| Provisional transport/deploy regression | **PASS** | 79 focused tests; Ruff, Bash syntax and diff check passed. Archive was streamed in bounded SSH chunks, and marker write/success-branch regressions were fixed before the successful attempt. |

### ORACLE-OCI

| Check | Result | Boundary |
|---|---:|---|
| Active catalog/import | **PASS** | `yogiyo-public-web:20260814:yobi-diverse-merchant-selection-v2:8a9d54b7230a`; import `yogiyo_20260814_8a9d54b7230ad6c8`. |
| Active knowledge/family | **PASS** | `external-knowledge-fe97d5a7bf7205681f75aeb5`; `external-recommendation-fe97d5a7bf7205681f75aeb5-78909a764a-5515c9c687`. |
| Active support/ranking | **PASS** | Support manifest `78909a764a01935850f615cd5f35bc8095e16455ea8fcc8611bb3dcebb94111`; ranking hash `5515c9c6877641a111e29ba418890b166b84374101877005749257eae826e191`. |
| Isolated structured-model probe | **PASS** | GPT-OSS 120b, cap 2,048, 6,663.421 ms, 2,077 response bytes, frozen order preserved. Caps 1,024/1,536 failed grounding and were rejected. |
| Isolated bounded-concurrency probe | **PASS** | Three successes under provider semaphore 2: 8,701.317 / 10,123.580 / 14,957.480 ms; 14,960.069 ms wall time. Historical capacity evidence, separate from the operator-approved quality-five acceptance. |
| Final recommendation quality | **PASS** | Exactly five requests: 5/5 valid, median 7,336.520 ms, max 7,860.266 ms, three menus/three merchants and 12 evidence passages in every case; no percentile claim. |

### PUBLIC API

| Check | Observed result | Boundary |
|---|---:|---|
| Provisional health/readiness/root/demo QR | HTTP 200 | Active `20260816T034237Z-e9417303ad55` |
| Protected demo status without token | HTTP 403 | Active provisional application |
| Source/recommendation readiness | both `true` | Active external data family on the provisional application |
| Final release public API | **PASS** | Health/readiness/root/demo QR 200, protected route 403, Oracle external source/recommendation readiness true |

### PUBLIC BROWSER

| Check | Result | Boundary |
|---|---:|---|
| Local UI/browser matrix | **PASS** | Recorded under LOCAL only |
| Provisional public welcome/address | **PASS** | Combined welcome+locale rendered; `Get started!` navigated to the fixed-address screen on the active provisional release |
| Final public UI | **PASS** | Automated browser rechecked welcome+locale/start; user independently observed recommendation results; internal criteria/evidence/order correctness is recorded by quality-five |

The public UI ends at a Yogiyo handoff mock. It does not prove a real cart transfer,
payment or order. The backend synthetic checkout/order remains deployment-smoke
evidence only.

### Initial public baseline (historical diagnostic snapshot)

| Check | Observed result | Boundary |
|---|---:|---|
| Public health/readiness/demo QR | HTTP 200 | Pre-recovery public release only |
| Protected demo status without token | HTTP 403 | Existing public release only |
| Catalog mode | `EXTERNAL_SOURCE`, `YOGIYO_PUBLIC_WEB` | Public-web import, not a live Yogiyo API |
| External counts | 200 merchants; 15,085 menus; 31,293 option groups; 208,513 option items | Existing public Oracle readiness payload |
| Active recommendation knowledge | 0 concepts, relations, closure rows, claims, documents, chunks, and mappings; 15,085 `UNMAPPED` | Critical baseline gap; legacy readiness was insufficient |
| NSG | TCP 22 ingress `0`; existing TCP 80 ingress `1` | Read-only query; no rule changed |

### Detailed local-mirror and focused-test history

| Command/check | Result | What it proves |
|---|---:|---|
| External knowledge builder apply + verify on the 15,085-menu SQLite mirror | **PASS** | 114 concepts/documents, 1,299 chunks, 1,955 high mappings, 15,085/15,085 classifications, 1,073 support rows, zero invented source-specific fact rows; local mirror only |
| Staged builder + deploy safety + failure-injection targeted suite | **PASS — 40 tests in 6.85s** | Migration `012`/staged CLI/order text contract; stage pointer invariance; atomic data-pointer activation rollback; post-symlink three-pointer restoration model; exact ready gates; forbidden archive members |
| Current combined release/deploy/seed/performance/structured-smoke target | **PASS — 77 tests, 1 Starlette deprecation warning, in 43.45s** | Includes exact `001`–`012`, staged pointer/activation and failure injection, archive rejection, seed manifest parity, honest per-scenario performance reporting, dynamic required-option selection, and fresh-SQLite normal HTTP order plus isolated `force_genai_timeout` fallback runs. This is source/SQLite/fake-normal-provider proof, not live Oracle/provider/public proof. |
| Executable structured normal-order/fallback target | **PASS — 3 tests, 1 Starlette deprecation warning, in 30.44s** | A grounded fake normal provider drove the actual HTTP smoke through dynamic recommendation/menu/options/cart/fixed-address/delivery/confirm/mock-success/`CONFIRMED` order and verified profile-graph cleanup; a separate real SQLite service run preserved frozen top-three order and dispatch `1` under isolated timeout. Deploy ordering records `structured` only after both scripts. Live Oracle/OCI remains pending. |
| Whole-source MyPy (`backend/app backend/evaluation scripts`) | **PASS — 83 source files** | Includes the staged builder and both structured smoke scripts after locale-aware fallback signature synchronization; static typing only, no Oracle/provider execution. |
| Synthetic SQLite/Oracle seed support-manifest parity target | **PASS — 31 tests in 10.83s** | Shared reviewed `SYNTHETIC_WIKI`/public-chunk support compiler, cited-evidence checks, exact manifest and ranking v1 identity, Oracle wrapper wiring, transaction/FK regressions; no live Oracle execution |
| Seed parity plus performance-harness reporting target | **PASS — 33 tests in 9.55s** | The preceding 31 seed checks plus reduced-sample no-percentile behavior and per-scenario gates that can fail even when an aggregate passes |
| Earlier focused bootstrap/catalog/knowledge/recommendation-release/migration/release-state checkpoint (10 test files) | **PASS — 69 tests in 37.95s** | Recorded before the final staged-deploy ordering edits. Useful as an integration checkpoint, but not current proof for files changed afterward and not Oracle/live-service proof. |
| `python -m py_compile` for five edited release scripts, the deploy gate helper, and three targeted test modules | **PASS** | Current Python syntax for the staged release/deploy verification scope |
| Ruff on the same release/deploy target | **PASS** | Current focused release-tool and targeted-test lint only |
| `bash -n` on deploy, guarded-ingress, remote-rollback, and release-rehearsal scripts | **PASS** | Shell parse only; no archive upload, OCI mutation, or rollback execution |
| Sanitized deployment preflight | **PASS — read-only** | Required local CLIs/build/knowledge/env example/key, 12 migrations ending in `012`, and release helper executables present; configured OCI profile had two subscribed regions, one running target, TCP 22 `0`, TCP 80 `1`; public baseline health/readiness/shell `200`, protected route `403`. No candidate upload or OCI mutation. |
| Active-family `--verify-only` on the staged-release SQLite mirror | **PASS** | The staged builder output has an active family with matching support/ranking digests, 15,085 classifications, 1,955 high-confidence mappings, 1,073 support rows, and all release-scoped integrity checks true; local mirror only |
| Staged query-plan gate on the 15,085-menu SQLite mirror | **PASS** | Aggregate-only output: 1,762 eligible menus/160 merchants, bound 24, 28 plan operators, 10 index accesses, four expected core indexes used; `menu.*` absent and all shape checks true. SQLite has no row estimates; actual Oracle `EXPLAIN PLAN` remains pending. |
| Transitional per-scenario reduced repository smoke (`warm=1` each, `cold=1`) | **INCONCLUSIVE by design; exit 0** | Parity failures 0. Preview/retrieval wall time was single 52.985/300.370 ms, multi-category AND 57.078/305.432 ms, and price-only 1,212.697/1,434.990 ms; NO_MATCH was 18.970 ms and process-cold single was 52.580/300.088 ms. This isolated the then-current price-only objective-SQL outlier before the exact-only fix. Cardinalities were single 1,192/149, multi 830/132, price 800/129, NO_MATCH 0/0; positive final candidates/merchants/chunks were 3/3/9. Sample count 1, therefore no percentile claim. |
| Pre-optimization formal repository performance gate (`warm=100` aggregate, `process-cold=20`) on the same SQLite mirror | **FAIL — exit 1** | Preview parity failures 0. Warm preview median/P95/max was 78.084/1,453.197/2,485.401 ms, so P95 exceeded the 500 ms gate. Warm retrieval P95 1,679.755 ms, NO_MATCH P95 37.952 ms, and process-cold retrieval P95 1,428.923 ms passed their 2 s/2 s/3 s limits. This run exposed the eager capability scan and aggregate-only scenario reporting; the optimized per-scenario retest is required. Cold means a new process with DB cache unspecified; no OCI/provider path was run. |
| Fixed-source formal per-scenario repository gate (`warm=100` each; 300 aggregate, `process-cold=20`) | **PASS — exit 0** | Aggregate preview median/P95/max 121.790/397.019/1,111.366 ms; retrieval 594.017/1,643.525/3,522.458 ms; NO_MATCH 41.814/145.925/375.443 ms; parity failures 0. Single preview/retrieval P95 was 427.795/1,498.342 ms, multi-category AND 383.992/1,696.977 ms, and price-only 393.983/1,643.525 ms, so every individual 500 ms/2 s gate passed. Process-cold preview/retrieval P95 was 91.406/378.589 ms with DB cache unspecified. SQLite mirror only; no OCI/provider path. |

The fixed-source formal repository command was:

```bash
DEMO_DB_BACKEND=sqlite SQLITE_PATH=/tmp/yobi-concept-test-subagent.db \
  .venv/bin/python scripts/recommendation_performance_smoke.py \
  --repository-only --warm-samples 100 --cold-samples 20 \
  --full-samples 1 --concurrency 1
```

Its sanitized positive-scenario JSON represented these independent samples (all
times milliseconds; `median/P95/max`):

| Scenario | Preview | Retrieval | Eligible menus/merchants | Final menus/merchants/chunks |
|---|---:|---:|---:|---:|
| single | 112.320 / 427.795 / 1,082.372 | 539.048 / 1,498.342 / 2,171.569 | 1,192 / 149 | 3 / 3 / 9 |
| multi-category AND | 129.538 / 383.992 / 697.709 | 547.925 / 1,696.977 / 2,545.410 | 830 / 132 | 3 / 3 / 9 |
| price-only | 122.924 / 393.983 / 1,111.366 | 682.478 / 1,643.525 / 3,522.458 | 800 / 129 | 3 / 3 / 9 |
| NO_MATCH | 41.814 / 145.925 / 375.443 | not run | 0 / 0 | 0 / 0 / 0 |

The aggregate warm count is 300 because each positive scenario has 100 samples;
the process-cold aggregate has 20 independent Python processes and is labelled
`process-cold/db-cache-unspecified`. No raw SQL, row IDs, release IDs, DSN, or
provider response is present in this evidence.

### OCI candidate and recovery chronology

These are historical failures of this release effort. Their partial gate passes do
not count as final rehearsal evidence.

| Candidate application ID | Observed stop | Recovery evidence |
|---|---|---|
| `20260815T231001Z-b32f68c7353f` | Staged Oracle plan rejected a covering index as insufficient table-access proof | No ready marker; old app health 200 and temporary readiness 503; exact temporary SSH rule removed |
| `20260815T231426Z-64ea3e65938c` | Plan/source/structured normal+fallback passed; performance failed with `DPY-4008` invalid bind | No ready marker; this application/data checkpoint became the verified recovery, public health/readiness 200; exact temporary SSH rule removed |
| `20260815T232437Z-50c1721d66b5` | Bind fixed; plan/source/structured passed; performance stopped at `PERFORMANCE_NORMAL_RECOMMENDATION_REQUIRED` after a provider rate-limit sample | Automatic rollback restored `20260815T231426Z-64ea3e65938c`; no ready marker; exact temporary SSH rule removed |
| `20260816T031853Z-e469d49d03b0` | Provisional plan/source/structured passed; non-portable marker write failed | Automatic rollback restored recovery; temporary LB/flow-log resources removed; TCP 22=0 |
| `20260816T032847Z-2d9eab12f72a` | Provisional plan/source/structured passed; inverted marker-success branch returned failure | Automatic rollback restored recovery; temporary LB/flow-log resources removed; TCP 22=0 |
| `20260816T034237Z-e9417303ad55` | **ACTIVE PROVISIONAL** — plan/source/structured normal+fallback passed; performance explicitly deferred | Ready+provisional markers written; public API and welcome→address browser checks passed; temporary resources absent; TCP 22=0/TCP 80=1 |

After these attempts the Oracle bind contract was fixed by binding
`selected_category_count` only when subjective selections exist. The structured
provider policy was then fixed at GPT-OSS 120b, one dispatch, no automatic retry or
model fallback, output cap 2,048 and provider concurrency 2. The release harness now
counts exactly 30 normal requests, reuses the scenario session, spaces starts by 65
seconds outside measured latency and runs an independent barrier concurrency-3 gate.

### Historical required final evidence (closed for that checkpoint)

| Gate | Current status | Required result before `PASS` |
|---|---:|---|
| Full backend/frontend/unit/E2E regression | `PASS — LOCAL` | `make test`, build, evaluation, Playwright and browser evidence are recorded above |
| Local recommendation performance | `PASS — SQLite mirror only` | Fixed-source warm 100 per positive scenario and process-cold 20 passed aggregate and individual preview/retrieval/NO_MATCH gates with parity failures 0; Oracle plan and OCI full-path proof remain separate |
| Oracle apply/release verification | `PASS — ORACLE-OCI data checkpoint` | Migration `012`, non-empty active knowledge/support/ranking family and recovery pointers are recorded; final post-redeploy readback remains below |
| OCI recommendation quality | **PASS — 5/5** | English/Korean single, multi-AND, price-only and repeat stability passed; no percentile claim from five samples |
| Standard deploy/backend smoke | **PASS** | Plan/source/structured normal+fallback passed on the active release; quality-five evidence was then bound to its final marker |
| Rollback safety | **PASS** | Earlier failed candidates repeatedly restored the verified predecessor; the user approved concise promotion rather than another artificial rollback/redeploy cycle |
| Final active application | **PASS** | `20260816T034237Z-e9417303ad55`; active knowledge/recommendation identities unchanged and ready |
| Final public browser | **PASS** | Final welcome+locale/start UI rechecked; user observed recommendation results; five-case HTTP gate covers the internal recommendation contract |
| Final network state | **PASS** | TCP 22 `0`, TCP 80 unchanged at `1`, temporary LB count restored |

## 2026-08-12 structured recommendation — deployed verification

This section records the deployed-source contract, local regression results, live
Oracle/OCI checks, public product verification, and rollback rehearsal for release
`20260812T141008Z-8418f92b7e37`.

### Implemented source contract

| Boundary | Current source contract | Evidence status |
|---|---|---|
| User flow | Confirmed profile/address → structured multi-select → result buttons → existing order flow; no recommendation composer | Local React/API implementation and focused tests |
| Selection | Same category `OR`; non-empty subjective categories express cross-category `AND`; stable catalog codes and localized labels | Local structural/domain/frontend contract; semantic passage fit needs provider/golden-set evaluation |
| Dietary scope | Explicit halal-certification and vegan choices only; no public v2 allergy filter or safety guarantee | Local domain/UI/API contract |
| Spice | Reviewed menu maximum and KR/US reference examples use `1..5` | Local seed/domain/frontend contract |
| Eligibility | Merchant service area, menu availability, base price, maximum spice, valid halal scope, confirmed vegan conflict, and similar-history exclusion are server owned | SQLite regression plus live Oracle structured smoke |
| Retrieval | Per-value exact/essential, lexical, and vector ranks are fused; bounded raw hits require real category coverage, while a lower-weight profile query cannot count as evidence | SQLite deterministic contract plus successful live Oracle `VECTOR_DISTANCE` execution |
| Generation | One no-tool/no-continuation dispatch chooses final pool menus and explanations; valid model order is preserved | Fake-provider contract plus live OCI normal result with one dispatch and grounded evidence IDs |
| Replay | Request ledger prevents duplicate dispatch; post-dispatch uncertainty does not auto-redispatch | Local repository/service contract |
| Data | 60 synthetic merchants, 600 menus, 100 categories, 102 Wiki documents, 345 essential claims, 918 prose paragraphs, and 1,263 total chunks | Compiler/seed contract and live Oracle readiness |
| Migration package | Additive/checksum migration set `001`–`010` | Exact ten-row live Oracle ledger verified |

The release family foreign-keys its knowledge release and stores versioned
catalog/preference/spice/certification/embedding identities. Independent immutable
catalog/certification manifest tables are not part of this implementation; readiness
validates the compatible seeded state and active family represented by those stored
identities. The live rollback rehearsal proves this implemented pointer boundary, not
a stronger external manifest registry.

The prose-first Wiki keeps 245 ingredient and 100 preparation essential claims.
Subjective material is represented by 918 natural paragraphs; the total 1,263 chunks
combine those paragraphs with 345 readable essential-fact chunks. Legacy allergy
tables/identifiers remain for storage compatibility but are excluded from the public
v2 recommendation context and acceptance contract. Reviews and merchant promotional
prose remain synthetic display data with recommendation and grounding weight `0`.

### Completed local checks

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
| Full backend Pytest | **PASS — 392 tests; 1 StarletteDeprecationWarning; 264.72s** | Whole local SQLite/backend regression for the deployed source |
| Whole-tree Ruff | **PASS** | Backend, tests, scripts, and deployment-source lint contract |
| Whole-source MyPy | **PASS — 69 source files** | Static type contract only; no live Oracle/provider execution |
| Frontend Vitest | **PASS — 19/19 tests** | Structured selector/result/API/order component contracts |
| Frontend production build | **PASS** | TypeScript and Vite compilation of the current structured UI; the existing chunk-size warning is non-fatal |
| Local Playwright on dedicated ports `15173/18000` | **PASS — 20 tests; 24 intentional duplicate-viewport skips; 34.8s** | iPhone core structured flow 11/11 plus Pixel 7, 1366×768, and 1920×1080 core paths; local browser evidence only |
| Structured backend MyPy | **PASS — 7 source files** | SQLite/Oracle/service type consistency after the post-review hardening; no Oracle connection, SQL execution, or vector result |

The first default-port browser launch could not start because port `5173` was already
held by a CashFlow application SSH forward. The same YOBI checkout passed on isolated
ports `15173/18000`; the default-port attempt is therefore an environment collision,
not a YOBI test failure. The production build retained its existing non-fatal
546.57 kB chunk warning.

Local Playwright alone does not prove the public site or live OCI provider; the live
checks below provide that separate evidence. Fake-provider and live dispatch checks
prove application behavior and structural ID grounding, not general semantic
entailment of every generated sentence. The current validator is not a general
natural-language entailment detector.

For subjective categories, current tests prove selected-code validation and per-
category evidence-reference coverage. They do not prove that every best-scoring
passage semantically entails its category. Normal-result cross-category `AND` quality
and `NO_MATCH` judgment therefore remain live-provider/golden-set evaluation work;
`SEARCH_FALLBACK` is intentionally only a labelled proximity result.

### Live Oracle, OCI, public, and rollback evidence

| Live gate | Result | Recorded evidence |
|---|---:|---|
| Active application | **PASS** | Release `20260812T141008Z-8418f92b7e37`; `yobi-api` and Nginx active; local and public health/readiness HTTP 200 |
| Oracle migration ledger | **PASS** | Exact checksum ledger `001`–`010`; migration `010` present |
| Knowledge readiness | **PASS** | Active release `knowledge-demo-319f456f7f388f32a1c965b0`; 102 concepts, 100 relations, 281 closure rows, 345 claims, 102 documents, 1,263 chunks, and 600 menu mappings |
| Recommendation family | **PASS** | Active family `structured-rag-v1:6ec5c99c2427c61e`; 44 preference options (40 active), 10 spice references, and 18 halal certification rows |
| Oracle retrieval | **PASS** | Representative live `VECTOR_DISTANCE` SQL executed successfully against the active public Wiki corpus |
| OCI generation | **PASS** | Normal structured recommendation returned three grounded results in one dispatch; replay kept `dispatch_count=1` and the same terminal ledger result |
| Public API smoke | **PASS** | Health, grounded evidence IDs, cart, OCR address, delivery, mock payment, and mock order completed |
| Public browser E2E | **PASS — 20 tests; 24 intentional project/viewport skips; 3.3m** | iPhone primary and localization plus Pixel 7, 1366×768, and 1920×1080 structured and order flows |
| Protected route | **PASS** | Unauthenticated demo-status request returned HTTP 403 |
| Rollback rehearsal | **PASS** | `20260812T135301Z-15c46e374baa` rolled back to `20260812T134353Z-8c07647f5fe8`; health/readiness and active data pointers passed; additive migrations remained; a newer release was then deployed and verified |

The runtime pins generation limits of 131,072 input bytes and 4,096 output tokens for
the deployed Grok request envelope. Oracle JSON payloads are canonicalized before
snapshot persistence. The final active release's recorded immediate predecessor is
`20260812T135513Z-8f91a6c7120a`.

The approved temporary current-source `/32` TCP 22 rule used for the deployment window
was removed by exact rule ID after all remote checks. The final independent NSG query
returned TCP 22 rule count `0` and retained the existing TCP 80 rule count `1`.

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
