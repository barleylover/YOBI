import { Check, RotateCcw, Sparkles } from "lucide-react";
import { useMemo } from "react";
import type {
  PreferenceCatalog,
  PreferenceCatalogCategory,
  PreferenceCategoryCode,
  RecommendationCriteriaV2,
  RecommendationPreviewV2,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
import { getPreferenceGroupCopy } from "../lib/preferenceGroupI18n";
import { SpiceReferenceScale } from "./SpiceReferenceScale";

const CATEGORY_KEYS: PreferenceCategoryCode[] = [
  "cuisine_origins",
  "flavors",
  "main_ingredients",
  "food_forms",
  "temperatures",
  "price_bands",
  "textures",
  "cooking_methods",
];

interface Props {
  catalog: PreferenceCatalog;
  criteria: RecommendationCriteriaV2;
  copy: RecommendationCopy;
  busy?: boolean;
  previewLoading?: boolean;
  preview?: RecommendationPreviewV2 | null;
  previewMessage?: string;
  canSubmitUnchanged?: boolean;
  conversationMode?: boolean;
  conflictMessage: string;
  onChange: (criteria: RecommendationCriteriaV2) => void;
  onValidateAdd?: (criteria: RecommendationCriteriaV2) => Promise<boolean>;
  onComplete: () => void;
}

function countCriteria(criteria: RecommendationCriteriaV2) {
  return CATEGORY_KEYS.reduce((total, key) => total + criteria[key].length, 0)
    + Number(criteria.dietary_filters.halal_certified_only)
    + Number(criteria.dietary_filters.vegan);
}

export function PreferenceSelector({
  catalog,
  criteria,
  copy,
  busy = false,
  previewLoading = false,
  preview = null,
  previewMessage = "",
  canSubmitUnchanged = false,
  conversationMode = false,
  conflictMessage,
  onChange,
  onValidateAdd,
  onComplete,
}: Props) {
  function capabilityReason(
    capability: { enabled: boolean; reason?: string | null } | undefined,
    fallback: string,
    koreanUnavailable: string,
  ) {
    if (capability?.enabled !== false) return fallback;
    const normalizedLocale = catalog.locale.toLowerCase();
    if (normalizedLocale === "ko" || normalizedLocale.startsWith("ko-")) return koreanUnavailable;
    if (normalizedLocale === "en" || normalizedLocale.startsWith("en-")) return capability.reason || fallback;
    return fallback;
  }

  const selectedCount = countCriteria(criteria);
  const groupCopy = getPreferenceGroupCopy(catalog.locale);
  const groupedCategories = useMemo(() => ({
    core: catalog.categories.filter((category) => category.group === "core"),
    additional: catalog.categories.filter((category) => category.group === "additional"),
    exact: catalog.categories.filter((category) => category.group === "exact"),
  }), [catalog.categories]);
  const ingredientCodes = new Set(criteria.main_ingredients);
  const hasConflict = (
    criteria.dietary_filters.halal_certified_only && ingredientCodes.has("PORK")
  ) || (
    criteria.dietary_filters.vegan
    && ["BEEF", "PORK", "CHICKEN", "FISH_SEAFOOD"].some((code) => ingredientCodes.has(code))
  );
  const optionLabels = useMemo(() => new Map(
    catalog.categories.flatMap((category) => category.options.map((option) => [option.code, option.label] as const)),
  ), [catalog.categories]);
  const selectedLabels = CATEGORY_KEYS.flatMap((key) => criteria[key].map((code) => optionLabels.get(code) ?? code));
  if (criteria.dietary_filters.halal_certified_only) selectedLabels.push(copy.halal);
  if (criteria.dietary_filters.vegan) selectedLabels.push(copy.vegan);

  async function toggle(category: PreferenceCategoryCode, code: string) {
    const selected = criteria[category];
    const removing = selected.includes(code);
    const next = {
      ...criteria,
      [category]: removing
        ? selected.filter((value) => value !== code)
        : [...selected, code],
    };
    if (!removing && onValidateAdd && !await onValidateAdd(next)) return;
    onChange(next);
  }

  async function changeDietary(key: "halal_certified_only" | "vegan", checked: boolean) {
    const next = {
      ...criteria,
      dietary_filters: { ...criteria.dietary_filters, [key]: checked },
    };
    if (checked && onValidateAdd && !await onValidateAdd(next)) return;
    onChange(next);
  }

  function clearCategory(category: PreferenceCategoryCode) {
    onChange({ ...criteria, [category]: [] });
  }

  function clearAll() {
    onChange({
      ...criteria,
      ...Object.fromEntries(CATEGORY_KEYS.map((key) => [key, []])),
      dietary_filters: { halal_certified_only: false, vegan: false },
    } as RecommendationCriteriaV2);
  }

  const completeEnabled = (selectedCount > 0 || canSubmitUnchanged) && !hasConflict;

  function categoryPanel(category: PreferenceCatalogCategory, open = false) {
    return (
      <details className="preference-category" data-category={category.code} open={open} key={category.code}>
        <summary><span><strong>{category.label}</strong>{category.description && <small>{category.description}</small>}</span><em>{criteria[category.code].length}</em></summary>
        <div className="preference-category-actions">
          <span>{copy.multiSelect}</span>
          {criteria[category.code].length > 0 && <button type="button" onClick={() => clearCategory(category.code)}>{copy.clearCategory}</button>}
        </div>
        <div className="preference-chip-grid">
          {category.options.map((option) => {
            const selected = criteria[category.code].includes(option.code);
            return (
              <button
                type="button"
                key={option.code}
                data-option-code={option.code}
                className={selected ? "preference-chip selected" : "preference-chip"}
                aria-pressed={selected}
                disabled={busy}
                onClick={() => void toggle(category.code, option.code)}
              >
                {selected && <Check size={14} />}
                <span><strong>{option.label}</strong>{option.description && <small>{option.description}</small>}</span>
              </button>
            );
          })}
        </div>
      </details>
    );
  }

  return (
    <section className={conversationMode ? "preference-selector conversation-quick-replies" : "preference-selector"} aria-labelledby="preference-selector-title">
      <header className={conversationMode ? "preference-selector-heading visually-hidden" : "preference-selector-heading"}>
        <p className="eyebrow">{copy.selectorEyebrow}</p>
        <h1 id="preference-selector-title">{copy.selectorTitle}</h1>
        <p>{copy.selectorDescription}</p>
        <span><Check size={14} /> {copy.multiSelect}</span>
      </header>

      <div className="preference-preview" aria-live="polite">
        {previewLoading && <span>{copy.loadingChoices}</span>}
        {!previewLoading && previewMessage && <span className={preview?.eligible_menu_count === 0 ? "warning" : ""}>{previewMessage}</span>}
      </div>

      {selectedLabels.length > 0 && (
        <section className="preference-summary" aria-label={copy.selectedSummary}>
          <div><strong>{copy.selectedSummary}</strong><span>{copy.selectedCount(selectedCount)}</span></div>
          <div className="preference-summary-tags">{selectedLabels.map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}</div>
        </section>
      )}

      <section className="preference-group" data-preference-group="core" aria-labelledby="preference-group-core">
        <header><span>01</span><div><h2 id="preference-group-core">{groupCopy.core.title}</h2><p>{groupCopy.core.help}</p></div></header>
        <div className="preference-category-list">
          {groupedCategories.core.map((category, index) => categoryPanel(category, index < 2))}
        </div>
      </section>

      <section className="preference-group" data-preference-group="additional" aria-labelledby="preference-group-additional">
        <header><span>02</span><div><h2 id="preference-group-additional">{groupCopy.additional.title}</h2><p>{groupCopy.additional.help}</p></div></header>
        <div className="preference-category-list">
          {groupedCategories.additional.map((category) => categoryPanel(category))}
        </div>
      </section>

      <section className="preference-group preference-group-exact" data-preference-group="exact" aria-labelledby="preference-group-exact">
        <header><span>03</span><div><h2 id="preference-group-exact">{groupCopy.exact.title}</h2><p>{groupCopy.exact.help}</p></div></header>
        <aside className="preference-meaning-guide" aria-labelledby="preference-meaning-title">
          <strong id="preference-meaning-title">{groupCopy.semanticTitle}</strong>
          <p>{groupCopy.semanticHelp}</p>
        </aside>
        <div className="preference-category-list">
          {groupedCategories.exact.map((category) => categoryPanel(category, true))}
        </div>

        <fieldset className="preference-dietary">
          <legend>{copy.dietaryTitle}</legend>
          <label className={criteria.dietary_filters.halal_certified_only ? "dietary-toggle selected" : "dietary-toggle"}>
            <input
              type="checkbox"
              checked={criteria.dietary_filters.halal_certified_only}
              disabled={busy || catalog.capabilities?.halal_certified_only?.enabled === false}
              onChange={(event) => void changeDietary("halal_certified_only", event.target.checked)}
            />
            <span><strong>{copy.halal}</strong><small>{capabilityReason(
              catalog.capabilities?.halal_certified_only,
              copy.halalHelp,
              "검증 가능한 공식 인증 정보가 없어 현재 사용할 수 없습니다.",
            )}</small></span>
          </label>
          <label className={criteria.dietary_filters.vegan ? "dietary-toggle selected" : "dietary-toggle"}>
            <input
              type="checkbox"
              checked={criteria.dietary_filters.vegan}
              disabled={busy || catalog.capabilities?.vegan?.enabled === false}
              onChange={(event) => void changeDietary("vegan", event.target.checked)}
            />
            <span><strong>{copy.vegan}</strong><small>{capabilityReason(
              catalog.capabilities?.vegan,
              copy.veganHelp,
              "검토된 메뉴별 재료 정보가 없어 현재 사용할 수 없습니다.",
            )}</small></span>
          </label>
        </fieldset>

        <SpiceReferenceScale
          value={criteria.max_spice_level}
          country={criteria.spice_reference_country}
          references={catalog.spice_references}
          copy={copy}
          disabled={busy || catalog.capabilities?.max_spice_level?.enabled === false}
          onChange={(max_spice_level) => {
            onChange({ ...criteria, max_spice_level });
          }}
          onCountryChange={(spice_reference_country) => {
            onChange({ ...criteria, spice_reference_country });
          }}
        />
        {catalog.capabilities?.max_spice_level?.enabled === false && (
          <p className="preference-capability-note" role="status">{capabilityReason(
            catalog.capabilities.max_spice_level,
            copy.spiceHelp,
            "검토된 메뉴별 맵기 정보가 없어 현재 사용할 수 없습니다.",
          )}</p>
        )}
      </section>

      {hasConflict && <p className="preference-conflict" role="alert">{conflictMessage}</p>}

      <footer className="preference-submit-bar">
        <div><strong>{copy.selectedCount(selectedCount)}</strong><small>{copy.noHiddenRelaxation}</small></div>
        <button type="button" className="text-button" onClick={clearAll} disabled={busy || selectedCount === 0}><RotateCcw size={16} /> {copy.clearAll}</button>
        <button type="button" className="primary-button" onClick={onComplete} disabled={busy || !completeEnabled}><Sparkles size={18} /> {copy.complete}</button>
      </footer>
    </section>
  );
}
