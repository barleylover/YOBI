---
{
  "concept_id": "dish_dosirak",
  "concept_type": "FAMILY",
  "name_ko": "도시락",
  "name_en": "Dosirak",
  "aliases": ["Korean lunch box"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_rice", "name_ko": "쌀", "name_en": "rice", "role": "CORE", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Dosirak v1"},
    {"ingredient_id": "ingredient_assorted_side_dishes", "name_ko": "반찬", "name_en": "assorted side dishes", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Side-dish composition varies by lunch box"},
    {"ingredient_id": "ingredient_egg", "name_ko": "달걀", "name_en": "egg", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Egg is a common but optional lunch-box component"}
  ],
  "allergens": [
    {"allergen_id": "allergen_egg", "status": "POSSIBLE", "source_ref": "Egg components are common"},
    {"allergen_id": "allergen_soy", "status": "POSSIBLE", "source_ref": "Several side dishes can use soy seasoning"},
    {"allergen_id": "allergen_wheat", "status": "POSSIBLE", "source_ref": "Breaded or sauced sides can introduce wheat"}
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Dosirak v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Dosirak

## Overview
Dosirak means a packed meal or lunch box rather than one fixed recipe. A Korean delivery dosirak usually combines rice with a main item and several side dishes.

## Taste
It is designed for variety: savory, sweet, spicy, pickled and mild components can appear in one box.

## Texture
Rice, crisp pickles, tender vegetables and a meat or fried main create multiple textures.

## Temperature
Rice and main dishes are usually warm while pickles and salads may be cool.

## Satiety
A standard box is intended as a complete one-person meal.

## Culture
Dosirak is the Korean packed-meal format used for school, work, travel and convenient restaurant meals.

## Analogy
Think of a composed bento-style meal, but do not infer ingredients from the container format alone.

## Ingredients
Rice is core to the demo family; every other component depends on the named lunch-box set.

## Safety
Egg, soy, wheat, fish, meat and other allergens can appear across side dishes. This family needs item-level facts and should never generate a blanket safety claim.
