import { describe, expect, it } from "vitest";
import {
  menuHasObviousVeganConflict,
  optionDietaryConflicts,
  optionGroupHasNoneChoice,
  planDefaultOptionSelections,
  selectedOptionsPriceDelta,
  toggledOptionSelection,
} from "../src/lib/orderFlow";
import type { MenuSummary, OptionGroup, OptionItem } from "../src/types";

function option(
  option_item_id: string,
  overrides: Partial<OptionItem> = {},
): OptionItem {
  return {
    option_item_id,
    name_en: option_item_id,
    name_ko: option_item_id,
    description: "",
    price_delta: 0,
    available: true,
    conflicting_rules: [],
    ...overrides,
  };
}

function group(
  option_group_id: string,
  items: OptionItem[],
  overrides: Partial<OptionGroup> = {},
): OptionGroup {
  return {
    option_group_id,
    name_en: option_group_id,
    name_ko: option_group_id,
    description: "",
    required: true,
    min_select: 1,
    max_select: 1,
    items,
    ...overrides,
  };
}

describe("order-flow option logic", () => {
  it("keeps obvious animal dishes out of vegan same-restaurant browsing", () => {
    const menu = (name_ko: string, name_en: string): MenuSummary => ({
      menu_id: name_ko,
      merchant_id: "merchant-1",
      merchant_name: "merchant",
      name_en,
      name_ko,
      category: "demo",
      description: "",
      cultural_description: "",
      price: 10_000,
      delivery_fee: 0,
      eta_min: 10,
      eta_max: 20,
      spice_level: 1,
      serves_min: 1,
      serves_max: 1,
      dietary_summary: "",
      evidence_status: "UNKNOWN",
      match_reasons: [],
      risk_hints: [],
      evidence_ids: [],
      grounded_claim_ids: [],
      grounded_passage_ids: [],
      is_synthetic: false,
    });

    expect(menuHasObviousVeganConflict(menu("타코와사비", "Tako wasabi"))).toBe(true);
    expect(menuHasObviousVeganConflict(menu("새우계란볶음밥", "Shrimp egg fried rice"))).toBe(true);
    expect(menuHasObviousVeganConflict(menu("바지락생면칼국수", "Fresh clam kalguksu"))).toBe(true);
    expect(menuHasObviousVeganConflict(menu("가지버섯덮밥", "Eggplant mushroom rice bowl"))).toBe(false);
  });

  it("keeps option toggles within the group maximum", () => {
    const multiple = group("sides", [option("a"), option("b"), option("c")], {
      min_select: 0,
      max_select: 2,
    });

    expect(toggledOptionSelection(multiple, ["a"], "b")).toEqual(["a", "b"]);
    expect(toggledOptionSelection(multiple, ["a", "b"], "c")).toEqual(["a", "b"]);
    expect(toggledOptionSelection(multiple, ["a", "b"], "a")).toEqual(["b"]);
  });

  it("plans every default before applying updates and reports an unsatisfied group", () => {
    const optional = group("optional", [option("none", { name_en: "None" })], {
      required: false,
      min_select: 0,
    });
    const blocked = group("required", [
      option("pork", { halal_certification_preserved: false }),
    ]);

    const plan = planDefaultOptionSelections(
      [optional, blocked],
      {},
      0,
      { halal_certified_only: true, vegan: false },
    );

    expect(plan.missingRequiredGroup?.option_group_id).toBe("required");
    expect(plan.selections.optional).toEqual([]);
    expect(optionDietaryConflicts(blocked.items[0], {
      halal_certified_only: true,
      vegan: false,
    }).breaksHalal).toBe(true);
  });

  it("chooses available safe defaults and computes their price delta", () => {
    const required = group("size", [
      option("sold-out", { available: false, price_delta: 500 }),
      option("large", { price_delta: 1_000 }),
    ]);
    const plan = planDefaultOptionSelections([required], {}, 0);

    expect(plan.missingRequiredGroup).toBeNull();
    expect(plan.updates).toEqual([{ optionGroupId: "size", optionItemIds: ["large"] }]);
    expect(selectedOptionsPriceDelta([required], plan.selections)).toBe(1_000);
  });

  it("repairs an empty or stale required selection before advancing", () => {
    const required = group("size", [
      option("sold-out", { available: false }),
      option("regular"),
    ]);
    const plan = planDefaultOptionSelections(
      [required],
      { size: ["sold-out"] },
      0,
    );

    expect(plan.missingRequiredGroup).toBeNull();
    expect(plan.selections.size).toEqual(["regular"]);
    expect(plan.updates).toEqual([{ optionGroupId: "size", optionItemIds: ["regular"] }]);
  });

  it("recognizes source-provided none choices", () => {
    expect(optionGroupHasNoneChoice(group("sauce", [option("skip", {
      name_en: "No option",
    })]))).toBe(true);
  });
});
