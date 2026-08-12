# YOBI MVP implementation plan (superseded recommendation scope)

> **Superseded product-flow plan.** This file is retained as the 2026-08-06/11
> implementation history. For the current recommendation experience, allergy scope,
> five-level spice contract, Wiki authoring, RAG authority, and LLM-call boundary, use
> [`STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`](STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md).
> The current flow is profile/address → structured selection → objective eligibility
> → broad lexical+embedding evidence pool → one generation request that selects and
> explains final pool menus → button-only follow-up. Historical free-chat and
> server-final-candidate statements below are not current requirements.

Date: 2026-08-06 KST
Wiki-centric demo update: 2026-08-11 KST

## Authority and conflict resolution

1. `docs/STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md` is the authority for the
   current recommendation flow and overrides the affected historical items below.
2. `YOBI_FINAL_MVP_CODEX_MASTER_PROMPT.md` remains historical authority outside the
   explicitly superseded recommendation scope.
3. `YOBI_OCI_INFRA_HANDOFF_MASTER.md` is the authority for verified OCI facts and constraints.
4. `references/product_proposal.pdf` supplies product philosophy, trust design, diagrams, and supporting examples.
5. The preliminary manuscript supplies background only where it does not conflict with the final prompt.
6. Oracle and Yogiyo orientation PDFs supply competition, submission, and technical guidance; their older `/openai/v1 + project` example and Oracle 23ai references are superseded.

The current MVP target is an English-speaking foreign tourist entering by QR, not a long-term resident. Onboarding is a visual form. A booking screenshot is supported. Payment is always mock. The production LLM path is `/20231130/actions/v1`, model `xai.grok-4.3`, with no `project=` parameter.

## Confirmed starting state (historical, 2026-08-06)

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
- Deterministic seed, expanded for the presentation demo: 3 service areas, 60
  merchants, 600 menus, 1,202 option groups, 2,405 option items, 2,400 zero-weight
  review snippets, 1,200 evidence rows, and 20 address fixtures.
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

### Phase 6 - internal menu knowledge graph demo

- Treat the internal Wiki as the primary recommendation/explanation source. Merchant
  description prose and all review text contribute `0` to ranking and safety.
- Model reusable food knowledge only to family/variant level, such as
  `김밥 → 참치김밥·치즈김밥`; a merchant-specific product name maps to one of those
  concepts instead of creating a merchant node.
- Compile 102 reusable documents (`2` cuisine, `30` family, `70` variant) into 100
  relations, 281 closure rows, 1,997 structured claims, and 918 searchable facet
  chunks; map all 600 menus across 100 menu categories. Claims are 361 ingredient,
  371 allergen, 247 dietary, 100 preparation, and 918 facet rows.
- Search by exact Korean/English alias, Korean facet term, and vector similarity after
  hard safety/availability filtering. Keep all surviving demo candidates with a
  `600` cap, enforce party-sized budget and negative preferences before final output,
  and compose ranking as `60%` Wiki, `25%` structured preference, and `15%`
  operational/menu metadata. The operational signal uses menu relevance, price,
  delivery fee, and ETA—not rating.
- Keep the synthetic merchant/menu feed realistically incomplete: only 206 menus have
  ingredient declarations (565 rows) and 221 have allergen declarations (595 rows).
  Keep 13 origins and 119 merchant ingredients cross-contact-only. Explicit
  absence alternatives require `VERIFIED` synthetic menu evidence while cross-contact
  stays `UNKNOWN`. Missing information stays unknown; shared-kitchen facts are
  cross-contact warnings only.
- Require generated explanations to return grounded passage IDs, scope, and
  uncertainty codes using `OPTION > MENU > VARIANT_WIKI > FAMILY_WIKI` precedence.
- Use base catalog `demo-2026.08.11-knowledge-v3`, knowledge catalog contract
  `demo-knowledge-catalog-2026.08.11-v3`, and migration ledger `001`–`009`. Local
  verification and OCI/public deployment remain separate gates.

## Scope boundaries

- No real Yogiyo data or API.
- No real card number, payment, or order.
- Synthetic claims are visibly labelled.
- No OCI resource deletion, scaling, IAM expansion, new VM, load balancer, Kubernetes, or dedicated AI cluster.
- K-Food Passport is deferred until the canonical flow is stable.
