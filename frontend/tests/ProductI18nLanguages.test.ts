import { describe, expect, it } from "vitest";
import {
  LANGUAGES,
  asEffectiveLanguage,
  effectiveLanguageMeta,
  travelerOptionLabel,
} from "../src/lib/locale";
import { getProductCopy } from "../src/lib/productI18n";
import { getRecommendationCopy } from "../src/lib/recommendationI18n";
import { getRedesignCopy } from "../src/lib/redesignI18n";
import { getDynamicCopy } from "../src/lib/i18n";

const fallbackLanguages = LANGUAGES.filter((language) => !["English", "한국어", "日本語"].includes(language));

function stringValues(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (!value || typeof value !== "object") return [];
  return Object.values(value).flatMap(stringValues);
}

describe("product-flow localization", () => {
  it("keeps Korean, English, and Japanese as complete display languages", () => {
    const english = getProductCopy("English");
    const korean = getProductCopy("한국어");
    const japanese = getProductCopy("日本語");

    expect(english.entry.start).toBe("Get started");
    expect(korean.entry.start).toBe("시작하기");
    expect(japanese.entry.start).toBe("始める");
    expect(korean.address.title).not.toBe(english.address.title);
    expect(japanese.address.title).not.toBe(english.address.title);
    expect(korean.recommendation.ready).not.toBe(english.recommendation.ready);
    expect(japanese.handoff.boundary).toBe("カートを確認してYogiyoへ進んでください。");
  });

  it("falls every other selectable language back to English and LTR", () => {
    const englishProduct = getProductCopy("English");
    const englishRecommendation = getRecommendationCopy("English");
    const englishRedesign = getRedesignCopy("English");
    const englishDynamic = getDynamicCopy("English");

    for (const language of fallbackLanguages) {
      expect(asEffectiveLanguage(language), language).toBe("English");
      expect(effectiveLanguageMeta(language), language).toEqual({ code: "en", direction: "ltr" });
      expect(getProductCopy(language).entry, language).toEqual(englishProduct.entry);
      expect(getProductCopy(language).address.title, language).toBe(englishProduct.address.title);
      expect(getRecommendationCopy(language).selectorTitle, language).toBe(englishRecommendation.selectorTitle);
      expect(getRedesignCopy(language).findMyDish, language).toBe(englishRedesign.findMyDish);
      expect(getDynamicCopy(language).catalogDescription, language).toBe(englishDynamic.catalogDescription);
    }
  });

  it("contains no user-visible demo, mock, or synthetic wording in the three display languages", () => {
    for (const language of ["English", "한국어", "日本語"] as const) {
      const product = getProductCopy(language);
      const recommendation = getRecommendationCopy(language);
      const redesign = getRedesignCopy(language);
      const visibleCopy = [
        ...stringValues(product),
        ...stringValues(recommendation),
        ...stringValues(redesign),
        product.recommendation.previewCount(228, 27),
        product.recommendation.cardPosition(1, 3),
        redesign.liveCount(228, 27),
        redesign.prepareOrder("₩12,000"),
      ].join(" ");
      expect(visibleCopy.match(/\bdemo\b|\bmock\b|\bsynthetic\b|데모|목업|합성|デモ|モック|合成/i), language).toBeNull();
    }
  });

  it("turns common romanized option terms into traveler-friendly English", () => {
    expect(travelerOptionLabel("Gopbaegi Add-On", "English")).toBe("Portion size");
    expect(travelerOptionLabel("Add Gopbaegi", "English")).toBe("Extra-large portion (gopbaegi)");
    expect(travelerOptionLabel("No Gopbaegi", "English")).toBe("Regular portion");
    expect(travelerOptionLabel("nostalgic sausage jeon", "English")).toBe("Nostalgic sausage pancake (jeon)");
    expect(travelerOptionLabel("곱빼기 추가", "한국어")).toBe("곱빼기 추가");
  });
});
