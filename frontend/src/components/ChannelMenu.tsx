import { useEffect, useState } from "react";
import { actionableError, api } from "../lib/api";
import {
  discoveryMenuForLanguage,
  KPOP_DEMO_DISHES,
  rankingExplanation,
} from "../lib/discoveryDemo";
import { getDynamicCopy } from "../lib/i18n";
import { asSupportedLanguage, formatMinuteRange, menuName, merchantName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getRedesignCopy } from "../lib/redesignI18n";
import type {
  FeaturedMenuCollection,
  FeaturedMenuEntry,
  FoodRankingCollection,
  FoodRankingSort,
  MenuSummary,
} from "../types";
import { BottomSheet } from "./BottomSheet";

interface Props {
  sessionId: string;
  language: string;
  locale: string;
  disabled?: boolean;
  onChoose: (menu: MenuSummary, snapshotId: string) => void | Promise<void>;
  onEditProfile: () => void;
}

type DiscoveryView = "rankings" | "feature" | null;

/** Figma screen 13 · Chat channel menu bar + expanded panel + discovery sheets. */
export function ChannelMenu({ sessionId, language, locale, disabled = false, onChoose, onEditProfile }: Props) {
  const supportedLanguage = asSupportedLanguage(language);
  const productCopy = getProductCopy(supportedLanguage);
  const dynamicCopy = getDynamicCopy(supportedLanguage);
  const v2 = getRedesignCopy(supportedLanguage);
  const copy = productCopy.navigation;
  const isEnglishDemo = supportedLanguage === "English";
  const [expanded, setExpanded] = useState(false);
  const [view, setView] = useState<DiscoveryView>(null);
  const [sort, setSort] = useState<FoodRankingSort>("review_count");
  const [ranking, setRanking] = useState<FoodRankingCollection | null>(null);
  const [feature, setFeature] = useState<FeaturedMenuCollection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [rankingReload, setRankingReload] = useState(0);
  const [featureReload, setFeatureReload] = useState(0);
  const [choosingMenuId, setChoosingMenuId] = useState<string | null>(null);
  const minimumOrderLabel = language === "한국어" ? "최소 주문" : language === "日本語" ? "最低注文" : "Minimum order";

  useEffect(() => {
    if (view !== "rankings") return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api.getFoodRankings(sessionId, sort, controller.signal, isEnglishDemo ? 10 : 20)
      .then((result) => setRanking({
        ...result,
        items: result.items.slice(0, isEnglishDemo ? 10 : 20),
      }))
      .catch((cause) => {
        if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
        setError(actionableError(cause, copy.unavailable, language));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [copy.unavailable, isEnglishDemo, language, rankingReload, sessionId, sort, view]);

  useEffect(() => {
    if (view !== "feature") return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api.getKpopDemonHuntersFeature(sessionId, controller.signal)
      .then(setFeature)
      .catch((cause) => {
        if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
        setError(actionableError(cause, copy.unavailable, language));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [copy.unavailable, featureReload, language, sessionId, view]);

  async function choose(menu: MenuSummary, snapshotId: string, dishName = "") {
    const displayMenu = discoveryMenuForLanguage(menu, dishName, language);
    setChoosingMenuId(menu.menu_id);
    setError("");
    try {
      await onChoose(displayMenu, snapshotId);
      setView(null);
      setExpanded(false);
    } catch (cause) {
      setError(actionableError(cause, copy.unavailable, language));
    } finally {
      setChoosingMenuId(null);
    }
  }

  const featureSlots: Array<{
    key: string;
    entry?: FeaturedMenuEntry;
    story?: (typeof KPOP_DEMO_DISHES)[number];
  }> = isEnglishDemo
    ? KPOP_DEMO_DISHES.map((story) => ({
        key: story.dishName,
        story,
        entry: feature?.items.find((item) => item.dish_name === story.dishName),
      }))
    : (feature?.items ?? []).map((entry) => ({ key: entry.menu.menu_id, entry }));

  return (
    <>
      <div className="v2-menu-bar">
        {!expanded && (
          <button type="button" className="v2-menu-toggle" aria-expanded={false} onClick={() => setExpanded(true)}>
            {v2.menuBar}
            <img src="/figma/up-chevron.svg" alt="" width={12} height={6} />
          </button>
        )}
        {expanded && (
          <div className="v2-menu-panel">
            <button type="button" className="v2-menu-collapse" aria-expanded onClick={() => setExpanded(false)}>
              {v2.menuBar}
              <img src="/figma/down-chevron-white.svg" alt="" width={12} height={6} />
            </button>
            <button type="button" className="v2-menu-item" onClick={onEditProfile} disabled={disabled}>
              <img src="/figma/icon-person.svg" alt="" width={28} height={28} />
              <span>{v2.editMyInfo}</span>
            </button>
            <div className="v2-menu-row">
              <button type="button" className="v2-menu-item half" onClick={() => setView("rankings")} disabled={disabled}>
                <span className="bars" aria-hidden="true"><i /><i /><i /></span>
                <span>{copy.foodRankings}</span>
              </button>
              <button type="button" className="v2-menu-item tile" onClick={() => setView("feature")} disabled={disabled}>
                <img src="/figma/kdh-tile.png" alt="" />
                <span className="tile-label">{isEnglishDemo ? "KPOP DEMON HUNTERS" : "K-POP ANIMATION"}</span>
              </button>
            </div>
          </div>
        )}
      </div>

      <BottomSheet open={view === "rankings"} labelledBy="discovery-rankings-title" onClose={() => setView(null)}>
        <div className={`v2-discovery-sheet${isEnglishDemo ? " v2-rankings-demo" : ""}`}>
          <header>
            {isEnglishDemo && <span className="v2-discovery-kicker">Prepared weekly discovery</span>}
            <h2 id="discovery-rankings-title">{isEnglishDemo ? "Food Rankings · Top 10" : copy.foodRankings}</h2>
            <p>{isEnglishDemo ? "Ten varied, orderable menus for this demo delivery area." : copy.demoRankingNotice}</p>
          </header>
          {isEnglishDemo && (
            <div className="v2-demo-boundary" role="note">
              <strong>Demo ranking</strong>
              <span>{rankingExplanation(sort)} Merchant and dish diversity prevents one restaurant from filling the list.</span>
            </div>
          )}
          <div className="v2-seg-tabs" role="tablist" aria-label={copy.foodRankings}>
            {([
              ["review_count", copy.reviews],
              ["order_count", copy.orders],
              ["korean_popularity", copy.koreanPopularity],
            ] as const).map(([value, label]) => (
              <button key={value} type="button" role="tab" aria-selected={sort === value} onClick={() => setSort(value)}>{label}</button>
            ))}
          </div>
          <div className="v2-discovery-scroll">
            {loading && (isEnglishDemo ? (
              <div className="v2-collection-loading" role="status" aria-label={copy.loading}>
                <span /><span /><span />
              </div>
            ) : <p className="v2-status" role="status">{copy.loading}</p>)}
            {error && (isEnglishDemo ? (
              <div className="v2-collection-error" role="alert">
                <p>{error}</p>
                <button type="button" onClick={() => setRankingReload((value) => value + 1)}>Try again</button>
              </div>
            ) : <p className="v2-error" role="alert">{error}</p>)}
            {!loading && !error && isEnglishDemo && (ranking?.items.length ?? 0) === 0 && (
              <p className="v2-status">No ranked menu fits the current filters.</p>
            )}
            {!loading && !error && (!isEnglishDemo || Boolean(ranking?.items.length)) && (
              <ol className="v2-ranking-list">
                {(ranking?.items ?? []).map((entry) => {
                  const displayMenu = discoveryMenuForLanguage(entry.menu, entry.dish_name ?? "", language);
                  return (
                    <li key={entry.menu.menu_id}>
                      <span className="rank" aria-label={isEnglishDemo ? `Rank ${entry.position}` : undefined}>{entry.position}</span>
                      <div>
                        {isEnglishDemo && entry.dish_name && <span className="v2-concept-chip">{entry.dish_name}</span>}
                        <strong>{menuName(displayMenu, language)}</strong>
                        <small>{merchantName(entry.menu.merchant_name, language)}{entry.menu.minimum_order_amount ? ` · ${minimumOrderLabel} ₩${entry.menu.minimum_order_amount.toLocaleString(locale)}` : ""}</small>
                        <p>{entry.menu.cultural_description || entry.menu.description || dynamicCopy.catalogDescription}</p>
                      </div>
                      <div className="action">
                        <strong>₩{entry.menu.price.toLocaleString(locale)}</strong>
                        <button
                          type="button"
                          className="v2-search-submit"
                          disabled={disabled || (isEnglishDemo && choosingMenuId !== null) || !ranking?.snapshot_id}
                          title={!ranking?.snapshot_id ? copy.unavailable : undefined}
                          onClick={() => void choose(displayMenu, ranking!.snapshot_id, entry.dish_name)}
                        >
                          {choosingMenuId === entry.menu.menu_id && isEnglishDemo ? "Opening…" : copy.selectMenu}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
          <button type="button" className="v2-text-button" onClick={() => setView(null)}>{copy.close}</button>
        </div>
      </BottomSheet>

      <BottomSheet open={view === "feature"} labelledBy="discovery-feature-title" onClose={() => setView(null)}>
        <div className={`v2-discovery-sheet${isEnglishDemo ? " v2-kpop-demo" : ""}`}>
          <header>
            {isEnglishDemo && <span className="v2-discovery-kicker">From screen to a nearby menu</span>}
            <h2 id="discovery-feature-title">{isEnglishDemo ? "KPop Demon Hunters · K-food trail" : copy.featureTitle}</h2>
            <p>{isEnglishDemo ? "Five film foods, their Korean-food context, and an orderable match when this area has one." : copy.featureDescription}</p>
          </header>
          {isEnglishDemo && (
            <div className="v2-kpop-hero">
              <img
                src="/yobi-gimbap-feature-hero.png"
                alt="Korean dishes arranged for the KPop Demon Hunters food trail"
                width={1536}
                height={1024}
              />
              <div><span>1 · See it</span><span>2 · Learn it</span><span>3 · Pick nearby</span></div>
            </div>
          )}
          {isEnglishDemo && (
            <div className="v2-demo-boundary kpop" role="note">
              <strong>Story reference</strong>
              <span>
                <a href="https://www.netflix.com/tudum/articles/kpop-demon-hunters-food-guide" target="_blank" rel="noreferrer">
                  Netflix Tudum official food guide
                </a>
                . Film-food notes are general context, not a restaurant recipe claim.
              </span>
            </div>
          )}
          <div className="v2-discovery-scroll">
            {loading && (isEnglishDemo ? (
              <div className="v2-collection-loading" role="status" aria-label={copy.loading}>
                <span /><span /><span />
              </div>
            ) : <p className="v2-status" role="status">{copy.loading}</p>)}
            {error && (isEnglishDemo ? (
              <div className="v2-collection-error" role="alert">
                <p>{error}</p>
                <button type="button" onClick={() => setFeatureReload((value) => value + 1)}>Try again</button>
              </div>
            ) : <p className="v2-error" role="alert">{error}</p>)}
            {!loading && !error && !isEnglishDemo && feature?.items.length === 0 && <p className="v2-status">{copy.noFeatureMenus}</p>}
            {!loading && !error && (isEnglishDemo || Boolean(feature?.items.length)) && (
              <div className="v2-feature-list">
                {featureSlots.map(({ key, entry, story }, index) => {
                  const displayMenu = entry
                    ? discoveryMenuForLanguage(entry.menu, entry.dish_name, language)
                    : null;
                  return (
                    <article key={key} className={!entry ? "unavailable" : undefined}>
                      <div className="v2-feature-heading">
                        <span className="dish-tag">{story?.dishName ?? entry?.dish_name}</span>
                        {isEnglishDemo && <em>{index + 1} / {KPOP_DEMO_DISHES.length}</em>}
                      </div>
                      {story && <small className="v2-screen-label">{story.screenLabel}</small>}
                      {story && <p className="v2-film-story">{story.story}</p>}
                      {story && <p className="v2-food-note"><strong>What it is</strong>{story.foodNote}</p>}
                      {entry && displayMenu ? (
                        <div className="v2-nearby-match">
                          {isEnglishDemo && <span>Available nearby</span>}
                          <strong>{menuName(displayMenu, language)}</strong>
                          <small>{merchantName(entry.menu.merchant_name, language)}{entry.menu.minimum_order_amount ? ` · ${minimumOrderLabel} ₩${entry.menu.minimum_order_amount.toLocaleString(locale)}` : ""}</small>
                          {!story && <p>{entry.description || entry.menu.cultural_description || entry.menu.description || dynamicCopy.catalogDescription}</p>}
                          <div className="meta">
                            <strong>₩{entry.menu.price.toLocaleString(locale)}</strong>
                            <span>{v2.estimatedArrival} · {formatMinuteRange(entry.menu.eta_min, entry.menu.eta_max, locale)} · {productCopy.recommendation.deliveryFee} · ₩{entry.menu.delivery_fee.toLocaleString(locale)}</span>
                          </div>
                          <button
                            type="button"
                            className="v2-card-primary"
                            disabled={disabled || (isEnglishDemo && choosingMenuId !== null) || !feature?.snapshot_id}
                            title={!feature?.snapshot_id ? copy.unavailable : undefined}
                            onClick={() => void choose(displayMenu, feature!.snapshot_id, entry.dish_name)}
                          >
                            {choosingMenuId === entry.menu.menu_id && isEnglishDemo ? "Opening…" : copy.selectMenu}
                          </button>
                        </div>
                      ) : (
                        <div className="v2-nearby-empty">
                          <strong>Not available in this demo area</strong>
                          <span>YOBI keeps the film-food slot visible and does not substitute an unrelated menu.</span>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </div>
          <button type="button" className="v2-text-button" onClick={() => setView(null)}>{copy.close}</button>
        </div>
      </BottomSheet>
    </>
  );
}
