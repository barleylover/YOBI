---
{
  "concept_id": "dish_mandu",
  "concept_type": "FAMILY",
  "name_ko": "만두",
  "name_en": "Mandu",
  "aliases": ["한국 만두", "Korean dumplings"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_wheat_wrapper", "name_ko": "밀 만두피", "name_en": "wheat dumpling wrapper", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Mandu v1"},
    {"ingredient_id": "ingredient_mixed_filling", "name_ko": "만두소", "name_en": "mixed dumpling filling", "role": "CORE", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Mandu v1"},
    {"ingredient_id": "ingredient_pork", "name_ko": "돼지고기", "name_en": "pork", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Pork is common in meat mandu but not universal"},
    {"ingredient_id": "ingredient_tofu", "name_ko": "두부", "name_en": "tofu", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Tofu is common in several fillings"}
  ],
  "allergens": [
    {"allergen_id": "allergen_wheat", "status": "PRESUMED_PRESENT", "source_ref": "The canonical demo wrapper is wheat-based"},
    {"allergen_id": "allergen_soy", "status": "POSSIBLE", "source_ref": "Tofu and seasoning can introduce soy"},
    {"allergen_id": "allergen_egg", "status": "POSSIBLE", "source_ref": "Some wrappers or fillings use egg"}
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Meat, seafood or egg may be present in fillings",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: mandu structured claims v1"
    },
    {
      "attribute_id": "diet_pork_possible",
      "value_text": "Pork is common in some mandu fillings",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: mandu structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetable filling is possible only after seasoning and wrapper are confirmed",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: mandu structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "filled_and_cooked",
      "value_text": "Wheat wrappers are filled and then steamed, boiled, pan-fried or deep-fried",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: mandu structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Mandu v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Mandu

## Overview
Mandu is the Korean dumpling family: a thin wrapper encloses a seasoned filling and may be steamed, boiled, pan-fried or deep-fried.

## Taste
The profile depends on the filling, usually savory with garlic, sesame or soy seasoning.

## Texture
Wrappers range from soft and tender to crisp, while fillings combine minced ingredients and vegetables.

## Temperature
Most mandu is served hot, although chilled leftovers and cold preparations exist outside the default delivery context.

## Satiety
A small order is a side; a large dumpling plate or soup can become a meal.

## Culture
Mandu is eaten as a snack, side dish, soup component and holiday food, with many regional and household forms.

## Analogy
Think of a dumpling family comparable in format to jiaozi or gyoza, with Korean fillings and seasonings.

## Ingredients
A wrapper and filling define mandu. Wheat, pork, tofu, kimchi, chives, glass noodles and egg vary by product.

## Safety
Wheat is presumed in the demo wrapper; pork, soy and egg remain possible. A vegetable name does not prove vegan filling or separate cooking oil.
