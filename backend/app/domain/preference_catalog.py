from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PREFERENCE_CATALOG_VERSION = "preference-catalog-2026.08.17-v3"

SUPPORTED_LOCALES = (
    "en",
    "ko",
    "ja",
    "zh-CN",
    "zh-TW",
    "es",
    "fr",
    "de",
    "it",
    "pt",
    "th",
    "vi",
    "id",
    "ar",
    "hi",
    "ru",
)


def _localized(*values: str) -> dict[str, str]:
    if len(values) != len(SUPPORTED_LOCALES):
        raise ValueError("PREFERENCE_LOCALIZATION_LENGTH_MISMATCH")
    return dict(zip(SUPPORTED_LOCALES, values))

PreferenceCategoryCode = Literal[
    "cuisine_origins",
    "flavors",
    "main_ingredients",
    "food_forms",
    "temperatures",
    "price_bands",
    "textures",
    "cooking_methods",
]

_CATEGORY_OPTION_CODES: tuple[tuple[PreferenceCategoryCode, tuple[str, ...]], ...] = (
    (
        "cuisine_origins",
        ("KOREAN", "CHINESE", "WESTERN", "SOUTHEAST_ASIAN", "MEXICAN"),
    ),
    (
        "flavors",
        ("SPICY", "SWEET", "SALTY", "SOUR", "NUTTY_SAVORY", "CLEAN_MILD"),
    ),
    (
        "main_ingredients",
        ("BEEF", "PORK", "CHICKEN", "FISH_SEAFOOD", "VEGETABLE"),
    ),
    (
        "food_forms",
        ("RICE", "NOODLES", "SOUP", "STEW_HOTPOT", "BREAD", "SALAD", "GRILLED_DISH"),
    ),
    ("temperatures", ("HOT", "WARM", "ROOM_TEMPERATURE", "COOL", "FROZEN")),
    (
        "price_bands",
        ("UNDER_10000", "FROM_10000_TO_19999", "FROM_20000_TO_29999", "OVER_30000"),
    ),
    ("textures", ("CRISPY", "CHEWY", "SOFT", "CRUNCHY", "THICK_RICH")),
    (
        "cooking_methods",
        ("GRILLED", "BOILED", "SIMMERED", "STEAMED", "FRIED", "STIR_FRIED", "BAKED"),
    ),
)

# v3 expands the catalog without removing legacy stable codes such as WESTERN.
# Legacy values remain parseable for old sessions, while only codes with active
# reviewed Wiki support and useful live-catalog coverage are exposed to the UI.
_ADDITIONAL_CATEGORY_OPTION_CODES: dict[PreferenceCategoryCode, tuple[str, ...]] = {
    "cuisine_origins": ("JAPANESE", "ITALIAN", "AMERICAN"),
    "food_forms": ("BOWL_POKE", "DESSERT_BAKERY", "FRIED_SNACK"),
}

_ADDITIONAL_OPTION_LABELS: dict[str, dict[str, str]] = {
    "JAPANESE": _localized(
        "Japanese", "일식", "日本料理", "日餐", "日式料理", "Japonesa", "Japonaise",
        "Japanisch", "Giapponese", "Japonesa", "อาหารญี่ปุ่น", "Món Nhật", "Jepang",
        "ياباني", "जापानी", "Японская",
    ),
    "ITALIAN": _localized(
        "Italian", "이탈리안", "イタリア料理", "意大利餐", "義大利料理", "Italiana",
        "Italienne", "Italienisch", "Italiana", "Italiana", "อาหารอิตาเลียน",
        "Món Ý", "Italia", "إيطالي", "इटैलियन", "Итальянская",
    ),
    "AMERICAN": _localized(
        "American & grill", "아메리칸·그릴", "アメリカ料理・グリル", "美式与烧烤",
        "美式與燒烤", "Americana y parrilla", "Américaine et grillades",
        "Amerikanisch & Grill", "Americana e grill", "Americana e grelhados",
        "อเมริกันและกริลล์", "Món Mỹ và đồ nướng", "Amerika & panggang",
        "أمريكي ومشويات", "अमेरिकी और ग्रिल", "Американская и гриль",
    ),
    "BOWL_POKE": _localized(
        "Bowls & poke", "덮밥·포케", "丼・ポケ", "盖饭与波奇碗", "蓋飯與波奇碗",
        "Bowls y poke", "Bols et poke", "Bowls & Poke", "Bowl e poke", "Bowls e poke",
        "ข้าวหน้าและโปเก", "Cơm tô và poke", "Rice bowl & poke", "أطباق الأرز والبوكي",
        "राइस बाउल और पोके", "Боулы и поке",
    ),
    "DESSERT_BAKERY": _localized(
        "Bakery & dessert", "베이커리·디저트", "ベーカリー・デザート", "烘焙与甜点",
        "烘焙與甜點", "Panadería y postre", "Boulangerie et dessert",
        "Gebäck & Dessert", "Panetteria e dessert", "Padaria e sobremesa",
        "เบเกอรี่และของหวาน", "Bánh và món tráng miệng", "Roti & pencuci mulut",
        "مخبوزات وحلويات", "बेकरी और मिठाई", "Выпечка и десерт",
    ),
    "FRIED_SNACK": _localized(
        "Fried snacks", "튀김·스낵", "揚げ物・スナック", "炸物小吃", "炸物小吃",
        "Fritos y snacks", "Fritures et snacks", "Frittierte Snacks", "Fritti e snack",
        "Fritos e petiscos", "ของทอดและของว่าง", "Đồ chiên và ăn vặt",
        "Gorengan & camilan", "مقليات ووجبات خفيفة", "तले स्नैक्स", "Жареные закуски",
    ),
}

# Each pack contains one localized category label followed by its option labels.
# The positional schema is validated at import so a new stable code cannot ship
# without every currently supported locale.
_LABEL_PACKS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "en": (
        ("Cuisine", ("Korean", "Chinese", "Western", "Southeast Asian", "Mexican")),
        ("Flavor", ("Spicy", "Sweet", "Salty", "Sour", "Nutty and savory", "Clean and mild")),
        ("Main ingredient", ("Beef", "Pork", "Chicken", "Fish and seafood", "Vegetables")),
        (
            "Food form",
            ("Rice", "Noodles", "Soup", "Stew or hot pot", "Bread", "Salad", "Grilled dish"),
        ),
        ("Temperature", ("Hot", "Warm", "Room temperature", "Cool", "Frozen")),
        ("Price", ("Under ₩10,000", "₩10,000–19,999", "₩20,000–29,999", "₩30,000 and over")),
        ("Texture", ("Crispy", "Chewy", "Soft", "Crunchy", "Thick and rich")),
        (
            "Cooking method",
            ("Grilled", "Boiled", "Simmered", "Steamed", "Fried", "Stir-fried", "Baked"),
        ),
    ),
    "ko": (
        ("음식 계통", ("한식", "중식", "양식", "동남아 음식", "멕시칸")),
        ("맛", ("매운맛", "단맛", "짠맛", "새콤한맛", "고소하고 감칠맛", "담백한맛")),
        ("주재료", ("소고기", "돼지고기", "닭고기", "생선·해산물", "채소")),
        ("음식 형태", ("밥", "면", "국물", "찌개·전골", "빵", "샐러드", "구이")),
        ("온도", ("뜨거운", "따뜻한", "상온", "시원한", "냉동")),
        ("가격대", ("1만원 미만", "1만–2만원 미만", "2만–3만원 미만", "3만원 이상")),
        ("식감", ("바삭한", "쫄깃한", "부드러운", "아삭한", "걸쭉하고 진한")),
        ("조리 방식", ("구운", "삶은", "푹 끓인", "찐", "튀긴", "볶은", "오븐에 구운")),
    ),
    "ja": (
        ("料理の系統", ("韓国料理", "中華料理", "洋食", "東南アジア料理", "メキシコ料理")),
        ("味", ("辛い", "甘い", "塩味", "酸味", "香ばしくうま味", "あっさり")),
        ("主な食材", ("牛肉", "豚肉", "鶏肉", "魚介類", "野菜")),
        ("料理の形", ("ご飯", "麺", "スープ", "鍋・煮込み", "パン", "サラダ", "焼き料理")),
        ("温度", ("熱々", "温かい", "常温", "冷たい", "冷凍")),
        ("価格帯", ("1万ウォン未満", "1万～2万ウォン未満", "2万～3万ウォン未満", "3万ウォン以上")),
        ("食感", ("カリッと", "もちもち", "やわらかい", "シャキシャキ", "濃厚でとろみ")),
        ("調理法", ("焼く", "ゆでる", "煮込む", "蒸す", "揚げる", "炒める", "オーブン焼き")),
    ),
    "zh-CN": (
        ("菜系", ("韩国料理", "中餐", "西餐", "东南亚料理", "墨西哥料理")),
        ("口味", ("辣", "甜", "咸", "酸", "香浓鲜美", "清淡")),
        ("主要食材", ("牛肉", "猪肉", "鸡肉", "鱼和海鲜", "蔬菜")),
        ("食物形式", ("米饭", "面", "汤", "炖菜或火锅", "面包", "沙拉", "烤制菜")),
        ("温度", ("热烫", "温热", "常温", "凉爽", "冷冻")),
        ("价格区间", ("1万韩元以下", "1万–2万韩元", "2万–3万韩元", "3万韩元以上")),
        ("口感", ("酥脆", "有嚼劲", "柔软", "爽脆", "浓稠醇厚")),
        ("烹饪方式", ("烤", "煮", "炖", "蒸", "炸", "炒", "烘焙")),
    ),
    "zh-TW": (
        ("菜系", ("韓國料理", "中餐", "西餐", "東南亞料理", "墨西哥料理")),
        ("口味", ("辣", "甜", "鹹", "酸", "香濃鮮美", "清淡")),
        ("主要食材", ("牛肉", "豬肉", "雞肉", "魚和海鮮", "蔬菜")),
        ("食物形式", ("米飯", "麵", "湯", "燉菜或火鍋", "麵包", "沙拉", "烤製料理")),
        ("溫度", ("熱燙", "溫熱", "常溫", "涼爽", "冷凍")),
        ("價格區間", ("1萬韓元以下", "1萬–2萬韓元", "2萬–3萬韓元", "3萬韓元以上")),
        ("口感", ("酥脆", "有嚼勁", "柔軟", "爽脆", "濃稠醇厚")),
        ("烹調方式", ("烤", "煮", "燉", "蒸", "炸", "炒", "烘焙")),
    ),
    "es": (
        ("Tipo de cocina", ("Coreana", "China", "Occidental", "Del Sudeste Asiático", "Mexicana")),
        ("Sabor", ("Picante", "Dulce", "Salado", "Ácido", "A nuez y sabroso", "Suave y ligero")),
        ("Ingrediente principal", ("Ternera", "Cerdo", "Pollo", "Pescado y marisco", "Verduras")),
        (
            "Tipo de plato",
            (
                "Arroz",
                "Fideos",
                "Sopa",
                "Guiso u olla caliente",
                "Pan",
                "Ensalada",
                "Plato a la parrilla",
            ),
        ),
        (
            "Temperatura",
            ("Muy caliente", "Templado", "A temperatura ambiente", "Fresco", "Congelado"),
        ),
        ("Precio", ("Menos de ₩10.000", "₩10.000–19.999", "₩20.000–29.999", "₩30.000 o más")),
        ("Textura", ("Crujiente", "Masticable", "Suave", "Crocante", "Espeso e intenso")),
        (
            "Método de cocción",
            (
                "A la parrilla",
                "Hervido",
                "Cocido a fuego lento",
                "Al vapor",
                "Frito",
                "Salteado",
                "Horneado",
            ),
        ),
    ),
    "fr": (
        ("Cuisine", ("Coréenne", "Chinoise", "Occidentale", "D’Asie du Sud-Est", "Mexicaine")),
        (
            "Saveur",
            ("Épicée", "Sucrée", "Salée", "Acidulée", "Noisettée et savoureuse", "Douce et légère"),
        ),
        ("Ingrédient principal", ("Bœuf", "Porc", "Poulet", "Poisson et fruits de mer", "Légumes")),
        (
            "Type de plat",
            ("Riz", "Nouilles", "Soupe", "Ragoût ou fondue", "Pain", "Salade", "Plat grillé"),
        ),
        ("Température", ("Très chaud", "Chaud", "Température ambiante", "Frais", "Glacé")),
        ("Prix", ("Moins de 10 000 ₩", "10 000–19 999 ₩", "20 000–29 999 ₩", "30 000 ₩ et plus")),
        ("Texture", ("Croustillante", "Moelleuse", "Tendre", "Croquante", "Épaisse et riche")),
        ("Cuisson", ("Grillé", "Bouilli", "Mijoté", "À la vapeur", "Frit", "Sauté", "Au four")),
    ),
    "de": (
        ("Küche", ("Koreanisch", "Chinesisch", "Westlich", "Südostasiatisch", "Mexikanisch")),
        (
            "Geschmack",
            ("Scharf", "Süß", "Salzig", "Sauer", "Nussig und herzhaft", "Mild und leicht"),
        ),
        ("Hauptzutat", ("Rind", "Schwein", "Huhn", "Fisch und Meeresfrüchte", "Gemüse")),
        (
            "Gerichtsform",
            ("Reis", "Nudeln", "Suppe", "Eintopf oder Hotpot", "Brot", "Salat", "Grillgericht"),
        ),
        ("Temperatur", ("Sehr heiß", "Warm", "Zimmertemperatur", "Kühl", "Gefroren")),
        ("Preisspanne", ("Unter 10.000 ₩", "10.000–19.999 ₩", "20.000–29.999 ₩", "Ab 30.000 ₩")),
        ("Konsistenz", ("Knusprig", "Bissfest", "Weich", "Kernig", "Dick und gehaltvoll")),
        (
            "Zubereitung",
            ("Gegrillt", "Gekocht", "Geschmort", "Gedämpft", "Frittiert", "Gebraten", "Gebacken"),
        ),
    ),
    "it": (
        ("Cucina", ("Coreana", "Cinese", "Occidentale", "Del Sud-est asiatico", "Messicana")),
        (
            "Sapore",
            ("Piccante", "Dolce", "Salato", "Aspro", "Nocciolato e saporito", "Delicato e leggero"),
        ),
        (
            "Ingrediente principale",
            ("Manzo", "Maiale", "Pollo", "Pesce e frutti di mare", "Verdure"),
        ),
        (
            "Tipo di piatto",
            (
                "Riso",
                "Noodles",
                "Zuppa",
                "Stufato o hot pot",
                "Pane",
                "Insalata",
                "Piatto alla griglia",
            ),
        ),
        ("Temperatura", ("Bollente", "Caldo", "A temperatura ambiente", "Fresco", "Congelato")),
        (
            "Fascia di prezzo",
            ("Meno di ₩10.000", "₩10.000–19.999", "₩20.000–29.999", "₩30.000 o più"),
        ),
        ("Consistenza", ("Croccante", "Tenace", "Morbido", "Crocchiante", "Denso e ricco")),
        (
            "Cottura",
            (
                "Alla griglia",
                "Bollito",
                "Cotto lentamente",
                "Al vapore",
                "Fritto",
                "Saltato",
                "Al forno",
            ),
        ),
    ),
    "pt": (
        ("Cozinha", ("Coreana", "Chinesa", "Ocidental", "Do Sudeste Asiático", "Mexicana")),
        (
            "Sabor",
            ("Picante", "Doce", "Salgado", "Ácido", "Acastanhado e saboroso", "Suave e leve"),
        ),
        (
            "Ingrediente principal",
            ("Carne bovina", "Carne suína", "Frango", "Peixe e frutos do mar", "Legumes"),
        ),
        (
            "Tipo de prato",
            ("Arroz", "Macarrão", "Sopa", "Ensopado ou hot pot", "Pão", "Salada", "Prato grelhado"),
        ),
        ("Temperatura", ("Muito quente", "Morno", "Temperatura ambiente", "Fresco", "Congelado")),
        (
            "Faixa de preço",
            ("Abaixo de ₩10.000", "₩10.000–19.999", "₩20.000–29.999", "₩30.000 ou mais"),
        ),
        ("Textura", ("Crocante", "Mastigável", "Macio", "Crocante e firme", "Espesso e rico")),
        (
            "Preparo",
            ("Grelhado", "Cozido", "Cozido lentamente", "No vapor", "Frito", "Salteado", "Assado"),
        ),
    ),
    "th": (
        ("ประเภทอาหาร", ("เกาหลี", "จีน", "ตะวันตก", "เอเชียตะวันออกเฉียงใต้", "เม็กซิกัน")),
        ("รสชาติ", ("เผ็ด", "หวาน", "เค็ม", "เปรี้ยว", "หอมมันและกลมกล่อม", "อ่อนและเบา")),
        ("วัตถุดิบหลัก", ("เนื้อวัว", "เนื้อหมู", "ไก่", "ปลาและอาหารทะเล", "ผัก")),
        ("รูปแบบอาหาร", ("ข้าว", "เส้น", "ซุป", "สตูว์หรือหม้อไฟ", "ขนมปัง", "สลัด", "อาหารย่าง")),
        ("อุณหภูมิ", ("ร้อนจัด", "อุ่น", "อุณหภูมิห้อง", "เย็น", "แช่แข็ง")),
        ("ช่วงราคา", ("ต่ำกว่า ₩10,000", "₩10,000–19,999", "₩20,000–29,999", "₩30,000 ขึ้นไป")),
        ("เนื้อสัมผัส", ("กรอบ", "เหนียวนุ่ม", "นุ่ม", "กรุบกรอบ", "ข้นและเข้มข้น")),
        ("วิธีปรุง", ("ย่าง", "ต้ม", "เคี่ยว", "นึ่ง", "ทอด", "ผัด", "อบ")),
    ),
    "vi": (
        ("Nền ẩm thực", ("Hàn Quốc", "Trung Quốc", "Phương Tây", "Đông Nam Á", "Mexico")),
        ("Hương vị", ("Cay", "Ngọt", "Mặn", "Chua", "Bùi và đậm đà", "Thanh nhẹ")),
        ("Nguyên liệu chính", ("Thịt bò", "Thịt heo", "Thịt gà", "Cá và hải sản", "Rau củ")),
        ("Dạng món", ("Cơm", "Mì", "Súp", "Món hầm hoặc lẩu", "Bánh mì", "Salad", "Món nướng")),
        ("Nhiệt độ", ("Nóng hổi", "Ấm", "Nhiệt độ phòng", "Mát", "Đông lạnh")),
        ("Khoảng giá", ("Dưới ₩10.000", "₩10.000–19.999", "₩20.000–29.999", "Từ ₩30.000")),
        ("Kết cấu", ("Giòn", "Dai", "Mềm", "Giòn xốp", "Sánh và đậm")),
        ("Cách chế biến", ("Nướng", "Luộc", "Hầm nhỏ lửa", "Hấp", "Chiên", "Xào", "Đút lò")),
    ),
    "id": (
        ("Jenis masakan", ("Korea", "Tiongkok", "Barat", "Asia Tenggara", "Meksiko")),
        (
            "Rasa",
            ("Pedas", "Manis", "Asin", "Asam", "Gurih dan beraroma kacang", "Ringan dan lembut"),
        ),
        (
            "Bahan utama",
            ("Daging sapi", "Daging babi", "Ayam", "Ikan dan hidangan laut", "Sayuran"),
        ),
        (
            "Bentuk hidangan",
            ("Nasi", "Mi", "Sup", "Semur atau hot pot", "Roti", "Salad", "Hidangan panggang"),
        ),
        ("Suhu", ("Sangat panas", "Hangat", "Suhu ruang", "Sejuk", "Beku")),
        (
            "Kisaran harga",
            ("Di bawah ₩10.000", "₩10.000–19.999", "₩20.000–29.999", "₩30.000 ke atas"),
        ),
        ("Tekstur", ("Renyah", "Kenyal", "Lembut", "Garing", "Kental dan kaya")),
        (
            "Cara memasak",
            (
                "Dipanggang",
                "Direbus",
                "Dimasak perlahan",
                "Dikukus",
                "Digoreng",
                "Ditumis",
                "Dioven",
            ),
        ),
    ),
    "ar": (
        ("نوع المطبخ", ("كوري", "صيني", "غربي", "جنوب شرق آسيوي", "مكسيكي")),
        ("النكهة", ("حار", "حلو", "مالح", "حامض", "بنكهة المكسرات ولذيذ", "خفيف ومعتدل")),
        ("المكوّن الرئيسي", ("لحم بقري", "لحم خنزير", "دجاج", "سمك ومأكولات بحرية", "خضروات")),
        ("شكل الطبق", ("أرز", "نودلز", "حساء", "يخنة أو قدر ساخن", "خبز", "سلطة", "طبق مشوي")),
        ("الحرارة", ("شديد السخونة", "دافئ", "بدرجة الغرفة", "بارد", "مجمّد")),
        ("فئة السعر", ("أقل من ₩10,000", "₩10,000–19,999", "₩20,000–29,999", "₩30,000 فأكثر")),
        ("القوام", ("مقرمش", "مطاطي", "طري", "هش", "كثيف وغني")),
        ("طريقة الطهي", ("مشوي", "مسلوق", "مطهو ببطء", "على البخار", "مقلي", "مقلب", "مخبوز")),
    ),
    "hi": (
        ("व्यंजन शैली", ("कोरियाई", "चीनी", "पश्चिमी", "दक्षिण-पूर्व एशियाई", "मैक्सिकन")),
        ("स्वाद", ("तीखा", "मीठा", "नमकीन", "खट्टा", "मेवेदार और स्वादिष्ट", "हल्का और सौम्य")),
        ("मुख्य सामग्री", ("बीफ़", "पोर्क", "चिकन", "मछली और समुद्री भोजन", "सब्ज़ियाँ")),
        ("भोजन का रूप", ("चावल", "नूडल्स", "सूप", "स्ट्यू या हॉट पॉट", "ब्रेड", "सलाद", "ग्रिल किया व्यंजन")),
        ("तापमान", ("बहुत गरम", "गरम", "कमरे के तापमान पर", "ठंडा", "जमा हुआ")),
        ("कीमत", ("₩10,000 से कम", "₩10,000–19,999", "₩20,000–29,999", "₩30,000 या अधिक")),
        ("बनावट", ("कुरकुरा", "चबाने योग्य", "मुलायम", "करारा", "गाढ़ा और भरपूर")),
        (
            "पकाने का तरीका",
            ("ग्रिल किया", "उबला", "धीमी आँच पर", "भाप में", "तला", "स्टर-फ्राइड", "बेक किया"),
        ),
    ),
    "ru": (
        ("Кухня", ("Корейская", "Китайская", "Западная", "Юго-Восточная Азия", "Мексиканская")),
        (
            "Вкус",
            ("Острый", "Сладкий", "Солёный", "Кислый", "Ореховый и насыщенный", "Мягкий и лёгкий"),
        ),
        ("Главный ингредиент", ("Говядина", "Свинина", "Курица", "Рыба и морепродукты", "Овощи")),
        (
            "Вид блюда",
            ("Рис", "Лапша", "Суп", "Рагу или хот-пот", "Хлеб", "Салат", "Блюдо на гриле"),
        ),
        (
            "Температура",
            ("Очень горячее", "Тёплое", "Комнатной температуры", "Прохладное", "Замороженное"),
        ),
        ("Цена", ("До 10 000 ₩", "10 000–19 999 ₩", "20 000–29 999 ₩", "От 30 000 ₩")),
        ("Текстура", ("Хрустящая", "Жевательная", "Мягкая", "Хрусткая", "Густая и насыщенная")),
        (
            "Способ приготовления",
            ("На гриле", "Варёное", "Томлёное", "На пару", "Жареное", "Обжаренное", "Запечённое"),
        ),
    ),
}

_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "KOREAN": ("Korean food", "K-food", "한식", "한국 음식"),
    "CHINESE": ("Chinese food", "Chinese cuisine", "중식", "중국 음식"),
    "WESTERN": ("Western food", "European American food", "양식", "서양 음식"),
    "SOUTHEAST_ASIAN": ("Southeast Asian food", "Thai Vietnamese food", "동남아 음식"),
    "MEXICAN": ("Mexican food", "Mexico cuisine", "멕시칸", "멕시코 음식"),
    "JAPANESE": ("Japanese food", "Japanese cuisine", "일식", "일본 음식"),
    "ITALIAN": ("Italian food", "Italian cuisine", "이탈리안", "이탈리아 음식"),
    "AMERICAN": ("American food", "American cuisine", "아메리칸", "미국 음식"),
    "SPICY": ("spicy hot chili", "매운맛", "매콤한"),
    "SWEET": ("sweet sugary", "단맛", "달콤한"),
    "SALTY": ("salty seasoned", "짠맛", "짭짤한"),
    "SOUR": ("sour tangy acidic", "새콤한맛", "산미"),
    "NUTTY_SAVORY": ("nutty savory umami", "고소한맛", "감칠맛"),
    "CLEAN_MILD": ("clean mild light flavor", "담백한맛", "순한맛"),
    "BEEF": ("beef", "소고기", "쇠고기"),
    "PORK": ("pork", "돼지고기"),
    "CHICKEN": ("chicken", "닭고기"),
    "FISH_SEAFOOD": ("fish seafood shellfish", "생선", "해산물"),
    "VEGETABLE": ("vegetable plant-forward", "채소", "야채"),
    "RICE": ("rice bowl rice dish", "밥", "쌀 요리"),
    "NOODLES": ("noodles pasta", "면", "국수"),
    "SOUP": ("soup broth", "국물", "국"),
    "STEW_HOTPOT": ("stew hot pot casserole", "찌개", "전골"),
    "BREAD": ("bread pastry sandwich", "빵"),
    "SALAD": ("salad raw vegetables", "샐러드"),
    "GRILLED_DISH": ("grilled dish barbecue", "구이", "바비큐"),
    "BOWL_POKE": ("rice bowl poke composed bowl", "덮밥", "포케"),
    "DESSERT_BAKERY": ("bakery dessert pastry cake sweet", "베이커리", "디저트"),
    "FRIED_SNACK": ("fried snack crisp side", "튀김", "스낵"),
    "HOT": ("piping hot steaming", "뜨거운 음식"),
    "WARM": ("warm food", "따뜻한 음식"),
    "ROOM_TEMPERATURE": ("room temperature", "상온 음식"),
    "COOL": ("cool chilled cold", "시원한 음식", "차가운 음식"),
    "FROZEN": ("frozen icy", "냉동", "얼린 음식"),
    "UNDER_10000": ("under 10000 won", "1만원 미만"),
    "FROM_10000_TO_19999": ("10000 to 19999 won", "1만원대"),
    "FROM_20000_TO_29999": ("20000 to 29999 won", "2만원대"),
    "OVER_30000": ("30000 won and over", "3만원 이상"),
    "CRISPY": ("crispy crisp fried", "바삭한"),
    "CHEWY": ("chewy springy", "쫄깃한"),
    "SOFT": ("soft tender", "부드러운"),
    "CRUNCHY": ("crunchy crisp vegetables", "아삭한"),
    "THICK_RICH": ("thick rich creamy dense", "걸쭉한", "진한"),
    "GRILLED": ("grilled charred barbecue", "구운", "구이"),
    "BOILED": ("boiled poached", "삶은", "데친"),
    "SIMMERED": ("simmered stewed slow-cooked", "푹 끓인", "조린"),
    "STEAMED": ("steamed", "찐"),
    "FRIED": ("deep-fried fried", "튀긴"),
    "STIR_FRIED": ("stir-fried sauteed", "볶은"),
    "BAKED": ("baked oven-roasted", "오븐에 구운"),
}

_LANGUAGE_NAME_TO_LOCALE = {
    "English": "en",
    "한국어": "ko",
    "日本語": "ja",
    "中文（简体）": "zh-CN",
    "中文（繁體）": "zh-TW",
    "Español": "es",
    "Français": "fr",
    "Deutsch": "de",
    "Italiano": "it",
    "Português": "pt",
    "ไทย": "th",
    "Tiếng Việt": "vi",
    "Bahasa Indonesia": "id",
    "العربية": "ar",
    "हिन्दी": "hi",
    "Русский": "ru",
}


@dataclass(frozen=True)
class PreferenceOptionDefinition:
    code: str
    labels: dict[str, str]
    query_aliases: tuple[str, ...]


@dataclass(frozen=True)
class PreferenceCategoryDefinition:
    code: PreferenceCategoryCode
    labels: dict[str, str]
    options: tuple[PreferenceOptionDefinition, ...]


class PreferenceSupportEvidence(BaseModel):
    """One reviewed support edge used only to decide whether a UI chip is useful."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category_code: PreferenceCategoryCode
    value_code: str = Field(pattern=r"^[A-Z0-9_]+$")
    menu_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    document_id: str | None = None
    source_kind: Literal[
        "WIKI_PARAGRAPH",
        "WIKI_ESSENTIAL_FACT",
        "MENU_CATALOG",
        "MERCHANT_AD",
        "REVIEW",
    ]
    review_status: Literal["DRAFT", "REVIEWED_DEMO", "VERIFIED"]


_ELIGIBLE_SUPPORT_KINDS = frozenset({"WIKI_PARAGRAPH", "WIKI_ESSENTIAL_FACT", "MENU_CATALOG"})
_REVIEWED_WIKI_KINDS = frozenset({"WIKI_PARAGRAPH", "WIKI_ESSENTIAL_FACT"})


def _build_definitions() -> tuple[PreferenceCategoryDefinition, ...]:
    definitions: list[PreferenceCategoryDefinition] = []
    for category_index, (category_code, option_codes) in enumerate(_CATEGORY_OPTION_CODES):
        category_labels = {
            locale: _LABEL_PACKS[locale][category_index][0] for locale in SUPPORTED_LOCALES
        }
        options = []
        for option_index, option_code in enumerate(option_codes):
            options.append(
                PreferenceOptionDefinition(
                    code=option_code,
                    labels={
                        locale: _LABEL_PACKS[locale][category_index][1][option_index]
                        for locale in SUPPORTED_LOCALES
                    },
                    query_aliases=_QUERY_ALIASES[option_code],
                )
            )
        for option_code in _ADDITIONAL_CATEGORY_OPTION_CODES.get(category_code, ()):
            labels = _ADDITIONAL_OPTION_LABELS[option_code]
            if set(labels) != set(SUPPORTED_LOCALES):
                raise ValueError(f"PREFERENCE_OPTION_LOCALE_MISMATCH:{option_code}")
            options.append(
                PreferenceOptionDefinition(
                    code=option_code,
                    labels=labels,
                    query_aliases=_QUERY_ALIASES[option_code],
                )
            )
        definitions.append(
            PreferenceCategoryDefinition(
                code=category_code,
                labels=category_labels,
                options=tuple(options),
            )
        )
    return tuple(definitions)


PREFERENCE_CATEGORIES = _build_definitions()
PREFERENCE_OPTIONS = {
    option.code: option for category in PREFERENCE_CATEGORIES for option in category.options
}
ALL_PREFERENCE_CODES = frozenset(PREFERENCE_OPTIONS)
CUISINE_ORIGIN_CODES = frozenset(
    option.code
    for category in PREFERENCE_CATEGORIES
    if category.code == "cuisine_origins"
    for option in category.options
)


def preference_option_is_exposable(
    option_code: str,
    *,
    menu_count: int,
    merchant_count: int,
    document_count: int,
) -> bool:
    """Use a stronger evidence floor for broad cuisine promises."""

    if option_code in CUISINE_ORIGIN_CODES:
        return menu_count >= 15 and merchant_count >= 3 and document_count >= 3
    return menu_count >= 3 and merchant_count >= 2 and document_count >= 1


def normalize_preference_locale(value: str) -> str:
    normalized = value.strip()
    if normalized in _LANGUAGE_NAME_TO_LOCALE:
        return _LANGUAGE_NAME_TO_LOCALE[normalized]
    if normalized in SUPPORTED_LOCALES:
        return normalized
    base = normalized.split("-", 1)[0].lower()
    return base if base in SUPPORTED_LOCALES else "en"


def validated_exposed_codes(
    evidence: list[PreferenceSupportEvidence],
    *,
    minimum_menu_count: int = 3,
    minimum_merchant_count: int = 2,
) -> frozenset[str]:
    """Return codes with useful catalog coverage and reviewed Wiki support.

    Merchant advertising and review snippets are ignored even when their text
    resembles a preference. They can never create or rescue an exposed chip.
    """

    valid_pairs = {
        (category.code, option.code)
        for category in PREFERENCE_CATEGORIES
        for option in category.options
    }
    grouped: dict[tuple[str, str], list[PreferenceSupportEvidence]] = defaultdict(list)
    for item in evidence:
        pair = (item.category_code, item.value_code)
        if pair not in valid_pairs:
            raise ValueError(f"UNKNOWN_PREFERENCE_SUPPORT:{item.category_code}:{item.value_code}")
        if item.source_kind in _ELIGIBLE_SUPPORT_KINDS:
            grouped[pair].append(item)

    exposed = set()
    for support_pair, rows in grouped.items():
        menu_ids = {row.menu_id for row in rows}
        merchant_ids = {row.merchant_id for row in rows}
        reviewed_wiki_documents = {
            row.document_id
            for row in rows
            if row.source_kind in _REVIEWED_WIKI_KINDS
            and row.review_status in {"REVIEWED_DEMO", "VERIFIED"}
            and row.document_id
        }
        menu_count = len(menu_ids)
        merchant_count = len(merchant_ids)
        document_count = len(reviewed_wiki_documents)
        if (
            menu_count >= minimum_menu_count
            and merchant_count >= minimum_merchant_count
            and preference_option_is_exposable(
                support_pair[1],
                menu_count=menu_count,
                merchant_count=merchant_count,
                document_count=document_count,
            )
        ):
            exposed.add(support_pair[1])
    return frozenset(exposed)


def localized_preference_catalog(
    locale: str,
    *,
    exposed_codes: frozenset[str],
) -> dict[str, object]:
    """Build the stable localized API payload from already validated coverage."""

    resolved_locale = normalize_preference_locale(locale)
    categories: list[dict[str, object]] = []
    for category in PREFERENCE_CATEGORIES:
        options = [
            {"code": option.code, "label": option.labels[resolved_locale]}
            for option in category.options
            if option.code in exposed_codes
        ]
        if options:
            categories.append(
                {
                    "code": category.code,
                    "label": category.labels[resolved_locale],
                    "options": options,
                }
            )
    return {
        "schema_version": "2",
        "catalog_version": PREFERENCE_CATALOG_VERSION,
        "locale": resolved_locale,
        "categories": categories,
        "spice_references": localized_spice_references(resolved_locale),
    }


def preference_query_aliases(value_code: str, locale: str) -> tuple[str, ...]:
    option = PREFERENCE_OPTIONS.get(value_code)
    if option is None:
        raise ValueError(f"UNKNOWN_PREFERENCE_CODE:{value_code}")
    localized_label = option.labels[normalize_preference_locale(locale)]
    return tuple(dict.fromkeys((localized_label, *option.query_aliases)))


_SPICE_REFERENCE_LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "country": ("Korean examples", "U.S. examples"),
        "KR": (
            "Seolleongtang",
            "Mild kimchi fried rice",
            "Bibimbap with gochujang",
            "Tteokbokki",
            "Spicy jjamppong",
        ),
        "US": (
            "Mac and cheese",
            "Mild buffalo wings",
            "Jalapeño nachos",
            "Hot buffalo wings",
            "Nashville hot chicken",
        ),
    },
    "ko": {
        "country": ("한국 음식 기준", "미국 음식 기준"),
        "KR": ("설렁탕", "순한 김치볶음밥", "고추장 비빔밥", "떡볶이", "매운 짬뽕"),
        "US": ("맥앤치즈", "순한 버펄로윙", "할라피뇨 나초", "매운 버펄로윙", "내슈빌 핫치킨"),
    },
    "ja": {
        "country": ("韓国料理の例", "米国料理の例"),
        "KR": (
            "ソルロンタン",
            "辛さ控えめキムチ炒飯",
            "コチュジャンビビンバ",
            "トッポッキ",
            "辛いチャンポン",
        ),
        "US": (
            "マカロニ＆チーズ",
            "マイルドなバッファローウィング",
            "ハラペーニョナチョス",
            "辛いバッファローウィング",
            "ナッシュビル・ホットチキン",
        ),
    },
    "zh-CN": {
        "country": ("韩国食物示例", "美国食物示例"),
        "KR": ("雪浓汤", "微辣泡菜炒饭", "辣酱拌饭", "辣炒年糕", "辣海鲜汤面"),
        "US": ("芝士通心粉", "微辣水牛城鸡翅", "墨西哥辣椒玉米片", "辣水牛城鸡翅", "纳什维尔辣鸡"),
    },
    "zh-TW": {
        "country": ("韓國食物範例", "美國食物範例"),
        "KR": ("雪濃湯", "微辣泡菜炒飯", "辣醬拌飯", "辣炒年糕", "辣海鮮湯麵"),
        "US": ("起司通心粉", "微辣水牛城雞翅", "墨西哥辣椒玉米片", "辣水牛城雞翅", "納什維爾辣雞"),
    },
}

_SPICE_COUNTRY_LABELS = {
    "es": ("Ejemplos coreanos", "Ejemplos de EE. UU."),
    "fr": ("Exemples coréens", "Exemples américains"),
    "de": ("Koreanische Beispiele", "US-Beispiele"),
    "it": ("Esempi coreani", "Esempi statunitensi"),
    "pt": ("Exemplos coreanos", "Exemplos dos EUA"),
    "th": ("ตัวอย่างอาหารเกาหลี", "ตัวอย่างอาหารสหรัฐฯ"),
    "vi": ("Ví dụ món Hàn", "Ví dụ món Mỹ"),
    "id": ("Contoh makanan Korea", "Contoh makanan AS"),
    "ar": ("أمثلة كورية", "أمثلة أمريكية"),
    "hi": ("कोरियाई उदाहरण", "अमेरिकी उदाहरण"),
    "ru": ("Корейские примеры", "Примеры США"),
}

_SPICE_FOOD_EXAMPLES: dict[str, dict[str, tuple[str, ...]]] = {
    "es": {
        "KR": (
            "Seolleongtang",
            "Arroz frito con kimchi suave",
            "Bibimbap con gochujang",
            "Tteokbokki",
            "Jjamppong picante",
        ),
        "US": (
            "Macarrones con queso",
            "Alitas Buffalo suaves",
            "Nachos con jalapeño",
            "Alitas Buffalo picantes",
            "Pollo picante de Nashville",
        ),
    },
    "fr": {
        "KR": (
            "Seolleongtang",
            "Riz frit au kimchi doux",
            "Bibimbap au gochujang",
            "Tteokbokki",
            "Jjamppong épicé",
        ),
        "US": (
            "Macaroni au fromage",
            "Ailes Buffalo douces",
            "Nachos aux jalapeños",
            "Ailes Buffalo épicées",
            "Poulet épicé de Nashville",
        ),
    },
    "de": {
        "KR": (
            "Seolleongtang",
            "Milder Kimchi-Bratreis",
            "Bibimbap mit Gochujang",
            "Tteokbokki",
            "Scharfes Jjamppong",
        ),
        "US": (
            "Macaroni mit Käse",
            "Milde Buffalo Wings",
            "Jalapeño-Nachos",
            "Scharfe Buffalo Wings",
            "Nashville Hot Chicken",
        ),
    },
    "it": {
        "KR": (
            "Seolleongtang",
            "Riso fritto al kimchi delicato",
            "Bibimbap con gochujang",
            "Tteokbokki",
            "Jjamppong piccante",
        ),
        "US": (
            "Maccheroni al formaggio",
            "Alette Buffalo delicate",
            "Nachos con jalapeño",
            "Alette Buffalo piccanti",
            "Pollo piccante di Nashville",
        ),
    },
    "pt": {
        "KR": (
            "Seolleongtang",
            "Arroz frito com kimchi suave",
            "Bibimbap com gochujang",
            "Tteokbokki",
            "Jjamppong picante",
        ),
        "US": (
            "Macarrão com queijo",
            "Asas Buffalo suaves",
            "Nachos com jalapeño",
            "Asas Buffalo picantes",
            "Frango picante de Nashville",
        ),
    },
    "th": {
        "KR": ("ซอลลองทัง", "ข้าวผัดกิมจิรสอ่อน", "บิบิมบับกับโคชูจัง", "ต็อกบกกี", "จัมปงรสเผ็ด"),
        "US": ("มักกะโรนีชีส", "ปีกไก่บัฟฟาโลรสอ่อน", "นาโชส์ฮาลาปินโญ", "ปีกไก่บัฟฟาโลรสเผ็ด", "ไก่เผ็ดแนชวิลล์"),
    },
    "vi": {
        "KR": (
            "Seolleongtang",
            "Cơm chiên kimchi cay nhẹ",
            "Bibimbap với gochujang",
            "Tteokbokki",
            "Jjamppong cay",
        ),
        "US": (
            "Mì ống phô mai",
            "Cánh gà Buffalo cay nhẹ",
            "Nachos jalapeño",
            "Cánh gà Buffalo cay",
            "Gà cay Nashville",
        ),
    },
    "id": {
        "KR": (
            "Seolleongtang",
            "Nasi goreng kimchi ringan",
            "Bibimbap dengan gochujang",
            "Tteokbokki",
            "Jjamppong pedas",
        ),
        "US": (
            "Makaroni keju",
            "Sayap Buffalo ringan",
            "Nachos jalapeño",
            "Sayap Buffalo pedas",
            "Ayam pedas Nashville",
        ),
    },
    "ar": {
        "KR": (
            "سوللونغتانغ",
            "أرز مقلي بالكيمتشي خفيف الحدة",
            "بيبيمباب مع غوتشوجانغ",
            "تيوكبوكي",
            "جامبونغ حار",
        ),
        "US": (
            "معكرونة بالجبن",
            "أجنحة بافالو خفيفة",
            "ناتشوز بالهالبينو",
            "أجنحة بافالو حارة",
            "دجاج ناشفيل الحار",
        ),
    },
    "hi": {
        "KR": (
            "सोलोंगतांग",
            "हल्का किमची फ्राइड राइस",
            "गोचुजांग वाला बिबिम्बाप",
            "टेटोकबोक्की",
            "तीखा जामपोंग",
        ),
        "US": ("मैक एंड चीज़", "हल्के बफ़ेलो विंग्स", "हालापेन्यो नाचोज़", "तीखे बफ़ेलो विंग्स", "नैशविल हॉट चिकन"),
    },
    "ru": {
        "KR": (
            "Соллонтхан",
            "Неострый жареный рис с кимчи",
            "Пибимпап с кочхуджаном",
            "Ттокпокки",
            "Острый чампон",
        ),
        "US": (
            "Макароны с сыром",
            "Неострые крылышки Баффало",
            "Начос с халапеньо",
            "Острые крылышки Баффало",
            "Острая курица по-нэшвиллски",
        ),
    },
}

# Proper dish names stay recognizable while descriptive portions are localized.
for _locale in SUPPORTED_LOCALES[5:]:
    _SPICE_REFERENCE_LABELS[_locale] = {
        "country": _SPICE_COUNTRY_LABELS[_locale],
        "KR": _SPICE_FOOD_EXAMPLES[_locale]["KR"],
        "US": _SPICE_FOOD_EXAMPLES[_locale]["US"],
    }


def localized_spice_references(locale: str) -> list[dict[str, object]]:
    resolved_locale = normalize_preference_locale(locale)
    labels = _SPICE_REFERENCE_LABELS[resolved_locale]
    return [
        {
            "country": country,
            "label": labels["country"][country_index],
            "levels": [
                {
                    "level": level,
                    "label": str(level),
                    "example": labels[country][level - 1],
                }
                for level in range(1, 6)
            ],
        }
        for country_index, country in enumerate(("KR", "US"))
    ]


def validate_preference_catalog_contract() -> None:
    if set(_LABEL_PACKS) != set(SUPPORTED_LOCALES):
        raise RuntimeError("PREFERENCE_LOCALE_SET_MISMATCH")
    expected_codes = {code for _, codes in _CATEGORY_OPTION_CODES for code in codes}
    expected_codes.update(
        code
        for codes in _ADDITIONAL_CATEGORY_OPTION_CODES.values()
        for code in codes
    )
    if set(_QUERY_ALIASES) != expected_codes:
        raise RuntimeError("PREFERENCE_QUERY_ALIAS_SET_MISMATCH")
    if len(PREFERENCE_OPTIONS) != len(expected_codes):
        raise RuntimeError("PREFERENCE_OPTION_CODE_DUPLICATE")
    for locale in SUPPORTED_LOCALES:
        pack = _LABEL_PACKS[locale]
        if len(pack) != len(_CATEGORY_OPTION_CODES):
            raise RuntimeError(f"PREFERENCE_CATEGORY_LABEL_MISSING:{locale}")
        for (_, option_codes), (category_label, option_labels) in zip(_CATEGORY_OPTION_CODES, pack):
            if not category_label.strip() or len(option_labels) != len(option_codes):
                raise RuntimeError(f"PREFERENCE_OPTION_LABEL_MISSING:{locale}")
            if any(not label.strip() for label in option_labels):
                raise RuntimeError(f"PREFERENCE_OPTION_LABEL_EMPTY:{locale}")
        spice = _SPICE_REFERENCE_LABELS[locale]
        if any(
            len(spice[key]) != expected for key, expected in (("country", 2), ("KR", 5), ("US", 5))
        ):
            raise RuntimeError(f"SPICE_REFERENCE_LABEL_MISSING:{locale}")


validate_preference_catalog_contract()
