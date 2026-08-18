import { expect, test } from "@playwright/test";
import { selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

test("Korean remains active through structured recommendation and menu selection", async ({ page }) => {
  await startStructuredSession(page, true);
  await page.getByRole("tab", { name: /정확 조건/ }).click();
  await expect(page.getByRole("checkbox", { name: /할랄 인증 식당만 보기/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "한국 음식 기준" })).toBeVisible();
  await selectFirstPreferenceAndRecommend(page, true);

  await expect(page.getByRole("heading", { name: /선택하신 취향을 바탕으로 골랐어요|조건에 가까운 메뉴/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "다른 메뉴 보기" })).toBeVisible();
  await expect(page.getByRole("button", { name: "조건 수정" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Wiki 근거 보기" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Wiki 근거 보기" }).first().click();
  const explanation = page.getByRole("dialog");
  await expect(explanation.locator(".structured-evidence").first()).toBeVisible();
  await explanation.locator(".yv2-primary-button").click();
  await page.getByRole("button", { name: "이 메뉴 선택" }).first().click();
  await expect(page.getByTestId("order-flow")).toBeVisible();
  await expect(page.getByText(/알레르기/)).toHaveCount(0);
});
