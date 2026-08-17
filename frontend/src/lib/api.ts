import type {
  AddressCandidate,
  CartPreview,
  Checkout,
  ConversationEventInput,
  ConversationEventResult,
  ConversationView,
  CriteriaCommitResult,
  FeaturedMenuCollection,
  FoodRankingCollection,
  FoodRankingSort,
  OptionGroup,
  Profile,
  PreferenceCatalog,
  RecommendationComparisonV2,
  RecommendationCriteriaV2,
  RecommendationBatchV2,
  RecommendationPreviewV2,
  RecommendationRequestV2,
  Session,
} from "../types";

interface RequestOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
}

async function request<T>(path: string, init?: RequestInit, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 15_000;
  let timedOut = false;
  const relayAbort = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) relayAbort();
  else options.signal?.addEventListener("abort", relayAbort, { once: true });
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: { code: "REQUEST_FAILED" } }));
      throw new Error(payload.detail?.code ?? `HTTP_${response.status}`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  } catch (cause) {
    if (controller.signal.aborted || (cause instanceof DOMException && cause.name === "AbortError")) {
      throw new Error(timedOut ? "REQUEST_TIMEOUT" : "REQUEST_ABORTED");
    }
    throw cause;
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", relayAbort);
  }
}

function clientRequestId(prefix: string) {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `${prefix}-${uuid}`;

  // randomUUID is restricted to secure browser contexts. The public demo is
  // intentionally served over HTTP, where getRandomValues remains available.
  // Keep a final non-cryptographic suffix only for older test/webview runtimes.
  const words = new Uint32Array(4);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(words);
    return `${prefix}-${Array.from(words, (word) => word.toString(16).padStart(8, "0")).join("")}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
}

const ACTIONABLE_ERRORS: Record<string, string> = {
  REQUIRED_MENU_OPTION_MISSING: "Choose one option in every required group to continue.",
  INVALID_MENU_OPTION: "Choose an option that belongs to this menu.",
  OPTION_GROUP_MAX_EXCEEDED: "Choose only the allowed number of options in this group.",
  CART_DIETARY_CONFLICT: "Remove the dietary-risk menu or option to continue.",
  CART_MULTIPLE_MERCHANTS: "Remove items from the other restaurant to continue with one delivery.",
  MINIMUM_ORDER_NOT_MET: "Add more items until the restaurant minimum is reached.",
  CART_INCOMPLETE: "Add a menu and confirm the delivery details to continue.",
  CART_OPTION_UNAVAILABLE: "That option is no longer available. Choose another option.",
  CART_MENU_UNAVAILABLE: "That menu is no longer available. Choose another menu.",
  CART_MENU_NO_LONGER_ELIGIBLE:
    "That menu no longer matches your saved preferences. Choose another menu or update your preferences.",
  CART_CHANGED_RECONFIRM_REQUIRED: "The menu or price changed. Review the cart and confirm it again.",
  CHECKOUT_STALE: "The cart changed after checkout started. Review and confirm it again before retrying payment.",
  CART_NOT_CONFIRMED: "Review and confirm the latest cart before payment.",
  IDEMPOTENCY_KEY_REUSED: "This payment request no longer matches the cart. Return to the cart and try again.",
  PAYMENT_ALREADY_SUCCEEDED: "This demo payment is already complete. Open the confirmed order instead.",
  ADDRESS_NOT_CONFIRMED: "Confirm your delivery address again before continuing.",
  ADDRESS_OUTSIDE_SERVICE_AREA: "Enter a supported delivery address or choose a verified address match.",
  ADDRESS_CANDIDATE_TOKEN_INVALID: "The address check expired. Search for the address again.",
  UPLOAD_SIZE_INVALID: "Choose an address image smaller than 8MB.",
  UNSUPPORTED_IMAGE_TYPE: "Choose a PNG, JPEG, or WebP address image.",
  IMAGE_EXTENSION_MISMATCH: "The file extension does not match the image type. Choose another image.",
  IMAGE_MAGIC_BYTE_INVALID: "That file is not a readable image. Choose another PNG, JPEG, or WebP file.",
  IMAGE_DECODE_FAILED: "That image could not be read. Try a clearer image or enter the address manually.",
  CHAT_STATE_VERSION_CONFLICT: "Your choices changed in another action. Review the latest result and try again.",
  RECOMMENDATION_SNAPSHOT_NOT_FOUND: "That recommendation is no longer available. Request a fresh set of menus.",
  MENU_NOT_IN_RECOMMENDATION_SNAPSHOT: "That menu is not part of the latest recommendation. Choose from the current cards.",
  OPTIONS_REQUIRE_SELECTED_MENU: "Choose the menu again before changing its options.",
  PREFERENCE_CATALOG_NOT_AVAILABLE: "The current food choices could not be loaded. Try again.",
  PREFERENCE_CATALOG_CHANGED: "The available food choices changed. Review the refreshed choices and try again.",
  PREFERENCE_CATALOG_VERSION_CONFLICT: "The available food choices changed. Review the refreshed choices and try again.",
  RECOMMENDATION_CRITERIA_INVALID: "Review the selected food preferences and try again.",
  RECOMMENDATION_IN_PROGRESS: "YOBI is still preparing this recommendation.",
  RECOMMENDATION_FAILED: "YOBI could not finish this recommendation. Your selections are still saved.",
  REQUEST_TIMEOUT: "This is taking longer than expected. YOBI will check the same request instead of starting another one.",
  REQUEST_ABORTED: "The request was stopped safely. Your saved choices did not change.",
  RECOMMENDATION_PREVIEW_UNAVAILABLE: "The live combination preview is temporarily unavailable.",
  RECOMMENDATION_COMPARISON_FAILED: "YOBI could not compare these menus. The recommendation itself has not changed.",
};

export function actionableError(cause: unknown, fallback: string) {
  const code = cause instanceof Error ? cause.message : "";
  return ACTIONABLE_ERRORS[code] ?? fallback;
}

export const api = {
  createProfile: (body: Record<string, unknown>) =>
    request<Profile>("/api/v1/profiles", { method: "POST", body: JSON.stringify(body) }),
  updateProfile: (profileId: string, body: Record<string, unknown>) =>
    request<Profile>(`/api/v1/profiles/${profileId}`, { method: "PATCH", body: JSON.stringify(body) }),
  createSession: (profileId: string) =>
    request<Session>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    }),
  getPreferenceCatalog: async (
    locale: string,
    cached?: { etag: string; catalog: PreferenceCatalog } | null,
  ) => {
    const headers: Record<string, string> = {};
    if (cached?.etag) headers["If-None-Match"] = cached.etag;
    const response = await fetch(
      `/api/v1/recommendation/preferences/catalog?locale=${encodeURIComponent(locale)}`,
      { headers },
    );
    if (response.status === 304 && cached) {
      return { catalog: cached.catalog, etag: cached.etag, notModified: true };
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: { code: "PREFERENCE_CATALOG_NOT_AVAILABLE" } }));
      throw new Error(payload.detail?.code ?? `HTTP_${response.status}`);
    }
    const catalog = await response.json() as PreferenceCatalog;
    return {
      catalog,
      etag: response.headers.get("ETag") ?? `"${catalog.catalog_version}"`,
      notModified: false,
    };
  },
  putRecommendationCriteria: (
    sessionId: string,
    criteria: RecommendationCriteriaV2,
    expectedStateVersion: number,
    catalogVersion: string,
    requestId = clientRequestId("criteria"),
  ) => request<CriteriaCommitResult>(`/api/v1/sessions/${sessionId}/recommendation-criteria`, {
    method: "PUT",
    body: JSON.stringify({
      criteria,
      expected_state_version: expectedStateVersion,
      catalog_version: catalogVersion,
      request_id: requestId,
    }),
  }),
  previewRecommendation: (
    sessionId: string,
    criteria: RecommendationCriteriaV2,
    _catalogVersion: string,
    signal?: AbortSignal,
  ) => request<RecommendationPreviewV2>(`/api/v1/sessions/${sessionId}/structured-recommendations/preview`, {
    method: "POST",
    body: JSON.stringify(criteria),
  }, { timeoutMs: 3_000, signal }),
  createRecommendation: (sessionId: string, input: RecommendationRequestV2, signal?: AbortSignal) =>
    request<RecommendationBatchV2>(`/api/v1/sessions/${sessionId}/recommendations`, {
      method: "POST",
      body: JSON.stringify(input),
    }, { timeoutMs: 15_000, signal }),
  getRecommendationRequest: (sessionId: string, requestId: string, signal?: AbortSignal) =>
    request<RecommendationBatchV2>(
      `/api/v1/sessions/${sessionId}/recommendation-requests/${encodeURIComponent(requestId)}`,
      undefined,
      { timeoutMs: 8_000, signal },
    ),
  compareRecommendations: (
    sessionId: string,
    input: { snapshot_id: string; request_id: string; idempotency_key: string },
    signal?: AbortSignal,
  ) => request<RecommendationComparisonV2>(`/api/v1/sessions/${sessionId}/recommendation-comparisons`, {
    method: "POST",
    body: JSON.stringify(input),
  }, { timeoutMs: 15_000, signal }),
  getFoodRankings: (sessionId: string, sort: FoodRankingSort, signal?: AbortSignal) =>
    request<FoodRankingCollection>(
      `/api/v1/sessions/${sessionId}/food-rankings?sort=${encodeURIComponent(sort)}&limit=20`,
      undefined,
      { timeoutMs: 8_000, signal },
    ),
  getKpopDemonHuntersFeature: (sessionId: string, signal?: AbortSignal) =>
    request<FeaturedMenuCollection>(
      `/api/v1/sessions/${sessionId}/featured/kpop-demon-hunters`,
      undefined,
      { timeoutMs: 8_000, signal },
    ),
  getConversation: (sessionId: string) =>
    request<ConversationView>(`/api/v1/sessions/${sessionId}/conversation`),
  postConversationEvent: (sessionId: string, event: ConversationEventInput) =>
    request<ConversationEventResult>(`/api/v1/sessions/${sessionId}/events`, {
      method: "POST",
      body: JSON.stringify(event),
    }),
  getOptions: (menuId: string) => request<OptionGroup[]>(`/api/v1/menus/${menuId}/options`),
  getMerchantMenus: (sessionId: string, merchantId: string, excludedMenuIds: string[]) =>
    request<import("../types").MenuSummary[]>(
      `/api/v1/sessions/${sessionId}/merchants/${merchantId}/menus?exclude=${encodeURIComponent(excludedMenuIds.join(","))}`,
    ),
  getCart: (sessionId: string, signal?: AbortSignal) => request<CartPreview>(
    `/api/v1/sessions/${sessionId}/cart`,
    undefined,
    { timeoutMs: 8_000, signal },
  ),
  addCartItem: (
    sessionId: string,
    menuId: string,
    optionItemIds: string[],
    userNote: string,
  ) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/items`, {
      method: "POST",
      headers: { "Idempotency-Key": clientRequestId("cart") },
      body: JSON.stringify({
        menu_id: menuId,
        quantity: 1,
        option_item_ids: optionItemIds,
        user_note: userNote,
      }),
    }),
  uploadAddress: async (sessionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`/api/v1/sessions/${sessionId}/address/attachments`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: { code: "ADDRESS_UPLOAD_FAILED" } }));
      throw new Error(payload.detail?.code ?? "ADDRESS_UPLOAD_FAILED");
    }
    return response.json() as Promise<{
      candidates: AddressCandidate[];
      low_confidence: boolean;
      notice: string;
    }>;
  },
  resolveAddress: (sessionId: string, text: string) =>
    request<{
      candidates: AddressCandidate[];
      low_confidence: boolean;
      notice: string;
    }>(`/api/v1/sessions/${sessionId}/address/resolve`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  confirmAddress: (sessionId: string, candidate: AddressCandidate) =>
    request<{ address_ref_id: string }>(`/api/v1/sessions/${sessionId}/address/confirm`, {
      method: "POST",
      body: JSON.stringify({ candidate_token: candidate.candidate_token }),
    }),
  confirmManualAddress: (
    sessionId: string,
    manual: {
      hotel_name: string;
      road_address: string;
      postal_code: string;
      city: string;
      delivery_hint: string;
    },
  ) =>
    request<{ address_ref_id: string }>(`/api/v1/sessions/${sessionId}/address/confirm`, {
      method: "POST",
      body: JSON.stringify({ manual }),
    }),
  updateDelivery: (sessionId: string, addressRefId: string) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/delivery`, {
      method: "PATCH",
      body: JSON.stringify({
        address_ref_id: addressRefId,
        handoff_method: "front_desk",
        cutlery: false,
        ring_bell: false,
        front_desk: true,
        user_note: "Please leave it at the hotel front desk. No disposable cutlery.",
      }),
    }),
  confirmCart: (sessionId: string) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/confirm`, {
      method: "POST",
    }),
  updateCartItem: (sessionId: string, cartItemId: string, quantity: number) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/items/${cartItemId}`, {
      method: "PATCH",
      body: JSON.stringify({ quantity }),
    }),
  deleteCartItem: (sessionId: string, cartItemId: string) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/items/${cartItemId}`, {
      method: "DELETE",
    }),
  createCheckout: (sessionId: string, cartId: string, cartVersion: number) =>
    request<Checkout>(`/api/v1/sessions/${sessionId}/checkout`, {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: `checkout-${cartId}-${cartVersion}`,
        payment_method: "international_card",
      }),
    }),
  getCheckout: (checkoutId: string) => request<Checkout>(`/api/v1/checkout/${checkoutId}`),
  paymentSuccess: (checkoutId: string) =>
    request<Checkout>(`/api/v1/checkout/${checkoutId}/mock-success`, { method: "POST" }),
  paymentFailure: (checkoutId: string) =>
    request<Checkout>(`/api/v1/checkout/${checkoutId}/mock-failure`, { method: "POST" }),
  getOrder: (orderId: string) => request<Record<string, unknown>>(`/api/v1/orders/${orderId}`),
  demoStatus: (token: string) =>
    request<{
      api: string;
      database: Record<string, unknown>;
      genai: string;
      fallback_mode: string;
      synthetic_data: boolean;
    }>("/api/v1/demo/status", { headers: { "X-Demo-Control-Token": token } }),
  setFailureMode: (token: string, mode: string) =>
    request<{ mode: string }>("/api/v1/demo/failure-mode", {
      method: "POST",
      headers: { "X-Demo-Control-Token": token },
      body: JSON.stringify({ mode }),
    }),
};
