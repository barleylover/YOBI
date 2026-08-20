import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ChatPage } from "../src/routes/ChatPage";
import { api } from "../src/lib/api";
import { emptyCriteria, useSessionStore } from "../src/stores/session";
import type {
  ConversationView,
  MealNeedState,
  MenuSummary,
  PreferenceCatalog,
  Profile,
  RecommendationBatchV2,
  Session,
} from "../src/types";

const mealNeedState: MealNeedState = {
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

const profile: Profile = {
  profile_id: "profile_frontend_test",
  preferred_language: "English",
  nationality: "United States",
  religion_selection: "Prefer not to say",
  spice_tolerance: 1,
  dietary_rules: [],
  favorite_foods: [],
  age_band: "25-34",
  consent_demo_data: true,
  remember_profile: false,
};

const session: Session = {
  session_id: "session_frontend_test",
  profile_id: profile.profile_id,
  state: "DISCOVERY",
  state_version: 0,
};

const menu: MenuSummary = {
  menu_id: "menu_internal_1",
  merchant_id: "merchant_internal_1",
  merchant_name: "YOBI Kitchen",
  name_en: "Wiki gimbap",
  name_ko: "위키 김밥",
  category: "Gimbap",
  description: "A compact rice-and-seaweed meal.",
  cultural_description: "Often chosen for an easy meal.",
  price: 9000,
  delivery_fee: 2000,
  eta_min: 20,
  eta_max: 30,
  spice_level: 1,
  serves_min: 1,
  serves_max: 1,
  dietary_summary: "",
  evidence_status: "VERIFIED",
  match_reasons: [],
  risk_hints: [],
  evidence_ids: [],
  grounded_claim_ids: [],
  grounded_passage_ids: [],
  is_synthetic: true,
};

const catalog: PreferenceCatalog = {
  schema_version: "3",
  catalog_version: "catalog-v2-test",
  knowledge_release_id: "knowledge-v2-test",
  locale: "en",
  categories: [
    {
      code: "cuisine_origins",
      group: "core",
      label: "Cuisine",
      options: [
        { code: "KOREAN", label: "Korean" },
        { code: "CHINESE", label: "Chinese" },
        { code: "JAPANESE", label: "Japanese" },
        { code: "ITALIAN", label: "Italian" },
        { code: "AMERICAN", label: "American & grill" },
        { code: "SOUTHEAST_ASIAN", label: "Southeast Asian" },
        { code: "MEXICAN", label: "Mexican" },
      ],
    },
    {
      code: "flavors",
      group: "additional",
      label: "Flavor",
      options: [{ code: "SWEET", label: "Sweet" }, { code: "SALTY", label: "Salty" }],
    },
    {
      code: "main_ingredients",
      group: "core",
      label: "Main ingredient",
      options: [{ code: "PORK", label: "Pork" }, { code: "VEGETABLE", label: "Vegetables" }],
    },
  ],
  spice_references: (["KR", "US"] as const).map((country) => ({
    country,
    label: `${country} examples`,
    levels: ([1, 2, 3, 4, 5] as const).map((level) => ({ level, label: `${level}`, example: `Food ${level}` })),
  })),
  price_range_krw: { min: 8000, max: 25000, step: 1000 },
  country_spice_profiles: [
    { country_code: "KR", spice_baseline: 4, representative_dish: "Shin Ramyun" },
    { country_code: "US", spice_baseline: 2, representative_dish: "Buffalo wings" },
  ],
  capabilities: {
    halal_certified_only: { enabled: true },
    vegan: { enabled: true },
  },
};

const criteria = { ...emptyCriteria(profile), cuisine_origins: ["KOREAN"], flavors: ["SWEET"] };
const batch: RecommendationBatchV2 = {
  session_id: session.session_id,
  request_id: "recommendation-test-request",
  snapshot_id: "snapshot_v2_1",
  state_version: 2,
  criteria_version: 1,
  status: "RECOMMENDED",
  phase: "COMPLETE",
  criteria_summary: "Korean and sweet",
  recommendations: [{
    rank: 1,
    menu,
    title: "An easy Korean meal",
    localized_title: "An easy Korean meal",
    localized_subtitle: "A compact Korean rice-and-seaweed roll",
    selection_reason: "It matches one selected value in each active category.",
    description: "The food Wiki describes this as a compact, lightly seasoned meal.",
    matched_criteria: [
      { category_code: "cuisine_origins", selected_value_codes: ["KOREAN"] },
      { category_code: "flavors", selected_value_codes: ["SWEET"] },
    ],
    wiki_passages: [{
      evidence_id: "wiki-1",
      evidence_type: "WIKI_PASSAGE",
      content: "Gimbap wraps rice and fillings in seaweed.",
      score: 0.92,
    }],
    caution_codes: [],
  }],
  unmatched_category_codes: [],
};

const preview = {
  eligible_menu_count: 8,
  eligible_merchant_count: 4,
  zero_reason_codes: [],
  release_id: "release-v2-test",
  support_manifest_sha256: "support-v2-test",
  ranking_policy_version: "ranking-v2-test",
  timing_ms: 4,
};

function conversation(overrides: Partial<ConversationView> = {}): ConversationView {
  return {
    session_id: session.session_id,
    state_version: 0,
    meal_need_state: mealNeedState,
    messages: [],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/chat/${session.session_id}`]}>
      <Routes>
        <Route path="/chat/:sessionId" element={<ChatPage />} />
        <Route path="/" element={<div />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ChatPage structured recommendation contract", () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.scrollTo = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    useSessionStore.getState().clear();
  });

  function prepareStore() {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_frontend_test",
      addressSummary: "YOBI hotel",
      cartQuantity: 0,
      draftCriteria: emptyCriteria(profile),
      committedCriteria: null,
      criteriaVersion: 0,
      recommendationPhase: "SELECTING",
      pendingRecommendation: null,
      latestRecommendation: null,
    });
    vi.spyOn(api, "previewRecommendation").mockResolvedValue(preview);
  }

  it("uses the staged controls and submits catalog-bound v3 criteria before recommending", async () => {
    prepareStore();
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({ catalog, etag: '"catalog-v2-test"', notModified: false });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation());
    const putCriteria = vi.spyOn(api, "putRecommendationCriteria").mockResolvedValue({
      session_id: session.session_id,
      criteria,
      criteria_version: 1,
      state_version: 1,
    });
    const createRecommendation = vi.spyOn(api, "createRecommendation").mockResolvedValue(batch);

    renderPage();

    expect(await screen.findByRole("heading", { name: "What are you craving?" })).toBeInTheDocument();
    for (const cuisine of ["Japanese", "Italian", "American & grill", "Southeast Asian", "Mexican"]) {
      expect(screen.getByRole("button", { name: cuisine })).toBeInTheDocument();
    }
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Korean" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Korean" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByText("8 menus from 4 restaurants currently fit")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Sweet" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sweet" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("radio", { name: "About the same" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("slider", { name: "Minimum price" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /Halal-certified only/ })).toBeEnabled();
    expect(screen.getByRole("switch", { name: /Vegan options only/ })).toBeEnabled();
    expect(screen.getByText("United States reference: Buffalo wings · spice 2/5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Find my dish/ }));

    await waitFor(() => expect(putCriteria).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({
        schema_version: "3",
        cuisine_origins: ["KOREAN"],
        flavors: ["SWEET"],
        spice_preference: "SIMILAR",
        price_range_krw: { min: 8000, max: 25000 },
      }),
      0,
      catalog.catalog_version,
      expect.stringMatching(/^criteria-/),
    ));
    await waitFor(() => expect(createRecommendation).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({ criteria_version: 1, expected_state_version: 1, mode: "INITIAL" }),
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText("An easy Korean meal")).toBeInTheDocument();
    const craving = screen.getByTestId("craving-question-message");
    const preference = screen.getByTestId("user-preference-message");
    const recommendations = screen.getByTestId("recommendation-results-message");
    expect(preference).toHaveTextContent("Korean");
    expect(preference).toHaveTextContent("Sweet");
    expect(craving.compareDocumentPosition(preference) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(preference.compareDocumentPosition(recommendations) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("A compact Korean rice-and-seaweed roll")).toBeInTheDocument();
  }, 10_000);

  it("polls one persisted pending request until the same request completes", async () => {
    prepareStore();
    const pendingBatch: RecommendationBatchV2 = {
      ...batch,
      snapshot_id: null,
      status: "PENDING",
      phase: "RETRIEVING",
      recommendations: [],
    };
    useSessionStore.setState({
      committedCriteria: criteria,
      draftCriteria: criteria,
      criteriaVersion: 1,
      recommendationPhase: "RETRIEVING",
      pendingRecommendation: {
        request_id: pendingBatch.request_id,
        expected_state_version: pendingBatch.state_version,
        criteria_version: pendingBatch.criteria_version,
        mode: "INITIAL",
      },
      latestRecommendation: pendingBatch,
    });
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({
      catalog,
      etag: '"catalog-v2-test"',
      notModified: false,
    });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation({
      state_version: pendingBatch.state_version,
      recommendation_criteria: criteria,
      criteria_version: 1,
      latest_recommendation: pendingBatch,
      active_recommendation: pendingBatch,
    }));
    const createRecommendation = vi.spyOn(api, "createRecommendation");
    const poll = vi.spyOn(api, "getRecommendationRequest")
      .mockResolvedValueOnce(pendingBatch)
      .mockResolvedValueOnce(batch);

    renderPage();

    await waitFor(() => expect(poll).toHaveBeenCalledTimes(2), { timeout: 6_000 });
    expect(poll).toHaveBeenNthCalledWith(
      1,
      session.session_id,
      pendingBatch.request_id,
    );
    expect(createRecommendation).not.toHaveBeenCalled();
    expect(await screen.findByText("An easy Korean meal")).toBeInTheDocument();
  }, 8_000);

  it("stays on conditions after cancel even when the provider result arrives late", async () => {
    prepareStore();
    const pendingBatch: RecommendationBatchV2 = {
      ...batch,
      snapshot_id: null,
      status: "PENDING",
      phase: "GENERATING",
      recommendations: [],
    };
    useSessionStore.setState({
      committedCriteria: criteria,
      draftCriteria: criteria,
      criteriaVersion: 1,
      recommendationPhase: "GENERATING",
      pendingRecommendation: {
        request_id: pendingBatch.request_id,
        expected_state_version: pendingBatch.state_version,
        criteria_version: pendingBatch.criteria_version,
        mode: "INITIAL",
      },
      latestRecommendation: pendingBatch,
    });
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({
      catalog,
      etag: '"catalog-v2-test"',
      notModified: false,
    });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation({
      state_version: pendingBatch.state_version,
      recommendation_criteria: criteria,
      criteria_version: 1,
      latest_recommendation: pendingBatch,
      active_recommendation: pendingBatch,
    }));
    let resolveLate: (value: RecommendationBatchV2) => void = () => undefined;
    const lateCompletion = new Promise<RecommendationBatchV2>((resolve) => { resolveLate = resolve; });
    vi.spyOn(api, "getRecommendationRequest").mockReturnValue(lateCompletion);
    const cancel = vi.spyOn(api, "cancelRecommendationRequest").mockResolvedValue({ cancelled: true });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel and edit conditions" }));

    await waitFor(() => expect(cancel).toHaveBeenCalledWith(session.session_id, pendingBatch.request_id));
    expect(await screen.findByRole("radio", { name: "About the same" })).toBeInTheDocument();
    resolveLate(batch);
    await waitFor(() => expect(screen.getByRole("radio", { name: "About the same" })).toBeInTheDocument());
    expect(screen.queryByText("An easy Korean meal")).not.toBeInTheDocument();
    expect(useSessionStore.getState().recommendationPhase).toBe("SELECTING");
  });

  it("blocks an explicit vegan or halal ingredient conflict before any API mutation", async () => {
    prepareStore();
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({ catalog, etag: '"catalog-v2-test"', notModified: false });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation());
    const putCriteria = vi.spyOn(api, "putRecommendationCriteria");

    renderPage();
    await screen.findByRole("heading", { name: "What are you craving?" });
    fireEvent.click(screen.getByRole("button", { name: "Pork" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Pork" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("switch", { name: /Halal-certified only/ }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("conflicts with the halal or vegan filter"));
    expect(screen.getByRole("button", { name: /Find my dish/ })).toBeDisabled();
    expect(putCriteria).not.toHaveBeenCalled();
  });

  it("forces a catalog refresh instead of treating stale committed criteria as an idempotent success", async () => {
    prepareStore();
    const getCatalog = vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({
      catalog,
      etag: '"catalog-v2-test"',
      notModified: false,
    });
    const getConversation = vi.spyOn(api, "getConversation").mockResolvedValue(conversation({
      state_version: 2,
      recommendation_criteria: criteria,
      criteria_version: 1,
    }));
    vi.spyOn(api, "putRecommendationCriteria").mockRejectedValue(new Error("PREFERENCE_CATALOG_CHANGED"));
    const createRecommendation = vi.spyOn(api, "createRecommendation");

    renderPage();
    expect(await screen.findByRole("heading", { name: "What are you craving?" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Korean" })).toHaveAttribute("aria-pressed", "true"));
    const hydrationReads = getConversation.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: /Find my dish/ }));

    expect(await screen.findByText(/available choices were updated/)).toBeInTheDocument();
    await waitFor(() => expect(getCatalog).toHaveBeenCalledTimes(2));
    expect(getConversation).toHaveBeenCalledTimes(hydrationReads);
    expect(createRecommendation).not.toHaveBeenCalled();
  });

  it("removes retired draft codes and tells the user to review the refreshed catalog", async () => {
    prepareStore();
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({
      catalog,
      etag: '"catalog-v2-test"',
      notModified: false,
    });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation());

    renderPage();
    await screen.findByRole("heading", { name: "What are you craving?" });
    useSessionStore.getState().setDraftCriteria({
      ...emptyCriteria(profile),
      cuisine_origins: ["RETIRED_CUISINE"],
    });

    expect(await screen.findByText(/available choices were updated/)).toBeInTheDocument();
    await waitFor(() => expect(useSessionStore.getState().draftCriteria.cuisine_origins).toEqual([]));
  });

  it("neutralizes unavailable capability controls so they never become hidden filters", async () => {
    prepareStore();
    useSessionStore.getState().setDraftCriteria({
      ...emptyCriteria(profile),
      dietary_filters: { halal_certified_only: true, vegan: true },
      spice_preference: "MORE",
    });
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({
      catalog: {
        ...catalog,
        capabilities: {
          halal_certified_only: { enabled: false, reason: "No certification coverage" },
          vegan: { enabled: false, reason: "No ingredient coverage" },
        },
      },
      etag: '"catalog-v2-test"',
      notModified: false,
    });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation());

    renderPage();
    await screen.findByRole("heading", { name: "What are you craving?" });
    await waitFor(() => expect(useSessionStore.getState().draftCriteria).toMatchObject({
      dietary_filters: { halal_certified_only: false, vegan: false },
      spice_preference: "MORE",
      price_range_krw: { min: 8000, max: 25000 },
    }));
  });

  it("restores a v2 result and selects a menu only through the existing event contract", async () => {
    prepareStore();
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({ catalog, etag: '"catalog-v2-test"', notModified: false });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation({
      state_version: 2,
      recommendation_criteria: criteria,
      criteria_version: 1,
      latest_recommendation: batch,
    }));
    const postEvent = vi.spyOn(api, "postConversationEvent").mockResolvedValue({
      event_id: "event-select-1",
      event_type: "SELECT_MENU",
      state_version: 3,
      state: { ...mealNeedState, selected_menu_id: menu.menu_id },
      selected_menu_id: menu.menu_id,
      selected_merchant_id: menu.merchant_id,
      selected_menu: menu,
      duplicate: false,
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([]);

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Choose this menu" }));

    expect(document.querySelector(".rank-bar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Compare/ })).not.toBeInTheDocument();

    await waitFor(() => expect(postEvent).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({
        event_type: "SELECT_MENU",
        snapshot_id: batch.snapshot_id,
        menu_id: menu.menu_id,
        expected_state_version: 2,
      }),
    ));
    await waitFor(() => expect(screen.getByTestId("order-flow")).toBeInTheDocument());
    expect(screen.getByTestId("selected-menu-message")).toHaveTextContent("An easy Korean meal");
    expect(screen.getByTestId("recommendation-results-message")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose this menu" })).not.toBeInTheDocument();
  });

  it("does not revive a stale v2 selection from the legacy snapshot", async () => {
    prepareStore();
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({ catalog, etag: '"catalog-v2-test"', notModified: false });
    const emptyLiveBatch: RecommendationBatchV2 = {
      ...batch,
      snapshot_id: null,
      status: "NO_MATCH",
      recommendations: [],
      failure_code: "LIVE_ELIGIBILITY_EMPTY",
    };
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation({
      state_version: 3,
      meal_need_state: { ...mealNeedState, selected_menu_id: menu.menu_id },
      latest_recommendation: emptyLiveBatch,
      latest_snapshot: {
        snapshot_id: "stale-snapshot",
        session_id: session.session_id,
        assistant_message_id: "stale-message",
        state_version: 2,
        meal_need_state: { ...mealNeedState, selected_menu_id: menu.menu_id },
        result: {
          snapshot_id: "stale-snapshot",
          candidates: [],
          query_summary: "stale",
          grounded_claim_ids: [],
          grounded_passage_ids: [],
          synthetic_data: true,
        },
        cards: [{ type: "menu_recommendations", data: { menus: [menu] }, title: "Stale" }],
        created_at: new Date().toISOString(),
      },
    }));

    renderPage();

    await waitFor(() => expect(useSessionStore.getState().recommendationPhase).toBe("NO_RESULTS"));
    expect(screen.queryByTestId("order-flow")).not.toBeInTheDocument();
  });
});
