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
    if (!response.ok) throw new Error("ADDRESS_UPLOAD_FAILED");
    return response.json() as Promise<{
      candidates: AddressCandidate[];
      low_confidence: boolean;
      notice: string;
    }>;
  },
  confirmAddress: (sessionId: string, candidate: AddressCandidate) =>
    request<{ address_ref_id: string }>(`/api/v1/sessions/${sessionId}/address/confirm`, {
      method: "POST",
      body: JSON.stringify({ candidate }),
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
