import { FormEvent, useEffect, useMemo, useState } from "react";
import { ArrowUp, ShoppingBag, Sparkles } from "lucide-react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { ChatRoomMenu } from "../components/ChatRoomMenu";
import { OrderFlowPanel } from "../components/OrderFlowPanel";
import { RichCard } from "../components/RichCard";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSessionStore } from "../stores/session";
import type { AssistantTurn, MenuSummary } from "../types";

interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  turn?: AssistantTurn;
}

function createChatEntryId() {
  return globalThis.crypto?.randomUUID?.() ?? `entry_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function ChatPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const profile = useSessionStore((state) => state.profile);
  const session = useSessionStore((state) => state.session);
  const addressRefId = useSessionStore((state) => state.addressRefId);
  const cartQuantity = useSessionStore((state) => state.cartQuantity);
  const { copy, dynamicCopy, journeyCopy, language } = useI18n();
  const chatCacheKey = `yobi-chat-entries-${sessionId}`;
  const inputCacheKey = `yobi-chat-input-${sessionId}`;
  const selectedMenuCacheKey = `yobi-selected-menu-${sessionId}`;
  const [input, setInput] = useState(() => sessionStorage.getItem(inputCacheKey) ?? "");
  const [sending, setSending] = useState(false);
  const [activity, setActivity] = useState(copy.checking);
  const [selectedMenu, setSelectedMenu] = useState<MenuSummary | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(selectedMenuCacheKey) ?? "null") as MenuSummary | null;
    } catch { return null; }
  });
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

  function chooseMenu(menu: MenuSummary) {
    setSelectedMenu(menu);
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
    if (sessionStorage.getItem(chatCacheKey)) return;
    let active = true;
    api.getMessages(sessionId)
      .then((messages) => {
        if (!active || messages.length === 0) return;
        setEntries(
          messages.map((message) => ({
            id: message.message_id,
            role: message.role,
            text: message.content,
          })),
        );
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [chatCacheKey, session?.session_id, sessionId]);
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
    if (!trimmed || sending) return;
    setInput("");
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
      }, intent);
      setEntries((current) => {
        const complete = {
          id: turn.message_id,
          role: "assistant" as const,
          text: responseText ?? (turn.fallback_used && language !== "English" ? dynamicCopy.fallbackResult : turn.text),
          turn,
        };
        return current.map((entry) => (entry.id === pendingId ? complete : entry));
      });
    } catch {
      const failure = { id: pendingId, role: "assistant" as const, text: journeyCopy.failedCheck };
      setEntries((current) =>
        current.map((entry) => (entry.id === pendingId ? failure : entry)),
      );
    } finally {
      setSending(false);
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
                  onClick={() => void send("I saw people eating some red rice cake dish on the street. What is that? Can I order it?", journeyCopy.demoPrompt)}
                >
                  <Sparkles size={13} /> {copy.demoQuestion}
                </button>
              )}
              {entry.turn?.fallback_used && <span className="fallback-chip">{journeyCopy.fallbackMode}</span>}
              {entry.turn?.cards.map((card, index) => (
                <RichCard card={card} key={`${entry.id}-${index}`} onChooseMenu={chooseMenu} onQuickReply={(reply, localizedReply) => void send(reply, localizedReply)} />
              ))}
              {entry.turn?.suggested_replies.length && !(entry.turn.fallback_used && language !== "English") ? (
                <div className="quick-replies">
                  {entry.turn.suggested_replies.map((reply) => <button key={reply} onClick={() => void send(reply)}>{reply}</button>)}
                </div>
              ) : null}
            </article>
          ))}
          {sending && <div className="typing"><span /><span /><span /><em>{activity}</em></div>}
          {selectedMenu && <OrderFlowPanel sessionId={sessionId} menu={selectedMenu} addressRefId={addressRefId} dietaryRules={activeRules} onClose={() => setSelectedMenu(null)} />}
        </div>

        <div className="chat-dock">
          <ChatRoomMenu
            disabled={sending}
            onPreset={(intent, prompt, response) => void send(prompt, prompt, intent, response)}
            onEditProfile={editProfile}
          />
          <form className="composer" onSubmit={submit}>
          <label htmlFor="message">{copy.ask}</label>
          <div>
            <textarea id="message" value={input} onChange={(event) => setInput(event.target.value)} placeholder={copy.placeholder} rows={1} />
            <button className="send-button" aria-label={journeyCopy.sendMessage} disabled={!input.trim() || sending}><ArrowUp size={20} /></button>
          </div>
          </form>
        </div>
      </section>
    </main>
  );
}
