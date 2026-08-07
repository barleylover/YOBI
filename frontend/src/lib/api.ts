import type {
  AddressCandidate,
  AssistantTurn,
  CartPreview,
  Checkout,
  OptionGroup,
  Profile,
  Session,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: { code: "REQUEST_FAILED" } }));
    throw new Error(payload.detail?.code ?? `HTTP_${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
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
  CART_CHANGED_RECONFIRM_REQUIRED: "The menu or price changed. Review the cart and confirm it again.",
  CART_NOT_CONFIRMED: "Review and confirm the latest cart before payment.",
  IDEMPOTENCY_KEY_REUSED: "This payment request no longer matches the cart. Return to the cart and try again.",
  PAYMENT_ALREADY_SUCCEEDED: "This demo payment is already complete. Open the confirmed order instead.",
  ADDRESS_NOT_CONFIRMED: "Confirm your delivery address again before continuing.",
  ADDRESS_CANDIDATE_TOKEN_INVALID: "The address check expired. Search for the address again.",
  UPLOAD_SIZE_INVALID: "Choose an address image smaller than 8MB.",
  UNSUPPORTED_IMAGE_TYPE: "Choose a PNG, JPEG, or WebP address image.",
  IMAGE_EXTENSION_MISMATCH: "The file extension does not match the image type. Choose another image.",
  IMAGE_MAGIC_BYTE_INVALID: "That file is not a readable image. Choose another PNG, JPEG, or WebP file.",
  IMAGE_DECODE_FAILED: "That image could not be read. Try a clearer image or enter the address manually.",
};

export function actionableError(cause: unknown, fallback: string) {
  const code = cause instanceof Error ? cause.message : "";
  return ACTIONABLE_ERRORS[code] ?? fallback;
}

export const api = {
  createProfile: (body: Record<string, unknown>) =>
    request<Profile>("/api/v1/profiles", { method: "POST", body: JSON.stringify(body) }),
  createSession: (profileId: string) =>
    request<Session>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    }),
  sendMessage: (sessionId: string, content: string) =>
    request<AssistantTurn>(`/api/v1/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  streamMessage: async (
    sessionId: string,
    content: string,
    handlers: { onText: (text: string) => void; onStatus: (text: string) => void },
  ) => {
    const response = await fetch(`/api/v1/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!response.ok || !response.body) throw new Error("CHAT_STREAM_FAILED");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalTurn: AssistantTurn | null = null;
    let providerError = false;

    function consumeFrame(frame: string) {
      const lines = frame.split(/\r?\n/);
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const dataText = lines
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (!event || !dataText) return;
      const data = JSON.parse(dataText) as Record<string, unknown>;
      if (event === "text_delta") handlers.onText(String(data.text ?? ""));
      if (event === "status" || event === "tool_started" || event === "tool_completed") {
        handlers.onStatus(String(data.text ?? data.label ?? ""));
      }
      if (event === "message_end") finalTurn = data as unknown as AssistantTurn;
      if (event === "error") providerError = true;
    }

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      frames.forEach(consumeFrame);
      if (done) break;
    }
    if (buffer.trim()) consumeFrame(buffer);
    if (providerError || !finalTurn) throw new Error("CHAT_STREAM_INCOMPLETE");
    return finalTurn as AssistantTurn;
  },
  getMessages: (sessionId: string) =>
    request<Array<{ message_id: string; role: "user" | "assistant"; content: string }>>(
      `/api/v1/sessions/${sessionId}/messages`,
    ),
  getOptions: (menuId: string) => request<OptionGroup[]>(`/api/v1/menus/${menuId}/options`),
  addCartItem: (
    sessionId: string,
    menuId: string,
    optionItemIds: string[],
    userNote: string,
  ) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/items`, {
      method: "POST",
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
  createCheckout: (sessionId: string) =>
    request<Checkout>(`/api/v1/sessions/${sessionId}/checkout`, {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: `checkout-${sessionId}`,
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
