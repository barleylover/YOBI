import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelMenu } from "../src/components/ChannelMenu";
import { api } from "../src/lib/api";
import type { MenuSummary } from "../src/types";

const menu: MenuSummary = {
  menu_id: "menu_discovery_1",
  merchant_id: "merchant_discovery_1",
  merchant_name: "YOBI Discovery Kitchen",
  name_en: "미번역 메뉴",
  name_ko: "미번역 메뉴",
  category: "Gimbap",
  description: "Prepared menu.",
  cultural_description: "Rice and fillings wrapped in seaweed.",
  price: 9000,
  minimum_order_amount: 12000,
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("active English discovery demos", () => {
  it("shows a diverse top ten, explains each prepared sort, and selects an English-labelled menu", async () => {
    const items = Array.from({ length: 12 }, (_, index) => ({
      position: index + 1,
      dish_name: index === 0 ? "Gimbap" : `Dish ${index + 1}`,
      metric_label: "Prepared activity",
      metric_value: 100 - index,
      menu: {
        ...menu,
        menu_id: `menu_discovery_${index + 1}`,
        merchant_id: `merchant_discovery_${index + 1}`,
      },
    }));
    const rankings = vi.spyOn(api, "getFoodRankings").mockResolvedValue({
      snapshot_id: "ranking_snapshot_1",
      demo_basis: "Server demo basis",
      sort: "review_count",
      items,
    });
    const onChoose = vi.fn().mockResolvedValue(undefined);

    render(
      <ChannelMenu
        sessionId="session_1"
        language="English"
        locale="en-US"
        onChoose={onChoose}
        onEditProfile={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    fireEvent.click(screen.getByRole("button", { name: "Food rankings" }));

    expect(await screen.findByRole("heading", { name: "Food Rankings · Top 10" })).toBeInTheDocument();
    expect(screen.getByText(/Merchant and dish diversity/)).toBeInTheDocument();
    expect(document.querySelectorAll(".v2-ranking-list > li")).toHaveLength(10);
    expect(screen.getAllByText("Gimbap")).toHaveLength(2);
    expect(screen.queryByText("미번역 메뉴")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Most ordered" }));
    await waitFor(() => {
      expect(rankings).toHaveBeenLastCalledWith(
        "session_1",
        "order_count",
        expect.any(AbortSignal),
        10,
      );
    });
    expect(screen.getByText(/prepared order-interest signal/i)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Choose this dish" })[0]);
    await waitFor(() => {
      expect(onChoose).toHaveBeenCalledWith(
        expect.objectContaining({ menu_id: "menu_discovery_1", localized_title: "Gimbap" }),
        "ranking_snapshot_1",
      );
    });
  });

  it("keeps all five film-food slots visible and takes an available match into the order flow", async () => {
    const availableDishes = ["Gimbap", "Tteokbokki", "Naengmyeon", "Eomuk"];
    vi.spyOn(api, "getKpopDemonHuntersFeature").mockResolvedValue({
      snapshot_id: "feature_snapshot_1",
      items: availableDishes.map((dishName, index) => ({
        dish_name: dishName,
        description: `General ${dishName} description.`,
        menu: {
          ...menu,
          menu_id: `feature_menu_${index + 1}`,
          merchant_id: `feature_merchant_${index + 1}`,
          localized_title: index === 0 ? "Spam Gimbap" : dishName,
        },
      })),
    });
    const onChoose = vi.fn().mockResolvedValue(undefined);

    render(
      <ChannelMenu
        sessionId="session_1"
        language="English"
        locale="en-US"
        onChoose={onChoose}
        onEditProfile={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    fireEvent.click(screen.getByRole("button", { name: "KPOP DEMON HUNTERS" }));

    expect(await screen.findByRole("heading", { name: "KPop Demon Hunters · K-food trail" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Korean dishes arranged/i })).toHaveAttribute(
      "src",
      "/yobi-gimbap-feature-hero.png",
    );
    expect(screen.getByRole("link", { name: "Netflix Tudum official food guide" })).toHaveAttribute(
      "href",
      "https://www.netflix.com/tudum/articles/kpop-demon-hunters-food-guide",
    );
    expect(document.querySelectorAll(".v2-feature-list > article")).toHaveLength(5);
    expect(screen.getByText("Hotteok")).toBeInTheDocument();
    expect(screen.getByText("Not available in this demo area")).toBeInTheDocument();
    expect(screen.getByText("Spam Gimbap")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Choose this dish" })[0]);
    await waitFor(() => {
      expect(onChoose).toHaveBeenCalledWith(
        expect.objectContaining({ menu_id: "feature_menu_1", localized_title: "Spam Gimbap" }),
        "feature_snapshot_1",
      );
    });
  });

  it("offers a deterministic retry after a collection request fails", async () => {
    vi.spyOn(api, "getFoodRankings")
      .mockRejectedValueOnce(new Error("TEMPORARY_FAILURE"))
      .mockResolvedValueOnce({
        snapshot_id: "ranking_snapshot_retry",
        demo_basis: "Server demo basis",
        sort: "review_count",
        items: [{
          position: 1,
          dish_name: "Gimbap",
          metric_label: "Prepared activity",
          metric_value: 10,
          menu,
        }],
      });

    render(
      <ChannelMenu
        sessionId="session_1"
        language="English"
        locale="en-US"
        onChoose={vi.fn()}
        onEditProfile={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    fireEvent.click(screen.getByRole("button", { name: "Food rankings" }));

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect((await screen.findAllByText("Gimbap")).length).toBeGreaterThanOrEqual(1);
  });
});
