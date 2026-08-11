---
{
  "concept_id": "dish_rose_tteokbokki",
  "concept_type": "VARIANT",
  "name_ko": "로제 떡볶이",
  "name_en": "Rose tteokbokki",
  "aliases": ["로제떡볶이", "creamy tteokbokki", "rose spicy rice cakes"],
  "version": "demo-wiki-2026.08.09-v1",
  "language": "en",
  "parents": [
    {
      "concept_id": "dish_tteokbokki",
      "relation_type": "VARIANT_OF",
      "inherit_claims": true,
      "source_ref": "YOBI synthetic culinary taxonomy review: tteokbokki variants v1"
    }
  ],
  "ingredients": [
    {
      "ingredient_id": "ingredient_dairy_cream",
      "name_ko": "유크림",
      "name_en": "dairy cream",
      "role": "CORE",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: rose tteokbokki v1"
    }
  ],
  "allergens": [
    {
      "allergen_id": "allergen_milk",
      "status": "PRESUMED_PRESENT",
      "source_ref": "The demo Wiki's canonical rose profile uses dairy cream"
    }
  ],
  "dietary": [
    {
      "attribute_id": "diet_contains_animal_product",
      "value_text": "Dairy cream defines the standard variant and fish cake may be present",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: rose-tteokbokki structured claims v1"
    },
    {
      "attribute_id": "diet_vegetarian_possible",
      "value_text": "A meat-free preparation is possible only after fish cake, stock and sauce are confirmed",
      "status": "POSSIBLE",
      "source_ref": "YOBI synthetic culinary knowledge review: rose-tteokbokki structured claims v1"
    }
  ],
  "preparation": [
    {
      "method": "simmered",
      "value_text": "Rice cakes are simmered in a creamy red sauce",
      "status": "PRESUMED_PRESENT",
      "source_ref": "YOBI synthetic culinary knowledge review: rose-tteokbokki structured claims v1"
    }
  ],
  "source_type": "SYNTHETIC_WIKI",
  "source_refs": ["YOBI synthetic culinary knowledge review: rose tteokbokki v1"],
  "license_state": "SYNTHETIC",
  "review_status": "REVIEWED_DEMO",
  "is_synthetic": true,
  "updated_at": "2026-08-09"
}
---
# Rose tteokbokki

## Overview
Rose tteokbokki coats chewy rice cakes in a creamy dairy rose sauce with gentle gochujang warmth.

## Taste
It is usually milder and rounder than classic red tteokbokki, with a creamy, lightly sweet and savoury profile. Individual shops can still make it quite spicy.

## Texture
The rice cakes remain springy and chewy while the emulsified sauce feels smooth and coats each piece more heavily than a thinner red sauce.

## Temperature
Rose tteokbokki is served hot. Its thick sauce can continue to set as it cools during delivery.

## Satiety
The creamy sauce makes it feel rich and substantial. Added noodles, cheese or fried sides can turn a snack-sized portion into a heavier shared meal.

## Culture
This is a modern Korean delivery and snack-shop variation rather than the oldest street-stall form. It reflects the popularity of blending familiar Korean spice with creamy Western-style sauces.

## Analogy
A traveller familiar with creamy tomato pasta can use that as a texture reference, but the base is chewy rice cake and the seasoning still comes from the tteokbokki family.

## Ingredients
This demo Wiki treats dairy cream as a core ingredient of the canonical rose variant and inherits rice cake and gochujang knowledge from tteokbokki. A specific merchant may use a different cream product or recipe.

## Safety
Milk is presumed present in this demo concept. Soy and wheat can also remain possible through inherited gochujang or processed additions; actual menu evidence and cross-contact information must override or qualify the Wiki default.
