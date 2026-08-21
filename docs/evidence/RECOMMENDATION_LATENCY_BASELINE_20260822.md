# Recommendation latency baseline and optimization — 2026-08-22

## Scope and measurement boundary

Five public, browser-driven cold-start recommendation flows were executed against release
`20260821T160500Z-e1baaed85007` at commit
`27f225618c633fa87d08ba0d4ac7f211c4791d34`. Each full provider run used a country-specific
presentation cache key that had not been used by the other runs. Full LLM flows were separated by
at least 60 seconds. Browser console errors were zero in all five flows.

The server ledger, provider-attempt audit rows, and structured terminal journal were read after each
flow. Times below are server measurements; browser network time additionally includes polling and
network overhead.

## Baseline observations

| Run | Country | Result | Total | Retrieval | Selection | Presentation | Persistence |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Austria | 3 LLM cards | 24,334 ms | 1,417 ms | 7,979 ms | 14,533 ms | 278 ms |
| 2 | Belgium | 3 LLM cards | 33,990 ms | 1,718 ms | 8,263 ms | 23,656 ms | 268 ms |
| 3 | Netherlands | 1 strict-match fallback | 1,583 ms | 1,333 ms | 0 ms | 0 ms | 228 ms |
| 4 | Switzerland | 3 LLM cards | 24,349 ms | 963 ms | 4,770 ms | 18,313 ms | 232 ms |
| 5 | Ireland | 3 LLM cards | 27,906 ms | 1,739 ms | 8,736 ms | 17,068 ms | 272 ms |

Across the four full LLM runs, mean server time was 27,644.75 ms. Retrieval averaged 1,459.25 ms
(5.3%), selection averaged 7,437 ms (26.9%), presentation averaged 18,392.5 ms (66.5%), and
persistence averaged 262.5 ms (1.0%). The non-LLM control completed in 1,583 ms server-side and
2,825 ms at the browser network boundary. Therefore the material bottleneck is the two serial LLM
calls, especially presentation, rather than Oracle retrieval or persistence.

The selection response averaged 5,190 input and 1,407 output tokens. The presentation response
averaged 4,548 input and 2,328 output tokens. Much of the old response contract asked the models to
echo server-owned ranks, evidence IDs, provenance fields, localized titles, and empty option arrays.

The four full runs selected original server ranks `[1,2,5]`, `[1,2,3]`, `[1,2,3]`, and `[1,2,4]`.
This confirms that the selection stage is not simply redundant: it retained the server's top two in
all observed cases and made a bounded third-place rerank in two. The optimization therefore keeps
the same model and all ranking inputs instead of replacing selection with deterministic top three.

## Implemented optimization

- The GPT-OSS-120B selection authority, frozen shortlist, and ordering decision remain unchanged.
- The selection model now returns only three ordered `menu_ids`. The server reconstructs matched
  criteria and evidence IDs, then rechecks shortlist membership, merchant diversity, hard filters,
  Wiki availability, and complete category support.
- Selection input retains menu identity, matched criterion codes, Wiki content, merchant, price,
  spice, and dietary state while removing repeated evidence-reference bookkeeping.
- Grok still generates localized subtitle, YOGIYO translation, short and long YOBI explanations,
  review summary, personalization use, and compound-component mentions. Immutable title,
  provenance arrays, and empty option-localization arrays are no longer model output.
- Selection output is capped at 2,048 tokens and presentation at 4,096 tokens. The observed maxima
  before this change were 1,585 and 2,487 tokens respectively.
- Browser completion polling changed from 1.2/2.5 seconds to 0.8/1.5 seconds, reducing the maximum
  post-completion visibility delay while retaining backoff for long-running requests.
- Terminal logs now expose separate `selection_ms` and `presentation_ms` in addition to aggregate
  provider time.

Serialized schema size fell from 1,124 to 214 bytes for selection (81.0%) and from 2,563 to 1,223
bytes for presentation (52.3%). Cache identity versions were advanced so legacy presentation rows
remain stored but are not silently reused for the new contract.

## Validation boundary

Local validation proves contract preservation and request reduction; it cannot prove OCI latency.
Post-change cold-start timings must be measured only after an explicitly authorized deployment and
must be compared with the baseline above using the same public-browser and server-ledger method.
