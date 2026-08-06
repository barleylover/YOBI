import { FormEvent, useMemo, useState } from "react";
import { ArrowUp, ChevronDown, ShieldCheck, ShoppingBag, Sparkles } from "lucide-react";
import { Navigate, useParams } from "react-router-dom";
import { OrderFlowPanel } from "../components/OrderFlowPanel";
import { RichCard } from "../components/RichCard";
import { api } from "../lib/api";
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
  const profile = useSessionStore((state) => state.profile);
  const session = useSessionStore((state) => state.session);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [selectedMenu, setSelectedMenu] = useState<MenuSummary | null>(null);
  const [entries, setEntries] = useState<ChatEntry[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "Hi, I’m YOBI. Tell me what you remember about the food—or how you want tonight’s meal to feel. I’ll translate that into grounded demo choices.",
    },
  ]);

  const activeRules = useMemo(() => profile?.dietary_rules ?? [], [profile]);
  if (!profile || !session || session.session_id !== sessionId) return <Navigate to="/" replace />;

  async function send(text = input) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setEntries((current) => [...current, { id: createChatEntryId(), role: "user", text: trimmed }]);
    setSending(true);
    try {
      const turn = await api.sendMessage(sessionId, trimmed);
      setEntries((current) => [...current, { id: turn.message_id, role: "assistant", text: turn.text, turn }]);
    } catch {
      setEntries((current) => [...current, { id: createChatEntryId(), role: "assistant", text: "I couldn’t complete that check. Your selections are unchanged—please try again." }]);
    } finally {
      setSending(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send();
  }

  return (
    <main className="chat-shell">
      <section className="chat-column">
        <header className="chat-header">
          <div className="brand-mark compact">YO<span>BI</span></div>
          <div><strong>Your Korean food buddy</strong><span><i /> Demo catalog ready</span></div>
          <button aria-label="Open cart"><ShoppingBag size={19} /></button>
        </header>
        <div className="journey-bar"><span className="active">Discover</span><span>Choose</span><span>Deliver</span><span>Pay</span></div>

        <div className="conversation" aria-live="polite">
          <section className="session-brief">
            <Sparkles size={18} />
            <div><strong>Ready for Alex’s first K-food order</strong><p>English · spice {profile.spice_tolerance}/5 · shellfish allergy</p></div>
          </section>
          {entries.map((entry) => (
            <article className={`message ${entry.role}`} key={entry.id}>
              <div className="message-label">{entry.role === "assistant" ? "YOBI" : "You"}</div>
              <div className="message-bubble">{entry.text}</div>
              {entry.turn?.fallback_used && <span className="fallback-chip">Demo continuity mode</span>}
              {entry.turn?.cards.map((card, index) => (
                <RichCard card={card} key={`${entry.id}-${index}`} onChooseMenu={setSelectedMenu} onQuickReply={(reply) => void send(reply)} />
              ))}
              {entry.turn?.suggested_replies.length ? (
                <div className="quick-replies">
                  {entry.turn.suggested_replies.map((reply) => <button key={reply} onClick={() => void send(reply)}>{reply}</button>)}
                </div>
              ) : null}
            </article>
          ))}
          {sending && <div className="typing"><span /><span /><span /><em>Checking menu details…</em></div>}
          {selectedMenu && <OrderFlowPanel sessionId={sessionId} menu={selectedMenu} onClose={() => setSelectedMenu(null)} />}
        </div>

        <form className="composer" onSubmit={submit}>
          <label htmlFor="message">Ask YOBI</label>
          <div>
            <textarea id="message" value={input} onChange={(event) => setInput(event.target.value)} placeholder="I saw a red rice cake dish on the street…" rows={1} />
            <button className="send-button" aria-label="Send message" disabled={!input.trim() || sending}><ArrowUp size={20} /></button>
          </div>
          <button type="button" className="prompt-suggestion" onClick={() => void send("I saw people eating some red rice cake dish on the street. What is that? Can I order it?")}>Try the demo question <ChevronDown size={15} /></button>
        </form>
      </section>

      <aside className="context-rail">
        <div className="rail-card profile-card"><p className="eyebrow">Your context</p><h2>Alex in Seoul</h2><p>English · United States · 25-34</p><div className="profile-tags"><span>Spice {profile.spice_tolerance}/5</span>{activeRules.map((rule) => <span key={rule}>{rule.replaceAll("_", " ")}</span>)}</div></div>
        <div className="rail-card"><p className="eyebrow">Trust layer</p><h3><ShieldCheck size={19} /> Evidence before reassurance</h3><p>Restaurant facts, risk signals, and unknowns stay visibly separate.</p><ul><li>Prices come from the demo catalog</li><li>Every dietary claim links to evidence</li><li>No real payment or order</li></ul></div>
        <div className="rail-card demo-data"><strong>Synthetic demo data</strong><p>30 restaurants · 150 menus · 600 review snippets</p></div>
      </aside>
    </main>
  );
}
