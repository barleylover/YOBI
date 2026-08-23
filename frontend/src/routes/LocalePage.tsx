import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  LANGUAGES,
  asSupportedLanguage,
  countryFlag,
  countryName,
  effectiveLanguageMeta,
  sortedCountries,
} from "../lib/locale";
import { LANGUAGE_ENGLISH_NAMES, getRedesignCopy } from "../lib/redesignI18n";
import { getProductCopy } from "../lib/productI18n";
import { useSessionStore } from "../stores/session";

type PickerTab = "language" | "country";

const COUNTRY_SEARCH_ALIASES: Record<string, string> = {
  US: "usa america united states 미국 アメリカ",
  GB: "uk britain england united kingdom 영국 イギリス",
  KR: "korea south korea republic of korea 한국 대한민국 韓国",
  JP: "japan 일본 日本",
  TR: "turkey turkiye türkiye 튀르키예 トルコ",
  ZZ: "other elsewhere unknown 기타 그 외 その他",
};

function normalizeSearchValue(value: string) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
}

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
  const productCopy = getProductCopy(supportedLanguage);
  const countries = useMemo(() => sortedCountries(supportedLanguage), [supportedLanguage]);

  useEffect(() => {
    document.documentElement.lang = effectiveMeta.code;
    document.documentElement.dir = effectiveMeta.direction;
  }, [effectiveMeta.code, effectiveMeta.direction]);

  const normalizedSearch = normalizeSearchValue(search.trim());
  const visibleLanguages = LANGUAGES.filter((item) => !normalizedSearch
    || normalizeSearchValue(item).includes(normalizedSearch)
    || normalizeSearchValue(LANGUAGE_ENGLISH_NAMES[item]).includes(normalizedSearch));
  const visibleCountries = countries.filter(([name, code]) => !normalizedSearch
    || normalizeSearchValue(name).includes(normalizedSearch)
    || normalizeSearchValue(countryName(name, locale)).includes(normalizedSearch)
    || normalizeSearchValue(COUNTRY_SEARCH_ALIASES[code] ?? "").includes(normalizedSearch));

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
            aria-label={tab === "language" ? copy.searchLanguage : copy.searchCountry}
          />
        </label>
      </div>

      <div className="v2-body" style={{ paddingTop: 4, paddingBottom: 8 }} role="tabpanel">
        {tab === "country" && (
          <p className="v2-locale-help">{productCopy.entry.countryHelp(language)}</p>
        )}
        <p className="v2-list-section-label">
          {tab === "language" ? copy.languageTab(LANGUAGES.length) : copy.countryTab(countries.length)}
        </p>
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
          const localizedName = countryName(name, locale);
          return (
            <button
              type="button"
              className="v2-list-row"
              key={code}
              aria-pressed={selected}
              onClick={() => setLocaleDraft(language, name)}
            >
              <span className="v2-country-flag" aria-hidden="true">{countryFlag(code)}</span>
              <div>
                <strong>{localizedName}</strong>
                {normalizeSearchValue(localizedName) !== normalizeSearchValue(name) && <small>{name}</small>}
              </div>
              <span className={selected ? "v2-radio checked" : "v2-radio"} aria-hidden="true" />
            </button>
          );
        })}
        {((tab === "language" && visibleLanguages.length === 0)
          || (tab === "country" && visibleCountries.length === 0)) && (
          <p className="v2-status" role="status">
            {language === "한국어" ? "검색 결과가 없습니다." : language === "日本語" ? "検索結果がありません。" : "No matching results."}
          </p>
        )}
      </div>
    </main>
  );
}
