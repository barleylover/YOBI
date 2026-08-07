import { expect, test } from "@playwright/test";

async function startSession(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Get started!" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Check delivery address" }).click();
  await page.getByRole("button", { name: "Confirm & start" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
}

test("chat menu shows fixed collections and preserves them through profile editing", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);

  await expect(page.getByText("Your delivery context is ready")).toHaveCount(0);
  const welcome = page.locator("article.message.assistant").filter({ hasText: "Hi, I’m YOBI" });
  await expect(welcome.getByRole("button", { name: "Try the demo question" })).toBeVisible();
  await expect(page.locator(".composer").getByRole("button", { name: "Try the demo question" })).toHaveCount(0);
  await expect(page.locator(".chat-room-menu-toggle svg")).toHaveClass(/lucide-chevron-up/);
  await page.getByRole("button", { name: "Chat menu" }).click();
  await expect(page.getByRole("button", { name: "Weekly ranking" })).toBeVisible();
  await page.getByRole("button", { name: "Weekly ranking" }).click();
  await expect(page.getByText("Here is this week's delivery ranking.")).toBeVisible();
  await expect(page.getByTestId("preset-weekly_ranking")).toBeVisible();
  await expect(page.getByText("BBQ", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next menu" }).click();
  await expect(page.getByText("BHC", { exact: true })).toBeVisible();
  await page.getByTestId("preset-menu-menu_022_01").getByRole("button", { name: "Choose this menu" }).click();
  await page.getByRole("button", { name: /^Regular/ }).click();
  await page.getByRole("button", { name: /^No extra/ }).click();
  await page.getByRole("button", { name: "Add to cart" }).click();
  await page.getByRole("button", { name: "No, continue to delivery" }).click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();
  await expect(page.getByTestId("cart-review")).toBeVisible();

  await page.getByRole("button", { name: "Chat menu" }).click();
  await page.getByRole("button", { name: "Edit my information" }).click();
  await expect(page).toHaveURL(/\/profile\?edit=1/);
  await expect(page.getByText("Current delivery address")).toBeVisible();
  await page.getByRole("checkbox", { name: "Milk" }).check();
  await page.getByRole("radio", { name: "I came to Korea for the spice" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByTestId("preset-weekly_ranking")).toBeVisible();
  await expect(page.locator(".session-brief")).toHaveCount(0);
  await expect(page.getByTestId("cart-review")).toBeVisible();
  await expect(page.getByText(/Remove Cheese-seasoned fried chicken to continue/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Proceed to payment" })).toBeDisabled();

  await page.getByRole("button", { name: "Chat menu" }).click();
  await page.getByRole("button", { name: "K-POP Demon Hunters" }).click();
  await expect(page.getByTestId("preset-kpop_demon_hunters")).toBeVisible();
  await expect(page.getByText("Gimbap", { exact: true })).toBeVisible();
});

test("Korean chat menu labels and preset response are localized", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await page.goto("/start");
  await page.locator("select").first().selectOption({ label: "한국어" });
  await page.locator("select").nth(1).selectOption({ label: "South Korea" });
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: /합성 데모 프로필/ }).check();
  await page.getByRole("button", { name: "배달 주소 확인" }).click();
  await page.getByRole("button", { name: "확인하고 시작" }).first().click();

  await page.getByRole("button", { name: "채팅방 메뉴" }).click();
  await expect(page.getByRole("button", { name: "금주의 순위" })).toBeVisible();
  await expect(page.getByRole("button", { name: "K-POP 데몬 헌터스" })).toBeVisible();
  await expect(page.getByRole("button", { name: "내 정보 수정" })).toBeVisible();
  await page.getByRole("button", { name: "금주의 순위" }).click();
  await expect(page.getByText("이번 주 배달 메뉴 순위예요.")).toBeVisible();
  await expect(page.getByTestId("preset-weekly_ranking")).toBeVisible();
});
