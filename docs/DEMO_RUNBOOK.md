# YOBI demo runbook

Audience: team members, presenters, and evaluators checking the current structured
recommendation flow from the combined welcome/locale screen through the explicit
Yogiyo-handoff mock. Mock checkout and synthetic-order completion are backend release
checks, not browser presentation steps.

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
OCI credentials. It can verify the UI, persistence, objective filtering, reviewed
support, server-owned ranking, deterministic explanation fallback, and backend mock
ordering contract. The provider-authored explanation path is exercised with a fake
provider in tests, not by the default `make dev` process. The server freezes the same
menu IDs/order in both paths. Neither path proves live model quality. Local work does
not verify Oracle Vector Search, OCI GenAI, Nginx/systemd, a real restaurant, payment,
courier, or public-network behavior.

### Oracle, OCI, and public verification

Do not present the historical 2026-08-09 release as evidence for the current v2
structured flow. The 2026-08-12 release separately passed migration `010`,
seed/readiness verification, live Oracle vector queries, one-call OCI generation,
public browser E2E, and rollback/redeploy. The repeatable gate is in
[`OCI_DEPLOYMENT.md`](OCI_DEPLOYMENT.md), and the exact completed evidence belongs in
[`TEST_REPORT.md`](TEST_REPORT.md).

Before any deployed rehearsal, reconfirm both `/healthz` and `/readyz` and the exact
active release identifiers. Never print `/etc/yobi/yobi.env` or other secret values.

## 2. Primary structured recommendation walkthrough

Allow roughly two minutes from the welcome screen to the handoff mock.

1. Open a fresh browser session. The welcome card already contains language and
   country controls. Point out that language controls presentation only, choose the
   locale/country, and continue. No locale or nationality choice activates halal,
   vegan, spice, or a religious rule.
2. On the next screen, accept the experience-data consent and confirm a supported
   synthetic delivery address by hotel search or the demo booking image. There are no
   age, religion, favorite-food, allergy, or profile-spice questions. The UI may send
   neutral placeholders only to preserve the additive legacy profile schema.
3. After address confirmation, identify the common navigation control for **Food
   rankings** and the **K-POP Demon Hunters** food feature, then open the structured
   selector. There is no recommendation composer.
4. Select at least one visible food-preference chip. Show that several values can be
   selected within cuisine, flavor, main ingredient, form, temperature, price,
   texture, or cooking method. Values within one category are alternatives (`OR`);
   each selected category contributes to the match (`AND`).
5. Read the capability status next to halal, vegan, and five-level spice. In an
   external-catalog release without formal certification, reviewed menu ingredients,
   or reviewed spice values, these controls are disabled with a visible reason. Do not
   present disabled as a negative fact about a menu. In the synthetic fixture, when a
   capability is enabled, the user may explicitly select it; country/religion never
   enables it silently.
6. Before pressing **Show my recommendations**, point out that selection changes have
   not called the generation endpoint and that there is no recommendation text box.
7. Choose **Show my recommendations**. The server applies objective/capability-aware
   filters, joins reviewed concept support, computes a versioned score/diversity, and
   freezes up to three menus before provider dispatch. One bounded request may explain
   exactly those menus; it cannot select or reorder them. The default local launcher
   shows a distinctly labelled deterministic explanation fallback for the same frozen
   menus without a second call.
8. The result appears as a YOBI chat response with one menu card visible at a time.
   Swipe or use the previous/next controls to inspect the carousel; the visual order is
   the frozen server order.
9. Open **View Wiki evidence**. The prose should read like general food
   encyclopedia material and must not expose internal chunk/menu IDs or describe
   general Wiki knowledge as the restaurant's exact recipe.
10. Use **Compare these menus** if more than one result is present. The first action
    may make one separate bounded comparison-writing call and an exact replay uses its
    cached response. It does not change ranking or write a legacy compare event. Then demonstrate
    either **Show different menus**, which preserves conditions and excludes already
    shown history, or **Edit choices**, which returns to the selector.
11. Optionally open **Food rankings**. Point out the `demo_basis`: external ranking
    uses source menu/merchant review counts, order/popularity are derived demo proxies,
    and only source-less synthetic fixture rows use stable ID-derived values. No view is
    a live Yogiyo-wide statistic. The English top 10 keeps metric order while preventing
    one merchant from filling the list. Open the K-POP feature and show the fixed
    Gimbap, Tteokbokki, Hotteok, Naengmyeon, and Eomuk trail. Its story source is linked,
    its general food copy is not a merchant recipe, and an unavailable nearby match is
    shown honestly instead of being replaced.
12. Choose **Choose this menu**. The app records a snapshot-backed selection event and
    scrolls to the existing order builder; it does not send a chat turn or another
    generation request.
13. Complete required options and choose **Add to cart**. If desired, use **Yes, show
    more menus** to add another item from the same merchant, then continue to delivery.
14. Confirm delivery details, review the server-priced cart, and continue to the
    explicit Yogiyo-handoff mock. Activating the handoff control changes only local UI
    state: it does not open Yogiyo, submit an order, or process payment. Backend mock
    checkout/order endpoints are exercised separately by the release smoke.

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
  second category. Reviewed support may match either value from the first category,
  but a candidate must have support for both active categories. The provider only
  explains the already frozen result. Inspect whether the passages genuinely support
  those labels; ID coverage alone is only structural grounding.
- **Five-level spice:** every reference choice and result card uses `1..5`; no current
  selector or recommendation card should display a three-level scale or `/3`.
- **Capability boundary:** only halal and vegan appear as dietary controls, and spice
  is a separate exact control. When the catalog returns `enabled=false`, the control
  is disabled, its reason is visible, and stale criteria are cleared to neutral values.
  Unknown coverage is not a positive or negative menu fact.
- **Dietary boundary:** only halal and vegan appear in the recommendation selector.
  Allergy fields, allergy-safe claims, option allergy locks, and allergy checkout
  blocks must be absent.
- **No inferred filter:** changing country or language must not
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
- **Server order:** a normal result and fallback preserve the pre-provider frozen
  server ranks. Provider output cannot replace or reorder a menu.
- **Compare/evidence:** Wiki evidence expands locally and calls no provider. Comparison
  uses `/recommendation-comparisons`, may make one separate call for a new
  idempotency key, caches the result, falls back deterministically, and writes no
  `COMPARE_MENUS` event.
- **Explanation fallback:** a provider timeout, `NO_MATCH`, or invalid response shows
  the same frozen menus with clearly distinguished deterministic explanation. The
  server must not issue a second recommendation-generation call.
- **Default local boundary:** `make dev` intentionally has no OCI credentials, so the
  fallback above is the expected local result. A provider-authored result in local
  automated tests comes from an injected fake provider and is not live-model evidence.
- **Similar:** **Show different menus** sends one new `SIMILAR` request, keeps the
  committed criteria, and does not redisplay server-recorded shown/rejected/selected
  menus when alternatives exist.
- **Reload recovery:** reload while a request is pending and after results are shown.
  The criteria, active request/result, snapshot, and chosen menu must come from server
  hydration, not a reconstructed browser-only answer. A completed-request read may
  refresh current price, fee/ETA, halal, or vegan state and remove a newly stale menu;
  it must not call generation or rewrite the stored explanation output.
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
  country examples are explanatory labels, not separate filter values. If the active
  catalog disables spice, verify both the scale and reference switch are unavailable
  with an explanatory message.
- Edit the profile and return to the same session. Current criteria, result, selected
  menu, and cart should remain recoverable unless an explicit change invalidates them.

## 5. Ordering and failure recovery

- Required menu-option, server pricing, single-merchant cart, delivery confirmation,
  cart-version fingerprint, restaurant minimum, mock checkout, failure/retry, and
  duplicate-order protections remain backend regression requirements. The public UI
  stops at the Yogiyo-handoff mock.
- For a v2-selected menu, cart review and checkout use the committed current-meal
  halal/vegan/price/spice criteria and current service area. Retained legacy profile
  allergy or religion fields must not silently block or activate a v2 rule.
- If a selected menu's price alone moved outside the original band, it remains
  selectable at the current server price. Cart review should show an updated-total
  warning without a dietary block, and the repriced fingerprint must be confirmed
  before checkout.
- Selecting a result and updating options do not invoke the recommendation generator.
- In backend smoke/tests, a mock payment failure must leave the cart recoverable;
  retry must not create two orders for the same confirmed cart version.
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
- “The server checks objective conditions and reviewed support, freezes up to three
  menu IDs and their order, and one model request can only explain those menus.”
- “The food Wiki keeps essential facts structured and subjective descriptions as
  natural encyclopedia-style prose.”
- “Halal, vegan, and spice controls stay unavailable when the active catalog lacks
  enough reviewed coverage; unknown data is never presented as verification.”
- “Merchant/menu/price/option rows come from a versioned public-web snapshot, while
  the general food Wiki, derived mappings, demo ranking proxies, address, payment, and
  order layers are explicitly synthetic or mock.”
- “This flow does not provide allergy filtering or allergy-safety guarantees.”
- “The handoff is local presentation only; no real restaurant, courier, payment
  processor, Yogiyo URL, or Yogiyo API is contacted.”
- For local runs: “This is SQLite and deterministic-embedding contract evidence, not
  proof of Oracle Vector Search or a live generation provider.”
- Only after a new deployment gate passes: state the exact release, Oracle, provider,
  and public evidence recorded in `TEST_REPORT.md`.
