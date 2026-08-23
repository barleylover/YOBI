import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  LANGUAGES,
  asSupportedLanguage,
  countryName,
  effectiveLanguageMeta,
  sortedCountries,
} from "../lib/locale";
import { LANGUAGE_ENGLISH_NAMES, getRedesignCopy } from "../lib/redesignI18n";
import { useSessionStore } from "../stores/session";

type PickerTab = "language" | "country";

export function LocalePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const language = useSessionStore((state) => state.draftLanguage);
  const country = useSessionStore((state) => state.draftCountry);
  const setLocaleDraft = useSessionStore((state) => state.setLocaleDraft);
  const query = new URLSearchParams(location.search);
  const [tab, setTab] = useState<PickerTab>(query.get("tab") === "country" ? "country" : "language");
  const [search, setSearch] = useState("");
  const supportedLanguage = asSupportedLanguage(language);
  const effectiveMeta = effectiveLanguageMeta(supportedLanguage);
  const locale = effectiveMeta.code;
  const copy = getRedesignCopy(supportedLanguage);
  const countries = useMemo(() => sortedCountries(supportedLanguage), [supportedLanguage]);

  useEffect(() => {
    document.documentElement.lang = effectiveMeta.code;
    document.documentElement.dir = effectiveMeta.direction;
  }, [effectiveMeta.code, effectiveMeta.direction]);

  const normalizedSearch = search.trim().toLowerCase();
  const visibleLanguages = LANGUAGES.filter((item) => !normalizedSearch
    || item.toLowerCase().includes(normalizedSearch)
    || LANGUAGE_ENGLISH_NAMES[item].toLowerCase().includes(normalizedSearch));
  const visibleCountries = countries.filter(([name]) => !normalizedSearch
    || name.toLowerCase().includes(normalizedSearch)
    || countryName(name, locale).toLowerCase().includes(normalizedSearch));

  function chooseLanguage(nextLanguage: string) {
    const nextSupported = asSupportedLanguage(nextLanguage);
    const validCountries = sortedCountries(nextSupported);
    const keepCountry = validCountries.some(([name]) => name === country);
    setLocaleDraft(nextLanguage, keepCountry ? country : validCountries[0][0]);
  }

  function close() {
    const back = query.get("edit") === "1"
      ? `/?edit=1&returnTo=${encodeURIComponent(query.get("returnTo") || "/")}`
      : "/";
    navigate(back);
  }

  function switchTab(nextTab: PickerTab) {
    setTab(nextTab);
    setSearch("");
  }

  return (
    <main className="v2-screen">
      <header className="v2-appbar">
        <button type="button" className="v2-icon-button" aria-label={copy.done} onClick={close}>
          <img src="/figma/x-icon.svg" alt="" width={14} height={14} />
        </button>
        <h1 className="v2-appbar-title">{copy.localeTitle}</h1>
        <button type="button" className="v2-appbar-action" onClick={close}>{copy.done}</button>
      </header>

      <div style={{ padding: "0 20px 14px" }}>
        <div className="v2-seg-tabs" role="tablist" aria-label={copy.localeTitle}>
          <button type="button" role="tab" aria-selected={tab === "language"} onClick={() => switchTab("language")}>
            {copy.languageTab(LANGUAGES.length)}
          </button>
          <button type="button" role="tab" aria-selected={tab === "country"} onClick={() => switchTab("country")}>
            {copy.countryTab(countries.length)}
          </button>
        </div>
      </div>

      <div style={{ padding: "0 20px 12px" }}>
        <label className="v2-search-field">
          <img src="/figma/search-icon.svg" alt="" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={tab === "language" ? copy.searchLanguage : copy.searchCountry}
          />
        </label>
      </div>

      <div className="v2-body" style={{ paddingTop: 4, paddingBottom: 8 }} role="tabpanel">
        <p className="v2-list-section-label">{copy.suggested}</p>
        {tab === "language" && visibleLanguages.map((item) => {
          const selected = item === language;
          return (
            <button
              type="button"
              className="v2-list-row"
              key={item}
              aria-pressed={selected}
              onClick={() => chooseLanguage(item)}
            >
              <div>
                <strong>{item}</strong>
                <small>{LANGUAGE_ENGLISH_NAMES[item]}</small>
              </div>
              <span className={selected ? "v2-radio checked" : "v2-radio"} aria-hidden="true" />
            </button>
          );
        })}
        {tab === "country" && visibleCountries.map(([name, code]) => {
          const selected = name === country;
          return (
            <button
              type="button"
              className="v2-list-row"
              key={code}
              aria-pressed={selected}
              onClick={() => setLocaleDraft(language, name)}
            >
              <div>
                <strong>{countryName(name, locale)}</strong>
                <small>{name}</small>
              </div>
              <span className={selected ? "v2-radio checked" : "v2-radio"} aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </main>
  );
}
