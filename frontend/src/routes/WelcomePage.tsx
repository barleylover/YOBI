import { ArrowLeft, ArrowRight, Languages, MapPin, MapPinned, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  LANGUAGES,
  LANGUAGE_META,
  asSupportedLanguage,
  countryName,
  sortedCountries,
} from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { useSessionStore } from "../stores/session";

export function WelcomePage() {
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
  const supportedLanguage = asSupportedLanguage(language);
  const locale = LANGUAGE_META[supportedLanguage].code;
  const productCopy = getProductCopy(supportedLanguage);
  const countries = useMemo(() => sortedCountries(supportedLanguage), [supportedLanguage]);

  useEffect(() => {
    document.documentElement.lang = LANGUAGE_META[supportedLanguage].code;
    document.documentElement.dir = LANGUAGE_META[supportedLanguage].direction;
    setLocaleDraft(language, country);
  }, [country, language, setLocaleDraft, supportedLanguage]);

  function changeLanguage(nextLanguage: string) {
    const nextSupportedLanguage = asSupportedLanguage(nextLanguage);
    const nextCountry = sortedCountries(nextSupportedLanguage)[0][0];
    setLanguage(nextLanguage);
    setCountry(nextCountry);
  }

  function start() {
    setLocaleDraft(language, country);
    if (editMode && profile) {
      updateProfile({ ...profile, preferred_language: language, nationality: country });
      navigate(`/profile?edit=1&returnTo=${encodeURIComponent(returnTo)}`);
      return;
    }
    navigate("/profile");
  }

  return (
    <main className="welcome-shell">
      <section className="welcome-card">
        <header className="welcome-brand">
          <div className="brand-mark">YO<span>BI</span></div>
          <span>{productCopy.entry.benefitFlavor}</span>
        </header>

        {editMode && (
          <button className="text-button welcome-back" type="button" onClick={() => navigate(returnTo)}>
            <ArrowLeft size={17} /> {productCopy.handoff.back}
          </button>
        )}

        <div className="welcome-content">
          <div className="welcome-hero">
            <div className="yobi-avatar" aria-hidden="true">Y</div>
            <h1>{productCopy.entry.heroTitle}<span>{productCopy.entry.heroBuddy}</span></h1>
          </div>
          <section className="welcome-pitch">
            <h2>{productCopy.entry.pitchTitle}</h2>
            <p>{productCopy.entry.pitchDescription}</p>
          </section>
          <div className="welcome-benefits">
            <span><Sparkles size={16} /> {productCopy.entry.benefitFlavor}</span>
            <span><ShieldCheck size={16} /> {productCopy.entry.benefitDietary}</span>
            <span><MapPin size={16} /> {productCopy.entry.benefitDelivery}</span>
          </div>

          <section className="welcome-locale" aria-label={`${productCopy.entry.languageLabel} · ${productCopy.entry.countryLabel}`}>
            <label>
              <span><Languages size={17} /> {productCopy.entry.languageLabel}</span>
              <select value={language} onChange={(event) => changeLanguage(event.target.value)}>
                {LANGUAGES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label>
              <span><MapPinned size={17} /> {productCopy.entry.countryLabel}</span>
              <select value={country} onChange={(event) => setCountry(event.target.value)}>
                {countries.map(([name, code]) => (
                  <option value={name} key={code}>{countryName(name, locale)}</option>
                ))}
              </select>
              <small>{productCopy.entry.countryHelp(language)}</small>
            </label>
          </section>
        </div>

        <footer>
          <div>
            <p>{productCopy.entry.localeApplies}</p>
            <p>{productCopy.entry.experienceNotice}</p>
          </div>
          <button className="primary-button welcome-cta" type="button" onClick={start}>
            {productCopy.entry.start} <ArrowRight size={20} />
          </button>
        </footer>
      </section>
    </main>
  );
}
