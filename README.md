# YOBI MVP

YOBI is an evidence-grounded AI food concierge and mock ordering agent for foreign tourists in Korea. The primary demo is a mobile web flow from onboarding to menu discovery, dietary evidence, merchant comparison, options, hotel address confirmation, mock payment, and mock order completion.

All catalog, review, hotel, payment, and order data in this repository is synthetic demo data. YOBI does not call a real Yogiyo API and never processes a real payment.

## Current status

The product is implemented and running on the existing Seoul OCI VM with Oracle AI
Database 26ai, Grok 4.3, GPT-OSS and deterministic fallback layers. Secure bootstrap,
public Health/Ready, responsive E2E, and three consecutive primary mobile flows have
passed. The standalone Grok bootstrap smoke remains recorded as degraded after a 429
and safe 404 category, while later public runtime calls returned Grok HTTP 200. See
`docs/IMPLEMENTATION_STATUS.md` for the exact evidence boundary.

## Local development

Requirements: Python 3.9+ and Node.js 20+.

```bash
make setup
make dev
```

Default frontend: `http://127.0.0.1:5173`
Default backend health: `http://127.0.0.1:8000/healthz`

`make dev` starts both servers, waits for readiness, and opens the frontend on macOS.
Keep that terminal open and press `Ctrl-C` to stop both processes. Set
`YOBI_NO_OPEN=1` if you do not want the browser to open automatically. Logs are
written under `.local-demo/` and are excluded from Git.
If either default port is already in use, the launcher selects the next free local
port without stopping the existing process and prints the actual URLs.

The local launcher explicitly uses a deterministic SQLite demo database, fixture
address extraction, and the deterministic agent fallback. OCI credentials are not
needed or used for this UI verification. See `docs/DEMO_RUNBOOK.md` for the exact
new-UI walkthrough and focused regression checklist.

## Verification

```bash
make test
make build
make evaluate
make prewarm
make smoke
make e2e
```

For a manual two-terminal start on alternate ports, set `YOBI_API_PROXY_TARGET` to
the backend origin when starting Vite. This changes only the local development proxy
and never enters the browser bundle.

## Security boundary

Do not put API keys, passwords, full DSNs, private keys, public IPs, or OCIDs in this
repository. Production secrets belong only in `/etc/yobi/yobi.env`, owned by
`root:root` with mode `0600`. Use the terminal-only secure
bootstrap flow in `docs/OCI_DEPLOYMENT.md`.
