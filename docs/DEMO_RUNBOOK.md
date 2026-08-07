# YOBI demo runbook

Audience: a team member, presenter, or evaluator checking the current YOBI UI from
onboarding through mock order completion. This runbook follows the redesigned flow:
the delivery address is confirmed before recommendations, menu results use a swipe
carousel, and checkout readiness includes dietary conflicts and the restaurant
minimum.

## 1. Choose the verification boundary

### Local UI verification

Use this for fast, repeatable checks on the current source code. The local launcher
uses SQLite, fixture-based address extraction, and deterministic agent continuity.
It does **not** verify Oracle, OCI GenAI, Tesseract, Nginx, systemd, a real payment,
restaurant, or courier.

From the project root:

```bash
# First run only, or after dependencies change
make setup

# Every local rehearsal
make dev
```

`make dev` waits for both services, opens the selected frontend URL on macOS, and
keeps them attached to the current terminal. Press `Ctrl-C` once to stop both. To
suppress automatic browser opening, run `YOBI_NO_OPEN=1 make dev`.

Default endpoints (the launcher always prints the actual values):

- Frontend: `http://127.0.0.1:5173`
- Backend health: `http://127.0.0.1:8000/healthz`
- Backend readiness: `http://127.0.0.1:8000/readyz`
- Local logs: `.local-demo/backend.log` and `.local-demo/frontend.log`

If port 5173 or 8000 is occupied, the launcher does not kill the existing process.
It selects the next free local port, updates the frontend proxy, and prints the actual
URLs. Use the manual two-terminal commands in section 6 only when you want to control
the ports yourself.

### Deployed presentation verification

Use the existing OCI environment only when Oracle, GenAI, Tesseract, Nginx, systemd,
or public-network behaviour is in scope. Run `./deploy/run_remote_prewarm.sh`, confirm
`/healthz` and `/readyz`, and open a fresh private browser window. Do not rerun secure
bootstrap during ordinary rehearsal and never print `/etc/yobi/yobi.env` values.

## 2. Primary new-UI demo

Allow about 60–90 seconds after the page opens.

1. In **Your starting information**, keep **English**, **United States**, age
   **25-34**, **Prefer not to say**, shellfish allergy **Severe**, and spice
   **Medium**. Leave Vegan off for the primary path.
2. Point out that Language now has 16 choices, Country has 36 choices, and countries
   associated with the selected language appear first. Confirm there is no gender
   field and that Vegan and Religion are explicit inputs.
3. In **Delivery address**, keep **Hotel name** and
   `YOBI Myeongdong Hotel`. Accept the synthetic-session consent and select
   **Check delivery address**.
4. Select **Confirm & start** on the returned synthetic address candidate. The chat
   must open with **Your delivery context is ready** and the confirmed hotel shown.
5. Select **Try the demo question**: “I saw people eating some red rice cake dish on
   the street. What is that? Can I order it?”
6. Show the classic tteokbokki risk evidence and the mild rose alternative. State
   that cross-contamination is unknown; the UI never labels the dish allergy-safe.
7. Select **Choose this menu** on **Mild rose tteokbokki**. The page must scroll
   directly to **Order builder**.
8. Choose **Mild**, **Regular**, **Add cheese**, and **Remove fish cake**. On the fish
   cake step, point out that **Keep fish cake** is initially disabled, explains the
   dietary risk, and offers **Unlock option** for an explicit override.
9. Review the Korean restaurant note, then select **Add to mock cart**.
10. Confirm **Hotel front desk**, **No bell**, and **No disposable cutlery** with
    **Confirm delivery details**. The address is not requested again because it was
    confirmed during onboarding.
11. In **Final review**, verify both readiness checks are green:
    **Dietary check** has no known hard conflict and **Restaurant minimum** is met.
    The server-calculated total should be item ₩14,400 + delivery ₩1,500 = ₩15,900.
12. Select **Proceed to payment**, confirm **Demo payment — no real charge**, and
    select **Pay ₩15,900 · demo**.
13. Verify a synthetic order ID is shown with
    **Demo payment successful · no real restaurant or courier was contacted**.

When the provider is limited, **Demo continuity mode** may appear. It must still use
catalog/domain results and keep the same dietary and pricing rules. The local launcher
always exercises this deterministic continuity boundary by design.

## 3. Focused UI regression checklist

Run these checks separately from the fast primary path when reviewing the redesign.

- **Language and country ordering:** change Language to `日本語`; Japan should move to
  the top of Country. Change it to `العربية`; Saudi Arabia, United Arab Emirates, and
  Egypt should appear before the alphabetical remainder.
- **Profile fields:** confirm there is no gender choice. Confirm Religion is optional,
  Vegan is available, and religion does not silently add dietary rules.
- **Three-level spice input:** confirm the only radio cards are **No heat**, **Medium**,
  and **Here for the heat**.
- **Address-first flow:** test **Hotel name**, **Booking image** with
  **Use stable demo booking image**, and **Road address**. Every mode must finish
  before chat opens and require an explicit confirmation or save action.
- **Simplified chat layout:** confirm the former
  `Discover | Choose | Deliver | Pay` bar and the right-side
  `Your context / Trust layer / Synthetic demo data` rail are absent.
- **Swipeable recommendations:** after the demo question, select
  **Find a different mild dish**. In **Grounded menu matches**, swipe horizontally on
  mobile or use **Previous menu** / **Next menu** on desktop; only one full card should
  be the reading focus at a time and the counter/dots should update.
- **Builder jump:** choose any recommendation and verify the viewport moves to
  **Order builder** without manual scrolling.
- **Risk override:** with shellfish allergy active, reach **Fish cake**. Confirm
  **Keep fish cake** is disabled with a reason, then select **Unlock option**. The
  unlocked label must still say server checks apply. Use **Remove fish cake** to
  complete the safe primary path.
- **Checkout readiness:** on Final review, verify quantity changes and item removal
  trigger server repricing. Dietary conflict and restaurant minimum must both affect
  `Ready to checkout`; payment stays disabled while either requirement fails.
- **Actionable errors:** invalid or stale actions must show a recovery instruction
  such as choosing all required options, removing a dietary-risk option, adding
  enough items for the minimum, or confirming the address again—not a raw server code.
- **Responsive presentation:** repeat onboarding and the menu carousel at 390 px
  mobile width and at a 1366 px presentation width. There should be no horizontal
  page overflow; horizontal movement is limited to the menu carousel.

## 4. Secondary product proof

- Ask: “Something warm and mild after walking in the rain, no pork and under
  15,000 won” to show constrained catalog retrieval and a chicken kalguksu result.
- Use **Compare mild rose options** to show price, ETA, portion, flavour, packaging,
  and dietary evidence on shared axes.
- On mock checkout select **Simulate failure**. The cart must remain unchanged; retry
  should complete without producing duplicate orders.
- Turn Vegan on during a fresh onboarding and verify recommendation/cart review uses
  the database-backed vegan filter. Unknown or unverified status must not be presented
  as verified vegan evidence.

## 5. Failure rehearsal and recovery

The local `/demo/control` page can exercise `force_genai_timeout`,
`force_payment_failure`, and `force_fallback`. After each rehearsal, restore `normal`
or reset the current synthetic session. Never delete catalog or migration data as a
demo reset.

For a local failure:

1. Read `.local-demo/backend.log` and `.local-demo/frontend.log`.
2. Check the health and readiness URLs printed by the launcher.
3. Press `Ctrl-C`, then run `make dev` again. The launcher will reuse the defaults if
   they are free or choose the next available ports.

For a deployed failure:

1. Check public `/healthz` and `/readyz`.
2. On the VM check `systemctl status yobi-api nginx`.
3. Inspect only recent structured logs; do not print environment values.
4. If the latest activation failed, run
   `sudo /opt/yobi/current/deploy/rollback.sh` to switch to the previous complete
   release and recheck health/readiness.

## 6. Manual local start, when required

Use two terminals only when debugging the launcher or intentionally changing ports.

Terminal 1:

```bash
APP_ENV=development \
DEMO_DB_BACKEND=sqlite \
DEMO_FALLBACK_ENABLED=true \
ADDRESS_OCR_PROVIDER=fixture \
OCI_GENAI_API_KEY= \
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
YOBI_API_PROXY_TARGET=http://127.0.0.1:8000 pnpm dev
```

For alternate ports, change the backend port and set
`YOBI_API_PROXY_TARGET` to the same backend origin before starting Vite.

## 7. Presenter truth statements

- “This is a synthetic-data MVP; it never contacts a real restaurant, courier, or
  payment processor.”
- For the deployed environment only: “The app uses the Oracle repository and Vector
  Search. Grok Function Calling is available, with deterministic continuity for
  provider limits using the same domain services.”
- For local verification only: “This run uses SQLite, fixture address extraction,
  and deterministic agent continuity; it is UI and domain-flow proof, not Oracle or
  live-provider proof.”
- “The current demo embeddings are deterministic 1,536-dimensional vectors, not
  Cohere-generated production embeddings.”
- “The public HTTP deployment is a presentation environment, not a production
  commerce service.”
