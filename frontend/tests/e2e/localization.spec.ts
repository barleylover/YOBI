import { expect, test } from "@playwright/test";
import { selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

test("Korean remains active through structured recommendation and menu selection", async ({ page }) => {
  await startStructuredSession(page, true);
  await page.locator("details.preference-more-panel > summary").click();
  await expect(page.getByRole("checkbox", { name: /할랄 인증 식당만 보기/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "한국 음식 기준" })).toBeVisible();
  await selectFirstPreferenceAndRecommend(page, true);

  await expect(page.locator(".recommendation-result-heading")).toBeVisible();
  await expect(page.getByRole("button", { name: "다른 메뉴 보기" })).toBeVisible();
  await expect(page.getByRole("button", { name: "조건 수정" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Wiki 근거 보기" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Wiki 근거 보기" }).first().click();
  await expect(page.locator(".structured-evidence").first()).toBeVisible();
  await page.getByRole("button", { name: "이 메뉴 선택" }).first().click();
  await expect(page.getByTestId("order-flow")).toBeVisible();
  await expect(page.getByText(/알레르기/)).toHaveCount(0);
});
