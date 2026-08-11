---
{
  "concept_id": "dish_kimchi_stew",
  "concept_type": "FAMILY",
  "name_ko": "김치찌개",
  "name_en": "Kimchi stew",
  "aliases": ["김치 찌개", "kimchi jjigae"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_kimchi", "name_ko": "김치", "name_en": "kimchi", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Kimchi stew v1"},
    {"ingredient_id": "ingredient_broth", "name_ko": "육수", "name_en": "broth", "role": "CORE", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Kimchi stew v1"},
    {"ingredient_id": "ingredient_pork", "name_ko": "돼지고기", "name_en": "pork", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Pork is common but not universal in kimchi stew"},
    {"ingredient_id": "ingredient_tofu", "name_ko": "두부", "name_en": "tofu", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Tofu is a common stew addition"}
  ],
  "allergens": [
    {"allergen_id": "allergen_soy", "status": "POSSIBLE", "source_ref": "Tofu and seasoning can introduce soy"},
    {"allergen_id": "allergen_fish", "status": "POSSIBLE", "source_ref": "Kimchi seasoning or broth can include fish products"},
    {"allergen_id": "allergen_shellfish_risk", "status": "POSSIBLE", "source_ref": "Some kimchi seasoning uses salted shrimp"}
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Pork, fish sauce or seafood stock may be present",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: kimchi-stew structured claims v1"
    },
    {
      "attribute_id": "diet_pork_possible",
      "value_text": "Pork is common but not universal",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: kimchi-stew structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetarian recipe requires confirmation of kimchi seasoning, broth and protein",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: kimchi-stew structured claims v1"
    },
    {
      "attribute_id": "diet_vegan_possible",
      "value_text": "A vegan recipe requires explicit absence of seafood seasoning and animal stock",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: kimchi-stew structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "simmered",
      "value_text": "Kimchi and optional protein are simmered in broth as a stew",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: kimchi-stew structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Kimchi stew v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Kimchi stew

## Overview
Kimchi stew is a bubbling Korean jjigae built around well-fermented kimchi and broth, often with tofu and a meat or fish-based addition.

## Taste
It is tangy, savory and chilli-warm, with deeper acidity when older kimchi is used.

## Texture
Softened kimchi and tofu contrast with meat or mushrooms in a spoonable broth.

## Temperature
It is served very hot and commonly continues bubbling in its cooking vessel.

## Satiety
With rice it is a complete one-person meal, although shared pots are also common.

## Culture
This is an everyday Korean comfort dish that uses fermented kimchi as both main ingredient and seasoning base.

## Analogy
Think of a lively fermented-cabbage stew with chilli warmth, not a mild cabbage soup.

## Ingredients
Kimchi and broth are core. Pork and tofu are common, while tuna, beef, sausage or mushrooms distinguish specific variants.

## Safety
Pork, soy, fish and salted shrimp are realistic possibilities. Vegetable appearance or an unlisted ingredient must not be treated as proof of vegan or allergen-safe preparation.
