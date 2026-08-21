import { useEffect, useRef, useState } from "react";
import type {
  RecommendationBatchV2,
  StructuredRecommendation,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
import type { RedesignCopy } from "../lib/redesignI18n";
import { asEffectiveLanguage, asSupportedLanguage, formatMinuteRange, menuName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { carouselIndexFromOffset } from "../lib/carouselScroll";
import { BottomSheet } from "./BottomSheet";

interface Props {
  batch: RecommendationBatchV2;
  /** Kept as an optional prop for callers restoring an older result component. */
  catalog?: unknown;
  copy: RecommendationCopy;
  v2: RedesignCopy;
  language: string;
  locale: string;
  busy?: boolean;
  readOnly?: boolean;
  timestamp: string;
  onChoose: (recommendation: StructuredRecommendation) => void;
  /** Comparison is intentionally no longer rendered in the v3 journey. */
  onCompare?: () => Promise<unknown>;
}

export function RecommendationResults({
  batch,
  copy,
  v2,
  language,
  locale,
  busy = false,
  readOnly = false,
  timestamp,
  onChoose,
}: Props) {
  const supportedLanguage = asSupportedLanguage(language);
  const productCopy = getProductCopy(supportedLanguage).recommendation;
  const carouselRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [explanationMenuId, setExplanationMenuId] = useState<string | null>(null);
  const isFallback = batch.status === "SEARCH_FALLBACK";
  const isUnderfilledStrictMatch = isFallback && batch.failure_code === "STRICT_MATCH_UNDERFILLED";
  const fallbackTitle = isUnderfilledStrictMatch ? copy.resultsTitle : copy.searchFallbackTitle;
  const fallbackDescription = isUnderfilledStrictMatch
    ? copy.noHiddenRelaxation
    : copy.searchFallbackDescription;

  useEffect(() => {
    setActiveIndex(0);
    setExplanationMenuId(null);
    const carousel = carouselRef.current;
    if (carousel && typeof carousel.scrollTo === "function") carousel.scrollTo({ left: 0 });
  }, [batch.request_id]);

  const explanationItem = batch.recommendations.find((item) => item.menu.menu_id === explanationMenuId) ?? null;

  return (
    <section
      className="v2-results"
      aria-labelledby="recommendation-results-title"
      data-testid="recommendation-results-message"
    >
      <h2 id="recommendation-results-title" className="visually-hidden">
        {isFallback ? fallbackTitle : copy.resultsTitle}
      </h2>
      {isFallback && (
        <div className="v2-bot-message">
          <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
          <div className="v2-bot-stack">
            <p className="v2-bot-name">{productCopy.assistantName}</p>
            <div className="v2-bubble">
              <p>{fallbackTitle}</p>
              <p className="v2-bubble-sub">{fallbackDescription}</p>
            </div>
          </div>
        </div>
      )}

      <div className="v2-bot-message">
        <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
        <div className="v2-bot-stack">
          <p className="v2-bot-name">{productCopy.assistantName}</p>
          <div className="v2-bubble v2-results-intro"><p>{v2.foundForYou}</p></div>
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
              const minimumOrderLabel = language === "한국어"
                ? "최소 주문"
                : language === "日本語"
                  ? "最低注文"
                  : "Minimum order";
              const sourceDescription = item.source_description
                || (asEffectiveLanguage(language) === "한국어" ? item.menu.description : "");
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
                        <h3>{item.localized_title || item.title || menuName(item.menu, language)}</h3>
                        {item.localized_subtitle && item.localized_subtitle !== item.localized_title && (
                          <small className="v2-card-subtitle">{item.localized_subtitle}</small>
                        )}
                        <p>{item.menu.merchant_name}</p>
                      </div>
                      <strong>₩{item.menu.price.toLocaleString(locale)}</strong>
                    </div>
                    {(item.yobi_short_explanation || item.description) && (
                      <p className="v2-card-yobi">
                        <span>{v2.yobiLabel}</span> {item.yobi_short_explanation || item.description}
                      </p>
                    )}
                    {sourceDescription && (
                      <p className="v2-card-yogiyo">
                        <span>{v2.yogiyoLabel}</span> {sourceDescription}
                      </p>
                    )}
                    <div className="v2-fact-chips">
                      <span>{formatMinuteRange(item.menu.eta_min, item.menu.eta_max, locale)}</span>
                      <span>{item.menu.delivery_fee ? `₩${item.menu.delivery_fee.toLocaleString(locale)}` : productCopy.freeDelivery}</span>
                      {Boolean(item.menu.minimum_order_amount) && (
                        <span>{minimumOrderLabel} ₩{item.menu.minimum_order_amount!.toLocaleString(locale)}</span>
                      )}
                      {spiceLevel != null && <span className="success">{v2.spiceOk(spiceLevel)}</span>}
                      {item.halal_certified
                        ? <span className="success">{v2.halalYes}</span>
                        : <span className="warn">{v2.halalNo}</span>}
                      {item.vegan_status === "LIKELY_FIT" && <span className="success">{copy.veganLikely}</span>}
                      {item.vegan_status === "POSSIBLE_WITH_CHECKS" && <span className="warn">{copy.veganChecks}</span>}
                    </div>
                    {item.vegan_warning && item.vegan_status !== "LIKELY_FIT" && (
                      <p className="v2-card-warning">{item.vegan_warning}</p>
                    )}
                    <button
                      type="button"
                      className="v2-card-secondary"
                      onClick={() => setExplanationMenuId(item.menu.menu_id)}
                    >
                      {v2.viewExplanation}
                    </button>
                    {!readOnly && (
                      <button
                        type="button"
                        className="v2-card-primary"
                        disabled={busy || !batch.snapshot_id}
                        onClick={() => onChoose(item)}
                      >
                        {v2.chooseThisMenu}
                      </button>
                    )}
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

      <BottomSheet open={Boolean(explanationItem)} labelledBy="explanation-sheet-title" onClose={() => setExplanationMenuId(null)}>
        {explanationItem && (
          <div className="v2-explanation-sheet">
            <header>
              <h2 id="explanation-sheet-title">{v2.additionalExplanation}</h2>
              <p>{explanationItem.localized_title || explanationItem.title || menuName(explanationItem.menu, language)} · {explanationItem.menu.merchant_name}</p>
              {explanationItem.localized_subtitle && explanationItem.localized_subtitle !== explanationItem.localized_title && (
                <small className="v2-explanation-subtitle">{explanationItem.localized_subtitle}</small>
              )}
            </header>
            <div className="v2-legend">
              <span className="warn">{v2.aiGenerated}</span>
            </div>
            <div className="v2-explanation-scroll">
              <div className="v2-explanation-block">
                <p className="v2-explanation-label">{v2.yobiLabel}</p>
                <p>{explanationItem.yobi_long_explanation || explanationItem.yobi_short_explanation || explanationItem.description}</p>
              </div>
              {explanationItem.country_preference && (
                <div className="v2-explanation-block preference">
                  <div className="v2-preference-heading">
                    <strong>{v2.countryPreference}</strong>
                    <span>{new Intl.DisplayNames([locale], { type: "region" }).of(explanationItem.country_preference.country_code)} · {explanationItem.country_preference.preference_percent}%</span>
                  </div>
                  <div className="v2-preference-bar" role="img" aria-label={`${explanationItem.country_preference.preference_percent}%`}>
                    <span style={{ width: `${explanationItem.country_preference.preference_percent}%` }} />
                  </div>
                  <small>{v2.sampleSize(explanationItem.country_preference.sample_size)}</small>
                </div>
              )}
              {explanationItem.review_summary && (
                <div className="v2-explanation-block">
                  <p className="v2-explanation-label">{v2.reviewSummary}</p>
                  <p>{explanationItem.review_summary}</p>
                </div>
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
