# YOBI demo runbook

Audience: presenter or evaluator running the deployed tourist ordering MVP. The goal
is to demonstrate a grounded K-food discovery-to-mock-order journey without exposing
runtime secrets or implying a real order.

## 1. Five-minute preflight

1. Run `./deploy/run_remote_prewarm.sh` from the project root.
2. Confirm the output reports Oracle readiness and no missing catalog/vector data.
3. Resolve the current public address from OCI or open `/demo/qr`. Do not save the
   public IP or any control token in Git.
4. Open a fresh private browser window so the presentation starts with a new session.
5. Verify `/healthz` and `/readyz` return HTTP 200.

Do not rerun secure bootstrap during ordinary rehearsal. `/etc/yobi/yobi.env` already
exists and is protected. Never paste an API key, DB password or demo-control token
into chat, source files or shell history.

## 2. Primary demo script

1. On onboarding, keep English, United States, age 25-34, shellfish allergy severe,
   spice tolerance 1/5 and the sample comfort foods. Point out that every field is
   editable and nationality never implies religion or dietary rules.
2. Accept synthetic demo-profile processing and select **Start ordering**.
3. Select **Try the demo question**: “I saw people eating some red rice cake dish on
   the street. What is that? Can I order it?”
4. Show that classic tteokbokki risk and the mild rose alternative are grounded in
   catalog/evidence IDs. State clearly that cross-contamination is not verified.
5. Choose the canonical **Mild rose tteokbokki** menu.
6. Choose **Mild**, **Regular**, **Add cheese**, and **Remove fish cake**.
7. Review the Korean restaurant note and add the item to the mock cart.
8. Choose **Use stable demo booking image**. Explain that the server decodes and
   re-encodes the image in memory, runs Tesseract, retains no raw image, and still
   requires explicit address confirmation.
9. Confirm **YOBI Myeongdong Hotel**, then confirm front desk delivery, no bell and
   no disposable cutlery.
10. Review the server-calculated total: item ₩14,400 + delivery ₩1,500 = ₩15,900.
11. Proceed to the external mock checkout and pay. Emphasize **Demo payment — no real
    charge**.
12. Show the synthetic order ID and the statement that no restaurant or courier was
    contacted.

Expected duration after onboarding: about 30–60 seconds without provider rate limit.
If the provider is limited, the card-producing continuity path keeps the same Oracle
data and safety rules and is visibly labelled **Demo continuity mode**.

## 3. Secondary proof points

- Ask for “Something warm and mild after walking in the rain, no pork and under
  15,000 won” to show category retrieval and chicken kalguksu explanation.
- Use **Compare mild rose options** to show shared price, ETA, portion, flavour,
  packaging and dietary axes.
- On mock checkout select **Simulate failure**. The cart must remain unchanged and a
  second payment attempt must create only one order.
- In the order review use quantity controls or remove the line to demonstrate
  server-authoritative repricing and confirmation reset.
- Use hotel search or manual road address instead of the image to show all three
  address entry modes.

## 4. Failure rehearsal

The protected control page supports `force_genai_timeout`, `force_payment_failure`,
and `force_fallback`. Use only the existing runtime rehearsal token in the protected
page; do not reveal it. After rehearsal return the mode to `normal` or reset the
current session. Catalog and migration data must never be deleted for a demo reset.

If the app is unavailable:

1. Check public `/healthz` and `/readyz`.
2. On the VM check `systemctl status yobi-api nginx`.
3. Inspect only recent structured logs; do not print environment values.
4. If the latest activation failed, run `sudo /opt/yobi/current/deploy/rollback.sh`.
   It switches to the previous complete release and verifies health and readiness.

## 5. Presenter truth statements

- “This is a synthetic-data MVP using the real Oracle repository and Vector Search.”
- “Grok Function Calling is live; deterministic continuity is available for provider
  limits and uses the same domain services.”
- “The current embeddings are deterministic 1,536-dimensional vectors, not Cohere.”
- “This is a public HTTP presentation environment, not a production service.”
