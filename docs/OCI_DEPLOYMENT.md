# OCI deployment

The existing `yobi-app-01` VM and private `yobi-adb` are reused. Scripts resolve
current identifiers and the ephemeral public IP at runtime; none are stored in Git.

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
`001`–`008`), and writes the protected runtime environment before any GenAI smoke
request. Verification includes the conversation snapshot/event and knowledge release,
chunk, and runtime-state tables introduced by `005` and `006`. No secret is echoed.

If `/etc/yobi/yobi.env` already exists, do not recreate it. The same resume command
loads the protected file and does not prompt for secrets. It atomically updates only
the non-secret `LLM_MAX_RETRIES="1"` policy when a legacy file contains `0` or omits
the key; all other lines are preserved and no value is printed. The protected file
remains mode `0600`.

Progress is recorded as safe metadata in
`/opt/yobi/shared/bootstrap_state.json` (`root:root`, mode `0600`). A transient 429
therefore leaves the database and environment checkpoints complete. Re-running the
same command loads `/etc/yobi/yobi.env`, skips completed steps, and resumes at the
first incomplete smoke/seed/service checkpoint without asking for the secrets again.

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
fails early if the `005` conversation migration, `006` knowledge migration, `007`
service-area/idempotency migration, `008` checkout cart-version migration, or
knowledge authoring directory is absent.
Deployment applies only checksum-safe
pending migrations, performs an idempotent seed upsert, switches the symlink, and
requires both health and readiness. If activation fails, it restores the previous
complete release link and restarts the services. It does not recreate the VM/ADB,
broaden IAM, or repeat secure bootstrap.

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
`/opt/yobi/shared/previous_release`. The default rollback uses only that recorded,
health-verified target; it does not choose a directory merely because its timestamp
sorts newest. An operator may pass an exact verified release ID when deliberately
choosing another retained release:

```bash
sudo /opt/yobi/current/deploy/rollback.sh
sudo /opt/yobi/current/deploy/rollback.sh 20260807T194921Z
```

Rollback switches application code only. It does not delete migration rows, remove
the additive `005`–`008` schema, or revert synthetic knowledge data. Old application
releases must therefore remain compatible with the additive schema. If target health
or readiness fails, the script restores the original current symlink and services.

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
generation adapter; `OCI_EMBED_MODEL` and `OCI_EMBED_DIMENSION` identify retrieval.
Do not provision or select a paid dedicated endpoint without separate approval. A
fake dedicated-adapter contract test is not live dedicated-endpoint evidence.

On the VM:

```bash
sudo systemctl status yobi-api nginx
sudo journalctl -u yobi-api --since "10 minutes ago"
curl --fail http://127.0.0.1/readyz
sudo /opt/yobi/current/deploy/rollback.sh
```
