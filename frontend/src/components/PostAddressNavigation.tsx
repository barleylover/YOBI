import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Flame,
  ListOrdered,
  Star,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { actionableError, api } from "../lib/api";
import { getDynamicCopy } from "../lib/i18n";
import { asSupportedLanguage, menuName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import {
  carouselDeltaForArrow,
  carouselIndexFromOffset,
  carouselOffsetForIndex,
} from "../lib/carouselScroll";
import type {
  FeaturedMenuCollection,
  FoodRankingCollection,
  FoodRankingSort,
  MenuSummary,
} from "../types";

interface Props {
  sessionId: string;
  language: string;
  locale: string;
  disabled?: boolean;
  onChoose: (menu: MenuSummary, snapshotId: string) => void | Promise<void>;
}

type DiscoveryView = "rankings" | "feature" | null;

export function PostAddressNavigation({ sessionId, language, locale, disabled = false, onChoose }: Props) {
  const productCopy = getProductCopy(asSupportedLanguage(language));
  const dynamicCopy = getDynamicCopy(asSupportedLanguage(language));
  const copy = productCopy.navigation;
  const recommendationCopy = productCopy.recommendation;
  const navRef = useRef<HTMLElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const dialogCloseRef = useRef<HTMLButtonElement>(null);
  const carouselRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [view, setView] = useState<DiscoveryView>(null);
  const [sort, setSort] = useState<FoodRankingSort>("review_count");
  const [ranking, setRanking] = useState<FoodRankingCollection | null>(null);
  const [feature, setFeature] = useState<FeaturedMenuCollection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [featureIndex, setFeatureIndex] = useState(0);
  const localizedMetricLabel = sort === "review_count"
    ? copy.reviews
    : sort === "order_count"
      ? copy.orders
      : copy.koreanPopularity;

  useEffect(() => {
    function outside(event: PointerEvent) {
      if (view || !expanded || navRef.current?.contains(event.target as Node)) return;
      setExpanded(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        if (view) {
          setView(null);
          requestAnimationFrame(() => navRef.current?.querySelector<HTMLButtonElement>(".discovery-nav-toggle")?.focus());
        } else setExpanded(false);
        return;
      }
      if (event.key !== "Tab" || !view || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [expanded, view]);

  useEffect(() => {
    if (!view) return;
    requestAnimationFrame(() => dialogCloseRef.current?.focus());
  }, [view]);

  useEffect(() => {
    if (view !== "rankings") return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api.getFoodRankings(sessionId, sort, controller.signal)
      .then((result) => setRanking({ ...result, items: result.items.slice(0, 20) }))
      .catch((cause) => {
        if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
        setError(language === "English" ? actionableError(cause, copy.unavailable) : copy.unavailable);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [copy.unavailable, language, sessionId, sort, view]);

  useEffect(() => {
    if (view !== "feature") return;
    const controller = new AbortController();
    setFeatureIndex(0);
    setLoading(true);
    setError("");
    api.getKpopDemonHuntersFeature(sessionId, controller.signal)
      .then(setFeature)
      .catch((cause) => {
        if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
        setError(language === "English" ? actionableError(cause, copy.unavailable) : copy.unavailable);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [copy.unavailable, language, sessionId, view]);

  function closeDialog() {
    setView(null);
    requestAnimationFrame(() => navRef.current?.querySelector<HTMLButtonElement>(".discovery-nav-toggle")?.focus());
  }

  function moveFeature(next: number) {
    const itemCount = feature?.items.length ?? 0;
    if (!itemCount) return;
    const index = Math.max(0, Math.min(next, itemCount - 1));
    setFeatureIndex(index);
    const carousel = carouselRef.current;
    if (carousel && typeof carousel.scrollTo === "function") {
      carousel.scrollTo({ left: carouselOffsetForIndex(carousel, index), behavior: "smooth" });
    }
  }

  async function choose(menu: MenuSummary, snapshotId: string) {
    await onChoose(menu, snapshotId);
    closeDialog();
  }

  return (
    <>
      {view && <button type="button" className="discovery-backdrop" tabIndex={-1} aria-hidden="true" onClick={closeDialog} />}
      {view && (
        <section ref={dialogRef} className="discovery-dialog" role="dialog" aria-modal="true" aria-labelledby="discovery-title">
          <header>
            <div>
              <p className="eyebrow">{copy.expand.replace(/\s[+]$/, "")}</p>
              <h2 id="discovery-title">{view === "rankings" ? copy.foodRankings : copy.feature}</h2>
            </div>
            <button ref={dialogCloseRef} type="button" className="dialog-close" aria-label={copy.close} onClick={closeDialog}><X size={19} /></button>
          </header>

          {view === "rankings" && (
            <div className="ranking-view">
              <p className="demo-ranking-notice">{language === "English" ? (ranking?.demo_basis || copy.demoRankingNotice) : copy.demoRankingNotice}</p>
              <div className="ranking-sort-tabs" role="tablist" aria-label={copy.foodRankings}>
                {([
                  ["review_count", copy.reviews],
                  ["order_count", copy.orders],
                  ["korean_popularity", copy.koreanPopularity],
                ] as const).map(([value, label]) => (
                  <button key={value} type="button" role="tab" aria-selected={sort === value} className={sort === value ? "active" : ""} onClick={() => setSort(value)}>{label}</button>
                ))}
              </div>
              {loading && <p className="collection-state" role="status">{copy.loading}</p>}
              {error && <p className="collection-state error" role="alert">{error}</p>}
              {!loading && !error && (
                <ol className="food-ranking-list">
                  {(ranking?.items ?? []).map((entry) => (
                    <li key={entry.menu.menu_id}>
                      <span className="ranking-position">{entry.position}</span>
                      <div className="ranking-menu-copy">
                        <strong>{menuName(entry.menu, language)}</strong>
                        <small>{entry.menu.merchant_name}</small>
                        <p>{entry.menu.cultural_description || entry.menu.description || dynamicCopy.catalogDescription}</p>
                        <span>{language === "English" ? entry.metric_label : localizedMetricLabel}: {entry.metric_value.toLocaleString(locale)}</span>
                      </div>
                      <div className="ranking-menu-action">
                        <strong>₩{entry.menu.price.toLocaleString(locale)}</strong>
                        <button type="button" className="secondary-button" disabled={disabled || !ranking?.snapshot_id} onClick={() => void choose(entry.menu, ranking!.snapshot_id)}>{copy.selectMenu}</button>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}

          {view === "feature" && (
            <div className="feature-view">
              <img className="feature-hero" src="/yobi-gimbap-feature-hero.png" alt={copy.featureTitle} />
              <div className="feature-intro"><h3>{copy.featureTitle}</h3><p>{copy.featureDescription}</p></div>
              {loading && <p className="collection-state" role="status">{copy.loading}</p>}
              {error && <p className="collection-state error" role="alert">{error}</p>}
              {!loading && !error && feature?.items.length === 0 && <p className="collection-state">{copy.noFeatureMenus}</p>}
              {!loading && !error && Boolean(feature?.items.length) && (
                <>
                  <div className="feature-carousel-controls">
                    <button type="button" aria-label={recommendationCopy.previous} onClick={() => moveFeature(featureIndex - 1)} disabled={featureIndex === 0}><ChevronLeft size={18} /></button>
                    <span aria-live="polite">{featureIndex + 1} / {feature?.items.length}</span>
                    <button type="button" aria-label={recommendationCopy.next} onClick={() => moveFeature(featureIndex + 1)} disabled={featureIndex === (feature?.items.length ?? 1) - 1}><ChevronRight size={18} /></button>
                  </div>
                  <div
                    className="feature-carousel"
                    ref={carouselRef}
                    role="region"
                    tabIndex={0}
                    aria-label={copy.feature}
                    onKeyDown={(event) => {
                      const delta = carouselDeltaForArrow(event.currentTarget, event.key);
                      if (delta) {
                        event.preventDefault();
                        moveFeature(featureIndex + delta);
                      }
                    }}
                    onScroll={(event) => {
                      const element = event.currentTarget;
                      setFeatureIndex(carouselIndexFromOffset(element, (feature?.items.length ?? 1) - 1));
                    }}
                  >
                    {feature?.items.map((entry) => (
                      <article className="feature-menu-card" key={entry.menu.menu_id}>
                        <div className="feature-dish-tag"><Flame size={15} /> {entry.dish_name}</div>
                        <h3>{menuName(entry.menu, language)}</h3>
                        <small>{entry.menu.merchant_name}</small>
                        <p>{entry.description || entry.menu.cultural_description || entry.menu.description || dynamicCopy.catalogDescription}</p>
                        <div><strong>₩{entry.menu.price.toLocaleString(locale)}</strong><span>{entry.menu.eta_min}–{entry.menu.eta_max}′ · ₩{entry.menu.delivery_fee.toLocaleString(locale)} {recommendationCopy.deliveryFee}</span></div>
                        <button type="button" className="primary-button full" disabled={disabled || !feature?.snapshot_id} onClick={() => void choose(entry.menu, feature!.snapshot_id)}>{copy.selectMenu}</button>
                      </article>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </section>
      )}

      <nav ref={navRef} className={expanded ? "post-address-nav expanded" : "post-address-nav"} aria-label={copy.expand.replace(/\s[+]$/, "")}>
        {expanded && (
          <div className="discovery-nav-actions">
            <button type="button" onClick={() => setView("rankings")} disabled={disabled}><ListOrdered size={18} /> {copy.foodRankings}</button>
            <button type="button" onClick={() => setView("feature")} disabled={disabled}><Star size={18} /> {copy.feature}</button>
          </div>
        )}
        <button
          type="button"
          className="discovery-nav-toggle"
          aria-expanded={expanded}
          aria-label={expanded ? copy.collapse : copy.expand}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? <ChevronDown size={22} /> : <ChevronUp size={22} />}
        </button>
      </nav>
    </>
  );
}
