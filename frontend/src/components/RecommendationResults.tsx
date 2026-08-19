import { useEffect, useMemo, useRef, useState } from "react";
import type {
  PreferenceCatalog,
  RecommendationBatchV2,
  RecommendationComparisonV2,
  StructuredRecommendation,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
import type { RedesignCopy } from "../lib/redesignI18n";
import { asSupportedLanguage, menuName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getComparisonFieldCopy } from "../lib/comparisonI18n";
import { carouselIndexFromOffset } from "../lib/carouselScroll";
import { BottomSheet } from "./BottomSheet";

interface Props {
  batch: RecommendationBatchV2;
  catalog: PreferenceCatalog;
  copy: RecommendationCopy;
  v2: RedesignCopy;
  language: string;
  locale: string;
  busy?: boolean;
  timestamp: string;
  onChoose: (recommendation: StructuredRecommendation) => void;
  onCompare: () => Promise<RecommendationComparisonV2>;
  onRetry: () => void;
}

export function RecommendationResults({
  batch,
  catalog,
  copy,
  v2,
  language,
  locale,
  busy = false,
  timestamp,
  onChoose,
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

  useEffect(() => {
    setActiveIndex(0);
    setExplanationMenuId(null);
    setComparison(null);
    setComparisonOpen(false);
    setComparisonError("");
    const carousel = carouselRef.current;
    if (carousel && typeof carousel.scrollTo === "function") carousel.scrollTo({ left: 0 });
  }, [batch.request_id]);

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

  const explanationItem = batch.recommendations.find((item) => item.menu.menu_id === explanationMenuId) ?? null;

  return (
    <section className="v2-results" aria-labelledby="recommendation-results-title">
      <h2 id="recommendation-results-title" className="visually-hidden">
        {isFallback ? copy.searchFallbackTitle : copy.resultsTitle}
      </h2>
      {isFallback && (
        <div className="v2-bot-message">
          <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
          <div className="v2-bot-stack">
            <p className="v2-bot-name">{productCopy.assistantName}</p>
            <div className="v2-bubble">
              <p>{copy.searchFallbackTitle}</p>
              <p className="v2-bubble-sub">{copy.searchFallbackDescription}</p>
            </div>
          </div>
        </div>
      )}

      <div className="v2-bot-message">
        <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
        <div className="v2-bot-stack">
          <div
            ref={carouselRef}
            className="v2-card-carousel"
            role="region"
            tabIndex={0}
            aria-label={copy.resultsTitle}
            onScroll={(event) => {
              const element = event.currentTarget;
              setActiveIndex(carouselIndexFromOffset(element, batch.recommendations.length - 1));
            }}
          >
            {batch.recommendations.map((item, index) => {
              const spiceLevel = item.menu.spice_level;
              return (
                <article className="v2-alimtalk-card" key={item.menu.menu_id} data-testid={`menu-${item.menu.menu_id}`}>
                  <div className="v2-card-strip">
                    <span>{v2.yobiPick}</span>
                    <span>{v2.pickCount(index + 1, batch.recommendations.length)}</span>
                  </div>
                  <img className="v2-card-hero" src="/figma/menu-hero.png" alt="" />
                  <div className="v2-card-body">
                    <div className="v2-card-title-row">
                      <div>
                        <h3>{item.title || menuName(item.menu, language)}</h3>
                        <p>{menuName(item.menu, language)} · {item.menu.merchant_name}</p>
                      </div>
                      <strong>₩{item.menu.price.toLocaleString(locale)}</strong>
                    </div>
                    <p className="v2-card-reason">
                      {isFallback ? copy.searchFallbackDescription : item.selection_reason}
                    </p>
                    {(item.description || item.menu.cultural_description || item.menu.description) && (
                      <p className="v2-card-yogiyo">
                        <span>{v2.yogiyoLabel}</span> {item.description || item.menu.cultural_description || item.menu.description}
                      </p>
                    )}
                    <div className="v2-fact-chips">
                      <span>{item.menu.eta_min}–{item.menu.eta_max} min</span>
                      <span>{item.menu.delivery_fee ? `₩${item.menu.delivery_fee.toLocaleString(locale)}` : productCopy.freeDelivery}</span>
                      {spiceLevel == null
                        ? <span>{comparisonCopy.spiceUnverified}</span>
                        : <span className="success">{v2.spiceOk(spiceLevel)}</span>}
                      {item.halal_certified
                        ? <span className="success">{v2.halalYes}</span>
                        : <span className="warn">{v2.halalNo}</span>}
                      {item.vegan_status === "LIKELY_FIT" && <span className="success">{copy.veganLikely}</span>}
                      {item.vegan_status === "POSSIBLE_WITH_CHECKS" && <span className="warn">{copy.veganChecks}</span>}
                    </div>
                    {item.vegan_warning && <p className="v2-card-warning">{item.vegan_warning}</p>}
                    <button
                      type="button"
                      className="v2-card-secondary"
                      onClick={() => setExplanationMenuId(item.menu.menu_id)}
                    >
                      {v2.viewExplanation}
                    </button>
                    <button
                      type="button"
                      className="v2-card-primary"
                      disabled={busy || !batch.snapshot_id}
                      onClick={() => onChoose(item)}
                    >
                      {v2.chooseThisMenu}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
          {batch.recommendations.length > 1 && (
            <div className="v2-carousel-dots" aria-hidden="true">
              {batch.recommendations.map((item, index) => (
                <span className={activeIndex === index ? "active" : ""} key={item.menu.menu_id} />
              ))}
            </div>
          )}
          <p className="v2-timestamp">{timestamp}</p>
        </div>
      </div>

      {batch.recommendations.length > 1 && (
        <div className="v2-inline-replies">
          <button type="button" className="v2-quick-reply" onClick={() => void toggleComparison()} disabled={busy || comparisonLoading} aria-pressed={comparisonOpen}>
            {copy.compare}
          </button>
          {isFallback && (
            <button type="button" className="v2-quick-reply" onClick={onRetry} disabled={busy}>
              {copy.tryAgain}
            </button>
          )}
        </div>
      )}

      {comparisonOpen && (
        <div className="v2-bot-message">
          <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
          <div className="v2-bot-stack">
            <p className="v2-bot-name">{productCopy.assistantName}</p>
            <div className="v2-bubble" aria-live="polite">
              <p><strong>{productCopy.compareTitle}</strong></p>
              {comparisonLoading && <p className="v2-bubble-sub">{productCopy.compareLoading}</p>}
              {comparisonError && <p className="v2-bubble-sub error">{comparisonError}</p>}
              {comparison && (
                <>
                  <p className="v2-bubble-sub">{comparison.summary}</p>
                  <div className="v2-comparison-list">
                    {comparison.items.map((item) => (
                      <article key={item.menu_id}>
                        <h4>{item.name}</h4>
                        <p><strong>{comparisonCopy.keyDifference}</strong>{item.key_difference}</p>
                        <p><strong>{comparisonCopy.tasteTexture}</strong>{item.taste_texture}</p>
                        <p><strong>{comparisonCopy.ingredientsForm}</strong>{item.ingredients_form}</p>
                        <p><strong>{comparisonCopy.spiceHeaviness}</strong>{item.spice_heaviness}</p>
                        <p><strong>{comparisonCopy.eatingContext}</strong>{item.eating_context}</p>
                        <p><strong>{comparisonCopy.bestFor}</strong>{item.best_for}</p>
                        {item.unverified_dietary_info && (
                          <p className="caution"><strong>{comparisonCopy.needsVerification}</strong>{item.unverified_dietary_info}</p>
                        )}
                      </article>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <BottomSheet open={Boolean(explanationItem)} labelledBy="explanation-sheet-title" onClose={() => setExplanationMenuId(null)}>
        {explanationItem && (
          <div className="v2-explanation-sheet">
            <header>
              <h2 id="explanation-sheet-title">{v2.additionalExplanation}</h2>
              <p>{menuName(explanationItem.menu, language)} · {explanationItem.menu.merchant_name}</p>
            </header>
            <div className="v2-legend">
              <span className="warn">{v2.aiGenerated}</span>
            </div>
            <div className="v2-explanation-scroll">
              <div className="v2-explanation-block">
                <p>{explanationItem.description || explanationItem.menu.cultural_description || explanationItem.menu.description}</p>
                {explanationItem.matched_criteria.length > 0 && (
                  <ul>
                    {explanationItem.matched_criteria.map((match) => {
                      const labels = match.labels?.length
                        ? match.labels
                        : match.selected_value_codes.map((code) => valueLabels.get(code)).filter((label): label is string => Boolean(label));
                      return labels.length ? <li key={match.category_code}>{labels.join(" · ")}</li> : null;
                    })}
                  </ul>
                )}
              </div>
              {explanationItem.wiki_passages.length > 0 && (
                <div className="v2-explanation-block wiki">
                  <p className="v2-legend"><span className="success">{v2.wikiEvidence}</span></p>
                  {explanationItem.wiki_passages.map((passage, index) => (
                    <blockquote key={passage.chunk_id ?? passage.evidence_id ?? index}>{passage.content}</blockquote>
                  ))}
                </div>
              )}
              {explanationItem.halal_certified && explanationItem.halal_scope_label && (
                <p className="v2-explanation-note"><strong>{copy.halalScope}:</strong> {explanationItem.halal_scope_label}</p>
              )}
            </div>
            <button type="button" className="v2-text-button" onClick={() => setExplanationMenuId(null)}>
              {v2.gotIt}
            </button>
          </div>
        )}
      </BottomSheet>
    </section>
  );
}
