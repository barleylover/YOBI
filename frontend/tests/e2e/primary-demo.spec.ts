import { expect, test } from "@playwright/test";

test("primary tourist order completes with evidence and no real charge", async ({ page }) => {
  const consoleErrors: string[] = [];
  const conversationEvents: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("request", (request) => {
    if (request.method() !== "POST" || !request.url().endsWith("/events")) return;
    const payload = request.postDataJSON() as { event_type?: string };
    if (payload.event_type) conversationEvents.push(payload.event_type);
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Hi, I’m YOBI/ })).toBeVisible();
  await page.getByRole("button", { name: "Get started!" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Check delivery address" }).click();
  await expect(page.getByText("YOBI Myeongdong Hotel")).toBeVisible();
  await page.getByRole("button", { name: "Confirm & start" }).first().click();

  await expect(page).toHaveURL(/\/chat\/session_/);
  await page.getByRole("button", { name: "Try the demo question" }).click();
  await expect(
    page
      .getByRole("heading", { name: "Why the classic version does not fit" })
      .or(page.getByRole("heading", { name: "Dietary evidence" }))
      .or(page.getByRole("heading", { name: "Grounded menu matches" }))
      .first(),
  ).toBeVisible();
  await expect(page.getByText("Cross-contamination is not verified").first()).toBeVisible();
  await page.getByTestId("menu-menu_001_01").getByRole("button", { name: "Choose this menu" }).click();

  await page.getByRole("button", { name: /^Mild/ }).click();
  await page.getByRole("button", { name: /^Regular/ }).click();
  await page.getByRole("button", { name: /^Add cheese/ }).click();
  await page.getByRole("button", { name: /^Remove fish cake/ }).click();
  await page.getByRole("button", { name: "Add to cart" }).click();
  await expect(page.getByRole("button", { name: "Yes, show more menus" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Open cart, 1 items/ })).toBeVisible();
  await page.getByRole("button", { name: "Yes, show more menus" }).click();
  await expect(page.getByRole("heading", { name: /More from this restaurant/ })).toBeVisible();
  await page.getByTestId("order-flow").getByTestId("menu-menu_001_02").getByRole("button", { name: "Choose this menu" }).click();
  await page.getByRole("button", { name: /^Regular/ }).click();
  await page.getByRole("button", { name: /^No extra/ }).click();
  await page.getByRole("button", { name: "Add to cart" }).click();
  await expect(page.getByRole("button", { name: /Open cart, 2 items/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Yes, show more menus" })).toBeVisible();
  await page.getByRole("button", { name: "No, continue to delivery" }).click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();
  await page.getByRole("button", { name: "Increase quantity" }).first().click();
  await expect(page.getByRole("button", { name: /Open cart, 3 items/ })).toBeVisible();
  await page.getByRole("button", { name: "Decrease quantity" }).first().click();
  await expect(page.getByRole("button", { name: /Open cart, 2 items/ })).toBeVisible();
  await expect(page.getByText("₩24,900", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Proceed to payment" }).click();
  await expect(page.getByText("Demo payment — no real charge")).toBeVisible();
  await page.getByRole("button", { name: /^Pay ₩24,900/ }).click();

  await expect(page).toHaveURL(/\/order\/YOBI-DEMO_/);
  await expect(page.getByRole("heading", { name: "Your first K-food order is in." })).toBeVisible();
  await expect(page.getByText(/no real restaurant or courier was contacted/i)).toBeVisible();
  expect(conversationEvents[0]).toBe("SELECT_MENU");
  expect(conversationEvents.filter((event) => event === "UPDATE_OPTIONS")).toHaveLength(4);
  expect(consoleErrors).toEqual([]);
});
