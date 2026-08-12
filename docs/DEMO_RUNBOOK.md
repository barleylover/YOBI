# YOBI demo runbook

Audience: team members, presenters, and evaluators checking the current structured
recommendation flow from onboarding through mock order completion.

> Product-flow authority: [`STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`](STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md).
> The historical free-chat presentation script no longer applies. The current
> recommendation surface has no composer or allergy controls; users choose preferences
> and continue through buttons.

## 1. Choose the evidence boundary

### Local source verification

Use this for repeatable checks of the current working tree:

```bash
# First run, or after dependency changes
make setup

# Each local rehearsal
make dev
```

`make dev` waits for both services, opens the frontend on macOS, and keeps them
attached to the terminal. Set `YOBI_NO_OPEN=1` to suppress browser opening. The
launcher prints the actual ports; its normal endpoints are:

- frontend: `http://127.0.0.1:5173`
- backend health: `http://127.0.0.1:8000/healthz`
- backend readiness: `http://127.0.0.1:8000/readyz`
- logs: `.local-demo/backend.log` and `.local-demo/frontend.log`

This path uses SQLite, fixture address extraction, deterministic embeddings, and no
OCI credentials. It can verify the UI, persistence, objective filtering,
evidence-pool contract, labelled saved-search fallback, and mock ordering flow. The
normal model-selected result path is exercised with a fake provider in tests, not by
the default `make dev` process. Neither path proves live model quality. Local work does
not verify Oracle Vector Search, OCI GenAI, Nginx/systemd, a real restaurant, payment,
courier, or public-network behavior.

### Oracle, OCI, and public verification

Do not present the historical 2026-08-09 release as evidence for the current v2
structured flow. This revision still requires a separate release-specific run of
migration `010`, seed/readiness verification, live Oracle vector queries, one-call OCI
generation, and public browser E2E. The exact gate is in
[`OCI_DEPLOYMENT.md`](OCI_DEPLOYMENT.md), and only completed results belong in
[`TEST_REPORT.md`](TEST_REPORT.md).

Before any deployed rehearsal, reconfirm both `/healthz` and `/readyz` and the exact
active release identifiers. Never print `/etc/yobi/yobi.env` or other secret values.

## 2. Primary structured recommendation walkthrough

Allow roughly two minutes from the welcome screen to the order builder.

1. Open a fresh browser session. On the welcome screen, point out that YOBI combines
   an internal food Wiki with the user's selections, then choose **Get started!**.
2. Choose a language and country, then continue. These values control presentation
   and may provide soft cultural context; they do not activate halal, vegan, or any
   religious rule.
3. On the information form, choose age/religion only if desired, enter favorite foods
   if useful, and confirm a delivery address. There is no allergy input or spice input
   on this profile form.
4. Accept the experience-data consent and confirm the address candidate. The app
   opens **What sounds good?** / **어떤 음식이 끌리세요?**, not a chat composer.
5. Select at least one visible food-preference chip. Show that several values can be
   selected within cuisine, flavor, main ingredient, form, temperature, price,
   texture, or cooking method. Values within one category are alternatives (`OR`);
   each selected category contributes to the match (`AND`).
6. Optionally enable **Only show halal-certified restaurants** or **Look for vegan
   options**. These are explicit current-meal choices. Halal and pork, or vegan and a
   selected animal main ingredient, produce an actionable conflict before submission.
7. Set the hottest level the user is comfortable eating on the five-level scale.
   Switch between Korean and US examples to show that examples are selection guides,
   not a universal measurement conversion.
8. Before pressing **Show my recommendations**, point out that selection changes have
   not called the generation endpoint and that there is no recommendation text box.
9. Choose **Show my recommendations**. The server first checks service area,
   availability, base price, spice, halal scope, and vegan conflicts, then retrieves a
   broad Wiki evidence pool. With a configured provider, one bounded generation
   request may select and explain the final menus from that pool. The default local
   launcher has no provider credentials, so it should instead show the distinctly
   labelled **Closest matching menus** saved-search fallback without a second call.
10. On the result screen, open **View Wiki evidence**. The prose should read like food
    encyclopedia material and must not expose internal chunk/menu IDs or describe
    general Wiki knowledge as the restaurant's exact recipe.
11. Use **Compare these menus** if more than one result is present. Then demonstrate
    either **Show different menus**, which preserves conditions and excludes already
    shown history, or **Edit choices**, which returns to the selector.
12. Choose **Choose this menu**. The app records a snapshot-backed selection event and
    scrolls to the existing order builder; it does not send a chat turn or another
    generation request.
13. Complete required options and choose **Add to cart**. If desired, use **Yes, show
    more menus** to add another item from the same merchant, then continue to delivery.
14. Confirm delivery details, review the server-priced cart, and proceed through the
    explicitly mock payment. A successful screen represents only a synthetic order;
    no restaurant, courier, or payment processor is contacted.

The UI uses ordinary service copy. The quiet common notice—restaurant/order
information is prepared for this experience and no real order or charge occurs—is the
truth boundary; cards do not repeat loud `DEMO`, `MOCK`, or `SYNTHETIC` badges.

## 3. Recommendation contract checks

Use a fresh session for each focused check.

- **No composer or legacy calls:** on the selector, `getByRole("textbox")` should find
  no recommendation field. Selecting or clearing chips must not call `/messages`,
  `/messages/stream`, or `/recommendations`. Submission makes one `INITIAL`
  recommendation request.
- **Selection semantics:** choose two chips in one category and at least one in a
  second category. Result evidence may match either value from the first category but
  a normal generated result must reference both active categories. Inspect whether
  the passages genuinely support those labels; ID coverage alone is only structural
  grounding. A labelled search fallback is a proximity result and makes no all-facets
  guarantee.
- **Five-level spice:** every reference choice and result card uses `1..5`; no current
  selector or recommendation card should display a three-level scale or `/3`.
- **Dietary boundary:** only halal and vegan appear in the recommendation selector.
  Allergy fields, allergy-safe claims, option allergy locks, and allergy checkout
  blocks must be absent.
- **No inferred filter:** changing country, language, or optional religion must not
  silently toggle halal or vegan.
- **Halal scope:** when halal-only is selected, every result must have current
  merchant/menu certification evidence. Treat the repository's certification rows as
  synthetic experience data, not proof about a real business.
- **Vegan caution:** confirmed animal conflicts must not be returned. A menu whose
  compatibility depends on choices may remain with a check-before-ordering warning;
  that warning is not certification or a safety guarantee.
- **No hidden relaxation:** an empty match shows which categories could not be met and
  offers **Edit choices**. It must not silently increase price/spice or disable a
  dietary condition.
- **Model order:** a normal result preserves the ranks returned by the validated
  single generation response. Retrieval score is not shown as final rank.
- **Compare/evidence:** opening comparison or Wiki evidence uses the already received
  snapshot/menu payload in the browser. It must not call generation or write a
  `COMPARE_MENUS` event in the current structured UI.
- **Search fallback:** a provider timeout or invalid response may show **Closest
  matching menus** from the saved pool. The copy must identify search results, and the
  server must not issue a second generation call.
- **Default local boundary:** `make dev` intentionally has no OCI credentials, so the
  fallback above is the expected local result. A normal `RECOMMENDED` result in local
  automated tests comes from an injected fake provider and is not live-model evidence.
- **Similar:** **Show different menus** sends one new `SIMILAR` request, keeps the
  committed criteria, and does not redisplay server-recorded shown/rejected/selected
  menus when alternatives exist.
- **Reload recovery:** reload while a request is pending and after results are shown.
  The criteria, active request/result, snapshot, and chosen menu must come from server
  hydration, not a reconstructed browser-only answer. A completed-request read may
  refresh current price, fee/ETA, halal, or vegan state and remove a newly stale menu;
  it must not call generation or rewrite the stored model output.
- **Replay:** resubmitting the same stable request identity recovers the saved state
  and must not produce a second generation dispatch. A new explicit retry uses a new
  request ID.
- **Interrupted owner:** a stale reservation that never reached generation becomes a
  `RETRIEVAL_OWNER_LOST` failure instead of remaining pending. A stale post-dispatch
  request becomes an unknown result and is never automatically redispatched.

## 4. Localization and responsive checks

- Run the main path in English and Korean. Confirm selector labels, halal/vegan copy,
  five-level references, result actions, order controls, and errors use the selected
  locale. Proper names may retain catalog text.
- Spot-check one right-to-left locale to ensure direction, chip wrapping, evidence,
  and action bars remain usable.
- Repeat at 390 px mobile and 1366 px presentation widths. There should be no page-
  level horizontal overflow, and the sticky completion/result controls must not cover
  focused fields or buttons.
- Switch KR/US spice references without changing the selected numeric ceiling. The
  country examples are explanatory labels, not separate filter values.
- Edit the profile and return to the same session. Current criteria, result, selected
  menu, and cart should remain recoverable unless an explicit change invalidates them.

## 5. Ordering and failure recovery

- Required menu-option, server pricing, single-merchant cart, delivery confirmation,
  cart-version fingerprint, restaurant minimum, mock checkout, failure/retry, and
  duplicate-order protections remain regression requirements.
- For a v2-selected menu, cart review and checkout use the committed current-meal
  halal/vegan/price/spice criteria and current service area. Retained legacy profile
  allergy or religion fields must not silently block or activate a v2 rule.
- If a selected menu's price alone moved outside the original band, it remains
  selectable at the current server price. Cart review should show an updated-total
  warning without a dietary block, and the repriced fingerprint must be confirmed
  before checkout.
- Selecting a result and updating options do not invoke the recommendation generator.
- A mock payment failure must leave the cart recoverable; retry must not create two
  orders for the same confirmed cart version.
- Use the token-protected `/api/v1/demo/failure-mode` endpoint only for supported
  local failure rehearsal. Restore `normal` afterward. Do not delete catalog, release,
  or migration data as a reset.

For local failures, read the printed logs and endpoint status, stop `make dev` with one
`Ctrl-C`, and restart it. For a deployed failure, inspect health/readiness and recent
sanitized service logs. If activation failed, follow the exact rollback procedure in
[`OCI_DEPLOYMENT.md`](OCI_DEPLOYMENT.md); never reverse or delete applied additive
migrations.

## 6. Manual local start

Use two terminals only when debugging the launcher or choosing ports explicitly.

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

## 7. Accurate presenter statements

- “You choose the qualities you want instead of steering an open-ended chat.”
- “The server first checks objective conditions and retrieves a broad set of internal
  Wiki evidence; one model request then chooses and explains the final menus only from
  that set.”
- “The food Wiki keeps essential facts structured and subjective descriptions as
  natural encyclopedia-style prose.”
- “Halal filtering uses certification-shaped records and vegan results can carry a
  check-before-ordering warning. The current merchant and certification data is
  synthetic experience data, not a claim about real restaurants.”
- “This flow does not provide allergy filtering or allergy-safety guarantees.”
- “No real restaurant, courier, payment processor, or Yogiyo integration is contacted.”
- For local runs: “This is SQLite and deterministic-embedding contract evidence, not
  proof of Oracle Vector Search or a live generation provider.”
- Only after a new deployment gate passes: state the exact release, Oracle, provider,
  and public evidence recorded in `TEST_REPORT.md`.
