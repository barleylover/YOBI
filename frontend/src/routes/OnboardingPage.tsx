import { ChangeEvent, FormEvent, useMemo, useRef, useState } from "react";
import { ArrowRight, Hotel, ImageUp, MapPin, ShieldCheck, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useSessionStore } from "../stores/session";
import type { AddressCandidate, Profile, Session } from "../types";

const LANGUAGES = [
  "English", "한국어", "日本語", "中文（简体）", "中文（繁體）", "Español", "Français",
  "Deutsch", "Italiano", "Português", "ไทย", "Tiếng Việt", "Bahasa Indonesia",
  "العربية", "हिन्दी", "Русский",
];

const COUNTRIES = [
  ["United States", "US"], ["United Kingdom", "GB"], ["Canada", "CA"], ["Australia", "AU"],
  ["New Zealand", "NZ"], ["Ireland", "IE"], ["South Korea", "KR"], ["Japan", "JP"],
  ["China", "CN"], ["Taiwan", "TW"], ["Hong Kong", "HK"], ["Singapore", "SG"],
  ["Spain", "ES"], ["Mexico", "MX"], ["Argentina", "AR"], ["Colombia", "CO"],
  ["France", "FR"], ["Belgium", "BE"], ["Germany", "DE"], ["Austria", "AT"],
  ["Switzerland", "CH"], ["Italy", "IT"], ["Portugal", "PT"], ["Brazil", "BR"],
  ["Thailand", "TH"], ["Vietnam", "VN"], ["Indonesia", "ID"], ["Malaysia", "MY"],
  ["Saudi Arabia", "SA"], ["United Arab Emirates", "AE"], ["Egypt", "EG"], ["India", "IN"],
  ["Russia", "RU"], ["Philippines", "PH"], ["Türkiye", "TR"], ["Netherlands", "NL"],
] as const;

const LANGUAGE_COUNTRIES: Record<string, string[]> = {
  English: ["US", "GB", "CA", "AU", "NZ", "IE", "SG"],
  "한국어": ["KR"],
  "日本語": ["JP"],
  "中文（简体）": ["CN", "SG"],
  "中文（繁體）": ["TW", "HK"],
  Español: ["ES", "MX", "AR", "CO"],
  Français: ["FR", "BE", "CA", "CH"],
  Deutsch: ["DE", "AT", "CH"],
  Italiano: ["IT", "CH"],
  Português: ["BR", "PT"],
  "ไทย": ["TH"],
  "Tiếng Việt": ["VN"],
  "Bahasa Indonesia": ["ID"],
  "العربية": ["SA", "AE", "EG"],
  "हिन्दी": ["IN"],
  "Русский": ["RU"],
};

type AddressMode = "hotel" | "upload" | "manual";
type CreatedContext = { profile: Profile; session: Session };

export function OnboardingPage() {
  const navigate = useNavigate();
  const setContext = useSessionStore((state) => state.setContext);
  const setDeliveryAddress = useSessionStore((state) => state.setDeliveryAddress);
  const candidateRef = useRef<HTMLDivElement>(null);
  const [spice, setSpice] = useState(2);
  const [language, setLanguage] = useState("English");
  const [country, setCountry] = useState("United States");
  const [ageBand, setAgeBand] = useState("25-34");
  const [religion, setReligion] = useState("Prefer not to say");
  const [vegan, setVegan] = useState(false);
  const [shellfishAllergy, setShellfishAllergy] = useState(true);
  const [severity, setSeverity] = useState<"mild" | "moderate" | "severe">("severe");
  const [favorites, setFavorites] = useState("Creamy pasta, chicken noodle soup");
  const [consent, setConsent] = useState(false);
  const [addressMode, setAddressMode] = useState<AddressMode>("hotel");
  const [hotelQuery, setHotelQuery] = useState("YOBI Myeongdong Hotel");
  const [addressImage, setAddressImage] = useState<File | null>(null);
  const [manualAddress, setManualAddress] = useState({
    hotel_name: "", road_address: "", postal_code: "", city: "Seoul",
    delivery_hint: "Please leave it at the hotel front desk.",
  });
  const [candidates, setCandidates] = useState<AddressCandidate[]>([]);
  const [addressNotice, setAddressNotice] = useState("");
  const [createdContext, setCreatedContext] = useState<CreatedContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const sortedCountries = useMemo(() => {
    const priority = LANGUAGE_COUNTRIES[language] ?? [];
    return [...COUNTRIES].sort((left, right) => {
      const leftIndex = priority.indexOf(left[1]);
      const rightIndex = priority.indexOf(right[1]);
      if (leftIndex !== -1 || rightIndex !== -1) {
        if (leftIndex === -1) return 1;
        if (rightIndex === -1) return -1;
        return leftIndex - rightIndex;
      }
      return left[0].localeCompare(right[0]);
    });
  }, [language]);

  async function ensureContext(): Promise<CreatedContext> {
    if (createdContext) return createdContext;
    const dietaryRules = [
      ...(shellfishAllergy ? ["shellfish_allergy"] : []),
      ...(vegan ? ["vegan"] : []),
    ];
    const profile = await api.createProfile({
      preferred_language: language,
      nationality: country,
      age_band: ageBand,
      religion_selection: religion,
      dietary_rules: dietaryRules,
      allergy_severity: severity,
      spice_tolerance: spice,
      favorite_foods: favorites.split(",").map((value) => value.trim()).filter(Boolean),
      consent_demo_data: consent,
      remember_profile: false,
    });
    const session = await api.createSession(profile.profile_id);
    const context = { profile, session };
    setCreatedContext(context);
    setContext(profile, session);
    return context;
  }

  function finish(addressRefId: string, summary: string, session: Session) {
    setDeliveryAddress(addressRefId, summary);
    navigate(`/chat/${session.session_id}`);
  }

  async function checkAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setCandidates([]);
    try {
      const context = await ensureContext();
      if (addressMode === "manual") {
        const result = await api.confirmManualAddress(context.session.session_id, manualAddress);
        finish(result.address_ref_id, `${manualAddress.hotel_name} · ${manualAddress.road_address}`, context.session);
        return;
      }
      const result = addressMode === "upload"
        ? await api.uploadAddress(context.session.session_id, addressImage as File)
        : await api.resolveAddress(context.session.session_id, hotelQuery);
      setCandidates(result.candidates);
      setAddressNotice(result.notice);
      if (!result.candidates.length) setError("No matching address was found. Try the full hotel name or enter the road address.");
      requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (cause) {
      setError(actionableError(cause, "We could not check that address. Try another method."));
    } finally {
      setLoading(false);
    }
  }

  async function confirmCandidate(candidate: AddressCandidate) {
    if (!createdContext) return;
    setLoading(true);
    setError("");
    try {
      const result = await api.confirmAddress(createdContext.session.session_id, candidate);
      finish(result.address_ref_id, `${candidate.hotel_name} · ${candidate.road_address}`, createdContext.session);
    } catch (cause) {
      setError(actionableError(cause, "Search for the address again, then confirm the matching result."));
    } finally {
      setLoading(false);
    }
  }

  async function loadDemoBooking() {
    setLoading(true);
    setError("");
    try {
      const context = await ensureContext();
      const response = await fetch("/demo-booking.png");
      const blob = await response.blob();
      const result = await api.uploadAddress(
        context.session.session_id,
        new File([blob], "yobi-demo-booking.png", { type: "image/png" }),
      );
      setCandidates(result.candidates);
      setAddressNotice(result.notice);
      requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (cause) {
      setError(actionableError(cause, "The demo address could not be checked. Try the hotel search."));
    } finally {
      setLoading(false);
    }
  }

  function fileChanged(event: ChangeEvent<HTMLInputElement>) {
    setAddressImage(event.target.files?.[0] ?? null);
  }

  const addressReady = addressMode === "hotel"
    ? hotelQuery.trim().length >= 2
    : addressMode === "upload"
      ? Boolean(addressImage)
      : Boolean(manualAddress.hotel_name.trim() && manualAddress.road_address.trim().length >= 3);

  return (
    <main className="onboarding-shell">
      <section className="onboarding-intro">
        <div className="brand-mark">YO<span>BI</span></div>
        <p className="eyebrow">Your Korean food buddy</p>
        <h1>Order K-food with context, not guesswork.</h1>
        <p className="intro-copy">Tell YOBI what you crave, what you avoid, and where the food should arrive. Your first recommendation starts with the full delivery context.</p>
        <div className="benefit-list">
          <span><Sparkles size={18} /> Understand flavour and texture</span>
          <span><ShieldCheck size={18} /> See risk and unknown evidence clearly</span>
          <span><MapPin size={18} /> Check the delivery address before choosing</span>
        </div>
        <p className="demo-notice">Demo service · synthetic restaurants · no real charge</p>
      </section>

      <form className="onboarding-card" onSubmit={checkAddress}>
        <div className="step-label">Your starting information</div>
        <h2>Set up a useful first answer.</h2>
        <div className="form-grid">
          <label>Language
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              {LANGUAGES.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>Country
            <select value={country} onChange={(event) => setCountry(event.target.value)}>
              {sortedCountries.map(([name, code]) => <option value={name} key={code}>{name}</option>)}
            </select>
            <span className="input-help">Countries commonly using {language} appear first.</span>
          </label>
          <label>Age range<select value={ageBand} onChange={(event) => setAgeBand(event.target.value)}><option>18-24</option><option>25-34</option><option>35-44</option><option>45-54</option><option>55+</option><option>Prefer not to say</option></select></label>
          <label>Religion (optional)<select value={religion} onChange={(event) => setReligion(event.target.value)}><option>Prefer not to say</option><option>No specific religion</option><option>Islam</option><option>Judaism</option><option>Hinduism</option><option>Buddhism</option><option>Christianity</option><option>Sikhism</option><option>Jainism</option><option>Other</option></select></label>
        </div>

        <fieldset>
          <legend>Dietary needs</legend>
          <div className="choice-grid">
            <label className={`choice ${vegan ? "selected" : ""}`}><input type="checkbox" checked={vegan} onChange={(event) => setVegan(event.target.checked)} /> Vegan</label>
            <label className={`choice ${shellfishAllergy ? "selected" : ""}`}><input type="checkbox" checked={shellfishAllergy} onChange={(event) => setShellfishAllergy(event.target.checked)} /> Shellfish allergy</label>
          </div>
          {shellfishAllergy && <label className="severity-select">Allergy severity<select value={severity} onChange={(event) => setSeverity(event.target.value as "mild" | "moderate" | "severe")}><option value="mild">Mild</option><option value="moderate">Moderate</option><option value="severe">Severe</option></select></label>}
          <p className="field-help">Religion is stored as context only. YOBI never infers dietary rules from language, country, or religion.</p>
        </fieldset>

        <fieldset className="spice-fieldset">
          <legend>Spice tolerance</legend>
          <div className="spice-options">
            {[
              [0, "No heat", "I can’t eat spicy food at all."],
              [2, "Medium", "A balanced, moderate level is good."],
              [5, "Here for the heat", "I came to Korea to eat spicy food."],
            ].map(([value, title, description]) => (
              <label className={spice === value ? "spice-choice selected" : "spice-choice"} key={value}>
                <input type="radio" name="spice" value={value} checked={spice === value} onChange={() => setSpice(Number(value))} />
                <span><strong>{title}</strong><small>{description}</small></span>
              </label>
            ))}
          </div>
        </fieldset>

        <label>Favourite comfort foods<input value={favorites} onChange={(event) => setFavorites(event.target.value)} placeholder="Creamy pasta, chicken noodle soup" /></label>

        <section className="onboarding-address" aria-labelledby="delivery-address-title">
          <div className="address-heading"><MapPin size={19} /><div><p className="eyebrow">Required before recommendations</p><h3 id="delivery-address-title">Delivery address</h3></div></div>
          <p>Check your hotel or road address now so every later order step starts in a deliverable area.</p>
          <div className="address-methods" role="tablist" aria-label="Address entry method">
            <button type="button" className={addressMode === "hotel" ? "active" : ""} onClick={() => { setAddressMode("hotel"); setCandidates([]); }}>Hotel name</button>
            <button type="button" className={addressMode === "upload" ? "active" : ""} onClick={() => { setAddressMode("upload"); setCandidates([]); }}>Booking image</button>
            <button type="button" className={addressMode === "manual" ? "active" : ""} onClick={() => { setAddressMode("manual"); setCandidates([]); }}>Road address</button>
          </div>
          {addressMode === "hotel" && <label>Hotel or stay name<input value={hotelQuery} onChange={(event) => setHotelQuery(event.target.value)} placeholder="e.g. YOBI Myeongdong Hotel" /></label>}
          {addressMode === "upload" && <>
            <label className="upload-zone"><ImageUp size={25} /><strong>{addressImage ? addressImage.name : "Choose booking image"}</strong><span>PNG, JPEG or WebP · up to 8MB</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={fileChanged} /></label>
            <button type="button" className="secondary-button full" onClick={() => void loadDemoBooking()} disabled={!consent || loading}>Use stable demo booking image</button>
          </>}
          {addressMode === "manual" && <div className="address-form compact">
            <label>Hotel or stay name<input value={manualAddress.hotel_name} onChange={(event) => setManualAddress((value) => ({ ...value, hotel_name: event.target.value }))} /></label>
            <label>Road address<input value={manualAddress.road_address} onChange={(event) => setManualAddress((value) => ({ ...value, road_address: event.target.value }))} placeholder="Full Korean road address" /></label>
            <div className="address-form-row"><label>Postal code<input value={manualAddress.postal_code} onChange={(event) => setManualAddress((value) => ({ ...value, postal_code: event.target.value }))} /></label><label>City<input value={manualAddress.city} onChange={(event) => setManualAddress((value) => ({ ...value, city: event.target.value }))} /></label></div>
          </div>}
          {addressNotice && <p className="notice-copy">{addressNotice}</p>}
          <div ref={candidateRef}>
            {candidates.map((candidate) => <article className="address-candidate" key={candidate.place_id}><Hotel size={20} /><div><strong>{candidate.hotel_name}</strong><p>{candidate.road_address}</p><small>{Math.round(candidate.confidence * 100)}% match · synthetic place</small></div><button type="button" className="primary-button" onClick={() => void confirmCandidate(candidate)} disabled={loading}>Confirm &amp; start</button></article>)}
          </div>
        </section>

        <label className="consent-row"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>I agree to process this synthetic demo profile and address for this browser session.</span></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button full large" disabled={!consent || !addressReady || loading}>
          {loading ? "Checking your delivery context…" : addressMode === "manual" ? "Save address & start ordering" : "Check delivery address"}<ArrowRight size={19} />
        </button>
      </form>
    </main>
  );
}
