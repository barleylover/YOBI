# RAG and hybrid recommendation design

YOBI does not let an LLM invent or select the final menu set. The server first builds
and validates cumulative meal needs, then produces a grounded candidate result. The
model may explain that result in natural language, but the body, cards, prices,
options, claims, and passages remain tied to server-owned identifiers.

## Turn orchestration

`DialogueEngine` converts each user turn into a `PreferenceDelta`, merges it into the
session's `MealNeedState`, assigns a `DialogueAct`, and evaluates readiness. Greetings,
uncertain answers, recommendation holds, and ordinary need collection can be answered
without tools or cards. Recommendation runs only when accumulated information passes
the readiness policy or the user explicitly requests a recommendation.

When tools are allowed, `DialogueAct` routes the turn to a small subset of the
14-function allowlist. The provider is never asked to choose from an unrelated full
surface. Tool arguments are Pydantic-validated; tool results are wrapped as bounded
`untrusted_data`. A persisted `RecommendationSnapshot` is the authority for later
selection, rejection, comparison, and “the second menu” references.

## Candidate and safety pipeline

The final recommendation path combines deterministic filtering and semantic ranking:

1. Merge profile rules with the cumulative conversation state.
2. Apply service area, merchant/menu availability, budget, spice, and normalized
   hard dietary/allergen constraints.
3. Map each candidate to the active knowledge release and resolve inherited Wiki
   claims through `DISH_CONCEPT_CLOSURE`.
4. Treat Wiki `DEFINING`/`CORE` ingredients as `PRESUMED_PRESENT`; eliminate a menu
   when those claims conflict with a hard exclusion.
5. Apply menu-specific claims and selected option `ADD`/`REMOVE` effects. Merchant
   origin/ingredient declarations remain separate `MERCHANT`-scope evidence: they do
   not prove menu presence, but they conservatively exclude a candidate when they
   conflict with a strict request, an explicit religious rule, or a severe allergy
   because shared-kitchen cross-contact is unresolved.
6. Expand the search text with accumulated temperature, texture, flavour, and
   category preferences, then combine lexical boosts with semantic similarity.
7. Exclude rejected menus and rerank the remaining candidates. Return only the
   server-built `RecommendationResult` and its claim/passage references.

Oracle performs `VECTOR_DISTANCE(..., COSINE)` over filtered menu vectors and the
active immutable `KNOWLEDGE_CHUNK` vectors, using a `0.75` menu / `0.25` knowledge
similarity blend before deterministic preference boosts. Legacy `MENU_KNOWLEDGE`
vectors have no recommendation weight. Candidate retrieval is explicitly capped at
40, and claim, passage, and evidence rows are loaded set-wise for that bounded set;
the final result retains the top three chunk IDs and resolved claim IDs per menu.
SQLite implements the same contract with deterministic embeddings and
application-side cosine similarity; it is local contract evidence, not Oracle Vector
Search evidence.

Review snippets are retained only as visibly synthetic display/backward-compatible
data. Their recommendation weight is `0`, their safety weight is `0`, and review text
is not supplied as grounded LLM context. Changing a review must not change candidate
order or an allergy decision.

## Wiki inheritance and override rules

The food Wiki is an explicitly versioned source of general food knowledge, not a
claim about a real restaurant recipe.

- `DEFINING` and `CORE` + `PRESUMED_PRESENT` claims may inherit across an edge whose
  `inherit_claims` flag is true.
- `COMMON`, `OPTIONAL`, `POSSIBLE`, `UNKNOWN`, and `CONFLICTING` remain qualified;
  they are not silently strengthened for filtering or prose.
- A missing ingredient/allergen claim is unknown, never `CONFIRMED_ABSENT`.
- A menu or option fact can override the same target only at its explicit scope.
- Merchant-wide origin text can be displayed as merchant context, but it cannot prove
  that every menu contains the ingredient.
- Unknown cross-contact remains a warning even when a sauce-level ingredient is
  marked absent.

This resolution contract is used by recommendation filtering, `explain_menu`,
`get_dietary_evidence`, snapshot references, and the grounded response validator.

## Authoring, chunks, and release activation

Markdown files under `knowledge/dishes/` are the editable Wiki source. Strict front
matter declares concept identity, parent edges, ingredient roles/status, allergen
status, sources, synthetic status, and review status. Each document supplies nine
named explanation facets. The compiler validates and normalizes the graph, creates a
closure table, emits stable claim/document/chunk IDs and hashes, and embeds each
facet.

Loaders stage a `KNOWLEDGE_RELEASE` as `LOADING`, insert only that immutable release's owned
rows, verify exact counts and non-null vectors, then mark it `READY` and switch
`KNOWLEDGE_RUNTIME_STATE`. `/readyz` fails when the active release is absent, not
ready, has a missing/invalid manifest, declared counts that differ from observed
counts, anything other than exactly 150 mappings/30 origins/266 merchant ingredients/
4 option effects, null or metadata-incompatible chunks, incompatible menu vectors,
or invalid required-option cardinality.

The authoring default is `yobi-semantic-hash-v1`, 1536 dimensions, version
`2026-08-06`. The release path explicitly pins seed and query embedding to the
deterministic provider; `auto` is only an explicit one-off operator override. Oracle
can re-embed the authored chunks only when an operator deliberately changes that
provider contract. Source/document hashes and embedding metadata
make a changed document or embedding model a new verifiable release artifact rather
than an invisible cache mutation.

Prewarmed explanations are also release-aware. Their provenance combines the catalog
version with the active knowledge release, their cache key includes a provenance hash,
and stale prewarm rows for the same menu/language are invalidated before regeneration.

## Generation provider is separate from embedding

`GenAIProvider` owns generation capabilities and request normalization. Current
configuration expresses OCI provider, logical generation model, on-demand or
dedicated serving mode, optional endpoint references, function calling, structured
output, streaming capability, timeout, bounded retry/backoff, maximum input/output,
maximum tool schemas per request, and maximum tool calls per response. AgentLoop uses
the lower server/provider limit and rejects excess input or calls before executing a
tool. Production/dedicated readiness fails closed with sanitized configuration codes
when required model, endpoint, HTTPS region, credentials, or capabilities are absent.
Dedicated tests use contract fixtures; the existence of that adapter is not evidence
that a paid dedicated endpoint has been provisioned.

Generation model changes do not alter `KNOWLEDGE_CHUNK` embeddings. Embedding model,
dimension, and version are configured and verified independently. Only an embedding
provider/version change triggers re-embedding, index evaluation, and an active-release
transition.

Provider errors are classified as `RATE_LIMIT`, `TIMEOUT`, `NETWORK_ERROR`,
`INVALID_TOOL_ARGUMENT`, `NO_TOOL_RESPONSE`, `EMPTY_RESPONSE`,
`GROUNDING_REJECTED`, `CAPABILITY_LIMIT_EXCEEDED`, or `PROVIDER_UNAVAILABLE` (with a final unknown-provider
fallback category at the service boundary). Timeout/network/5xx retries are bounded
with exponential backoff and jitter. Rate limits cause model cooldown/fallback rather
than sleeping through an interactive request. The fallback preserves the current
`DialogueAct`, state, and server facts.

## Grounded response contract

Model output is normalized into a short narrative plus optional referenced menu and
claim IDs. `GroundedResponseValidator` rejects references not present in the
server-owned cards/result, internal tool names, internal IDs in user-visible prose,
or stronger claims than the grounded payload supports. General Wiki passages are
labelled as synthetic food knowledge; menu-specific specifications and unknowns are
shown separately.

Cart/delivery/check-out tools accept only an explicit matching user act. The server
revalidates options, price, cart readiness, and state transitions. Agent cart inserts
use a unique request key, so a provider continuation failure or retry cannot duplicate
the line. The LLM cannot mark payment successful; mock-payment success remains an
explicit server endpoint, and order completion can only read the one order already
linked to a successful mock checkout.

## Evaluation boundary

`backend/evaluation/run_chatbot_acceptance.py` executes real `ChatService` turns over
the repository and checks multi-turn greetings, holds, correction, hard constraints,
readiness, snapshot references, and knowledge golden cases. Focused tests cover graph
authoring/load/search, all-menu mapping, Wiki/menu/option precedence, missing-is-not-
absent semantics, merchant scope, review weight `0`, provider capabilities/retries,
and UI conversation hydration/events.

Local SQLite and fake-provider results do not prove Oracle, OCI GenAI, Nginx, or the
public product. Those are separate Phase 7 deployment gates and must be recorded with
the exact release and commands in `TEST_REPORT.md`.
