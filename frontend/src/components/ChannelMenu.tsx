import { useEffect, useState } from "react";
import { actionableError, api } from "../lib/api";
import { getDynamicCopy } from "../lib/i18n";
import { asSupportedLanguage, formatMinuteRange, menuName, merchantName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getRedesignCopy } from "../lib/redesignI18n";
import type {
  FeaturedMenuCollection,
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
  const [expanded, setExpanded] = useState(false);
  const [view, setView] = useState<DiscoveryView>(null);
  const [sort, setSort] = useState<FoodRankingSort>("review_count");
  const [ranking, setRanking] = useState<FoodRankingCollection | null>(null);
  const [feature, setFeature] = useState<FeaturedMenuCollection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const localizedMetricLabel = sort === "review_count"
    ? copy.reviews
    : sort === "order_count"
      ? copy.orders
      : copy.koreanPopularity;
  const minimumOrderLabel = language === "한국어" ? "최소 주문" : language === "日本語" ? "最低注文" : "Minimum order";

  useEffect(() => {
    if (view !== "rankings") return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api.getFoodRankings(sessionId, sort, controller.signal)
      .then((result) => setRanking({ ...result, items: result.items.slice(0, 20) }))
      .catch((cause) => {
        if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
        setError(actionableError(cause, copy.unavailable, language));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [copy.unavailable, language, sessionId, sort, view]);

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
  }, [copy.unavailable, language, sessionId, view]);

  async function choose(menu: MenuSummary, snapshotId: string) {
    await onChoose(menu, snapshotId);
    setView(null);
    setExpanded(false);
  }

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
                <span className="tile-label">K-POP ANIMATION</span>
              </button>
            </div>
          </div>
        )}
      </div>

      <BottomSheet open={view === "rankings"} labelledBy="discovery-rankings-title" onClose={() => setView(null)}>
        <div className="v2-discovery-sheet">
          <header>
            <h2 id="discovery-rankings-title">{copy.foodRankings}</h2>
            <p>{copy.demoRankingNotice}</p>
          </header>
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
            {loading && <p className="v2-status" role="status">{copy.loading}</p>}
            {error && <p className="v2-error" role="alert">{error}</p>}
            {!loading && !error && (
              <ol className="v2-ranking-list">
                {(ranking?.items ?? []).map((entry) => (
                  <li key={entry.menu.menu_id}>
                    <span className="rank">{entry.position}</span>
                    <div>
                      <strong>{menuName(entry.menu, language)}</strong>
                      <small>{merchantName(entry.menu.merchant_name, language)}{entry.menu.minimum_order_amount ? ` · ${minimumOrderLabel} ₩${entry.menu.minimum_order_amount.toLocaleString(locale)}` : ""}</small>
                      <p>{entry.menu.cultural_description || entry.menu.description || dynamicCopy.catalogDescription}</p>
                      <em>{language === "English" ? entry.metric_label : localizedMetricLabel}: {entry.metric_value.toLocaleString(locale)}</em>
                    </div>
                    <div className="action">
                      <strong>₩{entry.menu.price.toLocaleString(locale)}</strong>
                      <button
                        type="button"
                        className="v2-search-submit"
                        disabled={disabled || !ranking?.snapshot_id}
                        onClick={() => void choose(entry.menu, ranking!.snapshot_id)}
                      >
                        {copy.selectMenu}
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <button type="button" className="v2-text-button" onClick={() => setView(null)}>{copy.close}</button>
        </div>
      </BottomSheet>

      <BottomSheet open={view === "feature"} labelledBy="discovery-feature-title" onClose={() => setView(null)}>
        <div className="v2-discovery-sheet">
          <header>
            <h2 id="discovery-feature-title">{copy.featureTitle}</h2>
            <p>{copy.featureDescription}</p>
          </header>
          <div className="v2-discovery-scroll">
            {loading && <p className="v2-status" role="status">{copy.loading}</p>}
            {error && <p className="v2-error" role="alert">{error}</p>}
            {!loading && !error && feature?.items.length === 0 && <p className="v2-status">{copy.noFeatureMenus}</p>}
            {!loading && !error && Boolean(feature?.items.length) && (
              <div className="v2-feature-list">
                {feature?.items.map((entry) => (
                  <article key={entry.menu.menu_id}>
                    <span className="dish-tag">{entry.dish_name}</span>
                    <strong>{menuName(entry.menu, language)}</strong>
                    <small>{merchantName(entry.menu.merchant_name, language)}{entry.menu.minimum_order_amount ? ` · ${minimumOrderLabel} ₩${entry.menu.minimum_order_amount.toLocaleString(locale)}` : ""}</small>
                    <p>{entry.description || entry.menu.cultural_description || entry.menu.description || dynamicCopy.catalogDescription}</p>
                    <div className="meta">
                      <strong>₩{entry.menu.price.toLocaleString(locale)}</strong>
                      <span>{formatMinuteRange(entry.menu.eta_min, entry.menu.eta_max, locale)} · ₩{entry.menu.delivery_fee.toLocaleString(locale)}</span>
                    </div>
                    <button
                      type="button"
                      className="v2-card-primary"
                      disabled={disabled || !feature?.snapshot_id}
                      onClick={() => void choose(entry.menu, feature!.snapshot_id)}
                    >
                      {copy.selectMenu}
                    </button>
                  </article>
                ))}
              </div>
            )}
          </div>
          <button type="button" className="v2-text-button" onClick={() => setView(null)}>{copy.close}</button>
        </div>
      </BottomSheet>
    </>
  );
}
