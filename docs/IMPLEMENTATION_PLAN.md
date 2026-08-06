# YOBI MVP implementation plan

Date: 2026-08-06 KST

## Authority and conflict resolution

1. `YOBI_FINAL_MVP_CODEX_MASTER_PROMPT.md` is the product and implementation authority.
2. `YOBI_OCI_INFRA_HANDOFF_MASTER.md` is the authority for verified OCI facts and constraints.
3. `references/product_proposal.pdf` supplies product philosophy, trust design, diagrams, and supporting examples.
4. The preliminary manuscript supplies background only where it does not conflict with the final prompt.
5. Oracle and Yogiyo orientation PDFs supply competition, submission, and technical guidance; their older `/openai/v1 + project` example and Oracle 23ai references are superseded.

The current MVP target is an English-speaking foreign tourist entering by QR, not a long-term resident. Onboarding is a visual form. A booking screenshot is supported. Payment is always mock. The production LLM path is `/20231130/actions/v1`, model `xai.grok-4.3`, with no `project=` parameter.

## Confirmed starting state

- This app workspace initially contained only the two master documents and four reference files.
- No Git repository or application source existed in this directory.
- Read-only OCI verification on 2026-08-06 found the expected VCN and subnets available, the 1 OCPU/6GB VM running, Oracle AI Database 26ai available, and the GenAI project, API key, Grok 4.3, Cohere Embed 4, and fallback candidate active.
- Public HTTP ingress is not yet present.
- No secret values or private-key files are stored in this workspace.

## Delivery phases

### Phase 1 - scaffold and vertical slice

- Monorepo, configuration, structured logging, local deterministic DB, and documentation.
- Mobile onboarding, session creation, English message, agent/tool routing, database menu search, and an inline menu card.

### Phase 2 - data and Oracle

- Oracle-specific sequential migrations and checksum ledger.
- Deterministic seed: 3 service areas, 30 merchants, 150 menus, at least 250 option items, 600 review snippets, 300 evidence rows, and 20 hotels.
- Hard dietary filters plus 1536-dimensional semantic embeddings and `VECTOR_DISTANCE(..., COSINE)` retrieval.
- Secure `YOBI_APP` bootstrap; ADMIN is never a runtime account.

### Phase 3 - agent and RAG

- Grok 4.3 Responses API client, allowlisted function-calling loop, Pydantic input validation, sanitized tool results, bounded retries/steps, and audit logs.
- Evidence policy for VERIFIED, RISK_SIGNAL, UNKNOWN, and CONFLICTING.
- Deterministic fallback uses the same domain services and database.

### Phase 4 - complete order journey

- Menu/category cards, dietary evidence, merchant comparison, one-question-at-a-time options, translated note, address upload/confirmation, delivery choices, server-side cart, mock checkout, and mock order.
- Distinct mock payment route with success, failure, cancel, retry, and idempotency.

### Phase 5 - quality and deployment

- Backend policy/cart/address/payment/fallback tests, frontend component tests, accessibility checks, and Playwright mobile/desktop E2E including upload and payment failure.
- Nginx, systemd, release/rollback scripts, preflight, demo reset, prewarm, current-URL QR, and safe logging.
- Secure user-run bootstrap only when secret input is genuinely required, followed by migration, seed, deployment, public smoke tests, and three consecutive canonical E2E passes.

## Scope boundaries

- No real Yogiyo data or API.
- No real card number, payment, or order.
- Synthetic claims are visibly labelled.
- No OCI resource deletion, scaling, IAM expansion, new VM, load balancer, Kubernetes, or dedicated AI cluster.
- K-Food Passport is deferred until the canonical flow is stable.

