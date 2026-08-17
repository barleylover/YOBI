import { describe, expect, it } from "vitest";
import { LANGUAGES } from "../src/lib/locale";
import { getProductCopy } from "../src/lib/productI18n";
import { getRecommendationCopy } from "../src/lib/recommendationI18n";
import { getDynamicCopy } from "../src/lib/i18n";

describe("new product-flow localization", () => {
  it("provides localized entry, address, recommendation, navigation and handoff copy for all supported languages", () => {
    const english = getProductCopy("English");

    for (const language of LANGUAGES.filter((item) => item !== "English")) {
      const copy = getProductCopy(language);
      const selector = getRecommendationCopy(language);
      expect(copy.entry.pitchTitle, `${language} entry`).not.toBe(english.entry.pitchTitle);
      expect(copy.entry.pitchTitle, `${language} entry is not the selector question`).not.toBe(selector.selectorTitle);
      expect(copy.entry.pitchDescription, `${language} entry description is not selector help`).not.toBe(selector.selectorDescription);
      expect(copy.entry.benefitFlavor, `${language} flavor benefit is not result rationale`).not.toBe(selector.matchedPreferences);
      expect(copy.entry.benefitDietary, `${language} dietary benefit is not a field label`).not.toBe(selector.dietaryTitle);
      expect(copy.address.title, `${language} address`).not.toBe(english.address.title);
      expect(copy.address.select, `${language} address action is not a menu action`).not.toBe(selector.chooseMenu);
      expect(copy.address.demoNotice, `${language} address notice is not the general experience notice`).not.toBe(selector.experienceNotice);
      expect(copy.address.demoNotice, `${language} address notice identifies the demo`).toMatch(/데모|デモ|演示|示範|demo|démo|เดโม|تجريبي|डेमो|демо/i);
      expect(copy.recommendation.ready, `${language} recommendation`).not.toBe(english.recommendation.ready);
      expect(copy.navigation.foodRankings, `${language} navigation`).not.toBe(english.navigation.foodRankings);
      expect(copy.handoff.title, `${language} handoff`).not.toBe(english.handoff.title);
      expect(copy.handoff.boundary, `${language} mock boundary`).not.toBe(english.handoff.boundary);
    }
  });

  it("uses Japanese throughout the new flow without an English product fallback", () => {
    const copy = getProductCopy("日本語");
    expect(copy.entry.start).toBe("始める");
    expect(copy.address.search).toBe("検索");
    expect(copy.recommendation.cardPosition(1, 3)).toBe("メニュー 1/3");
    expect(copy.navigation.foodRankings).toBe("料理ランキング");
    expect(copy.handoff.boundary).toContain("決済、注文作成は行っていません");
  });

  it("uses Arabic throughout the new flow, including the truthful terminal boundary", () => {
    const copy = getProductCopy("العربية");
    expect(copy.entry.start).toBe("ابدأ");
    expect(copy.entry.pitchTitle).toBe("اختر الطعام الكوري بمعلومات واضحة، لا بالتخمين.");
    expect(copy.entry.benefitFlavor).toBe("تعرّف على النكهة والقوام");
    expect(copy.address.search).toBe("بحث");
    expect(copy.address.select).toBe("اختيار هذا العنوان");
    expect(copy.address.demoNotice).toContain("عنوان ثابت مُعدّ مسبقًا");
    expect(copy.recommendation.previewCount(228, 27)).toBe("تطابق الشروط حاليًا 228 وجبة من 27 مطعمًا");
    expect(copy.recommendation.previewCount(228, 27)).not.toMatch(/menus|restaurants|selected/i);
    expect(copy.recommendation.cardPosition(1, 3)).toBe("الوجبة 1/3");
    expect(copy.navigation.foodRankings).toBe("ترتيب الأطعمة");
    expect(copy.handoff.boundary).toContain("لم تُرسل السلة");
  });

  it("uses one semantic eligible-menu status in Korean without English units", () => {
    const copy = getProductCopy("한국어");
    expect(copy.recommendation.previewCount(228, 27)).toBe("현재 27개 가게의 메뉴 228개가 조건에 맞아요");
    expect(copy.recommendation.previewCount(228, 27)).not.toMatch(/menus|restaurants|selected/i);
  });

  it("keeps Korean and Arabic catalog fallback copy source-neutral for external menus", () => {
    const korean = getDynamicCopy("한국어");
    const arabic = getDynamicCopy("العربية");
    expect(`${korean.fallbackResult} ${korean.catalogDescription}`).not.toMatch(/합성|synthetic/i);
    expect(korean.catalogDescription).toContain("현재 카탈로그와 배달 조건");
    expect(`${arabic.fallbackResult} ${arabic.catalogDescription}`).not.toMatch(/اصطناعي|اصطناعية|synthetic/i);
    expect(arabic.catalogDescription).toContain("الكتالوج وشروط التوصيل الحالية");
  });
});
