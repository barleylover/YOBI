import { expect, test } from "@playwright/test";
import { selectFirstPricePreference, startStructuredSession } from "./structured-helpers";

test("structured draft survives profile editing without allergy or chat controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startStructuredSession(page);
  const firstChip = await selectFirstPricePreference(page);
  const label = (await firstChip.innerText()).trim();
  await page.locator(".yv2-preference-tabs [role='tab']").first().click();
  await page.getByRole("button", { name: "Edit choices", exact: true }).first().click();

  await expect(page).toHaveURL(/\/profile\?edit=1/);
  await expect(page.getByText("Current demo address")).toBeVisible();
  await expect(page.getByText(/Allerg/i)).toHaveCount(0);
  await expect(page.getByText(/Age range|Religion|Favourite comfort foods/i)).toHaveCount(0);
  await expect(page.getByRole("radio")).toHaveCount(0);
  await page.getByRole("button", { name: "Keep this address" }).click();

  await expect(page).toHaveURL(/\/chat\/session_/);
  await page.locator(".yv2-preference-tabs [role='tab']").nth(2).click();
  await expect(page.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("textbox")).toHaveCount(0);
});

test("Korean structured controls include localized filters and five KR/US levels", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startStructuredSession(page, true);

  await page.getByRole("tab", { name: /정확 조건/ }).click();
  await expect(page.getByRole("heading", { name: "정확 조건" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /할랄 인증 식당만 보기/ })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /비건 메뉴 찾기/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "한국 음식 기준" })).toBeVisible();
  await expect(page.locator(".spice-reference-choice")).toHaveCount(5);
  await page.getByRole("button", { name: "미국 음식 기준" }).click();
  await expect(page.locator(".spice-reference-choice")).toHaveCount(5);
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
