# RAG and recommendation design

Retrieval is a hybrid pipeline:

1. Parse the request into query, budget, spice, and exclusions.
2. Apply zone, availability, price, and dietary hard filters in Oracle.
3. Embed the query in `SEARCH_QUERY` mode at 1536 dimensions.
4. Rank filtered menu vectors with cosine distance.
5. Add deterministic category and preference boosts.
6. Join menu evidence and review signals.
7. Return DB identifiers and facts to allowlisted agent tools.

Tool results are wrapped as `untrusted_data`, recursively length-bounded, and only
then returned to the model. The model may use ten read-oriented tools for category,
menu, explanation, evidence, merchant, option, translation, address-candidate, cart,
and mock-payment-status checks. Cart mutation, address confirmation, checkout,
payment, and order creation remain explicit API/UI actions because they require a
fresh user confirmation; the LLM cannot perform them directly.

The preferred provider is `cohere.embed-v4.0`. At secure bootstrap it is smoke-tested.
If that API path is unavailable, YOBI uses `yobi-semantic-hash-v1`: a deterministic,
non-random semantic hashing model with synonym expansion. The fallback is labelled and
does not masquerade as OCI embedding output.

Safety never depends on nearest-neighbour ranking. Severe shellfish + unknown is
excluded; a sauce-level verified-absent claim still carries a separate unknown
cross-contamination warning. Review text is untrusted evidence, never instructions.

The local 100-query evaluation covers category (20), dietary/allergy (20), cultural
explanation (15), merchant comparison (15), options (10), address/delivery (10),
prompt injection (5), and ambiguous/out-of-scope (5) cases. It reports zero
constraint violations, canonical top-3 failures, evidence coverage failures, unsafe
reassurance, price mismatches, and option mismatches. This is deterministic fallback
evidence; Oracle and OCI embedding evaluation remains a deployment gate until secure
bootstrap completes.
