import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferenceSelector } from "../src/components/PreferenceSelector";
import { PreferenceWizard } from "../src/components/PreferenceWizard";
import { normalizePreferenceCatalog } from "../src/lib/preferenceCatalog";
import { getRecommendationCopy } from "../src/lib/recommendationI18n";
import { getRedesignCopy } from "../src/lib/redesignI18n";
import { emptyCriteria } from "../src/stores/session";
import type { RecommendationCriteriaV2 } from "../src/types";

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
        { country_code: "US", spice_baseline: 2, representative_dish: "Buffalo wings" },
        { country_code: "JP", spice_baseline: 1, representative_dish: "Medium-spicy Japanese curry" },
      ],
      synthetic_enrichment_release_id: "synthetic-release-v1",
    }, "en");

    expect(catalog.schema_version).toBe("3");
    expect(catalog.price_range_krw).toEqual({ min: 4_000, max: 50_000, step: 1_000 });
    expect(catalog.country_spice_profiles).toEqual([
      { country_code: "US", spice_baseline: 2, representative_dish: "Buffalo wings" },
      { country_code: "JP", spice_baseline: 1, representative_dish: "Medium-spicy Japanese curry" },
    ]);
    expect(catalog.synthetic_enrichment_release_id).toBe("synthetic-release-v1");
  });

  it("shows the live preview, consistent three-step progress, spice anchors, and edit cancel", () => {
    const catalog = normalizePreferenceCatalog({
      ...rawCatalog("en"),
      schema_version: "3",
      price_range_krw: { min: 4_000, max: 62_000, step: 1_000 },
      country_spice_profiles: [{
        country_code: "US",
        spice_baseline: 2,
        representative_dish: "Buffalo wings",
        spice_scale_anchors: [
          {
            level: 2,
            familiar_dish: "Pepperoncini-topped pizza",
            korean_dish: "Mild kimchi fried rice",
            approximate_shu: 300,
            approximate_shu_min: 100,
            approximate_shu_max: 500,
          },
          {
            level: 4,
            familiar_dish: "Jalapeño poppers",
            korean_dish: "Tteokbokki",
            approximate_shu: 5_250,
            approximate_shu_min: 2_500,
            approximate_shu_max: 8_000,
          },
        ],
      }],
    }, "en");
    const onCancel = vi.fn();
    const onChange = vi.fn();
    const criteria: RecommendationCriteriaV2 = {
      ...emptyCriteria(),
      cuisine_origins: ["KOREAN"],
      spice_reference_country: "US",
    };

    const { container } = render(
      <PreferenceWizard
        catalog={catalog}
        criteria={criteria}
        copy={getRecommendationCopy("English")}
        v2={getRedesignCopy("English")}
        initialSection="conditions"
        preview={{
          eligible_menu_count: 12,
          eligible_merchant_count: 4,
          zero_reason_codes: [],
          release_id: "release-preview",
          support_manifest_sha256: "a".repeat(64),
          ranking_policy_version: "ranking-v1",
          timing_ms: 4,
        }}
        conflictMessage="Conflict"
        onChange={onChange}
        onComplete={vi.fn()}
        onBack={vi.fn()}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByText("Step 2 of 3 · Preferences")).toBeInTheDocument();
    expect(container.querySelectorAll(".v2-progress > span")).toHaveLength(3);
    expect(container.querySelectorAll(".v2-progress > span.active")).toHaveLength(2);
    expect(screen.getByText("12 dishes from 4 restaurants currently fit")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Maximum price" })).toHaveAttribute("max", "50000");
    expect(screen.getByText(/Level 2: Pepperoncini-topped pizza.*100–500 SHU/)).toBeInTheDocument();
    expect(screen.getByText(/Level 4: Jalapeño poppers.*2,500–8,000 SHU/)).toBeInTheDocument();
    expect(screen.getByText("Any spice · levels 1–5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preferred spice level 2/5" }));
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Preferred spice level 4/5" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      spice_range: { min: 2, max: 4 },
    }));
    fireEvent.click(screen.getByRole("button", { name: "Preferred spice level 1/5" }));
    fireEvent.click(screen.getByRole("button", { name: "Preferred spice level 1/5" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      spice_range: { min: 1, max: 1 },
    }));
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel changes" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
