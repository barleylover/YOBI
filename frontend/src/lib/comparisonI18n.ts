import type { SupportedLanguage } from "./locale";

export interface ComparisonFieldCopy {
  keyDifference: string;
  tasteTexture: string;
  ingredientsForm: string;
  spiceHeaviness: string;
  eatingContext: string;
  bestFor: string;
  needsVerification: string;
  spiceUnverified: string;
}

const packs: Record<SupportedLanguage, ComparisonFieldCopy> = {
  English: { keyDifference: "Key difference", tasteTexture: "Taste & texture", ingredientsForm: "Ingredients & form", spiceHeaviness: "Spice & weight", eatingContext: "Best context", bestFor: "Best for", needsVerification: "Needs verification", spiceUnverified: "Spice not verified" },
  "한국어": { keyDifference: "핵심 차이", tasteTexture: "맛과 식감", ingredientsForm: "재료와 형태", spiceHeaviness: "맵기와 무게감", eatingContext: "잘 맞는 상황", bestFor: "추천 취향", needsVerification: "확인 필요", spiceUnverified: "맵기 확인되지 않음" },
  "日本語": { keyDifference: "主な違い", tasteTexture: "味と食感", ingredientsForm: "材料と形", spiceHeaviness: "辛さと重さ", eatingContext: "向いている場面", bestFor: "おすすめの好み", needsVerification: "確認が必要", spiceUnverified: "辛さは未確認" },
  "中文（简体）": { keyDifference: "主要区别", tasteTexture: "味道与口感", ingredientsForm: "食材与形态", spiceHeaviness: "辣度与厚重感", eatingContext: "适合场景", bestFor: "适合偏好", needsVerification: "需要确认", spiceUnverified: "辣度未核实" },
  "中文（繁體）": { keyDifference: "主要差異", tasteTexture: "味道與口感", ingredientsForm: "食材與形態", spiceHeaviness: "辣度與厚重感", eatingContext: "適合情境", bestFor: "適合偏好", needsVerification: "需要確認", spiceUnverified: "辣度未核實" },
  Español: { keyDifference: "Diferencia clave", tasteTexture: "Sabor y textura", ingredientsForm: "Ingredientes y forma", spiceHeaviness: "Picante y contundencia", eatingContext: "Mejor contexto", bestFor: "Ideal para", needsVerification: "Requiere verificación", spiceUnverified: "Picante no verificado" },
  Français: { keyDifference: "Différence principale", tasteTexture: "Goût et texture", ingredientsForm: "Ingrédients et forme", spiceHeaviness: "Piquant et consistance", eatingContext: "Contexte idéal", bestFor: "Idéal pour", needsVerification: "À vérifier", spiceUnverified: "Piquant non vérifié" },
  Deutsch: { keyDifference: "Wichtigster Unterschied", tasteTexture: "Geschmack und Textur", ingredientsForm: "Zutaten und Form", spiceHeaviness: "Schärfe und Sättigung", eatingContext: "Passender Anlass", bestFor: "Geeignet für", needsVerification: "Prüfung nötig", spiceUnverified: "Schärfe nicht geprüft" },
  Italiano: { keyDifference: "Differenza principale", tasteTexture: "Gusto e consistenza", ingredientsForm: "Ingredienti e forma", spiceHeaviness: "Piccantezza e corposità", eatingContext: "Contesto ideale", bestFor: "Ideale per", needsVerification: "Da verificare", spiceUnverified: "Piccantezza non verificata" },
  Português: { keyDifference: "Diferença principal", tasteTexture: "Sabor e textura", ingredientsForm: "Ingredientes e formato", spiceHeaviness: "Picância e intensidade", eatingContext: "Melhor contexto", bestFor: "Ideal para", needsVerification: "Precisa de verificação", spiceUnverified: "Picância não verificada" },
  "ไทย": { keyDifference: "ความแตกต่างหลัก", tasteTexture: "รสชาติและเนื้อสัมผัส", ingredientsForm: "วัตถุดิบและรูปแบบ", spiceHeaviness: "ความเผ็ดและความหนัก", eatingContext: "สถานการณ์ที่เหมาะ", bestFor: "เหมาะสำหรับ", needsVerification: "ต้องตรวจสอบ", spiceUnverified: "ยังไม่ยืนยันความเผ็ด" },
  "Tiếng Việt": { keyDifference: "Điểm khác biệt chính", tasteTexture: "Hương vị và kết cấu", ingredientsForm: "Nguyên liệu và hình thức", spiceHeaviness: "Độ cay và độ nặng", eatingContext: "Hoàn cảnh phù hợp", bestFor: "Phù hợp với", needsVerification: "Cần xác minh", spiceUnverified: "Chưa xác minh độ cay" },
  "Bahasa Indonesia": { keyDifference: "Perbedaan utama", tasteTexture: "Rasa dan tekstur", ingredientsForm: "Bahan dan bentuk", spiceHeaviness: "Pedas dan bobot", eatingContext: "Konteks terbaik", bestFor: "Cocok untuk", needsVerification: "Perlu diverifikasi", spiceUnverified: "Tingkat pedas belum diverifikasi" },
  "العربية": { keyDifference: "الفرق الأساسي", tasteTexture: "النكهة والقوام", ingredientsForm: "المكونات والشكل", spiceHeaviness: "الحِدّة والثقل", eatingContext: "السياق الأنسب", bestFor: "الأنسب لـ", needsVerification: "يحتاج إلى تحقق", spiceUnverified: "درجة الحِدّة غير متحققة" },
  "हिन्दी": { keyDifference: "मुख्य अंतर", tasteTexture: "स्वाद और बनावट", ingredientsForm: "सामग्री और रूप", spiceHeaviness: "तीखापन और भारीपन", eatingContext: "उपयुक्त अवसर", bestFor: "इनके लिए उपयुक्त", needsVerification: "पुष्टि आवश्यक", spiceUnverified: "तीखापन सत्यापित नहीं" },
  "Русский": { keyDifference: "Главное отличие", tasteTexture: "Вкус и текстура", ingredientsForm: "Ингредиенты и форма", spiceHeaviness: "Острота и сытность", eatingContext: "Подходящая ситуация", bestFor: "Лучше для", needsVerification: "Требует проверки", spiceUnverified: "Острота не проверена" },
};

export function getComparisonFieldCopy(language: SupportedLanguage) {
  return packs[language];
}
