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

const DEMO_MERCHANT_NAMES: Record<string, string> = {
  "하루비어-동국대점": "Haru Beer - Dongguk Univ. Branch",
  "피자마루-약수점": "Pizza Maru - Yaksu Branch",
  "파스타입니다-종로점": "Pasta Imnida - Jongno Branch",
  "미친피자-본점": "Crazy Pizza - Main Branch",
  "국밥생각-충정로점": "Gukbap Saenggak - Chungjeongno Branch",
};

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
  if (asEffectiveLanguage(language) === "한국어" || !/[가-힣]/.test(name)) return name;
  const knownName = DEMO_MERCHANT_NAMES[name];
  if (knownName) return knownName;
  return romanizeHangul(name)
    .replace(/-/g, " - ")
    .replace(/\s-\sBonjeom$/i, " - Main Branch")
    .replace(/\s-\s([^\s]+)jeom$/i, " - $1 Branch");
}

export function demoRoadAddress(address: string, language: string) {
  if (asEffectiveLanguage(language) === "한국어") return address;
  return DEMO_ROAD_ADDRESSES[address] ?? address;
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
  return COUNTRIES.find(([name]) => name === country)?.[1] ?? "US";
}

export function countryName(country: string, locale: string) {
  const region = COUNTRIES.find(([name]) => name === country)?.[1];
  if (!region) return country;
  return new Intl.DisplayNames([locale], { type: "region" }).of(region) ?? country;
}
