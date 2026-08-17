import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe("OrderFlowPanel Yogiyo handoff contract", () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    useSessionStore.getState().clear();
  });

  it("confirms the cart and routes to the truthful handoff without creating a payment checkout", async () => {
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
    const createCheckout = vi.spyOn(api, "createCheckout");

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={(
            <OrderFlowPanel
              sessionId={session.session_id}
              menu={menu}
              addressRefId="address_checkout_test"
              onClose={() => undefined}
            />
          )} />
          <Route path="/handoff" element={<div>Yogiyo handoff page</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByTestId("cart-review");
    fireEvent.click(screen.getByRole("button", { name: "Yogiyo" }));

    await waitFor(() => expect(confirmCart).toHaveBeenCalledWith(session.session_id));
    expect(createCheckout).not.toHaveBeenCalled();
    await screen.findByText("Yogiyo handoff page");
  });

  it("skips an empty option list and keeps the selected menu, server price, cart, and handoff contracts", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "Synthetic hotel",
      cartQuantity: 0,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([]);
    const serverCart: CartPreview = {
      ...cart,
      version: 2,
      items: [{
        ...cart.items[0],
        menu_id: menu.menu_id,
        menu_name: "Server-selected external gimbap",
        menu_name_ko: "서버 선택 외부 김밥",
        unit_price: 12_345,
        line_total: 12_345,
      }],
      subtotal: 12_345,
      delivery_fee: 3_210,
      total_price: 15_555,
      missing_slots: ["delivery_preferences"],
      ready_to_checkout: false,
    };
    const addCartItem = vi.spyOn(api, "addCartItem").mockResolvedValue(serverCart);
    const deliveredCart = { ...serverCart, version: 3, missing_slots: [], ready_to_checkout: true };
    const updateDelivery = vi.spyOn(api, "updateDelivery").mockResolvedValue(deliveredCart);
    const confirmCart = vi.spyOn(api, "confirmCart").mockResolvedValue({ ...deliveredCart, version: 4, confirmed: true });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={(
            <OrderFlowPanel
              sessionId={session.session_id}
              menu={menu}
              addressRefId="address_checkout_test"
              onClose={() => undefined}
            />
          )} />
          <Route path="/handoff" element={<div>Yogiyo no-option handoff</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const note = await screen.findByRole("textbox");
    fireEvent.change(note, { target: { value: "Please pack the sauce separately." } });
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    await waitFor(() => expect(addCartItem).toHaveBeenCalledWith(
      session.session_id,
      menu.menu_id,
      [],
      "Please pack the sauce separately.",
    ));
    expect(screen.queryByTestId(/option-group-/)).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "No, continue to delivery" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm delivery details" }));
    await waitFor(() => expect(updateDelivery).toHaveBeenCalledWith(session.session_id, "address_checkout_test"));
    const review = await screen.findByTestId("cart-review");
    expect(review).toHaveTextContent("Server-selected external gimbap");
    expect(review).toHaveTextContent("₩12,345");
    expect(review).toHaveTextContent("₩15,555");

    fireEvent.click(screen.getByRole("button", { name: "Yogiyo" }));
    await waitFor(() => expect(confirmCart).toHaveBeenCalledWith(session.session_id));
    await screen.findByText("Yogiyo no-option handoff");
  });
});
