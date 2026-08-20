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
    merchant_id: menu.merchant_id,
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

  it("requires an explicit cart clear before configuring a menu from another restaurant", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 1,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([]);
    const foreignCart: CartPreview = {
      ...cart,
      items: [{
        ...cart.items[0],
        cart_item_id: "foreign-cart-item",
        menu_id: "foreign-menu",
        merchant_id: "foreign-merchant",
        menu_name: "Other restaurant noodles",
        menu_name_ko: "다른 가게 국수",
      }],
    };
    const emptyCart: CartPreview = {
      ...cart,
      version: cart.version + 1,
      items: [],
      subtotal: 0,
      delivery_fee: 0,
      total_price: 0,
      ready_to_checkout: false,
    };
    vi.spyOn(api, "getCart").mockResolvedValue(foreignCart);
    const deleteCartItem = vi.spyOn(api, "deleteCartItem").mockResolvedValue(emptyCart);

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

    expect(await screen.findByRole("heading", { name: "Your cart has items from another restaurant" })).toBeInTheDocument();
    expect(deleteCartItem).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Clear cart and continue" }));
    await waitFor(() => expect(deleteCartItem).toHaveBeenCalledWith(session.session_id, "foreign-cart-item"));
    expect(await screen.findByRole("heading", { name: "How should we say it?" })).toBeInTheDocument();
    expect(useSessionStore.getState().cartQuantity).toBe(0);
  });

  it("edits an existing cart line in place instead of adding a duplicate menu", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 1,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([{
      option_group_id: "group-spice",
      name_en: "Spice",
      name_ko: "맵기",
      display_name: "Spice",
      description: "Choose one",
      required: true,
      min_select: 1,
      max_select: 1,
      items: [
        {
          option_item_id: "item-mild",
          name_en: "Mild",
          name_ko: "순한맛",
          display_name: "Mild",
          description: "Mild",
          price_delta: 0,
          available: true,
          conflicting_rules: [],
        },
        {
          option_item_id: "item-hot",
          name_en: "Hot",
          name_ko: "매운맛",
          display_name: "Hot",
          description: "Hot",
          price_delta: 500,
          available: true,
          conflicting_rules: [],
        },
      ],
    }]);
    const cartWithOption: CartPreview = {
      ...cart,
      items: [{
        ...cart.items[0],
        options: [{
          option_item_id: "item-mild",
          name_en: "Mild",
          name_ko: "순한맛",
          display_name: "Mild",
          price_delta: 0,
        }],
      }],
    };
    const updatedCart: CartPreview = {
      ...cartWithOption,
      version: cartWithOption.version + 1,
      items: [{
        ...cartWithOption.items[0],
        options: [{
          option_item_id: "item-hot",
          name_en: "Hot",
          name_ko: "매운맛",
          display_name: "Hot",
          price_delta: 500,
        }],
      }],
    };
    vi.spyOn(api, "getCart").mockResolvedValue(cartWithOption);
    const updateCartItem = vi.spyOn(api, "updateCartItem").mockResolvedValue(updatedCart);
    const addCartItem = vi.spyOn(api, "addCartItem");

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

    await screen.findByTestId("cart-review");
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[1]);
    expect(await screen.findByRole("heading", { name: "Spice" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Hot/ }));
    expect(await screen.findByRole("heading", { name: "How should we say it?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));

    await waitFor(() => expect(updateCartItem).toHaveBeenCalledWith(
      session.session_id,
      "cart_item_1",
      { option_item_ids: ["item-hot"] },
    ));
    expect(addCartItem).not.toHaveBeenCalled();
    expect(await screen.findByTestId("cart-review")).toHaveTextContent("Hot");
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

    expect(screen.queryByText("Would you like anything else from this restaurant?")).not.toBeInTheDocument();
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
    vi.spyOn(api, "getMerchantMenus").mockResolvedValue([presentation(1).menu]);
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

  it("offers None only for optional groups and waits for Done on multi-select groups", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 0,
    });
    const onOptionChange = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(api, "getOptions").mockResolvedValue([
      {
        option_group_id: "group-optional",
        name_en: "Optional garnish",
        name_ko: "선택 고명",
        display_name: "Optional garnish",
        description: "Optional",
        required: false,
        min_select: 0,
        max_select: 1,
        items: [{
          option_item_id: "item-garnish",
          name_en: "Spring onion",
          name_ko: "파",
          display_name: "Spring onion",
          description: "Garnish",
          price_delta: 0,
          available: true,
          conflicting_rules: [],
        }],
      },
      {
        option_group_id: "group-required",
        name_en: "Required rice",
        name_ko: "필수 밥",
        display_name: "Required rice",
        description: "Required",
        required: true,
        min_select: 1,
        max_select: 1,
        items: [{
          option_item_id: "item-rice",
          name_en: "White rice",
          name_ko: "흰밥",
          display_name: "White rice",
          description: "Rice",
          price_delta: 0,
          available: true,
          conflicting_rules: [],
        }],
      },
      {
        option_group_id: "group-multi",
        name_en: "Toppings",
        name_ko: "토핑",
        display_name: "Toppings",
        description: "Choose up to two",
        required: false,
        min_select: 0,
        max_select: 2,
        items: [
          {
            option_item_id: "item-a",
            name_en: "Seaweed",
            name_ko: "김",
            display_name: "Seaweed",
            description: "Topping",
            price_delta: 0,
            available: true,
            conflicting_rules: [],
          },
          {
            option_item_id: "item-b",
            name_en: "Sesame",
            name_ko: "깨",
            display_name: "Sesame",
            description: "Topping",
            price_delta: 0,
            available: true,
            conflicting_rules: [],
          },
        ],
      },
    ]);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes><Route path="/chat" element={(
          <OrderFlowPanel
            sessionId={session.session_id}
            menu={menu}
            addressRefId="address_checkout_test"
            onClose={() => undefined}
            onOptionChange={onOptionChange}
          />
        )} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Optional garnish" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "None" }));
    expect(await screen.findByRole("heading", { name: "Required rice" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "None" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /White rice/ }));
    expect(await screen.findByRole("heading", { name: "Toppings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "None" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Seaweed/ }));
    await waitFor(() => expect(onOptionChange).toHaveBeenCalledWith(
      menu.menu_id,
      "group-multi",
      ["item-a"],
      false,
    ));
    fireEvent.click(screen.getByRole("button", { name: /Sesame/ }));
    await waitFor(() => expect(onOptionChange).toHaveBeenCalledWith(
      menu.menu_id,
      "group-multi",
      ["item-a", "item-b"],
      false,
    ));
    expect(screen.getByRole("heading", { name: "Toppings" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("heading", { name: "How should we say it?" })).toBeInTheDocument();
    expect(onOptionChange).toHaveBeenCalledWith(menu.menu_id, "group-optional", [], false);
    expect(onOptionChange).toHaveBeenCalledWith(menu.menu_id, "group-required", ["item-rice"], false);
  });

  it("allows a note-free cart add after every Korean translation model fails", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_checkout_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 0,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([]);
    const sourceText = "Please leave this at reception.";
    vi.spyOn(api, "translateRestaurantNote").mockResolvedValue({
      translation_id: "failed-translation",
      source_text: sourceText,
      source_language: "English",
      korean_text: null,
      back_translation: null,
      model_id: "all-configured-models",
      status: "FAILED",
      error_code: "PROVIDER_UNAVAILABLE",
      created_at: new Date().toISOString(),
    });
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
    fireEvent.click(screen.getByRole("button", { name: "Translate to Korean" }));
    expect(await screen.findByRole("button", { name: "Try Korean translation again" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add without restaurant note" }));

    await waitFor(() => expect(addCartItem).toHaveBeenCalledWith(
      session.session_id,
      menu.menu_id,
      [],
      "",
      undefined,
    ));
  });
});
