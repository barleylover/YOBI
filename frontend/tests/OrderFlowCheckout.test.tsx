import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { OrderFlowPanel } from "../src/components/OrderFlowPanel";
import { api } from "../src/lib/api";
import { useSessionStore } from "../src/stores/session";
import type { CartPreview, MenuSummary, Profile, Session } from "../src/types";

const menu: MenuSummary = {
  menu_id: "menu_checkout_1",
  merchant_id: "merchant_checkout_1",
  merchant_name: "Synthetic Checkout Kitchen",
  name_en: "Checkout gimbap",
  name_ko: "결제 김밥",
  category: "Gimbap",
  description: "A synthetic checkout fixture.",
  cultural_description: "A compact rice-and-seaweed meal.",
  price: 10000,
  delivery_fee: 2000,
  eta_min: 20,
  eta_max: 30,
  spice_level: 0,
  serves_min: 1,
  serves_max: 1,
  dietary_summary: "Synthetic fixture only.",
  evidence_status: "UNKNOWN",
  match_reasons: [],
  risk_hints: [],
  evidence_ids: [],
  grounded_claim_ids: [],
  grounded_passage_ids: [],
  is_synthetic: true,
};

const profile: Profile = {
  profile_id: "profile_checkout_test",
  preferred_language: "English",
  nationality: "United States",
  religion_selection: "Prefer not to say",
  spice_tolerance: 1,
  dietary_rules: [],
  favorite_foods: [],
  age_band: "25-34",
  allergy_severity: "mild",
  consent_demo_data: true,
  remember_profile: false,
};

const session: Session = {
  session_id: "session_checkout_test",
  profile_id: profile.profile_id,
  state: "ORDER_BUILDING",
  state_version: 1,
};

const cart: CartPreview = {
  cart_id: "cart_checkout_1",
  version: 8,
  items: [{
    cart_item_id: "cart_item_1",
    menu_id: menu.menu_id,
    menu_name: menu.name_en,
    menu_name_ko: menu.name_ko,
    quantity: 1,
    unit_price: menu.price,
    options: [],
    line_total: menu.price,
  }],
  subtotal: menu.price,
  delivery_fee: menu.delivery_fee,
  total_price: menu.price + menu.delivery_fee,
  missing_slots: [],
  dietary_warnings: [],
  minimum_order_amount: 0,
  minimum_order_shortfall: 0,
  ready_to_checkout: true,
  confirmed: false,
};

describe("OrderFlowPanel checkout contract", () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
    useSessionStore.getState().clear();
  });

  it("creates checkout with the cart id and version returned by confirmation", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "Synthetic hotel",
      cartQuantity: 1,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([]);
    vi.spyOn(api, "getCart").mockResolvedValue(cart);
    const confirmed = { ...cart, version: 9, confirmed: true };
    const confirmCart = vi.spyOn(api, "confirmCart").mockResolvedValue(confirmed);
    const createCheckout = vi.spyOn(api, "createCheckout").mockResolvedValue({
      checkout_id: "checkout_1",
      status: "PENDING",
      amount: confirmed.total_price,
      payment_method: "international_card",
      payment_url: "/pay/checkout_1",
    });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={(
            <OrderFlowPanel
              sessionId={session.session_id}
              menu={menu}
              addressRefId="address_checkout_test"
              dietaryRules={[]}
              onClose={() => undefined}
            />
          )} />
          <Route path="/pay/:checkoutId" element={<div>Mock payment page</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByTestId("cart-review");
    fireEvent.click(screen.getByRole("button", { name: /Proceed to payment/i }));

    await waitFor(() => expect(confirmCart).toHaveBeenCalledWith(session.session_id));
    await waitFor(() => expect(createCheckout).toHaveBeenCalledWith(
      session.session_id,
      confirmed.cart_id,
      confirmed.version,
    ));
    await screen.findByText("Mock payment page");
  });
});
