import { ArrowLeft, ArrowRight, Languages, MapPinned } from "lucide-react";
import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LANGUAGES, asSupportedLanguage, sortedCountries } from "../lib/locale";
import { useSessionStore } from "../stores/session";

export function LocalePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const profile = useSessionStore((state) => state.profile);
  const savedLanguage = useSessionStore((state) => state.draftLanguage);
  const savedCountry = useSessionStore((state) => state.draftCountry);
  const setLocaleDraft = useSessionStore((state) => state.setLocaleDraft);
  const updateProfile = useSessionStore((state) => state.updateProfile);
  const query = new URLSearchParams(location.search);
  const editMode = query.get("edit") === "1" && Boolean(profile);
  const returnTo = query.get("returnTo") || "/";
  const [language, setLanguage] = useState(profile?.preferred_language ?? savedLanguage);
  const [country, setCountry] = useState(profile?.nationality ?? savedCountry);
  const countries = useMemo(() => sortedCountries(asSupportedLanguage(language)), [language]);

  function next() {
    setLocaleDraft(language, country);
    if (editMode && profile) updateProfile({ ...profile, preferred_language: language, nationality: country });
    navigate(editMode ? `/profile?edit=1&returnTo=${encodeURIComponent(returnTo)}` : "/profile");
  }

  return (
    <main className="locale-shell">
      <section className="locale-card">
        <button className="text-button back-button" onClick={() => navigate(editMode ? returnTo : "/")}><ArrowLeft size={17} /> Back</button>
        <div className="step-label">1 of 2 · Starting information</div>
        <h1>Let’s speak your language.</h1>
        <p>Choose how YOBI should talk with you and where you are visiting from.</p>
        <label><Languages size={17} /> Language
          <select value={language} onChange={(event) => {
            const nextLanguage = event.target.value;
            setLanguage(nextLanguage);
            const firstCountry = sortedCountries(asSupportedLanguage(nextLanguage))[0][0];
            setCountry(firstCountry);
          }}>{LANGUAGES.map((item) => <option key={item}>{item}</option>)}</select>
        </label>
        <label><MapPinned size={17} /> Country
          <select value={country} onChange={(event) => setCountry(event.target.value)}>{countries.map(([name, code]) => <option value={name} key={code}>{name}</option>)}</select>
          <span className="input-help">Countries commonly using {language} appear first.</span>
        </label>
        <button className="primary-button full large" onClick={next}>Next <ArrowRight size={19} /></button>
        <p className="demo-notice">Language applies to recommendations, ordering and payment.</p>
      </section>
    </main>
  );
}
