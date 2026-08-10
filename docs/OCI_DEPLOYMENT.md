# OCI deployment

The existing `yobi-app-01` VM and private `yobi-adb` are reused. Scripts resolve
current identifiers and the ephemeral public IP at runtime; none are stored in Git.

Verified 2026-08-09 deployment: release `20260809T084353Z-704f74712d9d` is active,
the exact migration ledger is `001`–`008`, and the trusted rollback target is
`20260809T083629Z-bfb59275b93f`. Public readiness, the configured product E2E suite,
and three consecutive Primary runs passed. The approved temporary current-source
`/32` TCP 22 rules were removed after every SSH window; the final independent NSG
state is TCP 22 `0`, existing TCP 80 `1`. See `TEST_REPORT.md` for exact data and
GenAI smoke evidence.

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
`001`–`009`), and writes the protected runtime environment before any GenAI smoke
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

The primary smoke performs only the required function-call and continuation requests.
It honors `Retry-After`, otherwise waits 65–70 seconds plus jitter, and retries at most
twice. A separate checkpoint verifies `openai.gpt-oss-120b`. Errors expose only a safe
HTTP category, never the key, full response, or chained provider body. Prewarm checks
the database, retrieval, and explanation cache without making another GenAI request.

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
fails early unless every immutable/additive migration `001`–`008` and the knowledge
authoring directory are present. The archive SHA-256 becomes part of the release ID;
the VM verifies the uploaded checksum and records it in a release manifest before
installation. Each transfer uses a release-and-nonce-specific file under the SSH
user's home rather than a shared fixed `/tmp` name. The remote side validates the
exact path, owner, non-writable mode, and checksum, and removes that exact upload on
success or failure.
Deployment applies only checksum-safe
pending migrations, performs an idempotent seed upsert, switches the symlink, and
requires the exact eight-row migration ledger, current symlink, health, and readiness.
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
every migration known to the release. Oracle DDL commits implicitly, so `005`–`008`
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
additive `005`–`008` schema, or delete either knowledge release.

A genuinely historical v1 target with no knowledge manager/state takes the explicit
legacy compatibility path and leaves the current knowledge pointer untouched. This
only verifies compatibility with the current additive schema and current demo runtime.
It is not a general rollback guarantee: a future incompatible global configuration,
base catalog rewrite, destructive migration, or other non-release-scoped state change
requires a separately designed and verified snapshot/restore contract before rollout.
A legacy root-owned `/opt/yobi/shared/previous_release` may be read only as a validated
fallback; all new writes go to the protected control path.

## Chatbot-improvement deployment gate

Do not deploy the chatbot revision until the local full backend suite, chatbot
acceptance runner, frontend lint/test/build, and local product E2E all pass. The
required commands and evidence fields are listed in
`CHATBOT_IMPROVEMENT_IMPLEMENTATION.md` and `TEST_REPORT.md`.

Migration/seed activation for this revision must establish all of the following in
one release window:

- `SCHEMA_MIGRATION` contains checksum-verified `005`, `006`, `007`, and `008` in addition
  to immutable `001`–`004`;
- the new catalog version is active and all 150 menus have a `MAPPED` concept row;
- the active `KNOWLEDGE_RELEASE` is `READY`, its expected and actual graph counts
  exactly match the six observed release-scoped tables, its manifest/corpus ID match
  the running code, and no active knowledge chunk vector is null;
- supplemental release counts are exactly 150 menu mappings, 30 origin declarations,
  266 merchant ingredients, and 4 option effects;
- the active knowledge embedding model, dimension, and version match the runtime
  embedding provider; every menu vector has the same runtime metadata; chunk metadata
  matches the release; and required option min/max/availability cardinality is valid;
- catalog, profiles, carts, checkouts, mock orders, and prior migration records were
  not deleted to make the seed pass.

`/readyz` is the public safe summary of these checks. A 200 `/healthz` with a 503
`/readyz` is a failed activation, not a degraded success. Record the release ID,
catalog version, active knowledge release/embedding metadata, and safe count summary
in `TEST_REPORT.md`; never paste a DSN, OCID, public IP, credential, or endpoint ID.

After activation, verify ordinary free-form conversation separately from the fixed
demo shortcuts: `hi` produces no recommendation card, accumulated needs trigger the
readiness gate, snapshot selection survives reload, a grounded explanation separates
Wiki/menu/unknown facts, and the existing option/cart/Mock payment/order flow still
completes. Then run the Primary Demo on the same public release three consecutive
times and check the unauthenticated demo-control boundary remains HTTP 403.

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
that infrastructure change has been separately approved. An unreachable target is a
deployment blocker, not permission to broaden ingress.

On the VM:

```bash
sudo systemctl status yobi-api nginx
sudo journalctl -u yobi-api --since "10 minutes ago"
curl --fail http://127.0.0.1/readyz
sudo /opt/yobi/current/deploy/rollback.sh
```
