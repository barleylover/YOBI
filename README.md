# YOBI MVP

요기요 해커톤 팀 프로젝트입니다.

YOBI is an evidence-grounded AI food concierge and mock ordering agent for foreign tourists in Korea. The primary demo is a mobile web flow from onboarding to menu discovery, dietary evidence, merchant comparison, options, hotel address confirmation, mock payment, and mock order completion.

All catalog, review, hotel, payment, and order data in this repository is synthetic demo data. YOBI does not call a real Yogiyo API and never processes a real payment.

## Current status

The repository contains the original mobile ordering MVP plus the chatbot-improvement
runtime: server-owned multi-turn meal needs, a recommendation readiness gate,
persisted recommendation snapshots and UI events, a versioned synthetic menu Wiki,
and grounded hybrid recommendation/explanation paths. Reviews remain display-only
synthetic data with recommendation and safety weight `0`.

Implementation in Git is not, by itself, evidence that the same revision is live.
`docs/CHATBOT_IMPROVEMENT_IMPLEMENTATION.md` records the Phase 0-7 implementation
matrix and `docs/TEST_REPORT.md` separates current-worktree verification from the
historical public-release baseline. The public URL and OCI identifiers are resolved
at runtime and are intentionally not committed.

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

The chatbot acceptance suite can also be run directly from `backend/`:

```bash
../.venv/bin/python -m evaluation.run_chatbot_acceptance
```

For a manual two-terminal start on alternate ports, set `YOBI_API_PROXY_TARGET` to
the backend origin when starting Vite. This changes only the local development proxy
and never enters the browser bundle.

## Security boundary

Do not put API keys, passwords, full DSNs, private keys, public IPs, or OCIDs in this
repository. Production secrets belong only in `/etc/yobi/yobi.env`, owned by
`root:root` with mode `0600`. Use the terminal-only secure
bootstrap flow in `docs/OCI_DEPLOYMENT.md`.
