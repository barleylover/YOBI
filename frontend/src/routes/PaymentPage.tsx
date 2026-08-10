import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, CreditCard, LockKeyhole, XCircle } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSessionStore } from "../stores/session";
import type { Checkout } from "../types";

export function PaymentPage() {
  const { copy, journeyCopy } = useI18n();
  const { checkoutId = "" } = useParams();
  const navigate = useNavigate();
  const session = useSessionStore((state) => state.session);
  const [checkout, setCheckout] = useState<Checkout | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [requiresCartReview, setRequiresCartReview] = useState(false);

  useEffect(() => { api.getCheckout(checkoutId).then(setCheckout); }, [checkoutId]);

  async function pay(success: boolean) {
    setBusy(true);
    setMessage("");
    setRequiresCartReview(false);
    try {
      const updated = success ? await api.paymentSuccess(checkoutId) : await api.paymentFailure(checkoutId);
      setCheckout(updated);
      if (updated.status === "SUCCEEDED" && updated.order_id) navigate(`/order/${updated.order_id}`);
      else setMessage(journeyCopy.paymentFailed);
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      setRequiresCartReview([
        "CHECKOUT_STALE",
        "CART_CHANGED_RECONFIRM_REQUIRED",
        "CART_NOT_CONFIRMED",
        "IDEMPOTENCY_KEY_REUSED",
      ].includes(code));
      setMessage(actionableError(cause, journeyCopy.retry));
    } finally { setBusy(false); }
  }

  if (!checkout) return <main className="center-page"><p>{journeyCopy.loading}</p></main>;
  return (
    <main className="payment-shell">
      <section className="payment-window">
        <header><Link to="/"><ArrowLeft size={19} /> YOBI</Link><span><LockKeyhole size={16} /> {journeyCopy.secureCheckout}</span></header>
        <div className="payment-hero"><p className="eyebrow">{journeyCopy.paymentSimulation}</p><h1>{copy.paymentTitle}</h1><strong>₩{checkout.amount.toLocaleString()}</strong><p>{copy.demoPayment}</p></div>
        <div className="payment-method selected"><CreditCard size={24} /><div><strong>{journeyCopy.internationalCard}</strong><span>Visa •••• 4242</span></div><CheckCircle2 size={20} /></div>
        <div className="payment-method disabled"><span className="pay-logo"></span><div><strong>{journeyCopy.applePayDemo}</strong><span>{journeyCopy.presentationAvailable}</span></div></div>
        {message && <div className="payment-error"><XCircle size={18} />{message}</div>}
        {requiresCartReview && <Link className="text-button full" to={session ? `/chat/${session.session_id}` : "/"}>{journeyCopy.openCart}</Link>}
        <button className="primary-button full large" disabled={busy} onClick={() => void pay(true)}>{copy.pay} ₩{checkout.amount.toLocaleString()}</button>
        <button className="text-button full" disabled={busy} onClick={() => void pay(false)}>{copy.simulateFailure}</button>
        <p className="privacy-note"><LockKeyhole size={14} /> {journeyCopy.privacy}</p>
      </section>
    </main>
  );
}
