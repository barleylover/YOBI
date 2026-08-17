import { Check, ChevronLeft, ChevronRight } from "lucide-react";
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
  onBack?: () => void;
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
  onBack,
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
  const primaryCategories = useMemo(() => catalog.categories.filter((category) => (
    category.code === "cuisine_origins" || category.code === "main_ingredients"
  )), [catalog.categories]);
  const moreCategories = useMemo(() => catalog.categories.filter((category) => (
    category.code !== "cuisine_origins" && category.code !== "main_ingredients"
  )), [catalog.categories]);
  const exactCategories = moreCategories.filter((category) => category.group === "exact");
  const additionalCategories = moreCategories.filter((category) => category.group !== "exact");
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
  const primarySelectedCount = primaryCategories.reduce((total, category) => total + criteria[category.code].length, 0);
  const moreSelectedCount = Math.max(0, selectedCount - primarySelectedCount);

  function optionGrid(category: PreferenceCatalogCategory) {
    return (
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
    );
  }

  function inlineCategory(category: PreferenceCatalogCategory) {
    return (
      <section className="preference-category-inline" data-category={category.code} key={category.code}>
        <header>
          <h2>{category.label}</h2>
          <div>
            {criteria[category.code].length > 0 && <strong>{copy.selectedCount(criteria[category.code].length)}</strong>}
            {criteria[category.code].length > 0 && <button type="button" onClick={() => clearCategory(category.code)}>{copy.clearCategory}</button>}
            {criteria[category.code].length === 0 && <span>{copy.multiSelect}</span>}
          </div>
        </header>
        {optionGrid(category)}
      </section>
    );
  }

  function categoryPanel(category: PreferenceCatalogCategory, open = false) {
    return (
      <details className="preference-category" data-category={category.code} open={open} key={category.code}>
        <summary><span><strong>{category.label}</strong>{category.description && <small>{category.description}</small>}</span><em>{criteria[category.code].length}</em></summary>
        <div className="preference-category-actions">
          <span>{copy.multiSelect}</span>
          {criteria[category.code].length > 0 && <button type="button" onClick={() => clearCategory(category.code)}>{copy.clearCategory}</button>}
        </div>
        {optionGrid(category)}
      </details>
    );
  }

  return (
    <section className={conversationMode ? "preference-selector conversation-quick-replies figma-preference-selector" : "preference-selector"} aria-labelledby="preference-selector-title">
      <header className="preference-mobile-header">
        <div className="preference-mobile-nav">
          <button type="button" aria-label={copy.editProfile} onClick={onBack} disabled={!onBack}><ChevronLeft size={20} /></button>
          <strong>{copy.selectorEyebrow}</strong>
          <button type="button" className="preference-clear-all" onClick={clearAll} disabled={busy || selectedCount === 0}>{copy.clearAll}</button>
        </div>
        <div className="mobile-step-progress" aria-hidden="true"><span className="active" /><span className="active" /><span /></div>
      </header>

      <header className="preference-selector-heading">
        <h1 id="preference-selector-title">{copy.selectorTitle}</h1>
        <p>{copy.selectorDescription}</p>
      </header>

      {(selectedLabels.length > 0 || conversationMode) && (
        <section className="preference-summary" aria-label={copy.selectedSummary}>
          <div><strong>{copy.selectedSummary}</strong><span>{copy.selectedCount(selectedCount)}</span></div>
          <div className="preference-summary-tags">{selectedLabels.map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}</div>
        </section>
      )}

      <div className="preference-preview" aria-live="polite">
        {previewLoading && <span>{copy.loadingChoices}</span>}
        {!previewLoading && previewMessage && <span className={preview?.eligible_menu_count === 0 ? "warning" : ""}>{previewMessage}</span>}
      </div>

      <section data-preference-group="core">
        <h2 className="visually-hidden">{groupCopy.core.title}</h2>
        <p className="visually-hidden">{groupCopy.core.help}</p>
        <div className="preference-primary-categories">{primaryCategories.map(inlineCategory)}</div>
      </section>

      <details className="preference-more-panel">
        <summary>
          <div><strong>{groupCopy.additional.title}</strong><small>{groupCopy.additional.help}</small></div>
          {moreSelectedCount > 0 && <em>{moreSelectedCount}</em>}
          <ChevronRight size={18} />
        </summary>
        <div className="preference-more-content">
          <aside className="preference-meaning-guide" aria-labelledby="preference-meaning-title">
            <strong id="preference-meaning-title">{groupCopy.semanticTitle}</strong>
            <p>{groupCopy.semanticHelp}</p>
          </aside>
          <section data-preference-group="additional">
            <h2 className="visually-hidden">{groupCopy.additional.title}</h2>
            <div className="preference-category-list">{additionalCategories.map((category) => categoryPanel(category))}</div>
          </section>

          <section data-preference-group="exact">
            <h2 className="visually-hidden">{groupCopy.exact.title}</h2>
            <div className="preference-category-list">{exactCategories.map((category) => categoryPanel(category))}</div>
            <fieldset className="preference-dietary">
            <legend>{copy.dietaryTitle}</legend>
            <label className={criteria.dietary_filters.halal_certified_only ? "dietary-toggle selected" : "dietary-toggle"}>
              <input type="checkbox" checked={criteria.dietary_filters.halal_certified_only} disabled={busy || catalog.capabilities?.halal_certified_only?.enabled === false} onChange={(event) => void changeDietary("halal_certified_only", event.target.checked)} />
              <span><strong>{copy.halal}</strong><small>{capabilityReason(catalog.capabilities?.halal_certified_only, copy.halalHelp, "검증 가능한 공식 인증 정보가 없어 현재 사용할 수 없습니다.")}</small></span>
            </label>
            <label className={criteria.dietary_filters.vegan ? "dietary-toggle selected" : "dietary-toggle"}>
              <input type="checkbox" checked={criteria.dietary_filters.vegan} disabled={busy || catalog.capabilities?.vegan?.enabled === false} onChange={(event) => void changeDietary("vegan", event.target.checked)} />
              <span><strong>{copy.vegan}</strong><small>{capabilityReason(catalog.capabilities?.vegan, copy.veganHelp, "검토된 메뉴별 재료 정보가 없어 현재 사용할 수 없습니다.")}</small></span>
            </label>
            </fieldset>

            <SpiceReferenceScale
              value={criteria.max_spice_level}
              country={criteria.spice_reference_country}
              references={catalog.spice_references}
              copy={copy}
              disabled={busy || catalog.capabilities?.max_spice_level?.enabled === false}
              onChange={(max_spice_level) => onChange({ ...criteria, max_spice_level })}
              onCountryChange={(spice_reference_country) => onChange({ ...criteria, spice_reference_country })}
            />
            {catalog.capabilities?.max_spice_level?.enabled === false && <p className="preference-capability-note" role="status">{capabilityReason(catalog.capabilities.max_spice_level, copy.spiceHelp, "검토된 메뉴별 맵기 정보가 없어 현재 사용할 수 없습니다.")}</p>}
          </section>
        </div>
      </details>

      {hasConflict && <p className="preference-conflict" role="alert">{conflictMessage}</p>}

      <footer className="preference-submit-bar">
        <button type="button" className="primary-button" onClick={onComplete} disabled={busy || !completeEnabled}>
          {copy.complete}{preview?.eligible_menu_count ? ` · ${preview.eligible_menu_count.toLocaleString()}` : ""}
        </button>
      </footer>
    </section>
  );
}
