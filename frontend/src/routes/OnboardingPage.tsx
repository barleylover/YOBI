import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ImageUp, MapPin, Search } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { asSupportedLanguage } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { useSessionStore } from "../stores/session";
import type { AddressCandidate, Profile, Session } from "../types";

type AddressMode = "search" | "upload";
type CreatedContext = { profile: Profile; session: Session };

export function OnboardingPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { selectionCopy, language } = useI18n();
  const productCopy = getProductCopy(asSupportedLanguage(language));
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
  const [consent, setConsent] = useState(profile?.consent_demo_data ?? false);
  const [addressMode, setAddressMode] = useState<AddressMode>("search");
  const [searchQuery, setSearchQuery] = useState("YOBI Myeongdong Hotel");
  const [addressImage, setAddressImage] = useState<File | null>(null);
  const [candidates, setCandidates] = useState<AddressCandidate[]>([]);
  const [addressNotice, setAddressNotice] = useState("");
  const [createdContext, setCreatedContext] = useState<CreatedContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function ensureContext(): Promise<CreatedContext> {
    if (createdContext) return createdContext;
    const body = {
      preferred_language: language,
      nationality: country,
      age_band: "Prefer not to say",
      religion_selection: "Prefer not to say",
      dietary_rules: [],
      spice_tolerance: 1,
      favorite_foods: [],
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

  function finish(nextAddressRefId: string, summary: string, activeSession: Session) {
    setDeliveryAddress(nextAddressRefId, summary);
    navigate(editMode ? returnTo : `/chat/${activeSession.session_id}`);
  }

  async function keepCurrentAddress() {
    if (!addressRefId) return;
    setLoading(true);
    setError("");
    try {
      const context = await ensureContext();
      finish(addressRefId, addressSummary, context.session);
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, selectionCopy.addressError) : selectionCopy.addressError);
    } finally {
      setLoading(false);
    }
  }

  async function findAddress() {
    setLoading(true);
    setError("");
    setCandidates([]);
    try {
      const context = await ensureContext();
      const result = addressMode === "upload"
        ? await api.uploadAddress(context.session.session_id, addressImage as File)
        : await api.resolveAddress(context.session.session_id, searchQuery || "YOBI demo address");
      setCandidates(result.candidates);
      setAddressNotice(language === "English" ? (result.notice || productCopy.address.demoNotice) : productCopy.address.demoNotice);
      if (!result.candidates.length) setError(selectionCopy.addressNotFound);
      requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, selectionCopy.addressError) : selectionCopy.addressError);
    } finally {
      setLoading(false);
    }
  }

  async function confirmCandidate(candidate: AddressCandidate) {
    setLoading(true);
    setError("");
    try {
      const context = createdContext ?? await ensureContext();
      const result = await api.confirmAddress(context.session.session_id, candidate);
      finish(result.address_ref_id, `${candidate.hotel_name} · ${candidate.road_address}`, context.session);
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, selectionCopy.confirmError) : selectionCopy.confirmError);
    } finally {
      setLoading(false);
    }
  }

  async function submitAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (candidates.length > 0) {
      await confirmCandidate(candidates[0]);
      return;
    }
    await findAddress();
  }

  async function loadDemoBooking() {
    setLoading(true);
    setError("");
    setCandidates([]);
    try {
      const context = await ensureContext();
      const response = await fetch("/demo-booking.png");
      const blob = await response.blob();
      const result = await api.uploadAddress(
        context.session.session_id,
        new File([blob], "yobi-demo-booking.png", { type: "image/png" }),
      );
      setCandidates(result.candidates);
      setAddressNotice(language === "English" ? (result.notice || productCopy.address.demoNotice) : productCopy.address.demoNotice);
      if (!result.candidates.length) setError(selectionCopy.addressNotFound);
      requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, selectionCopy.demoImageError) : selectionCopy.demoImageError);
    } finally {
      setLoading(false);
    }
  }

  function fileChanged(event: ChangeEvent<HTMLInputElement>) {
    setAddressImage(event.target.files?.[0] ?? null);
    setCandidates([]);
  }

  const addressReady = addressMode === "search" ? searchQuery.trim().length > 0 : Boolean(addressImage);

  return (
    <main className="onboarding-shell profile-only figma-address-shell">
      <form className="onboarding-card simplified-address-card figma-address-card" onSubmit={submitAddress}>
        <header className="mobile-step-header">
          <button
            type="button"
            className="mobile-step-back"
            aria-label={productCopy.address.changeLocale}
            onClick={() => navigate(editMode ? `/?edit=1&returnTo=${encodeURIComponent(returnTo)}` : "/")}
          >
            <ChevronLeft size={20} />
          </button>
          <strong>{productCopy.address.step}</strong>
        </header>
        <div className="mobile-step-progress" aria-hidden="true"><span className="active" /><span /><span /></div>

        <section className="address-screen-heading">
          <h1>{productCopy.address.title}</h1>
          <p className="address-intro">{productCopy.address.description}</p>
        </section>

        <section className="onboarding-address" aria-labelledby="delivery-address-title">
          <h2 id="delivery-address-title" className="visually-hidden">{productCopy.address.title}</h2>

          {editMode && addressRefId && (
            <article className="current-address">
              <MapPin size={19} />
              <div><small>{productCopy.address.currentAddress}</small><strong>{addressSummary}</strong></div>
              <button type="button" className="secondary-button" onClick={() => void keepCurrentAddress()} disabled={!consent || loading}>
                {productCopy.address.keepAddress}
              </button>
            </article>
          )}

          <div className="address-methods" role="tablist" aria-label={productCopy.address.title}>
            <button
              type="button"
              role="tab"
              aria-selected={addressMode === "search"}
              className={addressMode === "search" ? "active" : ""}
              onClick={() => { setAddressMode("search"); setCandidates([]); }}
            ><Search size={16} /> {productCopy.address.search}</button>
            <button
              type="button"
              role="tab"
              aria-selected={addressMode === "upload"}
              className={addressMode === "upload" ? "active" : ""}
              onClick={() => { setAddressMode("upload"); setCandidates([]); }}
            ><ImageUp size={16} /> {productCopy.address.bookingImage}</button>
          </div>

          {addressMode === "search" && (
            <label role="tabpanel">
              {productCopy.address.searchLabel}
              <div className="address-search-field"><Search size={18} /><input value={searchQuery} onChange={(event) => { setSearchQuery(event.target.value); setCandidates([]); }} placeholder={productCopy.address.searchPlaceholder} /></div>
            </label>
          )}

          {addressMode === "upload" && (
            <div role="tabpanel">
              <label className="upload-zone">
                <ImageUp size={25} />
                <strong>{addressImage ? addressImage.name : productCopy.address.chooseImage}</strong>
                <span>PNG · JPEG · WebP · 8MB</span>
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={fileChanged} />
              </label>
              <button type="button" className="secondary-button full" onClick={() => void loadDemoBooking()} disabled={!consent || loading}>
                {productCopy.address.useDemoImage}
              </button>
            </div>
          )}

          <p className="notice-copy" role="status">{addressNotice || productCopy.address.demoNotice}</p>
          <div ref={candidateRef} className="address-results">
            {candidates.map((candidate) => (
              <article className="address-candidate" key={candidate.place_id}>
                <div><strong>{candidate.hotel_name}</strong><p>{candidate.road_address}</p></div>
                <button type="button" className="address-candidate-select" onClick={() => void confirmCandidate(candidate)} disabled={loading}>
                  <span className="visually-hidden">{productCopy.address.select}</span><ChevronRight size={18} />
                </button>
              </article>
            ))}
          </div>
        </section>

        <label className="consent-row">
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
          <span>{productCopy.address.consent}</span>
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button full large address-submit" disabled={!consent || (!candidates.length && !addressReady) || loading}>
          {loading ? selectionCopy.checkingContext : candidates.length ? productCopy.address.select : productCopy.address.check}
        </button>
      </form>
    </main>
  );
}
