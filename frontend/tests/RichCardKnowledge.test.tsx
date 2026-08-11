import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RichCard } from "../src/components/RichCard";
import { useSessionStore } from "../src/stores/session";
import type { CardPayload } from "../src/types";

const knowledgeCard: CardPayload = {
  type: "menu_explanation",
  title: "About tuna gimbap",
  subtitle: "General synthetic dish Wiki",
  data: {
    explanation: {
      category: "Tuna gimbap",
      cultural_analogy: "A tuna-filled rice pinwheel.",
      portion: "Usually serves 1",
      unknown_fields: [],
      evidence_ids: ["claim_hidden_ingredient", "chunk_hidden_safety"],
      is_synthetic: true,
      wiki_passages: [{
        chunk_id: "chunk_hidden_safety",
        document_id: "doc_hidden_tuna_gimbap",
        concept_id: "dish_tuna_gimbap",
        facet: "safety",
        content: "Fish is presumed present, while the restaurant-specific recipe still requires confirmation.",
        source_kind: "SYNTHETIC_WIKI",
        source_version: "demo-wiki-v1",
        is_synthetic: true,
        score: 0.92,
      }],
      ingredient_claims: [
        {
          ingredient_id: "ingredient_tuna",
          name_en: "tuna",
          name_ko: "참치",
          role: "DEFINING",
          status: "PRESUMED_PRESENT",
          source_scope: "DISH_CONCEPT",
          source_id: "claim_hidden_ingredient",
          source_version: "demo-wiki-v1",
          confidence_band: "medium",
          inherited: false,
        },
        {
          ingredient_id: "ingredient_fish_cake",
          name_en: "fish cake",
          role: "OPTIONAL",
          status: "CONFIRMED_ABSENT",
          source_scope: "OPTION",
          source_id: "claim_hidden_removed_option",
          source_version: "demo-menu-v1",
          confidence_band: "high",
          inherited: false,
        },
      ],
      allergen_claims: [
        {
          allergen_id: "allergen_fish",
          code: "fish",
          status: "PRESUMED_PRESENT",
          source_scope: "DISH_CONCEPT",
          source_id: "claim_hidden_fish",
          source_version: "demo-wiki-v1",
          confidence_band: "medium",
          inherited: false,
          cross_contamination_status: "UNKNOWN",
        },
        {
          allergen_id: "allergen_shellfish",
          code: "shellfish_risk",
          status: "CONFIRMED_ABSENT",
          source_scope: "DISH_CONCEPT",
          source_id: "claim_hidden_shellfish",
          source_version: "demo-wiki-v1",
          confidence_band: "medium",
          inherited: false,
          cross_contamination_status: "UNKNOWN",
        },
      ],
      dietary_claims: [{
        attribute_id: "diet_halal_not_verified",
        code: "halal_not_verified",
        display_name: "Halal status",
        value_text: "Not halal-verified by the Wiki",
        status: "UNKNOWN",
        source_scope: "DISH_CONCEPT",
        source_id: "claim_hidden_halal",
        source_version: "demo-wiki-v1",
        confidence_band: "medium",
        inherited: false,
      }],
      preparation_claims: [{
        method: "rolled_and_sliced",
        value_text: "Fillings are rolled with rice in seaweed and sliced.",
        status: "PRESUMED_PRESENT",
        source_scope: "DISH_CONCEPT",
        source_id: "claim_hidden_preparation",
        source_version: "demo-wiki-v1",
        confidence_band: "medium",
        inherited: false,
      }],
    },
  },
};

const dietaryKnowledgeCard: CardPayload = {
  type: "dietary_evidence",
  title: "Dietary evidence",
  subtitle: "Evidence status is not a safety guarantee",
  data: {
    evidence: [],
    wiki_passages: knowledgeCard.data.explanation.wiki_passages,
    ingredient_claims: knowledgeCard.data.explanation.ingredient_claims,
    allergen_claims: knowledgeCard.data.explanation.allergen_claims,
    dietary_claims: knowledgeCard.data.explanation.dietary_claims,
    preparation_claims: knowledgeCard.data.explanation.preparation_claims,
  },
};

const completeSafetyCard: CardPayload = {
  ...knowledgeCard,
  data: {
    explanation: {
      ...knowledgeCard.data.explanation,
      allergen_claims: ["egg", "fish", "milk", "sesame", "shellfish_risk", "soy", "wheat"].map(
        (code) => ({
          allergen_id: `allergen_${code}`,
          code,
          status: "POSSIBLE" as const,
          source_scope: "DISH_CONCEPT" as const,
          source_id: `claim_${code}`,
          source_version: "demo-wiki-v1",
          confidence_band: "medium",
          inherited: false,
          cross_contamination_status: "UNKNOWN",
        }),
      ),
      dietary_claims: [
        "contains_animal_product",
        "halal_not_verified",
        "pork_possible",
        "vegan_possible",
        "vegetarian_possible",
      ].map((code) => ({
        attribute_id: `diet_${code}`,
        code,
        display_name: code.replaceAll("_", " "),
        value_text: code.replaceAll("_", " "),
        status: "POSSIBLE" as const,
        source_scope: "DISH_CONCEPT" as const,
        source_id: `claim_${code}`,
        source_version: "demo-wiki-v1",
        confidence_band: "medium",
        inherited: false,
      })),
    },
  },
};

function renderCard(card: CardPayload = knowledgeCard) {
  return render(
    <RichCard
      card={card}
      onChooseMenu={vi.fn()}
      onQuickReply={vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
  useSessionStore.getState().setLocaleDraft("English", "United States");
  sessionStorage.clear();
});

describe("RichCard menu Wiki explanation", () => {
  it("renders the retrieved passage and structured claims without exposing raw source IDs", () => {
    const { container } = renderCard();

    expect(screen.getByLabelText("Retrieved menu Wiki")).toHaveTextContent(
      "Fish is presumed present, while the restaurant-specific recipe still requires confirmation.",
    );
    expect(screen.getByLabelText("Typical ingredients and menu changes")).toHaveTextContent("tuna");
    expect(screen.getByLabelText("Typical ingredients and menu changes")).toHaveTextContent(
      "Menu record says absent; kitchen cross-contact is not verified",
    );
    expect(screen.getByLabelText("Allergy and dietary signals")).toHaveTextContent("Fish");
    expect(screen.getByLabelText("Allergy and dietary signals")).toHaveTextContent(
      "General Wiki says absent; this restaurant recipe is not verified",
    );
    expect(screen.getByLabelText("Allergy and dietary signals")).toHaveTextContent("Not halal-verified by the Wiki");
    expect(screen.getByLabelText("Typical preparation")).toHaveTextContent(
      "Fillings are rolled with rice in seaweed and sliced.",
    );
    expect(screen.getByText(/not an allergy-safe guarantee/i)).toBeInTheDocument();
    expect(container).not.toHaveTextContent("claim_hidden_ingredient");
    expect(container).not.toHaveTextContent("chunk_hidden_safety");
  });

  it("uses clear Korean labels while preserving uncertainty and cross-contact limits", () => {
    useSessionStore.getState().setLocaleDraft("한국어", "South Korea");
    const { container } = renderCard();

    const originalWiki = screen.getByText("Wiki 원문 근거(영문)").closest("details");
    expect(originalWiki).not.toHaveAttribute("open");
    expect(originalWiki).toHaveTextContent("Fish is presumed present");
    expect(screen.getByLabelText("대표 재료·변경 정보")).toHaveTextContent("참치");
    expect(screen.getByLabelText("대표 재료·변경 정보")).toHaveTextContent(
      "메뉴 기록상 미포함 · 주방 교차접촉 미확인",
    );
    expect(screen.getByLabelText("알레르기·식단 신호")).toHaveTextContent("생선");
    expect(screen.getByLabelText("알레르기·식단 신호")).toHaveTextContent(
      "일반 Wiki상 미포함 · 이 매장 레시피 미확인",
    );
    expect(screen.getByLabelText("대표 조리법")).toHaveTextContent("말아 썰기");
    expect(screen.getByText(/알레르기 안전을 보장하지 않습니다/)).toHaveTextContent(
      "주방 교차접촉 여부는 확인되지 않았습니다",
    );
    expect(container).not.toHaveTextContent("claim_hidden_shellfish");
  });

  it("renders the same structured Wiki facts in the dietary-evidence path", () => {
    const { container } = renderCard(dietaryKnowledgeCard);

    expect(screen.getByLabelText("Typical ingredients and menu changes")).toHaveTextContent("tuna");
    expect(screen.getByLabelText("Allergy and dietary signals")).toHaveTextContent("Shellfish");
    expect(screen.getByLabelText("Typical preparation")).toHaveTextContent("Rolled And Sliced");
    expect(screen.getByText(/not an allergy-safe guarantee/i)).toBeInTheDocument();
    expect(container).not.toHaveTextContent("claim_hidden_fish");
  });

  it("does not truncate supported allergen or dietary safety signals", () => {
    useSessionStore.getState().setLocaleDraft("한국어", "South Korea");
    renderCard(completeSafetyCard);

    const risks = screen.getByLabelText("알레르기·식단 신호");
    expect(risks).toHaveTextContent("밀");
    expect(risks).toHaveTextContent("채식 가능성");
  });
});
