import * as Dialog from "@radix-ui/react-dialog";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  GitCompareArrows,
  Leaf,
  Pencil,
  RotateCcw,
  Sparkles,
  Truck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  PreferenceCatalog,
  RecommendationBatchV2,
  RecommendationComparisonV2,
  StructuredRecommendation,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
import { asSupportedLanguage, menuName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getComparisonFieldCopy } from "../lib/comparisonI18n";
import {
  carouselDeltaForArrow,
  carouselIndexFromOffset,
  carouselOffsetForIndex,
} from "../lib/carouselScroll";

interface Props {
  batch: RecommendationBatchV2;
  catalog: PreferenceCatalog;
  copy: RecommendationCopy;
  language: string;
  locale: string;
  busy?: boolean;
  onChoose: (recommendation: StructuredRecommendation) => void;
  onSimilar: () => void;
  onEdit: () => void;
  onCompare: () => Promise<RecommendationComparisonV2>;
  onRetry: () => void;
}

function FoodArtwork() {
  return (
    <div className="yv2-food-art" aria-hidden="true">
      <img className="yv2-food-orb-one" src="/figma-yobi-v2/recommendation-icon-04.svg" alt="" />
      <img className="yv2-food-orb-two" src="/figma-yobi-v2/recommendation-icon-05.svg" alt="" />
      <img className="yv2-food-plate" src="/figma-yobi-v2/recommendation-icon-11.svg" alt="" />
      <img className="yv2-food-filling" src="/figma-yobi-v2/recommendation-icon-07.svg" alt="" />
      <img className="yv2-food-dot yv2-food-dot-one" src="/figma-yobi-v2/recommendation-icon-12.svg" alt="" />
      <img className="yv2-food-dot yv2-food-dot-two" src="/figma-yobi-v2/recommendation-icon-13.svg" alt="" />
      <img className="yv2-food-dot yv2-food-dot-three" src="/figma-yobi-v2/recommendation-icon-14.svg" alt="" />
      <img className="yv2-food-highlight" src="/figma-yobi-v2/recommendation-icon-10.svg" alt="" />
    </div>
  );
}

export function RecommendationResults({
  batch,
  catalog,
  copy,
  language,
  locale,
  busy = false,
  onChoose,
  onSimilar,
  onEdit,
  onCompare,
  onRetry,
}: Props) {
  const supportedLanguage = asSupportedLanguage(language);
  const productCopy = getProductCopy(supportedLanguage).recommendation;
  const comparisonCopy = getComparisonFieldCopy(supportedLanguage);
  const carouselRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [explanationMenuId, setExplanationMenuId] = useState<string | null>(null);
  const [comparison, setComparison] = useState<RecommendationComparisonV2 | null>(null);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const valueLabels = useMemo(() => new Map(
    catalog.categories.flatMap((category) => category.options.map((option) => [option.code, option.label] as const)),
  ), [catalog.categories]);
  const isFallback = batch.status === "SEARCH_FALLBACK";
  const explanationItem = batch.recommendations.find((item) => item.menu.menu_id === explanationMenuId) ?? null;

  useEffect(() => {
    setActiveIndex(0);
    setExplanationMenuId(null);
    setComparison(null);
    setComparisonOpen(false);
    setComparisonError("");
    const carousel = carouselRef.current;
    if (carousel && typeof carousel.scrollTo === "function") carousel.scrollTo({ left: 0 });
  }, [batch.request_id]);

  function moveTo(index: number) {
    const nextIndex = Math.max(0, Math.min(index, batch.recommendations.length - 1));
    setActiveIndex(nextIndex);
    const carousel = carouselRef.current;
    if (carousel && typeof carousel.scrollTo === "function") {
      carousel.scrollTo({ left: carouselOffsetForIndex(carousel, nextIndex), behavior: "smooth" });
    }
  }

  async function toggleComparison() {
    if (batch.recommendations.length < 2) return;
    if (comparison) {
      setComparisonOpen((value) => !value);
      return;
    }
    setComparisonLoading(true);
    setComparisonError("");
    setComparisonOpen(true);
    try {
      setComparison(await onCompare());
    } catch {
      setComparisonError(productCopy.compareFailed);
    } finally {
      setComparisonLoading(false);
    }
  }

  return (
    <Dialog.Root open={Boolean(explanationItem)} onOpenChange={(open) => { if (!open) setExplanationMenuId(null); }}>
      <section className="recommendation-results chat-result-experience yv2-recommendation-results" aria-labelledby="recommendation-results-title">
        <div className="assistant-message-row yv2-assistant-summary">
          <img className="assistant-avatar" src="/figma-yobi-v2/recommendation-icon-09.svg" alt="" />
          <div className="assistant-message-stack">
            <strong className="assistant-name">{productCopy.assistantName}</strong>
            <section className={isFallback ? "assistant-bubble result fallback" : "assistant-bubble result"}>
              <p className="yv2-eyebrow">{isFallback ? copy.searchFallbackTitle : copy.selectorEyebrow}</p>
              <h1 id="recommendation-results-title">{isFallback ? copy.searchFallbackTitle : copy.resultsTitle}</h1>
              <p>{isFallback ? copy.searchFallbackDescription : batch.criteria_summary || productCopy.ready}</p>
            </section>
          </div>
        </div>

        <div className="yv2-card-stack">
          <div className="structured-carousel-controls">
            <button type="button" aria-label={productCopy.previous} onClick={() => moveTo(activeIndex - 1)} disabled={activeIndex === 0}><ChevronLeft size={18} /></button>
            <span aria-live="polite">{productCopy.cardPosition(activeIndex + 1, batch.recommendations.length)}</span>
            <button type="button" aria-label={productCopy.next} onClick={() => moveTo(activeIndex + 1)} disabled={activeIndex === batch.recommendations.length - 1}><ChevronRight size={18} /></button>
          </div>

          <div
            ref={carouselRef}
            className="structured-menu-carousel yv2-menu-carousel"
            role="region"
            tabIndex={0}
            aria-label={copy.resultsTitle}
            onKeyDown={(event) => {
              const delta = carouselDeltaForArrow(event.currentTarget, event.key);
              if (delta) {
                event.preventDefault();
                moveTo(activeIndex + delta);
              }
            }}
            onScroll={(event) => {
              const element = event.currentTarget;
              setActiveIndex(carouselIndexFromOffset(element, batch.recommendations.length - 1));
            }}
          >
            {batch.recommendations.map((item) => {
              const foodDescription = item.description || item.menu.cultural_description || item.menu.description;
              const matchedLabels = item.matched_criteria.flatMap((match) => (
                match.labels?.length
                  ? match.labels
                  : match.selected_value_codes.map((code) => valueLabels.get(code)).filter((label): label is string => Boolean(label))
              ));
              return (
                <article className="structured-menu-card yv2-menu-card" key={item.menu.menu_id} data-testid={`menu-${item.menu.menu_id}`}>
                  <header className="yv2-pick-banner">
                    <span><Sparkles size={14} />YOBI PICK ARRIVED</span>
                    <small aria-hidden="true">{item.rank} / {batch.recommendations.length}</small>
                  </header>
                  <FoodArtwork />
                  <div className="structured-menu-content">
                    <div className="structured-menu-title-row">
                      <div><h2>{item.title || menuName(item.menu, language)}</h2><p>{menuName(item.menu, language)} · {item.menu.merchant_name}</p></div>
                      <strong>₩{item.menu.price.toLocaleString(locale)}</strong>
                    </div>

                    <section className="yv2-match-copy">
                      <strong>{copy.matchedPreferences}</strong>
                      <p>{isFallback ? copy.searchFallbackDescription : item.selection_reason}</p>
                      <small>{foodDescription}</small>
                    </section>

                    {matchedLabels.length > 0 && (
                      <div className="yv2-match-tags">{matchedLabels.slice(0, 5).map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}</div>
                    )}

                    <div className="structured-menu-facts yv2-menu-facts">
                      <span><Clock3 size={14} />{item.menu.eta_min}–{item.menu.eta_max}′</span>
                      <span><Truck size={14} />{item.menu.delivery_fee ? `₩${item.menu.delivery_fee.toLocaleString(locale)}` : productCopy.freeDelivery}</span>
                      <span>{item.menu.spice_level == null ? comparisonCopy.spiceUnverified : `${item.menu.spice_level} / 5`}</span>
                      {item.halal_certified && <span className="halal-status"><Check size={14} /> {copy.halalCertified}</span>}
                      {item.vegan_status === "LIKELY_FIT" && <span className="vegan-status"><Leaf size={14} /> {copy.veganLikely}</span>}
                      {item.vegan_status === "POSSIBLE_WITH_CHECKS" && <span className="vegan-check-status"><Leaf size={14} /> {copy.veganChecks}</span>}
                    </div>
                    {item.halal_certified && item.halal_scope_label && <p className="certification-scope"><strong>{copy.halalScope}:</strong> {item.halal_scope_label}</p>}
                    {item.vegan_warning && <p className="vegan-warning">{item.vegan_warning}</p>}

                    <button className="yv2-explanation-button" type="button" onClick={() => setExplanationMenuId(item.menu.menu_id)}>
                      <Sparkles size={16} />{copy.evidence}<ChevronRight size={16} />
                    </button>
                    <button className="yv2-primary-button" type="button" disabled={busy || !batch.snapshot_id} onClick={() => onChoose(item)}>{copy.chooseMenu}</button>
                  </div>
                </article>
              );
            })}
          </div>

          {batch.recommendations.length > 1 && (
            <div className="carousel-dots" aria-hidden="true">
              {batch.recommendations.map((item, index) => <span className={activeIndex === index ? "active" : ""} key={item.menu.menu_id} />)}
            </div>
          )}
        </div>

        {comparisonOpen && (
          <section className="yv2-comparison-panel" aria-live="polite">
            <header><GitCompareArrows size={18} /><h2>{productCopy.compareTitle}</h2></header>
            {comparisonLoading && <p>{productCopy.compareLoading}</p>}
            {comparisonError && <p className="yv2-error-banner" role="alert">{comparisonError}</p>}
            {comparison && (
              <>
                <p>{comparison.summary}</p>
                <div className="comparison-menu-list">
                  {comparison.items.map((item) => (
                    <article key={item.menu_id}>
                      <h3>{item.name}</h3>
                      <p><strong>{comparisonCopy.keyDifference}</strong>{item.key_difference}</p>
                      <p><strong>{comparisonCopy.tasteTexture}</strong>{item.taste_texture}</p>
                      <p><strong>{comparisonCopy.ingredientsForm}</strong>{item.ingredients_form}</p>
                      <p><strong>{comparisonCopy.spiceHeaviness}</strong>{item.spice_heaviness}</p>
                      <p><strong>{comparisonCopy.eatingContext}</strong>{item.eating_context}</p>
                      <p><strong>{comparisonCopy.bestFor}</strong>{item.best_for}</p>
                      {item.unverified_dietary_info && <p className="comparison-caution"><strong>{comparisonCopy.needsVerification}</strong>{item.unverified_dietary_info}</p>}
                    </article>
                  ))}
                </div>
              </>
            )}
          </section>
        )}

        {isFallback && <button type="button" className="yv2-secondary-button fallback-retry" onClick={onRetry} disabled={busy}>{copy.tryAgain}</button>}

        <aside className="result-action-rail yv2-quick-replies" aria-label={copy.resultsTitle}>
          <button type="button" onClick={onSimilar} disabled={busy || comparisonLoading}><RotateCcw size={17} /><span>{copy.similar}</span></button>
          <button type="button" aria-pressed={comparisonOpen} onClick={() => void toggleComparison()} disabled={busy || comparisonLoading || batch.recommendations.length < 2}><GitCompareArrows size={17} /><span>{copy.compare}</span></button>
          <button type="button" onClick={onEdit} disabled={busy || comparisonLoading}><Pencil size={17} /><span>{copy.editCriteria}</span></button>
        </aside>
        <p className="yv2-result-boundary">{copy.experienceNotice}</p>
      </section>

      <Dialog.Portal>
        <Dialog.Overlay className="yv2-sheet-overlay" />
        <Dialog.Content className="yv2-explanation-sheet">
          <div className="yv2-sheet-handle" aria-hidden="true" />
          <header>
            <div>
              <p className="yv2-eyebrow">AI GENERATED</p>
              <Dialog.Title>{copy.evidence}</Dialog.Title>
              <Dialog.Description>
                {explanationItem ? `${menuName(explanationItem.menu, language)} · ${explanationItem.menu.merchant_name}` : ""}
              </Dialog.Description>
            </div>
            <Dialog.Close className="yv2-icon-button" aria-label={getProductCopy(supportedLanguage).navigation.close}><X size={19} /></Dialog.Close>
          </header>
          {explanationItem && (
            <div className="yv2-explanation-content">
              <section><strong>{productCopy.foodDescription}</strong><p>{explanationItem.description || explanationItem.menu.cultural_description || explanationItem.menu.description}</p></section>
              <section><strong>{copy.matchedPreferences}</strong><p>{explanationItem.selection_reason}</p></section>
              {explanationItem.wiki_passages.length > 0 && (
                <section className="structured-evidence">
                  {explanationItem.wiki_passages.map((passage, index) => <blockquote key={passage.chunk_id ?? passage.evidence_id ?? index}>{passage.content}</blockquote>)}
                </section>
              )}
              <p className="yv2-explanation-boundary">{copy.experienceNotice}</p>
            </div>
          )}
          <Dialog.Close className="yv2-primary-button">{getProductCopy(supportedLanguage).navigation.close}</Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
