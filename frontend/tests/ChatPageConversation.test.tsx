import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  schema_version: "2",
  catalog_version: "catalog-v2-test",
  knowledge_release_id: "knowledge-v2-test",
  locale: "en",
  categories: [
    {
      code: "cuisine_origins",
      label: "Cuisine",
      options: [{ code: "KOREAN", label: "Korean" }, { code: "CHINESE", label: "Chinese" }],
    },
    {
      code: "flavors",
      label: "Flavor",
      options: [{ code: "SWEET", label: "Sweet" }, { code: "SALTY", label: "Salty" }],
    },
    {
      code: "main_ingredients",
      label: "Main ingredient",
      options: [{ code: "PORK", label: "Pork" }, { code: "VEGETABLE", label: "Vegetables" }],
    },
  ],
  spice_references: (["KR", "US"] as const).map((country) => ({
    country,
    label: `${country} examples`,
    levels: ([1, 2, 3, 4, 5] as const).map((level) => ({ level, label: `${level}`, example: `Food ${level}` })),
  })),
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
  }

  it("uses chips instead of free text and submits the catalog-bound v2 criteria before recommending", async () => {
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

    expect(await screen.findByRole("heading", { name: "What sounds good?" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Korean" }));
    fireEvent.click(screen.getByRole("button", { name: "Sweet" }));
    fireEvent.click(screen.getByRole("button", { name: /Show my recommendations/ }));

    await waitFor(() => expect(putCriteria).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({ cuisine_origins: ["KOREAN"], flavors: ["SWEET"] }),
      0,
      catalog.catalog_version,
      expect.stringMatching(/^criteria-/),
    ));
    await waitFor(() => expect(createRecommendation).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({ criteria_version: 1, expected_state_version: 1, mode: "INITIAL" }),
    ));
    expect(await screen.findByText("An easy Korean meal")).toBeInTheDocument();
  });

  it("blocks an explicit vegan or halal ingredient conflict before any API mutation", async () => {
    prepareStore();
    vi.spyOn(api, "getPreferenceCatalog").mockResolvedValue({ catalog, etag: '"catalog-v2-test"', notModified: false });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation());
    const putCriteria = vi.spyOn(api, "putRecommendationCriteria");

    renderPage();
    await screen.findByRole("heading", { name: "What sounds good?" });
    fireEvent.click(screen.getByRole("button", { name: "Pork" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Only show halal-certified restaurants/ }));

    expect(screen.getByRole("alert")).toHaveTextContent("conflicts with the halal or vegan filter");
    expect(screen.getByRole("button", { name: /Show my recommendations/ })).toBeDisabled();
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
    expect(await screen.findByRole("heading", { name: "What sounds good?" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Korean" })).toHaveAttribute("aria-pressed", "true"));
    const hydrationReads = getConversation.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /Show my recommendations/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("available choices were updated");
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
    await screen.findByRole("heading", { name: "What sounds good?" });
    useSessionStore.getState().setDraftCriteria({
      ...emptyCriteria(profile),
      cuisine_origins: ["RETIRED_CUISINE"],
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("available choices were updated");
    await waitFor(() => expect(useSessionStore.getState().draftCriteria.cuisine_origins).toEqual([]));
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
