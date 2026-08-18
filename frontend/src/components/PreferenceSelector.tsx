import { ArrowLeft, ArrowRight, Check, RotateCcw, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
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

const STEP_CATEGORIES: PreferenceCategoryCode[][] = [
  ["cuisine_origins", "main_ingredients", "food_forms"],
  ["flavors", "temperatures", "textures", "cooking_methods"],
  ["price_bands"],
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
  onBack?: () => void;
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
  onBack,
}: Props) {
  const [step, setStep] = useState(0);
  const selectedCount = countCriteria(criteria);
  const groupCopy = getPreferenceGroupCopy(catalog.locale);
  const stepCopy = [
    groupCopy.core,
    groupCopy.additional,
    groupCopy.exact,
  ];
  const categoriesByStep = useMemo(() => STEP_CATEGORIES.map((codes) => {
    const codeSet = new Set(codes);
    return catalog.categories.filter((category) => codeSet.has(category.code));
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
  const completeEnabled = (selectedCount > 0 || canSubmitUnchanged) && !hasConflict;

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

  function previousStep() {
    if (step > 0) {
      setStep((value) => value - 1);
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    onBack?.();
  }

  function nextStep() {
    if (step < 2) {
      setStep((value) => value + 1);
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    onComplete();
  }

  function categoryPanel(category: PreferenceCatalogCategory) {
    return (
      <section className="yv2-preference-category preference-category" data-category={category.code} key={category.code}>
        <header>
          <div><h2>{category.label}</h2>{category.description && <p>{category.description}</p>}</div>
          {criteria[category.code].length > 0 && (
            <button type="button" onClick={() => clearCategory(category.code)}>{copy.clearCategory}</button>
          )}
        </header>
        <div className="yv2-preference-chip-grid">
          {category.options.map((option) => {
            const selected = criteria[category.code].includes(option.code);
            return (
              <button
                type="button"
                key={option.code}
                data-option-code={option.code}
                className={selected ? "yv2-preference-chip selected" : "yv2-preference-chip"}
                aria-pressed={selected}
                disabled={busy}
                onClick={() => void toggle(category.code, option.code)}
              >
                <span className="yv2-chip-check">{selected && <Check size={13} />}</span>
                <span><strong>{option.label}</strong>{option.description && <small>{option.description}</small>}</span>
              </button>
            );
          })}
        </div>
      </section>
    );
  }

  return (
    <section className={conversationMode ? "yv2-preference-selector conversation-quick-replies" : "yv2-preference-selector"} aria-labelledby="preference-selector-title">
      <header className="yv2-preference-header">
        <button className="yv2-icon-button" type="button" aria-label={copy.editCriteria} onClick={previousStep}>
          <ArrowLeft size={20} />
        </button>
        <div className="yv2-step-progress">
          <span>{step + 2} / 4</span>
          <i><b style={{ inlineSize: `${((step + 2) / 4) * 100}%` }} /></i>
        </div>
        <span className="yv2-selection-count">{copy.selectedCount(selectedCount)}</span>
      </header>

      <nav className="yv2-preference-tabs" aria-label={copy.selectorTitle}>
        {stepCopy.map((item, index) => (
          <button
            type="button"
            role="tab"
            className={step === index ? "active" : ""}
            aria-selected={step === index}
            aria-current={step === index ? "step" : undefined}
            onClick={() => setStep(index)}
            key={item.title}
          >
            <span>{index + 1}</span>{item.title}
          </button>
        ))}
      </nav>

      <div className="yv2-preference-body">
        <header className="yv2-screen-title">
          <p className="yv2-eyebrow">{copy.selectorEyebrow}</p>
          <h1 id="preference-selector-title">{step === 0 ? copy.selectorTitle : stepCopy[step].title}</h1>
          <p>{stepCopy[step].help}</p>
        </header>

        {(previewLoading || previewMessage) && (
          <div className={preview?.eligible_menu_count === 0 ? "yv2-preview-pill warning" : "yv2-preview-pill"} aria-live="polite">
            <Sparkles size={15} />{previewLoading ? copy.loadingChoices : previewMessage}
          </div>
        )}

        {selectedLabels.length > 0 && (
          <div className="yv2-selected-strip" aria-label={copy.selectedSummary}>
            {selectedLabels.map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}
          </div>
        )}

        <section className="yv2-preference-step-content" data-preference-group={step === 0 ? "core" : step === 1 ? "additional" : "exact"}>
          <div className="yv2-preference-category-list">
            {categoriesByStep[step].map(categoryPanel)}
          </div>

          {step === 2 && (
            <>
              <aside className="yv2-meaning-guide">
                <strong>{groupCopy.semanticTitle}</strong>
                <p>{groupCopy.semanticHelp}</p>
              </aside>

              <fieldset className="preference-dietary yv2-preference-dietary">
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
                onChange={(max_spice_level) => onChange({ ...criteria, max_spice_level })}
                onCountryChange={(spice_reference_country) => onChange({ ...criteria, spice_reference_country })}
              />
              {catalog.capabilities?.max_spice_level?.enabled === false && (
                <p className="preference-capability-note" role="status">{capabilityReason(
                  catalog.capabilities.max_spice_level,
                  copy.spiceHelp,
                  "검토된 메뉴별 맵기 정보가 없어 현재 사용할 수 없습니다.",
                )}</p>
              )}
            </>
          )}
        </section>

        {hasConflict && <p className="yv2-error-banner" role="alert">{conflictMessage}</p>}
      </div>

      <footer className="yv2-preference-footer">
        <div><strong>{copy.selectedCount(selectedCount)}</strong><small>{copy.noHiddenRelaxation}</small></div>
        <button type="button" className="yv2-clear-button" onClick={clearAll} disabled={busy || selectedCount === 0}>
          <RotateCcw size={15} />{copy.clearAll}
        </button>
        <button
          type="button"
          className="yv2-primary-button"
          onClick={nextStep}
          disabled={busy || (step === 2 && !completeEnabled)}
        >
          {step === 2 ? copy.complete : stepCopy[step + 1].title}
          {step === 2 ? <Sparkles size={18} /> : <ArrowRight size={18} />}
        </button>
      </footer>
    </section>
  );
}
