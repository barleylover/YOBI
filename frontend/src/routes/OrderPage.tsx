import { useEffect, useState } from "react";
import { CheckCircle2, Clock3, Hotel, MessageCircle, RotateCcw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";

export function OrderPage() {
  const { orderId = "" } = useParams();
  const [order, setOrder] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { api.getOrder(orderId).then(setOrder); }, [orderId]);
  if (!order) return <main className="center-page"><p>Confirming your mock order…</p></main>;
  return (
    <main className="order-complete-shell">
      <section className="order-complete-card">
        <div className="success-orbit"><CheckCircle2 size={42} /></div>
        <p className="eyebrow">Mock order confirmed</p><h1>Your first K-food order is in.</h1><p className="order-id">{orderId}</p>
        <div className="arrival-card"><Clock3 size={22} /><div><strong>Estimated arrival</strong><span>About 35 minutes · synthetic ETA</span></div></div>
        <div className="arrival-card"><Hotel size={22} /><div><strong>Handoff</strong><span>Leave with the YOBI Myeongdong Hotel front desk</span></div></div>
        <p className="demo-notice">Demo payment successful · no real restaurant or courier was contacted</p>
        <div className="button-row"><Link className="primary-button" to="/"><RotateCcw size={18} /> Start another order</Link><button className="secondary-button"><MessageCircle size={18} /> View conversation</button></div>
      </section>
    </main>
  );
}

