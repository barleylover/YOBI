import {
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  GitCompareArrows,
  Leaf,
  Pencil,
  RotateCcw,
  Search,
  Soup,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
  const [evidenceOpen, setEvidenceOpen] = useState<Set<string>>(() => new Set());
  const [comparison, setComparison] = useState<RecommendationComparisonV2 | null>(null);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const valueLabels = useMemo(() => new Map(
    catalog.categories.flatMap((category) => category.options.map((option) => [option.code, option.label] as const)),
  ), [catalog.categories]);
  const isFallback = batch.status === "SEARCH_FALLBACK";

  useEffect(() => {
    setActiveIndex(0);
    setEvidenceOpen(new Set());
    setComparison(null);
    setComparisonOpen(false);
    setComparisonError("");
    const carousel = carouselRef.current;
    if (carousel && typeof carousel.scrollTo === "function") carousel.scrollTo({ left: 0 });
  }, [batch.request_id]);

  function toggleEvidence(menuId: string) {
    setEvidenceOpen((current) => {
      const next = new Set(current);
      if (next.has(menuId)) next.delete(menuId); else next.add(menuId);
      return next;
    });
  }

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
    <section className="recommendation-results chat-result-experience" aria-labelledby="recommendation-results-title">
      <div className="assistant-message-row">
        <div className="assistant-avatar" aria-hidden="true">Y</div>
        <div className="assistant-message-stack">
          <strong className="assistant-name">{productCopy.assistantName}</strong>
          <section className={isFallback ? "assistant-bubble result fallback" : "assistant-bubble result"}>
            <header className="recommendation-result-heading">
              {isFallback ? <Search size={22} /> : <Sparkles size={22} />}
              <div>
                <p className="eyebrow">{isFallback ? copy.searchFallbackTitle : copy.selectorEyebrow}</p>
                <h1 id="recommendation-results-title">{isFallback ? copy.searchFallbackTitle : copy.resultsTitle}</h1>
                <p>{isFallback ? copy.searchFallbackDescription : batch.criteria_summary || productCopy.ready}</p>
              </div>
            </header>
          </section>
        </div>
      </div>

      <div className="assistant-message-row recommendation-card-message">
        <div className="assistant-avatar ghost" aria-hidden="true" />
        <div className="assistant-message-stack card-stack">
          <div className="structured-carousel-controls">
            <button type="button" aria-label={productCopy.previous} onClick={() => moveTo(activeIndex - 1)} disabled={activeIndex === 0}><ChevronLeft size={18} /></button>
            <span aria-live="polite">{productCopy.cardPosition(activeIndex + 1, batch.recommendations.length)}</span>
            <button type="button" aria-label={productCopy.next} onClick={() => moveTo(activeIndex + 1)} disabled={activeIndex === batch.recommendations.length - 1}><ChevronRight size={18} /></button>
          </div>

          <div
            ref={carouselRef}
            className="structured-menu-carousel"
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
              const evidenceVisible = evidenceOpen.has(item.menu.menu_id);
              const foodDescription = item.description || item.menu.cultural_description || item.menu.description;
              return (
                <article className="structured-menu-card" key={item.menu.menu_id} data-testid={`menu-${item.menu.menu_id}`}>
                  <div className="menu-artwork" aria-label={`${productCopy.foodDescription} · YOBI`} role="img">
                    <Soup size={42} />
                    <span>YOBI K-FOOD</span>
                  </div>
                  <div className="structured-menu-content">
                    <div className="structured-menu-title-row">
                      <div><h2>{item.title || menuName(item.menu, language)}</h2><p>{menuName(item.menu, language)} · {item.menu.merchant_name}</p></div>
                      <strong>₩{item.menu.price.toLocaleString(locale)}</strong>
                    </div>

                    <section className="food-description">
                      <h3>{productCopy.foodDescription}</h3>
                      <p>{foodDescription}</p>
                    </section>
                    <section className="match-reason"><h3>{copy.matchedPreferences}</h3><p>{isFallback ? copy.searchFallbackDescription : item.selection_reason}</p></section>

                    <div className="structured-menu-facts">
                      <span>{item.menu.eta_min}–{item.menu.eta_max}′</span>
                      <span>{productCopy.deliveryFee}: {item.menu.delivery_fee ? `₩${item.menu.delivery_fee.toLocaleString(locale)}` : productCopy.freeDelivery}</span>
                      <span>{item.menu.spice_level == null ? comparisonCopy.spiceUnverified : `${item.menu.spice_level} / 5`}</span>
                      {item.halal_certified && <span className="halal-status"><CheckCircle2 size={14} /> {copy.halalCertified}</span>}
                      {item.vegan_status === "LIKELY_FIT" && <span className="vegan-status"><Leaf size={14} /> {copy.veganLikely}</span>}
                      {item.vegan_status === "POSSIBLE_WITH_CHECKS" && <span className="vegan-check-status"><Leaf size={14} /> {copy.veganChecks}</span>}
                    </div>
                    {item.halal_certified && item.halal_scope_label && <p className="certification-scope"><strong>{copy.halalScope}:</strong> {item.halal_scope_label}</p>}
                    {item.vegan_warning && <p className="vegan-warning">{item.vegan_warning}</p>}

                    <button className="evidence-toggle" type="button" aria-expanded={evidenceVisible} onClick={() => toggleEvidence(item.menu.menu_id)}>
                      {evidenceVisible ? copy.hideEvidence : copy.evidence}<ChevronDown size={16} />
                    </button>
                    {evidenceVisible && (
                      <div className="structured-evidence">
                        {item.matched_criteria.length > 0 && <ul>{item.matched_criteria.map((match) => {
                          const labels = match.labels?.length
                            ? match.labels
                            : match.selected_value_codes.map((code) => valueLabels.get(code)).filter((label): label is string => Boolean(label));
                          return labels.length ? <li key={match.category_code}>{labels.join(" · ")}</li> : null;
                        })}</ul>}
                        {item.wiki_passages.map((passage, index) => <blockquote key={passage.chunk_id ?? passage.evidence_id ?? index}>{passage.content}</blockquote>)}
                      </div>
                    )}

                    <button className="primary-button full" type="button" disabled={busy || !batch.snapshot_id} onClick={() => onChoose(item)}>{copy.chooseMenu}</button>
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
      </div>

      {comparisonOpen && (
        <div className="assistant-message-row comparison-message">
          <div className="assistant-avatar" aria-hidden="true">Y</div>
          <div className="assistant-message-stack">
            <strong className="assistant-name">{productCopy.assistantName}</strong>
            <section className="assistant-bubble comparison" aria-live="polite">
              <header><GitCompareArrows size={18} /><h2>{productCopy.compareTitle}</h2></header>
              {comparisonLoading && <p>{productCopy.compareLoading}</p>}
              {comparisonError && <p className="form-error" role="alert">{comparisonError}</p>}
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
          </div>
        </div>
      )}

      {isFallback && <button type="button" className="text-button fallback-retry" onClick={onRetry} disabled={busy}>{copy.tryAgain}</button>}

      {typeof document !== "undefined" && createPortal(
        <aside className="result-action-rail" aria-label={copy.resultsTitle}>
          <button type="button" onClick={onSimilar} disabled={busy || comparisonLoading}><RotateCcw size={18} /><span>{copy.similar}</span></button>
          <button type="button" aria-pressed={comparisonOpen} onClick={() => void toggleComparison()} disabled={busy || comparisonLoading || batch.recommendations.length < 2}><GitCompareArrows size={18} /><span>{copy.compare}</span></button>
          <button type="button" onClick={onEdit} disabled={busy || comparisonLoading}><Pencil size={18} /><span>{copy.editCriteria}</span></button>
        </aside>,
        document.body,
      )}
    </section>
  );
}
