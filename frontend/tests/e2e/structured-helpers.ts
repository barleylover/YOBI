import { expect, type Page } from "@playwright/test";

export type JourneyLanguage = "English" | "한국어" | "日本語";

const labels = {
  English: {
    languageButton: /Language.*English/,
    languageChoice: /English.*English/,
    start: "Get started",
    search: "Search",
    continueAddress: "Continue with this address",
    craving: "What are you craving?",
    next: "Next",
    find: "Find my dish",
    choose: "Choose this menu",
  },
  "한국어": {
    languageButton: /Language.*English/,
    languageChoice: /한국어.*Korean/,
    start: "시작하기",
    search: "검색",
    continueAddress: "이 주소로 계속하기",
    craving: "어떤 음식이 당기세요?",
    next: "다음",
    find: "내 메뉴 찾기",
    choose: "이 메뉴 선택",
  },
  "日本語": {
    languageButton: /Language.*English/,
    languageChoice: /日本語.*Japanese/,
    start: "始める",
    search: "検索",
    continueAddress: "この住所で続ける",
    craving: "どんな料理が食べたいですか？",
    next: "次へ",
    find: "料理を探す",
    choose: "このメニューを選ぶ",
  },
} as const;

function normalizeLanguage(language: boolean | JourneyLanguage): JourneyLanguage {
  return language === true ? "한국어" : language === false ? "English" : language;
}

export async function startStructuredSession(
  page: Page,
  language: boolean | JourneyLanguage = "English",
) {
  const selectedLanguage = normalizeLanguage(language);
  const copy = labels[selectedLanguage];
  await page.goto("/");
  if (selectedLanguage !== "English") {
    await page.getByRole("button", { name: copy.languageButton }).click();
    await page.getByRole("button", { name: copy.languageChoice }).click();
    await page.locator(".v2-appbar-action").click();
  }
  await page.getByRole("button", { name: copy.start, exact: true }).click();
  await expect(page).toHaveURL(/\/profile/);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: copy.search, exact: true }).click();
  await page.getByRole("button", { name: copy.continueAddress, exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByRole("heading", { name: copy.craving })).toBeVisible();
  return copy;
}

export async function selectFirstPricePreference(page: Page) {
  const firstChip = page.locator(".v2-wizard-body .v2-chip:visible").first();
  await expect(firstChip).toBeVisible();
  await firstChip.click();
  await expect(firstChip).toHaveAttribute("aria-pressed", "true");
  return firstChip;
}

export async function selectFirstPreferenceAndRecommend(
  page: Page,
  language: boolean | JourneyLanguage = "English",
) {
  const selectedLanguage = normalizeLanguage(language);
  const copy = labels[selectedLanguage];
  await selectFirstPricePreference(page);
  await page.getByRole("button", { name: copy.next, exact: true }).click();
  await page.getByRole("button", { name: copy.next, exact: true }).click();
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST" && response.url().endsWith("/recommendations")
  ));
  await page.getByRole("button", { name: copy.find, exact: true }).click();
  expect((await responsePromise).ok()).toBe(true);
  await expect(page.getByRole("button", { name: copy.choose, exact: true }).first()).toBeVisible({ timeout: 30_000 });
}

export async function completeCurrentOptions(page: Page, addToCartLabel = "Add to cart") {
  const optionGroup = page.locator("[data-testid^='option-group-']:visible").first();
  if (await optionGroup.isVisible().catch(() => false)) {
    await page.getByRole("button", { name: /Use defaults for the rest|나머지는 기본값 사용|残りは標準設定/ }).click();
  }
  const note = page.locator("textarea.v2-note-input");
  await expect(note).toBeVisible();
  await note.fill("");
  await expect(page.getByRole("button", { name: addToCartLabel, exact: true })).toBeEnabled();
  await page.getByRole("button", { name: addToCartLabel, exact: true }).click();
}
