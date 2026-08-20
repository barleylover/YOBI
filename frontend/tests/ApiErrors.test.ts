import { describe, expect, it } from "vitest";
import { actionableError } from "../src/lib/api";

describe("localized API errors", () => {
  it("maps the same server code in Korean, English, and Japanese", () => {
    const cause = new Error("RESTAURANT_NOTE_TRANSLATION_REQUIRED");

    expect(actionableError(cause, "fallback", "English")).toContain("Translate");
    expect(actionableError(cause, "fallback", "한국어")).toContain("번역");
    expect(actionableError(cause, "fallback", "日本語")).toContain("翻訳");
  });

  it("uses English for every other selectable language", () => {
    const cause = new Error("CART_MENU_UNAVAILABLE");

    expect(actionableError(cause, "fallback", "العربية"))
      .toBe(actionableError(cause, "fallback", "English"));
  });

  it("keeps the caller fallback for an unknown code", () => {
    expect(actionableError(new Error("UNKNOWN_CODE"), "localized fallback", "日本語"))
      .toBe("localized fallback");
  });
});
