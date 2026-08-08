# Security and truth boundaries

- No real Yogiyo API, restaurant, courier, card processor, or hotel service is called.
- All restaurants, menus, reviews, hotels, payments, and orders are synthetic.
- YOBI never calls food “safe” for an allergy. `UNKNOWN` is not positive evidence.
- Nationality is never converted into religious or dietary assumptions.
- The browser cannot submit authoritative prices or option deltas; the server rebuilds
  totals from current database rows.
- Checkout idempotency prevents duplicate mock orders and reuse across carts.
- Raw booking images are validated in memory and discarded after address candidates.
- Production demo controls require a separate token.

Secrets are entered only in a user-controlled terminal via `getpass`. The ADMIN
password is used once to create `YOBI_APP` and is never written. The runtime file is
`/etc/yobi/yobi.env`, owned by `root:root` with mode `0600`. Systemd reads it before
starting the unprivileged `yobi` process. Deployment commands parse this file as data
with interpolation disabled and pass values directly as process environment; they
never shell-source secret-bearing lines.
Bootstrap progress is stored separately in
`/opt/yobi/shared/control/bootstrap_state.json`, also `root:root` mode `0600`; it contains
only step status and timestamps, never credentials or a DSN. GenAI failures are
reduced to safe error categories. Provider response bodies and chained SDK exception
details are not printed, so a 429/401 cannot spill an API key, authorization header,
or full upstream response into terminal logs.
Do not put API keys, passwords, full DSNs, OCIDs, public IPs, private keys,
Authorization headers, raw allergy profiles, raw addresses, or card data in Git/logs.

Deployment control state is separated from application-writable data.
`/opt/yobi/shared` is `root:yobi` mode `0750`, its `control` and `control/release-state`
directories are `root:root` mode `0750`, and systemd does not grant the service a
writable path there. Bootstrap checkpoints, the previous-release pointer, and per-release
knowledge provenance use unpredictable exclusive temporary files, `fsync`, atomic
replacement, `O_NOFOLLOW`, and strict owner/mode validation. Per-release state is
`root:root` mode `0640` and records the application release/archive checksum plus the
previous and current knowledge release IDs. A release-local manifest is display
metadata, not the rollback authority.

Deploy and rollback serialize through the same non-blocking root-owned `0600` flock.
Uploads use a validated release-and-nonce-specific path, are rejected when symlinked,
unexpectedly owned, or group/world writable, and are deleted by exact path. Release
roots and current/target trees are real-path checked, owned `root:yobi`, and stripped
of group/world write permission, so the unprivileged service can read but cannot
rewrite executable code or rollback metadata.

Knowledge-pointer changes use the `YOBI_APP` account, bound SQL, `READY` validation,
an expected-current guard, commit, and readback. Deploy/rollback failure restores the
previous pointer before restarting the previous application, including an explicit
no-active state. A new-contract target without trusted release state fails closed.
Historical v1 targets without that contract may skip pointer switching solely for
current additive-schema compatibility; future incompatible global configuration or
base-catalog changes require a separate snapshot/restore contract.

The permitted public surface is Nginx TCP 80 only. Uvicorn binds loopback. Deployment
scripts do not change SSH rules. Even a temporary current-source `/32` TCP 22 rule is
a separate approval item and, if approved, must be removed by exact rule identity with
the final SSH-rule count verified as zero. The deployment adds no load balancer, VM,
ECPU, dedicated cluster, or other paid infrastructure.
