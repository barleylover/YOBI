import { LANGUAGES, LANGUAGE_META, type SupportedLanguage } from "./locale";
import { getRecommendationCopy } from "./recommendationI18n";

interface GroupVocabulary {
  coreTitle: string;
  coreHelp: string;
  additionalTitle: string;
  exactTitle: string;
  semanticTitle: string;
  semanticHelp: string;
}

const vocabulary: Record<SupportedLanguage, GroupVocabulary> = {
  English: {
    coreTitle: "Core preferences", coreHelp: "Start with 1–3 subjective choices that matter most to you.", additionalTitle: "Additional preferences", exactTitle: "Exact conditions", semanticTitle: "Similar words, different jobs", semanticHelp: "SPICY is a flavor you enjoy; maximum spice is a hard cap. VEGETABLE is a preferred main ingredient; vegan is a dietary condition. Temperature, texture and cooking method describe different facets—use each option description to distinguish hot or cold, mouthfeel, and how the food is prepared.",
  },
  "한국어": {
    coreTitle: "핵심 선호", coreHelp: "가장 중요한 주관적 선호부터 1~3개 골라보세요.", additionalTitle: "추가 선호", exactTitle: "정확 조건", semanticTitle: "비슷한 말, 다른 역할", semanticHelp: "SPICY는 좋아하는 맛이고 최대 맵기는 넘지 않을 강한 상한 조건입니다. VEGETABLE은 선호하는 주재료이고 vegan은 식이 조건입니다. 온도·식감·조리법은 서로 다른 특징이므로 각 설명에서 뜨겁거나 차가움, 입안의 느낌, 만드는 방식을 구분해 주세요.",
  },
  "日本語": {
    coreTitle: "主な好み", coreHelp: "最も大切な主観的な好みを1～3個から選んでください。", additionalTitle: "追加の好み", exactTitle: "厳密な条件", semanticTitle: "似た言葉でも役割は別", semanticHelp: "SPICYは好きな味、最大辛さは超えない上限です。VEGETABLEは好みの主材料、ヴィーガンは食事条件です。温度・食感・調理法は別の特徴なので、各説明で温冷、口当たり、作り方を区別してください。",
  },
  "中文（简体）": {
    coreTitle: "核心偏好", coreHelp: "请先选择 1–3 个最重要的主观偏好。", additionalTitle: "更多偏好", exactTitle: "严格条件", semanticTitle: "相似词语，不同作用", semanticHelp: "SPICY 表示喜欢的味道，最高辣度是不可超过的上限。VEGETABLE 表示偏好的主要食材，纯素则是饮食条件。温度、口感和烹饪方式描述不同维度，请结合各选项说明区分冷热、入口感受和制作方法。",
  },
  "中文（繁體）": {
    coreTitle: "核心偏好", coreHelp: "請先選擇 1–3 個最重要的主觀偏好。", additionalTitle: "更多偏好", exactTitle: "嚴格條件", semanticTitle: "相似詞語，不同作用", semanticHelp: "SPICY 表示喜歡的味道，最高辣度是不可超過的上限。VEGETABLE 表示偏好的主要食材，純素則是飲食條件。溫度、口感和烹調方式描述不同面向，請依各選項說明區分冷熱、入口感受和製作方法。",
  },
  Español: {
    coreTitle: "Preferencias principales", coreHelp: "Empieza con 1–3 preferencias subjetivas que sean importantes para ti.", additionalTitle: "Preferencias adicionales", exactTitle: "Condiciones exactas", semanticTitle: "Palabras parecidas, funciones distintas", semanticHelp: "SPICY es un sabor que te gusta; el picante máximo es un límite estricto. VEGETABLE es un ingrediente principal preferido; vegano es una condición alimentaria. Temperatura, textura y cocción describen aspectos distintos: consulta cada descripción para diferenciar frío o caliente, sensación en boca y preparación.",
  },
  Français: {
    coreTitle: "Préférences principales", coreHelp: "Commencez par 1 à 3 préférences subjectives qui comptent le plus.", additionalTitle: "Préférences supplémentaires", exactTitle: "Conditions précises", semanticTitle: "Des mots proches, des rôles différents", semanticHelp: "SPICY désigne une saveur appréciée ; le piquant maximal est une limite stricte. VEGETABLE est un ingrédient principal souhaité ; végane est une condition alimentaire. Température, texture et cuisson décrivent des aspects différents : lisez chaque description pour distinguer chaud ou froid, sensation en bouche et préparation.",
  },
  Deutsch: {
    coreTitle: "Kernvorlieben", coreHelp: "Wähle zuerst 1–3 subjektive Vorlieben, die dir am wichtigsten sind.", additionalTitle: "Weitere Vorlieben", exactTitle: "Genaue Bedingungen", semanticTitle: "Ähnliche Wörter, verschiedene Aufgaben", semanticHelp: "SPICY ist ein gewünschter Geschmack; die maximale Schärfe ist eine feste Obergrenze. VEGETABLE ist eine bevorzugte Hauptzutat; vegan ist eine Ernährungsbedingung. Temperatur, Textur und Zubereitung beschreiben verschiedene Aspekte – beachte die Erklärungen zu warm oder kalt, Mundgefühl und Zubereitungsart.",
  },
  Italiano: {
    coreTitle: "Preferenze principali", coreHelp: "Inizia con 1–3 preferenze soggettive che contano di più per te.", additionalTitle: "Preferenze aggiuntive", exactTitle: "Condizioni precise", semanticTitle: "Parole simili, ruoli diversi", semanticHelp: "SPICY indica un sapore gradito; il piccante massimo è un limite rigido. VEGETABLE è un ingrediente principale preferito; vegano è una condizione alimentare. Temperatura, consistenza e cottura descrivono aspetti diversi: usa ogni descrizione per distinguere caldo o freddo, sensazione in bocca e preparazione.",
  },
  Português: {
    coreTitle: "Preferências principais", coreHelp: "Comece com 1–3 preferências subjetivas que mais importam para você.", additionalTitle: "Preferências adicionais", exactTitle: "Condições exatas", semanticTitle: "Palavras parecidas, funções diferentes", semanticHelp: "SPICY é um sabor desejado; a picância máxima é um limite rígido. VEGETABLE é um ingrediente principal preferido; vegano é uma condição alimentar. Temperatura, textura e preparo descrevem aspectos diferentes: leia cada descrição para separar quente ou frio, sensação na boca e modo de preparo.",
  },
  "ไทย": {
    coreTitle: "ความชอบหลัก", coreHelp: "เริ่มจากความชอบเชิงความรู้สึกที่สำคัญที่สุด 1–3 ข้อ", additionalTitle: "ความชอบเพิ่มเติม", exactTitle: "เงื่อนไขที่แน่นอน", semanticTitle: "คำคล้ายกันแต่ทำหน้าที่ต่างกัน", semanticHelp: "SPICY คือรสชาติที่ชอบ ส่วนระดับเผ็ดสูงสุดคือขีดจำกัดที่ห้ามเกิน VEGETABLE คือวัตถุดิบหลักที่ชอบ ส่วนวีแกนคือเงื่อนไขด้านอาหาร อุณหภูมิ เนื้อสัมผัส และวิธีปรุงบอกคนละด้าน โปรดอ่านคำอธิบายเพื่อแยกร้อนหรือเย็น ความรู้สึกในปาก และวิธีทำ",
  },
  "Tiếng Việt": {
    coreTitle: "Sở thích chính", coreHelp: "Hãy bắt đầu với 1–3 sở thích chủ quan quan trọng nhất.", additionalTitle: "Sở thích bổ sung", exactTitle: "Điều kiện chính xác", semanticTitle: "Từ gần giống, vai trò khác nhau", semanticHelp: "SPICY là vị bạn thích; độ cay tối đa là giới hạn cứng. VEGETABLE là nguyên liệu chính ưa thích; thuần chay là điều kiện ăn uống. Nhiệt độ, kết cấu và cách nấu mô tả các khía cạnh khác nhau—hãy đọc mô tả để phân biệt nóng hoặc lạnh, cảm giác trong miệng và cách chế biến.",
  },
  "Bahasa Indonesia": {
    coreTitle: "Preferensi utama", coreHelp: "Mulailah dengan 1–3 preferensi subjektif yang paling penting bagi Anda.", additionalTitle: "Preferensi tambahan", exactTitle: "Kondisi pasti", semanticTitle: "Kata mirip, fungsi berbeda", semanticHelp: "SPICY adalah rasa yang disukai; tingkat pedas maksimum adalah batas keras. VEGETABLE adalah bahan utama pilihan; vegan adalah kondisi diet. Suhu, tekstur, dan cara memasak menjelaskan sisi berbeda—baca deskripsi untuk membedakan panas atau dingin, sensasi di mulut, dan cara pengolahan.",
  },
  "العربية": {
    coreTitle: "التفضيلات الأساسية", coreHelp: "ابدأ باختيار 1–3 تفضيلات ذاتية تهمك أكثر.", additionalTitle: "تفضيلات إضافية", exactTitle: "شروط دقيقة", semanticTitle: "كلمات متشابهة وأدوار مختلفة", semanticHelp: "SPICY نكهة تفضلها، أما الحد الأقصى للحِدّة فهو سقف صارم. VEGETABLE مكوّن رئيسي مفضّل، أما النباتي الصرف فهو شرط غذائي. تصف الحرارة والقوام وطريقة الطهي جوانب مختلفة؛ اقرأ وصف كل خيار للتمييز بين الساخن والبارد، والإحساس في الفم، وكيفية التحضير.",
  },
  "हिन्दी": {
    coreTitle: "मुख्य पसंद", coreHelp: "सबसे महत्वपूर्ण 1–3 व्यक्तिपरक पसंद से शुरुआत करें।", additionalTitle: "अतिरिक्त पसंद", exactTitle: "सटीक शर्तें", semanticTitle: "मिलते शब्द, अलग काम", semanticHelp: "SPICY वह स्वाद है जो आपको पसंद है; अधिकतम तीखापन एक सख्त सीमा है। VEGETABLE पसंदीदा मुख्य सामग्री है; वीगन एक भोजन संबंधी शर्त है। तापमान, बनावट और पकाने का तरीका अलग पहलू बताते हैं—गर्म या ठंडा, मुँह का एहसास और तैयारी समझने के लिए हर विवरण पढ़ें।",
  },
  "Русский": {
    coreTitle: "Основные предпочтения", coreHelp: "Начните с 1–3 самых важных субъективных предпочтений.", additionalTitle: "Дополнительные предпочтения", exactTitle: "Точные условия", semanticTitle: "Похожие слова, разные роли", semanticHelp: "SPICY — любимый вкус, а максимальная острота — жёсткий предел. VEGETABLE — предпочитаемый основной ингредиент, а веганство — пищевое условие. Температура, текстура и способ приготовления описывают разные стороны: читайте пояснения, чтобы различать горячее и холодное, ощущение во рту и способ готовки.",
  },
};

function languageForLocale(locale: string): SupportedLanguage {
  const normalized = locale.toLowerCase();
  return LANGUAGES.find((language) => {
    const code = LANGUAGE_META[language].code.toLowerCase();
    return normalized === code || normalized.startsWith(`${code}-`) || code.startsWith(`${normalized}-`);
  }) ?? "English";
}

export function getPreferenceGroupCopy(locale: string) {
  const language = languageForLocale(locale);
  const words = vocabulary[language];
  const recommendation = getRecommendationCopy(language);
  return {
    core: { title: words.coreTitle, help: words.coreHelp },
    additional: { title: words.additionalTitle, help: recommendation.selectorDescription },
    exact: {
      title: words.exactTitle,
      help: `${recommendation.dietaryTitle} · ${recommendation.spiceTitle}. ${recommendation.noHiddenRelaxation}`,
    },
    semanticTitle: words.semanticTitle,
    semanticHelp: words.semanticHelp,
  };
}
