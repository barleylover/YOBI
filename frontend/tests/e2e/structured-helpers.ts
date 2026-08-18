import { expect, type Page } from "@playwright/test";

export async function startStructuredSession(page: Page, korean = false) {
  await page.goto("/");
  const languageSelect = page.locator(".yv2-entry-locales select").first();
  const countrySelect = page.locator(".yv2-entry-locales select").nth(1);
  await expect(languageSelect).toBeVisible();
  if (korean) {
    await languageSelect.selectOption({ label: "한국어" });
    await countrySelect.selectOption("South Korea");
    await page.getByRole("button", { name: "시작하기" }).click();
  } else {
    await expect(page.getByRole("heading", { name: /Hi, I’m YOBI/ })).toBeVisible();
    await page.getByRole("button", { name: "Get started!" }).click();
  }
  await expect(page).toHaveURL(/\/profile/);
  await page.getByRole("checkbox", { name: korean ? /중립 프로필/ : /neutral profile/ }).check();
  await page.getByRole("button", { name: korean ? "데모 주소 찾기" : "Find the demo address" }).click();
  await page.getByRole("button", { name: korean ? "이 주소 선택" : "Select this address" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByRole("heading", { name: korean ? "어떤 음식이 끌리세요?" : "What sounds good?" })).toBeVisible();
}

export async function selectFirstPricePreference(page: Page) {
  await page.locator(".yv2-preference-tabs [role='tab']").nth(2).click();
  const priceCategory = page.locator("[data-category='price_bands']");
  const firstChip = priceCategory.locator(".yv2-preference-chip").first();
  await expect(firstChip).toBeVisible();
  await firstChip.click();
  await expect(firstChip).toHaveAttribute("aria-pressed", "true");
  return firstChip;
}

export async function selectFirstPreferenceAndRecommend(page: Page, korean = false) {
  await selectFirstPricePreference(page);
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
