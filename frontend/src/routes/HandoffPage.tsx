import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { asSupportedLanguage } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getRedesignCopy } from "../lib/redesignI18n";
import { useSessionStore } from "../stores/session";
import type { CartPreview } from "../types";

export function HandoffPage() {
  const navigate = useNavigate();
  const { language, locale, journeyCopy } = useI18n();
  const supportedLanguage = asSupportedLanguage(language);
  const productCopy = getProductCopy(supportedLanguage);
  const copy = productCopy.handoff;
  const v2 = getRedesignCopy(supportedLanguage);
  const session = useSessionStore((state) => state.session);
  const addressRefId = useSessionStore((state) => state.addressRefId);
  const addressSummary = useSessionStore((state) => state.addressSummary);
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    setLoading(true);
    api.getCart(session.session_id, controller.signal)
      .then(setCart)
      .catch((cause) => {
        if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
        setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [journeyCopy.retry, language, session]);

  if (!session || !addressRefId) return <Navigate to="/" replace />;

  const won = (value: number) => `₩${value.toLocaleString(locale)}`;
  const itemCount = cart?.items.reduce((total, item) => total + item.quantity, 0) ?? 0;
  const firstItemName = cart?.items[0]
    ? (language === "한국어" ? cart.items[0].menu_name_ko : cart.items[0].menu_name)
    : "";

  return (
    <main className="v2-screen subtle v2-handoff">
      <header className="v2-handoff-header">
        <div className="row">
          <button
            type="button"
            className="v2-icon-button light"
            aria-label={copy.back}
            onClick={() => navigate(`/chat/${session.session_id}`)}
          >
            <img src="/figma/back-chevron-white.svg" alt="" width={9} height={16} />
          </button>
          <div className="titles">
            <h1>{ended ? copy.done.split(".")[0] : v2.readyToOrder}</h1>
            <p>{cart ? v2.itemsSummary(itemCount, firstItemName) : copy.eyebrow}</p>
          </div>
          <img src="/figma/logo-mark.svg" alt="" width={38} height={38} style={{ borderRadius: 12 }} />
        </div>
      </header>

      <div className="v2-body" style={{ gap: 12, paddingTop: 16 }}>
        {loading && <p className="v2-status" role="status">{journeyCopy.loading}</p>}
        {error && <p className="v2-error" role="alert">{error}</p>}

        {!ended && cart && (
          <section className="v2-summary-card" aria-label={v2.yourMenu}>
            {cart.items.map((item) => (
              <div key={item.cart_item_id}>
                <div className="v2-summary-line">
                  <div>
                    <strong>{language === "한국어" ? item.menu_name_ko : item.menu_name} ×{item.quantity}</strong>
                    <small>{item.options.map((option) => language === "한국어" ? option.name_ko : option.name_en).join(" · ") || journeyCopy.included}</small>
                  </div>
                  <strong>{won(item.line_total)}</strong>
                </div>
                <div className="v2-divider" />
              </div>
            ))}
            <div className="v2-price-row"><span>{v2.subtotal}</span><strong>{won(cart.subtotal)}</strong></div>
            <div className="v2-price-row"><span>{productCopy.recommendation.deliveryFee}</span><strong>{won(cart.delivery_fee)}</strong></div>
            <div className="v2-price-row total big"><span>{journeyCopy.total}</span><strong>{won(cart.total_price)}</strong></div>
          </section>
        )}

        {!ended && (
          <section className="v2-summary-card address" aria-label={v2.deliverTo}>
            <img src="/figma/logo-mark.svg" alt="" width={38} height={38} style={{ borderRadius: 12, opacity: 0.9 }} />
            <div>
              <strong>{addressSummary.split(" · ")[0]}</strong>
              <small>{addressSummary.split(" · ").slice(1).join(" · ")}</small>
            </div>
            <Link to={`/profile?edit=1&returnTo=/handoff`}>{v2.editChip}</Link>
          </section>
        )}

        {!ended && (
          <div className="v2-demo-warning standalone">
            <span aria-hidden="true">!</span>
            <p>{v2.handoffDemoNotice}</p>
          </div>
        )}

        {ended && (
          <section className="v2-summary-card" role="status">
            <p style={{ margin: 0, fontSize: 15, lineHeight: 1.5 }}>{copy.done}</p>
            <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>{copy.boundary}</p>
          </section>
        )}
      </div>

      <footer className="v2-cta-footer" style={{ background: "var(--surface-base)" }}>
        {!ended ? (
          <>
            <button
              type="button"
              className="v2-cta"
              style={{ borderRadius: 17 }}
              onClick={() => setEnded(true)}
              disabled={loading || !cart?.ready_to_checkout}
            >
              {v2.openInYogiyo} ↗
            </button>
            <button
              type="button"
              className="v2-cta secondary"
              style={{ borderRadius: 17, background: "var(--surface-base)", border: "1px solid var(--surface-border)" }}
              onClick={() => navigate(`/chat/${session.session_id}`)}
            >
              {v2.backToMenus}
            </button>
          </>
        ) : (
          <Link
            className="v2-cta secondary"
            style={{ borderRadius: 17, textDecoration: "none" }}
            to={`/chat/${session.session_id}`}
          >
            {copy.back}
          </Link>
        )}
      </footer>
    </main>
  );
}
