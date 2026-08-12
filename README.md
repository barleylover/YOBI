# YOBI MVP

요기요 해커톤 팀 프로젝트입니다.

YOBI is an evidence-grounded AI food concierge and mock ordering agent for foreign tourists in Korea. The primary demo is a mobile web flow from onboarding to menu discovery, dietary evidence, merchant comparison, options, hotel address confirmation, mock payment, and mock order completion.

All catalog, review, hotel, payment, and order data in this repository is synthetic demo data. YOBI does not call a real Yogiyo API and never processes a real payment.

## Current status

The repository contains the original mobile ordering MVP plus a structured
recommendation runtime. Users choose meal preferences before recommendation; the
server applies objective eligibility and builds a broad hybrid Wiki evidence pool,
then one bounded generation request is instructed to select and explain menus from
that pool. The server enforces final menu/evidence-reference membership; semantic
faithfulness of generated prose remains a model-quality evaluation boundary.
The Wiki keeps objective facts structured while using prose passages for subjective
food descriptions. Reviews remain display-only synthetic data with recommendation
and safety weight `0`.

The structured flow has no free-text recommendation composer. Its only dietary
controls are halal certification and vegan guidance: halal is an active,
scope-verified certification filter; vegan recommendations may carry a check-before-
ordering warning. Allergy input is not part of the new public recommendation path.
All catalog, certification, and merchant data remains synthetic demo data.

The structured revision is live as OCI release
`20260812T141008Z-8418f92b7e37`; Git source alone is still not evidence for a future
release.
The [structured-recommendation plan](docs/STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md)
is the current product and implementation authority,
[implementation status](docs/IMPLEMENTATION_STATUS.md) summarizes what is connected,
and the [test report](docs/TEST_REPORT.md) records the exact local, Oracle/OCI,
rollback, and public evidence. The
[chatbot-improvement record](docs/CHATBOT_IMPROVEMENT_IMPLEMENTATION.md) is retained
only as superseded free-chat history. The public URL and OCI identifiers are resolved
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
address extraction, deterministic embeddings, and no OCI credentials. The structured
flow therefore exercises its labelled saved-search fallback locally. The normal
model-selected result path was separately verified against the deployed OCI provider;
local startup does not reproduce that external call. See the
[demo runbook](docs/DEMO_RUNBOOK.md) for the exact new-UI walkthrough and
focused regression checklist.

## Verification

```bash
make test
make build
make evaluate
make prewarm
make smoke
make e2e
```

`make test`, `make build`, and the current Playwright suite cover the working-tree
source contracts. `make evaluate`, `make prewarm`, and `make smoke` still exercise
retained v1 ranking/chat/cache paths; they are useful regression checks but do not, by
themselves, approve the structured v2 recommendation path. The historical v1 chatbot
acceptance suite can also be run directly from `backend/`:

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
bootstrap flow in the [OCI deployment guide](docs/OCI_DEPLOYMENT.md).
