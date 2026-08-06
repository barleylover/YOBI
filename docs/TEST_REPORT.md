# Test report

Last verification: 2026-08-06 KST.

| Scope | Result | Evidence boundary |
|---|---:|---|
| Ruff | PASS | Backend, scripts, and deployment Python |
| MyPy | PASS | 40 Python source files |
| Pytest | 35 PASS | Product, integrity, rate-limit/failover, grounding, and bootstrap resume checks |
| Frontend ESLint | PASS | React/TypeScript source and tests |
| Frontend unit/component | 2 PASS | Evidence status labelling |
| TypeScript + Vite build | PASS | 1,788 modules; production assets generated |
| Shell syntax | PASS | All deployment shell scripts |
| Oracle connection/migrations | PASS | `YOBI_APP`; `SCHEMA_MIGRATION` versions `001`, `002` |
| Oracle seed integrity | PASS | Exact row counts, 150 vectors, canonical search, required options |
| Grok bootstrap smoke | DEGRADED | HTTP 429, bounded wait/retry, then safe HTTP 404 category |
| GPT-OSS smoke | PASS | Live fallback-model response |
| Deterministic fallback smoke | PASS | Live Oracle repository with forced deterministic path |
| Runtime GenAI | PASS | Public E2E logs contain Grok 4.3 HTTP 200, GPT-OSS HTTP 200, and function calls |
| Local Health/Ready | PASS | Nginx to API, Oracle readiness, vector readiness |
| Public Health/Ready | PASS | TCP 80 `/healthz` and `/readyz` return HTTP 200 |
| Public Playwright | 11 PASS, 9 intentional skips | Four viewports plus iPhone secondary and payment-failure flows |
| Public primary repeat | 3 PASS | iPhone full mock order repeated consecutively in 4.0–8.0 seconds |
| Console errors | PASS | Primary-flow assertion requires an empty browser console-error list |
| Retrieval evaluation | 100 PASS | Deterministic local evaluation; all policy mismatch counters zero |

The public test run exposed and fixed three deployment-only defects: the VM firewall
did not permit HTTP, `crypto.randomUUID()` was unavailable on a non-secure HTTP
origin, and Oracle rejected the reserved bind name `:session` in address validation.
The final public run verified the real Oracle delivery/cart/checkout path after these
fixes.

The demo-control status request is expected to return 403 without its protected
token; public E2E asserts that boundary rather than bypassing it. Provider responses
that contain no grounded tool result are rejected and routed to the deterministic
card-producing continuity path.

The 100-query retrieval distribution is 20 category, 20 dietary/allergy, 15 cultural
explanation, 15 merchant comparison, 10 options, 10 address/delivery, 5 prompt
injection, and 5 ambiguous/out-of-scope cases. Constraint, canonical top-3, evidence,
unsafe reassurance, price, and option mismatch counters are all zero.
