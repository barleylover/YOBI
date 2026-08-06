import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, CreditCard, LockKeyhole, XCircle } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Checkout } from "../types";

export function PaymentPage() {
  const { checkoutId = "" } = useParams();
  const navigate = useNavigate();
  const [checkout, setCheckout] = useState<Checkout | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => { api.getCheckout(checkoutId).then(setCheckout); }, [checkoutId]);

  async function pay(success: boolean) {
    setBusy(true);
    try {
      const updated = success ? await api.paymentSuccess(checkoutId) : await api.paymentFailure(checkoutId);
      setCheckout(updated);
      if (updated.status === "SUCCEEDED" && updated.order_id) navigate(`/order/${updated.order_id}`);
      else setMessage("Demo payment failed. Your cart is unchanged, so you can retry safely.");
    } finally { setBusy(false); }
  }

  if (!checkout) return <main className="center-page"><p>Loading secure demo checkout…</p></main>;
  return (
    <main className="payment-shell">
      <section className="payment-window">
        <header><Link to="/"><ArrowLeft size={19} /> YOBI</Link><span><LockKeyhole size={16} /> Mock secure checkout</span></header>
        <div className="payment-hero"><p className="eyebrow">External payment simulation</p><h1>Complete your demo order</h1><strong>₩{checkout.amount.toLocaleString()}</strong><p>Demo payment — no real charge</p></div>
        <div className="payment-method selected"><CreditCard size={24} /><div><strong>International card</strong><span>Demo Visa •••• 4242</span></div><CheckCircle2 size={20} /></div>
        <div className="payment-method disabled"><span className="pay-logo"></span><div><strong>Apple Pay demo</strong><span>Available in presentation mode</span></div></div>
        {message && <div className="payment-error"><XCircle size={18} />{message}</div>}
        <button className="primary-button full large" disabled={busy} onClick={() => void pay(true)}>Pay ₩{checkout.amount.toLocaleString()} · demo</button>
        <button className="text-button full" disabled={busy} onClick={() => void pay(false)}>Simulate failure</button>
        <p className="privacy-note"><LockKeyhole size={14} /> No card number, personal payment data, or real charge is processed.</p>
      </section>
    </main>
  );
}

