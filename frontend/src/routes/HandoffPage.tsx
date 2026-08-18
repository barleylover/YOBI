import { ArrowLeft, CheckCircle2, ExternalLink, Info, MapPin, ShoppingBag } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { asSupportedLanguage } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { useSessionStore } from "../stores/session";
import type { CartPreview } from "../types";

export function HandoffPage() {
  const { language, locale, journeyCopy, copy: uiCopy } = useI18n();
  const copy = getProductCopy(asSupportedLanguage(language)).handoff;
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

  return (
    <main className="yv2-cart-shell">
      <section className="yv2-cart-card">
        <header className="yv2-page-header">
          <Link className="yv2-icon-button" aria-label={copy.back} to={`/chat/${session.session_id}`}><ArrowLeft size={20} /></Link>
          <h1>{uiCopy.readyCheckout}</h1>
          <span className="yv2-cart-header-icon"><ShoppingBag size={19} /></span>
        </header>

        {!ended ? (
          <>
            <div className="yv2-cart-content">
              <header className="yv2-screen-title">
                <p className="yv2-eyebrow">{copy.eyebrow}</p>
                <h1>{copy.title}</h1>
                <p>{copy.description}</p>
              </header>

              {loading && <p className="collection-state" role="status">{journeyCopy.loading}</p>}
              {error && <p className="yv2-error-banner" role="alert">{error}</p>}
              {cart && (
                <>
                  <section className="handoff-cart-summary yv2-cart-items" aria-label={uiCopy.review}>
                    {cart.items.map((item) => (
                      <article key={item.cart_item_id}>
                        <span className="yv2-cart-item-art"><ShoppingBag size={18} /></span>
                        <div>
                          <strong>{language === "한국어" ? item.menu_name_ko : item.menu_name}</strong>
                          <small>{item.options.map((option) => language === "한국어" ? option.name_ko : option.name_en).join(" · ") || copy.account}</small>
                          <span>× {item.quantity}</span>
                        </div>
                        <strong>₩{item.line_total.toLocaleString(locale)}</strong>
                      </article>
                    ))}
                  </section>

                  <section className="yv2-cart-address">
                    <MapPin size={18} />
                    <div><span>{uiCopy.delivery}</span><strong>{addressSummary}</strong></div>
                  </section>

                  <section className="yv2-cart-totals">
                    <div><span>{journeyCopy.items}</span><span>₩{cart.subtotal.toLocaleString(locale)}</span></div>
                    <div><span>{uiCopy.delivery}</span><span>₩{cart.delivery_fee.toLocaleString(locale)}</span></div>
                    <div><strong>{journeyCopy.total}</strong><strong>₩{cart.total_price.toLocaleString(locale)}</strong></div>
                  </section>
                </>
              )}

              <aside className="yv2-info-banner"><Info size={17} /><span>{copy.boundary}</span></aside>
            </div>

            <footer className="yv2-cart-actions">
              <button type="button" className="yv2-primary-button yogiyo-button" onClick={() => setEnded(true)} disabled={loading || !cart?.ready_to_checkout}>
                {copy.cta} <ExternalLink size={18} />
              </button>
              <Link to={`/chat/${session.session_id}`}>{copy.back}</Link>
            </footer>
          </>
        ) : (
          <section className="yv2-handoff-ended" role="status">
            <span><CheckCircle2 size={40} /></span>
            <h1>{copy.done}</h1>
            <p>{copy.boundary}</p>
            <Link className="yv2-secondary-button" to={`/chat/${session.session_id}`}>{copy.back}</Link>
          </section>
        )}
      </section>
    </main>
  );
}
