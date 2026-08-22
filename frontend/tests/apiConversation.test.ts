import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/lib/api";
import { emptyCriteria } from "../src/stores/session";
import type { ConversationEventResult, MealNeedState, PreferenceCatalog } from "../src/types";

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
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

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

  it("revalidates the preference catalog with its ETag", async () => {
    const catalog: PreferenceCatalog = {
      schema_version: "2",
      catalog_version: "catalog-v2",
      knowledge_release_id: "knowledge-v2",
      locale: "en",
      categories: [],
      spice_references: [],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 304,
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.getPreferenceCatalog("en", { etag: '"catalog-v2"', catalog }))
      .resolves.toEqual({ catalog, etag: '"catalog-v2"', notModified: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/recommendation/preferences/catalog?locale=en",
      expect.objectContaining({
        headers: { "If-None-Match": '"catalog-v2"' },
      }),
    );
  });

  it("bounds preference catalog requests with the shared timeout contract", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_path: string, init?: RequestInit) => new Promise<Response>(
      (_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        }, { once: true });
      },
    ));
    vi.stubGlobal("fetch", fetchMock);

    const expectation = expect(api.getPreferenceCatalog("en")).rejects.toThrow("REQUEST_TIMEOUT");
    await vi.advanceTimersByTimeAsync(8_000);
    await expectation;
  });

  it("commits catalog-bound criteria and creates a versioned recommendation request", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ criteria_version: 2, state_version: 3 }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ request_id: "recommendation-1", status: "PENDING" }) });
    vi.stubGlobal("fetch", fetchMock);
    const criteria = { ...emptyCriteria(), cuisine_origins: ["KOREAN"] };

    await api.putRecommendationCriteria("session_1", criteria, 2, "catalog-v2", "criteria-request-1");
    await api.createRecommendation("session_1", {
      request_id: "recommendation-1",
      expected_state_version: 3,
      criteria_version: 2,
      mode: "INITIAL",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(1,
      "/api/v1/sessions/session_1/recommendation-criteria",
      expect.objectContaining({ body: JSON.stringify({
        criteria,
        expected_state_version: 2,
        catalog_version: "catalog-v2",
        request_id: "criteria-request-1",
      }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2,
      "/api/v1/sessions/session_1/recommendations",
      expect.objectContaining({ body: JSON.stringify({
        request_id: "recommendation-1",
        expected_state_version: 3,
        criteria_version: 2,
        mode: "INITIAL",
      }) }),
    );
  });

  it("previews the exact criteria through the server-owned structured endpoint", async () => {
    const criteria = { ...emptyCriteria(), cuisine_origins: ["KOREAN"] };
    const preview = {
      eligible_menu_count: 8,
      eligible_merchant_count: 4,
      zero_reason_codes: [],
      release_id: "release-v2",
      support_manifest_sha256: "support-v2",
      ranking_policy_version: "ranking-v2",
      timing_ms: 3,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(preview),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.previewRecommendation("session_1", criteria, "catalog-v2")).resolves.toEqual(preview);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/session_1/structured-recommendations/preview",
      expect.objectContaining({ method: "POST", body: JSON.stringify(criteria) }),
    );
  });

  it("polls a recommendation request with GET instead of redispatching it", async () => {
    const response = { request_id: "recommendation-1", status: "PENDING" };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: vi.fn().mockResolvedValue(response) });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.getRecommendationRequest("session_1", "recommendation-1")).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/session_1/recommendation-requests/recommendation-1",
      expect.objectContaining({ headers: expect.any(Object) }),
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
