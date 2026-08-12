# YOBI mobile UI direction

> Current flow authority: [`../STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md`](../STRUCTURED_RECOMMENDATION_IMPLEMENTATION_PLAN.md).
> The older persistent-composer and free-form discovery direction is superseded.

The product should feel warm, editorial, and reassuring. It is a guided food-discovery
experience supported by an internal Wiki, not a conventional chat transcript and not
a dense delivery marketplace catalog.

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

The post-address experience has four explicit surfaces:

1. **Select** — category sections with multi-select chips, selected-summary tags,
   halal/vegan toggles, and a five-level KR/US spice guide.
2. **Prepare** — short retrieval and generation progress states. No conversational
   typing indicator or fake back-and-forth transcript.
3. **Decide** — ordered recommendation cards with reasons, encyclopedia-style Wiki
   prose, price/ETA/spice facts, dietary state, expandable evidence, comparison, and
   button follow-ups.
4. **Order** — the existing option builder, cart, delivery, review, mock payment, and
   completion surfaces.

The recommendation area has no composer. Every supported follow-up is explicit:
**Choose this menu**, **Show different menus**, **Edit choices**, **Compare these
menus**, **View Wiki evidence**, and a distinct retry action after a failed/fallback
request. Delivery instructions remain a transaction-stage field and must not be
confused with recommendation input.

## Layout

- **Mobile:** compact sticky header, single-column category stack, summary tags,
  thumb-reachable sticky completion control, full-width result cards, and cart bottom
  sheet. Chips wrap without causing page-level horizontal scroll.
- **Desktop/presentation:** centered discovery/result column with enough width for
  side-by-side comparison. Evidence expands inside the associated result rather than
  in a persistent chat rail.
- **Loading:** preserve the selector/result shell so layout does not jump. Distinguish
  “checking available menus” from “reading the Wiki and preparing matches.”
- **Result actions:** keep primary menu selection visually dominant; group similar,
  compare, and edit as secondary actions.

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
- Similar menus preserve committed criteria; editing returns a copy of committed
  criteria to the selector.
- Respect `prefers-reduced-motion`; animation is limited to short opacity/translate
  transitions and expansion affordances.

## Trust and copy

- Use natural service language; do not place `DEMO`, `MOCK`, or `SYNTHETIC` badges on
  every selector or result card.
- Keep one quiet, persistent truth statement that restaurant/order information is
  prepared for the experience and that no real order or charge occurs.
- Halal certification and general “verified evidence” are visually distinct. Show
  certification scope when present, but never imply that the synthetic record proves
  a real restaurant's certification.
- Vegan `POSSIBLE_WITH_CHECKS` appears as a check-before-ordering caution, not a green
  verified badge.
- Allergy selection, allergy-risk badges, “allergy safe” copy, option allergy locks,
  and allergy checkout gates do not appear in the current public flow.
- Internal enum names and IDs never appear in user copy.

All state uses an icon plus explicit text; color alone is never the signal. Empty,
no-match, fallback, provider failure, catalog refresh, and state-version conflicts each
offer a specific next action without silently weakening the user's choices.
