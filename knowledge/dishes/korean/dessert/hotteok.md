---
{
  "concept_id": "dish_hotteok",
  "concept_type": "FAMILY",
  "name_ko": "호떡",
  "name_en": "Hotteok",
  "aliases": ["한국식 호떡", "Korean filled sweet pancake"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [{"concept_id": "dish_korean_cuisine", "relation_type": "IS_A", "inherit_claims": false, "source_ref": "YOBI synthetic taxonomy: Korean cuisine hierarchy v1"}],
  "ingredients": [
    {"ingredient_id": "ingredient_wheat_dough", "name_ko": "밀 반죽", "name_en": "wheat dough", "role": "DEFINING", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Hotteok v1"},
    {"ingredient_id": "ingredient_brown_sugar", "name_ko": "흑설탕", "name_en": "brown sugar filling", "role": "CORE", "status": "PRESUMED_PRESENT", "source_ref": "YOBI synthetic culinary knowledge review: Hotteok v1"},
    {"ingredient_id": "ingredient_mixed_seeds", "name_ko": "씨앗", "name_en": "mixed seeds", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Seed hotteok is a common variant"},
    {"ingredient_id": "ingredient_tree_nuts", "name_ko": "견과류", "name_en": "tree nuts", "role": "COMMON", "status": "POSSIBLE", "source_ref": "Nut fillings vary by product"}
  ],
  "allergens": [
    {"allergen_id": "allergen_wheat", "status": "PRESUMED_PRESENT", "source_ref": "The canonical demo dough is wheat-based"},
    {"allergen_id": "allergen_tree_nut", "status": "POSSIBLE", "source_ref": "Nut fillings are common but not universal"},
    {"allergen_id": "allergen_sesame", "status": "POSSIBLE", "source_ref": "Seed mixtures can include sesame"}
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Milk or egg may be present in some dough recipes",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: hotteok structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetarian preparation is commonly possible after dough and filling are confirmed",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: hotteok structured claims v1"
    },
    {
      "attribute_id": "diet_vegan_possible",
      "value_text": "A vegan recipe is possible only when dairy and egg are explicitly absent",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: hotteok structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "griddled",
      "value_text": "Filled wheat dough is pressed and griddled until browned",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: hotteok structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: Hotteok v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Hotteok

## Overview
Hotteok is a griddled Korean filled pancake, usually made from yeasted wheat dough around a sweet molten filling.

## Taste
The classic profile is caramel-like, sweet and gently spiced, with nutty notes in seed versions.

## Texture
The outside is crisp and chewy while the hot sugar filling is sticky and fluid.

## Temperature
It is best served hot; the filling can remain much hotter than the exterior.

## Satiety
One piece is a rich snack or dessert rather than a full meal.

## Culture
Hotteok is closely associated with winter street-food stalls and made-to-order snacking.

## Analogy
Think of a chewy griddled dough pocket with molten cinnamon-brown-sugar filling, not a fluffy breakfast pancake.

## Ingredients
Wheat dough and brown sugar filling define the demo family. Seeds and tree nuts distinguish popular variants.

## Safety
Wheat is presumed present; tree nuts and sesame are possible. A plain-looking filling does not confirm their absence, and shared griddles remain separate evidence.
