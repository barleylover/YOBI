import { ArrowLeft, Check, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  COUNTRIES,
  LANGUAGES,
  LANGUAGE_META,
  asSupportedLanguage,
  countryName,
  sortedCountries,
  type SupportedLanguage,
} from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { useSessionStore } from "../stores/session";

type LocaleTab = "language" | "country";

const doneLabels: Record<SupportedLanguage, string> = {
  English: "Done",
  "한국어": "완료",
  "日本語": "完了",
  "中文（简体）": "完成",
  "中文（繁體）": "完成",
  Español: "Listo",
  Français: "Terminé",
  Deutsch: "Fertig",
  Italiano: "Fine",
  Português: "Concluído",
  "ไทย": "เสร็จสิ้น",
  "Tiếng Việt": "Xong",
  "Bahasa Indonesia": "Selesai",
  "العربية": "تم",
  "हिन्दी": "पूर्ण",
  "Русский": "Готово",
};

export function LocalePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const query = new URLSearchParams(location.search);
  const requestedTab = query.get("tab");
  const savedLanguage = useSessionStore((state) => state.draftLanguage);
  const savedCountry = useSessionStore((state) => state.draftCountry);
  const setLocaleDraft = useSessionStore((state) => state.setLocaleDraft);
  const [language, setLanguage] = useState(savedLanguage);
  const [country, setCountry] = useState(savedCountry);
  const [activeTab, setActiveTab] = useState<LocaleTab>(requestedTab === "country" ? "country" : "language");
  const [search, setSearch] = useState("");
  const supportedLanguage = asSupportedLanguage(language);
  const locale = LANGUAGE_META[supportedLanguage].code;
  const copy = getProductCopy(supportedLanguage);
  const returnTo = query.get("returnTo") || "/";
  const countries = useMemo(() => sortedCountries(supportedLanguage), [supportedLanguage]);
  const languageRows = useMemo(() => LANGUAGES.filter((item) => item.toLocaleLowerCase(locale).includes(search.toLocaleLowerCase(locale))), [locale, search]);
  const countryRows = useMemo(() => countries.filter(([name]) => {
    const localized = countryName(name, locale);
    return `${localized} ${name}`.toLocaleLowerCase(locale).includes(search.toLocaleLowerCase(locale));
  }), [countries, locale, search]);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = LANGUAGE_META[supportedLanguage].direction;
    setLocaleDraft(language, country);
  }, [country, language, locale, setLocaleDraft, supportedLanguage]);

  if (requestedTab !== "language" && requestedTab !== "country") {
    return <Navigate to={`/${location.search}`} replace />;
  }

  function chooseLanguage(nextLanguage: string) {
    const nextSupportedLanguage = asSupportedLanguage(nextLanguage);
    const firstCountry = sortedCountries(nextSupportedLanguage)[0][0];
    setLanguage(nextLanguage);
    setCountry(firstCountry);
  }

  function changeTab(next: LocaleTab) {
    setActiveTab(next);
    setSearch("");
  }

  return (
    <main className="yv2-locale-shell">
      <section className="yv2-locale-card">
        <header className="yv2-page-header">
          <button className="yv2-icon-button" type="button" aria-label={copy.handoff.back} onClick={() => navigate(returnTo)}>
            <ArrowLeft size={20} />
          </button>
          <h1>{copy.entry.languageLabel} &amp; {copy.entry.countryLabel.toLocaleLowerCase(locale)}</h1>
          <button className="yv2-header-action" type="button" onClick={() => navigate(returnTo)}>{doneLabels[supportedLanguage]}</button>
        </header>

        <div className="yv2-locale-tabs" role="tablist" aria-label={`${copy.entry.languageLabel} · ${copy.entry.countryLabel}`}>
          <button type="button" role="tab" aria-selected={activeTab === "language"} onClick={() => changeTab("language")}>
            {copy.entry.languageLabel}<span>{LANGUAGES.length}</span>
          </button>
          <button type="button" role="tab" aria-selected={activeTab === "country"} onClick={() => changeTab("country")}>
            {copy.entry.countryLabel}<span>{COUNTRIES.length}</span>
          </button>
        </div>

        <label className="yv2-search-field">
          <Search size={18} aria-hidden="true" />
          <span className="visually-hidden">{activeTab === "language" ? copy.entry.languageLabel : copy.entry.countryLabel}</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={copy.address.search} />
        </label>

        <div className="yv2-locale-list" role="tabpanel">
          {activeTab === "language" && languageRows.map((item) => {
            const selected = item === language;
            const languageCode = LANGUAGE_META[item].code.split("-")[0].toUpperCase();
            return (
              <button type="button" className={selected ? "selected" : ""} aria-pressed={selected} onClick={() => chooseLanguage(item)} key={item}>
                <span className="yv2-locale-code">{languageCode}</span>
                <strong>{item}</strong>
                {selected && <Check size={19} />}
              </button>
            );
          })}
          {activeTab === "country" && countryRows.map(([name, code]) => {
            const selected = name === country;
            return (
              <button type="button" className={selected ? "selected" : ""} aria-pressed={selected} onClick={() => setCountry(name)} key={code}>
                <span className="yv2-locale-code">{code}</span>
                <strong>{countryName(name, locale)}</strong>
                {selected && <Check size={19} />}
              </button>
            );
          })}
        </div>
      </section>
    </main>
  );
}
