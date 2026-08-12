import { ArrowRight, MapPin, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

export function WelcomePage() {
  const navigate = useNavigate();
  useEffect(() => {
    document.documentElement.lang = "en";
    document.documentElement.dir = "ltr";
  }, []);
  return (
    <main className="welcome-shell">
      <section className="welcome-card">
        <header className="welcome-brand"><div className="brand-mark">YO<span>BI</span></div><span>K-FOOD CONCIERGE</span></header>
        <div className="welcome-content">
          <div className="welcome-hero">
            <div className="yobi-avatar" aria-hidden="true">Y</div>
            <h1>Hi, I’m YOBI!<span>Your Korean food buddy.</span></h1>
          </div>
          <section className="welcome-pitch">
            <h2>Order K-food with context, not guesswork.</h2>
            <p>Choose the cuisines, flavours, ingredients and food styles you want, then confirm where the food should arrive. YOBI uses those choices to prepare your recommendations.</p>
          </section>
          <div className="welcome-benefits">
            <span><Sparkles size={16} /> Understand flavour &amp; texture</span>
            <span><ShieldCheck size={16} /> Use halal &amp; vegan guidance</span>
            <span><MapPin size={16} /> Check delivery before choosing</span>
          </div>
        </div>
        <footer>
          <p>Restaurant and order information is prepared for this experience. No real order or charge is made.</p>
          <button className="primary-button welcome-cta" onClick={() => navigate("/start")}>Get started! <ArrowRight size={20} /></button>
        </footer>
      </section>
    </main>
  );
}
