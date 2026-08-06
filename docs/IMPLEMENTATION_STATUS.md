# YOBI MVP implementation status

Last updated: 2026-08-06 KST

## MVP status

The requested OCI-hosted MVP is implemented, bootstrapped, and publicly reachable.
The current release is `20260806T051649Z`. The public address is resolved from OCI at
runtime and is intentionally not stored in this repository.

Confirmed live:

- `/etc/yobi/yobi.env` remains `root:root`, mode `0600`, and was reused without
  rewriting or returning secret values to the local machine.
- `YOBI_APP` connects to Oracle AI Database 26ai. `SCHEMA_MIGRATION` contains `001`
  and `002`; the resume path skips both already-applied migrations.
- Seed integrity is exact: 30 merchants, 150 menus, 300 evidence records, 600 review
  snippets, 302 option groups, 605 option items, and 20 hotel/address fixtures.
- All 150 menu vectors are populated, canonical vector search is ready, and no
  required option group is missing an item.
- The modified Grok smoke encountered HTTP 429 and then a safe HTTP 404 category, so
  its checkpoint is recorded as `degraded`. The GPT-OSS smoke and Oracle-backed
  deterministic fallback smoke both passed.
- Subsequent public E2E traffic independently recorded successful HTTP 200 responses
  from both `xai.grok-4.3` and `openai.gpt-oss-120b`, including function calls and
  fallback selection.
- `yobi-api` and Nginx are active. Local and public `/healthz` and `/readyz` return
  HTTP 200.
- SELinux permits the Nginx upstream connection, the VM firewall permits HTTP, and
  the existing NSG has exactly one approved public TCP 80 ingress rule.
- Public Playwright passed 11 checks with 9 intentional cross-viewport skips; the
  full iPhone primary order then passed three additional consecutive runs.

## Bootstrap checkpoints

| Checkpoint | Status |
|---|---|
| `database` | `complete` |
| `genai_smoke` | `degraded` — bounded 429 retry, then safe HTTP 404 category |
| `fallback_model_smoke` | `complete` |
| `seed` | `complete` |
| `deterministic_fallback_smoke` | `complete` |
| `prewarm` | `complete` |
| `health_ready` | `complete` |
| `services` | `complete` |
| `bootstrap` | `complete` — primary degraded, both fallback layers complete |

## Delivered product boundary

The mobile flow covers onboarding, conversational discovery, grounded category and
menu explanation, dietary evidence, merchant comparison, options, translated notes,
hotel address confirmation, delivery preferences, server-side cart, mock payment,
payment failure recovery, and mock order completion. Catalog, review, hotel, payment,
and order records are synthetic. No real restaurant, courier, Yogiyo API, or payment
processor is contacted.

This is a public HTTP demo, not a production deployment: it has no custom domain or
TLS certificate. The protected demo-control page requires the runtime token.

## Verified OCI snapshot

| Area | Confirmed state |
|---|---|
| Network | Existing `yobi-vcn`, public app subnet, and private DB subnet reused |
| Compute | Existing `yobi-app-01`, 1 OCPU/6 GB, RUNNING |
| Database | Existing `yobi-adb`, Oracle AI Database 26ai, AVAILABLE |
| GenAI | Grok 4.3 primary and GPT-OSS fallback both returned live HTTP 200 during public E2E |
| VM app | Release `20260806T051649Z`; `yobi-api` and Nginx active |
| Public web | Exactly one approved TCP 80 ingress rule; Health/Ready and public E2E pass |

## Truth boundary

The original standalone Grok bootstrap smoke remains honestly recorded as degraded;
it was not rewritten after later runtime success. Live Grok success is proven by the
public E2E service logs, while bootstrap continuity is proven by GPT-OSS and
deterministic smoke checkpoints. No production-readiness claim is made.
