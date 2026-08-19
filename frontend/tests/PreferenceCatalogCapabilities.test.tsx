import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferenceSelector } from "../src/components/PreferenceSelector";
import { normalizePreferenceCatalog } from "../src/lib/preferenceCatalog";
import { getRecommendationCopy } from "../src/lib/recommendationI18n";
import { emptyCriteria } from "../src/stores/session";

function rawCatalog(locale: string) {
  return {
    schema_version: "2",
    catalog_version: "catalog-capability-test",
    knowledge_release_id: "knowledge-capability-test",
    locale,
    categories: [{
      code: "cuisine_origins",
      label: locale === "ko" ? "음식 계통" : "Cuisine",
      options: [{ code: "KOREAN", label: locale === "ko" ? "한식" : "Korean" }],
    }],
    spice_references: ["KR", "US"].map((country) => ({
      country,
      label: country,
      levels: [1, 2, 3, 4, 5].map((level) => ({ level, label: String(level), example: `Food ${level}` })),
    })),
    capabilities: {
      halal_certified_only: {
        enabled: false,
        disabled_reason: "No verifiable formal certification coverage is available.",
      },
      vegan: {
        enabled: false,
        disabled_reason: "Reviewed menu-level ingredient coverage is unavailable.",
      },
      max_spice_level: {
        enabled: false,
        disabled_reason: "Reviewed menu-level spice values are unavailable.",
      },
    },
  };
}

describe("catalog capability contract", () => {
  afterEach(cleanup);

  it("normalizes backend disabled_reason and displays it for English users", () => {
    const catalog = normalizePreferenceCatalog(rawCatalog("en"), "en");
    expect(catalog.capabilities?.halal_certified_only).toEqual({
      enabled: false,
      reason: "No verifiable formal certification coverage is available.",
    });

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
    expect(screen.getByRole("checkbox", { name: /No verifiable formal certification coverage/ })).toBeDisabled();
    expect(screen.getByText("Reviewed menu-level spice values are unavailable.")).toBeInTheDocument();
  });

  it("uses localized unavailability copy instead of leaking English reasons into Korean UI", () => {
    const catalog = normalizePreferenceCatalog(rawCatalog("ko"), "ko");
    const onChange = vi.fn();
    render(
      <PreferenceSelector
        catalog={catalog}
        criteria={{ ...emptyCriteria(), spice_reference_country: "KR" }}
        copy={getRecommendationCopy("한국어")}
        conflictMessage="충돌"
        onChange={onChange}
        onComplete={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /검증 가능한 공식 인증 정보가 없어/ })).toBeDisabled();
    expect(screen.getByText("검토된 메뉴별 맵기 정보가 없어 현재 사용할 수 없습니다.")).toBeInTheDocument();
    expect(screen.queryByText(/No verifiable formal certification/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "한국 음식 기준" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "미국 음식 기준" })).toBeEnabled();
    screen.getByRole("button", { name: "미국 음식 기준" }).click();
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ spice_reference_country: "US" }));
  });

  it("preserves the v3 price range, country baselines, and enrichment identity", () => {
    const catalog = normalizePreferenceCatalog({
      ...rawCatalog("en"),
      schema_version: "3",
      price_range_krw: { min: 4_000, max: 62_000, step: 1_000 },
      country_spice_profiles: [
        { country_code: "US", spice_baseline: 2 },
        { country_code: "JP", spice_baseline: 1 },
      ],
      synthetic_enrichment_release_id: "synthetic-release-v1",
    }, "en");

    expect(catalog.schema_version).toBe("3");
    expect(catalog.price_range_krw).toEqual({ min: 4_000, max: 62_000, step: 1_000 });
    expect(catalog.country_spice_profiles).toEqual([
      { country_code: "US", spice_baseline: 2 },
      { country_code: "JP", spice_baseline: 1 },
    ]);
    expect(catalog.synthetic_enrichment_release_id).toBe("synthetic-release-v1");
  });
});
