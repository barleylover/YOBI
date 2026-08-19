import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { api } from "../src/lib/api";
import { LocalePage } from "../src/routes/LocalePage";
import { OnboardingPage } from "../src/routes/OnboardingPage";
import { WelcomePage } from "../src/routes/WelcomePage";
import { emptyCriteria, useSessionStore } from "../src/stores/session";
import type { AddressCandidate, Profile, Session } from "../src/types";

const profile: Profile = {
  profile_id: "profile_onboarding_test",
  preferred_language: "English",
  nationality: "United States",
  country_code: "US",
  religion_selection: "Prefer not to say",
  spice_tolerance: 1,
  dietary_rules: [],
  favorite_foods: [],
  age_band: "Prefer not to say",
  consent_demo_data: true,
  remember_profile: false,
};

const session: Session = {
  session_id: "session_onboarding_test",
  profile_id: profile.profile_id,
  state: "DISCOVERY",
  state_version: 0,
};

const candidate: AddressCandidate = {
  place_id: "address_candidate_1",
  hotel_name: "YOBI Myeongdong Hotel",
  road_address: "123 YOBI-ro, Jung-gu, Seoul",
  postal_code: "04500",
  city: "Seoul",
  delivery_hint: "Front desk",
  confidence: 1,
  source: "YOBI_DEMO",
  needs_confirmation: true,
  candidate_token: "address-candidate-token",
};

function LocationEcho() {
  const location = useLocation();
  return <div>Profile route {location.search}</div>;
}

function resetStore() {
  useSessionStore.setState({
    draftLanguage: "English",
    draftCountry: "United States",
    profile: null,
    session: null,
    addressRefId: "",
    addressSummary: "",
    cartQuantity: 0,
    draftCriteria: emptyCriteria(),
    committedCriteria: null,
    criteriaVersion: 0,
    recommendationPhase: "SELECTING",
    pendingRecommendation: null,
    latestRecommendation: null,
  });
}

function renderWelcome() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<WelcomePage />} />
        <Route path="/start" element={<LocalePage />} />
        <Route path="/profile" element={<div>Profile route</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("welcome and address flow", () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.scrollTo = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    resetStore();
    document.documentElement.lang = "en";
    document.documentElement.dir = "ltr";
  });

  it("selects Korean through the locale screen and applies it immediately", async () => {
    resetStore();
    renderWelcome();

    expect(screen.getByRole("heading", { name: /Korean food/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Language.*English/ }));
    fireEvent.click(screen.getByRole("button", { name: /한국어.*Korean/ }));
    await waitFor(() => expect(document.documentElement).toHaveAttribute("lang", "ko"));
    fireEvent.click(document.querySelector<HTMLButtonElement>(".v2-appbar-action")!);

    expect(await screen.findByRole("heading", { name: /한국 음식/ })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("lang", "ko");
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    expect(useSessionStore.getState().draftLanguage).toBe("한국어");

    fireEvent.click(screen.getByRole("button", { name: "시작하기" }));
    expect(await screen.findByText("Profile route")).toBeInTheDocument();
  });

  it("keeps Arabic selectable while displaying the English LTR fallback", async () => {
    renderWelcome();
    fireEvent.click(screen.getByRole("button", { name: /Language.*English/ }));
    fireEvent.click(screen.getByRole("button", { name: /العربية.*Arabic/ }));
    await waitFor(() => expect(document.documentElement).toHaveAttribute("lang", "en"));
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    fireEvent.click(document.querySelector<HTMLButtonElement>(".v2-appbar-action")!);

    expect(await screen.findByRole("heading", { name: /Korean food/ })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("lang", "en");
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    expect(screen.getByRole("button", { name: "Get started" })).toBeInTheDocument();
    expect(useSessionStore.getState().draftLanguage).toBe("العربية");
  });

  it("starts a new journey in the newly selected language instead of a stale profile language", async () => {
    useSessionStore.setState({
      profile: { ...profile, preferred_language: "한국어" },
      session,
      draftLanguage: "日本語",
      draftCountry: "Japan",
    });
    renderWelcome();

    fireEvent.click(screen.getByRole("button", { name: "始める" }));

    expect(await screen.findByText("Profile route")).toBeInTheDocument();
    expect(useSessionStore.getState().profile).toBeNull();
    expect(useSessionStore.getState().session).toBeNull();
    expect(useSessionStore.getState().draftLanguage).toBe("日本語");
    expect(useSessionStore.getState().draftCountry).toBe("Japan");
  });

  it("redirects the retired start route safely while preserving edit and return parameters", async () => {
    resetStore();
    useSessionStore.setState({ profile, session });
    render(
      <MemoryRouter initialEntries={[`/start?edit=1&returnTo=${encodeURIComponent(`/chat/${session.session_id}`)}`]}>
        <Routes>
          <Route path="/start" element={<LocalePage />} />
          <Route path="/" element={<WelcomePage />} />
          <Route path="/profile" element={<LocationEcho />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Done" }).at(-1)!);
    expect(await screen.findByRole("heading", { name: /Korean food/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Get started" }));
    expect(await screen.findByText(/Profile route \?edit=1/)).toHaveTextContent(
      `returnTo=${encodeURIComponent(`/chat/${session.session_id}`)}`,
    );
  });

  it("creates a neutral profile and confirms a searched address without user-facing boundary labels", async () => {
    resetStore();
    const createProfile = vi.spyOn(api, "createProfile").mockResolvedValue(profile);
    vi.spyOn(api, "createSession").mockResolvedValue(session);
    vi.spyOn(api, "resolveAddress").mockResolvedValue({
      candidates: [candidate],
      low_confidence: false,
      notice: "Internal fixture notice",
    });
    vi.spyOn(api, "confirmAddress").mockResolvedValue({ address_ref_id: "address_ref_1" });

    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <Routes>
          <Route path="/profile" element={<OnboardingPage />} />
          <Route path="/chat/:sessionId" element={<div>Chat route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByText(/Age range|Religion|Favourite comfort foods/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.trim())).toEqual(["Search address", "Booking image"]);
    fireEvent.click(screen.getByRole("checkbox", { name: /use this address for this session only/i }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(createProfile).toHaveBeenCalledWith(expect.objectContaining({
      country_code: "US",
      age_band: "Prefer not to say",
      religion_selection: "Prefer not to say",
      dietary_rules: [],
      favorite_foods: [],
    })));
    expect(screen.queryByText("Internal fixture notice")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/demo|mock|synthetic/i);
    fireEvent.click(await screen.findByRole("button", { name: "Continue with this address" }));
    expect(await screen.findByText("Chat route")).toBeInTheDocument();
    expect(useSessionStore.getState().addressRefId).toBe("address_ref_1");
  });

  it("resolves the sample booking image through the same address confirmation flow", async () => {
    resetStore();
    vi.spyOn(api, "createProfile").mockResolvedValue(profile);
    vi.spyOn(api, "createSession").mockResolvedValue(session);
    const uploadAddress = vi.spyOn(api, "uploadAddress").mockResolvedValue({
      candidates: [candidate],
      low_confidence: false,
      notice: "Internal fixture notice",
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob(["image"], { type: "image/png" }))));

    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <Routes><Route path="/profile" element={<OnboardingPage />} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /use this address for this session only/i }));
    fireEvent.click(screen.getByRole("tab", { name: "Booking image" }));
    fireEvent.click(screen.getByRole("button", { name: "Use the sample booking image" }));
    await waitFor(() => expect(uploadAddress).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({ type: "image/png" }),
    ));
    expect(await screen.findByText(candidate.road_address)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/demo|mock|synthetic/i);
  });
});
