import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ChatPage } from "../src/routes/ChatPage";
import { api } from "../src/lib/api";
import { useSessionStore } from "../src/stores/session";
import type {
  AssistantTurn,
  ConversationView,
  MealNeedState,
  MenuSummary,
  OptionGroup,
  Profile,
  Session,
} from "../src/types";

const needState: MealNeedState = {
  schema_version: 1,
  turn_count: 1,
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
  shown_menu_ids: ["menu_internal_1"],
  rejected_menu_ids: [],
  compared_menu_ids: [],
  option_selections: {},
  option_risk_acknowledged: [],
  recommendation_hold: false,
  strictness: "STRICT",
};

const menu: MenuSummary = {
  menu_id: "menu_internal_1",
  merchant_id: "merchant_internal_1",
  merchant_name: "Synthetic Kitchen",
  name_en: "Server-restored gimbap",
  name_ko: "서버 복원 김밥",
  category: "Gimbap",
  description: "A synthetic menu restored from the server conversation.",
  cultural_description: "A compact rice-and-seaweed meal.",
  price: 9000,
  delivery_fee: 2000,
  eta_min: 20,
  eta_max: 30,
  spice_level: 1,
  serves_min: 1,
  serves_max: 1,
  dietary_summary: "Review the evidence before choosing.",
  evidence_status: "UNKNOWN",
  match_reasons: ["Matches a mild rice preference"],
  risk_hints: ["Kitchen cross-contamination is not verified"],
  evidence_ids: ["evidence_internal_1"],
  grounded_claim_ids: ["claim_internal_1"],
  grounded_passage_ids: ["chunk_internal_1"],
  is_synthetic: true,
};

const turn: AssistantTurn = {
  message_id: "msg_server_1",
  text: "Here is one grounded choice.",
  state: "MENU_EXPLANATION",
  cards: [{ type: "menu_recommendations", title: "Grounded menu matches", data: { menus: [menu] } }],
  suggested_replies: [],
  dialogue_act: "RECOMMEND",
  readiness: {
    status: "READY",
    score: 1,
    information_dimensions: ["preference"],
    missing_fields: [],
    reason: "Enough information is available.",
  },
  recommendation_result: {
    snapshot_id: "snapshot_1",
    candidates: [{
      menu_id: menu.menu_id,
      merchant_id: menu.merchant_id,
      rank: 1,
      score: 1,
      match_reasons: menu.match_reasons,
      risk_hints: menu.risk_hints,
      evidence_ids: menu.evidence_ids,
      claim_ids: menu.grounded_claim_ids,
      passage_ids: menu.grounded_passage_ids,
    }],
    query_summary: "mild rice",
    grounded_claim_ids: [],
    grounded_passage_ids: [],
    synthetic_data: true,
  },
  recommendation_snapshot_id: "snapshot_1",
  state_version: 1,
  fallback_used: false,
  created_at: "2026-08-09T00:00:00Z",
};

const conversation: ConversationView = {
  session_id: "session_frontend_test",
  state_version: 1,
  meal_need_state: needState,
  messages: [
    {
      message_id: "msg_user_1",
      role: "user",
      content: "Mild rice, please.",
      message_type: "text",
      safe_metadata: {},
      created_at: "2026-08-09T00:00:00Z",
    },
    {
      message_id: turn.message_id,
      role: "assistant",
      content: turn.text,
      message_type: "assistant_turn",
      safe_metadata: turn as unknown as Record<string, unknown>,
      created_at: turn.created_at,
    },
  ],
  latest_snapshot: {
    snapshot_id: "snapshot_1",
    session_id: "session_frontend_test",
    assistant_message_id: turn.message_id,
    state_version: 1,
    meal_need_state: needState,
    result: turn.recommendation_result!,
    cards: turn.cards,
    created_at: turn.created_at,
  },
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
  allergy_severity: "mild",
  consent_demo_data: true,
  remember_profile: false,
};

const session: Session = {
  session_id: conversation.session_id,
  profile_id: profile.profile_id,
  state: "DISCOVERY",
  state_version: 0,
};

const optionGroup: OptionGroup = {
  option_group_id: "portion_size",
  name_en: "Portion size",
  name_ko: "양",
  description: "Choose a synthetic portion size.",
  required: true,
  min_select: 1,
  max_select: 1,
  items: [{
    option_item_id: "regular_portion",
    name_en: "Regular",
    name_ko: "보통",
    description: "A regular synthetic portion.",
    price_delta: 0,
    available: true,
    conflicting_rules: [],
  }],
};

describe("ChatPage conversation contract", () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
    useSessionStore.getState().clear();
  });

  it("replaces stale browser cards with the server conversation and selects through the event API", async () => {
    sessionStorage.setItem(
      `yobi-chat-entries-${session.session_id}`,
      JSON.stringify([{ id: "stale", role: "assistant", text: "Stale browser-only result" }]),
    );
    sessionStorage.setItem(
      `yobi-selected-menu-${session.session_id}`,
      JSON.stringify({ ...menu, menu_id: "stale_menu", name_en: "Stale browser menu" }),
    );
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_frontend_test",
      addressSummary: "Synthetic hotel",
      cartQuantity: 0,
    });
    vi.spyOn(api, "getConversation").mockResolvedValue(conversation);
    const selectedState = { ...needState, selected_menu_id: menu.menu_id };
    const postEvent = vi.spyOn(api, "postConversationEvent")
      .mockResolvedValueOnce({
        event_id: "event_1",
        event_type: "SELECT_MENU",
        state_version: 2,
        state: selectedState,
        selected_menu_id: menu.menu_id,
        selected_merchant_id: menu.merchant_id,
        selected_menu: menu,
        duplicate: false,
      })
      .mockResolvedValueOnce({
        event_id: "event_2",
        event_type: "UPDATE_OPTIONS",
        state_version: 3,
        state: {
          ...selectedState,
          option_selections: { [optionGroup.option_group_id]: [optionGroup.items[0].option_item_id] },
        },
        selected_menu_id: menu.menu_id,
        selected_merchant_id: menu.merchant_id,
        duplicate: false,
      });
    vi.spyOn(api, "getOptions").mockResolvedValue([optionGroup]);

    render(
      <MemoryRouter initialEntries={[`/chat/${session.session_id}`]}>
        <Routes>
          <Route path="/chat/:sessionId" element={<ChatPage />} />
          <Route path="/" element={<div />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByTestId("order-flow")).not.toBeInTheDocument();
    expect(screen.queryByText("Stale browser menu")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(menu.name_en)).toBeInTheDocument());
    expect(screen.queryByText("Stale browser-only result")).not.toBeInTheDocument();
    expect(screen.queryByText(menu.menu_id)).not.toBeInTheDocument();
    expect(screen.queryByText(menu.evidence_ids[0])).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Choose this menu" }));
    await waitFor(() => expect(postEvent).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({
        event_type: "SELECT_MENU",
        snapshot_id: "snapshot_1",
        menu_id: menu.menu_id,
        expected_state_version: 1,
      }),
    ));
    await waitFor(() => expect(screen.getByTestId("order-flow")).toBeInTheDocument());

    fireEvent.click(await screen.findByRole("button", { name: /Regular/ }));
    await waitFor(() => expect(postEvent).toHaveBeenNthCalledWith(
      2,
      session.session_id,
      expect.objectContaining({
        event_type: "UPDATE_OPTIONS",
        menu_id: menu.menu_id,
        option_group_id: optionGroup.option_group_id,
        option_item_ids: [optionGroup.items[0].option_item_id],
        expected_state_version: 2,
      }),
    ));
  });

  it("rehydrates a streamed natural-language selection and uses the authoritative state version", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_frontend_test",
      addressSummary: "Synthetic hotel",
      cartQuantity: 0,
    });
    const selectedState = { ...needState, selected_menu_id: menu.menu_id };
    const selectedTurn: AssistantTurn = {
      ...turn,
      message_id: "msg_selected_naturally",
      text: "I selected the first menu. Choose its required option next.",
      dialogue_act: "SELECT",
      cards: [{ type: "option_question", title: "Choose a required option", data: {} }],
      recommendation_result: null,
      state_version: 2,
    };
    const selectedConversation: ConversationView = {
      ...conversation,
      state_version: 4,
      meal_need_state: selectedState,
      messages: [
        ...conversation.messages,
        {
          message_id: selectedTurn.message_id,
          role: "assistant",
          content: selectedTurn.text,
          message_type: "assistant_turn",
          safe_metadata: selectedTurn as unknown as Record<string, unknown>,
          created_at: selectedTurn.created_at,
        },
      ],
    };
    let selectionStreamed = false;
    const getConversation = vi.spyOn(api, "getConversation")
      .mockImplementation(async () => selectionStreamed ? selectedConversation : conversation);
    vi.spyOn(api, "streamMessage").mockImplementation(async () => {
      selectionStreamed = true;
      return selectedTurn;
    });
    vi.spyOn(api, "getOptions").mockResolvedValue([optionGroup]);
    const postEvent = vi.spyOn(api, "postConversationEvent").mockResolvedValue({
      event_id: "event_after_natural_selection",
      event_type: "UPDATE_OPTIONS",
      state_version: 5,
      state: {
        ...selectedState,
        option_selections: { [optionGroup.option_group_id]: [optionGroup.items[0].option_item_id] },
      },
      selected_menu_id: menu.menu_id,
      selected_merchant_id: menu.merchant_id,
      duplicate: false,
    });

    render(
      <MemoryRouter initialEntries={[`/chat/${session.session_id}`]}>
        <Routes>
          <Route path="/chat/:sessionId" element={<ChatPage />} />
          <Route path="/" element={<div />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId(`menu-${menu.menu_id}`)).toBeInTheDocument());
    const hydrationCallCount = getConversation.mock.calls.length;
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Choose the first menu" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(getConversation.mock.calls.length).toBeGreaterThan(hydrationCallCount));
    await waitFor(() => expect(screen.getByTestId("order-flow")).toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: /Regular/ }));
    await waitFor(() => expect(postEvent).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({
        event_type: "UPDATE_OPTIONS",
        menu_id: menu.menu_id,
        expected_state_version: 4,
      }),
    ));
  });

  it("recovers a committed turn after the SSE response is lost", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_frontend_test",
      addressSummary: "Synthetic hotel",
      cartQuantity: 0,
    });
    let requestId = "";
    vi.spyOn(api, "getConversation").mockImplementation(async () => {
      if (!requestId) return conversation;
      const recoveredTurn: AssistantTurn = {
        ...turn,
        message_id: "msg_recovered_after_lost_stream",
        text: "Recovered from the authoritative server conversation.",
        dialogue_act: "GREET",
        cards: [],
        recommendation_result: null,
        recommendation_snapshot_id: null,
        state_version: 2,
      };
      return {
        ...conversation,
        state_version: 2,
        messages: [
          ...conversation.messages,
          {
            message_id: "msg_recovered_user",
            role: "user" as const,
            content: "hi again",
            message_type: "text",
            safe_metadata: { client_request_id: requestId },
            created_at: recoveredTurn.created_at,
          },
          {
            message_id: recoveredTurn.message_id,
            role: "assistant" as const,
            content: recoveredTurn.text,
            message_type: "assistant_turn",
            safe_metadata: {
              ...(recoveredTurn as unknown as Record<string, unknown>),
              client_request_id: requestId,
            },
            created_at: recoveredTurn.created_at,
          },
        ],
      };
    });
    vi.spyOn(api, "streamMessage").mockImplementation(async (...args) => {
      requestId = String(args[4]);
      throw new Error("CHAT_STREAM_INCOMPLETE");
    });

    render(
      <MemoryRouter initialEntries={[`/chat/${session.session_id}`]}>
        <Routes>
          <Route path="/chat/:sessionId" element={<ChatPage />} />
          <Route path="/" element={<div />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId(`menu-${menu.menu_id}`)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hi again" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(
      screen.getByText("Recovered from the authoritative server conversation."),
    ).toBeInTheDocument());
    expect(screen.queryByText(/couldn.t reconnect/i)).not.toBeInTheDocument();
  });

  it("selects a menu embedded in a comparison card through the snapshot event contract", async () => {
    useSessionStore.setState({
      profile,
      session,
      addressRefId: "address_frontend_test",
      addressSummary: "Synthetic hotel",
      cartQuantity: 0,
    });
    const comparisonTurn: AssistantTurn = {
      ...turn,
      message_id: "msg_comparison_1",
      text: "Here is a grounded side-by-side comparison.",
      dialogue_act: "COMPARE",
      cards: [{
        type: "merchant_comparison",
        title: "Grounded merchant comparison",
        data: {
          merchants: [{
            merchant_id: menu.merchant_id,
            merchant_name: menu.merchant_name,
            menu_id: menu.menu_id,
            menu_name: menu.name_en,
            price: menu.price,
            delivery_fee: menu.delivery_fee,
            eta: `${menu.eta_min}-${menu.eta_max} min`,
            portion: "One synthetic serving",
            flavor: "Mild and savory",
            packaging_signal: "Unknown",
            dietary_status: menu.evidence_status,
            dietary_note: menu.dietary_summary,
            best_for: "A mild rice meal",
            evidence_ids: menu.evidence_ids,
            menu,
          }],
        },
      }],
      recommendation_snapshot_id: "snapshot_1",
    };
    const comparisonConversation: ConversationView = {
      ...conversation,
      messages: [{
        message_id: comparisonTurn.message_id,
        role: "assistant",
        content: comparisonTurn.text,
        message_type: "assistant_turn",
        safe_metadata: comparisonTurn as unknown as Record<string, unknown>,
        created_at: comparisonTurn.created_at,
      }],
    };
    vi.spyOn(api, "getConversation").mockResolvedValue(comparisonConversation);
    vi.spyOn(api, "getOptions").mockResolvedValue([optionGroup]);
    const postEvent = vi.spyOn(api, "postConversationEvent").mockResolvedValue({
      event_id: "event_comparison_select",
      event_type: "SELECT_MENU",
      state_version: 2,
      state: { ...needState, selected_menu_id: menu.menu_id },
      selected_menu_id: menu.menu_id,
      selected_merchant_id: menu.merchant_id,
      selected_menu: menu,
      duplicate: false,
    });
    const streamMessage = vi.spyOn(api, "streamMessage");

    render(
      <MemoryRouter initialEntries={[`/chat/${session.session_id}`]}>
        <Routes>
          <Route path="/chat/:sessionId" element={<ChatPage />} />
          <Route path="/" element={<div />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: menu.merchant_name });
    fireEvent.click(screen.getByRole("button", { name: "Choose this menu" }));
    await waitFor(() => expect(postEvent).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({
        event_type: "SELECT_MENU",
        snapshot_id: "snapshot_1",
        menu_id: menu.menu_id,
        expected_state_version: 1,
      }),
    ));
    expect(streamMessage).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("order-flow")).toBeInTheDocument());
  });
});
