import { useMemo, useState, type CSSProperties } from "react";
import type {
  PreferenceCatalog,
  PreferenceCatalogCategory,
  PreferenceCategoryCode,
  RecommendationCriteriaV2,
  RecommendationPreviewV2,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
import type { RedesignCopy } from "../lib/redesignI18n";

const CATEGORY_KEYS: PreferenceCategoryCode[] = [
  "cuisine_origins",
  "flavors",
  "main_ingredients",
  "food_forms",
  "temperatures",
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
  initialSection?: WizardSection;
  onChange: (criteria: RecommendationCriteriaV2) => void;
  onValidateAdd?: (criteria: RecommendationCriteriaV2) => Promise<boolean>;
  onComplete: () => void;
  onBack: () => void;
  onCancel?: () => void;
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
  initialSection = "core",
  onChange,
  onValidateAdd,
  onComplete,
  onBack,
  onCancel,
}: Props) {
  const [section, setSection] = useState<WizardSection>(initialSection);
  const [pendingSpiceEndpoint, setPendingSpiceEndpoint] = useState<number | null>(null);
  const sectionIndex = SECTION_ORDER.indexOf(section);
  const priceCatalog = catalog.price_range_krw ?? { min: 4_000, max: 50_000, step: 1_000 };
  const defaultPrice = {
    min: Math.max(priceCatalog.min, 6_000),
    max: Math.min(priceCatalog.max, 50_000),
  };
  const selectedPrice = criteria.price_range_krw ?? defaultPrice;
  const selectedSpiceRange = criteria.spice_range ?? { min: 1 as const, max: 5 as const };
  const hasCustomExactCriteria = selectedPrice.min !== defaultPrice.min
    || selectedPrice.max !== defaultPrice.max
    || selectedSpiceRange.min !== 1
    || selectedSpiceRange.max !== 5;

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
      + Number(criteria.dietary_filters.vegan)
      + Number(hasCustomExactCriteria),
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
    core: v2.stepPreferences,
    taste: v2.stepPreferencesTaste,
    conditions: v2.stepPreferencesConditions,
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
    setPendingSpiceEndpoint(null);
    onChange({
      ...criteria,
      ...Object.fromEntries(CATEGORY_KEYS.map((key) => [key, []])),
      price_bands: [],
      price_range_krw: defaultPrice,
      spice_range: { min: 1, max: 5 },
      spice_preference: "SIMILAR",
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

  const completeEnabled = (
    criteria.schema_version === "3" || selectedCount > 0 || canSubmitUnchanged
  ) && !hasConflict;
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
                {option.label}
              </button>
            );
          })}
        </div>
      </section>
    );
  }

  const countrySpiceProfile = catalog.country_spice_profiles?.find(
    (item) => item.country_code === criteria.spice_reference_country,
  ) ?? catalog.country_spice_profiles?.find((item) => item.country_code === "US");

  function changePrice(edge: "min" | "max", value: number) {
    const min = edge === "min" ? Math.min(value, selectedPrice.max - priceCatalog.step) : selectedPrice.min;
    const max = edge === "max" ? Math.max(value, selectedPrice.min + priceCatalog.step) : selectedPrice.max;
    onChange({ ...criteria, price_range_krw: { min, max }, price_bands: [] });
  }

  function selectSpiceEndpoint(level: 1 | 2 | 3 | 4 | 5) {
    if (pendingSpiceEndpoint == null) {
      setPendingSpiceEndpoint(level);
      return;
    }
    const minimum = Math.min(pendingSpiceEndpoint, level) as 1 | 2 | 3 | 4 | 5;
    const maximum = Math.max(pendingSpiceEndpoint, level) as 1 | 2 | 3 | 4 | 5;
    setPendingSpiceEndpoint(null);
    onChange({ ...criteria, spice_range: { min: minimum, max: maximum } });
  }

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
          disabled={busy || (selectedCount === 0 && !hasCustomExactCriteria)}
        >
          {copy.clearAll}
        </button>
      </header>
      <div className="v2-progress" aria-hidden="true">
        {[0, 1, 2].map((step) => (
          <span key={step} className={step <= 1 ? "active" : ""} />
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

        <div className="v2-live-preview" role="status" aria-live="polite">
          {previewLoading
            ? <span>{copy.loadingChoices}</span>
            : preview
              ? <strong>{v2.liveCount(preview.eligible_menu_count, preview.eligible_merchant_count)}</strong>
              : <span>{v2.craveSubtitle}</span>}
        </div>

        {previewMessage && <p className="v2-error" role="status">{previewMessage}</p>}

        {section !== "conditions" && grouped[section].map((category) => categoryCard(category))}

        {section === "conditions" && (
          <>
            <section className="v2-pref-card" data-category="spice_preference">
              <header>
                <h2>{copy.spiceTitle}</h2>
              </header>
              <p className="v2-card-help">{copy.spiceHelp}</p>
              <div className="v2-spice-range-summary" aria-live="polite">
                <strong>{v2.spiceRangeSelection(selectedSpiceRange.min, selectedSpiceRange.max)}</strong>
                <small>{v2.spiceRangeInstruction(pendingSpiceEndpoint)}</small>
              </div>
              <div
                className="v2-spice-range"
                role="group"
                aria-label={copy.spiceTitle}
                data-testid="spice-range-selector"
                style={{
                  "--spice-range-start": `${10 + ((selectedSpiceRange.min - 1) / 4) * 80}%`,
                  "--spice-range-width": `${((selectedSpiceRange.max - selectedSpiceRange.min) / 4) * 80}%`,
                } as CSSProperties}
              >
                <span className="v2-spice-range-track" aria-hidden="true" />
                <span className="v2-spice-range-fill" aria-hidden="true" />
                {([1, 2, 3, 4, 5] as const).map((level) => {
                  const inRange = level >= selectedSpiceRange.min && level <= selectedSpiceRange.max;
                  const endpoint = level === selectedSpiceRange.min || level === selectedSpiceRange.max;
                  return (
                    <button
                      type="button"
                      key={level}
                      className={[
                        inRange ? "in-range" : "",
                        endpoint ? "endpoint" : "",
                        pendingSpiceEndpoint === level ? "pending" : "",
                      ].filter(Boolean).join(" ")}
                      aria-pressed={inRange}
                      aria-label={`${copy.spiceTitle} ${level}/5`}
                      disabled={busy}
                      onClick={() => selectSpiceEndpoint(level)}
                    >
                      {level}
                    </button>
                  );
                })}
              </div>
              {Boolean(countrySpiceProfile?.spice_scale_anchors?.length) && (
                <div className="v2-spice-guide" data-testid="country-spice-reference">
                  <small>{v2.spiceScaleGuide}</small>
                  <div className="v2-spice-anchor-grid">
                    {countrySpiceProfile!.spice_scale_anchors!.map((anchor) => (
                      <p key={anchor.level} style={{ gridColumn: anchor.level }}>
                        {v2.spiceScaleAnchor(
                          anchor.level,
                          anchor.familiar_dish,
                          anchor.approximate_shu_min,
                          anchor.approximate_shu_max,
                        )}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </section>

            <section className="v2-pref-card" data-category="price_range_krw">
              <header>
                <h2>{v2.priceRange}</h2>
                <div className="spacer" />
                <span className="v2-inline-clear as-label">₩{selectedPrice.min.toLocaleString()}–₩{selectedPrice.max.toLocaleString()}</span>
              </header>
              <div className="v2-price-range" aria-label={v2.priceRange}>
                <input
                  type="range"
                  min={priceCatalog.min}
                  max={priceCatalog.max}
                  step={priceCatalog.step}
                  value={selectedPrice.min}
                  disabled={busy}
                  aria-label={v2.priceMinimum}
                  onChange={(event) => changePrice("min", Number(event.target.value))}
                />
                <input
                  type="range"
                  min={priceCatalog.min}
                  max={priceCatalog.max}
                  step={priceCatalog.step}
                  value={selectedPrice.max}
                  disabled={busy}
                  aria-label={v2.priceMaximum}
                  onChange={(event) => changePrice("max", Number(event.target.value))}
                />
                <div className="v2-price-range-labels"><span>₩{priceCatalog.min.toLocaleString()}</span><span>₩{priceCatalog.max.toLocaleString()}</span></div>
              </div>
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

            {grouped.conditions.filter((category) => category.code !== "price_bands").map((category) => categoryCard(category))}

            {hasConflict && <p className="v2-error" role="alert">{conflictMessage}</p>}
          </>
        )}
      </div>

      <footer className="v2-sticky-bar">
        {onCancel && (
          <button type="button" className="v2-text-button v2-wizard-cancel" onClick={onCancel} disabled={busy}>
            {v2.cancelChanges}
          </button>
        )}
        <div className="v2-selection-bar">
          <p>{copy.selectedCount(selectedCount)}</p>
          <button type="button" className="v2-selection-next" onClick={goNext} disabled={nextDisabled}>
            {section === "conditions" ? (onCancel ? v2.saveChanges : v2.findMyDish) : v2.next}
            <img src="/figma/right-chevron-white.svg" alt="" width={7} height={14} />
          </button>
        </div>
      </footer>
    </div>
  );
}
