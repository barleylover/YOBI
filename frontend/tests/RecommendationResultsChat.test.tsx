import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecommendationResults } from "../src/components/RecommendationResults";
import { getRecommendationCopy } from "../src/lib/recommendationI18n";
import { getRedesignCopy } from "../src/lib/redesignI18n";
import type { MenuSummary, RecommendationBatchV2 } from "../src/types";

const menu: MenuSummary = {
  menu_id: "menu_chat_1",
  merchant_id: "merchant_chat_1",
  merchant_name: "YOBI Kitchen",
  name_en: "Gimbap",
  name_ko: "김밥",
  localized_title: "Gimbap",
  category: "Gimbap",
  description: "Rice and vegetables wrapped in seaweed.",
  cultural_description: "A compact Korean meal.",
  price: 9000,
  delivery_fee: 2000,
  eta_min: 20,
  eta_max: 30,
  spice_level: 1,
  serves_min: 1,
  serves_max: 1,
  dietary_summary: "",
  evidence_status: "VERIFIED",
  match_reasons: [],
  risk_hints: [],
  evidence_ids: [],
  grounded_claim_ids: [],
  grounded_passage_ids: [],
  is_synthetic: true,
};

const secondMenu: MenuSummary = {
  ...menu,
  menu_id: "menu_chat_2",
  name_en: "Bibimbap",
  name_ko: "비빔밥",
  localized_title: "Bibimbap",
};

const batch: RecommendationBatchV2 = {
  session_id: "session_chat_test",
  request_id: "request_chat_test",
  snapshot_id: "snapshot_chat_test",
  state_version: 2,
  criteria_version: 1,
  status: "RECOMMENDED",
  phase: "COMPLETE",
  criteria_summary: "Korean comfort food",
  recommendations: [menu, secondMenu].map((item, index) => ({
    rank: index + 1,
    menu: item,
    title: item.name_en,
    localized_title: item.localized_title,
    localized_subtitle: index === 0 ? "Seasoned rice and fillings rolled in seaweed" : "Korean mixed rice bowl",
    selection_reason: "Legacy selection reason must stay hidden.",
    description: item.description,
    yobi_short_explanation: "A familiar rice-based Korean meal with mild flavours.",
    yobi_long_explanation: "This is a rice-based Korean meal. The Wiki evidence describes its familiar ingredients. Its mild flavour makes it approachable.",
    source_description: `Restaurant description for ${item.name_ko}.`,
    review_summary: "Guests often mention balanced flavour and a convenient portion. Some found the seaweed slightly chewy.",
    country_preference: { country_code: "US", preference_percent: 82, sample_size: 426 },
    evidence_ids: ["wiki-1"],
    review_ids: ["review-1"],
    generation_model: "xai.grok-4.3",
    matched_criteria: [],
    wiki_passages: [],
    caution_codes: [],
  })),
  unmatched_category_codes: [],
};

describe("chat-style recommendation results", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo;
  });

  it("shows localized YOBI and YOGIYO content without rank, selection reason, or comparison", () => {
    render(
      <RecommendationResults
        batch={batch}
        copy={getRecommendationCopy("English")}
        v2={getRedesignCopy("English")}
        timestamp="10:05"
        language="English"
        locale="en-US"
        onChoose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Gimbap").length).toBeGreaterThan(0);
    expect(screen.getByText("Seasoned rice and fillings rolled in seaweed")).toBeInTheDocument();
    expect(screen.getAllByText("YOBI:").length).toBeGreaterThan(0);
    expect(screen.getAllByText("YOGIYO:").length).toBeGreaterThan(0);
    expect(screen.queryByText("Legacy selection reason must stay hidden.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /compare/i })).not.toBeInTheDocument();
    expect(document.querySelector(".rank-bar")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "View additional explanation" })[0]);
    expect(screen.getByText(/This is a rice-based Korean meal/)).toBeInTheDocument();
    expect(screen.getByText(/United States.*82%/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "82%" })).toBeInTheDocument();
    expect(screen.getByText(/Guests often mention balanced flavour/)).toBeInTheDocument();
    expect(screen.queryByText(/Gimbap wraps rice/)).not.toBeInTheDocument();
  });

  it("uses English copy for a selected language outside Korean, English, and Japanese", () => {
    const groundedDescription = "Wiki reference: seasoned rice is rolled with vegetables in seaweed.";
    const externalBatch: RecommendationBatchV2 = {
      ...batch,
      recommendations: [{
        ...batch.recommendations[0],
        yobi_short_explanation: groundedDescription,
        menu: { ...batch.recommendations[0].menu, is_synthetic: false },
      }],
    };

    render(
      <RecommendationResults
        batch={externalBatch}
        copy={getRecommendationCopy("العربية")}
        v2={getRedesignCopy("العربية")}
        timestamp="10:05"
        language="العربية"
        locale="en"
        onChoose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText(groundedDescription)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose this menu" })).toBeInTheDocument();
    expect(screen.queryByText(/وجبة اصطناعية|synthetic menu/i)).not.toBeInTheDocument();
  });

  it("does not expose an untranslated Korean source description after an English fallback", () => {
    const fallbackBatch: RecommendationBatchV2 = {
      ...batch,
      recommendations: [{
        ...batch.recommendations[0],
        source_description: "",
        menu: {
          ...batch.recommendations[0].menu,
          description: "번역되지 않은 식당 원문 설명",
        },
      }],
    };

    render(
      <RecommendationResults
        batch={fallbackBatch}
        copy={getRecommendationCopy("English")}
        v2={getRedesignCopy("English")}
        timestamp="10:05"
        language="English"
        locale="en-US"
        onChoose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.queryByText("번역되지 않은 식당 원문 설명")).not.toBeInTheDocument();
    expect(screen.queryByText("YOGIYO:")).not.toBeInTheDocument();
  });

  it("renders every recommendation in the horizontal card carousel", () => {
    render(
      <RecommendationResults
        batch={batch}
        copy={getRecommendationCopy("English")}
        v2={getRedesignCopy("English")}
        timestamp="10:05"
        language="English"
        locale="en-US"
        onChoose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(document.querySelector(".v2-card-carousel")).toHaveAttribute("aria-label", "Picked for your preferences");
    expect(document.querySelectorAll(".v2-alimtalk-card")).toHaveLength(2);
    expect(screen.getAllByText("Bibimbap").length).toBeGreaterThan(0);
  });
});
