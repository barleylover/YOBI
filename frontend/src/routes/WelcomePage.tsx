import { ArrowLeft, ArrowRight, ChevronRight, Globe2, MapPin } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { YobiLogo } from "../components/YobiLogo";
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

  function openLocalePicker(tab: "language" | "country") {
    const params = new URLSearchParams({ tab, returnTo: location.pathname + location.search });
    navigate(`/start?${params.toString()}`);
  }

  return (
    <main className="yv2-entry-shell">
      <section className="yv2-entry-card">
        <header className="yv2-entry-header">
          {editMode && (
            <button className="yv2-icon-button" type="button" aria-label={productCopy.handoff.back} onClick={() => navigate(returnTo)}>
              <ArrowLeft size={20} />
            </button>
          )}
          <YobiLogo />
        </header>

        <div className="yv2-entry-content">
          <div className="yv2-entry-copy">
            <h1>{productCopy.entry.heroTitle}</h1>
            <h2>{productCopy.entry.pitchTitle}</h2>
            <p>{productCopy.entry.pitchDescription}</p>
          </div>

          <section className="yv2-entry-locales" aria-label={`${productCopy.entry.languageLabel} · ${productCopy.entry.countryLabel}`}>
            <div className="yv2-entry-locale-row">
              <Globe2 size={21} aria-hidden="true" />
              <label>
                <span>{productCopy.entry.languageLabel}</span>
                <select aria-label={productCopy.entry.languageLabel} value={language} onChange={(event) => changeLanguage(event.target.value)}>
                  {LANGUAGES.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <button type="button" aria-label={`${productCopy.entry.languageLabel} · ${language}`} onClick={() => openLocalePicker("language")}>
                <ChevronRight size={19} />
              </button>
            </div>
            <div className="yv2-entry-locale-row">
              <MapPin size={21} aria-hidden="true" />
              <label>
                <span>{productCopy.entry.countryLabel}</span>
                <select aria-label={productCopy.entry.countryLabel} value={country} onChange={(event) => setCountry(event.target.value)}>
                  {countries.map(([name, code]) => (
                    <option value={name} key={code}>{countryName(name, locale)}</option>
                  ))}
                </select>
              </label>
              <button type="button" aria-label={`${productCopy.entry.countryLabel} · ${countryName(country, locale)}`} onClick={() => openLocalePicker("country")}>
                <ChevronRight size={19} />
              </button>
            </div>
          </section>
        </div>

        <footer className="yv2-entry-footer">
          <button className="yv2-primary-button" type="button" onClick={start}>
            {productCopy.entry.start}<ArrowRight size={20} />
          </button>
          <p>{productCopy.entry.experienceNotice}</p>
        </footer>
      </section>
    </main>
  );
}
