---
{
  "concept_id": "dish_kalguksu",
  "concept_type": "FAMILY",
  "name_ko": "칼국수",
  "name_en": "Kalguksu",
  "aliases": [
    "칼국수 면요리",
    "Korean knife-cut noodles",
    "knife-cut noodle soup"
  ],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [
    {
      "concept_id": "dish_korean_cuisine",
      "relation_type": "IS_A",
      "inherit_claims": false,
      "source_ref": "YOBI synthetic culinary taxonomy review: Kalguksu family v1"
    }
  ],
  "ingredients": [
    {
      "ingredient_id": "ingredient_wheat_noodles",
      "name_ko": "칼국수 면",
      "name_en": "knife-cut wheat noodles",
      "role": "DEFINING",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: Kalguksu v1"
    },
    {
      "ingredient_id": "ingredient_broth",
      "name_ko": "육수",
      "name_en": "broth",
      "role": "CORE",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: Kalguksu v1"
    }
  ],
  "allergens": [
    {
      "allergen_id": "allergen_wheat",
      "status": "PRESUMED_PRESENT",
      "source_ref": "The demo Wiki canonical kalguksu profile uses wheat noodles"
    }
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Meat, fish or shellfish broth may be used",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: kalguksu structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A vegetable-broth version is possible but not implied by the family name",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: kalguksu structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "simmered",
      "value_text": "Knife-cut wheat noodles are boiled or simmered in broth",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: kalguksu structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": [
    "YOBI synthetic culinary knowledge review: Kalguksu v1"
  ],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Kalguksu

## Overview
Kalguksu is a Korean noodle-soup family built around broad knife-cut-style noodles in broth. Named variants identify the broth, protein or seafood base.

## Taste
The family is generally savory and broth-forward, ranging from clean anchovy stock to richer chicken, clam or perilla-seasoned versions.

## Texture
Broad noodles are soft-chewy and slightly rustic, while vegetables, meat or shellfish add variant-specific texture.

## Temperature
Kalguksu is normally served steaming hot, and its noodles continue to soften while held in broth during delivery.

## Satiety
A bowl is usually a substantial one-person meal, with dumplings or extra noodles making it heavier.

## Culture
It is familiar Korean comfort food and is especially associated with cool or rainy weather and casual neighborhood restaurants.

## Analogy
Think of a hearty noodle soup with broader, hand-cut-style strands, while the named variant tells you what stock and toppings to expect.

## Ingredients
The demo family treats wheat noodles and broth as defining. Anchovy, clam, chicken, vegetables and seasonings depend on the specific kalguksu variant.

## Safety
Wheat is presumed present. Fish and shellfish occur in named broth variants, but are not inherited as assumptions for every child; menu-specific broth and cross-contact evidence is still required.
