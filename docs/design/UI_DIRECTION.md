# YOBI mobile UI direction

Stitch was not available in the current toolset, so this direction is implemented directly as a token-based React component system.

## Product feel

Warm, editorial, and reassuring without looking clinical. The chat is the application; rich cards support decisions without turning the experience into a conventional delivery-app catalogue.

## Tokens

- Canvas: warm ivory `#FFF9F4`
- Surface: white `#FFFFFF`
- Ink: deep aubergine `#24151F`
- Primary coral: `#F64675`
- Primary pressed: `#D92F60`
- AI purple: `#7057D9`
- Verified teal: `#087C70`
- Risk amber: `#A65A00`
- Unknown slate: `#667085`
- Critical red: `#B42318`
- Radius: 16/22/28px hierarchy
- Touch target: at least 44px

## Layout

- Mobile: sticky compact header, inline conversation cards, persistent composer, cart bottom sheet.
- Desktop/presentation: conversation column plus a right evidence/progress rail; typography remains large enough for a projector.
- Risk states always include an icon and explicit text, never colour alone.

## Interaction

- Ask one decision at a time.
- Display progress before remote work begins.
- Use quick replies for bounded choices and natural language for discovery and corrections.
- Respect `prefers-reduced-motion`; animations are short opacity/translate transitions only.

