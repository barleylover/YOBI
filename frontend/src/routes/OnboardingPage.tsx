import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Hotel, ImageUp, MapPin } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSessionStore } from "../stores/session";
import type { AddressCandidate, Profile, Session } from "../types";

const ALLERGY_CODES = ["shellfish", "fish", "milk", "egg", "peanut", "tree_nut", "wheat", "soy", "sesame"] as const;

type AddressMode = "existing" | "hotel" | "upload" | "manual";
type CreatedContext = { profile: Profile; session: Session };

export function OnboardingPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { profileCopy, selectionCopy, chatMenuCopy, language } = useI18n();
  const profile = useSessionStore((state) => state.profile);
  const session = useSessionStore((state) => state.session);
  const addressRefId = useSessionStore((state) => state.addressRefId);
  const addressSummary = useSessionStore((state) => state.addressSummary);
  const setContext = useSessionStore((state) => state.setContext);
  const updateProfile = useSessionStore((state) => state.updateProfile);
  const setDeliveryAddress = useSessionStore((state) => state.setDeliveryAddress);
  const country = useSessionStore((state) => state.draftCountry);
  const query = new URLSearchParams(location.search);
  const editMode = query.get("edit") === "1" && Boolean(profile && session);
  const returnTo = query.get("returnTo") || (session ? `/chat/${session.session_id}` : "/");
  const candidateRef = useRef<HTMLDivElement>(null);
  const [spice, setSpice] = useState(profile?.spice_tolerance ?? 2);
  const [ageBand, setAgeBand] = useState(profile?.age_band ?? "25-34");
  const [religion, setReligion] = useState(profile?.religion_selection ?? "Prefer not to say");
  const [vegan, setVegan] = useState(profile?.dietary_rules.includes("vegan") ?? false);
  const [allergies, setAllergies] = useState<Set<string>>(() => profile
    ? new Set(profile.dietary_rules.filter((rule) => rule.endsWith("_allergy")).map((rule) => rule.replace(/_allergy$/, "")))
    : new Set(["shellfish"]));
  const [severity, setSeverity] = useState<"mild" | "moderate" | "severe">(profile?.allergy_severity ?? "severe");
  const [favorites, setFavorites] = useState(profile?.favorite_foods.join(", ") ?? "");
  const [consent, setConsent] = useState(profile?.consent_demo_data ?? false);
  const [addressMode, setAddressMode] = useState<AddressMode>(editMode && addressRefId ? "existing" : "hotel");
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

  function toggleAllergy(code: string) {
    setAllergies((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code); else next.add(code);
      return next;
    });
  }

  async function ensureContext(): Promise<CreatedContext> {
    if (createdContext) return createdContext;
    const dietaryRules = [
      ...[...allergies].map((code) => `${code}_allergy`),
      ...(vegan ? ["vegan"] : []),
    ];
    const body = {
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
    };
    if (editMode && profile && session) {
      const updated = await api.updateProfile(profile.profile_id, body);
      updateProfile(updated);
      const context = { profile: updated, session };
      setCreatedContext(context);
      return context;
    }
    const createdProfile = await api.createProfile(body);
    const createdSession = await api.createSession(createdProfile.profile_id);
    const context = { profile: createdProfile, session: createdSession };
    setCreatedContext(context);
    setContext(createdProfile, createdSession);
    return context;
  }

  function finish(addressRefId: string, summary: string, session: Session) {
    setDeliveryAddress(addressRefId, summary);
    navigate(editMode ? returnTo : `/chat/${session.session_id}`);
  }

  async function checkAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setCandidates([]);
    try {
      const context = await ensureContext();
      if (addressMode === "existing") {
        finish(addressRefId, addressSummary, context.session);
        return;
      }
      if (addressMode === "manual") {
        const result = await api.confirmManualAddress(context.session.session_id, manualAddress);
        finish(result.address_ref_id, `${manualAddress.hotel_name} · ${manualAddress.road_address}`, context.session);
        return;
      }
      const result = addressMode === "upload"
        ? await api.uploadAddress(context.session.session_id, addressImage as File)
        : await api.resolveAddress(context.session.session_id, hotelQuery);
      setCandidates(result.candidates);
      setAddressNotice(language === "English" ? result.notice : selectionCopy.addressDescription);
      if (!result.candidates.length) setError(selectionCopy.addressNotFound);
      requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (cause) {
      setError(actionableError(cause, selectionCopy.addressError));
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
      setError(actionableError(cause, selectionCopy.confirmError));
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
      setAddressNotice(language === "English" ? result.notice : selectionCopy.addressDescription);
      requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (cause) {
      setError(actionableError(cause, selectionCopy.demoImageError));
    } finally {
      setLoading(false);
    }
  }

  function fileChanged(event: ChangeEvent<HTMLInputElement>) {
    setAddressImage(event.target.files?.[0] ?? null);
  }

  const addressReady = addressMode === "existing"
    ? Boolean(addressRefId)
    : addressMode === "hotel"
    ? hotelQuery.trim().length >= 2
    : addressMode === "upload"
      ? Boolean(addressImage)
      : Boolean(manualAddress.hotel_name.trim() && manualAddress.road_address.trim().length >= 3);

  return (
    <main className="onboarding-shell profile-only">
      <form className="onboarding-card" onSubmit={checkAddress}>
        <div className="profile-card-heading">
          <div><div className="step-label">{profileCopy.step}</div><h2>{profileCopy.title}</h2></div>
          <button type="button" className="text-button" onClick={() => navigate(editMode ? `/start?edit=1&returnTo=${encodeURIComponent(returnTo)}` : "/start")}><ArrowLeft size={16} /> {profileCopy.changeLocale}</button>
        </div>
        <div className="form-grid">
          <label>{profileCopy.age}<select value={ageBand} onChange={(event) => setAgeBand(event.target.value)}><option>18-24</option><option>25-34</option><option>35-44</option><option>45-54</option><option>55+</option><option value="Prefer not to say">{selectionCopy.preferNot}</option></select></label>
          <label>{profileCopy.religion}<select value={religion} onChange={(event) => setReligion(event.target.value)}><option value="Prefer not to say">{selectionCopy.preferNot}</option>{selectionCopy.religions.map((label, index) => <option value={selectionCopy.religionValues[index]} key={selectionCopy.religionValues[index]}>{label}</option>)}</select></label>
        </div>

        <fieldset>
          <legend>{profileCopy.dietary}</legend>
          <div className="choice-grid">
            <label className={`choice ${vegan ? "selected" : ""}`}><input type="checkbox" checked={vegan} onChange={(event) => setVegan(event.target.checked)} /> {profileCopy.vegan}</label>
            {ALLERGY_CODES.map((code, index) => <label className={`choice ${allergies.has(code) ? "selected" : ""}`} key={code}><input type="checkbox" checked={allergies.has(code)} onChange={() => toggleAllergy(code)} /> {selectionCopy.allergies[index]}</label>)}
          </div>
          {allergies.size > 0 && <label className="severity-select">{profileCopy.severity}<select value={severity} onChange={(event) => setSeverity(event.target.value as "mild" | "moderate" | "severe")}><option value="mild">{selectionCopy.severity[0]}</option><option value="moderate">{selectionCopy.severity[1]}</option><option value="severe">{selectionCopy.severity[2]}</option></select></label>}
        </fieldset>

        <fieldset className="spice-fieldset">
          <legend>{profileCopy.spice}</legend>
          <div className="spice-options">
            {selectionCopy.spice.map((title, index) => {
              const value = index + 1;
              return (
              <label className={spice === value ? "spice-choice selected" : "spice-choice"} key={value}>
                <input type="radio" name="spice" value={value} checked={spice === value} onChange={() => setSpice(Number(value))} />
                <span><strong>{title}</strong></span>
              </label>
              );
            })}
          </div>
        </fieldset>

        <label>{profileCopy.favourites}<input value={favorites} onChange={(event) => setFavorites(event.target.value)} placeholder={selectionCopy.favouritesPlaceholder} /></label>

        <section className="onboarding-address" aria-labelledby="delivery-address-title">
          <div className="address-heading"><MapPin size={19} /><div><p className="eyebrow">{profileCopy.required}</p><h3 id="delivery-address-title">{profileCopy.address}</h3></div></div>
          <p>{selectionCopy.addressDescription}</p>
          {addressMode === "existing" && <article className="current-address"><MapPin size={19} /><div><small>{chatMenuCopy.currentAddress}</small><strong>{addressSummary}</strong></div><button type="button" className="secondary-button" onClick={() => setAddressMode("hotel")}>{chatMenuCopy.changeAddress}</button></article>}
          <div className="address-methods" role="tablist" aria-label={profileCopy.address}>
            <button type="button" className={addressMode === "hotel" ? "active" : ""} onClick={() => { setAddressMode("hotel"); setCandidates([]); }}>{profileCopy.hotel}</button>
            <button type="button" className={addressMode === "upload" ? "active" : ""} onClick={() => { setAddressMode("upload"); setCandidates([]); }}>{profileCopy.image}</button>
            <button type="button" className={addressMode === "manual" ? "active" : ""} onClick={() => { setAddressMode("manual"); setCandidates([]); }}>{profileCopy.road}</button>
          </div>
          {addressMode === "hotel" && <label>{selectionCopy.hotelOrStay}<input value={hotelQuery} onChange={(event) => setHotelQuery(event.target.value)} placeholder="YOBI Myeongdong Hotel" /></label>}
          {addressMode === "upload" && <>
            <label className="upload-zone"><ImageUp size={25} /><strong>{addressImage ? addressImage.name : selectionCopy.chooseImage}</strong><span>PNG · JPEG · WebP · 8MB</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={fileChanged} /></label>
            <button type="button" className="secondary-button full" onClick={() => void loadDemoBooking()} disabled={!consent || loading}>{selectionCopy.useDemoImage}</button>
          </>}
          {addressMode === "manual" && <div className="address-form compact">
            <label>{selectionCopy.hotelOrStay}<input value={manualAddress.hotel_name} onChange={(event) => setManualAddress((value) => ({ ...value, hotel_name: event.target.value }))} /></label>
            <label>{profileCopy.road}<input value={manualAddress.road_address} onChange={(event) => setManualAddress((value) => ({ ...value, road_address: event.target.value }))} placeholder={selectionCopy.fullRoad} /></label>
            <div className="address-form-row"><label>{selectionCopy.postalCode}<input value={manualAddress.postal_code} onChange={(event) => setManualAddress((value) => ({ ...value, postal_code: event.target.value }))} /></label><label>{selectionCopy.city}<input value={manualAddress.city} onChange={(event) => setManualAddress((value) => ({ ...value, city: event.target.value }))} /></label></div>
          </div>}
          {addressNotice && <p className="notice-copy">{addressNotice}</p>}
          <div ref={candidateRef}>
            {candidates.map((candidate) => <article className="address-candidate" key={candidate.place_id}><Hotel size={20} /><div><strong>{candidate.hotel_name}</strong><p>{candidate.road_address}</p><small>{Math.round(candidate.confidence * 100)}% · {selectionCopy.syntheticPlace}</small></div><button type="button" className="primary-button" onClick={() => void confirmCandidate(candidate)} disabled={loading}>{selectionCopy.confirmStart}</button></article>)}
          </div>
        </section>

        <label className="consent-row"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>{profileCopy.consent}</span></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button full large" disabled={!consent || !addressReady || loading}>
          {loading ? selectionCopy.checkingContext : editMode && addressMode === "existing" ? chatMenuCopy.saveChanges : addressMode === "manual" ? selectionCopy.saveStart : profileCopy.check}<ArrowRight size={19} />
        </button>
      </form>
    </main>
  );
}
