import { describe, expect, it } from "vitest";
import {
  findMenuProjection,
  recommendationCriteriaEqual,
} from "../src/lib/recommendationState";

describe("recommendation state helpers", () => {
  it("compares equivalent criteria independently of object key order", () => {
    const left = {
      flavors: ["SPICY", "SAVORY"],
      dietary_filters: { vegan: false, halal_certified_only: true },
    };
    const right = {
      dietary_filters: { halal_certified_only: true, vegan: false },
      flavors: ["SPICY", "SAVORY"],
    };

    expect(recommendationCriteriaEqual(left, right)).toBe(true);
    expect(recommendationCriteriaEqual(left, { ...right, flavors: ["SAVORY", "SPICY"] }))
      .toBe(false);
  });

  it("finds a nested menu projection without recursing forever on cycles", () => {
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    cyclic.cards = [{ data: { menu: {
      menu_id: "menu-1",
      merchant_id: "merchant-1",
      name_en: "Bibimbap",
    } } }];

    expect(findMenuProjection(cyclic, "menu-1")?.name_en).toBe("Bibimbap");
    expect(findMenuProjection(cyclic, "missing")).toBeNull();
    expect(recommendationCriteriaEqual(cyclic, cyclic)).toBe(false);
  });

  it("keeps the legacy depth-first first-match order for duplicate menu IDs", () => {
    const cards = [
      { menu_id: "menu-1", merchant_id: "merchant-1", name_en: "First" },
      { menu_id: "menu-1", merchant_id: "merchant-2", name_en: "Second" },
    ];

    expect(findMenuProjection(cards, "menu-1")?.name_en).toBe("First");
  });
});
