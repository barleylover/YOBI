import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, ShoppingBag, Sparkles } from "lucide-react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { ChatRoomMenu } from "../components/ChatRoomMenu";
import { OrderFlowPanel } from "../components/OrderFlowPanel";
import { RichCard } from "../components/RichCard";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSessionStore } from "../stores/session";
import type {
  AssistantTurn,
  CardPayload,
  ConversationEventInput,
  ConversationMessage,
  ConversationView,
  MenuSummary,
} from "../types";

interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  turn?: AssistantTurn;
}

function createChatEntryId() {
  return globalThis.crypto?.randomUUID?.() ?? `entry_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function assistantTurnFromMessage(message: ConversationMessage): AssistantTurn | undefined {
  const value = message.safe_metadata;
  if (
    message.role !== "assistant"
    || typeof value.message_id !== "string"
    || typeof value.text !== "string"
    || !Array.isArray(value.cards)
    || !Array.isArray(value.suggested_replies)
  ) return undefined;
  return value as unknown as AssistantTurn;
}

function findMenu(value: unknown, menuId: string): MenuSummary | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const match = findMenu(item, menuId);
      if (match) return match;
    }
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (record.menu_id === menuId && typeof record.merchant_id === "string" && typeof record.name_en === "string") {
    return record as unknown as MenuSummary;
  }
  for (const item of Object.values(record)) {
    const match = findMenu(item, menuId);
    if (match) return match;
  }
  return null;
}

function eventIdempotencyKey(kind: string) {
  return `${kind}-${createChatEntryId()}`;
}

export function ChatPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const profile = useSessionStore((state) => state.profile);
  const session = useSessionStore((state) => state.session);
  const addressRefId = useSessionStore((state) => state.addressRefId);
  const cartQuantity = useSessionStore((state) => state.cartQuantity);
  const { chatMenuCopy, copy, dynamicCopy, journeyCopy, language } = useI18n();
  const chatCacheKey = `yobi-chat-entries-${sessionId}`;
  const inputCacheKey = `yobi-chat-input-${sessionId}`;
  const selectedMenuCacheKey = `yobi-selected-menu-${sessionId}`;
  const pendingRequestCacheKey = `yobi-chat-pending-request-${sessionId}`;
  const [input, setInput] = useState(() => sessionStorage.getItem(inputCacheKey) ?? "");
  const [hydrating, setHydrating] = useState(true);
  const [sending, setSending] = useState(false);
  const [eventPending, setEventPending] = useState(false);
  const [interactionError, setInteractionError] = useState("");
  const [activity, setActivity] = useState(copy.checking);
  const stateVersionRef = useRef(session?.state_version ?? 0);
  // A cached menu is only a projection cache. The server conversation must first
  // confirm the selected menu id before the order builder can be restored.
  const [selectedMenu, setSelectedMenu] = useState<MenuSummary | null>(null);
  const [entries, setEntries] = useState<ChatEntry[]>(() => {
    try {
      const cached = JSON.parse(sessionStorage.getItem(chatCacheKey) ?? "null") as ChatEntry[] | null;
      if (cached?.length) return cached;
    } catch { /* Ignore an invalid browser-only cache. */ }
    return [{ id: "welcome", role: "assistant", text: copy.hello }];
  });

  const activeRules = useMemo(() => profile?.dietary_rules ?? [], [profile]);
  function openCart() {
    document.querySelector<HTMLElement>("[data-testid='order-flow']")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const localizedAssistantText = useCallback((turn: AssistantTurn | undefined, serverText: string) => {
    if (!turn || language === "English") return serverText;
    if (turn.fallback_used) return dynamicCopy.fallbackResult;
    const preset = turn.cards.find((card): card is Extract<CardPayload, { type: "preset_collection" }> => card.type === "preset_collection");
    if (preset?.data.kind === "weekly_ranking") return chatMenuCopy.weeklyResponse;
    if (preset?.data.kind === "kpop_demon_hunters") return chatMenuCopy.kpopResponse;
    return serverText;
  }, [chatMenuCopy.kpopResponse, chatMenuCopy.weeklyResponse, dynamicCopy.fallbackResult, language]);

  const applyConversation = useCallback((conversation: ConversationView) => {
    stateVersionRef.current = conversation.state_version;
    const authoritativeEntries: ChatEntry[] = conversation.messages.map((message) => {
      const turn = assistantTurnFromMessage(message);
      return {
        id: message.message_id,
        role: message.role,
        text: localizedAssistantText(turn, message.content),
        turn,
      };
    });
    setEntries(authoritativeEntries.length
      ? authoritativeEntries
      : [{ id: "welcome", role: "assistant", text: copy.hello }]);

    const selectedMenuId = conversation.meal_need_state.selected_menu_id;
    if (!selectedMenuId) {
      setSelectedMenu(null);
      return;
    }
    const turns = conversation.messages
      .map(assistantTurnFromMessage)
      .filter((turn): turn is AssistantTurn => Boolean(turn));
    const restored = findMenu(conversation.latest_snapshot?.cards, selectedMenuId)
      ?? findMenu(turns.map((turn) => turn.cards), selectedMenuId);
    if (restored) {
      setSelectedMenu(restored);
      return;
    }
    try {
      const cached = JSON.parse(sessionStorage.getItem(selectedMenuCacheKey) ?? "null") as MenuSummary | null;
      setSelectedMenu(cached?.menu_id === selectedMenuId ? cached : null);
    } catch {
      setSelectedMenu(null);
    }
  }, [copy.hello, localizedAssistantText, selectedMenuCacheKey]);

  const refreshConversation = useCallback(async () => {
    const conversation = await api.getConversation(sessionId);
    applyConversation(conversation);
    return conversation;
  }, [applyConversation, sessionId]);

  async function recordConversationEvent(event: Omit<ConversationEventInput, "idempotency_key" | "expected_state_version">) {
    const result = await api.postConversationEvent(sessionId, {
      ...event,
      expected_state_version: stateVersionRef.current,
      idempotency_key: eventIdempotencyKey(event.event_type.toLowerCase()),
    });
    stateVersionRef.current = result.state_version;
    return result;
  }

  async function chooseMenu(menu: MenuSummary, snapshotId: string | null | undefined) {
    if (!snapshotId) {
      setInteractionError("This card is no longer linked to a current recommendation. Ask YOBI to show the menu again.");
      return;
    }
    setEventPending(true);
    setInteractionError("");
    try {
      const result = await recordConversationEvent({
        event_type: "SELECT_MENU",
        snapshot_id: snapshotId,
        menu_id: menu.menu_id,
      });
      setSelectedMenu(result.selected_menu ?? menu);
    } catch (cause) {
      setInteractionError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
      await refreshConversation().catch(() => undefined);
    } finally {
      setEventPending(false);
    }
  }

  useEffect(() => {
    if (!selectedMenu) return;
    const timer = window.setTimeout(() => {
      document.querySelector<HTMLElement>("[data-testid='order-flow']")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [selectedMenu]);
  useEffect(() => {
    if (!sessionId || session?.session_id !== sessionId) return;
    let active = true;
    setHydrating(true);
    api.getConversation(sessionId)
      .then((conversation) => { if (active) applyConversation(conversation); })
      .catch(() => undefined)
      .finally(() => { if (active) setHydrating(false); });
    return () => {
      active = false;
    };
  }, [applyConversation, session?.session_id, sessionId]);
  useEffect(() => {
    sessionStorage.setItem(chatCacheKey, JSON.stringify(entries));
  }, [chatCacheKey, entries]);
  useEffect(() => {
    sessionStorage.setItem(inputCacheKey, input);
  }, [input, inputCacheKey]);
  useEffect(() => {
    if (selectedMenu) sessionStorage.setItem(selectedMenuCacheKey, JSON.stringify(selectedMenu));
    else sessionStorage.removeItem(selectedMenuCacheKey);
  }, [selectedMenu, selectedMenuCacheKey]);
  useEffect(() => {
    setEntries((current) => current.map((entry) => entry.id === "welcome" ? { ...entry, text: copy.hello } : entry));
  }, [copy.hello]);
  useEffect(() => {
    const saved = Number(sessionStorage.getItem(`yobi-chat-scroll-${sessionId}`) ?? "0");
    if (saved > 0) requestAnimationFrame(() => window.scrollTo({ top: saved }));
  }, [sessionId]);
  if (!profile || !session || session.session_id !== sessionId || !addressRefId) return <Navigate to="/" replace />;

  async function send(
    text = input,
    displayText = text,
    intent?: "weekly_ranking" | "kpop_demon_hunters",
    responseText?: string,
  ) {
    const trimmed = text.trim();
    if (!trimmed || sending || eventPending) return;
    let requestId = `chat-${createChatEntryId()}`;
    let replayAttempt = false;
    try {
      const pending = JSON.parse(sessionStorage.getItem(pendingRequestCacheKey) ?? "null") as {
        content?: string;
        intent?: string | null;
        requestId?: string;
      } | null;
      if (
        pending?.content === trimmed
        && (pending.intent ?? null) === (intent ?? null)
        && pending.requestId
      ) {
        requestId = pending.requestId;
        replayAttempt = true;
      }
    } catch { /* Replace an invalid browser-only retry record. */ }
    sessionStorage.setItem(
      pendingRequestCacheKey,
      JSON.stringify({ content: trimmed, intent: intent ?? null, requestId }),
    );
    setInput("");
    setInteractionError("");
    setEntries((current) => [...current, { id: createChatEntryId(), role: "user", text: displayText.trim() }]);
    setSending(true);
    setActivity(copy.checking);
    const pendingId = createChatEntryId();
    setEntries((current) => [...current, { id: pendingId, role: "assistant", text: "" }]);
    try {
      const turn = await api.streamMessage(sessionId, trimmed, {
        onText: (delta) => {
          if (responseText) return;
          setEntries((current) => {
            return current.map((entry) =>
              entry.id === pendingId ? { ...entry, text: entry.text + delta } : entry,
            );
          });
        },
        onStatus: (status) => setActivity(language === "English" ? status : copy.checking),
      }, intent, requestId);
      sessionStorage.removeItem(pendingRequestCacheKey);
      stateVersionRef.current = turn.state_version;
      setEntries((current) => {
        const complete = {
          id: turn.message_id,
          role: "assistant" as const,
          text: responseText ?? (turn.fallback_used && language !== "English" ? dynamicCopy.fallbackResult : turn.text),
          turn,
        };
        return current.map((entry) => (entry.id === pendingId ? complete : entry));
      });
      // A natural-language selection is committed server-side as part of the
      // streamed turn. Rehydrate that authoritative state before reopening the
      // order builder instead of relying on the assistant payload as a local
      // mutation signal.
      if (turn.dialogue_act === "SELECT" || replayAttempt) {
        await refreshConversation().catch(() => undefined);
      }
    } catch (cause) {
      let recovered = false;
      try {
        const conversation = await api.getConversation(sessionId);
        recovered = conversation.messages.some((message) => (
          message.role === "assistant"
          && message.safe_metadata.client_request_id === requestId
        ));
        if (recovered) {
          applyConversation(conversation);
          sessionStorage.removeItem(pendingRequestCacheKey);
        }
      } catch { /* Keep the stable request for an explicit retry. */ }
      if (recovered) return;
      if (cause instanceof Error && cause.message === "CHAT_REQUEST_ID_REUSED") {
        sessionStorage.removeItem(pendingRequestCacheKey);
      }
      const failure = {
        id: pendingId,
        role: "assistant" as const,
        text: language === "English" ? actionableError(cause, journeyCopy.failedCheck) : journeyCopy.failedCheck,
      };
      setEntries((current) =>
        current.map((entry) => (entry.id === pendingId ? failure : entry)),
      );
    } finally {
      setSending(false);
    }
  }

  async function handleSuggestedReply(reply: string, turn: AssistantTurn) {
    const candidates = turn.recommendation_result?.candidates ?? [];
    const normalized = reply.toLowerCase();
    setEventPending(true);
    setInteractionError("");
    try {
      if (normalized.includes("compare") && candidates.length >= 2 && turn.recommendation_snapshot_id) {
        await recordConversationEvent({
          event_type: "COMPARE_MENUS",
          snapshot_id: turn.recommendation_snapshot_id,
          menu_ids: candidates.map((candidate) => candidate.menu_id),
        });
      } else if (
        (normalized.includes("something else") || normalized.includes("different") || normalized.includes("another"))
        && turn.recommendation_snapshot_id
      ) {
        for (const candidate of candidates) {
          await recordConversationEvent({
            event_type: "REJECT_MENU",
            snapshot_id: turn.recommendation_snapshot_id,
            menu_id: candidate.menu_id,
          });
        }
      }
    } catch (cause) {
      setInteractionError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
      await refreshConversation().catch(() => undefined);
      setEventPending(false);
      return;
    }
    setEventPending(false);
    await send(reply);
  }

  async function updateConversationOptions(
    menuId: string,
    optionGroupId: string,
    optionItemIds: string[],
    riskAcknowledged: boolean,
  ) {
    // Same-merchant add-ons are selected inside the existing cart flow and do not
    // belong to the recommendation snapshot that opened this builder.
    if (selectedMenu?.menu_id !== menuId) return;
    setEventPending(true);
    setInteractionError("");
    try {
      await recordConversationEvent({
        event_type: "UPDATE_OPTIONS",
        menu_id: menuId,
        option_group_id: optionGroupId,
        option_item_ids: optionItemIds,
        risk_acknowledged: riskAcknowledged,
      });
    } catch (cause) {
      setInteractionError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
      await refreshConversation().catch(() => undefined);
      throw cause;
    } finally {
      setEventPending(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send();
  }

  function editProfile() {
    sessionStorage.setItem(`yobi-chat-scroll-${sessionId}`, String(window.scrollY));
    navigate(`/profile?edit=1&returnTo=${encodeURIComponent(`/chat/${sessionId}`)}`);
  }

  return (
    <main className="chat-shell">
      <section className="chat-column">
        <header className="chat-header">
          <div className="brand-mark compact">YO<span>BI</span></div>
          <div><strong>{copy.buddy}</strong><span><i /> {journeyCopy.catalogReady}</span></div>
          <button className="cart-button" aria-label={language === "English" ? `${journeyCopy.openCart}, ${cartQuantity} items` : `${journeyCopy.openCart}, ${journeyCopy.quantity} ${cartQuantity}`} onClick={openCart} disabled={!selectedMenu} title={selectedMenu ? journeyCopy.openCart : journeyCopy.chooseFirst}><ShoppingBag size={19} />{cartQuantity > 0 && <span className="cart-badge">{cartQuantity}</span>}</button>
        </header>
        <div className="conversation" aria-live="polite">
          {entries.map((entry) => (
            <article className={`message ${entry.role}`} key={entry.id}>
              <div className="message-label">{entry.role === "assistant" ? "YOBI" : copy.you}</div>
              {entry.text && <div className="message-bubble">{entry.text}</div>}
              {entry.id === "welcome" && entries.length === 1 && !sending && (
                <button
                  type="button"
                  className="welcome-prompt-suggestion"
                  disabled={hydrating || eventPending}
                  onClick={() => void send("I saw people eating some red rice cake dish on the street. What is that? Can I order it?", journeyCopy.demoPrompt)}
                >
                  <Sparkles size={13} /> {copy.demoQuestion}
                </button>
              )}
              {entry.turn?.fallback_used && <span className="fallback-chip">{journeyCopy.fallbackMode}</span>}
              {entry.turn?.cards.map((card, index) => (
                <RichCard
                  card={card}
                  key={`${entry.id}-${index}`}
                  disabled={sending || eventPending}
                  onChooseMenu={(menu) => void chooseMenu(menu, entry.turn?.recommendation_snapshot_id)}
                  onQuickReply={(reply, localizedReply) => void send(reply, localizedReply)}
                />
              ))}
              {entry.turn?.suggested_replies.length && !(entry.turn.fallback_used && language !== "English") ? (
                <div className="quick-replies">
                  {entry.turn.suggested_replies.map((reply) => <button disabled={sending || eventPending} key={reply} onClick={() => void handleSuggestedReply(reply, entry.turn as AssistantTurn)}>{reply}</button>)}
                </div>
              ) : null}
            </article>
          ))}
          {sending && <div className="typing"><span /><span /><span /><em>{activity}</em></div>}
          {interactionError && <p className="form-error" role="alert">{interactionError}</p>}
          {selectedMenu && <OrderFlowPanel sessionId={sessionId} menu={selectedMenu} addressRefId={addressRefId} dietaryRules={activeRules} onClose={() => setSelectedMenu(null)} onOptionChange={updateConversationOptions} />}
        </div>

        <div className="chat-dock">
          <ChatRoomMenu
            disabled={sending || eventPending || hydrating}
            onPreset={(intent, prompt, response) => void send(prompt, prompt, intent, response)}
            onEditProfile={editProfile}
          />
          <form className="composer" onSubmit={submit}>
          <label htmlFor="message">{copy.ask}</label>
          <div>
            <textarea id="message" value={input} onChange={(event) => setInput(event.target.value)} placeholder={copy.placeholder} rows={1} disabled={hydrating || eventPending} />
            <button className="send-button" aria-label={journeyCopy.sendMessage} disabled={!input.trim() || sending || hydrating || eventPending}><ArrowUp size={20} /></button>
          </div>
          </form>
        </div>
      </section>
    </main>
  );
}
