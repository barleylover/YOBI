# YOBI demo runbook

Audience: a team member, presenter, or evaluator checking the current YOBI UI from
onboarding through mock order completion. This runbook follows the redesigned flow:
the mobile welcome screen fits without scrolling, onboarding is split into locale and
profile steps, the delivery address is confirmed before recommendations, and the
same-restaurant add-on loop preserves one-merchant checkout.

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

`TEST_REPORT.md` records chatbot-improvement release
`20260809T084353Z-704f74712d9d` as the current verified public boundary. Reconfirm
`/readyz` before a presentation; an HTTP `200` alone is insufficient unless the exact
catalog, active knowledge release, and all readiness checks also match the report.

## 2. Chatbot quality and primary ordering proof

### Multi-turn chatbot quality proof

Use ordinary free-form chat, not **Try the demo question** or the two fixed content
shortcuts, for this check.

1. Start a fresh confirmed-address session and send `hi`. YOBI must greet or ask a
   useful first question. No menu recommendation card or recommendation snapshot may
   appear.
2. Send `I don't know yet`. YOBI must continue need discovery without treating the
   absence of a preference as permission to recommend.
3. In another fresh session send `No soup and no pork. Ask me questions first.` The
   turn must stay in recommendation-hold mode with no cards.
4. Send `I would like something warm, savory and chewy.` The new preferences and both
   negative constraints must coexist in server state; hold still prevents cards.
5. Send `Actually soup is okay, but still no pork.` Soup must leave the exclusion
   list while pork remains. No unrelated preference may disappear.
6. Send `Recommend something mild under 12,000 won now.` A grounded menu carousel may
   now appear. Every card must meet the budget and spice limit, avoid the remaining
   pork constraint, and be marked as synthetic demo data.
7. Reject one shown card, select another, and refresh the page. The UI must hydrate
   the latest server conversation/snapshot instead of restoring a different
   browser-only choice. A repeated event must not duplicate state changes.
8. Ask `Explain the menu I selected.` The answer must distinguish general synthetic
   Wiki description from menu-specific facts and unknowns. It must not show raw menu,
   claim, chunk, or tool IDs and must not create an unrelated recommendation carousel.

For a shorter readiness proof, send `I want something warm.` followed by
`Savory and chewy, please.` The first turn should ask a follow-up with no cards; the
second may recommend because three useful preference dimensions have accumulated.

If inspecting the API, `GET /api/v1/sessions/{id}/conversation` must show the same
`state_version`, cumulative `meal_need_state`, messages, and latest snapshot rendered
by the UI. This endpoint is a diagnostic truth source; do not expose its internal IDs
as presenter-facing food explanations.

### Primary new-UI demo

Allow about 60–90 seconds after the page opens.

1. On the no-scroll welcome screen, point out **Order K-food with context, not
   guesswork**, the three compact trust benefits, and the synthetic/no-charge
   boundary, then select **Get started!**. The welcome screen intentionally has no
   speech bubbles or neighbourhood tagline.
2. On locale step 1, keep **English** and **United States**, then select **Next**.
   Point out that Language has 16 choices, Country has 36 choices, and countries
   associated with the selected language appear first.
3. On the form-only profile step 2, keep age **25-34**, **Prefer not to say**, shellfish allergy
   **Severe**, spice **A little spice is fine**, and Vegan off. Show the expanded allergy
   list and explain that one shared severity applies to every selected allergy.
4. In **Delivery address**, keep **Hotel name** and
   `YOBI Myeongdong Hotel`. Accept the synthetic-session consent and select
   **Check delivery address**.
5. Select **Confirm & start** on the returned synthetic address candidate. The chat
   must open directly with YOBI's welcome message; the former delivery-context summary
   card is no longer shown.
6. Select the small **Try the demo question** action directly beneath that first YOBI
   message: “I saw people eating some red rice cake dish on
   the street. What is that? Can I order it?”
7. Show the classic tteokbokki risk evidence and the mild rose alternative. State
   that cross-contamination is unknown; the UI never labels the dish allergy-safe.
8. Select **Choose this menu** on **Mild rose tteokbokki**. The page must scroll
   directly to **Order builder**.
9. Choose **Mild**, **Regular**, **Add cheese**, and **Remove fish cake**. On the fish
   cake step, point out that **Keep fish cake** is initially disabled, explains the
   dietary risk, and offers **Unlock option** for an explicit override.
10. Review the Korean restaurant note, then select **Add to cart**. Verify the
    cart badge shows `1`.
11. At **Would you like anything else from this restaurant?**, select **Yes, show more
    menus**. Swipe the same-restaurant carousel, choose one menu, complete its options,
    and add it. Verify the badge shows `2` and the question appears again. Select
    **No, continue to delivery**.
12. Confirm **Hotel front desk**, **No bell**, and **No disposable cutlery** with
    **Confirm delivery details**. The address is not requested again because it was
    confirmed during onboarding.
13. In **Final review**, verify both readiness checks are green:
    **Dietary check** has no known hard conflict and **Restaurant minimum** is met.
    The canonical two-item path totals ₩24,900. Increase and decrease one item once
    and verify the badge follows the sum of quantities.
14. Select **Proceed to payment**, confirm **Demo payment — no real charge**, and
    select **Pay ₩24,900 · demo**.
15. Verify a synthetic order ID is shown with
    **Demo payment successful · no real restaurant or courier was contacted**.

For the multilingual proof, choose **한국어** and **South Korea** on step 1. From
profile step 2 onward, verify the form, address errors, chat/fallback cards, option
builder, cart readiness, payment and order confirmation all remain in Korean. Menu,
restaurant and hotel proper names may retain their catalog names.

When the provider is limited, **Demo continuity mode** may appear. It must still use
catalog/domain results and keep the same dietary and pricing rules. The local launcher
always exercises this deterministic continuity boundary by design.

### Chat-room menu proof

1. In chat, open **Chat menu** directly above the composer. Its closed-state chevron
   points upward and its open-state chevron points downward. Confirm the three
   localized actions are **Weekly ranking**, **K-POP Demon Hunters**, and
   **Edit my information**.
2. Select **Weekly ranking**. The assistant must return the fixed order **BBQ, BHC,
   No More Pizza, Hong Kong Banjeom, Yeopgi Tteokbokki** with one horizontally
   swipeable nearby menu card for each rank.
3. Choose a ranked menu and complete its options. These preset cards use the same
   server-priced Order Builder and cart as ordinary recommendations.
4. Open **Chat menu** again and select **K-POP Demon Hunters**. Confirm the fixed food
   order **Gimbap, Gukbap, Hotteok, Seolleongtang, Eomuk** and swipe all five cards.
5. Select **Edit my information**. Confirm the current profile and delivery address
   are prefilled, change one item, and select **Save changes**. The same chat, cards,
   cart quantity, and draft are preserved on return. If an allergy change conflicts
   with the cart, Final review must refresh from the server and disable payment.

The two content shortcuts are intentionally deterministic demo turns. They do not
calculate rankings, fetch live delivery data, or invoke the LLM; ordinary free-form
chat continues to use the Agent Loop and its deterministic continuity path.

## 3. Focused UI regression checklist

Run these checks separately from the fast primary path when reviewing the redesign.

- **Language and country ordering:** change Language to `日本語`; Japan should move to
  the top of Country. Change it to `العربية`; Saudi Arabia, United Arab Emirates, and
  Egypt should appear before the alphabetical remainder.
- **Profile fields:** confirm there is no gender choice. Confirm Religion is optional,
  Vegan is available, and religion does not silently add dietary rules.
- **Three-level spice input:** confirm the only radio cards are **Not spicy at all**,
  **A little spicy**, and **I love spicy food**. Menu cards and profile context use
  the same 1–3 scale; no `/5` label remains.
- **Language continuity:** select a non-English locale and confirm profile step 2,
  chat navigation, order controls, payment and completion switch with it.
- **Expanded allergies:** select several allergies and confirm only one shared
  severity selector appears. Known positive allergen tags are server hard conflicts
  for a severe profile; the verified-absence shellfish rule remains stricter.
- **Address-first flow:** test **Hotel name**, **Booking image** with
  **Use stable demo booking image**, and **Road address**. Every mode must finish
  before chat opens and require an explicit confirmation or save action.
- **Simplified chat layout:** confirm the former
  `Discover | Choose | Deliver | Pay` bar and the right-side
  `Your context / Trust layer / Synthetic demo data` rail are absent.
- **Chat-room menu:** confirm the bottom menu opens and closes without losing the
  composer draft, each content action inserts one user turn and one fixed assistant
  collection, and repeated taps are disabled while a response is in flight.
- **Profile edit return:** edit an existing profile from chat without creating a new
  session. Confirm current address reuse, language propagation, chat/card restoration,
  cart quantity preservation, and server revalidation of dietary conflicts.
- **Swipeable recommendations:** after the demo question, select
  **Find a different mild dish**. In **Grounded menu matches**, swipe horizontally on
  mobile or use **Previous menu** / **Next menu** on desktop; only one full card should
  be the reading focus at a time and the counter/dots should update.
- **Builder jump:** choose any recommendation and verify the viewport moves to
  **Order builder** without manual scrolling.
- **Same-restaurant loop:** after adding an item, choose **Yes** and verify only menus
  from the selected restaurant appear. Add a second item, confirm the question repeats,
  then choose **No**. The cart badge is the sum of quantities, not distinct lines.
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
   `sudo /opt/yobi/current/deploy/rollback.sh` to switch to the exact previous
   health-verified release recorded by deployment, then recheck health/readiness.
   The script refuses incomplete or unverified release directories and does not
   reverse additive database migrations.

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
