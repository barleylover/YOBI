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
  return {
    schema_version: "2",
    catalog_version: textValue(
      payload.catalog_version ?? payload.preference_catalog_version ?? payload.version,
      "unknown",
    ),
    knowledge_release_id: textValue(payload.knowledge_release_id, "unknown"),
    locale: textValue(payload.locale, locale),
    categories,
    spice_references: spiceReferences,
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
