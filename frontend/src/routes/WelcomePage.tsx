import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LANGUAGE_META, asSupportedLanguage, countryName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getRedesignCopy } from "../lib/redesignI18n";
import { useSessionStore } from "../stores/session";

export function WelcomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const profile = useSessionStore((state) => state.profile);
  const language = useSessionStore((state) => state.draftLanguage);
  const country = useSessionStore((state) => state.draftCountry);
  const updateProfile = useSessionStore((state) => state.updateProfile);
  const query = new URLSearchParams(location.search);
  const editMode = query.get("edit") === "1" && Boolean(profile);
  const returnTo = query.get("returnTo") || "/";
  const supportedLanguage = asSupportedLanguage(language);
  const locale = LANGUAGE_META[supportedLanguage].code;
  const productCopy = getProductCopy(supportedLanguage);
  const redesignCopy = getRedesignCopy(supportedLanguage);

  useEffect(() => {
    document.documentElement.lang = LANGUAGE_META[supportedLanguage].code;
    document.documentElement.dir = LANGUAGE_META[supportedLanguage].direction;
  }, [supportedLanguage]);

  function openLocalePicker(tab: "language" | "country") {
    navigate(`/start?tab=${tab}${editMode ? `&edit=1&returnTo=${encodeURIComponent(returnTo)}` : ""}`);
  }

  function start() {
    if (editMode && profile) {
      updateProfile({ ...profile, preferred_language: language, nationality: country });
      navigate(`/profile?edit=1&returnTo=${encodeURIComponent(returnTo)}`);
      return;
    }
    navigate("/profile");
  }

  return (
    <main className="v2-screen">
      {editMode && (
        <header className="v2-appbar">
          <button type="button" className="v2-icon-button" aria-label={redesignCopy.back} onClick={() => navigate(returnTo)}>
            <img src="/figma/back-chevron.svg" alt="" width={9} height={16} />
          </button>
          <p className="v2-appbar-step">{productCopy.address.changeLocale}</p>
        </header>
      )}
      <div className="v2-body" style={{ paddingTop: editMode ? 8 : 20, justifyContent: "space-between" }}>
        <section className="v2-onboarding-hero">
          <img src="/figma/logo-mark.svg" alt="YOBI" />
          <h1>
            {productCopy.entry.heroTitle}
            <span>{productCopy.entry.heroBuddy}</span>
          </h1>
          <p>{productCopy.entry.pitchDescription}</p>
        </section>

        <div className="v2-onboarding-context">
          <button type="button" className="v2-field-card" onClick={() => openLocalePicker("language")}>
            <div>
              <small>{productCopy.entry.languageLabel}</small>
              <strong>{language}</strong>
            </div>
            <img src="/figma/chevron-down.svg" alt="" />
          </button>
          <button type="button" className="v2-field-card" onClick={() => openLocalePicker("country")}>
            <div>
              <small>{productCopy.entry.countryLabel}</small>
              <strong>{countryName(country, locale)}</strong>
            </div>
            <img src="/figma/chevron-down.svg" alt="" />
          </button>
        </div>
      </div>

      <footer className="v2-cta-footer">
        <button type="button" className="v2-cta" onClick={start}>
          {productCopy.entry.start}
        </button>
        <p className="v2-footnote">{redesignCopy.demoFootnote}</p>
      </footer>
    </main>
  );
}
