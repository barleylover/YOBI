import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecommendationResults } from "../src/components/RecommendationResults";
import { getProductCopy } from "../src/lib/productI18n";
import { getRecommendationCopy } from "../src/lib/recommendationI18n";
import type { MenuSummary, PreferenceCatalog, RecommendationBatchV2 } from "../src/types";

const menu: MenuSummary = {
  menu_id: "menu_chat_1",
  merchant_id: "merchant_chat_1",
  merchant_name: "YOBI Kitchen",
  name_en: "Gimbap",
  name_ko: "김밥",
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

const secondMenu = { ...menu, menu_id: "menu_chat_2", name_en: "Bibimbap", name_ko: "비빔밥" };
const catalog: PreferenceCatalog = {
  schema_version: "2",
  catalog_version: "catalog-chat-test",
  knowledge_release_id: "knowledge-chat-test",
  locale: "en",
  categories: [],
  spice_references: [],
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
    selection_reason: "Matches the saved flavor and form choices.",
    description: item.description,
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
    document.documentElement.dir = "ltr";
    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo;
  });

  it("uses a three-action fixed rail, omits recommendation ranks, and caches one comparison per batch", async () => {
    const onSimilar = vi.fn();
    const onEdit = vi.fn();
    const onCompare = vi.fn().mockResolvedValue({
      snapshot_id: batch.snapshot_id,
      request_id: "comparison_chat_test",
      summary: "Gimbap is lighter; bibimbap is a fuller bowl meal.",
      generated_by: "LLM" as const,
      items: [menu, secondMenu].map((item) => ({
        menu_id: item.menu_id,
        name: item.name_en,
        key_difference: "Form",
        taste_texture: "Balanced",
        ingredients_form: "Rice-based",
        spice_heaviness: "Mild",
        eating_context: "Lunch",
        best_for: "A straightforward meal",
        unverified_dietary_info: "Confirm ingredients with the restaurant.",
      })),
    });

    render(
      <RecommendationResults
        batch={batch}
        catalog={catalog}
        copy={getRecommendationCopy("English")}
        language="English"
        locale="en-US"
        onChoose={vi.fn()}
        onSimilar={onSimilar}
        onEdit={onEdit}
        onCompare={onCompare}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("YOBI")).toBeInTheDocument();
    expect(document.querySelector(".rank-bar")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".result-action-rail > button")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Show different menus" }));
    expect(onSimilar).toHaveBeenCalledTimes(1);

    const compare = screen.getByRole("button", { name: "Compare these menus" });
    fireEvent.click(compare);
    expect(await screen.findByText("Gimbap is lighter; bibimbap is a fuller bowl meal.")).toBeInTheDocument();
    expect(onCompare).toHaveBeenCalledTimes(1);
    fireEvent.click(compare);
    fireEvent.click(compare);
    await waitFor(() => expect(screen.getByText("Gimbap is lighter; bibimbap is a fuller bowl meal.")).toBeVisible());
    expect(onCompare).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Edit choices" }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("preserves a grounded server food description for Arabic external-catalog results", () => {
    const groundedDescription = "Wiki reference: the rice is seasoned before being rolled with vegetables in seaweed.";
    const externalBatch: RecommendationBatchV2 = {
      ...batch,
      recommendations: [{
        ...batch.recommendations[0],
        description: groundedDescription,
        menu: { ...batch.recommendations[0].menu, is_synthetic: false },
      }],
    };

    render(
      <RecommendationResults
        batch={externalBatch}
        catalog={catalog}
        copy={getRecommendationCopy("العربية")}
        language="العربية"
        locale="ar"
        onChoose={vi.fn()}
        onSimilar={vi.fn()}
        onEdit={vi.fn()}
        onCompare={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText(groundedDescription)).toBeInTheDocument();
    expect(screen.queryByText(/وجبة اصطناعية|synthetic menu/i)).not.toBeInTheDocument();
  });

  it("moves exactly one Arabic RTL card with controls, physical arrow keys, and signed scroll offsets", async () => {
    document.documentElement.dir = "rtl";
    const productCopy = getProductCopy("العربية").recommendation;
    const scrollTo = vi.fn(function (this: HTMLElement, options: ScrollToOptions) {
      this.scrollLeft = Number(options.left ?? 0);
    });
    HTMLElement.prototype.scrollTo = scrollTo as unknown as typeof HTMLElement.prototype.scrollTo;

    render(
      <RecommendationResults
        batch={batch}
        catalog={catalog}
        copy={getRecommendationCopy("العربية")}
        language="العربية"
        locale="ar"
        onChoose={vi.fn()}
        onSimilar={vi.fn()}
        onEdit={vi.fn()}
        onCompare={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    const carousel = document.querySelector<HTMLElement>(".structured-menu-carousel")!;
    Object.defineProperty(carousel, "clientWidth", { configurable: true, value: 390 });
    scrollTo.mockClear();

    fireEvent.click(screen.getByRole("button", { name: productCopy.next }));
    expect(scrollTo).toHaveBeenLastCalledWith({ left: -390, behavior: "smooth" });
    expect(await screen.findByText(productCopy.cardPosition(2, 2))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: productCopy.previous }));
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 0, behavior: "smooth" });
    expect(await screen.findByText(productCopy.cardPosition(1, 2))).toBeInTheDocument();

    carousel.scrollLeft = -390;
    fireEvent.scroll(carousel);
    expect(await screen.findByText(productCopy.cardPosition(2, 2))).toBeInTheDocument();
    carousel.scrollLeft = 0;
    fireEvent.scroll(carousel);
    expect(await screen.findByText(productCopy.cardPosition(1, 2))).toBeInTheDocument();

    carousel.focus();
    fireEvent.keyDown(carousel, { key: "ArrowLeft" });
    expect(scrollTo).toHaveBeenLastCalledWith({ left: -390, behavior: "smooth" });
    expect(await screen.findByText(productCopy.cardPosition(2, 2))).toBeInTheDocument();
    fireEvent.keyDown(carousel, { key: "ArrowRight" });
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 0, behavior: "smooth" });
    expect(await screen.findByText(productCopy.cardPosition(1, 2))).toBeInTheDocument();
  });
});
