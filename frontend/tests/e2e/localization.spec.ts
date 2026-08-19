import { expect, test } from "@playwright/test";
import { selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

test("Korean remains active through recommendation, explanation and menu selection", async ({ page }) => {
  await startStructuredSession(page, "한국어");
  await selectFirstPreferenceAndRecommend(page, "한국어");

  await expect(page.getByRole("button", { name: "추가 설명 보기" }).first()).toBeVisible();
  await expect(page.getByText("YOBI:").first()).toBeVisible();
  await expect(page.getByText("요기요:").first()).toBeVisible();
  await page.getByRole("button", { name: "추가 설명 보기" }).first().click();
  await expect(page.getByRole("heading", { name: "추가 설명" })).toBeVisible();
  await expect(page.locator(".v2-preference-bar")).toBeVisible();
  await expect(page.getByText("리뷰 요약")).toBeVisible();
  await page.getByRole("button", { name: "확인", exact: true }).click();
  await page.getByRole("button", { name: "이 메뉴 선택" }).first().click();
  await expect(page.getByTestId("order-flow")).toBeVisible();
  await expect(page.getByText(/Allergy|Maximum spice|Compare these menus/)).toHaveCount(0);
});

test("Japanese remains active through recommendation and additional explanation", async ({ page }, testInfo) => {
  test.skip(
    !["iPhone 13", "desktop-1366"].includes(testInfo.project.name),
    "One mobile and one desktop Japanese proof are sufficient.",
  );
  await startStructuredSession(page, "日本語");
  await selectFirstPreferenceAndRecommend(page, "日本語");

  await expect(page.locator("html")).toHaveAttribute("lang", "ja");
  await expect(page.getByRole("button", { name: "詳しい説明を見る" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "このメニューを選ぶ" }).first()).toBeVisible();
  await page.getByRole("button", { name: "詳しい説明を見る" }).first().click();
  await expect(page.getByRole("heading", { name: "詳しい説明" })).toBeVisible();
  await expect(page.getByText("レビュー要約")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/Compare these menus|Maximum spice level|demo|mock|synthetic/i);
});
