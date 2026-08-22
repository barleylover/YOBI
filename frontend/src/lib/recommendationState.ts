import type { MenuSummary } from "../types";

function canonicalizeJson(value: unknown, ancestors: WeakSet<object>): unknown {
  if (Array.isArray(value)) {
    if (ancestors.has(value)) throw new TypeError("CIRCULAR_JSON_VALUE");
    ancestors.add(value);
    const result = value.map((item) => canonicalizeJson(item, ancestors));
    ancestors.delete(value);
    return result;
  }
  if (!value || typeof value !== "object") return value;
  if (ancestors.has(value)) throw new TypeError("CIRCULAR_JSON_VALUE");
  ancestors.add(value);
  const record = value as Record<string, unknown>;
  const result = Object.fromEntries(
    Object.keys(record)
      .sort()
      .map((key) => [key, canonicalizeJson(record[key], ancestors)]),
  );
  ancestors.delete(value);
  return result;
}

export function recommendationCriteriaEqual(left: unknown, right: unknown) {
  try {
    return JSON.stringify(canonicalizeJson(left, new WeakSet()))
      === JSON.stringify(canonicalizeJson(right, new WeakSet()));
  } catch {
    return false;
  }
}

export function findMenuProjection(value: unknown, menuId: string): MenuSummary | null {
  const pending: unknown[] = [value];
  const visited = new WeakSet<object>();
  while (pending.length) {
    const current = pending.pop();
    if (!current || typeof current !== "object") continue;
    if (visited.has(current)) continue;
    visited.add(current);
    if (Array.isArray(current)) {
      for (let index = current.length - 1; index >= 0; index -= 1) {
        pending.push(current[index]);
      }
      continue;
    }
    const item = current as Record<string, unknown>;
    if (
      item.menu_id === menuId
      && typeof item.merchant_id === "string"
      && typeof item.name_en === "string"
    ) {
      return item as unknown as MenuSummary;
    }
    const nested = Object.values(item);
    for (let index = nested.length - 1; index >= 0; index -= 1) {
      pending.push(nested[index]);
    }
  }
  return null;
}
