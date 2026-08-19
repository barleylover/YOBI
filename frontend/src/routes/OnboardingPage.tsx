import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { asSupportedLanguage, countryCode } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getRedesignCopy } from "../lib/redesignI18n";
import { useSessionStore } from "../stores/session";
import type { AddressCandidate, Profile, Session } from "../types";

type AddressMode = "search" | "upload";
type CreatedContext = { profile: Profile; session: Session };

export function OnboardingPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { selectionCopy, language, selectedLanguage } = useI18n();
  const supportedLanguage = asSupportedLanguage(language);
  const productCopy = getProductCopy(supportedLanguage);
  const redesignCopy = getRedesignCopy(supportedLanguage);
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
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [addressNotice, setAddressNotice] = useState("");
  const [createdContext, setCreatedContext] = useState<CreatedContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function ensureContext(): Promise<CreatedContext> {
    if (createdContext) return createdContext;
    const body = {
      preferred_language: selectedLanguage,
      nationality: country,
      country_code: countryCode(country),
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
      setError(actionableError(cause, selectionCopy.addressError, language));
    } finally {
      setLoading(false);
    }
  }

  function applyCandidates(result: { candidates: AddressCandidate[]; notice?: string | null }) {
    setCandidates(result.candidates);
    setSelectedCandidateId(result.candidates[0]?.place_id ?? "");
    setAddressNotice(productCopy.address.demoNotice);
    if (!result.candidates.length) setError(selectionCopy.addressNotFound);
    requestAnimationFrame(() => candidateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }

  async function findAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!consent || loading) return;
    setLoading(true);
    setError("");
    setCandidates([]);
    setSelectedCandidateId("");
    try {
      const context = await ensureContext();
      const result = addressMode === "upload"
        ? await api.uploadAddress(context.session.session_id, addressImage as File)
        : await api.resolveAddress(context.session.session_id, searchQuery || "YOBI Myeongdong Hotel");
      applyCandidates(result);
    } catch (cause) {
      setError(actionableError(cause, selectionCopy.addressError, language));
    } finally {
      setLoading(false);
    }
  }

  async function confirmSelectedCandidate() {
    const candidate = candidates.find((item) => item.place_id === selectedCandidateId);
    if (!candidate || !createdContext) return;
    setLoading(true);
    setError("");
    try {
      const result = await api.confirmAddress(createdContext.session.session_id, candidate);
      finish(result.address_ref_id, `${candidate.hotel_name} · ${candidate.road_address}`, createdContext.session);
    } catch (cause) {
      setError(actionableError(cause, selectionCopy.confirmError, language));
    } finally {
      setLoading(false);
    }
  }

  async function loadDemoBooking() {
    setLoading(true);
    setError("");
    setCandidates([]);
    setSelectedCandidateId("");
    try {
      const context = await ensureContext();
      const response = await fetch("/demo-booking.png");
      const blob = await response.blob();
      const result = await api.uploadAddress(
        context.session.session_id,
        new File([blob], "yobi-demo-booking.png", { type: "image/png" }),
      );
      applyCandidates(result);
    } catch (cause) {
      setError(actionableError(cause, selectionCopy.demoImageError, language));
    } finally {
      setLoading(false);
    }
  }

  function fileChanged(event: ChangeEvent<HTMLInputElement>) {
    setAddressImage(event.target.files?.[0] ?? null);
    setCandidates([]);
    setSelectedCandidateId("");
  }

  function switchMode(mode: AddressMode) {
    setAddressMode(mode);
    setCandidates([]);
    setSelectedCandidateId("");
  }

  return (
    <main className="v2-screen subtle">
      <header className="v2-appbar">
        <button
          type="button"
          className="v2-icon-button"
          aria-label={redesignCopy.back}
          onClick={() => navigate(editMode ? `/?edit=1&returnTo=${encodeURIComponent(returnTo)}` : "/")}
        >
          <img src="/figma/back-chevron.svg" alt="" width={9} height={16} />
        </button>
        <p className="v2-appbar-step">{redesignCopy.stepDelivery}</p>
      </header>
      <div className="v2-progress" aria-hidden="true">
        <span className="active" /><span /><span />
      </div>

      <form className="v2-body" style={{ gap: 18, paddingTop: 22 }} onSubmit={findAddress}>
        <div className="v2-heading">
          <h1>{productCopy.address.title}</h1>
          <p>{productCopy.address.description}</p>
        </div>

        {editMode && addressRefId && (
          <div className="v2-select-card selected">
            <div>
              <strong>{addressSummary}</strong>
              <small>{productCopy.address.currentAddress}</small>
            </div>
            <button
              type="button"
              className="v2-search-submit"
              onClick={() => void keepCurrentAddress()}
              disabled={!consent || loading}
            >
              {productCopy.address.keepAddress}
            </button>
          </div>
        )}

        <div className="v2-seg-tabs" role="tablist" aria-label={productCopy.address.title}>
          <button
            type="button"
            role="tab"
            aria-selected={addressMode === "search"}
            onClick={() => switchMode("search")}
          >
            {productCopy.address.search}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={addressMode === "upload"}
            onClick={() => switchMode("upload")}
          >
            {productCopy.address.bookingImage}
          </button>
        </div>

        {addressMode === "search" && (
          <div className="v2-search-field bordered" role="tabpanel">
            <img src="/figma/search-icon.svg" alt="" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={productCopy.address.searchPlaceholder}
              aria-label={productCopy.address.searchLabel}
            />
            <button type="submit" className="v2-search-submit" disabled={!consent || loading || !searchQuery.trim()}>
              {redesignCopy.search}
            </button>
          </div>
        )}

        {addressMode === "upload" && (
          <div role="tabpanel" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <label className="v2-upload-zone">
              <strong>{addressImage ? addressImage.name : productCopy.address.chooseImage}</strong>
              <span>PNG · JPEG · WebP · 8MB</span>
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={fileChanged} />
            </label>
            <div style={{ display: "flex", gap: 10 }}>
              <button
                type="submit"
                className="v2-cta compact secondary"
                disabled={!consent || loading || !addressImage}
              >
                {productCopy.address.check}
              </button>
              <button
                type="button"
                className="v2-cta compact secondary"
                onClick={() => void loadDemoBooking()}
                disabled={!consent || loading}
              >
                {productCopy.address.useDemoImage}
              </button>
            </div>
          </div>
        )}

        {loading && <p className="v2-status" role="status">{selectionCopy.checkingContext}</p>}
        {addressNotice && candidates.length > 0 && <p className="v2-status" role="status">{addressNotice}</p>}

        {candidates.length > 0 && (
          <div className="v2-candidates" ref={candidateRef}>
            <p>{redesignCopy.matchingAddresses(candidates.length)}</p>
            {candidates.map((candidate) => {
              const selected = candidate.place_id === selectedCandidateId;
              return (
                <button
                  type="button"
                  key={candidate.place_id}
                  className={selected ? "v2-select-card selected" : "v2-select-card"}
                  aria-pressed={selected}
                  onClick={() => setSelectedCandidateId(candidate.place_id)}
                  disabled={loading}
                >
                  <div>
                    <strong>{candidate.hotel_name}</strong>
                    <small>{candidate.road_address}</small>
                  </div>
                  {selected
                    ? <img className="check" src="/figma/check-circle.svg" alt="" />
                    : <img className="chevron" src="/figma/right-chevron.svg" alt="" />}
                </button>
              );
            })}
          </div>
        )}

        <label className="v2-consent">
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
          <span className="box" aria-hidden="true" />
          <span>{productCopy.address.consent}</span>
        </label>

        <div className="v2-banner">
          <p>{redesignCopy.demoDeliveryBanner}</p>
        </div>

        {error && <p className="v2-error" role="alert">{error}</p>}
      </form>

      <footer className="v2-cta-footer">
        <button
          type="button"
          className="v2-cta"
          onClick={() => void confirmSelectedCandidate()}
          disabled={!consent || loading || !selectedCandidateId}
        >
          {redesignCopy.continueWithAddress}
        </button>
      </footer>
    </main>
  );
}
