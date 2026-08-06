import { FormEvent, useState } from "react";
import { ArrowRight, Check, ShieldCheck, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useSessionStore } from "../stores/session";

export function OnboardingPage() {
  const navigate = useNavigate();
  const setContext = useSessionStore((state) => state.setContext);
  const [spice, setSpice] = useState(1);
  const [language, setLanguage] = useState("English");
  const [country, setCountry] = useState("United States");
  const [ageBand, setAgeBand] = useState("25-34");
  const [gender, setGender] = useState("Prefer not to say");
  const [religion, setReligion] = useState("Prefer not to say");
  const [shellfishAllergy, setShellfishAllergy] = useState(true);
  const [severity, setSeverity] = useState<"mild" | "moderate" | "severe">("severe");
  const [favorites, setFavorites] = useState("Creamy pasta, chicken noodle soup");
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const profile = await api.createProfile({
        preferred_language: language,
        nationality: country,
        age_band: ageBand,
        gender,
        religion_selection: religion,
        dietary_rules: shellfishAllergy ? ["shellfish_allergy"] : [],
        allergy_severity: severity,
        spice_tolerance: spice,
        favorite_foods: favorites.split(",").map((value) => value.trim()).filter(Boolean),
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
          <label>Language<select value={language} onChange={(event) => setLanguage(event.target.value)}><option>English</option><option>한국어</option><option>日本語</option><option>中文</option></select></label>
          <label>Country<select value={country} onChange={(event) => setCountry(event.target.value)}><option>United States</option><option>United Kingdom</option><option>Japan</option><option>Singapore</option><option>Australia</option><option>Other</option></select></label>
          <label>Age range<select value={ageBand} onChange={(event) => setAgeBand(event.target.value)}><option>18-24</option><option>25-34</option><option>35-44</option><option>45-54</option><option>55+</option><option>Prefer not to say</option></select></label>
          <label>Gender<select value={gender} onChange={(event) => setGender(event.target.value)}><option>Prefer not to say</option><option>Woman</option><option>Man</option><option>Non-binary</option><option>Self-describe</option></select></label>
          <label className="wide">Religion (optional)<select value={religion} onChange={(event) => setReligion(event.target.value)}><option>Prefer not to say</option><option>No specific religion</option><option>Islam</option><option>Judaism</option><option>Hinduism</option><option>Buddhism</option><option>Christianity</option><option>Other</option></select></label>
        </div>
        <fieldset>
          <legend>Dietary needs</legend>
          <label className={`choice ${shellfishAllergy ? "selected" : ""}`}><input type="checkbox" checked={shellfishAllergy} onChange={(event) => setShellfishAllergy(event.target.checked)} /> Shellfish allergy</label>
          {shellfishAllergy && <label className="severity-select">Severity<select value={severity} onChange={(event) => setSeverity(event.target.value as "mild" | "moderate" | "severe")}><option value="mild">Mild</option><option value="moderate">Moderate</option><option value="severe">Severe</option></select></label>}
          <p className="field-help">YOBI never interprets nationality as a religious or dietary rule.</p>
        </fieldset>
        <label className="range-field">
          <span>Spice tolerance <strong>{spice}/5</strong></span>
          <input type="range" min="0" max="5" value={spice} onChange={(event) => setSpice(Number(event.target.value))} />
          <span className="range-labels"><span>Very mild</span><span>Very hot</span></span>
        </label>
        <label>Favourite comfort foods<input value={favorites} onChange={(event) => setFavorites(event.target.value)} placeholder="Creamy pasta, chicken noodle soup" /></label>
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
