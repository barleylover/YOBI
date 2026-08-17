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
  place_id: "demo_address_1",
  hotel_name: "YOBI Myeongdong Hotel",
  road_address: "123 YOBI-ro, Jung-gu, Seoul",
  postal_code: "04500",
  city: "Seoul",
  delivery_hint: "Front desk",
  confidence: 1,
  source: "YOBI_DEMO",
  needs_confirmation: true,
  candidate_token: "demo-address-token",
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

describe("merged welcome and neutral demo address flow", () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    resetStore();
    document.documentElement.lang = "en";
    document.documentElement.dir = "ltr";
  });

  it("keeps language and country on the welcome screen and applies the language immediately", async () => {
    resetStore();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<WelcomePage />} />
          <Route path="/profile" element={<div>Profile route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /Hi, I’m YOBI/ })).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(screen.getByLabelText("Language").querySelectorAll("option")).toHaveLength(16);

    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "한국어" } });
    expect(await screen.findByRole("heading", { name: /안녕하세요, YOBI예요/ })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("lang", "ko");
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    expect(useSessionStore.getState().draftLanguage).toBe("한국어");

    fireEvent.click(screen.getByRole("button", { name: /시작하기/ }));
    expect(await screen.findByText("Profile route")).toBeInTheDocument();
  });

  it("switches the merged entry to Arabic RTL without retaining English product copy", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<WelcomePage />} />
          <Route path="/profile" element={<div>مسار الملف</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "العربية" } });
    expect(await screen.findByRole("heading", { name: /مرحبًا، أنا YOBI/ })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("lang", "ar");
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("button", { name: /ابدأ/ })).toBeInTheDocument();
    expect(screen.queryByText("Order K-food with context, not guesswork.")).not.toBeInTheDocument();
    expect(useSessionStore.getState().draftCountry).toBe("Saudi Arabia");
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

    expect(await screen.findByRole("heading", { name: /Hi, I’m YOBI/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Get started/ }));
    expect(await screen.findByText(/Profile route \?edit=1/)).toHaveTextContent(
      `returnTo=${encodeURIComponent(`/chat/${session.session_id}`)}`,
    );
  });

  it("removes demographic questions and sends a neutral profile before search address confirmation", async () => {
    resetStore();
    const createProfile = vi.spyOn(api, "createProfile").mockResolvedValue(profile);
    vi.spyOn(api, "createSession").mockResolvedValue(session);
    vi.spyOn(api, "resolveAddress").mockResolvedValue({
      candidates: [candidate],
      low_confidence: false,
      notice: "Prepared demo address",
    });
    vi.spyOn(api, "confirmAddress").mockResolvedValue({ address_ref_id: "address_ref_demo" });

    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <Routes>
          <Route path="/profile" element={<OnboardingPage />} />
          <Route path="/chat/:sessionId" element={<div>Chat route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByText(/Age range|Religion|Favourite comfort foods/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.trim())).toEqual(expect.arrayContaining(["Search", "Booking image"]));
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    fireEvent.click(screen.getByRole("checkbox", { name: /neutral profile/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find the demo address" }));

    await waitFor(() => expect(createProfile).toHaveBeenCalledWith(expect.objectContaining({
      age_band: "Prefer not to say",
      religion_selection: "Prefer not to say",
      dietary_rules: [],
      favorite_foods: [],
    })));
    fireEvent.click(await screen.findByRole("button", { name: "Select this address" }));
    expect(await screen.findByText("Chat route")).toBeInTheDocument();
    expect(useSessionStore.getState().addressRefId).toBe("address_ref_demo");
  });

  it("resolves the booking-image path to the same prepared demo address", async () => {
    resetStore();
    vi.spyOn(api, "createProfile").mockResolvedValue(profile);
    vi.spyOn(api, "createSession").mockResolvedValue(session);
    const uploadAddress = vi.spyOn(api, "uploadAddress").mockResolvedValue({
      candidates: [candidate],
      low_confidence: false,
      notice: "Prepared demo address",
    });
    vi.spyOn(api, "confirmAddress").mockResolvedValue({ address_ref_id: "address_ref_demo" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob(["demo"], { type: "image/png" }))));

    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <Routes>
          <Route path="/profile" element={<OnboardingPage />} />
          <Route path="/chat/:sessionId" element={<div>Chat route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /neutral profile/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Booking image" }));
    fireEvent.click(screen.getByRole("button", { name: "Use the demo booking image" }));
    await waitFor(() => expect(uploadAddress).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({ name: "yobi-demo-booking.png" }),
    ));
    expect(await screen.findByText(candidate.road_address)).toBeInTheDocument();
  });
});
