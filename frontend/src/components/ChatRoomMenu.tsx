import { useState } from "react";
import { ChevronDown, Clapperboard, Settings2, Trophy } from "lucide-react";
import { useI18n } from "../lib/i18n";

interface Props {
  disabled: boolean;
  onPreset: (
    intent: "weekly_ranking" | "kpop_demon_hunters",
    prompt: string,
    response: string,
  ) => void;
  onEditProfile: () => void;
}

export function ChatRoomMenu({ disabled, onPreset, onEditProfile }: Props) {
  const { chatMenuCopy } = useI18n();
  const [open, setOpen] = useState(false);

  function choose(action: () => void) {
    setOpen(false);
    action();
  }

  return (
    <section className={`chat-room-menu ${open ? "open" : ""}`}>
      {open && (
        <div className="chat-room-menu-grid" id="chat-room-menu-items">
          <button disabled={disabled} onClick={() => choose(() => onPreset("weekly_ranking", chatMenuCopy.weeklyPrompt, chatMenuCopy.weeklyResponse))}>
            <span className="chat-menu-icon coral"><Trophy size={22} /></span>
            <strong>{chatMenuCopy.weekly}</strong>
          </button>
          <button disabled={disabled} onClick={() => choose(() => onPreset("kpop_demon_hunters", chatMenuCopy.kpopPrompt, chatMenuCopy.kpopResponse))}>
            <span className="chat-menu-icon violet"><Clapperboard size={22} /></span>
            <strong>{chatMenuCopy.kpop}</strong>
          </button>
          <button onClick={() => choose(onEditProfile)}>
            <span className="chat-menu-icon amber"><Settings2 size={22} /></span>
            <strong>{chatMenuCopy.editProfile}</strong>
          </button>
        </div>
      )}
      <button
        type="button"
        className="chat-room-menu-toggle"
        aria-expanded={open}
        aria-controls="chat-room-menu-items"
        aria-label={open ? chatMenuCopy.close : chatMenuCopy.open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{chatMenuCopy.open}</span><ChevronDown size={20} />
      </button>
    </section>
  );
}
