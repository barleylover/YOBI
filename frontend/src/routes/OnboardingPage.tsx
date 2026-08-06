import { FormEvent, useState } from "react";
import { ArrowRight, Check, ShieldCheck, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useSessionStore } from "../stores/session";

export function OnboardingPage() {
  const navigate = useNavigate();
  const setContext = useSessionStore((state) => state.setContext);
  const [spice, setSpice] = useState(1);
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const profile = await api.createProfile({
        preferred_language: "English",
        nationality: "United States",
        age_band: "25-34",
        gender: "Prefer not to say",
        religion_selection: "No specific religion",
        dietary_rules: ["shellfish_allergy"],
        allergy_severity: "severe",
        spice_tolerance: spice,
        favorite_foods: ["creamy pasta", "chicken noodle soup"],
        consent_demo_data: consent,
        remember_profile: false,
      });
      const session = await api.createSession(profile.profile_id);
      setContext(profile, session);
      navigate(`/chat/${session.session_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start the demo");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="onboarding-shell">
      <section className="onboarding-intro">
        <div className="brand-mark">YO<span>BI</span></div>
        <p className="eyebrow">Your Korean food buddy</p>
        <h1>Order K-food with context, not guesswork.</h1>
        <p className="intro-copy">
          Tell YOBI what you remember, crave, or need to avoid. It explains the food,
          checks synthetic evidence, and helps you build a mock order in English.
        </p>
        <div className="benefit-list">
          <span><Sparkles size={18} /> Understand flavour and texture</span>
          <span><ShieldCheck size={18} /> See risk and unknown evidence clearly</span>
          <span><Check size={18} /> Confirm every action before payment</span>
        </div>
        <p className="demo-notice">Demo service · synthetic restaurants · no real charge</p>
      </section>

      <form className="onboarding-card" onSubmit={submit}>
        <div className="step-label">A few basics before we chat</div>
        <h2>Make the first answer useful.</h2>
        <div className="form-grid">
          <label>Language<select defaultValue="English"><option>English</option></select></label>
          <label>Country<select defaultValue="United States"><option>United States</option></select></label>
          <label>Age range<select defaultValue="25-34"><option>25-34</option></select></label>
          <label>Gender<select defaultValue="Prefer not to say"><option>Prefer not to say</option></select></label>
          <label className="wide">Religion<select defaultValue="No specific religion"><option>No specific religion</option></select></label>
        </div>
        <fieldset>
          <legend>Dietary needs</legend>
          <label className="choice selected"><input type="checkbox" defaultChecked /> Shellfish allergy <span>Severe</span></label>
          <p className="field-help">YOBI never interprets nationality as a religious or dietary rule.</p>
        </fieldset>
        <label className="range-field">
          <span>Spice tolerance <strong>{spice}/5</strong></span>
          <input type="range" min="0" max="5" value={spice} onChange={(event) => setSpice(Number(event.target.value))} />
          <span className="range-labels"><span>Very mild</span><span>Very hot</span></span>
        </label>
        <label>Favourite comfort foods<input value="Creamy pasta, chicken noodle soup" readOnly /></label>
        <label className="consent-row">
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
          <span>I agree to process this synthetic demo profile for this browser session.</span>
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button full large" disabled={!consent || loading}>
          {loading ? "Preparing your concierge…" : "Start ordering"}<ArrowRight size={19} />
        </button>
      </form>
    </main>
  );
}
