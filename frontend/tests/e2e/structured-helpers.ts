import { expect, type Page } from "@playwright/test";

export async function startStructuredSession(page: Page, korean = false) {
  await page.goto(korean ? "/start" : "/");
  if (korean) {
    await page.locator("select").first().selectOption({ label: "한국어" });
    await page.locator("select").nth(1).selectOption({ label: "South Korea" });
  } else {
    await expect(page.getByRole("heading", { name: /Hi, I’m YOBI/ })).toBeVisible();
    await page.getByRole("button", { name: "Get started!" }).click();
  }
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: korean ? /합성 데모 프로필/ : /I agree/ }).check();
  await page.getByRole("button", { name: korean ? "배달 주소 확인" : "Check delivery address" }).click();
  await page.getByRole("button", { name: korean ? "확인하고 시작" : "Confirm & start" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByRole("heading", { name: korean ? "어떤 음식이 끌리세요?" : "What sounds good?" })).toBeVisible();
}

export async function selectFirstPreferenceAndRecommend(page: Page, korean = false) {
  const firstChip = page.locator(".preference-chip:visible").first();
  await expect(firstChip).toBeVisible();
  await firstChip.click();
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST" && response.url().endsWith("/recommendations")
  ));
  await page.getByRole("button", { name: korean ? "추천 메뉴 보기" : "Show my recommendations" }).click();
  expect((await responsePromise).ok()).toBe(true);
  await expect(page.getByRole("button", { name: korean ? "이 메뉴 선택" : "Choose this menu" }).first()).toBeVisible();
}

export async function completeCurrentOptions(page: Page, addToCartLabel = "Add to cart") {
  await expect(page.locator("[data-testid^='option-group-']").first()).toBeVisible();
  for (let index = 0; index < 10; index += 1) {
    const optionGroup = page.locator("[data-testid^='option-group-']:visible").first();
    if (!(await optionGroup.isVisible().catch(() => false))) break;
    const groupTestId = await optionGroup.getAttribute("data-testid");
    const availableOption = optionGroup.locator("button.option-button:enabled").first();
    await expect(availableOption).toBeVisible();
    await availableOption.click();
    await expect(page.locator(`[data-testid="${groupTestId}"]`)).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: addToCartLabel })).toBeVisible();
  await page.getByRole("button", { name: addToCartLabel }).click();
}
