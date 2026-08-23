export const LANGUAGES = [
  "English", "한국어", "日本語", "中文（简体）", "中文（繁體）", "Español", "Français",
  "Deutsch", "Italiano", "Português", "ไทย", "Tiếng Việt", "Bahasa Indonesia",
  "العربية", "हिन्दी", "Русский",
] as const;

export type SupportedLanguage = (typeof LANGUAGES)[number];

export const LANGUAGE_META: Record<SupportedLanguage, { code: string; direction: "ltr" | "rtl" }> = {
  English: { code: "en", direction: "ltr" },
  "한국어": { code: "ko", direction: "ltr" },
  "日本語": { code: "ja", direction: "ltr" },
  "中文（简体）": { code: "zh-CN", direction: "ltr" },
  "中文（繁體）": { code: "zh-TW", direction: "ltr" },
  Español: { code: "es", direction: "ltr" },
  Français: { code: "fr", direction: "ltr" },
  Deutsch: { code: "de", direction: "ltr" },
  Italiano: { code: "it", direction: "ltr" },
  Português: { code: "pt", direction: "ltr" },
  "ไทย": { code: "th", direction: "ltr" },
  "Tiếng Việt": { code: "vi", direction: "ltr" },
  "Bahasa Indonesia": { code: "id", direction: "ltr" },
  "العربية": { code: "ar", direction: "rtl" },
  "हिन्दी": { code: "hi", direction: "ltr" },
  "Русский": { code: "ru", direction: "ltr" },
};

export const COUNTRIES = [
  ["United States", "US"], ["United Kingdom", "GB"], ["Canada", "CA"], ["Australia", "AU"],
  ["New Zealand", "NZ"], ["Ireland", "IE"], ["South Korea", "KR"], ["Japan", "JP"],
  ["China", "CN"], ["Taiwan", "TW"], ["Hong Kong", "HK"], ["Singapore", "SG"],
  ["Spain", "ES"], ["Mexico", "MX"], ["Argentina", "AR"], ["Colombia", "CO"],
  ["France", "FR"], ["Belgium", "BE"], ["Germany", "DE"], ["Austria", "AT"],
  ["Switzerland", "CH"], ["Italy", "IT"], ["Portugal", "PT"], ["Brazil", "BR"],
  ["Thailand", "TH"], ["Vietnam", "VN"], ["Indonesia", "ID"], ["Malaysia", "MY"],
  ["Saudi Arabia", "SA"], ["United Arab Emirates", "AE"], ["Egypt", "EG"], ["India", "IN"],
  ["Russia", "RU"], ["Philippines", "PH"], ["Türkiye", "TR"], ["Netherlands", "NL"],
  ["Other", "ZZ"],
] as const;

export const LANGUAGE_COUNTRIES: Record<SupportedLanguage, string[]> = {
  English: ["US", "GB", "CA", "AU", "NZ", "IE", "SG"], "한국어": ["KR"], "日本語": ["JP"],
  "中文（简体）": ["CN", "SG"], "中文（繁體）": ["TW", "HK"], Español: ["ES", "MX", "AR", "CO"],
  Français: ["FR", "BE", "CA", "CH"], Deutsch: ["DE", "AT", "CH"], Italiano: ["IT", "CH"],
  Português: ["BR", "PT"], "ไทย": ["TH"], "Tiếng Việt": ["VN"], "Bahasa Indonesia": ["ID"],
  "العربية": ["SA", "AE", "EG"], "हिन्दी": ["IN"], "Русский": ["RU"],
};

export function asSupportedLanguage(value: string): SupportedLanguage {
  return (LANGUAGES as readonly string[]).includes(value) ? value as SupportedLanguage : "English";
}

export type EffectiveLanguage = "English" | "한국어" | "日本語";

export function asEffectiveLanguage(value: string): EffectiveLanguage {
  const selected = asSupportedLanguage(value);
  return selected === "한국어" || selected === "日本語" ? selected : "English";
}

export function effectiveLanguageMeta(value: string) {
  return LANGUAGE_META[asEffectiveLanguage(value)];
}

export function sortedCountries(language: SupportedLanguage) {
  const priority = LANGUAGE_COUNTRIES[language];
  return [...COUNTRIES].sort((left, right) => {
    const leftIndex = priority.indexOf(left[1]);
    const rightIndex = priority.indexOf(right[1]);
    if (leftIndex !== -1 || rightIndex !== -1) {
      if (leftIndex === -1) return 1;
      if (rightIndex === -1) return -1;
      return leftIndex - rightIndex;
    }
    return left[0].localeCompare(right[0]);
  });
}

export function menuName(
  menu: { name_en: string; name_ko: string; localized_title?: string | null },
  language: string,
) {
  if (menu.localized_title) return menu.localized_title;
  if (asEffectiveLanguage(language) === "한국어") return menu.name_ko || menu.name_en;
  return menu.name_en || menu.name_ko;
}

const DEMO_ROAD_ADDRESSES: Record<string, string> = {
  "서울특별시 중구 을지로 21": "21 Eulji-ro, Jung-gu, Seoul",
  "서울특별시 중구 데모로 21": "21 Demo-ro, Jung-gu, Seoul",
};

const DEMO_ROAD_ADDRESSES_JA: Record<string, string> = {
  "서울특별시 중구 을지로 21": "ソウル特別市 中区 乙支路21",
  "서울특별시 중구 데모로 21": "ソウル特別市 中区 デモ路21",
  "21 Eulji-ro, Jung-gu, Seoul": "ソウル特別市 中区 乙支路21",
  "21 Demo-ro, Jung-gu, Seoul": "ソウル特別市 中区 デモ路21",
};

const DEMO_MERCHANT_NAMES: Record<string, string> = {
  "하루비어-동국대점": "Haru Beer - Dongguk Univ. Branch",
  "피자마루-약수점": "Pizza Maru - Yaksu Branch",
  "파스타입니다-종로점": "Pasta Imnida - Jongno Branch",
  "미친피자-본점": "Crazy Pizza - Main Branch",
  "국밥생각-충정로점": "Gukbap Saenggak - Chungjeongno Branch",
  "미도인덮밥,스테이크-대학로점": "Midoin Deopbap & Steak - Daehak-ro Branch",
  "남경중화요리-남대문시장점": "Namgyeong Chinese Restaurant - Namdaemun Market",
  "비빔밥입니다-공덕점": "Bibimbap-imnida - Gongdeok Branch",
  "맛단(맛있는다이어트식단)-종로점": "Matdan - Jongno Branch",
  "본도시락-서울시청점": "Bon Dosirak - Seoul City Hall Branch",
  "김밥천국-명동본점": "Gimbap Cheonguk - Myeongdong Main Branch",
};

const DEMO_MERCHANT_NAMES_JA: Record<string, string> = {
  "하루비어-동국대점": "ハルビア・東国大学店",
  "피자마루-약수점": "ピザマル・薬水店",
  "파스타입니다-종로점": "パスタイムニダ・鍾路店",
  "미친피자-본점": "ミチンピザ・本店",
  "국밥생각-충정로점": "クッパセンガク・忠正路店",
  "미도인덮밥,스테이크-대학로점": "ミドイン丼＆ステーキ・大学路店",
  "남경중화요리-남대문시장점": "南京中華料理・南大門市場店",
  "비빔밥입니다-공덕점": "ビビンバイムニダ・孔徳店",
  "맛단(맛있는다이어트식단)-종로점": "マッタン（おいしいダイエット食）・鍾路店",
  "본도시락-서울시청점": "ボン弁当・ソウル市庁店",
  "김밥천국-명동본점": "キンパ天国・明洞本店",
};

const DEMO_MERCHANT_TERMS_JA: Array<[RegExp, string]> = [
  [/Boneless Korean fried chicken/gi, "骨なし韓国フライドチキン"],
  [/Spicy stir-fried pork/gi, "辛口豚炒め"],
  [/Bean sprout gukbap/gi, "もやしクッパ"],
  [/Cheese pork cutlet/gi, "チーズとんかつ"],
  [/Grilled mackerel/gi, "サバ焼き"],
  [/Beef jjajangmyeon/gi, "牛肉チャジャン麺"],
  [/Jjajang fried rice/gi, "チャジャン炒飯"],
  [/Chocolate croffle/gi, "チョコレートクロッフル"],
  [/Chicken Kalguksu/gi, "鶏カルグクス"],
  [/Bibim naengmyeon/gi, "ビビン冷麺"],
  [/Bibim kalguksu/gi, "ビビンカルグクス"],
  [/Bulgogi gimbap/gi, "プルコギキンパ"],
  [/Bulgogi pizza/gi, "プルコギピザ"],
  [/Kimchi mandu/gi, "キムチマンドゥ"],
  [/Kimchi stew/gi, "キムチチゲ"],
  [/Korean baekban/gi, "韓国定食"],
  [/Spicy tangsuyuk/gi, "辛口酢豚"],
  [/Cheese tteokbokki/gi, "チーズトッポッキ"],
  [/Bibim guksu/gi, "ビビングクス"],
  [/Eomuk udon/gi, "オムクうどん"],
  [/Soft Tofu/gi, "スンドゥブ"],
  [/Hong Kong Banjeom/gi, "香港飯店"],
  [/No More Pizza/gi, "ノーモアピザ"],
  [/Yeopgi Tteokbokki/gi, "ヨプギトッポッキ"],
  [/Myeongdong/gi, "明洞"],
  [/Hongdae/gi, "弘大"],
  [/Gangnam/gi, "江南"],
  [/Euljiro/gi, "乙支路"],
  [/Cheonggye/gi, "清渓"],
  [/Jongno/gi, "鍾路"],
  [/Namsan/gi, "南山"],
  [/Seoul/gi, "ソウル"],
  [/Hanok/gi, "韓屋"],
  [/Eulji/gi, "乙支"],
  [/Rose/gi, "ロゼ"],
  [/Tteokbokki/gi, "トッポッキ"],
  [/Tteok/gi, "トック"],
  [/Kalguksu/gi, "カルグクス"],
  [/Bibimbap/gi, "ビビンバ"],
  [/Gimbap/gi, "キンパ"],
  [/Crisp Chicken/gi, "サクサクチキン"],
  [/Samgyetang/gi, "サムゲタン"],
  [/Jjajang/gi, "チャジャン"],
  [/Bulgogi/gi, "プルコギ"],
  [/Hotteok/gi, "ホットク"],
  [/Japchae/gi, "チャプチェ"],
  [/Jjamppong/gi, "チャンポン"],
  [/Gukbap/gi, "クッパ"],
  [/Seolleongtang/gi, "ソルロンタン"],
  [/Eomuk/gi, "オムク"],
  [/Bingsu/gi, "ピンス"],
  [/Dosirak/gi, "お弁当"],
  [/Sundubu jjigae/gi, "スンドゥブチゲ"],
  [/Garden/gi, "ガーデン"],
  [/Workshop/gi, "工房"],
  [/Kitchen/gi, "キッチン"],
  [/Dining/gi, "ダイニング"],
  [/Table/gi, "食堂"],
  [/House/gi, "店"],
  [/Room/gi, "店"],
];

const HANGUL_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"];
const HANGUL_VOWELS = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"];
const HANGUL_FINALS = ["", "k", "k", "ks", "n", "n", "nh", "t", "l", "lk", "lm", "lb", "ls", "lt", "lp", "lh", "m", "p", "ps", "t", "t", "ng", "t", "t", "k", "t", "p", "h"];

function romanizeHangul(value: string) {
  const romanized = Array.from(value, (character) => {
    const code = character.charCodeAt(0) - 0xac00;
    if (code < 0 || code > 11171) return character;
    const initial = Math.floor(code / 588);
    const vowel = Math.floor((code % 588) / 28);
    const final = code % 28;
    return `${HANGUL_INITIALS[initial]}${HANGUL_VOWELS[vowel]}${HANGUL_FINALS[final]}`;
  }).join("");
  return romanized.replace(/(^|[\s·-])([a-z])/g, (_, prefix: string, letter: string) => `${prefix}${letter.toUpperCase()}`);
}

export function merchantName(name: string, language: string) {
  const effectiveLanguage = asEffectiveLanguage(language);
  if (effectiveLanguage === "한국어") return name;
  if (effectiveLanguage === "日本語") {
    const koreanName = DEMO_MERCHANT_NAMES[name]
      ? name
      : Object.entries(DEMO_MERCHANT_NAMES).find(([, englishName]) => englishName === name)?.[0];
    if (koreanName && DEMO_MERCHANT_NAMES_JA[koreanName]) {
      return DEMO_MERCHANT_NAMES_JA[koreanName];
    }
    if (/[가-힣]/.test(name)) return `韓国料理店「${name}」`;
    return DEMO_MERCHANT_TERMS_JA.reduce(
      (localized, [pattern, replacement]) => localized.replace(pattern, replacement),
      name,
    ).replace(/\s+/g, " ").trim();
  }
  if (!/[가-힣]/.test(name)) return name;
  const knownName = DEMO_MERCHANT_NAMES[name];
  if (knownName) return knownName;
  return romanizeHangul(name)
    .replace(/-/g, " - ")
    .replace(/\s-\sBonjeom$/i, " - Main Branch")
    .replace(/\s-\s([^\s]+)jeom$/i, " - $1 Branch");
}

export function demoRoadAddress(address: string, language: string) {
  const effectiveLanguage = asEffectiveLanguage(language);
  if (effectiveLanguage === "한국어") return address;
  if (effectiveLanguage === "日本語") return DEMO_ROAD_ADDRESSES_JA[address] ?? address;
  return DEMO_ROAD_ADDRESSES[address] ?? address;
}

export function demoHotelName(name: string, language: string) {
  if (asEffectiveLanguage(language) !== "日本語") return name;
  if (["YOBI Myeongdong Hotel", "YOBI Hotel Myeongdong", "요비호텔"].includes(name)) {
    return "YOBI明洞ホテル";
  }
  const demoHotel = /^YOBI Demo Hotel (\d+)$/i.exec(name);
  return demoHotel ? `YOBIデモホテル ${demoHotel[1]}` : name;
}

export function localizeDemoAddressSummary(summary: string, language: string) {
  if (!summary) return summary;
  const [hotel, ...addressParts] = summary.split(" · ");
  const address = addressParts.join(" · ");
  const localizedHotel = demoHotelName(hotel, language);
  return address ? `${localizedHotel} · ${demoRoadAddress(address, language)}` : localizedHotel;
}

export function localizedVeganWarning(
  status: "LIKELY_FIT" | "POSSIBLE_WITH_CHECKS" | "CONFLICT" | "UNKNOWN" | null | undefined,
  language: string,
  originalWarning?: string | null,
) {
  const effectiveLanguage = asEffectiveLanguage(language);
  if (effectiveLanguage === "English") return originalWarning ?? "";
  if (effectiveLanguage === "日本語") {
    if (status === "CONFLICT") return "動物性の原材料が確認されているため、ヴィーガン条件には合いません。";
    if (status === "POSSIBLE_WITH_CHECKS") return "ヴィーガン対応か、注文前に原材料とオプションを店舗へ確認してください。";
    if (status === "LIKELY_FIT") return "ヴィーガン対応候補です。選んだオプションを注文前に確認してください。";
    return "ヴィーガン対応は未確認です。原材料とオプションをご確認ください。";
  }
  if (status === "CONFLICT") return "동물성 재료가 확인되어 비건 조건과 맞지 않습니다.";
  if (status === "POSSIBLE_WITH_CHECKS") return "주문 전 가게에 재료와 옵션의 비건 여부를 확인해 주세요.";
  if (status === "LIKELY_FIT") return "비건 가능 메뉴입니다. 주문 전 선택한 옵션을 확인해 주세요.";
  return "비건 여부가 확인되지 않았습니다. 재료와 옵션을 확인해 주세요.";
}

export function formatMinuteRange(minimum: number, maximum: number, locale: string) {
  const formatter = new Intl.NumberFormat(locale, {
    style: "unit",
    unit: "minute",
    unitDisplay: "short",
  });
  return `${formatter.format(minimum)}–${formatter.format(maximum)}`;
}

export function countryCode(country: string) {
  return COUNTRIES.find(([name]) => name === country)?.[1] ?? "ZZ";
}

export function countryName(country: string, locale: string) {
  const region = COUNTRIES.find(([name]) => name === country)?.[1];
  if (!region) return country;
  if (region === "ZZ") return country;
  return new Intl.DisplayNames([locale], { type: "region" }).of(region) ?? country;
}

export function countryFlag(countryCodeValue: string) {
  if (!/^[A-Z]{2}$/.test(countryCodeValue) || countryCodeValue === "ZZ") return "🌐";
  return String.fromCodePoint(...Array.from(countryCodeValue, (letter) => 127397 + letter.charCodeAt(0)));
}

const ADVENTUROUS_DISH_PATTERN = /곱창|대창|막창|내장|홍어|산낙지|번데기|순대|gopchang|daechang|makchang|intestine|tripe|hongeo|raw octopus|silkworm|blood sausage/i;

export function isAdventurousDish(...values: Array<string | null | undefined>) {
  return ADVENTUROUS_DISH_PATTERN.test(values.filter(Boolean).join(" "));
}

export function travelerOptionLabel(value: string, language: string) {
  if (language !== "English") return value;
  const normalized = value.trim().toLowerCase();
  if (["gopbaegi add-on", "gopbaegi addon", "add gopbaegi"].includes(normalized)) {
    return normalized.startsWith("add ")
      ? "Extra-large portion (gopbaegi)"
      : "Portion size";
  }
  if (["no gopbaegi", "without gopbaegi"].includes(normalized)) return "Regular portion";
  if (normalized === "nostalgic sausage jeon") return "Nostalgic sausage pancake (jeon)";
  return value;
}
