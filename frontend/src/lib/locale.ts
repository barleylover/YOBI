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

export function menuName(menu: { name_en: string; name_ko: string }, language: string) {
  if (language === "한국어") return menu.name_ko || menu.name_en;
  return menu.name_en || menu.name_ko;
}

export function countryName(country: string, locale: string) {
  const region = COUNTRIES.find(([name]) => name === country)?.[1];
  if (!region) return country;
  return new Intl.DisplayNames([locale], { type: "region" }).of(region) ?? country;
}
