# 2026-08-17 food-Wiki expansion and final deployment evidence

This record separates authored general food knowledge, derived menu-name mapping,
live provider observations, deterministic remediation, and final deployment. It does
not claim that a general Wiki passage proves a restaurant's recipe, certification,
allergens, or menu-level spice.

## Delivered scope

- Added 84 reviewed general-food Wiki documents, growing the active release from 114
  to 198 concepts/documents and from 1,299 to 1,551 public chunks.
- Added Japanese, Italian, American/grill, Southeast Asian, Mexican, and carefully
  bounded Chinese extensions alongside the existing Korean/Chinese foundation.
- Optimized the public cuisine choices to Korean, Chinese, Southeast Asian, Mexican,
  Japanese, Italian, and American & grill. Food-form shortcuts also include
  bowl/poke, dessert/bakery, and fried snack.
- Kept every general Wiki row as `SYNTHETIC_WIKI/REVIEWED_DEMO`, every derived
  menu-name mapping as `YOBI_DERIVED_DEMO_MAPPING`, and every imported catalog fact as
  `YOGIYO_PUBLIC_WEB`.
- Excluded drinks/cafe items, sauces/seasonings, non-food promotions, and unsupported
  composite names from high-confidence meal mapping.

## Mapping and support result

| Measure | Previous active family | Expanded final family | Change |
|---|---:|---:|---:|
| High-confidence mapped menus | 1,955 | 3,922 | +1,967 |
| Concept-not-authored menus | 6,986 | 4,673 | -2,313 |
| Knowledge concepts/documents | 114 | 198 | +84 |
| Public Wiki chunks | 1,299 | 1,551 | +252 |
| Reviewed preference-support rows | 1,073 | 1,499 | +426 |

The final 15,085-menu classification is 3,922 high mappings, 4,673
concept-not-authored, 420 ambiguous names, 4,217 non-food/promotional items, and
1,853 unsupported composites. Classification coverage is exactly 15,085/15,085.

Expanded cuisine availability in the active service area:

| Cuisine option | Eligible menus | Merchants |
|---|---:|---:|
| Japanese | 241 | 35 |
| Italian | 272 | 21 |
| American & grill | 386 | 81 |
| Southeast Asian | 33 | 6 |
| Mexican | 33 | 4 |

## Exactly five live quality observations

The user limited the expanded-release live validation to exactly five provider
requests. No sixth provider request was made.

| Case | Result | Latency | Menus / merchants | Reviewed passages |
|---|---|---:|---:|---:|
| Japanese, Korean copy | PASS | 6,469.304 ms | 3 / 3 | 10 |
| Italian, English copy | STRICT FAIL → safe fallback | 6,405.549 ms | 3 / 3 | 6 |
| American, English copy | PASS | 6,179.516 ms | 3 / 3 | 9 |
| Southeast Asian, Korean copy | PASS | 6,407.546 ms | 3 / 3 | 3 |
| Mexican, English copy | PASS | 6,542.866 ms | 3 / 3 | 9 |

Median was 6,407.546 ms and maximum was 6,542.866 ms. Five observations are not a
statistical percentile sample, so no P90/P95 claim is made.

The Italian request still froze three supported menus from three merchants, but its
generation result did not satisfy the strict response contract and the safety fallback
serialized `matched_criteria` as empty. The server-side candidates and all 24 inspected
Italian candidate-support rows were valid. The deterministic fallback was corrected to
group the already frozen `CriterionEvidence` by category and return only selected
option codes plus reviewed evidence IDs. Expanded SQLite and live Oracle checks then
confirmed three Italian results, unchanged server order, and selected-cuisine evidence
on every result. Those remediation checks made zero provider calls.

The immutable machine-readable observation and review record is
[`deploy/evidence/recommendation_quality_expansion_five_20260817.json`](../../deploy/evidence/recommendation_quality_expansion_five_20260817.json), SHA-256
`59a442314d6c22b5fe301d02e829e662f4b661e05dbe3f5af83e2dad0eeaa501`.

## Final OCI state

- Application: `20260816T201131Z-29fbc2f9fd32` (UTC release identifier; deployed
  2026-08-17 KST)
- Archive SHA-256:
  `29fbc2f9fd325e7c4e15c88a5abde9c8c12b7f5bdfb394fa50a5de244757fa25`
- Knowledge: `external-knowledge-0ffd2f53ba2e2539ee9c5a27`
- Recommendation family:
  `external-recommendation-0ffd2f53ba2e2539ee9c5a27-71a41f074c-5515c9c687`
- Support manifest:
  `71a41f074cb7fa0693b2d92009bcdf708ac0a335a08802171c5f1a408066d5f4`
- Preference catalog: `preference-catalog-2026.08.17-v3`
- Ranking policy: `yobi-concept-rank-v1`, SHA-256
  `5515c9c6877641a111e29ba418890b166b84374101877005749257eae826e191`
- Oracle migration ledger: exact `001`–`012`
- Final deploy provider calls: `0`; staged/active query plan, source integrity,
  Italian deterministic fallback, reviewed-five binding, health, and readiness passed.
- Public root, health, readiness, QR, and preference catalog returned HTTP 200;
  unauthenticated protected demo status returned HTTP 403.
- Public browser verified the combined welcome/locale screen, fixed-address flow, all
  seven cuisine buttons, and no horizontal overflow. The generated test profile and
  session were cascade-deleted afterward.
- Cleanup verified TCP 22 ingress `0`, TCP 80 unchanged, and no temporary Bastion,
  load balancer, or network load balancer remained.

The source catalog remains a dated public-web snapshot rather than a live Yogiyo API.
The browser still ends at a local Yogiyo handoff mock and makes no real payment/order.
