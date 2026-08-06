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
starting the unprivileged `yobi` process.
Bootstrap progress is stored separately in
`/opt/yobi/shared/bootstrap_state.json`, also `root:root` mode `0600`; it contains
only step status and timestamps, never credentials or a DSN. GenAI failures are
reduced to safe error categories. Provider response bodies and chained SDK exception
details are not printed, so a 429/401 cannot spill an API key, authorization header,
or full upstream response into terminal logs.
Do not put API keys, passwords, full DSNs, OCIDs, public IPs, private keys,
Authorization headers, raw allergy profiles, raw addresses, or card data in Git/logs.

The permitted public surface is Nginx TCP 80 only. Uvicorn binds loopback. Existing
SSH rules are not changed. The deployment adds no load balancer, VM, ECPU, dedicated
cluster, or other paid infrastructure.
