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
import { useI18n } from "../lib/i18n";
import { menuName } from "../lib/locale";
import { PresetCollectionCard } from "./PresetCollectionCard";

interface Props {
  card: CardPayload;
  onChooseMenu: (menu: MenuSummary) => void;
  onQuickReply: (text: string, localizedText?: string) => void;
}

export function RichCard({ card, onChooseMenu, onQuickReply }: Props) {
  const { copy, dynamicCopy, journeyCopy, language, locale } = useI18n();
  const localizedCatalog = language !== "English";
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

  if (card.type === "preset_collection") {
    return <PresetCollectionCard card={card} onChooseMenu={onChooseMenu} />;
  }

  if (card.type === "category_recommendations") {
    const categories = (card.data.categories ?? []) as CategoryRecommendation[];
    return (
      <section className="category-card" aria-label={card.title}>
        <div className="card-heading">
          <p className="eyebrow">{copy.whyMatch}</p>
          <h3>{localizedCatalog ? dynamicCopy.menuMatches : card.title}</h3>
          {card.subtitle && !localizedCatalog && <p>{card.subtitle}</p>}
        </div>
        <div className="category-grid">
          {categories.map((category) => (
            <article key={category.category}>
              <Soup size={19} aria-hidden="true" />
              <h4>{category.category}</h4>
              {category.description && <p>{localizedCatalog ? dynamicCopy.catalogDescription : category.description}</p>}
              <ul>{(localizedCatalog ? [dynamicCopy.matchReason] : category.match_reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul>
              {(localizedCatalog && category.risk_hints.length ? [dynamicCopy.riskUnknown] : category.risk_hints).map((risk) => <p className="risk-copy" key={risk}><TriangleAlert size={14} /> {risk}</p>)}
              <details className="source-drawer">
                <summary>{journeyCopy.catalogSources}</summary>
                <code>{category.source_ids.join(" · ")}</code>
              </details>
              <button className="secondary-button full" onClick={() => onQuickReply(`Show me ${category.category}`, `${copy.chooseMenu}: ${category.category}`)}>
                {copy.chooseMenu} <ArrowRight size={15} />
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
          <div><p className="eyebrow">{copy.whyMatch}</p><h3>{localizedCatalog ? dynamicCopy.menuMatches : card.title}</h3>{card.subtitle && !localizedCatalog && <p>{card.subtitle}</p>}</div>
          {menus.length > 1 && <div className="carousel-controls" aria-label={dynamicCopy.menuMatches}>
            <button aria-label={journeyCopy.previousMenu} onClick={() => showMenu(activeMenuIndex - 1)} disabled={activeMenuIndex === 0}><ArrowLeft size={17} /></button>
            <span>{activeMenuIndex + 1} / {menus.length}</span>
            <button aria-label={journeyCopy.nextMenu} onClick={() => showMenu(activeMenuIndex + 1)} disabled={activeMenuIndex === menus.length - 1}><ArrowRight size={17} /></button>
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
                  <h4>{menuName(menu, language)}</h4>
                  <p className="ko-name">{menu.name_ko}</p>
                </div>
                <strong>₩{menu.price.toLocaleString()}</strong>
              </div>
              <p>{localizedCatalog ? dynamicCopy.catalogDescription : menu.description}</p>
              <div className="fact-row">
                <span><Clock3 size={15} /> {new Intl.NumberFormat(locale, { style: "unit", unit: "minute", unitDisplay: "short" }).format(menu.eta_min)}–{new Intl.NumberFormat(locale, { style: "unit", unit: "minute", unitDisplay: "short" }).format(menu.eta_max)}</span>
                <span>{copy.spice} {menu.spice_level} / 3</span>
              </div>
              <EvidenceBadge status={menu.evidence_status} />
              {(localizedCatalog && menu.risk_hints.length ? [dynamicCopy.riskUnknown] : menu.risk_hints).map((risk) => <p className="risk-copy" key={risk}>{risk}</p>)}
              <details className="source-drawer">
                <summary>{copy.whyMatch}</summary>
                <ul>{(localizedCatalog ? [dynamicCopy.matchReason] : menu.match_reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul>
                <code>{[menu.menu_id, menu.merchant_id, ...menu.evidence_ids].join(" · ")}</code>
              </details>
              <p className="demo-label">{journeyCopy.syntheticMenu} · 2026-08-06</p>
              <button className="primary-button full" onClick={() => onChooseMenu(menu)}>
                {copy.chooseMenu}
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
        <div className="card-heading"><p className="eyebrow">{copy.whyMatch}</p><h3>{localizedCatalog ? dynamicCopy.menuMatches : card.title}</h3>{!localizedCatalog && <p>{card.subtitle}</p>}</div>
        <article><h4>{menuName(menu, language)}</h4><p>{localizedCatalog ? dynamicCopy.catalogDescription : explanation.cultural_analogy}</p><p><strong>{journeyCopy.portion}:</strong> {localizedCatalog ? dynamicCopy.catalogDescription : explanation.portion} · <strong>{copy.spice}:</strong> {menu.spice_level} / 3</p>{(localizedCatalog && explanation.unknown_fields.length ? [dynamicCopy.riskUnknown] : explanation.unknown_fields).map((item) => <p className="risk-copy" key={item}>{item}</p>)}<details className="source-drawer"><summary>{copy.evidence}</summary><code>{explanation.evidence_ids.join(" · ")}</code></details></article>
      </section>
    );
  }

  if (card.type === "dietary_evidence") {
    const evidence = (card.data.evidence ?? []) as Evidence[];
    return (
      <section className="evidence-card" aria-label={card.title}>
        <div className="card-heading">
          <p className="eyebrow risk">{copy.evidence}</p>
          <h3>{localizedCatalog ? copy.evidence : card.title}</h3>
          {!localizedCatalog && <p>{card.subtitle}</p>}
        </div>
        {evidence.map((item) => (
          <article className="evidence-row" key={item.evidence_id}>
            <EvidenceBadge status={item.status} />
            <strong>{localizedCatalog ? copy.evidence : item.claim_type.replaceAll("_", " ")}</strong>
            <p>{localizedCatalog ? dynamicCopy.evidenceDescription : item.excerpt}</p>
            <small>{localizedCatalog ? copy.evidence : item.source_type.replaceAll("_", " ")} · {item.updated_at}</small>
            <p className="action-copy"><Info size={15} /> {localizedCatalog ? dynamicCopy.riskUnknown : item.suggested_action}</p>
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
          <p className="eyebrow">{journeyCopy.sideBySide}</p>
          <h3>{localizedCatalog ? dynamicCopy.menuMatches : card.title}</h3>
          {!localizedCatalog && <p>{card.subtitle}</p>}
        </div>
        <div className="comparison-grid">
          {merchants.map((merchant, index) => (
            <article key={merchant.merchant_id} className={index === 0 ? "recommended" : ""}>
              {index === 0 && <span className="recommend-ribbon">{journeyCopy.bestFit}</span>}
              <Store size={18} aria-hidden="true" />
              <h4>{merchant.merchant_name}</h4>
              <strong>₩{merchant.price.toLocaleString()}</strong>
              <dl>
                <div><dt>{copy.delivery}</dt><dd>{merchant.eta} · ₩{merchant.delivery_fee.toLocaleString()}</dd></div>
                <div><dt>{journeyCopy.flavour}</dt><dd>{localizedCatalog ? dynamicCopy.catalogDescription : merchant.flavor}</dd></div>
                <div><dt>{journeyCopy.portion}</dt><dd>{localizedCatalog ? dynamicCopy.catalogDescription : merchant.portion}</dd></div>
              </dl>
              <EvidenceBadge status={merchant.dietary_status} />
              <p>{localizedCatalog ? dynamicCopy.evidenceDescription : merchant.dietary_note}</p>
              <details className="source-drawer"><summary>{copy.evidence}</summary><code>{merchant.evidence_ids.join(" · ") || journeyCopy.notVerified}</code></details>
              <button
                className={index === 0 ? "primary-button full" : "secondary-button full"}
                onClick={() => onQuickReply(index === 0 ? "Choose Seoul Rose Tteokbokki" : `Choose ${merchant.merchant_name}`, `${copy.chooseMenu}: ${merchant.merchant_name}`)}
              >
                {copy.chooseMenu}
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
