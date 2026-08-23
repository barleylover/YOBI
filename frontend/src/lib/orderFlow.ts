import type { DietaryFiltersV2, OptionGroup, OptionItem } from "../types";

export interface OptionConflicts {
  breaksHalal: boolean;
  breaksVegan: boolean;
  needsVeganCheck: boolean;
}

export function optionDietaryConflicts(
  option: OptionItem,
  dietaryFilters?: DietaryFiltersV2,
): OptionConflicts {
  return {
    breaksHalal: Boolean(
      dietaryFilters?.halal_certified_only
      && option.halal_certification_preserved === false
    ),
    breaksVegan: Boolean(dietaryFilters?.vegan && option.vegan_status === "CONFLICT"),
    needsVeganCheck: Boolean(
      dietaryFilters?.vegan
      && option.vegan_status === "POSSIBLE_WITH_CHECKS"
    ),
  };
}

export function optionGroupHasNoneChoice(group: OptionGroup) {
  return group.items.some((option) => {
    const value = `${option.name_ko} ${option.name_en} ${option.display_name ?? ""}`
      .replace(/\s+/g, "")
      .toLowerCase();
    return ["선택안함", "미선택", "none", "nooption", "選択しない", "なし"]
      .some((token) => value.includes(token));
  });
}

export function toggledOptionSelection(
  group: OptionGroup,
  current: string[],
  optionId: string,
) {
  if (group.max_select === 1) return [optionId];
  if (current.includes(optionId)) return current.filter((value) => value !== optionId);
  if (current.length >= group.max_select) return current;
  return [...current, optionId];
}

export function selectedOptionsPriceDelta(
  groups: OptionGroup[],
  selections: Record<string, string[]>,
) {
  return groups.reduce((total, group) => {
    const optionIds = new Set(selections[group.option_group_id] ?? []);
    return total + group.items.reduce(
      (subtotal, option) => subtotal + (
        optionIds.has(option.option_item_id) ? option.price_delta : 0
      ),
      0,
    );
  }, 0);
}

interface DefaultOptionUpdate {
  optionGroupId: string;
  optionItemIds: string[];
}

export interface DefaultOptionPlan {
  selections: Record<string, string[]>;
  updates: DefaultOptionUpdate[];
  missingRequiredGroup: OptionGroup | null;
}

export function planDefaultOptionSelections(
  groups: OptionGroup[],
  selections: Record<string, string[]>,
  startIndex: number,
  dietaryFilters?: DietaryFiltersV2,
): DefaultOptionPlan {
  const next = Object.fromEntries(
    Object.entries(selections).map(([groupId, optionIds]) => [groupId, [...optionIds]]),
  );
  const updates: DefaultOptionUpdate[] = [];
  for (let index = startIndex; index < groups.length; index += 1) {
    const group = groups[index];
    const current = next[group.option_group_id];
    const currentIsValid = current !== undefined
      && current.length >= group.min_select
      && current.length <= group.max_select
      && current.every((optionId) => {
        const option = group.items.find((item) => item.option_item_id === optionId);
        if (!option?.available) return false;
        const { breaksHalal, breaksVegan } = optionDietaryConflicts(option, dietaryFilters);
        return !breaksHalal && !breaksVegan;
      });
    if (currentIsValid) continue;
    if (group.min_select === 0) {
      next[group.option_group_id] = [];
      updates.push({ optionGroupId: group.option_group_id, optionItemIds: [] });
      continue;
    }
    const optionIds = group.items
      .filter((option) => {
        if (!option.available) return false;
        const { breaksHalal, breaksVegan } = optionDietaryConflicts(option, dietaryFilters);
        return !breaksHalal && !breaksVegan;
      })
      .slice(0, group.min_select)
      .map((option) => option.option_item_id);
    if (optionIds.length < group.min_select) {
      return { selections: next, updates, missingRequiredGroup: group };
    }
    next[group.option_group_id] = optionIds;
    updates.push({ optionGroupId: group.option_group_id, optionItemIds: optionIds });
  }
  return { selections: next, updates, missingRequiredGroup: null };
}
