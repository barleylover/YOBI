import type {
  PreferenceCatalog,
  PreferenceCatalogCategory,
  PreferenceCatalogOption,
  PreferenceCategoryCode,
  PreferenceCategoryGroup,
  SpiceReferenceCountry,
  SpiceReferenceGroup,
  SpiceReferenceLevel,
} from "../types";

export interface PreferenceCatalogCache {
  etag: string;
  catalog: PreferenceCatalog;
}

const CATEGORY_CODES = new Set<PreferenceCategoryCode>([
  "cuisine_origins",
  "flavors",
  "main_ingredients",
  "food_forms",
  "temperatures",
  "price_bands",
  "textures",
  "cooking_methods",
]);

const DEFAULT_CATEGORY_GROUP: Record<PreferenceCategoryCode, PreferenceCategoryGroup> = {
  cuisine_origins: "core",
  main_ingredients: "core",
  food_forms: "core",
  flavors: "additional",
  textures: "additional",
  cooking_methods: "additional",
  temperatures: "additional",
  price_bands: "exact",
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textValue(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function normalizeOption(value: unknown): PreferenceCatalogOption | null {
  const item = record(value);
  const code = textValue(item.code ?? item.value_code ?? item.option_code);
  const label = textValue(item.label ?? item.localized_label ?? item.display_name);
  if (!code || !label) return null;
  return { code, label, description: textValue(item.description) || null };
}

function normalizeCategory(value: unknown): PreferenceCatalogCategory | null {
  const item = record(value);
  const code = textValue(item.code ?? item.category_code) as PreferenceCategoryCode;
  const label = textValue(item.label ?? item.localized_label ?? item.display_name);
  const values = Array.isArray(item.options) ? item.options : Array.isArray(item.values) ? item.values : [];
  const options = values.map(normalizeOption).filter((option): option is PreferenceCatalogOption => Boolean(option));
  if (!CATEGORY_CODES.has(code) || !label || !options.length) return null;
  const rawGroup = textValue(item.group ?? item.category_group) as PreferenceCategoryGroup;
  const group = (["core", "additional", "exact"] as const).includes(rawGroup)
    ? rawGroup
    : DEFAULT_CATEGORY_GROUP[code];
  return { code, group, label, description: textValue(item.description) || null, options };
}

function normalizeSpiceLevel(value: unknown): SpiceReferenceLevel | null {
  const item = record(value);
  const numeric = Number(item.level);
  if (![1, 2, 3, 4, 5].includes(numeric)) return null;
  const level = numeric as 1 | 2 | 3 | 4 | 5;
  const example = textValue(item.example ?? item.food_example ?? item.reference_food);
  if (!example) return null;
  return {
    level,
    label: textValue(item.label ?? item.localized_label, String(level)),
    example,
    description: textValue(item.description) || null,
  };
}

function normalizeSpiceGroup(value: unknown): SpiceReferenceGroup | null {
  const item = record(value);
  const country = textValue(item.country ?? item.country_code ?? item.reference_country) as SpiceReferenceCountry;
  if (country !== "KR" && country !== "US") return null;
  const values = Array.isArray(item.levels) ? item.levels : Array.isArray(item.references) ? item.references : [];
  const levels = values
    .map(normalizeSpiceLevel)
    .filter((level): level is SpiceReferenceLevel => Boolean(level))
    .sort((left, right) => left.level - right.level);
  if (levels.length !== 5 || new Set(levels.map((level) => level.level)).size !== 5) return null;
  return { country, label: textValue(item.label ?? item.localized_label, country), levels };
}

function normalizeCapability(value: unknown) {
  const item = record(value);
  if (typeof value === "boolean") return { enabled: value, reason: null };
  if (typeof item.enabled !== "boolean") return undefined;
  return {
    enabled: item.enabled,
    reason: textValue(item.reason ?? item.reason_text ?? item.disabled_reason) || null,
  };
}

function normalizePriceRange(value: unknown) {
  const item = record(value);
  const min = Number(item.min);
  const max = Number(item.max);
  const step = Number(item.step);
  if (!Number.isInteger(min) || !Number.isInteger(max) || !Number.isInteger(step)) return undefined;
  if (min < 0 || max <= min || step !== 1_000) return undefined;
  return { min, max, step };
}

function fallbackRepresentativeDish(countryCode: string, locale: string) {
  const language = locale.toLowerCase().split(/[-_]/, 1)[0];
  if (countryCode === "KR") {
    return language === "ko" ? "신라면" : language === "ja" ? "辛ラーメン" : "Shin Ramyun";
  }
  if (countryCode === "US") {
    return language === "ko" ? "버팔로 윙" : language === "ja" ? "バッファローウィング" : "Buffalo wings";
  }
  return language === "ko"
    ? "현지의 대표적인 중간 매운 음식"
    : language === "ja"
      ? "現地の代表的な中辛料理"
      : "a familiar medium-spicy local dish";
}

function normalizeCountrySpiceProfiles(value: unknown, locale: string) {
  if (!Array.isArray(value)) return undefined;
  const profiles = value.flatMap((entry) => {
    const item = record(entry);
    const countryCode = textValue(item.country_code).toUpperCase();
    const spiceBaseline = Number(item.spice_baseline);
    if (!/^[A-Z]{2}$/.test(countryCode) || ![1, 2, 3, 4, 5].includes(spiceBaseline)) {
      return [];
    }
    return [{
      country_code: countryCode as SpiceReferenceCountry,
      spice_baseline: spiceBaseline as 1 | 2 | 3 | 4 | 5,
      representative_dish: textValue(
        item.representative_dish,
        fallbackRepresentativeDish(countryCode, locale),
      ),
    }];
  });
  return profiles.length ? profiles : undefined;
}

export function normalizePreferenceCatalog(value: unknown, locale: string): PreferenceCatalog {
  const payload = record(value);
  const categoryValues = Array.isArray(payload.categories)
    ? payload.categories
    : Object.entries(record(payload.categories)).map(([categoryCode, category]) => ({
      ...record(category),
      category_code: categoryCode,
    }));
  const categories = categoryValues
    .map(normalizeCategory)
    .filter((category): category is PreferenceCatalogCategory => Boolean(category));
  const rawSpice = Array.isArray(payload.spice_references)
    ? payload.spice_references
    : Array.isArray(payload.spice_reference_catalog)
      ? payload.spice_reference_catalog
      : [];
  const spiceReferences = rawSpice
    .map(normalizeSpiceGroup)
    .filter((group): group is SpiceReferenceGroup => Boolean(group));
  if (
    !categories.length
    || spiceReferences.length !== 2
    || new Set(spiceReferences.map((group) => group.country)).size !== 2
  ) throw new Error("PREFERENCE_CATALOG_INVALID");
  const rawCapabilities = record(payload.capabilities ?? payload.control_capabilities);
  const halalCapability = normalizeCapability(rawCapabilities.halal_certified_only ?? rawCapabilities.halal);
  const veganCapability = normalizeCapability(rawCapabilities.vegan);
  const spiceCapability = normalizeCapability(rawCapabilities.max_spice_level ?? rawCapabilities.spice);
  const priceRange = normalizePriceRange(payload.price_range_krw);
  const countrySpiceProfiles = normalizeCountrySpiceProfiles(payload.country_spice_profiles, locale);
  return {
    schema_version: payload.schema_version === "3" ? "3" : "2",
    catalog_version: textValue(
      payload.catalog_version ?? payload.preference_catalog_version ?? payload.version,
      "unknown",
    ),
    knowledge_release_id: textValue(payload.knowledge_release_id, "unknown"),
    locale: textValue(payload.locale, locale),
    categories,
    spice_references: spiceReferences,
    price_range_krw: priceRange,
    country_spice_profiles: countrySpiceProfiles,
    synthetic_enrichment_release_id: textValue(payload.synthetic_enrichment_release_id) || null,
    capabilities: halalCapability || veganCapability || spiceCapability ? {
      halal_certified_only: halalCapability,
      vegan: veganCapability,
      max_spice_level: spiceCapability,
    } : undefined,
  };
}

function cacheKey(locale: string) {
  return `yobi-preference-catalog-${locale}`;
}

export function readPreferenceCatalogCache(locale: string): PreferenceCatalogCache | null {
  try {
    const cached = JSON.parse(sessionStorage.getItem(cacheKey(locale)) ?? "null") as PreferenceCatalogCache | null;
    if (!cached?.etag || !cached.catalog) return null;
    return { ...cached, catalog: normalizePreferenceCatalog(cached.catalog, locale) };
  } catch {
    return null;
  }
}

export function writePreferenceCatalogCache(locale: string, cache: PreferenceCatalogCache) {
  sessionStorage.setItem(cacheKey(locale), JSON.stringify(cache));
}
