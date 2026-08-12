import { useEffect, useState } from "react";
import { CheckCircle2, Clock3, Hotel, RotateCcw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { getRecommendationCopy } from "../lib/recommendationI18n";

export function OrderPage() {
  const { copy, journeyCopy, language } = useI18n();
  const recommendationCopy = getRecommendationCopy(language);
  const { orderId = "" } = useParams();
  const [order, setOrder] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { api.getOrder(orderId).then(setOrder); }, [orderId]);
  if (!order) return <main className="center-page"><p>{journeyCopy.loading}</p></main>;
  return (
    <main className="order-complete-shell">
      <section className="order-complete-card">
        <div className="success-orbit"><CheckCircle2 size={42} /></div>
        <h1>{copy.orderConfirmed}</h1><p className="order-id">{orderId}</p>
        <div className="arrival-card"><Clock3 size={22} /><div><strong>{copy.arrival}</strong><span>{journeyCopy.etaDemo.split(" · ")[0]}</span></div></div>
        <div className="arrival-card"><Hotel size={22} /><div><strong>{copy.handoff}</strong><span>{journeyCopy.frontDeskHandoff}</span></div></div>
        <p className="demo-notice">{recommendationCopy.experienceNotice}</p>
        <Link className="primary-button full" to="/"><RotateCcw size={18} /> {copy.anotherOrder}</Link>
      </section>
    </main>
  );
}
