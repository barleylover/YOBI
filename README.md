# YOBI MVP

요기요 해커톤 팀 프로젝트입니다.

YOBI is an evidence-grounded food concierge for foreign tourists in Korea. The
primary mobile-web flow combines the welcome and locale choice, confirms a supported
demo delivery address, guides users through button-based preferences, presents
server-ranked menus in a chat-style one-card carousel, then continues through options,
cart review, and an explicit Yogiyo-handoff mock. The browser does not expose mock
payment or synthetic-order completion.

The deployed menu/merchant catalog is a versioned import of public Yogiyo web
catalog fields; it is not a live Yogiyo API integration. Reviews, the demo hotel,
payments, and orders remain synthetic/mock, and YOBI never processes a real payment.
The current browser flow ends at an explicit Yogiyo handoff mock; it does not call a
Yogiyo URL/API or show an internal payment-success/order-complete screen. Synthetic
checkout and order APIs remain backend-only release integrity checks.

## Current status

The repository contains the original mobile ordering MVP plus a structured
recommendation runtime. Users choose meal preferences before recommendation. In the
current worktree contract the server applies objective eligibility, reviewed concept
support, deterministic retrieval, scoring, and diversity to freeze a bounded shortlist
of at most 15 menus. When the provider path is available, the selection model returns
exactly three menu IDs from that shortlist; the server then revalidates shortlist
membership, hard constraints, diversity, and evidence ownership before presentation
and persistence. Provider or contract failure uses a deterministic selection from the
same frozen shortlist. A persisted request ledger makes same-request replay return the
canonical result without another dispatch. Semantic faithfulness of generated prose
remains a model-quality evaluation boundary.
The Wiki keeps objective facts structured while using prose passages for subjective
food descriptions. Reviews remain display-only synthetic data with recommendation
and safety weight `0`.

The structured flow has no free-text recommendation composer or demographic profile
questions. Halal certification, vegan guidance, and the five-level spice ceiling are
catalog-published capabilities, not unconditional promises: a control is disabled with
a visible reason when the active release lacks enough reviewed menu-level coverage.
Allergy input is not part of the public recommendation path. Formal certification,
reviewed menu-level ingredient, and reviewed menu-level spice data are unavailable in
the current external source, so those controls are unavailable rather than inferred.
General food Wiki material and derived menu-name-to-concept mappings are explicitly
labelled reviewed synthetic support, never merchant recipe facts.

After address confirmation, a common navigation control also exposes a clearly
labelled demo ranking view and a K-POP Demon Hunters food feature. Rankings use source
menu/merchant review counts for the external catalog and deterministic ID-derived
values only for synthetic fixture menus with no source counts; they are never described
as live Yogiyo-wide statistics. The feature maps five
general food concepts to currently available menus and does not treat general Wiki
prose as a restaurant recipe.

The 2026-08-17 final application `20260816T201131Z-29fbc2f9fd32` is publicly active
and healthy. It serves the Oracle external catalog (200 merchants, 15,085 menus),
migration `012`, 198 reviewed general-food Wiki concepts/documents, 1,551 chunks,
3,922 high-confidence menu mappings, and 1,499 reviewed preference-support rows.
Compared with the previous family, 1,967 additional menus are now mapped. The public
selector exposes Korean, Chinese, Southeast Asian, Mexican, Japanese, Italian, and
American & grill cuisine choices.

The operator-approved expanded-cuisine validation made exactly five provider calls:
Japanese, American, Southeast Asian, and Mexican returned normal grounded results;
Italian returned the same server-frozen three menus through the safety fallback after
its generated response failed the strict contract. Review found that the fallback had
dropped already available selected-cuisine evidence. That deterministic serialization
was fixed and verified on expanded SQLite and live Oracle without another provider
call. The final deploy itself made zero provider calls and passed query-plan, source,
fallback, evidence-binding, public API/browser, and network-cleanup gates. Five samples
do not support a percentile claim. See the
[expansion evidence](docs/evidence/KNOWLEDGE_EXPANSION_20260817.md) for the exact
quality boundary. Git source alone is never deployment evidence.
The [structured-recommendation plan](docs/STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md)
is the current product and implementation authority,
[codebase refactor plan](docs/CODEBASE_REFACTOR_PLAN_20260822.md) records the current
cross-stack audit, completed seams, verification evidence, and staged decomposition,
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
flow therefore exercises its labelled deterministic fallback locally. The provider
selection and presentation path is a separate OCI gate; local startup does not
reproduce those external calls. In every path, candidate eligibility and the shortlist
remain server-owned, and generated menu IDs must pass the server contract before they
can be persisted. See the
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

The recommendation performance harness has two honest modes. A reduced run is useful
for functional iteration and intentionally makes no P95/P90 claim; the release gate
uses the documented warm 100 **per positive repository scenario**, process-cold 20,
full provider-path 30, and three-way concurrency samples. It reports each scenario
separately as well as the aggregate:

```bash
.venv/bin/python scripts/recommendation_performance_smoke.py \
  --repository-only --warm-samples 3 --cold-samples 2

.venv/bin/python scripts/recommendation_performance_smoke.py \
  --base-url http://127.0.0.1 --release-gate
```

The external deployment's `structured` release gate first runs
`scripts/structured_recommendation_smoke.py`: it discovers an active supported
preference and recommendation, dynamically selects that menu and its required
available options, and verifies cart→fixed demo address→mock checkout→synthetic order
plus cascade cleanup without a hard-coded demo menu ID. It then runs
`scripts/structured_fallback_smoke.py` against the Oracle runtime with an isolated
process-local forced timeout, proving the same frozen menu order, deterministic
fallback explanation, one dispatch, and cleanup without changing the public failure
mode. These backend checks do not change the Yogiyo-handoff UI boundary or imply a
real payment/order.

`make test`, `make build`, and the current Playwright suite cover the working-tree
source contracts. `make evaluate`, `make prewarm`, and `make smoke` still exercise
retained v1 ranking/chat/cache paths; they are useful regression checks but do not, by
themselves, approve the structured v2 recommendation path. The historical v1 chatbot
acceptance suite can also be run directly from `backend/`:

`make build` also enforces a 300 KiB uncompressed limit for the initial JavaScript
entry and every individual JavaScript chunk. Override the byte limits only for an
explicitly reviewed release with `YOBI_ENTRY_JS_BUDGET_BYTES` or
`YOBI_JS_CHUNK_BUDGET_BYTES`.

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
