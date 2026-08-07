# Data model

The Oracle schema is created only by the sequential SQL migration runner. Runtime
FastAPI uses `YOBI_APP`; `ADMIN` is rejected by configuration validation.

Core catalog tables are `MERCHANT`, `MENU`, `MENU_OPTION_GROUP`,
`MENU_OPTION_ITEM`, `REVIEW_SNIPPET`, `EVIDENCE`, `MENU_KNOWLEDGE`, and
`ADDRESS_PLACE`. Runtime state is held by `USER_PROFILE`, `CHAT_SESSION`,
`CHAT_MESSAGE`, `ADDRESS_REF`, `CART`, `CART_ITEM`, `DELIVERY_PREFERENCE`,
`MOCK_CHECKOUT`, and `MOCK_ORDER`. `AUDIT_LOG` is the safe operational event sink;
`SCHEMA_MIGRATION` records filename, SHA-256 checksum, and application time.

`MENU`, `REVIEW_SNIPPET`, and `MENU_KNOWLEDGE` use
`VECTOR(1536, FLOAT32)`. Every vector stores model, dimension, and version metadata.
Production search first applies SQL filters, then ranks remaining rows with
`VECTOR_DISTANCE(..., COSINE)`. Severe shellfish profiles require explicit
`shellfish_sauce_absent` evidence before a menu can enter the candidate set. Other
supported severe allergies hard-filter known positive allergen tags. Profiles, menus
and categories share one three-level spice contract: 1 not spicy, 2 moderately spicy,
3 very spicy.

The deterministic seed produces exactly 20 categories, 30 merchants, 150 menus, 600 review
snippets, 300 evidence rows, at least 250 option items, and 20 hotels. All are marked
synthetic. Fixed demo identifiers include:

- `menu_002_01`: classic tteokbokki, spice 3, shellfish risk signal.
- `menu_001_01`: mild rose tteokbokki, spice 1, sauce shellfish absent, kitchen
  cross-contamination unknown.
- `menu_001_02`: second same-restaurant, spice-1 synthetic menu with explicit
  shellfish-sauce absence evidence for the add-on carousel demo.
- `menu_003_01`: gentle chicken kalguksu.
- `menu_021_01`–`menu_025_01`: fixed weekly ranking cards for BBQ, BHC,
  No More Pizza, Hong Kong Banjeom, and Yeopgi Tteokbokki.
- `menu_026_01`–`menu_030_01`: fixed K-POP Demon Hunters food cards for gimbap,
  gukbap, hotteok, seolleongtang, and eomuk.
- `hotel_demo_01`: synthetic Myeongdong hotel fixture.

`--upsert` is the safe default seed mode. `--fresh` deletes only deterministic
catalog rows in the app schema and is never called by deployment automation.
Migration `004_three_level_spice.sql` maps existing 0–5 values to 1–3 and replaces
only the related check constraints; earlier migrations remain immutable.
