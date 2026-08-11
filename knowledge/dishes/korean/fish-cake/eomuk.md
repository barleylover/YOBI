---
{
  "concept_id": "dish_eomuk",
  "concept_type": "FAMILY",
  "name_ko": "어묵",
  "name_en": "Eomuk",
  "aliases": ["오뎅", "Korean fish cake"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_fish_paste", "name_ko": "생선살", "name_en": "fish paste", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Eomuk v1"},
    {"ingredient_id": "ingredient_starch", "name_ko": "전분", "name_en": "starch", "role": "CORE", "status": "PRESUMED_PRESENT", "source_ref": "The canonical demo fish-cake mixture uses starch"},
    {"ingredient_id": "ingredient_wheat_flour", "name_ko": "밀가루", "name_en": "wheat flour", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Commercial fish-cake formulations vary"},
    {"ingredient_id": "ingredient_broth", "name_ko": "육수", "name_en": "broth", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Skewered eomuk is commonly served in broth"}
  ],
  "allergens": [
    {"allergen_id": "allergen_fish", "status": "PRESUMED_PRESENT", "source_ref": "Fish paste defines eomuk"},
    {"allergen_id": "allergen_wheat", "status": "POSSIBLE", "source_ref": "Flour or processed starch blends vary"},
    {"allergen_id": "allergen_soy", "status": "POSSIBLE", "source_ref": "Seasoning and broth can introduce soy"}
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Fish paste defines the dish",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: eomuk structured claims v1"
    },
    {
      "attribute_id": "diet_halal_not_verified",
      "value_text": "Processed fish paste and shared preparation are not halal-verified by the Wiki",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: eomuk structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "formed_and_cooked",
      "value_text": "Seasoned fish paste is formed and fried, steamed or boiled",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: eomuk structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Eomuk v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Eomuk

## Overview
Eomuk is Korean fish cake: seasoned fish paste is mixed with starch, shaped and cooked, then served alone, skewered in broth or added to other dishes.

## Taste
It is mild, savory and lightly sweet, with broth or sauce adding most of the seasoning.

## Texture
The characteristic texture is springy, smooth and resilient rather than flaky like a fish fillet.

## Temperature
Street-style skewers are served hot in broth; packaged sides may be warm or cool.

## Satiety
A few pieces are a snack or side, while a large broth portion can be a light meal.

## Culture
Eomuk skewers and their warming broth are familiar Korean street-food sights, especially in cool weather.

## Analogy
Think of a smooth, springy fish paste cake in the broad family of fish balls or kamaboko, often served on a skewer.

## Ingredients
Fish paste and starch define the demo concept. Wheat flour, vegetables, soy seasoning and broth vary by manufacturer and serving style.

## Safety
Fish is presumed present; wheat and soy are possible. Removing visible eomuk from another dish does not by itself remove broth exposure or cross-contact.
