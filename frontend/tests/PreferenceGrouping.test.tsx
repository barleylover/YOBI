import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferenceSelector } from "../src/components/PreferenceSelector";
import { getPreferenceGroupCopy } from "../src/lib/preferenceGroupI18n";
import { normalizePreferenceCatalog } from "../src/lib/preferenceCatalog";
import { getRecommendationCopy } from "../src/lib/recommendationI18n";
import { emptyCriteria } from "../src/stores/session";

const categoryGroups = {
  cuisine_origins: "core",
  main_ingredients: "core",
  food_forms: "core",
  flavors: "additional",
  textures: "additional",
  cooking_methods: "additional",
  temperatures: "additional",
  price_bands: "exact",
} as const;

function rawCatalog() {
  return {
    schema_version: "2",
    catalog_version: "grouped-catalog",
    knowledge_release_id: "grouped-release",
    locale: "en",
    categories: Object.entries(categoryGroups).map(([code, group]) => ({
      code,
      group,
      label: code,
      description: `${code} description`,
      options: [{ code: `${code.toUpperCase()}_OPTION`, label: `${code} option`, description: `${code} option meaning` }],
    })),
    spice_references: ["KR", "US"].map((country) => ({
      country,
      label: country,
      levels: [1, 2, 3, 4, 5].map((level) => ({ level, label: String(level), example: `Food ${level}` })),
    })),
  };
}

describe("preference category grouping and meaning guidance", () => {
  afterEach(cleanup);

  it("preserves backend category.group and renders price, dietary and spice under exact conditions", () => {
    const catalog = normalizePreferenceCatalog(rawCatalog(), "en");
    expect(catalog.categories.map(({ code, group }) => [code, group])).toEqual(
      Object.entries(categoryGroups),
    );

    const { container } = render(
      <PreferenceSelector
        catalog={catalog}
        criteria={emptyCriteria()}
        copy={getRecommendationCopy("English")}
        conflictMessage="Conflict"
        onChange={vi.fn()}
        onComplete={vi.fn()}
      />,
    );

    expect(screen.getByRole("tab", { name: /Core preferences/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/1–3 subjective choices/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Additional preferences/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Exact conditions/ }));
    expect(screen.getByRole("heading", { name: "Exact conditions" })).toBeInTheDocument();
    const exact = container.querySelector<HTMLElement>("[data-preference-group='exact']");
    expect(exact).not.toBeNull();
    expect(exact?.querySelector("[data-category='price_bands']")).not.toBeNull();
    expect(exact?.querySelector(".preference-dietary")).not.toBeNull();
    expect(exact?.querySelector(".preference-spice")).not.toBeNull();
  });

  it("explains flavor versus hard cap, ingredient versus dietary condition, and adjacent facets", () => {
    const catalog = normalizePreferenceCatalog(rawCatalog(), "en");
    render(
      <PreferenceSelector
        catalog={catalog}
        criteria={emptyCriteria()}
        copy={getRecommendationCopy("English")}
        conflictMessage="Conflict"
        onChange={vi.fn()}
        onComplete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /Exact conditions/ }));
    const guide = screen.getByText(/SPICY is a flavor you enjoy/);
    expect(guide).toHaveTextContent(/maximum spice is a hard cap/);
    expect(guide).toHaveTextContent(/VEGETABLE is a preferred main ingredient/);
    expect(guide).toHaveTextContent(/vegan is a dietary condition/);
    expect(guide).toHaveTextContent(/Temperature, texture and cooking method describe different facets/);
  });

  it("localizes the grouping and semantic guidance in Japanese and Arabic", () => {
    expect(getPreferenceGroupCopy("ja").core.help).toContain("1～3個");
    expect(getPreferenceGroupCopy("ja").semanticHelp).toContain("最大辛さは超えない上限");
    expect(getPreferenceGroupCopy("ar").core.title).toBe("التفضيلات الأساسية");
    expect(getPreferenceGroupCopy("ar").semanticHelp).toContain("الحد الأقصى للحِدّة");
  });
});
