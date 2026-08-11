---
{
  "concept_id": "dish_gimbap",
  "concept_type": "FAMILY",
  "name_ko": "김밥",
  "name_en": "Gimbap",
  "aliases": [
    "김밥",
    "kimbap",
    "Korean seaweed rice roll"
  ],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [
    {
      "concept_id": "dish_korean_cuisine",
      "relation_type": "IS_A",
      "inherit_claims": false,
      "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"
    }
  ],
  "ingredients": [
    {
      "ingredient_id": "ingredient_rice",
      "name_ko": "쌀",
      "name_en": "seasoned rice",
      "role": "CORE",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    },
    {
      "ingredient_id": "ingredient_seaweed",
      "name_ko": "김",
      "name_en": "dried seaweed",
      "role": "DEFINING",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    },
    {
      "ingredient_id": "ingredient_sesame_oil",
      "name_ko": "참기름",
      "name_en": "sesame oil",
      "role": "COMMON",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    },
    {
      "ingredient_id": "ingredient_pickled_radish",
      "name_ko": "단무지",
      "name_en": "pickled radish",
      "role": "COMMON",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    },
    {
      "ingredient_id": "ingredient_egg",
      "name_ko": "달걀",
      "name_en": "egg",
      "role": "COMMON",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    }
  ],
  "allergens": [
    {
      "allergen_id": "allergen_egg",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    },
    {
      "allergen_id": "allergen_soy",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    },
    {
      "allergen_id": "allergen_sesame",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: Gimbap v1"
    }
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Egg, fish cake, meat or seafood may be included",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: gimbap structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetarian roll is possible only after all fillings and seasoning are confirmed",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: gimbap structured claims v1"
    },
    {
      "attribute_id": "diet_vegan_possible",
      "value_text": "A vegan roll requires explicit confirmation of egg, fish cake, meat and sauce",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: gimbap structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "rolled_and_sliced",
      "value_text": "Seasoned rice and fillings are rolled in seaweed and sliced",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: gimbap structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": [
    "YOBI synthetic culinary knowledge review: Gimbap v1"
  ],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Gimbap

## Overview
Gimbap is seasoned rice and varied fillings rolled in dried seaweed and sliced into bite-size rounds. The filling combination defines each named variant.

## Taste
The base is mild, savory and lightly nutty, with sweetness or acidity from pickled fillings.

## Texture
Each slice combines soft rice, crisp vegetables and firmer fillings inside a flexible seaweed wrapper.

## Temperature
It is generally served at room temperature and is best before the rice dries.

## Satiety
One roll is a light meal or substantial snack; multiple rolls suit sharing.

## Culture
Gimbap is everyday portable food for outings, quick lunches and travel, distinct from raw-fish sushi.

## Analogy
It resembles a compact rice-and-filling pinwheel, seasoned with sesame oil rather than vinegar-forward sushi rice.

## Ingredients
Rice and seaweed are core. Pickled radish, egg, carrot, spinach, ham, fish cake, tuna or cheese vary by named roll.

## Safety
Egg, soy, sesame, fish, wheat, milk or meat can enter through fillings. The exact named variant and merchant recipe must override this family-level list.
