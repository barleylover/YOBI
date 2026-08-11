---
{
  "concept_id": "dish_gukbap",
  "concept_type": "FAMILY",
  "name_ko": "국밥",
  "name_en": "Gukbap",
  "aliases": ["국밥", "Korean soup with rice"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_rice", "name_ko": "쌀", "name_en": "rice", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Gukbap v1"},
    {"ingredient_id": "ingredient_broth", "name_ko": "육수", "name_en": "broth", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Gukbap v1"},
    {"ingredient_id": "ingredient_pork", "name_ko": "돼지고기", "name_en": "pork", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Pork gukbap is common but not the whole family"},
    {"ingredient_id": "ingredient_beef", "name_ko": "소고기", "name_en": "beef", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Beef and offal variants exist"}
  ],
  "allergens": [
    {"allergen_id": "allergen_soy", "status": "POSSIBLE", "source_ref": "Broth seasoning can include soy"},
    {"allergen_id": "allergen_shellfish_risk", "status": "POSSIBLE", "source_ref": "Broth or fermented accompaniments can introduce seafood"}
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Meat, seafood or animal stock is common but varies by subtype",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: gukbap structured claims v1"
    },
    {
      "attribute_id": "diet_halal_not_verified",
      "value_text": "Protein sourcing and broth preparation are not halal-verified by the family Wiki",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: gukbap structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetarian subtype is possible only when broth and toppings are confirmed",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: gukbap structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "simmered",
      "value_text": "Broth and toppings are simmered and served with rice",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: gukbap structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Gukbap v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Gukbap

## Overview
Gukbap is the Korean family of soup served with rice, either already combined or presented for the diner to add.

## Taste
It is usually savory and broth-forward; seasoning ranges from mild and clean to spicy and fermented.

## Texture
Soft rice absorbs broth while meat, offal, vegetables or bean sprouts provide the main contrasting texture.

## Temperature
Gukbap is served piping hot and is intended to stay warm through the meal.

## Satiety
A bowl is a substantial one-person meal.

## Culture
Regional gukbap traditions are associated with practical, warming meals and late-night or market dining.

## Analogy
Think of a hearty soup-and-rice meal, but the protein and broth base must be identified from the specific menu name.

## Ingredients
Rice and broth define the family. Pork, beef, offal, bean sprouts and seafood distinguish different gukbap variants.

## Safety
Pork cannot be inferred for every gukbap, but it is common enough to require a strict warning when the variant is unknown. Broth composition and cross-contact remain menu facts.
