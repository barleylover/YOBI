import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  }],
  subtotal: 9000,
  delivery_fee: 2000,
  total_price: 11000,
  missing_slots: [],
  dietary_warnings: [],
  minimum_order_amount: 0,
  minimum_order_shortfall: 0,
  ready_to_checkout: true,
  confirmed: true,
};

describe("truthful Yogiyo handoff boundary", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    useSessionStore.getState().clear();
  });

  it("ends the demo at one Yogiyo CTA without payment or order creation", async () => {
    useSessionStore.setState({ profile, session, addressRefId: "address_handoff_test" });
    vi.spyOn(api, "getCart").mockResolvedValue(cart);
    const createCheckout = vi.spyOn(api, "createCheckout");
    const paymentSuccess = vi.spyOn(api, "paymentSuccess");

    render(
      <MemoryRouter initialEntries={["/handoff"]}>
        <Routes>
          <Route path="/handoff" element={<HandoffPage />} />
          <Route path={`/chat/${session.session_id}`} element={<div>YOBI chat</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Continue in Yogiyo to order" })).toBeInTheDocument();
    expect(screen.getByText(/No cart was sent/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Yogiyo" }));
    expect(await screen.findByRole("heading", { name: /YOBI demo ends here/ })).toBeInTheDocument();
    expect(createCheckout).not.toHaveBeenCalled();
    expect(paymentSuccess).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^Pay/ })).not.toBeInTheDocument();
    // The handoff is the terminal mock boundary, not another post-address browsing screen.
    expect(document.querySelector(".post-address-nav")).not.toBeInTheDocument();
  });

  it("redirects legacy payment URLs to the same handoff instead of exposing mock payment", async () => {
    useSessionStore.setState({ profile, session, addressRefId: "address_handoff_test" });
    vi.spyOn(api, "getCart").mockResolvedValue(cart);

    render(
      <MemoryRouter initialEntries={["/pay/legacy-checkout"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Continue in Yogiyo to order" })).toBeInTheDocument();
    expect(screen.queryByText(/Mock payment/i)).not.toBeInTheDocument();
  });
});
