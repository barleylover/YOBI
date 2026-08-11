---
{
  "concept_id": "dish_naengmyeon",
  "concept_type": "FAMILY",
  "name_ko": "냉면",
  "name_en": "Naengmyeon",
  "aliases": ["한국식 냉면", "Korean cold noodles"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_buckwheat_noodles", "name_ko": "메밀면", "name_en": "buckwheat noodles", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Naengmyeon v1"},
    {"ingredient_id": "ingredient_chilled_broth", "name_ko": "냉육수", "name_en": "chilled broth", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Broth defines mul-naengmyeon but not every mixed-sauce variant"},
    {"ingredient_id": "ingredient_beef", "name_ko": "소고기", "name_en": "beef", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Beef broth or garnish is common"},
    {"ingredient_id": "ingredient_egg", "name_ko": "달걀", "name_en": "egg", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Boiled egg is a common garnish"}
  ],
  "allergens": [
    {"allergen_id": "allergen_wheat", "status": "POSSIBLE", "source_ref": "Many commercial noodles blend buckwheat with wheat or starch"},
    {"allergen_id": "allergen_egg", "status": "POSSIBLE", "source_ref": "Egg garnish is common but removable only when confirmed"},
    {"allergen_id": "allergen_soy", "status": "POSSIBLE", "source_ref": "Sauce and broth seasoning vary"}
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Meat broth, meat slices or egg may be present",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: naengmyeon structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetarian version requires confirmation of broth, sauce and toppings",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: naengmyeon structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "boiled_and_chilled",
      "value_text": "Noodles are boiled, rinsed cold and served in broth or mixed sauce",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: naengmyeon structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Naengmyeon v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Naengmyeon

## Overview
Naengmyeon is a family of very cold, elastic noodles served either in chilled broth or mixed with a spicy sauce.

## Taste
Broth versions are clean, tangy and lightly savory; mixed versions are sweeter and chilli-forward.

## Texture
The long noodles are notably firm and elastic and are often cut with scissors before eating.

## Temperature
It is intentionally served cold, sometimes with visible ice in the broth.

## Satiety
A bowl is usually a one-person meal, though it can feel lighter than a hot noodle soup.

## Culture
Naengmyeon is popular in summer and is also eaten after Korean barbecue as a refreshing finish.

## Analogy
Think of extra-chewy cold noodles in a tart chilled broth or spicy mixed sauce, not a cold pasta salad.

## Ingredients
Buckwheat-style noodles define the family, but commercial blends vary. Beef broth, egg, cucumber, radish and mustard are common additions.

## Safety
Wheat, egg and soy are possible, and beef broth matters for vegetarian or religious rules. A buckwheat label alone does not establish wheat absence.
