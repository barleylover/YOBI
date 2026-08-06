# Demo runbook

Before presenting, run `./deploy/run_remote_prewarm.sh`, verify `/readyz`, open the
current OCI public URL, and run the primary scenario once. `/demo/control` is
protected; use the existing runtime rehearsal token without copying it into the
repository or shell history. The deterministic catalog remains available if GenAI
times out or returns an ungrounded answer.

1. Scan `/demo/qr` or open the current live URL.
2. Keep English, United States, shellfish allergy severe, and spice tolerance 1/5.
3. Consent and ask: “I saw a red rice cake dish on the street. What was it?”
4. Show classic tteokbokki spice 4 and its shellfish review risk signal.
5. Show mild rose sauce verified absent plus cross-contamination unknown.
6. Choose Mild, Regular, Add cheese, Remove fish cake.
7. Confirm the translated restaurant note.
8. Upload the bundled synthetic booking image and confirm the Myeongdong hotel.
9. Confirm front desk, no bell, and no cutlery.
10. Review the DB-calculated ₩15,900 total.
11. Complete the payment simulation and show the synthetic order ID.

Failure modes are `force_genai_timeout`, `force_payment_failure`, and
`force_fallback`. A payment failure must leave the cart intact and allow retry. Reset
only session/cart/checkout/order state; catalog rows remain unchanged.
