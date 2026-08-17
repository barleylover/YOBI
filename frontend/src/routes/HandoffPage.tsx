import { ArrowLeft, CheckCircle2, ExternalLink, ShoppingBag } from "lucide-react";
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
    <main className="handoff-shell">
      <section className="handoff-card">
        <header>
          <Link to={`/chat/${session.session_id}`}><ArrowLeft size={18} /> YOBI</Link>
          <span>{copy.cta} · {copy.eyebrow}</span>
        </header>

        {!ended ? (
          <>
            <div className="handoff-icon" aria-hidden="true"><ShoppingBag size={34} /></div>
            <p className="eyebrow">{copy.eyebrow}</p>
            <h1>{copy.title}</h1>
            <p className="handoff-lead">{copy.description}</p>
            <p>{copy.account}</p>

            {loading && <p className="collection-state" role="status">{journeyCopy.loading}</p>}
            {error && <p className="form-error" role="alert">{error}</p>}
            {cart && (
              <section className="handoff-cart-summary" aria-label={uiCopy.review}>
                <div><span>{journeyCopy.items}: {cart.items.length}</span><strong>₩{cart.total_price.toLocaleString(locale)}</strong></div>
                {cart.items.map((item) => <p key={item.cart_item_id}>{language === "한국어" ? item.menu_name_ko : item.menu_name} × {item.quantity}</p>)}
              </section>
            )}

            <button type="button" className="yogiyo-button" onClick={() => setEnded(true)} disabled={loading || !cart?.ready_to_checkout}>
              {copy.cta} <ExternalLink size={19} />
            </button>
            <p className="handoff-boundary">{copy.boundary}</p>
          </>
        ) : (
          <section className="handoff-ended" role="status">
            <div className="handoff-icon complete" aria-hidden="true"><CheckCircle2 size={38} /></div>
            <h1>{copy.done}</h1>
            <p>{copy.boundary}</p>
            <Link className="secondary-button full" to={`/chat/${session.session_id}`}>{copy.back}</Link>
          </section>
        )}
      </section>
    </main>
  );
}
