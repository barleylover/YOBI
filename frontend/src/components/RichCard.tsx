import { useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Clock3, Info, Leaf, Soup, Store, TriangleAlert } from "lucide-react";
import type {
  CardPayload,
  CategoryRecommendation,
  Evidence,
  MenuSummary,
  MerchantComparison,
} from "../types";
import { EvidenceBadge } from "./EvidenceBadge";

interface Props {
  card: CardPayload;
  onChooseMenu: (menu: MenuSummary) => void;
  onQuickReply: (text: string) => void;
}

export function RichCard({ card, onChooseMenu, onQuickReply }: Props) {
  const carouselRef = useRef<HTMLDivElement>(null);
  const [activeMenuIndex, setActiveMenuIndex] = useState(0);

  function showMenu(index: number) {
    const track = carouselRef.current;
    if (!track) return;
    const nextIndex = Math.max(0, Math.min(index, track.children.length - 1));
    const firstCard = track.children[0] as HTMLElement | undefined;
    const nextCard = track.children[nextIndex] as HTMLElement | undefined;
    if (!firstCard || !nextCard) return;
    track.scrollTo({ left: nextCard.offsetLeft - firstCard.offsetLeft, behavior: "smooth" });
    setActiveMenuIndex(nextIndex);
  }

  if (card.type === "category_recommendations") {
    const categories = (card.data.categories ?? []) as CategoryRecommendation[];
    return (
      <section className="category-card" aria-label={card.title}>
        <div className="card-heading">
          <p className="eyebrow">Food directions</p>
          <h3>{card.title}</h3>
          {card.subtitle && <p>{card.subtitle}</p>}
        </div>
        <div className="category-grid">
          {categories.map((category) => (
            <article key={category.category}>
              <Soup size={19} aria-hidden="true" />
              <h4>{category.category}</h4>
              {category.description && <p>{category.description}</p>}
              <ul>{category.match_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              {category.risk_hints.map((risk) => <p className="risk-copy" key={risk}><TriangleAlert size={14} /> {risk}</p>)}
              <details className="source-drawer">
                <summary>Catalog sources</summary>
                <code>{category.source_ids.join(" · ")}</code>
              </details>
              <button className="secondary-button full" onClick={() => onQuickReply(`Show me ${category.category}`)}>
                Explore this direction <ArrowRight size={15} />
              </button>
            </article>
          ))}
        </div>
      </section>
    );
  }

  if (card.type === "menu_recommendations") {
    const menus = (card.data.menus ?? []) as MenuSummary[];
    return (
      <section className="rich-card-stack" aria-label={card.title}>
        <div className="card-heading carousel-heading">
          <div><p className="eyebrow">Menu match</p><h3>{card.title}</h3>{card.subtitle && <p>{card.subtitle}</p>}</div>
          {menus.length > 1 && <div className="carousel-controls" aria-label="Menu carousel controls">
            <button aria-label="Previous menu" onClick={() => showMenu(activeMenuIndex - 1)} disabled={activeMenuIndex === 0}><ArrowLeft size={17} /></button>
            <span>{activeMenuIndex + 1} / {menus.length}</span>
            <button aria-label="Next menu" onClick={() => showMenu(activeMenuIndex + 1)} disabled={activeMenuIndex === menus.length - 1}><ArrowRight size={17} /></button>
          </div>}
        </div>
        <div className="menu-carousel" ref={carouselRef} onScroll={(event) => {
          const track = event.currentTarget;
          const firstCard = track.children[0] as HTMLElement | undefined;
          const secondCard = track.children[1] as HTMLElement | undefined;
          const interval = secondCard && firstCard ? secondCard.offsetLeft - firstCard.offsetLeft : track.clientWidth || 1;
          setActiveMenuIndex(Math.max(0, Math.min(menus.length - 1, Math.round(track.scrollLeft / interval))));
        }}>
          {menus.map((menu) => (
          <article className="menu-card" key={menu.menu_id} data-testid={`menu-${menu.menu_id}`} aria-label={`${menu.name_en} recommendation`}>
            <div className="food-illustration" aria-hidden="true">
              <span>{menu.category.toLowerCase().includes("rose") ? "ROSE" : "K-FOOD"}</span>
            </div>
            <div className="menu-card-body">
              <div className="card-row">
                <div>
                  <h4>{menu.name_en}</h4>
                  <p className="ko-name">{menu.name_ko}</p>
                </div>
                <strong>₩{menu.price.toLocaleString()}</strong>
              </div>
              <p>{menu.description}</p>
              <div className="fact-row">
                <span><Clock3 size={15} /> {menu.eta_min}-{menu.eta_max} min</span>
                <span>Spice {menu.spice_level}/5</span>
              </div>
              <EvidenceBadge status={menu.evidence_status} />
              {menu.risk_hints.map((risk) => <p className="risk-copy" key={risk}>{risk}</p>)}
              <details className="source-drawer">
                <summary>Why this match</summary>
                <ul>{menu.match_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                <code>{[menu.menu_id, menu.merchant_id, ...menu.evidence_ids].join(" · ")}</code>
              </details>
              <p className="demo-label">Synthetic demo menu · checked 2026-08-06</p>
              <button className="primary-button full" onClick={() => onChooseMenu(menu)}>
                Choose this menu
              </button>
            </div>
          </article>
          ))}
        </div>
        {menus.length > 1 && <div className="carousel-dots" aria-hidden="true">{menus.map((menu, index) => <span className={index === activeMenuIndex ? "active" : ""} key={menu.menu_id} />)}</div>}
      </section>
    );
  }

  if (card.type === "menu_explanation") {
    const menu = card.data.menu as MenuSummary;
    const explanation = card.data.explanation as {
      cultural_analogy: string;
      portion: string;
      unknown_fields: string[];
      evidence_ids: string[];
    };
    return (
      <section className="explanation-card" aria-label={card.title}>
        <div className="card-heading"><p className="eyebrow">Dish guide</p><h3>{card.title}</h3><p>{card.subtitle}</p></div>
        <article><h4>{menu.name_en}</h4><p>{explanation.cultural_analogy}</p><p><strong>Portion:</strong> {explanation.portion} · <strong>Spice:</strong> {menu.spice_level}/5</p>{explanation.unknown_fields.map((item) => <p className="risk-copy" key={item}>{item}</p>)}<details className="source-drawer"><summary>Evidence sources</summary><code>{explanation.evidence_ids.join(" · ")}</code></details></article>
      </section>
    );
  }

  if (card.type === "dietary_evidence") {
    const evidence = (card.data.evidence ?? []) as Evidence[];
    return (
      <section className="evidence-card" aria-label={card.title}>
        <div className="card-heading">
          <p className="eyebrow risk">Dietary evidence</p>
          <h3>{card.title}</h3>
          <p>{card.subtitle}</p>
        </div>
        {evidence.map((item) => (
          <article className="evidence-row" key={item.evidence_id}>
            <EvidenceBadge status={item.status} />
            <strong>{item.claim_type.replaceAll("_", " ")}</strong>
            <p>{item.excerpt}</p>
            <small>{item.source_type.replaceAll("_", " ")} · checked {item.updated_at}</small>
            <p className="action-copy"><Info size={15} /> {item.suggested_action}</p>
          </article>
        ))}
      </section>
    );
  }

  if (card.type === "merchant_comparison") {
    const merchants = (card.data.merchants ?? []) as MerchantComparison[];
    return (
      <section className="comparison-card" aria-label={card.title}>
        <div className="card-heading">
          <p className="eyebrow">Side-by-side</p>
          <h3>{card.title}</h3>
          <p>{card.subtitle}</p>
        </div>
        <div className="comparison-grid">
          {merchants.map((merchant, index) => (
            <article key={merchant.merchant_id} className={index === 0 ? "recommended" : ""}>
              {index === 0 && <span className="recommend-ribbon">Best fit</span>}
              <Store size={18} aria-hidden="true" />
              <h4>{merchant.merchant_name}</h4>
              <strong>₩{merchant.price.toLocaleString()}</strong>
              <dl>
                <div><dt>Delivery</dt><dd>{merchant.eta} · ₩{merchant.delivery_fee.toLocaleString()}</dd></div>
                <div><dt>Flavour</dt><dd>{merchant.flavor}</dd></div>
                <div><dt>Portion</dt><dd>{merchant.portion}</dd></div>
              </dl>
              <EvidenceBadge status={merchant.dietary_status} />
              <p>{merchant.dietary_note}</p>
              <details className="source-drawer"><summary>Evidence sources</summary><code>{merchant.evidence_ids.join(" · ") || "Not verified"}</code></details>
              <button
                className={index === 0 ? "primary-button full" : "secondary-button full"}
                onClick={() => onQuickReply(index === 0 ? "Choose Seoul Rose Tteokbokki" : `Choose ${merchant.merchant_name}`)}
              >
                Choose {index === 0 ? "recommended" : "this place"}
              </button>
            </article>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="simple-card">
      <Leaf size={18} aria-hidden="true" />
      <h3>{card.title}</h3>
      {card.subtitle && <p>{card.subtitle}</p>}
    </section>
  );
}
