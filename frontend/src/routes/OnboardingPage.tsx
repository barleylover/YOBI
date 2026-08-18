import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Building2, Check, ImageUp, Info, MapPin, Search } from "lucide-react";
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
  const [selectedCandidate, setSelectedCandidate] = useState<AddressCandidate | null>(null);
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

  function showCandidates(result: { candidates: AddressCandidate[]; notice?: string }) {
    setCandidates(result.candidates);
    setSelectedCandidate(result.candidates[0] ?? null);
    setAddressNotice(language === "English" ? (result.notice || productCopy.address.demoNotice) : productCopy.address.demoNotice);
    if (!result.candidates.length) setError(selectionCopy.addressNotFound);
    requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }

  async function findAddress() {
    setLoading(true);
    setError("");
    setCandidates([]);
    setSelectedCandidate(null);
    try {
      const context = await ensureContext();
      const result = addressMode === "upload"
        ? await api.uploadAddress(context.session.session_id, addressImage as File)
        : await api.resolveAddress(context.session.session_id, searchQuery || "YOBI demo address");
      showCandidates(result);
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
      const context = await ensureContext();
      const result = await api.confirmAddress(context.session.session_id, candidate);
      finish(result.address_ref_id, `${candidate.hotel_name} · ${candidate.road_address}`, context.session);
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, selectionCopy.confirmError) : selectionCopy.confirmError);
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedCandidate) {
      await confirmCandidate(selectedCandidate);
      return;
    }
    await findAddress();
  }

  async function loadDemoBooking() {
    setLoading(true);
    setError("");
    setCandidates([]);
    setSelectedCandidate(null);
    try {
      const context = await ensureContext();
      const response = await fetch("/demo-booking.png");
      const blob = await response.blob();
      const result = await api.uploadAddress(
        context.session.session_id,
        new File([blob], "yobi-demo-booking.png", { type: "image/png" }),
      );
      showCandidates(result);
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, selectionCopy.demoImageError) : selectionCopy.demoImageError);
    } finally {
      setLoading(false);
    }
  }

  function fileChanged(event: ChangeEvent<HTMLInputElement>) {
    setAddressImage(event.target.files?.[0] ?? null);
    setCandidates([]);
    setSelectedCandidate(null);
  }

  const addressReady = addressMode === "search" ? searchQuery.trim().length > 0 : Boolean(addressImage);
  const submitEnabled = consent && (selectedCandidate !== null || addressReady) && !loading;

  return (
    <main className="yv2-flow-shell yv2-address-shell">
      <form className="yv2-flow-card yv2-address-card" onSubmit={(event) => void submit(event)}>
        <header className="yv2-step-header">
          <button
            type="button"
            className="yv2-icon-button"
            aria-label={productCopy.address.changeLocale}
            onClick={() => navigate(editMode ? `/?edit=1&returnTo=${encodeURIComponent(returnTo)}` : "/")}
          >
            <ArrowLeft size={20} />
          </button>
          <div><span>1 / 4</span><i><b /></i></div>
        </header>

        <section className="yv2-address-content">
          <div className="yv2-screen-title">
            <h1>{productCopy.address.title}</h1>
            <p>{productCopy.address.description}</p>
          </div>

          {editMode && addressRefId && (
            <article className="yv2-current-address">
              <MapPin size={19} />
              <div><small>{productCopy.address.currentAddress}</small><strong>{addressSummary}</strong></div>
              <button type="button" onClick={() => void keepCurrentAddress()} disabled={!consent || loading}>{productCopy.address.keepAddress}</button>
            </article>
          )}

          <div className="yv2-segmented-control" role="tablist" aria-label={productCopy.address.title}>
            <button
              type="button"
              role="tab"
              aria-selected={addressMode === "search"}
              onClick={() => { setAddressMode("search"); setCandidates([]); setSelectedCandidate(null); }}
            ><Search size={16} /> {productCopy.address.search}</button>
            <button
              type="button"
              role="tab"
              aria-selected={addressMode === "upload"}
              onClick={() => { setAddressMode("upload"); setCandidates([]); setSelectedCandidate(null); }}
            ><ImageUp size={16} /> {productCopy.address.bookingImage}</button>
          </div>

          {addressMode === "search" && (
            <label className="yv2-address-search" role="tabpanel">
              <span>{productCopy.address.searchLabel}</span>
              <div><Search size={18} /><input value={searchQuery} onChange={(event) => { setSearchQuery(event.target.value); setCandidates([]); setSelectedCandidate(null); }} placeholder={productCopy.address.searchPlaceholder} /></div>
            </label>
          )}

          {addressMode === "upload" && (
            <div className="yv2-upload-panel" role="tabpanel">
              <label className="yv2-upload-zone">
                <ImageUp size={26} />
                <strong>{addressImage ? addressImage.name : productCopy.address.chooseImage}</strong>
                <span>PNG · JPEG · WebP · 8MB</span>
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={fileChanged} />
              </label>
              <button type="button" className="yv2-secondary-button" onClick={() => void loadDemoBooking()} disabled={!consent || loading}>
                {productCopy.address.useDemoImage}
              </button>
            </div>
          )}

          <div ref={candidateRef} className="yv2-address-results">
            {candidates.map((candidate) => {
              const selected = selectedCandidate?.place_id === candidate.place_id;
              return (
                <button
                  type="button"
                  className={selected ? "yv2-address-candidate selected" : "yv2-address-candidate"}
                  aria-pressed={selected}
                  onClick={() => setSelectedCandidate(candidate)}
                  key={candidate.place_id}
                >
                  <span className="yv2-address-building"><Building2 size={19} /></span>
                  <span><strong>{candidate.hotel_name}</strong><small>{candidate.road_address}</small></span>
                  <span className="yv2-address-check">{selected && <Check size={15} />}</span>
                </button>
              );
            })}
          </div>

          <label className="yv2-consent-row">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <span>{productCopy.address.consent}</span>
          </label>

          <aside className="yv2-info-banner"><Info size={17} /><span>{addressNotice || productCopy.address.demoNotice}</span></aside>
          {error && <p className="yv2-error-banner" role="alert">{error}</p>}
        </section>

        <footer className="yv2-sticky-action">
          <button className="yv2-primary-button" disabled={!submitEnabled}>
            {loading ? selectionCopy.checkingContext : selectedCandidate ? productCopy.address.select : productCopy.address.check}
            <ArrowRight size={19} />
          </button>
        </footer>
      </form>
    </main>
  );
}
