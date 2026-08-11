---
{
  "concept_id": "dish_japchae",
  "concept_type": "FAMILY",
  "name_ko": "잡채",
  "name_en": "Japchae",
  "aliases": ["한국식 잡채", "Korean glass noodles"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_sweet_potato_noodles", "name_ko": "당면", "name_en": "sweet-potato glass noodles", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Japchae v1"},
    {"ingredient_id": "ingredient_mixed_vegetables", "name_ko": "채소", "name_en": "mixed vegetables", "role": "CORE", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Japchae v1"},
    {"ingredient_id": "ingredient_soy_sauce", "name_ko": "간장", "name_en": "soy sauce", "role": "CORE", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Japchae v1"},
    {"ingredient_id": "ingredient_sesame_oil", "name_ko": "참기름", "name_en": "sesame oil", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Sesame oil is a common finishing seasoning"}
  ],
  "allergens": [
    {"allergen_id": "allergen_soy", "status": "PRESUMED_PRESENT", "source_ref": "The canonical demo seasoning uses soy sauce"},
    {"allergen_id": "allergen_sesame", "status": "POSSIBLE", "source_ref": "Sesame oil and seeds are common"}
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Beef or egg may be added but are not universal",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: japchae structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetarian version is possible after sauce and toppings are confirmed",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: japchae structured claims v1"
    },
    {
      "attribute_id": "diet_vegan_possible",
      "value_text": "A vegan version requires confirmation of sauce and all toppings",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: japchae structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "stir_fried_and_mixed",
      "value_text": "Cooked glass noodles are mixed or stir-fried with seasoned vegetables and toppings",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: japchae structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Japchae v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Japchae

## Overview
Japchae is a Korean noodle dish made with translucent sweet-potato noodles and separately cooked vegetables tossed in seasoning.

## Taste
It is savory, gently sweet and nutty rather than spicy.

## Texture
The noodles are glossy and pleasantly chewy, balanced by tender or lightly crisp vegetables.

## Temperature
Japchae can be served warm or at room temperature and travels well for delivery.

## Satiety
It can be a side dish or a light meal; meat and portion size change how filling it feels.

## Culture
Japchae appears at celebrations and shared tables but is also sold as an everyday prepared dish.

## Analogy
Think of springy glass noodles tossed like a warm noodle salad with vegetables and soy seasoning.

## Ingredients
Sweet-potato noodles, vegetables and soy sauce are central to this demo concept. Beef, egg and mushrooms are common variations.

## Safety
Soy is presumed present and sesame is possible. The noodle itself differs from wheat pasta, but sauces and shared preparation still need menu-specific checks.
