import { useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Clock3, MapPin } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { menuName } from "../lib/locale";
import type { CardPayload, MenuSummary } from "../types";

interface Props {
  card: Extract<CardPayload, { type: "preset_collection" }>;
  onChooseMenu: (menu: MenuSummary) => void;
  disabled?: boolean;
}

export function PresetCollectionCard({ card, onChooseMenu, disabled = false }: Props) {
  const { chatMenuCopy, copy, journeyCopy, language, locale } = useI18n();
  const entries = card.data.entries ?? [];
  const kind = card.data.kind;
  const trackRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  function show(index: number) {
    const track = trackRef.current;
    if (!track) return;
    const nextIndex = Math.max(0, Math.min(index, entries.length - 1));
    const first = track.children[0] as HTMLElement | undefined;
    const next = track.children[nextIndex] as HTMLElement | undefined;
    if (!first || !next) return;
    track.scrollTo({ left: next.offsetLeft - first.offsetLeft, behavior: "smooth" });
    setActiveIndex(nextIndex);
  }

  const title = kind === "weekly_ranking" ? chatMenuCopy.weekly : chatMenuCopy.kpop;
  return (
    <section className={`preset-collection ${kind}`} aria-label={title} data-testid={`preset-${kind}`}>
      <header className="preset-heading">
        <div><span>YOBI PICKS</span><h3>{title}</h3><p>{chatMenuCopy.swipe}</p></div>
        <div className="carousel-controls">
          <button aria-label={journeyCopy.previousMenu} onClick={() => show(activeIndex - 1)} disabled={activeIndex === 0}><ArrowLeft size={17} /></button>
          <span>{activeIndex + 1} / {entries.length}</span>
          <button aria-label={journeyCopy.nextMenu} onClick={() => show(activeIndex + 1)} disabled={activeIndex === entries.length - 1}><ArrowRight size={17} /></button>
        </div>
      </header>
      <div className="preset-carousel" ref={trackRef} onScroll={(event) => {
        const track = event.currentTarget;
        const first = track.children[0] as HTMLElement | undefined;
        const second = track.children[1] as HTMLElement | undefined;
        const interval = second && first ? second.offsetLeft - first.offsetLeft : track.clientWidth || 1;
        setActiveIndex(Math.max(0, Math.min(entries.length - 1, Math.round(track.scrollLeft / interval))));
      }}>
        {entries.map((entry) => (
          <article className="preset-menu-card" key={entry.menu.menu_id} data-testid={`preset-menu-${entry.menu.menu_id}`}>
            <div className="preset-visual">
              <span className="preset-number">{kind === "weekly_ranking" ? `${entry.rank}` : String(entry.rank).padStart(2, "0")}</span>
              <div><small>{kind === "weekly_ranking" ? chatMenuCopy.rank : "K-FOOD"}</small><strong>{kind === "kpop_demon_hunters" && language === "한국어" ? entry.menu.name_ko : entry.label}</strong></div>
            </div>
            <div className="preset-body">
              {language === "English" && <p className="preset-description">{entry.description}</p>}
              <h4>{menuName(entry.menu, language)}</h4>
              <p className="preset-merchant"><MapPin size={14} /> {language === "한국어" ? entry.label : entry.menu.merchant_name}</p>
              <div className="preset-facts">
                <strong>₩{entry.menu.price.toLocaleString(locale)}</strong>
                <span><Clock3 size={14} /> {new Intl.NumberFormat(locale, { style: "unit", unit: "minute", unitDisplay: "short" }).format(entry.menu.eta_min)}–{new Intl.NumberFormat(locale, { style: "unit", unit: "minute", unitDisplay: "short" }).format(entry.menu.eta_max)}</span>
                <span>{copy.spice} {entry.menu.spice_level}/5</span>
              </div>
              <button className="primary-button full" onClick={() => onChooseMenu(entry.menu)} disabled={disabled}>{copy.chooseMenu}</button>
            </div>
          </article>
        ))}
      </div>
      <div className="carousel-dots" aria-hidden="true">{entries.map((entry, index) => <span className={index === activeIndex ? "active" : ""} key={entry.menu.menu_id} />)}</div>
    </section>
  );
}
