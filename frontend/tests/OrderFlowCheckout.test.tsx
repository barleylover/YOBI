import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { OrderFlowPanel } from "../src/components/OrderFlowPanel";
import { api } from "../src/lib/api";
import { useSessionStore } from "../src/stores/session";
import type {
  CartPreview,
  MenuSummary,
  MerchantMenuPresentation,
  Profile,
  Session,
} from "../src/types";

const menu: MenuSummary = {
  menu_id: "menu_checkout_1",
  merchant_id: "merchant_checkout_1",
  merchant_name: "YOBI Checkout Kitchen",
  name_en: "Checkout gimbap",
  name_ko: "결제 김밥",
  category: "Gimbap",
  description: "A compact checkout fixture.",
  cultural_description: "A compact rice-and-seaweed meal.",
  price: 10000,
  delivery_fee: 2000,
  eta_min: 20,
  eta_max: 30,
  spice_level: 0,
  serves_min: 1,
  serves_max: 1,
  dietary_summary: "Ingredient details available.",
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

function presentation(index: number): MerchantMenuPresentation {
  const presentedMenu: MenuSummary = {
    ...menu,
    menu_id: `merchant-menu-${index}`,
    name_en: `Restaurant menu ${index}`,
    name_ko: `식당 메뉴 ${index}`,
    localized_title: `Localized menu ${index}`,
  };
  return {
    menu: presentedMenu,
    localized_title: presentedMenu.localized_title!,
    yobi_short_explanation: `A concise explanation for menu ${index}.`,
    yobi_long_explanation: `A longer explanation for menu ${index}.`,
    source_description: `Restaurant description ${index}.`,
    review_summary: `Review summary ${index}.`,
    country_preference: { country_code: "US", preference_percent: 70 + index, sample_size: 200 + index },
    evidence_ids: [`wiki-${index}`],
    review_ids: [`review-${index}`],
    generation_model: "xai.grok-4.3",
  };
}

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
      addressSummary: "YOBI hotel",
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
    fireEvent.click(screen.getByRole("button", { name: "Prepare this order · ₩12,000" }));

    await waitFor(() => expect(confirmCart).toHaveBeenCalledWith(session.session_id));
    expect(createCheckout).not.toHaveBeenCalled();
    await screen.findByText("Yogiyo handoff page");
  });

  it("skips an empty option list and keeps the selected menu, server price, cart, and handoff contracts", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
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
    fireEvent.change(note, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    await waitFor(() => expect(addCartItem).toHaveBeenCalledWith(
      session.session_id,
      menu.menu_id,
      [],
      "",
      undefined,
    ));
    expect(screen.queryByTestId(/option-group-/)).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "No, continue to delivery" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm delivery details" }));
    await waitFor(() => expect(updateDelivery).toHaveBeenCalledWith(session.session_id, "address_checkout_test"));
    const review = await screen.findByTestId("cart-review");
    expect(review).toHaveTextContent("Server-selected external gimbap");
    expect(review).toHaveTextContent("₩12,345");
    expect(review).toHaveTextContent("₩15,555");

    fireEvent.click(screen.getByRole("button", { name: "Prepare this order · ₩15,555" }));
    await waitFor(() => expect(confirmCart).toHaveBeenCalledWith(session.session_id));
    await screen.findByText("Yogiyo no-option handoff");
  });

  it("translates a user-language restaurant note to Korean before adding it", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 0,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([]);
    const sourceText = "Please leave the sauce on the side.";
    const translation = {
      translation_id: "note-translation-1",
      source_text: sourceText,
      source_language: "English",
      korean_text: "소스는 따로 담아 주세요.",
      back_translation: "Please pack the sauce separately.",
      model_id: "gpt-oss-20b",
      status: "SUCCEEDED" as const,
      created_at: new Date().toISOString(),
    };
    const translate = vi.spyOn(api, "translateRestaurantNote").mockResolvedValue(translation);
    const addCartItem = vi.spyOn(api, "addCartItem").mockResolvedValue(cart);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes><Route path="/chat" element={(
          <OrderFlowPanel
            sessionId={session.session_id}
            menu={menu}
            addressRefId="address_checkout_test"
            onClose={() => undefined}
          />
        )} /></Routes>
      </MemoryRouter>,
    );

    const note = await screen.findByRole("textbox");
    fireEvent.change(note, { target: { value: sourceText } });
    expect(screen.getByRole("button", { name: "Add to cart" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Translate to Korean" }));
    expect(await screen.findByText(translation.korean_text)).toBeInTheDocument();
    expect(screen.getByText(/Please pack the sauce separately/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to cart" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));

    await waitFor(() => expect(translate).toHaveBeenCalledWith(session.session_id, sourceText, "English"));
    await waitFor(() => expect(addCartItem).toHaveBeenCalledWith(
      session.session_id,
      menu.menu_id,
      [],
      sourceText,
      translation.translation_id,
    ));
  });

  it("loads all same-restaurant Wiki presentations in cursor pages of twelve", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 0,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([]);
    vi.spyOn(api, "addCartItem").mockResolvedValue(cart);
    const pageOne = Array.from({ length: 12 }, (_, index) => presentation(index + 1));
    const pageTwo = [presentation(13), presentation(14)];
    const getPresentations = vi.spyOn(api, "getMerchantMenuPresentations")
      .mockResolvedValueOnce({ items: pageOne, next_cursor: "cursor-12" })
      .mockResolvedValueOnce({ items: pageTwo, next_cursor: null });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes><Route path="/chat" element={(
          <OrderFlowPanel
            sessionId={session.session_id}
            menu={menu}
            addressRefId="address_checkout_test"
            onClose={() => undefined}
          />
        )} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes, show more menus" }));
    await waitFor(() => expect(document.querySelectorAll(".v2-merchant-menu-carousel .v2-alimtalk-card")).toHaveLength(12));

    const carousel = document.querySelector<HTMLElement>(".v2-merchant-menu-carousel")!;
    Object.defineProperties(carousel, {
      scrollWidth: { configurable: true, value: 1000 },
      clientWidth: { configurable: true, value: 400 },
    });
    carousel.scrollLeft = 500;
    fireEvent.scroll(carousel);

    await waitFor(() => expect(getPresentations).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(document.querySelectorAll(".v2-merchant-menu-carousel .v2-alimtalk-card")).toHaveLength(14));
    expect(screen.getByText("Localized menu 14")).toBeInTheDocument();
    expect(getPresentations).toHaveBeenNthCalledWith(2, session.session_id, menu.merchant_id, {
      cursor: "cursor-12",
      limit: 12,
      exclude_menu_ids: [menu.menu_id],
    });
  });

  it("renders localized option group and item display names", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 0,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([{
      option_group_id: "group-spice",
      name_en: "Spice",
      name_ko: "맵기",
      display_name: "Localized spice level",
      description: "Choose a spice level.",
      required: true,
      min_select: 1,
      max_select: 1,
      items: [{
        option_item_id: "item-mild",
        name_en: "Mild",
        name_ko: "순한맛",
        display_name: "Localized mild",
        description: "Mild option.",
        price_delta: 0,
        available: true,
        conflicting_rules: [],
      }],
    }]);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes><Route path="/chat" element={(
          <OrderFlowPanel
            sessionId={session.session_id}
            menu={menu}
            addressRefId="address_checkout_test"
            onClose={() => undefined}
          />
        )} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Localized spice level" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Localized mild/ })).toBeInTheDocument();
    expect(screen.queryByText("맵기")).not.toBeInTheDocument();
  });
});
