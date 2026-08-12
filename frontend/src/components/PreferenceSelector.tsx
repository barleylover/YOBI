import { Check, RotateCcw, Sparkles } from "lucide-react";
import { useMemo } from "react";
import type {
  PreferenceCatalog,
  PreferenceCategoryCode,
  RecommendationCriteriaV2,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
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
  canSubmitUnchanged?: boolean;
  conflictMessage: string;
  onChange: (criteria: RecommendationCriteriaV2) => void;
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
  canSubmitUnchanged = false,
  conflictMessage,
  onChange,
  onComplete,
}: Props) {
  const selectedCount = countCriteria(criteria);
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

  function toggle(category: PreferenceCategoryCode, code: string) {
    const selected = criteria[category];
    onChange({
      ...criteria,
      [category]: selected.includes(code)
        ? selected.filter((value) => value !== code)
        : [...selected, code],
    });
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
  return (
    <section className="preference-selector" aria-labelledby="preference-selector-title">
      <header className="preference-selector-heading">
        <p className="eyebrow">{copy.selectorEyebrow}</p>
        <h1 id="preference-selector-title">{copy.selectorTitle}</h1>
        <p>{copy.selectorDescription}</p>
        <span><Check size={14} /> {copy.multiSelect}</span>
      </header>

      {selectedLabels.length > 0 && (
        <section className="preference-summary" aria-label={copy.selectedSummary}>
          <div><strong>{copy.selectedSummary}</strong><span>{copy.selectedCount(selectedCount)}</span></div>
          <div className="preference-summary-tags">{selectedLabels.map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}</div>
        </section>
      )}

      <div className="preference-category-list">
        {catalog.categories.map((category, index) => (
          <details className="preference-category" open={index < 2} key={category.code}>
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
                    className={selected ? "preference-chip selected" : "preference-chip"}
                    aria-pressed={selected}
                    disabled={busy}
                    onClick={() => toggle(category.code, option.code)}
                  >
                    {selected && <Check size={14} />}
                    <span><strong>{option.label}</strong>{option.description && <small>{option.description}</small>}</span>
                  </button>
                );
              })}
            </div>
          </details>
        ))}
      </div>

      <fieldset className="preference-dietary">
        <legend>{copy.dietaryTitle}</legend>
        <label className={criteria.dietary_filters.halal_certified_only ? "dietary-toggle selected" : "dietary-toggle"}>
          <input
            type="checkbox"
            checked={criteria.dietary_filters.halal_certified_only}
            disabled={busy}
            onChange={(event) => onChange({
              ...criteria,
              dietary_filters: { ...criteria.dietary_filters, halal_certified_only: event.target.checked },
            })}
          />
          <span><strong>{copy.halal}</strong><small>{copy.halalHelp}</small></span>
        </label>
        <label className={criteria.dietary_filters.vegan ? "dietary-toggle selected" : "dietary-toggle"}>
          <input
            type="checkbox"
            checked={criteria.dietary_filters.vegan}
            disabled={busy}
            onChange={(event) => onChange({
              ...criteria,
              dietary_filters: { ...criteria.dietary_filters, vegan: event.target.checked },
            })}
          />
          <span><strong>{copy.vegan}</strong><small>{copy.veganHelp}</small></span>
        </label>
      </fieldset>

      <SpiceReferenceScale
        value={criteria.max_spice_level}
        country={criteria.spice_reference_country}
        references={catalog.spice_references}
        copy={copy}
        disabled={busy}
        onChange={(max_spice_level) => {
          onChange({ ...criteria, max_spice_level });
        }}
        onCountryChange={(spice_reference_country) => {
          onChange({ ...criteria, spice_reference_country });
        }}
      />

      {hasConflict && <p className="preference-conflict" role="alert">{conflictMessage}</p>}

      <footer className="preference-submit-bar">
        <div><strong>{copy.selectedCount(selectedCount)}</strong><small>{copy.noHiddenRelaxation}</small></div>
        <button type="button" className="text-button" onClick={clearAll} disabled={busy || selectedCount === 0}><RotateCcw size={16} /> {copy.clearAll}</button>
        <button type="button" className="primary-button" onClick={onComplete} disabled={busy || !completeEnabled}><Sparkles size={18} /> {copy.complete}</button>
      </footer>
    </section>
  );
}
