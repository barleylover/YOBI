import { useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Clock3, Info, Leaf, Soup, Store, TriangleAlert } from "lucide-react";
import type {
  KnowledgeClaimStatus,
  KnowledgeSourceScope,
  CardPayload,
  MenuSummary,
  StructuredMenuKnowledge,
} from "../types";
import { EvidenceBadge } from "./EvidenceBadge";
import { useI18n } from "../lib/i18n";
import { menuName } from "../lib/locale";
import { PresetCollectionCard } from "./PresetCollectionCard";

interface Props {
  card: CardPayload;
  onChooseMenu: (menu: MenuSummary) => void;
  onQuickReply: (text: string, localizedText?: string) => void;
  disabled?: boolean;
}

const knowledgeCopy = {
  English: {
    wiki: "Retrieved menu Wiki",
    originalWiki: "Retrieved Wiki passages",
    ingredients: "Typical ingredients and menu changes",
    allergens: "Allergy and dietary signals",
    preparation: "Typical preparation",
    synthetic: "Synthetic menu Wiki",
    boundary: "General synthetic Wiki and menu records are not an allergy-safe guarantee. Restaurant recipe changes and kitchen cross-contact are not verified.",
    menuPresent: "Listed for this menu",
    wikiPresent: "Defined by the general Wiki",
    presumed: "Commonly present",
    possible: "Possible",
    unknown: "Not verified",
    conflicting: "Conflicting records",
    menuAbsent: "Menu record says absent; kitchen cross-contact is not verified",
    wikiAbsent: "General Wiki says absent; this restaurant recipe is not verified",
  },
  "한국어": {
    wiki: "검색된 메뉴 Wiki",
    originalWiki: "Wiki 원문 근거(영문)",
    ingredients: "대표 재료·변경 정보",
    allergens: "알레르기·식단 신호",
    preparation: "대표 조리법",
    synthetic: "합성 메뉴 Wiki",
    boundary: "일반 합성 Wiki와 메뉴 기록은 알레르기 안전을 보장하지 않습니다. 매장별 레시피 변경과 주방 교차접촉 여부는 확인되지 않았습니다.",
    menuPresent: "메뉴 데이터상 포함",
    wikiPresent: "일반 Wiki상 대표 구성",
    presumed: "일반적으로 포함",
    possible: "포함 가능성",
    unknown: "미확인",
    conflicting: "정보 상충",
    menuAbsent: "메뉴 기록상 미포함 · 주방 교차접촉 미확인",
    wikiAbsent: "일반 Wiki상 미포함 · 이 매장 레시피 미확인",
  },
} as const;

const koreanAllergenLabels: Record<string, string> = {
  egg: "달걀",
  fish: "생선",
  milk: "우유",
  dairy: "유제품",
  peanut: "땅콩",
  sesame: "참깨",
  shellfish: "갑각류·조개류",
  soy: "대두",
  tree_nut: "견과류",
  tree_nuts: "견과류",
  wheat: "밀",
};

const koreanIngredientLabels: Record<string, string> = {
  ingredient_assorted_side_dishes: "여러 반찬",
  ingredient_bean_sprouts: "콩나물",
  ingredient_beef: "소고기",
  ingredient_beef_bone_broth: "사골 육수",
  ingredient_black_bean_paste: "춘장",
  ingredient_broth: "육수",
  ingredient_brown_sugar: "흑설탕",
  ingredient_buckwheat_noodles: "메밀면",
  ingredient_cheese: "치즈",
  ingredient_chicken: "닭고기",
  ingredient_chicken_broth: "닭 육수",
  ingredient_chili_seasoning: "고추 양념",
  ingredient_chilled_broth: "차가운 육수",
  ingredient_chocolate: "초콜릿",
  ingredient_dairy_cream: "유제품 크림",
  ingredient_egg: "달걀",
  ingredient_fish_cake: "어묵",
  ingredient_fish_paste: "생선살 반죽",
  ingredient_frying_oil: "튀김용 기름",
  ingredient_garlic: "마늘",
  ingredient_ginseng: "인삼",
  ingredient_glutinous_rice: "찹쌀",
  ingredient_gochujang: "고추장",
  ingredient_kimchi: "김치",
  ingredient_mackerel: "고등어",
  ingredient_mango: "망고",
  ingredient_mixed_filling: "혼합 소",
  ingredient_mixed_seeds: "여러 씨앗류",
  ingredient_mixed_vegetables: "여러 채소",
  ingredient_onion: "양파",
  ingredient_pickled_radish: "단무지",
  ingredient_pork: "돼지고기",
  ingredient_red_bean: "팥",
  ingredient_rice: "쌀밥",
  ingredient_rice_cake: "떡",
  ingredient_sauce: "소스",
  ingredient_seaweed: "김",
  ingredient_sesame_oil: "참기름",
  ingredient_shaved_ice: "간 얼음",
  ingredient_shellfish: "갑각류·조개류",
  ingredient_soft_tofu: "순두부",
  ingredient_soy_sauce: "간장",
  ingredient_starch: "전분",
  ingredient_sugar: "설탕",
  ingredient_sweet_potato: "고구마",
  ingredient_sweet_potato_noodles: "당면",
  ingredient_tofu: "두부",
  ingredient_tomato_sauce: "토마토소스",
  ingredient_tree_nuts: "견과류",
  ingredient_tuna: "참치",
  ingredient_wheat_dough: "밀가루 반죽",
  ingredient_wheat_flour: "밀가루",
  ingredient_wheat_noodles: "밀면",
  ingredient_wheat_wrapper: "밀가루 피",
};

const koreanPreparationLabels: Record<string, string> = {
  assembled_and_mixed: "재료를 모아 섞기",
  assembled_set: "여러 구성품을 한 상으로 담기",
  baked: "오븐에 굽기",
  boiled: "삶기",
  boiled_and_chilled: "삶은 뒤 차갑게 식히기",
  boiled_and_mixed: "삶은 뒤 섞기",
  breaded_and_deep_fried: "튀김옷을 입혀 튀기기",
  breaded_fried_and_assembled: "튀김옷을 입혀 튀긴 뒤 담기",
  chilled_and_mixed: "차갑게 섞기",
  chilled_in_broth: "차가운 육수에 담기",
  deep_fried: "기름에 튀기기",
  deep_fried_and_glazed: "튀긴 뒤 소스를 입히기",
  deep_fried_and_sauced: "튀긴 뒤 소스와 버무리기",
  deep_fried_and_seasoned: "튀긴 뒤 양념하기",
  deep_fried_and_topped: "튀긴 뒤 토핑 올리기",
  filled_and_cooked: "소를 채워 익히기",
  formed_and_cooked: "모양을 잡아 익히기",
  fried_rolled_and_sliced: "부친 뒤 말아 썰기",
  frozen_shaved_and_topped: "얼음을 갈아 토핑 올리기",
  griddled: "철판에 굽기",
  grilled: "굽기",
  grilled_and_assembled: "구운 뒤 담기",
  long_simmered: "오래 끓이기",
  marinated_and_grilled: "양념에 재운 뒤 굽기",
  pan_fried: "팬에 부치기",
  pressed_and_baked: "눌러 굽기",
  pressed_baked_and_topped: "눌러 구운 뒤 토핑 올리기",
  rolled_and_sliced: "말아 썰기",
  served_in_hot_broth: "뜨거운 육수에 담기",
  shaved_and_topped: "갈아 토핑 올리기",
  simmered: "자작하게 끓이기",
  simmered_and_assembled: "끓인 뒤 담기",
  simmered_and_topped: "끓인 뒤 토핑 올리기",
  stir_fried: "볶기",
  stir_fried_and_assembled: "볶은 뒤 담기",
  stir_fried_and_mixed: "볶은 뒤 섞기",
  stir_fried_then_simmered: "볶은 뒤 끓이기",
  wok_fried: "웍에 볶기",
  wok_fried_and_mixed: "웍에 볶아 섞기",
  wok_fried_and_sauced: "웍에 볶아 소스 입히기",
  wok_fried_separately: "재료를 따로 웍에 볶기",
};

const koreanDietaryLabels: Record<string, string> = {
  contains_animal_product: "동물성 재료 신호",
  halal_not_verified: "할랄 인증 상태",
  pork_possible: "돼지고기 포함 가능성",
  vegan_possible: "비건 가능성",
  vegetarian_possible: "채식 가능성",
};

const koreanDietaryValues: Record<string, string> = {
  contains_animal_product: "동물성 재료가 포함될 수 있음",
  halal_not_verified: "Wiki에서 할랄 인증을 확인하지 못함",
  pork_possible: "돼지고기 포함 여부를 매장별로 확인해야 함",
  vegan_possible: "비건 가능 여부를 매장별로 확인해야 함",
  vegetarian_possible: "채식 가능 여부를 매장별로 확인해야 함",
};

const dietarySafetyCodes = new Set(Object.keys(koreanDietaryLabels));

const koreanFacetLabels: Record<string, string> = {
  analogy: "비슷한 음식",
  culture: "문화적 특징",
  ingredients: "재료",
  overview: "개요",
  safety: "주의 정보",
  satiety: "포만감",
  taste: "맛",
  temperature: "온도",
  texture: "식감",
};

function humanizeToken(value: string) {
  return value
    .replace(/^(allergen|ingredient|diet)_/, "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusText(
  status: KnowledgeClaimStatus,
  scope: KnowledgeSourceScope,
  language: string,
) {
  const copy = language === "한국어" ? knowledgeCopy["한국어"] : knowledgeCopy.English;
  if (status === "CONFIRMED_PRESENT") {
    return scope === "MENU" || scope === "OPTION" ? copy.menuPresent : copy.wikiPresent;
  }
  if (status === "PRESUMED_PRESENT") return copy.presumed;
  if (status === "POSSIBLE") return copy.possible;
  if (status === "CONFLICTING") return copy.conflicting;
  if (status === "CONFIRMED_ABSENT") {
    return scope === "MENU" || scope === "OPTION" ? copy.menuAbsent : copy.wikiAbsent;
  }
  return copy.unknown;
}

function allergenLabel(code: string, language: string) {
  const normalized = code.toLowerCase().replace(/^allergen_/, "").replace(/_risk$/, "");
  if (language === "한국어") return koreanAllergenLabels[normalized] ?? humanizeToken(code);
  return humanizeToken(normalized);
}

function ingredientLabel(
  ingredientId: string,
  nameEn: string,
  nameKo: string | undefined,
  language: string,
) {
  if (language === "한국어") return nameKo ?? koreanIngredientLabels[ingredientId] ?? nameEn;
  return nameEn;
}

function preparationLabel(method: string, language: string) {
  if (language === "한국어") return koreanPreparationLabels[method] ?? humanizeToken(method);
  return humanizeToken(method);
}

function dietaryLabel(code: string, displayName: string, language: string) {
  const normalized = code.toLowerCase().replace(/^diet_/, "");
  if (language === "한국어") return koreanDietaryLabels[normalized] ?? displayName;
  return displayName || humanizeToken(code);
}

function dietaryValue(code: string, valueText: string, language: string) {
  const normalized = code.toLowerCase().replace(/^diet_/, "");
  if (language === "한국어") return koreanDietaryValues[normalized] ?? valueText;
  return valueText;
}

function facetLabel(facet: string, language: string) {
  if (language === "한국어") return koreanFacetLabels[facet.toLowerCase()] ?? humanizeToken(facet);
  return humanizeToken(facet);
}

function KnowledgeSummary({
  knowledge,
  language,
}: {
  knowledge: StructuredMenuKnowledge;
  language: string;
}) {
  const ui = language === "한국어" ? knowledgeCopy["한국어"] : knowledgeCopy.English;
  const wikiPassages = (knowledge.wiki_passages ?? [])
    .filter((passage, index, passages) => (
      passage.content.trim()
      && passages.findIndex((candidate) => candidate.content === passage.content) === index
    ))
    .slice(0, 3);
  const ingredientClaims = (knowledge.ingredient_claims ?? []).slice(0, 6);
  const allergenClaims = (knowledge.allergen_claims ?? []).slice(0, 10);
  const dietaryClaims = (knowledge.dietary_claims ?? [])
    .filter((claim) => dietarySafetyCodes.has(claim.code.toLowerCase().replace(/^diet_/, "")))
    .slice(0, 5);
  const preparationClaims = (knowledge.preparation_claims ?? []).slice(0, 3);
  const hasKnowledge = Boolean(
    wikiPassages.length
    || ingredientClaims.length
    || allergenClaims.length
    || dietaryClaims.length
    || preparationClaims.length,
  );

  if (!hasKnowledge) return null;

  const passageItems = wikiPassages.map((passage) => (
    <div className="wiki-passage" key={passage.chunk_id}>
      <strong>{facetLabel(passage.facet, language)}</strong>
      <p>{passage.content}</p>
    </div>
  ));

  return (
    <div className="knowledge-summary">
      {wikiPassages.length > 0 && language === "한국어" && (
        <details className="knowledge-section knowledge-wiki knowledge-wiki-details">
          <summary>{ui.originalWiki}</summary>
          {passageItems}
        </details>
      )}
      {wikiPassages.length > 0 && language !== "한국어" && (
        <section className="knowledge-section knowledge-wiki" aria-label={ui.wiki}>
          <h5><Info size={15} aria-hidden="true" /> {ui.wiki}</h5>
          {passageItems}
        </section>
      )}

      {ingredientClaims.length > 0 && (
        <section className="knowledge-section" aria-label={ui.ingredients}>
          <h5><Leaf size={15} aria-hidden="true" /> {ui.ingredients}</h5>
          <ul className="knowledge-list ingredient-list">
            {ingredientClaims.map((claim) => (
              <li key={`${claim.source_id}:${claim.ingredient_id}`}>
                <strong>{ingredientLabel(claim.ingredient_id, claim.name_en, claim.name_ko, language)}</strong>
                <small>{statusText(claim.status, claim.source_scope, language)}</small>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(allergenClaims.length > 0 || dietaryClaims.length > 0) && (
        <section className="knowledge-section knowledge-risks" aria-label={ui.allergens}>
          <h5><TriangleAlert size={15} aria-hidden="true" /> {ui.allergens}</h5>
          <ul className="knowledge-list">
            {allergenClaims.map((claim) => (
              <li key={`${claim.source_id}:${claim.allergen_id}`}>
                <strong>{allergenLabel(claim.code, language)}</strong>
                <small>{statusText(claim.status, claim.source_scope, language)}</small>
              </li>
            ))}
            {dietaryClaims.map((claim) => (
              <li key={`${claim.source_id}:${claim.attribute_id}`}>
                <strong>{dietaryLabel(claim.code, claim.display_name, language)}</strong>
                <small>{dietaryValue(claim.code, claim.value_text, language)} · {statusText(claim.status, claim.source_scope, language)}</small>
              </li>
            ))}
          </ul>
        </section>
      )}

      {preparationClaims.length > 0 && (
        <section className="knowledge-section" aria-label={ui.preparation}>
          <h5><Soup size={15} aria-hidden="true" /> {ui.preparation}</h5>
          <ul className="preparation-list">
            {preparationClaims.map((claim) => (
              <li key={`${claim.source_id}:${claim.method}`}>
                <strong>{preparationLabel(claim.method, language)}</strong>
                <span>{language === "한국어" ? statusText(claim.status, claim.source_scope, language) : claim.value_text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="knowledge-boundary"><TriangleAlert size={15} aria-hidden="true" /> {ui.boundary}</p>
    </div>
  );
}

export function RichCard({ card, onChooseMenu, onQuickReply, disabled = false }: Props) {
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
    return <PresetCollectionCard card={card} onChooseMenu={onChooseMenu} disabled={disabled} />;
  }

  if (card.type === "category_recommendations") {
    const categories = card.data.categories ?? [];
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
                <span>{journeyCopy.syntheticMenu} · {category.source_ids.length} catalog references</span>
              </details>
              <button className="secondary-button full" disabled={disabled} onClick={() => onQuickReply(`Show me ${category.category}`, `${copy.chooseMenu}: ${category.category}`)}>
                {copy.chooseMenu} <ArrowRight size={15} />
              </button>
            </article>
          ))}
        </div>
      </section>
    );
  }

  if (card.type === "menu_recommendations") {
    const menus = card.data.menus ?? [];
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
                <span>{journeyCopy.syntheticMenu} · {menu.evidence_ids.length} evidence references</span>
              </details>
              <p className="demo-label">{journeyCopy.syntheticMenu} · 2026-08-06</p>
              <button className="primary-button full" disabled={disabled} onClick={() => onChooseMenu(menu)}>
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
    const menu = card.data.menu;
    const explanation = card.data.explanation;
    const ui = language === "한국어" ? knowledgeCopy["한국어"] : knowledgeCopy.English;
    return (
      <section className="explanation-card" aria-label={card.title}>
        <div className="card-heading"><p className="eyebrow">{copy.whyMatch}</p><h3>{localizedCatalog ? dynamicCopy.menuMatches : card.title}</h3>{!localizedCatalog && <p>{card.subtitle}</p>}</div>
        <article>
          <h4>{menu ? menuName(menu, language) : explanation.category}</h4>
          <p>{localizedCatalog ? dynamicCopy.catalogDescription : explanation.cultural_analogy}</p>
          {menu && <p><strong>{journeyCopy.portion}:</strong> {localizedCatalog ? dynamicCopy.catalogDescription : explanation.portion} · <strong>{copy.spice}:</strong> {menu.spice_level} / 3</p>}

          <KnowledgeSummary knowledge={explanation} language={language} />
          {(localizedCatalog && explanation.unknown_fields.length ? [dynamicCopy.riskUnknown] : explanation.unknown_fields).map((item) => <p className="risk-copy" key={item}>{item}</p>)}
          <details className="source-drawer"><summary>{copy.evidence}</summary><span>{ui.synthetic} · {explanation.evidence_ids.length} grounded references</span></details>
        </article>
      </section>
    );
  }

  if (card.type === "dietary_evidence") {
    const evidence = card.data.evidence ?? [];
    return (
      <section className="evidence-card" aria-label={card.title}>
        <div className="card-heading">
          <p className="eyebrow risk">{copy.evidence}</p>
          <h3>{localizedCatalog ? copy.evidence : card.title}</h3>
          {!localizedCatalog && <p>{card.subtitle}</p>}
        </div>
        <KnowledgeSummary knowledge={card.data} language={language} />
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
    const merchants = card.data.merchants ?? [];
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
              <details className="source-drawer"><summary>{copy.evidence}</summary><span>{merchant.evidence_ids.length ? `${merchant.evidence_ids.length} grounded references` : journeyCopy.notVerified}</span></details>
              <button
                className={index === 0 ? "primary-button full" : "secondary-button full"}
                disabled={disabled || !merchant.menu}
                onClick={() => { if (merchant.menu) onChooseMenu(merchant.menu); }}
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
