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
verifies `YOBI_APP` plus migrations `001`, `002` and append-only `003`, and writes the protected runtime
environment before any GenAI smoke request. No secret is echoed.

If `/etc/yobi/yobi.env` already exists, do not recreate it. The same resume command
loads the protected file and does not prompt for or overwrite its values.

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
`/opt/yobi/current`, applies only checksum-safe pending migrations, performs an
idempotent seed upsert, switches the symlink, and requires both health and readiness.
If activation fails, it restores the previous complete release link and restarts the
services. It does not recreate the VM/ADB, broaden IAM, or repeat secure bootstrap.

On the VM:

```bash
sudo systemctl status yobi-api nginx
sudo journalctl -u yobi-api --since "10 minutes ago"
curl --fail http://127.0.0.1/readyz
sudo /opt/yobi/current/deploy/rollback.sh
```
