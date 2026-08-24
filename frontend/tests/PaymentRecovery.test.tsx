import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import App from "../src/App";
import { api } from "../src/lib/api";
import { HandoffPage } from "../src/routes/HandoffPage";
import { useSessionStore } from "../src/stores/session";
import type { CartPreview, Profile, Session } from "../src/types";

const profile: Profile = {
  profile_id: "profile_handoff_test",
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
  session_id: "session_handoff_test",
  profile_id: profile.profile_id,
  state: "ORDER_BUILDING",
  state_version: 4,
};

const cart: CartPreview = {
  cart_id: "cart_handoff_test",
  version: 2,
  items: [{
    cart_item_id: "cart_item_1",
    menu_id: "menu_1",
    menu_name: "YOBI gimbap",
    menu_name_ko: "요비 김밥",
    quantity: 1,
    unit_price: 9000,
    options: [],
    line_total: 9000,
    user_note: "Please leave the sauce on the side.",
    korean_note: "소스는 따로 담아 주세요.",
  }],
  subtotal: 9000,
  delivery_fee: 2000,
  total_price: 11000,
  missing_slots: [],
  dietary_warnings: [],
  minimum_order_amount: 0,
  minimum_order_shortfall: 0,
  delivery_preference: {
    handoff_method: "front_desk",
    cutlery: true,
    ring_bell: false,
    front_desk: true,
    user_note: "Please leave it at the hotel front desk. Please include disposable cutlery. Please do not ring the bell.",
    korean_note: "호텔 프런트에 맡겨 주세요. 일회용 수저와 포크를 포함해 주세요. 벨을 누르지 말아 주세요.",
    back_translation: "Please leave it at the hotel front desk.",
  },
  ready_to_checkout: true,
  confirmed: true,
};

describe("Yogiyo handoff", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    useSessionStore.getState().clear();
  });

  it("uses one Yogiyo CTA without payment or order creation", async () => {
    useSessionStore.setState({ profile, session, addressRefId: "address_handoff_test" });
    vi.spyOn(api, "getCart").mockResolvedValue(cart);
    const createCheckout = vi.spyOn(api, "createCheckout");
    const paymentSuccess = vi.spyOn(api, "paymentSuccess");

    render(
      <MemoryRouter initialEntries={["/handoff"]}>
        <Routes>
          <Route path="/handoff" element={<HandoffPage />} />
          <Route path={`/chat/${session.session_id}`} element={<div>YOBI chat</div>} />
          <Route path="/start" element={<div>Country and language settings</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Ready to order" })).toBeInTheDocument();
    expect(screen.getByText(/Restaurant request:/)).toBeInTheDocument();
    expect(screen.getByText(/Please leave the sauce on the side/)).toBeInTheDocument();
    expect(screen.getByText("소스는 따로 담아 주세요.")).toBeInTheDocument();
    expect(screen.getByText("Courier handoff request")).toBeInTheDocument();
    expect(screen.getByText(/hotel front desk.*disposable cutlery/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Back to dishes" })).toHaveLength(2);
    expect(document.body.textContent).not.toMatch(/demo|mock|synthetic/i);
    fireEvent.click(screen.getByRole("button", { name: /Open in Yogiyo/ }));
    expect(await screen.findByRole("heading", { name: "Continue your order in Yogiyo" })).toBeInTheDocument();
    expect(screen.getByText("Review the basket, then continue to Yogiyo.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to dishes" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Back to YOBI" })).toHaveLength(1);
    expect(createCheckout).not.toHaveBeenCalled();
    expect(paymentSuccess).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^Pay/ })).not.toBeInTheDocument();
    expect(document.querySelector(".post-address-nav")).not.toBeInTheDocument();
    sessionStorage.setItem("yobi-pending-test", "stale");
    fireEvent.click(screen.getByText("Back to YOBI"));
    expect(await screen.findByText("Country and language settings")).toBeInTheDocument();
    await waitFor(() => expect(useSessionStore.getState().session).toBeNull());
    expect(sessionStorage.getItem("yobi-pending-test")).toBeNull();
    expect(useSessionStore.getState().draftLanguage).toBe("English");
  });

  it("redirects legacy payment URLs to the same handoff without a payment screen", async () => {
    useSessionStore.setState({ profile, session, addressRefId: "address_handoff_test" });
    vi.spyOn(api, "getCart").mockResolvedValue(cart);

    render(
      <MemoryRouter initialEntries={["/pay/legacy-checkout"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Ready to order" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/demo|mock|synthetic/i);
  });

  it("keeps localized menu and option names on the Japanese handoff", async () => {
    const japaneseProfile = { ...profile, preferred_language: "日本語" as const, nationality: "Japan" };
    const localizedCart: CartPreview = {
      ...cart,
      items: [{
        ...cart.items[0],
        display_name: "YOBIキンパ",
        options: [{
          option_item_id: "option_1",
          name_en: "No pickles",
          name_ko: "단무지 제외",
          display_name: "たくあん抜き",
          price_delta: 0,
        }],
      }],
    };
    useSessionStore.setState({ profile: japaneseProfile, session, addressRefId: "address_handoff_test" });
    vi.spyOn(api, "getCart").mockResolvedValue(localizedCart);

    render(
      <MemoryRouter initialEntries={["/handoff"]}>
        <Routes>
          <Route path="/handoff" element={<HandoffPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect((await screen.findAllByText(/YOBIキンパ/)).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("たくあん抜き")).toBeInTheDocument();
    expect(screen.queryByText("요비 김밥")).not.toBeInTheDocument();
  });
});
