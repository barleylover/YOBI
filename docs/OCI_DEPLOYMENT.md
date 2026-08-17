# OCI deployment

The existing `yobi-app-01` VM and private `yobi-adb` are reused. Scripts resolve
current identifiers and the ephemeral public IP at runtime; none are stored in Git.

## 2026-08-17 expanded knowledge/UI release (final active)

The concise final deployment used the guarded temporary Bastion transport and the
standard one-way release workflow. Application `20260816T201131Z-29fbc2f9fd32`
(UTC identifier, deployed 2026-08-17 KST) is active with archive SHA-256
`29fbc2f9fd325e7c4e15c88a5abde9c8c12b7f5bdfb394fa50a5de244757fa25`.

Current active identities and counts:

- catalog `yogiyo-public-web:20260814:yobi-diverse-merchant-selection-v2:8a9d54b7230a`
- knowledge `external-knowledge-0ffd2f53ba2e2539ee9c5a27`
- recommendation family
  `external-recommendation-0ffd2f53ba2e2539ee9c5a27-71a41f074c-5515c9c687`
- support manifest
  `71a41f074cb7fa0693b2d92009bcdf708ac0a335a08802171c5f1a408066d5f4`
- 198 concepts/documents, 1,551 chunks, 3,922 high-confidence mapped menus,
  1,499 reviewed preference-support rows, and exact 15,085-menu classification
- preference catalog `preference-catalog-2026.08.17-v3`

The expanded-cuisine acceptance had already executed exactly five provider calls.
Four normal results passed; the Italian call returned three valid server-frozen menus
through the safety fallback and exposed a missing-evidence serialization defect. That
deterministic defect was fixed and verified in SQLite and live Oracle without another
provider request. The final deployment therefore skipped normal generation and ran
only staged/active Oracle plan, source integrity, an isolated Italian fallback, the
immutable reviewed-five evidence check, and health/readiness. Its provider dispatch
count was zero.

The final standard deploy passed and wrote both reviewed quality and ready markers.
Public root/health/readiness/QR/catalog returned 200, protected demo status returned
403, and browser verification found all seven cuisine buttons with no horizontal
overflow. The generated browser-smoke profile/session was deleted. Cleanup verified
the temporary Bastion path absent, TCP 22 ingress 0, TCP 80 unchanged, and temporary
LB/NLB counts at baseline.

Detailed evidence is in
[`evidence/KNOWLEDGE_EXPANSION_20260817.md`](evidence/KNOWLEDGE_EXPANSION_20260817.md).

## Historical 2026-08-16 external recommendation release (superseded)

The section below records the predecessor and earlier transport chronology. Its
application/data IDs are not current.

The initial public baseline was healthy in `EXTERNAL_SOURCE` mode with 200 merchants
and 15,085 menus but had zero active menu-to-Wiki mappings and support rows. Migration
`012` and the external knowledge/support/ranking data family have since been applied
to Oracle. The operator first selected a provisional deployment, then explicitly
replaced the former 30-request/concurrency-3 gate with focused five-case quality
acceptance. Application
`20260816T034237Z-e9417303ad55` is final active after query-plan,
source-integrity, normal structured order, isolated fallback and the
operator-approved five-case quality gate passed. The provisional marker was removed
only after the five-case evidence was validated and a final quality marker was
written.

Current active data identities are:

- catalog `yogiyo-public-web:20260814:yobi-diverse-merchant-selection-v2:8a9d54b7230a`
- import `yogiyo_20260814_8a9d54b7230ad6c8`
- knowledge `external-knowledge-fe97d5a7bf7205681f75aeb5`
- recommendation family
  `external-recommendation-fe97d5a7bf7205681f75aeb5-78909a764a-5515c9c687`
- support manifest
  `78909a764a01935850f615cd5f35bc8095e16455ea8fcc8611bb3dcebb94111`
- ranking policy hash
  `5515c9c6877641a111e29ba418890b166b84374101877005749257eae826e191`

### Candidate failure and recovery history

| Candidate application ID | Failed gate/cause | Recovery result |
|---|---|---|
| `20260815T231001Z-b32f68c7353f` | Staged Oracle plan did not accept a covering index as table proof | No ready marker; old app health 200, temporary ready 503; exact SSH rule cleanup |
| `20260815T231426Z-64ea3e65938c` | Plan/source/structured normal+fallback passed; performance hit `DPY-4008` invalid bind | No ready marker; app/data recovery became active; public health/readiness 200; exact SSH rule cleanup |
| `20260815T232437Z-50c1721d66b5` | Bind fixed; plan/source/structured passed; performance hit `PERFORMANCE_NORMAL_RECOMMENDATION_REQUIRED` with a provider rate-limit sample | Automatic rollback restored `20260815T231426Z-64ea3e65938c`; no ready marker; exact SSH rule cleanup |
| `20260816T031853Z-e469d49d03b0` | Provisional three-gate sequence passed; provisional marker used an unsupported `/dev/stdin` install source | Automatic rollback restored recovery; temporary LB/flow-log resources removed; TCP 22 returned to 0 |
| `20260816T032847Z-2d9eab12f72a` | Provisional three-gate sequence passed; inverted shell success condition treated marker success as failure | Automatic rollback restored recovery; temporary LB/flow-log resources removed; TCP 22 returned to 0 |
| `20260816T034237Z-e9417303ad55` | **FINAL ACTIVE**; plan/source/structured normal+fallback and five-case quality passed | Final quality marker references evidence SHA-256 `868d35c331de63f4de3b600fd68e0628a3a2e26dd009f038b4a968adaad006a3`; public API/browser checked; temporary resources absent; TCP 22=0, TCP 80 unchanged=1 |

The invalid bind is fixed by omitting `selected_category_count` unless subjective
selections are present. The explanation model is now `openai.gpt-oss-120b` with one
dispatch, no automatic retry/model fallback, output cap 2,048 and provider concurrency
2. An isolated full-prompt probe completed in 6,663.421 ms and a three-request probe
under the concurrency-2 semaphore completed with three successes in 14,960.069 ms.
The user subsequently replaced the 30-request statistical benchmark with exactly five
focused quality cases. They passed 5/5 with median 7,336.520 ms and max 7,860.266 ms;
no percentile is claimed.

### Evidence partitions and final placeholders

| Partition | Current evidence | Required closure |
|---|---|---|
| `LOCAL` | Full test/build/evaluation, Playwright, local browser and archive contract PASS | Closed locally; see `TEST_REPORT.md` |
| `ORACLE-OCI` | Migration/data identities and plan/source/structured/five-case quality gates PASS | Closed |
| `PUBLIC API` | Final health/readiness/root/demo QR 200, protected route 403 | Closed |
| `PUBLIC BROWSER` | Final combined welcome+locale/start UI passed; user observed recommendation results | Closed with internal recommendation correctness covered by the five-case HTTP gate |

- final application `20260816T034237Z-e9417303ad55`
- quality-five evidence 5/5 PASS; no statistical percentile claim
- final network readback TCP 22=0, TCP 80=1, temporary LB count restored

Before the final rehearsal, retain the recorded local source gates and rerun any gate
whose source changed:

```bash
make test
make build
.venv/bin/python scripts/recommendation_performance_smoke.py --repository-only
bash -n deploy/deploy.sh deploy/with_temporary_ssh_ingress.sh \
  deploy/run_remote_rollback.sh deploy/release_rehearsal.sh
```

The initial read-only preflight found the required local CLIs, built frontend,
knowledge sources, runtime example, OCI profile, SSH key, exactly 12 migrations with
`012` last, and all release helper executables. The configured profile exposed two
subscribed regions; target discovery found one running instance, TCP 22 count `0`,
TCP 80 count `1`, and the existing public baseline returned health/readiness/shell
`200` plus protected-route `403`. This remains a sanitized historical baseline; it
does not prove the final candidate or final public browser flow.

The guarded SSH VM access window below resolves (but
never prints) the current source IPv4, adds one exact `/32` TCP 22 NSG rule, runs the
given command, removes that exact rule ID on success/error/signal exit, and then
independently requires TCP 22 count `0` and the original TCP 80 count unchanged. It
fails closed if TCP 22 was already open or TCP 80 was not exactly the expected single
rule. `YOBI_DEPLOY_SOURCE_CIDR` may be set only to an explicitly verified IPv4 `/32`;
never use a broader CIDR.

For an ordinary one-way deployment the command is
`./deploy/with_temporary_ssh_ingress.sh ./deploy/deploy.sh`. The required final gate
uses the rehearsal orchestrator below so candidate deploy, public checks, rollback,
predecessor checks, a minimum two-second separation, identical-source final redeploy,
and final public checks all occur inside one `/32` window. If a public check fails
after activation, the orchestrator attempts to restore the verified predecessor
before returning failure; the outer wrapper still removes SSH access and recounts the
NSG on every exit.

```bash
./deploy/with_temporary_ssh_ingress.sh ./deploy/release_rehearsal.sh
```

Two archive transfers and a later plain SSH probe ended with the connection closed or
timed out after roughly 75–80 seconds; each exact temporary ingress rule was removed
and the recovery release remained active. Cache exclusions reduced the verified
archive to 353 members and 3,630,171 bytes, so the latest failure was not attributed
to archive size. A different transport may be used only if it runs the same remote
gate/rollback contract and leaves equivalent sanitized evidence. Transport readiness
and the final rehearsal remain `PENDING`; do not broaden TCP 22 ingress.

The standard deploy now enforces all of these steps before its ready marker:

1. build an archive containing exactly migrations `001`–`012` while rejecting
   `.env`, key/wallet paths, `*.db`, `backend/backend`, temporary and cache paths;
2. verify the archive checksum and exact migration ledger on the VM;
3. in external mode run the idempotent builder with `--stage-only`; it loads and
   release-scope verifies the deterministic `READY` knowledge/recommendation family
   while proving both active data pointers are unchanged;
4. run `recommendation_query_plan.py --backend oracle --scope staged --verify`, which
   records only aggregate candidate/merchant and Oracle plan/index estimates (never
   raw SQL, binds, release IDs, DSN, or row IDs), then verify the demo address;
5. prepare/switch the application symlink, run `--activate-staged` to reverify and
   move both data pointers in one transaction, verify exact pointer readback, and
   restart the services;
6. pass the active Oracle plan gate and `catalog_mode.py verify-external`; then run
   `structured_recommendation_smoke.py`, which dynamically selects one active
   externally recommended menu, validates required available options, adds/reprices
   its cart line, applies the fixed demo address and delivery preference, confirms
   the cart, completes a synthetic mock checkout/order, verifies one generation
   dispatch, and cascade-deletes the temporary profile/session/cart/checkout/order;
7. run `structured_fallback_smoke.py` against the same Oracle runtime with a private
   process-local `DemoControl(force_genai_timeout)`. It must preserve the frozen
   server top-three IDs/order, deterministic explanation fields, dispatch count `1`,
   and cleanup without changing the public application's failure mode; then run
   `recommendation_performance_smoke.py --release-gate`; and
8. use the exact four-gate contract helper to reject any omitted/duplicate gate, then
   write the ready marker, otherwise restore the
   previously verified application, knowledge, and recommendation pointers.

The four external gate names remain `query-plan`, `source-integrity`, `structured`,
and `performance`. `structured` is now an umbrella gate that is recorded only after
both the normal order smoke and isolated provider-fallback smoke succeed.

The performance release gate retains the repository same-process warm 100 and
fresh-process cold 20 (`process-cold/db-cache-unspecified`, never a claimed DB-cache
flush). Its provider path measures exactly 30 sequential normal requests; the
SIMILAR seed is the first timed/counted sample and the same session is reused, so no
hidden six-request setup exists. Starts are spaced by 65 seconds outside measured
latency, after a 65-second quiet period, and an independent barrier concurrency-3
gate follows another quiet period. It requires 30/30 `RECOMMENDED`, valid frozen
ranks, no fallback, and zero errors; concurrency requires three successes. It emits
P95/P90 only when the documented sample minimum is met.

`release_rehearsal.sh` verifies public health, readiness, the application shell, and
the unauthenticated protected-route `403` after the candidate, predecessor, and final
release. New-release checks additionally require both
`source_integrity_ready=true` and `recommendation_ready=true`. It never prints the
resolved public address or OCI identifiers.

Run the product/browser E2E on the same final release and record the application,
knowledge/support/ranking family, migration count, performance JSON, rollback target,
final redeployment release, and final NSG counts without copying an IP, DSN, OCID,
endpoint ID, credential, or raw environment line into Git. If the guarded wrapper
reports cleanup failure, stop: do not declare success until an independent read-only
NSG query confirms TCP 22 `0` and TCP 80 `1`.

The 2026-08-16 UI authority ends the visible browser flow at the explicit Yogiyo
handoff mock; it does not expose mock payment success or an order-complete screen.
The backend release smoke above deliberately retains the synthetic checkout/order
API as an integrity regression. This resolves the two document scopes without
claiming that YOBI or Yogiyo placed a real order or transferred a cart.

## Historical 2026-08-12 deployed procedure and evidence

Verified 2026-08-12 deployment: structured-recommendation release
`20260812T141008Z-8418f92b7e37` is active and its recorded rollback predecessor is
`20260812T135513Z-8f91a6c7120a`. The exact migration ledger is `001`–`010`.
Oracle readiness, live vector retrieval, one-dispatch OCI generation, public product
E2E, and a compatible rollback/redeploy rehearsal passed. The approved temporary
current-source `/32` TCP 22 rule was removed by exact rule identity after verification;
the final independent NSG state is TCP 22 `0`, existing TCP 80 `1`. See
`TEST_REPORT.md` for exact data and generation evidence.

The active release contains migrations `001`–`010`, base catalog
`demo-2026.08.11-knowledge-v3`, and knowledge catalog contract
`demo-knowledge-catalog-2026.08.12-v4`. The commands and gates below are the deployed
operational contract; the completed 2026-08-12 evidence is recorded separately in
`TEST_REPORT.md` so future runs do not inherit it without re-verification.

```bash
make test
make build
make deploy
./deploy/run_secure_bootstrap.sh
```

The first run is interactive. Enter the ADB TLS DSN, ADB ADMIN password,
`YOBI_APP` password, OCI Generative AI API-key secret, and a demo-control token. The
script creates the least-privilege app user if absent, applies checksum migrations,
verifies `YOBI_APP` plus every migration packaged in that release (currently
`001`–`010`), and writes the protected runtime environment before any GenAI smoke
request. Verification includes the conversation snapshot/event and knowledge release,
chunk, and runtime-state tables introduced by `005` and `006`. No secret is echoed.

If `/etc/yobi/yobi.env` already exists, do not recreate it. The same resume command
loads the protected file and does not prompt for secrets. It atomically updates only
the non-secret release policies `LLM_MAX_RETRIES="1"` and
`EMBEDDING_PROVIDER="deterministic"` when a legacy file differs or omits either key;
all secret and unrelated lines are preserved and no value is printed. Duplicate
policy entries fail closed. The protected file remains mode `0600`.

Progress is recorded as safe metadata in
`/opt/yobi/shared/control/bootstrap_state.json` (`root:root`, mode `0600`). A transient 429
therefore leaves the database and environment checkpoints complete. Re-running the
same command loads `/etc/yobi/yobi.env`, skips completed steps, and resumes at the
first incomplete smoke/seed/service checkpoint without asking for the secrets again.
The control directory is `root:root` mode `0750`; checkpoint writes use an
unpredictable exclusive temporary file, `fsync`, and atomic replacement. A legacy
root-owned `/opt/yobi/shared/bootstrap_state.json` can be read for resume, but an
untrusted owner, writable file, symlink, or malformed checkpoint fails closed.

The existing primary smoke performs the retained v1 function-call and continuation
requests. It honors `Retry-After`, otherwise waits 65–70 seconds plus jitter, and
retries at most twice. A separate checkpoint verifies `openai.gpt-oss-120b`. Errors
expose only a safe HTTP category, never the key, full response, or chained provider
body. This transport/capability smoke is historical regression coverage; it is not the
structured-v2 one-dispatch recommendation smoke required by the Phase 8 gate below.
Prewarm checks the database, retrieval, and explanation cache without making another
GenAI request.

If the primary smoke remains rate-limited or returns a safe provider error category,
the checkpoint is recorded as `degraded` and bootstrap continues through the GPT-OSS
and deterministic fallback checkpoints. A later resume skips all terminal checkpoints
and verifies seed integrity again without duplicating provider smoke calls.

Important recovery boundary: a run made with the legacy script can be resumed without
secret input only if `/etc/yobi/yobi.env` already exists. If that script exited before
the file was written, restore the file from an operator-controlled secure source; the
terminated process and the provider management API cannot recover secret values.

After secure bootstrap succeeds, run:

```bash
./deploy/enable_http_ingress.sh
```

This adds only the approved `0.0.0.0/0` TCP 80 rule to the existing
`yobi-app-nsg`; it refuses duplicate unexpected state. FastAPI port 8000 is never
opened publicly. VM installation also idempotently enables the HTTP service in
`firewalld` and the SELinux Nginx upstream boolean.

Presentation prewarm from the project root:

```bash
./deploy/run_remote_prewarm.sh
```

This reads the protected runtime environment only on the VM and prints safe readiness
state; secret values are never returned to the local shell.

`deploy/deploy.sh` now builds a release-specific virtual environment before changing
`/opt/yobi/current`. The release archive includes `knowledge/`, the complete
`database/migrations/` directory, and the application/evaluation code. Packaging
fails early unless every immutable/additive migration `001`–`010` and the knowledge
authoring directory are present. The archive SHA-256 becomes part of the release ID;
the VM verifies the uploaded checksum and records it in a release manifest before
installation. Each transfer uses a release-and-nonce-specific file under the SSH
user's home rather than a shared fixed `/tmp` name. The remote side validates the
exact path, owner, non-writable mode, and checksum, and removes that exact upload on
success or failure.
Deployment applies only checksum-safe
pending migrations, performs an idempotent seed upsert, switches the symlink, and
requires the exact ten-row migration ledger, current symlink, health, and readiness.
If any preparation, activation, or metadata step fails after a prior release was
verified, it restores that exact release and rechecks both endpoints. It does not
recreate the VM/ADB, broaden IAM, or repeat secure bootstrap.

Deploy and rollback share the non-blocking root-owned lock
`/run/lock/yobi-deploy.lock` (`0600`). A concurrent operation exits before changing
the database pointer or current symlink. `/opt/yobi`, `/opt/yobi/releases`, and each
current/target release tree are checked as real directories and hardened to
`root:yobi` with no group/world-writable file or directory. The `yobi` service account
can read the release but cannot rewrite code, manifests, helpers, or rollback markers;
systemd has no writable `/opt/yobi/shared` allowance.

Seed generation and all embedding calls finish before catalog DML begins. Base rows,
vectors, the new `LOADING`→`READY` knowledge release, supplemental mappings, runtime
activation, and integrity verification then run in one caller-owned Oracle
transaction with one final commit. Any exception rolls back the whole seed window;
the knowledge loader also rolls back its savepoint and never commits independently,
so the previously active release remains selected. A source-derived release ID may be
reused only with the identical manifest and an already `READY` release.
Changing the embedding provider/model/version for unchanged authored sources therefore
requires an explicit catalog/compiler contract bump. A collision is a failed seed,
not permission to mutate the existing release; active embedding model, dimension, and
version must match the runtime provider before commit/readiness succeeds.

Deployment captures the active knowledge release after Migration `006` is available
and before seed activation. After seed commit it records the new active ID, the prior
ID (including an explicit null state), application release ID, and archive SHA-256 in
`/opt/yobi/shared/control/release-state/<release-id>.json`. This root-owned `0640`
state is written with exclusive temporary creation, `fsync`, atomic replacement, and
owner/mode/symlink validation; the release-local manifest is informational and is not
the rollback authority. If a later deploy step fails, the script first reactivates the
captured prior `READY` release—or explicitly clears `ACTIVE` when none existed—using
bound SQL, an expected-current guard, commit, and readback, then restores and verifies
the prior application release.

Before pending DDL runs, the migration runner validates the filename and checksum of
every migration known to the release. Oracle DDL commits implicitly, so `005`–`010`
are additive and every statement treats its already-created column, table, or
index as a successful resume condition. If a process stops partway through any
migration, no `SCHEMA_MIGRATION` record is written; rerun the same unmodified release
to reconcile the existing objects and complete the ledger record. Never edit an
applied SQL file, manually insert a migration record, or use a different release to
continue a partial migration.

Each healthy release receives `.yobi-release-ready`. After successful activation,
deployment records the exact former current release in
`/opt/yobi/shared/control/previous_release`. The default rollback uses only that recorded,
health-verified target; it does not choose a directory merely because its timestamp
sorts newest. An operator may pass an exact verified release ID when deliberately
choosing another retained release:

```bash
sudo /opt/yobi/current/deploy/rollback.sh
sudo /opt/yobi/current/deploy/rollback.sh 20260809T083629Z-bfb59275b93f
```

For releases that carry the current knowledge contract, rollback reads the target's
root-owned release state and activates its recorded `READY` knowledge release before
switching application code. A target that contains the knowledge manager but lacks
trusted state is rejected. If activation, health/readiness, or rollback metadata fails,
the script restores the original knowledge pointer first, then the original current
symlink, and verifies both endpoints. It does not delete migration rows, remove the
additive `005`–`010` schema, or delete either knowledge release.

A genuinely historical v1 target with no knowledge manager/state takes the explicit
legacy compatibility path and leaves the current knowledge pointer untouched. This
only verifies compatibility with the current additive schema and current demo runtime.
It is not a general rollback guarantee: a future incompatible global configuration,
base catalog rewrite, destructive migration, or other non-release-scoped state change
requires a separately designed and verified snapshot/restore contract before rollout.
A legacy root-owned `/opt/yobi/shared/previous_release` may be read only as a validated
fallback; all new writes go to the protected control path.

## Structured recommendation Phase 8 deployment gate

The current authorities for this gate are
[`STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`](STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md),
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), and
[`TEST_REPORT.md`](TEST_REPORT.md). The historical chatbot acceptance runner and
`CHATBOT_IMPROVEMENT_IMPLEMENTATION.md` remain regression records only; neither can
approve the structured selector and one-dispatch RAG flow.

Do not describe the v2 revision as deployed merely because `make deploy`, the legacy
provider smoke, `/healthz`, or the current `/readyz` succeeds. Before activation, the
full local backend suite, frontend lint/test/build, structured product E2E, migration
and seed checks must pass and be recorded without summing overlapping targeted test
scopes.

### Migration, seed, and release-family evidence

One controlled Oracle release window must establish all of the following:

- `SCHEMA_MIGRATION` is exactly checksum-verified `001`–`010`; migration `010` can
  resume safely after Oracle's implicit DDL commits, without editing its checksum or
  inserting a ledger row manually.
- Base catalog `demo-2026.08.11-knowledge-v3` and knowledge catalog contract
  `demo-knowledge-catalog-2026.08.12-v4` are present. The active `KNOWLEDGE_RELEASE`
  is `READY`, its source-derived ID and 64-character manifest match the running code,
  expected/declared/observed counts agree, and no active chunk vector or embedding
  metadata is missing.
- Release-scoped counts are exactly 102 concepts/documents (`2` cuisine, `30` family,
  `70` variant), 100 relations, 281 closure rows, 345 essential claims, 1,263 chunks,
  600 menu mappings, 13 origin declarations, 120 merchant ingredient rows, and 4
  option effects. Claims are 245 ingredient plus 100 preparation; chunks are 918 prose
  paragraphs plus 345 essential-fact passages.
- Base rows include 60 merchants, 600 menus, 100 categories, 1,202 option groups,
  2,405 option items, 1,200 evidence rows, and 2,400 zero-weight reviews. Required
  option cardinality remains valid. Catalogs, profiles, carts, checkouts, mock orders,
  and earlier migration rows are not deleted to make validation pass.
- The active recommendation family pins that knowledge release, base catalog,
  preference catalog, KR/US spice reference, synthetic certification release, and
  embedding identity. Seed verification observes 44 preference rows of which 40 are
  coverage-enabled, 10 spice references (`KR`/`US` × `1..5`), and 18 active synthetic
  halal certification rows.
- A request reserved before an active-pointer change keeps its original
  `release_family_id` and initial `eligibility_as_of` through pool construction,
  generation, and snapshot provenance. Snapshot commit and later selection still use
  that exact family, but re-check mutable availability, price/service area, and
  certification validity at the current operation time. The proof must exercise
  Oracle, not only the SQLite fixture.

`RECOMMENDATION_RELEASE_FAMILY` has a foreign key to `KNOWLEDGE_RELEASE`; catalog and
certification are pinned version strings rather than independent immutable manifest
tables. The seed transaction validates their compatible expected state and readiness
validates the active family alongside the canonical catalog/knowledge/provider
checks. The 2026-08-12 rollback rehearsal verified the implemented application,
knowledge, and compatible recommendation-family boundary. This must not be described
as proof of a stronger external catalog/certification manifest registry.

### Live Oracle retrieval and generation evidence

- Run representative structured criteria through live Oracle and prove that objective
  merchant service area, menu availability, base price, five-level spice, valid halal scope,
  confirmed vegan conflict, and `SIMILAR` history exclusions execute before retrieval.
- Confirm the real query path uses `VECTOR_DISTANCE(..., COSINE)` plus lexical/alias
  signals against public prose/essential chunks. Record pool membership/provenance and
  golden-set recall; deterministic SQLite vectors are not Oracle semantic-quality
  evidence.
- Run a live structured-v2 recommendation with the configured primary model. One
  application dispatch must choose final pool menu IDs and write explanations in the
  same response, without tools, continuation, automatic retry, or automatic model
  fallback. Preserve valid model order and reject any outside-pool/evidence reference.
- A legacy function-call smoke, a configured-provider `/readyz`, or a degraded primary
  bootstrap checkpoint does not satisfy this gate. The current v2 generator calls only
  its configured primary model; Phase 8 requires an actual normal `RECOMMENDED` result,
  not a public experience that can only return `SEARCH_FALLBACK`.
- Separately rehearse an empty pool, model `NO_MATCH`, invalid/provider failure search
  fallback with no second call, idempotent replay with no extra dispatch, and stale
  `DISPATCHED` recovery to `UNKNOWN_AFTER_DISPATCH` without automatic redispatch.

### Public product and rollback evidence

On the same exact release, run the public mobile and desktop path from profile/address
confirmation through structured selection, recommendation, options, cart, delivery,
mock payment, and mock order:

- no recommendation composer and no `/messages` or `/messages/stream` request from the
  new UI;
- same-category `OR`, cross-category `AND`, only explicit halal/vegan dietary choices,
  no allergy controls or safety claim, and no country/language/religion inference;
- five-level spice with switchable KR/US examples, no current `/3` display;
- model-selected normal results and their Wiki evidence, then button-only choose,
  similar, edit, compare, and evidence actions;
- reload/request recovery, catalog-version conflict, option dietary state, server
  pricing, cart confirmation fingerprint, payment failure/retry, and duplicate-order
  protections; and
- ordinary service copy with one quiet synthetic/order truth statement, never a claim
  that a demo merchant is a real certified restaurant or that a real charge occurred.

Verify `/healthz`, `/readyz`, unauthenticated production demo controls (`403`), Nginx
and systemd, sanitized release-window logs, and the exact active application,
knowledge, recommendation-family, catalog, certification, generation-model, and
embedding identities. Then rehearse rollback. A successful rollback must restore a
compatible application plus both active data pointers, retain additive migrations,
and pass the old release's public regression. Append exact commands, release IDs, and
results to `TEST_REPORT.md`; never paste a DSN, OCID, public IP, credential, API key,
or endpoint ID.

Generation and embedding are independent deployment settings. The default approved
path remains OCI on-demand generation. `GENAI_PROVIDER`, logical generation model,
`OCI_GENAI_SERVING_MODE`, and optional dedicated endpoint references affect only the
generation adapter; `EMBEDDING_PROVIDER`, `OCI_EMBED_MODEL`, and
`OCI_EMBED_DIMENSION` identify retrieval. The current release pins
`EMBEDDING_PROVIDER=deterministic` for both seed and query vectors; `auto` is not a
production default.
Do not provision or select a paid dedicated endpoint without separate approval. A
fake dedicated-adapter contract test is not live dedicated-endpoint evidence.

Production or dedicated `/readyz` validates the required GenAI key, model, HTTPS
base URL/region, endpoint references where applicable, Responses/Function Calling
support, and compatible input/output/tool limits. It returns sanitized
`GENAI_NOT_READY` codes rather than identifiers or credentials when configuration is
invalid.

The repository deploy path requires authenticated VM access. Do not add TCP 22, IAM
policy, a Bastion, or an artifact channel merely to make deployment possible unless
that infrastructure change has been separately approved. When an ephemeral SSH rule
is approved, restrict it to the observed current-source `/32`, record its exact rule
ID, remove that ID after the final remote check, and independently assert that TCP 22
returns to zero without altering the existing TCP 80 rule.

On the VM:

```bash
sudo systemctl status yobi-api nginx
sudo journalctl -u yobi-api --since "10 minutes ago"
curl --fail http://127.0.0.1/readyz
sudo /opt/yobi/current/deploy/rollback.sh
```
