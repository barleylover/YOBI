# YOBI mobile UI direction

> Current flow authority: [`../STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`](../STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md).
> The older persistent-composer and free-form discovery direction is superseded.

The product should feel warm, editorial, and reassuring. It is a guided food-discovery
experience supported by an internal Wiki. Recommendations use a familiar chat-bubble
presentation and one-card carousel, but there is no free-text composer or fake
back-and-forth transcript and the page is not a dense delivery marketplace catalog.

## Tokens

- Canvas: warm ivory `#FFF9F4`
- Surface: white `#FFFFFF`
- Ink: deep aubergine `#24151F`
- Primary coral: `#F64675`
- Primary pressed: `#D92F60`
- AI/Wiki purple: `#7057D9`
- Certification teal: `#087C70`
- Caution amber: `#A65A00`
- Unknown slate: `#667085`
- Critical red: `#B42318`
- Radius hierarchy: `16 / 22 / 28px`
- Minimum touch target: `44px`

## Information architecture

The product flow has six explicit surfaces:

1. **Welcome + locale** — the brand introduction, benefit summary, language, country,
   and primary CTA share one responsive card.
2. **Address** — consent plus hotel search or booking-image lookup against the fixed
   supported synthetic demo address. No demographics, favorite-food, allergy, or profile-spice
   form appears.
3. **Select + discover** — category sections with multi-select chips and selected-
   summary tags. Halal/vegan and five-level KR/US spice controls remain visible only as
   release-aware capabilities and are disabled with reasons when unsupported. The
   common navigation also opens demo food rankings and the K-POP Demon Hunters food
   feature.
4. **Prepare** — short eligibility, ranking, and explanation progress states. No conversational
   typing indicator or fake back-and-forth transcript.
5. **Decide** — a YOBI response bubble with one server-ranked card visible at a time,
   carousel controls, reasons, encyclopedia-style Wiki prose, price/ETA/spice facts,
   supported dietary state, expandable evidence, comparison, and button follow-ups.
6. **Options → handoff** — option builder, cart, delivery, review, and an explicit local
   Yogiyo-handoff mock. No payment-success or order-complete surface is public.

The recommendation area has no composer. Every supported follow-up is explicit:
**Choose this menu**, **Show different menus**, **Edit choices**, **Compare these
menus**, **View Wiki evidence**, and a distinct retry action after a failed/fallback
request. Delivery instructions remain a transaction-stage field and must not be
confused with recommendation input.

## Layout

- **Mobile:** compact sticky header, single-column category stack, summary tags,
  thumb-reachable sticky completion control, one-card snap carousel, and cart bottom
  sheet. Chips and comparison copy wrap without causing page-level horizontal scroll.
- **Desktop/presentation:** centered discovery/result column with enough width for
  side-by-side comparison. Evidence expands inside the associated result rather than
  in a persistent chat rail.
- **Loading:** preserve the selector/result shell so layout does not jump. Distinguish
  “checking available menus” from “reading the Wiki and preparing matches.”
- **Result actions:** keep primary menu selection visually dominant; group similar,
  compare, and edit as secondary actions.
- **Common navigation:** keep the post-address navigation at one predictable edge,
  trap focus inside its dialog, close on `Escape`, and restore focus to the trigger.
  Ranking/feature content scrolls inside the dialog rather than expanding the page.

## Interaction

- Same-category chips are independently toggleable and communicate multi-select.
- Show a concise selected summary and allow category-level and global clearing.
- Block submission only for empty criteria, unsupported catalog values, or explicit
  conflicts such as halal+pork and vegan+animal main ingredient.
- Changing preference chips, halal/vegan, or the spice guide performs no generation
  request. Generation begins only after the explicit completion action.
- Switching KR/US examples keeps the numeric maximum unless the user changes it.
- A catalog reload must preserve supported selections and visibly identify/remove any
  code no longer served by the active catalog.
- A capability with `enabled=false` disables its control, renders the server reason,
  clears a stale selected value, and submits the neutral value. Disabled means
  insufficient reviewed coverage, not that a menu passed or failed the condition.
- Similar menus preserve committed criteria; editing returns a copy of committed
  criteria to the selector.
- Comparison may request one separately cached, grounded comparison for the current
  2-3-menu snapshot. It never changes server rank; Wiki expansion stays local.
- Respect `prefers-reduced-motion`; animation is limited to short opacity/translate
  transitions and expansion affordances.

## Trust and copy

- Use natural service language; do not place `DEMO`, `MOCK`, or `SYNTHETIC` badges on
  every selector or result card.
- Keep one quiet, persistent truth statement that merchant/menu fields come from a
  versioned public-web catalog while general Wiki/mapping/ranking-proxy/address/order
  layers have explicit demo boundaries, and that no real order or charge occurs.
- Halal certification and general “verified evidence” are visually distinct. Show
  certification scope when present, but never imply that the synthetic record proves
  a real restaurant's certification.
- Vegan `POSSIBLE_WITH_CHECKS` appears as a check-before-ordering caution, not a green
  verified badge.
- Allergy selection, allergy-risk badges, “allergy safe” copy, option allergy locks,
  and allergy checkout gates do not appear in the current public flow.
- Internal enum names and IDs never appear in user copy.
- Ranking copy always exposes its demo basis and never says the proxy is a live
  Yogiyo-wide ranking. The five-food feature describes general dishes and nearby
  mapped menus, never a verified restaurant recipe.
- `yobi-gimbap-feature-hero.png` is an AI-generated local YOBI asset created with
  OpenAI ImageGen on 2026-08-16, not an external hotlink or reference asset. It uses
  fictional people and no franchise characters, text, or logos; it supports the food
  feature without implying official franchise artwork.

All state uses an icon plus explicit text; color alone is never the signal. Empty,
no-match, fallback, provider failure, catalog refresh, and state-version conflicts each
offer a specific next action without silently weakening the user's choices.
