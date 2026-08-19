import { useMemo, useState } from "react";
import type {
  PreferenceCatalog,
  PreferenceCatalogCategory,
  PreferenceCategoryCode,
  RecommendationCriteriaV2,
  RecommendationPreviewV2,
  SpiceReferenceCountry,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
import type { RedesignCopy } from "../lib/redesignI18n";

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

export type WizardSection = "core" | "taste" | "conditions";

const SECTION_ORDER: WizardSection[] = ["core", "taste", "conditions"];

interface Props {
  catalog: PreferenceCatalog;
  criteria: RecommendationCriteriaV2;
  copy: RecommendationCopy;
  v2: RedesignCopy;
  busy?: boolean;
  previewLoading?: boolean;
  preview?: RecommendationPreviewV2 | null;
  previewMessage?: string;
  canSubmitUnchanged?: boolean;
  conflictMessage: string;
  notice?: string;
  onChange: (criteria: RecommendationCriteriaV2) => void;
  onValidateAdd?: (criteria: RecommendationCriteriaV2) => Promise<boolean>;
  onComplete: () => void;
  onBack: () => void;
}

function countCriteria(criteria: RecommendationCriteriaV2) {
  return CATEGORY_KEYS.reduce((total, key) => total + criteria[key].length, 0)
    + Number(criteria.dietary_filters.halal_certified_only)
    + Number(criteria.dietary_filters.vegan);
}

export function PreferenceWizard({
  catalog,
  criteria,
  copy,
  v2,
  busy = false,
  previewLoading = false,
  preview = null,
  previewMessage = "",
  canSubmitUnchanged = false,
  conflictMessage,
  notice = "",
  onChange,
  onValidateAdd,
  onComplete,
  onBack,
}: Props) {
  const [section, setSection] = useState<WizardSection>("core");
  const sectionIndex = SECTION_ORDER.indexOf(section);

  const grouped = useMemo(() => ({
    core: catalog.categories.filter((category) => category.group === "core"),
    taste: catalog.categories.filter((category) => category.group === "additional"),
    conditions: catalog.categories.filter((category) => category.group === "exact"),
  }), [catalog.categories]);

  const selectedCount = countCriteria(criteria);
  const sectionCounts: Record<WizardSection, number> = {
    core: grouped.core.reduce((total, category) => total + criteria[category.code].length, 0),
    taste: grouped.taste.reduce((total, category) => total + criteria[category.code].length, 0),
    conditions: grouped.conditions.reduce((total, category) => total + criteria[category.code].length, 0)
      + Number(criteria.dietary_filters.halal_certified_only)
      + Number(criteria.dietary_filters.vegan),
  };

  const ingredientCodes = new Set(criteria.main_ingredients);
  const hasConflict = (
    criteria.dietary_filters.halal_certified_only && ingredientCodes.has("PORK")
  ) || (
    criteria.dietary_filters.vegan
    && ["BEEF", "PORK", "CHICKEN", "FISH_SEAFOOD"].some((code) => ingredientCodes.has(code))
  );

  const sectionLabels: Record<WizardSection, string> = {
    core: v2.sectionCore,
    taste: v2.sectionTaste,
    conditions: v2.sectionConditions,
  };
  const stepLabels: Record<WizardSection, string> = {
    core: v2.stepOf(2, 4, v2.sectionPreferences),
    taste: v2.stepOf(3, 4, v2.sectionTaste),
    conditions: v2.stepOf(4, 4, v2.sectionConditions),
  };

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

  function goBack() {
    if (sectionIndex === 0) onBack();
    else setSection(SECTION_ORDER[sectionIndex - 1]);
    window.scrollTo({ top: 0 });
  }

  function goNext() {
    if (section === "conditions") {
      onComplete();
      return;
    }
    setSection(SECTION_ORDER[sectionIndex + 1]);
    window.scrollTo({ top: 0 });
  }

  const completeEnabled = (selectedCount > 0 || canSubmitUnchanged) && !hasConflict;
  const nextDisabled = busy || (section === "conditions" && !completeEnabled);

  function categoryCard(category: PreferenceCatalogCategory) {
    const count = criteria[category.code].length;
    return (
      <section className="v2-pref-card" data-category={category.code} key={category.code}>
        <header>
          <h2>{category.label}</h2>
          {count > 0 && <span className="v2-count-badge">{count}</span>}
          <div className="spacer" />
          {count > 0
            ? <button type="button" className="v2-inline-clear" onClick={() => clearCategory(category.code)}>{v2.clear}</button>
            : <span className="v2-any-label">{v2.any}</span>}
        </header>
        <div className="v2-chip-grid">
          {category.options.map((option) => {
            const selected = criteria[category.code].includes(option.code);
            return (
              <button
                type="button"
                key={option.code}
                data-option-code={option.code}
                className={selected ? "v2-chip selected" : "v2-chip"}
                aria-pressed={selected}
                disabled={busy}
                title={option.description ?? undefined}
                onClick={() => void toggle(category.code, option.code)}
              >
                {selected && <img src="/figma/radio-check.svg" alt="" width={12} height={10} />}
                {option.label}
              </button>
            );
          })}
        </div>
      </section>
    );
  }

  const spiceDisabled = busy || catalog.capabilities?.max_spice_level?.enabled === false;
  const activeReference = catalog.spice_references.find(
    (reference) => reference.country === criteria.spice_reference_country,
  ) ?? catalog.spice_references[0];
  const activeLevel = activeReference?.levels.find((item) => item.level === criteria.max_spice_level);

  return (
    <div className="v2-screen subtle v2-wizard">
      <header className="v2-appbar">
        <button type="button" className="v2-icon-button" aria-label={v2.back} onClick={goBack}>
          <img src="/figma/back-chevron.svg" alt="" width={9} height={16} />
        </button>
        <p className="v2-appbar-step">{stepLabels[section]}</p>
        <button
          type="button"
          className="v2-appbar-action"
          onClick={clearAll}
          disabled={busy || selectedCount === 0}
        >
          {copy.clearAll}
        </button>
      </header>
      <div className="v2-progress" aria-hidden="true">
        {[0, 1, 2, 3].map((step) => (
          <span key={step} className={step <= sectionIndex + 1 ? "active" : ""} />
        ))}
      </div>
      <div className="v2-section-tabs" role="tablist" aria-label={v2.sectionPreferences}>
        {SECTION_ORDER.map((item) => (
          <button
            type="button"
            role="tab"
            key={item}
            aria-selected={section === item}
            className={section === item ? "active" : ""}
            onClick={() => setSection(item)}
          >
            {sectionLabels[item]}
            {sectionCounts[item] > 0 && <span>{sectionCounts[item]}</span>}
          </button>
        ))}
      </div>

      <div className="v2-wizard-body">
        {section === "core" && (
          <div className="v2-heading" style={{ padding: "0 4px" }}>
            <h1 style={{ fontSize: 24 }}>{v2.craveTitle}</h1>
            <p>{v2.craveSubtitle}</p>
          </div>
        )}

        {notice && <p className="v2-status" role="status">{notice}</p>}

        <div className="v2-banner" aria-live="polite">
          <p>
            {previewLoading && copy.loadingChoices}
            {!previewLoading && preview && !previewMessage && v2.liveCount(preview.eligible_menu_count, preview.eligible_merchant_count)}
            {!previewLoading && previewMessage}
            {!previewLoading && !preview && !previewMessage && copy.multiSelect}
          </p>
        </div>

        {section !== "conditions" && grouped[section].map((category) => categoryCard(category))}

        {section === "conditions" && (
          <>
            <section className="v2-pref-card" data-category="max_spice_level">
              <header>
                <h2>{copy.spiceTitle}</h2>
                <div className="spacer" />
                <span className="v2-inline-clear as-label">{v2.upTo(criteria.max_spice_level)}</span>
              </header>
              <p className="v2-card-help">{copy.spiceHelp}</p>
              {catalog.spice_references.length > 1 && (
                <div className="v2-seg-tabs" role="group" aria-label={copy.spiceTitle}>
                  {catalog.spice_references.map((reference) => (
                    <button
                      type="button"
                      key={reference.country}
                      aria-selected={criteria.spice_reference_country === reference.country}
                      onClick={() => onChange({
                        ...criteria,
                        spice_reference_country: reference.country as SpiceReferenceCountry,
                      })}
                    >
                      {reference.country === "KR" ? copy.koreanReference : copy.usReference}
                    </button>
                  ))}
                </div>
              )}
              <div className="v2-spice-stepper" role="radiogroup" aria-label={copy.spiceTitle}>
                {([1, 2, 3, 4, 5] as const).map((level, index) => (
                  <span key={level} className="v2-spice-step">
                    {index > 0 && <i className={level <= criteria.max_spice_level ? "filled" : ""} />}
                    <button
                      type="button"
                      role="radio"
                      aria-checked={criteria.max_spice_level === level}
                      className={level <= criteria.max_spice_level ? "filled" : ""}
                      disabled={spiceDisabled}
                      onClick={() => onChange({ ...criteria, max_spice_level: level })}
                    >
                      {level}
                    </button>
                  </span>
                ))}
              </div>
              <div className="v2-spice-range-labels" aria-hidden="true">
                <span>{v2.mild}</span>
                <span>{v2.veryHot}</span>
              </div>
              {activeLevel && (
                <div className="v2-spice-example">
                  <span className="v2-count-badge large">{activeLevel.level}</span>
                  <div>
                    <strong>{activeLevel.label} · <em>{activeLevel.example}</em></strong>
                    {activeLevel.description && <small>{activeLevel.description}</small>}
                  </div>
                </div>
              )}
              {catalog.capabilities?.max_spice_level?.enabled === false && (
                <p className="v2-capability-note" role="status">
                  {catalog.capabilities.max_spice_level.reason || v2.capabilityUnavailable}
                </p>
              )}
            </section>

            <section className="v2-pref-card" data-category="dietary">
              <header>
                <h2>{copy.dietaryTitle}</h2>
                {(Number(criteria.dietary_filters.halal_certified_only) + Number(criteria.dietary_filters.vegan)) > 0 && (
                  <span className="v2-count-badge">
                    {Number(criteria.dietary_filters.halal_certified_only) + Number(criteria.dietary_filters.vegan)}
                  </span>
                )}
              </header>
              {([
                ["halal_certified_only", v2.halalLabel, copy.halalHelp, catalog.capabilities?.halal_certified_only] as const,
                ["vegan", v2.veganLabel, copy.veganHelp, catalog.capabilities?.vegan] as const,
              ]).map(([key, label, help, capability], index) => {
                const checked = criteria.dietary_filters[key];
                const unavailable = capability?.enabled === false;
                return (
                  <div key={key}>
                    {index > 0 && <div className="v2-divider" />}
                    <label className="v2-switch-row">
                      <div>
                        <strong>{label}</strong>
                        {unavailable
                          ? <small className="warn">{capability?.reason || v2.capabilityUnavailable}</small>
                          : <small>{help}</small>}
                      </div>
                      <input
                        type="checkbox"
                        role="switch"
                        checked={checked}
                        disabled={busy || unavailable}
                        onChange={(event) => void changeDietary(key, event.target.checked)}
                      />
                      <span className="v2-switch" aria-hidden="true" />
                    </label>
                  </div>
                );
              })}
            </section>

            {grouped.conditions.map((category) => categoryCard(category))}

            {hasConflict && <p className="v2-error" role="alert">{conflictMessage}</p>}
          </>
        )}
      </div>

      <footer className="v2-sticky-bar">
        <div className="v2-selection-bar">
          <p>{copy.selectedCount(selectedCount)}</p>
          <button type="button" className="v2-selection-next" onClick={goNext} disabled={nextDisabled}>
            {section === "conditions" ? v2.findMyDish : v2.next}
            <img src="/figma/right-chevron-white.svg" alt="" width={7} height={14} />
          </button>
        </div>
      </footer>
    </div>
  );
}
