#!/usr/bin/env python3
"""Generate the reviewed 2026-08-17 general-food Wiki expansion.

This manifest is intentionally curated rather than inferred from merchant copy.
It contains general culinary descriptions and conservative Korean name aliases
only.  It does not assert a merchant recipe, certification, dietary status,
allergen safety, portion, or menu-specific spice level.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "knowledge" / "external_dishes" / "expanded_20260817"
VERSION = "external-demo-wiki-2026.08.17-v2"
UPDATED_AT = "2026-08-17"


@dataclass(frozen=True)
class CuisineSpec:
    slug: str
    name_ko: str
    name_en: str
    aliases: Sequence[str]
    overview: str
    range_note: str

    @property
    def concept_id(self) -> str:
        return f"dish_{self.slug}_cuisine"


@dataclass(frozen=True)
class DishSpec:
    slug: str
    name_ko: str
    name_en: str
    aliases: Sequence[str]
    cuisine: str | None
    overview: str
    experience: str

    @property
    def concept_id(self) -> str:
        return f"dish_{self.slug}"


CUISINES: Sequence[CuisineSpec] = (
    CuisineSpec(
        "chinese",
        "중화요리",
        "Chinese cuisine",
        ("중국 음식", "중국요리", "Chinese food"),
        "Chinese cuisine is a large collection of regional food traditions rather than one flavour profile. Rice and noodle dishes, dumplings, soups, braises, stir-fries and steamed foods all sit within the tradition.",
        "Its dishes can be clean and delicate, savoury and aromatic, sweet-sour, numbing-spicy or deeply roasted. A cuisine label therefore describes lineage, not a guaranteed ingredient, cooking method or heat level.",
    ),
    CuisineSpec(
        "japanese",
        "일식",
        "Japanese cuisine",
        ("일본 음식", "일본요리", "Japanese food"),
        "Japanese cuisine includes rice, noodles, raw and cooked seafood, grilled dishes, fried foods, simmered dishes and modern comfort food. The tradition contains both restrained preparations and rich, sauce-forward meals.",
        "Serving temperature and texture vary widely, from cool sushi rice and sashimi to steaming noodles and crisp fried cutlets. The cuisine node does not prove raw-fish handling, ingredients or dietary suitability for a menu.",
    ),
    CuisineSpec(
        "italian",
        "이탈리안",
        "Italian cuisine",
        ("이탈리아 음식", "이탈리아요리", "Italian food"),
        "Italian cuisine is a regional tradition encompassing pasta, pizza, risotto, breads, soups, grilled foods and desserts. Tomato, olive oil, cheese and herbs are familiar directions, but they are not universal requirements.",
        "The cuisine ranges from light, clean dishes to creamy, baked or slow-cooked preparations. A menu's actual sauce, dairy, meat and allergens must be confirmed from merchant information.",
    ),
    CuisineSpec(
        "american",
        "아메리칸",
        "American cuisine",
        ("미국 음식", "미국식 요리", "American food"),
        "American cuisine is a broad, multicultural family that includes burgers, barbecue, sandwiches, steaks, fried snacks and many regional foods. It cannot be reduced to one recipe or one flavour.",
        "Common restaurant styles may be hearty, grilled, smoky, crisp or sauce-forward, while lighter versions also exist. The lineage does not establish portion, protein, dietary status or preparation for a specific menu.",
    ),
    CuisineSpec(
        "southeast_asian",
        "동남아 음식",
        "Southeast Asian cuisine",
        ("동남아시아 음식", "동남아요리", "Southeast Asian food"),
        "Southeast Asian cuisine brings together distinct Thai, Vietnamese, Indonesian and neighbouring food traditions. Rice, noodles, herbs, soups, grilled foods and stir-fries appear in many forms without defining every dish.",
        "Fresh herbs, savoury sauces, acidity, sweetness and chilli heat can be balanced in different ways. A regional label never guarantees spice, fish sauce, nuts, meat or vegetarian suitability.",
    ),
    CuisineSpec(
        "mexican",
        "멕시칸",
        "Mexican cuisine",
        ("멕시코 음식", "멕시코요리", "Mexican food"),
        "Mexican cuisine includes tacos, filled tortillas, grilled foods, stews, salsas and regional corn- and wheat-based preparations. Korean delivery menus may also use Mexican-inspired formats and flavours.",
        "A dish may be fresh and tangy, smoky, savoury, creamy or spicy, but heat and filling vary by product. The cuisine label does not prove meat, cheese, gluten or chilli content.",
    ),
)


DISHES: Sequence[DishSpec] = (
    DishSpec("salad", "샐러드", "Salad", ("샐러드", "mixed salad"), None, "A salad is a composed dish built around vegetables, grains, fruit, noodles or other bite-sized components, commonly served with a dressing.", "It is often cool or at room temperature and can feel crisp, crunchy, soft or hearty depending on the base. The name alone does not identify dressing, protein or dietary suitability."),
    DishSpec("poke", "포케", "Poke bowl", ("포케", "포케볼", "poke bowl"), None, "A poke bowl is a composed bowl meal commonly pairing a rice or vegetable base with cut toppings and sauce. Contemporary menus include seafood, meat, tofu and vegetable versions.", "It is usually served cool or at room temperature with soft grains and crisp toppings. The word poke does not guarantee raw fish, a specific sauce or a particular protein."),
    DishSpec("pasta", "파스타", "Pasta", ("파스타", "pasta dish"), "italian", "Pasta is an Italian noodle family shaped into many forms and paired with sauces, broths or baked preparations.", "It may be light and tangy, savoury, spicy or thick and creamy, and is generally served warm or hot. The menu name must identify the actual sauce and ingredients."),
    DishSpec("risotto", "리조또", "Risotto", ("리조또", "Italian risotto"), "italian", "Risotto is an Italian rice dish prepared by gradually cooking rice with liquid until the grains are tender and the surrounding texture becomes creamy.", "It is normally served warm and ranges from delicate to rich and savoury. Creaminess describes texture and does not by itself prove dairy content."),
    DishSpec("soup", "수프", "Soup", ("수프", "스프", "크림스프", "양송이스프", "단호박스프", "콘스프", "토마토스프", "머쉬룸스프", "오늘의 수프", "soup"), None, "Soup is a liquid-based dish in which vegetables, grains, meat, seafood or other components are cooked or combined with broth or a purée.", "It can be clear and mild, thick and rich, served hot or served cool. The broad name gives no reliable ingredient or allergen guarantee."),
    DishSpec("sashimi", "사시미", "Sashimi", ("사시미", "Japanese sashimi"), "japanese", "Sashimi is a Japanese serving style centred on carefully cut raw seafood or other designated ingredients without vinegared sushi rice.", "It is served cool, with a clean flavour and tender or firm texture depending on the item. Raw handling, species and freshness require merchant confirmation."),
    DishSpec("takoyaki", "타코야키", "Takoyaki", ("타코야키", "타코야끼", "octopus ball snack"), "japanese", "Takoyaki is a Japanese round griddle snack made from batter cooked in moulds, traditionally with small octopus pieces and savoury toppings.", "It is served hot with a soft interior and browned exterior, often tasting savoury and sauce-forward. A merchant may vary fillings and toppings."),
    DishSpec("tako_wasabi", "타코와사비", "Tako wasabi", ("타코와사비", "문어 와사비", "Japanese octopus wasabi"), "japanese", "Tako wasabi is a Japanese-style cold appetiser combining small pieces of octopus with a sharp wasabi-forward seasoning.", "It is served cool with a chewy texture and clean, pungent flavour. Octopus preparation, seasoning and accompaniments vary by merchant."),
    DishSpec("taco", "타코", "Taco", ("타코", "Mexican taco"), "mexican", "A taco is a Mexican dish format in which a small tortilla carries a filling and garnishes. Soft and crisp-shell interpretations both appear on delivery menus.", "It can be fresh, savoury, smoky, tangy or spicy depending on filling and salsa. The word taco does not establish meat, cheese or chilli."),
    DishSpec("burrito", "부리토", "Burrito", ("부리토", "부리또", "Mexican burrito"), "mexican", "A burrito is a filled tortilla wrapped into a compact meal, often combining grains, beans, vegetables, protein or sauce in varying combinations.", "It is generally served warm, with soft and hearty textures. Fillings and dietary properties are product-specific rather than guaranteed by the format."),
    DishSpec("quesadilla", "퀘사디아", "Quesadilla", ("퀘사디아", "Mexican quesadilla"), "mexican", "A quesadilla is a folded or layered tortilla cooked with a melting filling and optional additions.", "It is commonly served warm with a crisped exterior and soft, rich centre. Cheese is common but actual ingredients and alternatives require merchant confirmation."),
    DishSpec("nachos", "나초", "Nachos", ("나초", "nachos"), "mexican", "Nachos are a shared snack built around crisp tortilla chips with sauces or toppings added before serving or packed separately.", "They are crunchy and savoury, with richness, tang or heat depending on toppings. The format does not guarantee cheese, meat or a spice level."),
    DishSpec("steak", "스테이크", "Steak", ("스테이크", "steak"), "american", "Steak describes a thick-cut food portion cooked as a central dish; restaurant menus use the term for beef, fish, poultry and plant-based items.", "It is usually served warm or hot with a browned or grilled surface and a tender or firm centre. The name alone must not be treated as proof of beef."),
    DishSpec("barbecue", "바비큐", "Barbecue", ("바비큐", "바베큐", "barbecue", "BBQ"), "american", "Barbecue is a cooking and dining family associated with grilling, roasting or slow cooking over heat and smoke, with many regional interpretations.", "It is typically savoury, roasted or smoky and served warm. Sauce, protein, smoke intensity and cooking time differ by menu."),
    DishSpec("hot_dog", "핫도그", "Hot dog", ("핫도그", "hot dog"), "american", "Hot dog is a portable bread-and-filling format; Korean menus may also use the name for battered, skewered corn-dog styles.", "It is commonly served hot with a soft or crisp exterior and savoury centre. The format does not identify sausage type, batter or cheese."),
    DishSpec("french_fries", "감자튀김", "French fries", ("감자튀김", "프렌치프라이", "French fries"), "american", "French fries are cut potato pieces cooked by frying or an equivalent crisping method and served as a snack or side.", "They are usually hot, salty and crisp outside with a soft centre. Oil, seasoning and shared-fryer exposure are merchant-specific."),
    DishSpec("chicken_wings", "치킨윙", "Chicken wings", ("치킨윙", "버팔로윙", "chicken wings"), "american", "Chicken wings are portioned wing pieces cooked until browned or crisp and served plain, seasoned or coated with sauce.", "They are generally hot, savoury and tender, sometimes spicy or sweet. Cooking method, coating and heat level vary by menu."),
    DishSpec("cheese_balls", "치즈볼", "Cheese balls", ("치즈볼", "cheese balls"), None, "Cheese balls are bite-sized savoury snacks with a cheese-style centre or flavour, commonly enclosed in dough or a crumbed shell and cooked until browned.", "They are served warm with a crisp or chewy exterior and soft, rich centre. The exact dairy and coating ingredients require product information."),
    DishSpec("cheese_sticks", "치즈스틱", "Cheese sticks", ("치즈스틱", "cheese sticks"), None, "Cheese sticks are elongated snacks built around a cheese-style filling, usually coated and cooked until the outside is crisp.", "They are best known for a hot, soft centre and savoury crust. Cheese type, coating and fryer handling are not implied by the name."),
    DishSpec("steamed_egg", "계란찜", "Korean steamed egg", ("계란찜", "달걀찜", "Korean steamed egg"), "korean", "Korean steamed egg is a soft egg dish gently steamed or cooked with liquid until set, often served as a warm side.", "Its defining texture is tender and custard-like, with a mild savoury profile. Added stock, vegetables and seasoning vary by restaurant."),
    DishSpec("rice_ball", "주먹밥", "Korean rice ball", ("주먹밥", "Korean rice ball"), "korean", "Jumeokbap is a Korean hand-formed rice snack or side in which seasoned rice is shaped into compact portions, sometimes with mix-ins.", "It is usually soft and chewy, served warm or at room temperature, and can be mild or savoury. Mix-ins are not guaranteed."),
    DishSpec("rice_bowl", "덮밥", "Rice bowl", ("덮밥", "rice bowl"), None, "A rice bowl is a meal format placing a cooked topping, sauce or composed ingredients over rice.", "It is generally warm and combines soft rice with textures determined by the topping. The broad format does not establish cuisine, protein or sauce."),
    DishSpec("yukhoe", "육회", "Yukhoe", ("육회", "Korean seasoned raw beef"), "korean", "Yukhoe is a Korean raw-beef dish in which finely cut meat is seasoned and served cool, commonly with crisp or sweet accompaniments.", "Its texture is tender and the flavour is savoury and lightly seasoned. Raw handling and actual ingredients require direct merchant verification."),
    DishSpec("kimchi_braise", "김치찜", "Kimchi-jjim", ("김치찜", "braised kimchi"), "korean", "Kimchi-jjim is a Korean braised dish that slowly cooks mature kimchi with liquid and optional additions until deeply softened.", "It is served hot with a tender texture and robust savoury, sour and often spicy flavour. Protein and heat level vary by recipe."),
    DishSpec("yukgaejang", "육개장", "Yukgaejang", ("육개장", "spicy Korean beef soup"), "korean", "Yukgaejang is a Korean red soup traditionally associated with shredded beef, vegetables and aromatic seasoning simmered together.", "It is served steaming hot with a savoury, robust and commonly spicy profile. The menu must confirm protein and actual heat."),
    DishSpec("jjageuli", "짜글이", "Jjageuli", ("짜글이", "Korean reduced stew"), "korean", "Jjageuli is a Korean stew style cooked with relatively little broth so the sauce reduces around the main ingredients.", "It is served hot, thick and savoury, and many versions are spicy. Meat, tofu and vegetable combinations differ by restaurant."),
    DishSpec("macaron", "마카롱", "Macaron", ("마카롱", "macaron"), None, "A macaron is a small filled confection built from two smooth meringue-style shells around a cream, ganache or jam-like centre.", "It is sweet, lightly crisp outside and chewy or soft within, normally served cool or at room temperature. Flavours and allergens vary widely."),
    DishSpec("tart", "타르트", "Tart", ("타르트", "tart dessert"), None, "A tart is a baked pastry shell holding a sweet or savoury filling, with fruit, custard, chocolate and cheese-style fillings among common dessert forms.", "It combines a crisp or crumbly shell with a soft filling and is served cool, warm or at room temperature. Ingredients are product-specific."),
    DishSpec("donut", "도넛", "Doughnut", ("도넛", "도너츠", "doughnut", "donut"), "american", "A doughnut is a sweet dough product shaped and cooked as a ring or filled piece, usually fried and sometimes baked.", "It is soft or chewy with a browned exterior and may be glazed, sugared or filled. Toppings and allergens require product information."),
    DishSpec("bagel", "베이글", "Bagel", ("베이글", "bagel"), "american", "A bagel is a ring-shaped bread traditionally boiled briefly before baking, producing a close crumb and chewy crust.", "It is eaten at room temperature, warm or toasted, with savoury or sweet toppings. Fillings and spreads are not implied by the bread name."),
    DishSpec("cookie", "쿠키", "Cookie", ("쿠키", "cookie"), None, "A cookie is a small baked sweet with styles ranging from thin and crisp to thick, soft or chewy.", "Butter, chocolate, fruit, nuts and spices are possible flavour directions rather than guaranteed ingredients. Product labelling remains necessary for allergens."),
    DishSpec("choux_pastry", "슈 페이스트리", "Choux pastry", ("쿠키슈", "슈 페이스트리", "choux pastry"), None, "Choux pastry is a light baked shell that expands around a hollow centre and is commonly filled with cream or a savoury mixture after baking.", "It is soft or crisp outside with an airy interior, usually served cool or at room temperature when filled. Filling and allergens vary by product."),
    DishSpec("ice_cream", "아이스크림", "Ice cream", ("아이스크림", "ice cream"), None, "Ice cream is a frozen dessert family churned or otherwise frozen to create a smooth, scoopable texture, with dairy and non-dairy styles both available.", "It is served frozen, sweet and creamy or icy depending on the formulation. The name alone does not prove dairy content or allergen safety."),
    DishSpec("gelato", "젤라토", "Gelato", ("젤라토", "gelato"), "italian", "Gelato is an Italian-style frozen dessert known for a dense, smooth texture and flavour-forward service at a slightly softer temperature than hard ice cream.", "It remains a broad product family with dairy and non-dairy variations. Flavour names do not establish ingredients or allergens."),
    DishSpec("yogurt", "요거트", "Yogurt", ("요거트", "요구르트", "yogurt"), None, "Yogurt is a cultured food or drink family with plain, sweetened, frozen and topping-based formats in the catalog.", "It is tangy and creamy or drinkable, usually served cool. Dairy-free versions exist, so the name alone is not a dairy guarantee."),
    DishSpec("juice", "주스", "Fruit juice", ("주스", "fruit juice"), None, "Juice is a non-alcoholic drink made from or flavoured around fruit or vegetables, served alone or blended with other components.", "It is normally cool and can be sweet, tart, pulpy or clear. Added sugar, dairy and exact fruit content are product-specific."),
    DishSpec("americano", "아메리카노", "Americano", ("아메리카노", "caffe Americano"), None, "An Americano is a coffee drink combining espresso-style coffee with water, served hot or over ice.", "Its profile is roasted and relatively clean, with strength affected by the coffee and dilution. Milk, syrup and decaffeination must be specified separately."),
    DishSpec("cafe_latte", "카페라떼", "Caffe latte", ("카페라떼", "카페 라떼", "caffe latte"), "italian", "A caffe latte is an espresso-style coffee drink combined with a larger proportion of milk or a milk alternative.", "It is smooth and creamy, served hot or iced, and may include flavouring. The name does not identify dairy type or added sugar."),
    DishSpec("cold_brew", "콜드브루", "Cold-brew coffee", ("콜드브루", "cold brew"), None, "Cold-brew coffee is prepared by extracting coffee with cool water over an extended period and serving the resulting drink chilled or diluted.", "It is cool, roasted and often perceived as smooth. Sweetener, milk and caffeine strength vary by product."),
    DishSpec("smoothie", "스무디", "Smoothie", ("스무디", "smoothie"), None, "A smoothie is a thick blended drink built around fruit, vegetables or other flavour bases, often with ice or a creamy component.", "It is served cool with a thick, soft texture and can be sweet or tart. Dairy, juice, sugar and supplements are optional rather than guaranteed."),
    DishSpec("croissant", "크루아상", "Croissant", ("크루아상", "크로와상", "croissant"), None, "A croissant is a laminated, crescent-shaped pastry baked so repeated dough and fat layers separate into a flaky structure.", "It is light, crisp and tender when fresh, served at room temperature or warm. Fillings and exact fats vary by bakery."),
    DishSpec("salt_bread", "소금빵", "Salt bread", ("소금빵", "시오빵", "salt bread"), None, "Salt bread is a soft roll style finished with a distinct salty surface and commonly shaped around a rich interior crumb.", "It is baked and served warm or at room temperature, with a soft centre and lightly crisp base. Fat and filling details vary."),
    DishSpec("loaf_bread", "식빵", "Loaf bread", ("식빵", "sandwich loaf"), None, "Loaf bread is a sliced or sliceable bread baked in a pan, ranging from lean sandwich bread to soft enriched styles.", "It is usually mild and soft, eaten at room temperature or toasted. Wheat, dairy, egg and sweeteners must be checked per product."),
    DishSpec("baguette", "바게트", "Baguette", ("바게트", "바게뜨", "baguette"), None, "A baguette is a long, narrow loaf baked for a crisp crust and an open or chewy interior, then sold whole or used as the base for filled breads.", "It is served at room temperature or warmed and may be plain, filled or topped. A named variation can substantially change ingredients."),
    DishSpec("pastry", "페이스트리", "Pastry", ("페이스트리", "페스츄리", "패스트리", "pastry"), None, "Pastry is a broad baked family using layered, crumbly or enriched dough to create sweet and savoury products.", "Textures range from flaky and crisp to soft and rich. Filling, dairy, egg, wheat and nuts cannot be inferred from the family name."),
    DishSpec("castella", "카스텔라", "Castella", ("카스텔라", "카스테라", "castella cake"), None, "Castella is a soft sponge-style cake with a fine, moist crumb, adapted across Japanese and Korean bakery traditions.", "It is sweet, tender and generally served at room temperature. Flavour additions and ingredient details differ by bakery."),
    DishSpec("croquette", "고로케", "Croquette", ("고로케", "크로켓", "croquette"), None, "A croquette is a shaped snack containing a soft filling inside a crumbed or dough-like exterior, then cooked until browned.", "It is served warm with a crisp outside and soft centre. Potato, meat, curry and cream fillings are possibilities, not guarantees."),
    DishSpec("waffle", "와플", "Waffle", ("와플", "waffle"), None, "A waffle is a griddled batter food cooked between patterned plates, served plain or with sweet or savoury toppings.", "It is warm, crisp at the ridges and soft inside. Toppings, dairy, egg and wheat depend on the product."),
    DishSpec("churros", "츄러스", "Churros", ("츄러스", "churros"), None, "Churros are ridged lengths of dough cooked until browned and commonly finished with sugar or served with a dip.", "They are best known for a hot, crisp exterior and soft or chewy centre. Coatings and fryer handling vary."),
    DishSpec("garlic_shrimp", "갈릭 쉬림프", "Garlic shrimp", ("갈릭쉬림프", "갈릭 쉬림프", "garlic shrimp"), None, "Garlic shrimp is a cooked shrimp dish seasoned around garlic, commonly served as a plate or bowl component.", "It is warm, savoury and aromatic with a firm, tender bite. Sauce, butter, spice and side dishes differ by menu."),
    DishSpec("grilled_salmon", "연어 스테이크", "Salmon steak", ("연어스테이크", "연어 스테이크", "salmon steak"), None, "Salmon steak is a thick salmon portion cooked as a central plate, usually by grilling, pan cooking or roasting.", "It is served warm with a browned surface and tender, flaky interior. Sauce, seasoning and doneness are product-specific."),
    DishSpec("fried_shrimp", "새우튀김", "Fried shrimp", ("새우튀김", "새우 튀김", "fried shrimp"), None, "Fried shrimp is shrimp coated in batter or crumbs and cooked until the exterior becomes crisp.", "It is served hot with a firm, tender centre and savoury crust. Coating, oil and shared-fryer exposure require merchant confirmation."),
    DishSpec("fried_squid", "오징어튀김", "Fried squid", ("오징어튀김", "오징어 튀김", "fried squid"), None, "Fried squid is cut squid coated and cooked until browned, appearing as rings, strips or larger pieces.", "It is hot and crisp outside with a chewy, tender centre. Batter and fryer details vary by restaurant."),
    DishSpec("acai_bowl", "아사이볼", "Acai bowl", ("아사이볼", "아사이 볼", "acai bowl"), None, "An acai bowl is a chilled, thick fruit-based bowl topped with fruit, grains, seeds or other additions.", "It is cool, smooth and commonly sweet or tart with contrasting crunchy toppings. Exact base, sugar and toppings vary."),
    DishSpec("cup_bap", "컵밥", "Cup-bap", ("컵밥", "Korean cup rice"), "korean", "Cup-bap is a Korean portable rice-meal format layering rice with compact toppings and sauce in a cup or bowl.", "It is usually served warm and savoury, with texture and heat determined by the topping. No protein or sauce is guaranteed by the format."),
    DishSpec("omurice", "오므라이스", "Omurice", ("오므라이스", "omelette rice"), "japanese", "Omurice is a Japanese modern comfort dish pairing seasoned rice with a cooked egg covering and sauce.", "It is served warm, soft and savoury, often with sweet-tangy sauce. Rice seasoning, filling and egg style vary."),
    DishSpec("tonkatsu", "돈카츠", "Tonkatsu", ("돈카츠", "Japanese pork cutlet"), "japanese", "Tonkatsu is a Japanese breaded pork cutlet cooked until the coating is crisp and the meat is tender.", "It is served warm with a savoury crust and commonly a tangy sauce. Cut, oil and accompaniments depend on the restaurant."),
    DishSpec("katsudon", "가츠동", "Katsudon", ("가츠동", "Japanese cutlet rice bowl"), "japanese", "Katsudon is a Japanese rice bowl topped with a cooked cutlet and a seasoned mixture that often softens part of the crust.", "It is warm, savoury and soft with some crisp texture remaining. Cutlet type, egg and sauce must be confirmed per menu."),
    DishSpec("ramen_japanese", "일본 라멘", "Japanese ramen", ("일본라멘", "일본 라멘", "돈코츠라멘", "미소라멘", "쇼유라멘", "Japanese ramen"), "japanese", "Japanese ramen is a noodle-soup family pairing wheat noodles with a seasoned broth and varied toppings.", "It is served steaming hot and ranges from clean and light to thick, rich or spicy. Broth base and toppings are menu-specific."),
    DishSpec("gyudon", "규동", "Gyudon", ("규동", "Japanese beef bowl"), "japanese", "Gyudon is a Japanese rice bowl traditionally topped with thinly cooked beef and onion in a savoury-sweet seasoning.", "It is served warm with soft rice and tender topping. Actual protein, garnish and sauce composition require menu confirmation."),
    DishSpec("tempura", "덴푸라", "Tempura", ("덴푸라", "텐푸라", "tempura"), "japanese", "Tempura is a Japanese fried-dish family in which seafood or vegetables receive a light batter before cooking.", "It is served hot with a delicate crisp coating. The name does not establish the item inside or shared-fryer safety."),
    DishSpec("okonomiyaki", "오코노미야키", "Okonomiyaki", ("오코노미야키", "오코노미야끼", "Japanese savoury pancake"), "japanese", "Okonomiyaki is a Japanese savoury griddle cake combining batter with shredded and optional ingredients, then finishing it with sauce and toppings.", "It is served hot, soft and savoury with browned edges. Fillings and toppings vary substantially."),
    DishSpec("yakisoba", "야키소바", "Yakisoba", ("야키소바", "야끼소바", "Japanese stir-fried noodles"), "japanese", "Yakisoba is a Japanese stir-fried noodle dish seasoned with a savoury, lightly sweet sauce and optional vegetables or protein.", "It is served warm with chewy noodles and browned aromas. Protein and toppings are not fixed."),
    DishSpec("gyoza", "교자", "Gyoza", ("교자", "Japanese gyoza"), "japanese", "Gyoza are Japanese dumplings with a thin wrapper around a seasoned filling, commonly pan-fried, steamed or boiled.", "They are served warm with a tender wrapper and sometimes a crisp base. Filling and cooking method vary."),
    DishSpec("pho", "쌀국수", "Pho-style rice noodles", ("쌀국수", "베트남 쌀국수", "Vietnamese rice noodle soup"), "southeast_asian", "Pho is a Vietnamese noodle-soup family built around rice noodles in an aromatic broth with garnishes and optional protein.", "It is served steaming hot with soft noodles and a clean, savoury broth. Protein, herbs and sauces differ by menu."),
    DishSpec("pad_thai", "팟타이", "Pad Thai", ("팟타이", "Thai stir-fried rice noodles"), "southeast_asian", "Pad Thai is a Thai stir-fried rice-noodle dish balancing savoury, sweet and tangy seasoning with optional protein and garnishes.", "It is served warm with chewy noodles and contrasting crunchy additions. Peanut, seafood and heat must be verified per menu."),
    DishSpec("bun_cha", "분짜", "Bun cha", ("분짜", "Vietnamese bun cha"), "southeast_asian", "Bun cha is a Vietnamese meal pairing rice noodles, grilled components, herbs and a dipping broth or sauce.", "It combines warm grilled aromas with cool noodles and fresh textures. Meat and sauce composition vary by restaurant."),
    DishSpec("banh_mi", "반미", "Banh mi", ("반미", "반미 샌드위치", "Vietnamese banh mi"), "southeast_asian", "Banh mi is a Vietnamese filled-bread format using a light, crisp roll with savoury fillings, pickled vegetables and herbs in many combinations.", "It is served at room temperature or warm with crisp, soft and tangy contrasts. The filling is menu-specific."),
    DishSpec("nasi_goreng", "나시고렝", "Nasi goreng", ("나시고렝", "나시고랭", "Indonesian fried rice"), "southeast_asian", "Nasi goreng is an Indonesian fried-rice family seasoned for a deeply savoury, aromatic profile and served with varied toppings.", "It is served hot with separated, stir-fried grains. Sweetness, chilli, protein and garnishes differ by recipe."),
    DishSpec("tom_yum", "똠얌", "Tom yum", ("똠얌", "톰얌", "Thai hot and sour soup"), "southeast_asian", "Tom yum is a Thai soup family known for an aromatic hot-and-sour balance built from herbs, acidity and optional chilli.", "It is served hot with a light or creamy broth depending on style. Seafood, meat, dairy-like additions and heat level vary."),
    DishSpec("spring_roll", "스프링롤", "Spring roll", ("스프링롤", "짜조", "spring roll"), "southeast_asian", "Spring roll is a wrapped snack family with fresh and fried forms across Southeast and East Asian cuisines.", "Fresh versions are cool and crisp; fried versions are hot and crunchy. Wrapper, filling and cooking method must be read from the menu."),
    DishSpec("mala_tang", "마라탕", "Malatang", ("마라탕", "Chinese malatang"), "chinese", "Malatang is a Chinese hot-pot-style bowl in which selected ingredients are cooked in a seasoned broth associated with chilli heat and numbing spice.", "It is served steaming hot and can be intensely aromatic or spicy. Broth, ingredient selection and heat vary by restaurant."),
    DishSpec("mala_xiangguo", "마라샹궈", "Mala xiang guo", ("마라샹궈", "Chinese dry mala pot"), "chinese", "Mala xiang guo is a Chinese dry-pot style that stir-fries selected ingredients with aromatic chilli and numbing-spice seasoning.", "It is served hot, savoury and commonly spicy with varied textures. Ingredients and heat are chosen or defined by the menu."),
    DishSpec("mapo_tofu", "마파두부", "Mapo tofu", ("마파두부", "Chinese mapo tofu"), "chinese", "Mapo tofu is a Chinese tofu dish cooked in a savoury sauce commonly associated with chilli and aromatic numbing spice.", "It is served hot with soft tofu and a thick, robust sauce. Meat content and spice level vary by recipe."),
    DishSpec("dim_sum", "딤섬", "Dim sum", ("딤섬", "Chinese dim sum"), "chinese", "Dim sum is a Chinese small-dish tradition encompassing steamed, baked and fried dumplings, buns and other bite-sized foods.", "Textures and serving temperatures vary by item, so the broad name does not establish filling, wrapper or cooking method."),
    DishSpec("xiaolongbao", "샤오롱바오", "Xiaolongbao", ("샤오롱바오", "소룡포", "soup dumplings"), "chinese", "Xiaolongbao are Chinese steamed dumplings with a thin wrapper enclosing a savoury filling and hot broth-like juices.", "They are served hot with a tender wrapper. Filling, broth and allergens require product-specific confirmation."),
    DishSpec("fried_noodles", "볶음면", "Stir-fried noodles", ("볶음면", "stir-fried noodles"), None, "Stir-fried noodles are a broad dish family in which cooked noodles are tossed over high heat with seasoning and optional additions.", "They are served warm, savoury and chewy, with sauce, cuisine and ingredients determined by the named variation."),
    DishSpec("fried_rice", "볶음밥", "Fried rice", ("볶음밥", "fried rice"), None, "Fried rice is a broad rice-dish family in which cooked grains are stir-fried with seasoning and optional vegetables or protein.", "It is served hot or warm with separated, savoury grains. Cuisine, oil, protein and sauces vary by product."),
)


def _front_matter(
    *,
    concept_id: str,
    concept_type: str,
    name_ko: str,
    name_en: str,
    aliases: Sequence[str],
    parent_id: str | None,
) -> str:
    payload = {
        "concept_id": concept_id,
        "concept_type": concept_type,
        "name_ko": name_ko,
        "name_en": name_en,
        "aliases": list(aliases),
        "language": "en",
        "parents": (
            [
                {
                    "concept_id": parent_id,
                    "relation_type": "IS_A",
                    "inherit_claims": False,
                    "source_ref": f"YOBI reviewed demo taxonomy: {concept_id} lineage v2",
                }
            ]
            if parent_id
            else []
        ),
        "source_type": "SYNTHETIC_WIKI",
        "source_refs": [f"YOBI reviewed demo culinary summary: {concept_id} v2"],
        "license_state": "SYNTHETIC",
        "review_status": "REVIEWED_DEMO",
        "is_synthetic": True,
        "version": VERSION,
        "updated_at": UPDATED_AT,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_cuisine(spec: CuisineSpec) -> str:
    front = _front_matter(
        concept_id=spec.concept_id,
        concept_type="CUISINE",
        name_ko=spec.name_ko,
        name_en=spec.name_en,
        aliases=spec.aliases,
        parent_id=None,
    )
    return (
        f"---\n{front}\n---\n# {spec.name_en}\n\n"
        f"{spec.overview}\n\n{spec.range_note}\n\n"
        "This is a reviewed synthetic general-food description used for demo taxonomy. "
        "It is not a claim about a restaurant recipe, certification, portion, allergen safety, "
        "dietary suitability or menu-specific spice level.\n"
    )


def render_dish(spec: DishSpec) -> str:
    parent_id = f"dish_{spec.cuisine}_cuisine" if spec.cuisine else None
    front = _front_matter(
        concept_id=spec.concept_id,
        concept_type="FAMILY",
        name_ko=spec.name_ko,
        name_en=spec.name_en,
        aliases=spec.aliases,
        parent_id=parent_id,
    )
    return (
        f"---\n{front}\n---\n# {spec.name_en}\n\n"
        f"{spec.overview}\n\n{spec.experience}\n\n"
        "This is general culinary guidance, not a statement about one merchant's recipe, "
        "ingredients, certification, allergens, portion or menu-specific spice level. "
        "Check the current merchant information before ordering.\n"
    )


def expected_files() -> list[tuple[Path, str]]:
    values: list[tuple[Path, str]] = []
    for cuisine_spec in CUISINES:
        values.append(
            (
                OUTPUT / f"cuisine-{cuisine_spec.slug}.md",
                render_cuisine(cuisine_spec),
            )
        )
    for dish_spec in DISHES:
        values.append((OUTPUT / f"{dish_spec.slug}.md", render_dish(dish_spec)))
    return values


def validate_manifest() -> None:
    concept_ids = [spec.concept_id for spec in CUISINES]
    concept_ids.extend(spec.concept_id for spec in DISHES)
    if len(concept_ids) != len(set(concept_ids)):
        raise RuntimeError("EXPANSION_DUPLICATE_CONCEPT_ID")
    known_cuisines = {spec.slug for spec in CUISINES} | {"korean"}
    unknown = sorted(
        {
            spec.cuisine
            for spec in DISHES
            if spec.cuisine is not None and spec.cuisine not in known_cuisines
        }
    )
    if unknown:
        raise RuntimeError(f"EXPANSION_UNKNOWN_CUISINE:{','.join(unknown)}")
    forbidden_aliases = {"메뉴", "메인", "사이드", "세트", "추천", "신메뉴", "음식"}
    for spec in DISHES:
        if forbidden_aliases.intersection(spec.aliases):
            raise RuntimeError(f"EXPANSION_UNSAFE_ALIAS:{spec.concept_id}")
        if len(spec.overview) < 90 or len(spec.experience) < 80:
            raise RuntimeError(f"EXPANSION_THIN_PROSE:{spec.concept_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    validate_manifest()
    files = expected_files()
    expected_names = {path.name for path, _ in files}
    existing_names = {path.name for path in OUTPUT.glob("*.md")} if OUTPUT.exists() else set()
    if args.check:
        if existing_names != expected_names:
            raise RuntimeError("EXPANSION_GENERATED_FILE_SET_MISMATCH")
        for path, content in files:
            if path.read_text(encoding="utf-8") != content:
                raise RuntimeError(f"EXPANSION_GENERATED_CONTENT_MISMATCH:{path.name}")
        print(json.dumps({"status": "PASS", "documents": len(files)}, sort_keys=True))
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(existing_names - expected_names)
    if unexpected:
        raise RuntimeError(f"EXPANSION_UNEXPECTED_FILES:{','.join(unexpected)}")
    for path, content in files:
        path.write_text(content, encoding="utf-8")
    print(json.dumps({"status": "WRITTEN", "documents": len(files)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
