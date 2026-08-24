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
  RestaurantNoteTranslation,
  MerchantMenuPresentationPage,
  Session,
} from "../types";
import { asEffectiveLanguage } from "./locale";

interface RequestOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
}

async function fetchWithTimeout(
  path: string,
  init?: RequestInit,
  options: RequestOptions = {},
): Promise<Response> {
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
    return await fetch(path, {
      ...init,
      signal: controller.signal,
    });
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

async function responseErrorCode(response: Response, fallback: string) {
  const payload = await response.json().catch(() => null) as unknown;
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (detail && typeof detail === "object") {
      const code = (detail as { code?: unknown }).code;
      if (typeof code === "string" && code) return code;
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit, options: RequestOptions = {}): Promise<T> {
  const response = await fetchWithTimeout(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  }, options);
  if (!response.ok) {
    throw new Error(await responseErrorCode(response, `HTTP_${response.status}`));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
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

type ErrorCopy = readonly [english: string, korean: string, japanese: string];

const ACTIONABLE_ERRORS: Record<string, ErrorCopy> = {
  REQUIRED_MENU_OPTION_MISSING: [
    "Choose one option in every required group to continue.",
    "계속하려면 모든 필수 옵션 그룹에서 하나씩 선택해 주세요.",
    "続けるには、必須の各オプショングループで1つ選択してください。",
  ],
  INVALID_MENU_OPTION: [
    "Choose an option that belongs to this menu.",
    "이 메뉴에 포함된 옵션을 선택해 주세요.",
    "このメニューに含まれるオプションを選択してください。",
  ],
  OPTION_GROUP_MAX_EXCEEDED: [
    "Choose only the allowed number of options in this group.",
    "이 그룹에서 허용된 개수만큼만 옵션을 선택해 주세요.",
    "このグループで選べる数以内にしてください。",
  ],
  CART_DIETARY_CONFLICT: [
    "Remove the dietary-risk menu or option to continue.",
    "식이 조건에 맞지 않는 메뉴나 옵션을 삭제해 주세요.",
    "食事条件に合わないメニューまたはオプションを削除してください。",
  ],
  CART_MULTIPLE_MERCHANTS: [
    "Remove items from the other restaurant to continue with one delivery.",
    "한 가게에서 배달받으려면 다른 가게의 메뉴를 삭제해 주세요.",
    "1店舗から配達するには、別の店舗の商品を削除してください。",
  ],
  MINIMUM_ORDER_NOT_MET: [
    "Add more items until the restaurant minimum is reached.",
    "가게의 최소 주문 금액을 채울 때까지 메뉴를 더 담아 주세요.",
    "店舗の最低注文金額に達するまで商品を追加してください。",
  ],
  CART_INCOMPLETE: [
    "Add a menu and confirm the delivery details to continue.",
    "메뉴를 담고 배달 정보를 확인해 주세요.",
    "メニューを追加し、配達情報を確認してください。",
  ],
  CART_OPTION_UNAVAILABLE: [
    "That option is no longer available. Choose another option.",
    "해당 옵션은 현재 이용할 수 없어요. 다른 옵션을 선택해 주세요.",
    "そのオプションは現在利用できません。別のオプションを選択してください。",
  ],
  CART_MENU_UNAVAILABLE: [
    "That menu is no longer available. Choose another menu.",
    "해당 메뉴는 현재 이용할 수 없어요. 다른 메뉴를 선택해 주세요.",
    "そのメニューは現在利用できません。別のメニューを選択してください。",
  ],
  CART_MENU_NO_LONGER_ELIGIBLE: [
    "That menu no longer matches your saved preferences. Choose another menu or update your preferences.",
    "해당 메뉴가 저장된 취향 조건과 더 이상 맞지 않아요. 다른 메뉴를 고르거나 조건을 수정해 주세요.",
    "そのメニューは保存した条件に合わなくなりました。別のメニューを選ぶか条件を変更してください。",
  ],
  CART_CHANGED_RECONFIRM_REQUIRED: [
    "The menu or price changed. Review the cart and confirm it again.",
    "메뉴 또는 가격이 변경됐어요. 장바구니를 다시 확인해 주세요.",
    "メニューまたは価格が変更されました。カートを確認し直してください。",
  ],
  CHECKOUT_STALE: [
    "The cart changed after checkout started. Review and confirm it again before retrying payment.",
    "결제를 시작한 뒤 장바구니가 변경됐어요. 다시 확인한 후 결제를 시도해 주세요.",
    "決済開始後にカートが変更されました。確認し直してから決済を再試行してください。",
  ],
  CART_NOT_CONFIRMED: [
    "Review and confirm the latest cart before payment.",
    "결제 전에 최신 장바구니 내용을 확인해 주세요.",
    "決済前に最新のカート内容を確認してください。",
  ],
  IDEMPOTENCY_KEY_REUSED: [
    "This payment request no longer matches the cart. Return to the cart and try again.",
    "결제 요청과 장바구니 내용이 달라졌어요. 장바구니로 돌아가 다시 시도해 주세요.",
    "決済リクエストとカート内容が一致しません。カートに戻って再試行してください。",
  ],
  PAYMENT_ALREADY_SUCCEEDED: [
    "This payment is already complete. Open the confirmed order instead.",
    "이미 결제가 완료됐어요. 확정된 주문을 확인해 주세요.",
    "この決済は完了しています。確定済みの注文を確認してください。",
  ],
  ADDRESS_NOT_CONFIRMED: [
    "Confirm your delivery address again before continuing.",
    "계속하기 전에 배달 주소를 다시 확인해 주세요.",
    "続ける前に配達先住所をもう一度確認してください。",
  ],
  ADDRESS_OUTSIDE_SERVICE_AREA: [
    "Enter a supported delivery address or choose a verified address match.",
    "배달 가능한 주소를 입력하거나 확인된 주소 결과를 선택해 주세요.",
    "配達可能な住所を入力するか、確認済みの住所候補を選択してください。",
  ],
  ADDRESS_CANDIDATE_TOKEN_INVALID: [
    "The address check expired. Search for the address again.",
    "주소 확인 시간이 만료됐어요. 주소를 다시 검색해 주세요.",
    "住所確認の有効期限が切れました。もう一度検索してください。",
  ],
  UPLOAD_SIZE_INVALID: [
    "Choose an address image smaller than 8MB.",
    "8MB보다 작은 주소 이미지를 선택해 주세요.",
    "8MB未満の住所画像を選択してください。",
  ],
  UNSUPPORTED_IMAGE_TYPE: [
    "Choose a PNG, JPEG, or WebP address image.",
    "PNG, JPEG 또는 WebP 주소 이미지를 선택해 주세요.",
    "PNG、JPEG、またはWebPの住所画像を選択してください。",
  ],
  IMAGE_EXTENSION_MISMATCH: [
    "The file extension does not match the image type. Choose another image.",
    "파일 확장자와 이미지 형식이 맞지 않아요. 다른 이미지를 선택해 주세요.",
    "拡張子と画像形式が一致しません。別の画像を選択してください。",
  ],
  IMAGE_MAGIC_BYTE_INVALID: [
    "That file is not a readable image. Choose another PNG, JPEG, or WebP file.",
    "읽을 수 있는 이미지가 아니에요. 다른 PNG, JPEG 또는 WebP 파일을 선택해 주세요.",
    "読み取れる画像ではありません。別のPNG、JPEG、またはWebPファイルを選択してください。",
  ],
  IMAGE_DECODE_FAILED: [
    "That image could not be read. Try a clearer image or enter the address manually.",
    "이미지를 읽지 못했어요. 더 선명한 이미지를 사용하거나 주소를 직접 입력해 주세요.",
    "画像を読み取れませんでした。鮮明な画像を使うか、住所を直接入力してください。",
  ],
  CHAT_STATE_VERSION_CONFLICT: [
    "Your choices changed in another action. Review the latest result and try again.",
    "다른 작업에서 선택 내용이 변경됐어요. 최신 결과를 확인하고 다시 시도해 주세요.",
    "別の操作で選択内容が変わりました。最新の結果を確認して再試行してください。",
  ],
  RECOMMENDATION_SNAPSHOT_NOT_FOUND: [
    "That recommendation is no longer available. Request a fresh set of menus.",
    "해당 추천을 더 이상 이용할 수 없어요. 메뉴를 다시 추천받아 주세요.",
    "そのおすすめは利用できません。新しいメニュー候補を取得してください。",
  ],
  MENU_NOT_IN_RECOMMENDATION_SNAPSHOT: [
    "That menu is not part of the latest recommendation. Choose from the current cards.",
    "해당 메뉴는 최신 추천에 포함되지 않아요. 현재 카드에서 선택해 주세요.",
    "そのメニューは最新のおすすめに含まれていません。現在のカードから選択してください。",
  ],
  OPTIONS_REQUIRE_SELECTED_MENU: [
    "Choose the menu again before changing its options.",
    "옵션을 변경하기 전에 메뉴를 다시 선택해 주세요.",
    "オプションを変更する前にメニューを選び直してください。",
  ],
  RESTAURANT_NOTE_TRANSLATION_REQUIRED: [
    "Translate the restaurant note into Korean before adding the menu.",
    "메뉴를 담기 전에 가게 요청사항을 한국어로 번역해 주세요.",
    "メニューを追加する前に、店舗へのメモを韓国語に翻訳してください。",
  ],
  RESTAURANT_NOTE_TRANSLATION_INVALID: [
    "The saved translation no longer matches this note. Translate it again.",
    "저장된 번역이 현재 요청사항과 맞지 않아요. 다시 번역해 주세요.",
    "保存された翻訳が現在のメモと一致しません。もう一度翻訳してください。",
  ],
  PREFERENCE_CATALOG_NOT_AVAILABLE: [
    "The current food choices could not be loaded. Try again.",
    "현재 음식 선택지를 불러오지 못했어요. 다시 시도해 주세요.",
    "現在の料理選択肢を読み込めませんでした。再試行してください。",
  ],
  PREFERENCE_CATALOG_CHANGED: [
    "The available food choices changed. Review the refreshed choices and try again.",
    "선택 가능한 음식 조건이 변경됐어요. 새로고침된 내용을 확인하고 다시 시도해 주세요.",
    "選択できる料理条件が変更されました。更新内容を確認して再試行してください。",
  ],
  PREFERENCE_CATALOG_VERSION_CONFLICT: [
    "The available food choices changed. Review the refreshed choices and try again.",
    "선택 가능한 음식 조건이 변경됐어요. 새로고침된 내용을 확인하고 다시 시도해 주세요.",
    "選択できる料理条件が変更されました。更新内容を確認して再試行してください。",
  ],
  RECOMMENDATION_CRITERIA_INVALID: [
    "Review the selected food preferences and try again.",
    "선택한 음식 취향을 확인하고 다시 시도해 주세요.",
    "選択した料理の好みを確認して再試行してください。",
  ],
  RECOMMENDATION_IN_PROGRESS: [
    "YOBI is still preparing this recommendation.",
    "YOBI가 아직 추천을 준비하고 있어요.",
    "YOBIがおすすめを準備しています。",
  ],
  RECOMMENDATION_FAILED: [
    "YOBI could not finish this recommendation. Your selections are still saved.",
    "추천을 완료하지 못했어요. 선택한 조건은 그대로 저장돼 있어요.",
    "おすすめを完了できませんでした。選択した条件は保存されています。",
  ],
  RECOMMENDATION_REQUEST_NOT_FOUND: [
    "This recommendation request is no longer available. Request a fresh set of menus.",
    "해당 추천 요청을 더 이상 이용할 수 없어요. 메뉴를 다시 추천받아 주세요.",
    "そのおすすめリクエストは利用できません。新しい候補を取得してください。",
  ],
  REQUEST_TIMEOUT: [
    "This is taking longer than expected. YOBI will check the same request instead of starting another one.",
    "예상보다 오래 걸리고 있어요. 새 요청을 만들지 않고 같은 요청을 다시 확인할게요.",
    "予想より時間がかかっています。新しい処理を始めず、同じリクエストを確認します。",
  ],
  REQUEST_ABORTED: [
    "The request was stopped safely. Your saved choices did not change.",
    "요청을 안전하게 중단했어요. 저장된 선택 내용은 바뀌지 않았어요.",
    "処理を安全に停止しました。保存済みの選択内容は変わっていません。",
  ],
  RECOMMENDATION_PREVIEW_UNAVAILABLE: [
    "The live combination preview is temporarily unavailable.",
    "선택 조합 미리보기를 잠시 이용할 수 없어요.",
    "選択条件のプレビューは一時的に利用できません。",
  ],
  RECOMMENDATION_COMPARISON_FAILED: [
    "YOBI could not compare these menus. The recommendation itself has not changed.",
    "메뉴 비교를 완료하지 못했어요. 추천 결과는 변경되지 않았어요.",
    "メニューを比較できませんでした。おすすめ結果は変更されていません。",
  ],
};

export function actionableError(cause: unknown, fallback: string, language = "English") {
  const code = cause instanceof Error ? cause.message : "";
  const localized = ACTIONABLE_ERRORS[code];
  if (!localized) return fallback;
  const effectiveLanguage = asEffectiveLanguage(language);
  return localized[effectiveLanguage === "한국어" ? 1 : effectiveLanguage === "日本語" ? 2 : 0];
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
    const response = await fetchWithTimeout(
      `/api/v1/recommendation/preferences/catalog?locale=${encodeURIComponent(locale)}`,
      { headers },
      { timeoutMs: 8_000 },
    );
    if (response.status === 304 && cached) {
      return { catalog: cached.catalog, etag: cached.etag, notModified: true };
    }
    if (!response.ok) {
      throw new Error(await responseErrorCode(response, "PREFERENCE_CATALOG_NOT_AVAILABLE"));
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
    }, { timeoutMs: 30_000, signal }),
  getRecommendationRequest: (sessionId: string, requestId: string, signal?: AbortSignal) =>
    request<RecommendationBatchV2>(
      `/api/v1/sessions/${sessionId}/recommendation-requests/${encodeURIComponent(requestId)}`,
      undefined,
      { timeoutMs: 8_000, signal },
    ),
  cancelRecommendationRequest: (sessionId: string, requestId: string) =>
    request<{ cancelled: boolean }>(
      `/api/v1/sessions/${sessionId}/recommendation-requests/${encodeURIComponent(requestId)}/cancel`,
      { method: "POST" },
    ),
  compareRecommendations: (
    sessionId: string,
    input: { snapshot_id: string; request_id: string; idempotency_key: string },
    signal?: AbortSignal,
  ) => request<RecommendationComparisonV2>(`/api/v1/sessions/${sessionId}/recommendation-comparisons`, {
    method: "POST",
    body: JSON.stringify(input),
  }, { timeoutMs: 15_000, signal }),
  getFoodRankings: (
    sessionId: string,
    sort: FoodRankingSort,
    signal?: AbortSignal,
    limit = 20,
  ) =>
    request<FoodRankingCollection>(
      `/api/v1/sessions/${sessionId}/food-rankings?sort=${encodeURIComponent(sort)}&limit=${limit}`,
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
  getOptions: (menuId: string, sessionId?: string, precomputedOnly = false) => {
    const params = new URLSearchParams();
    if (sessionId) params.set("session_id", sessionId);
    if (precomputedOnly) params.set("precomputed_only", "true");
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return request<OptionGroup[]>(
      `/api/v1/menus/${menuId}/options${query}`,
      undefined,
      { timeoutMs: 35_000 },
    );
  },
  getMerchantMenus: (sessionId: string, merchantId: string, excludedMenuIds: string[]) =>
    request<import("../types").MenuSummary[]>(
      `/api/v1/sessions/${sessionId}/merchants/${merchantId}/menus?exclude=${encodeURIComponent(excludedMenuIds.join(","))}`,
    ),
  getMerchantMenuPresentations: (
    sessionId: string,
    merchantId: string,
    input: { cursor?: string | null; limit?: number; exclude_menu_ids?: string[] },
  ) => request<MerchantMenuPresentationPage>(
    `/api/v1/sessions/${sessionId}/merchants/${merchantId}/menu-presentations`,
    { method: "POST", body: JSON.stringify(input) },
    { timeoutMs: 30_000 },
  ),
  translateRestaurantNote: (
    sessionId: string,
    sourceText: string,
    sourceLanguage: string,
  ) => request<RestaurantNoteTranslation>(
    `/api/v1/sessions/${sessionId}/restaurant-note-translations`,
    {
      method: "POST",
      body: JSON.stringify({ source_text: sourceText, source_language: sourceLanguage }),
    },
    { timeoutMs: 30_000 },
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
    noteTranslationId?: string | null,
  ) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/items`, {
      method: "POST",
      headers: { "Idempotency-Key": clientRequestId("cart") },
      body: JSON.stringify({
        menu_id: menuId,
        quantity: 1,
        option_item_ids: optionItemIds,
        user_note: userNote,
        note_translation_id: noteTranslationId || undefined,
      }),
    }),
  uploadAddress: async (sessionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetchWithTimeout(`/api/v1/sessions/${sessionId}/address/attachments`, {
      method: "POST",
      body: form,
    }, { timeoutMs: 30_000 });
    if (!response.ok) {
      throw new Error(await responseErrorCode(response, "ADDRESS_UPLOAD_FAILED"));
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
  updateDelivery: (
    sessionId: string,
    addressRefId: string,
    preference: {
      handoff_method: "front_desk" | "door" | "meet_outside";
      cutlery: boolean;
      ring_bell: boolean;
      front_desk: boolean;
      user_note: string;
    } = {
      handoff_method: "front_desk",
      cutlery: true,
      ring_bell: false,
      front_desk: true,
      user_note: "Please leave it at the hotel front desk and include disposable cutlery.",
    },
  ) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/delivery`, {
      method: "PATCH",
      body: JSON.stringify({
        address_ref_id: addressRefId,
        ...preference,
      }),
    }),
  confirmCart: (sessionId: string) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/confirm`, {
      method: "POST",
    }),
  updateCartItem: (
    sessionId: string,
    cartItemId: string,
    update: number | {
      quantity?: number;
      option_item_ids?: string[];
      user_note?: string;
      note_translation_id?: string;
    },
  ) =>
    request<CartPreview>(`/api/v1/sessions/${sessionId}/cart/items/${cartItemId}`, {
      method: "PATCH",
      body: JSON.stringify(typeof update === "number" ? { quantity: update } : update),
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
