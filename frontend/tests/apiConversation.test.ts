import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/lib/api";
import type { ConversationEventResult, MealNeedState } from "../src/types";

const state: MealNeedState = {
  schema_version: 1,
  turn_count: 0,
  temperature_preferences: [],
  texture_preferences: [],
  flavor_preferences: [],
  preferred_categories: [],
  excluded_categories: [],
  excluded_ingredients: [],
  dietary_rules: [],
  profile_dietary_rules: [],
  positive_preferences: [],
  negative_preferences: [],
  shown_menu_ids: [],
  rejected_menu_ids: [],
  compared_menu_ids: [],
  option_selections: {},
  option_risk_acknowledged: [],
  recommendation_hold: false,
  strictness: "STRICT",
};

describe("versioned mutation API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts a typed, versioned and idempotent menu-selection event", async () => {
    const result: ConversationEventResult = {
      event_id: "event_1",
      event_type: "SELECT_MENU",
      state_version: 5,
      state: { ...state, selected_menu_id: "menu_1" },
      selected_menu_id: "menu_1",
      selected_merchant_id: "merchant_1",
      duplicate: false,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(result),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.postConversationEvent("session_1", {
      event_type: "SELECT_MENU",
      snapshot_id: "snapshot_1",
      menu_id: "menu_1",
      expected_state_version: 4,
      idempotency_key: "select-menu-1",
    })).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/session_1/events",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          event_type: "SELECT_MENU",
          snapshot_id: "snapshot_1",
          menu_id: "menu_1",
          expected_state_version: 4,
          idempotency_key: "select-menu-1",
        }),
      }),
    );
  });

  it("sends a client-stable request id with a chat message", async () => {
    const response = { message_id: "msg_1" };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(response),
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.sendMessage("session_1", "hello", "chat-request-0001");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/session_1/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ content: "hello", request_id: "chat-request-0001" }),
      }),
    );
  });

  it("binds checkout idempotency to the confirmed cart identity and version", async () => {
    const checkout = {
      checkout_id: "checkout_1",
      status: "PENDING" as const,
      amount: 12000,
      payment_method: "international_card",
      payment_url: "/pay/checkout_1",
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(checkout),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.createCheckout("session_1", "cart_1", 7)).resolves.toEqual(checkout);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/session_1/checkout",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          idempotency_key: "checkout-cart_1-7",
          payment_method: "international_card",
        }),
      }),
    );
  });

  it("creates a cart idempotency key when randomUUID is unavailable on public HTTP", async () => {
    const cart = { cart_id: "cart_1", version: 1, items: [], missing_slots: [] };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(cart),
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", {
      getRandomValues: (words: Uint32Array) => {
        words.set([1, 2, 3, 4]);
        return words;
      },
    });

    await expect(api.addCartItem("session_1", "menu_1", ["option_1"], "Mild"))
      .resolves.toEqual(cart);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/session_1/cart/items",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "cart-00000001000000020000000300000004",
        }),
      }),
    );
  });
});
