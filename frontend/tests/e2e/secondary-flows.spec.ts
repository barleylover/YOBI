import { expect, test } from "@playwright/test";

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function startSession(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Get started!" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Check delivery address" }).click();
  await page.getByRole("button", { name: "Confirm & start" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
}

test("abstract request becomes a grounded constrained shortlist", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);
  await page.getByLabel("Ask YOBI").fill(
    "Something warm and mild after walking in the rain. No pork and under 15,000 won.",
  );
  await page.getByRole("button", { name: "Send message" }).click();
  const categoryCard = page.getByRole("region", { name: "Directions for your current needs" });
  const menuCard = page.getByRole("region", { name: "Grounded menu matches" });
  await expect(categoryCard.or(menuCard).first()).toBeVisible();
  if (await categoryCard.isVisible()) {
    const firstCategory = (await categoryCard.locator("article h4").first().innerText()).trim();
    expect(firstCategory).not.toBe("");
    await expect(page.getByRole("button", { name: `Recommend ${firstCategory}`, exact: true })).toBeVisible();
    await expect(categoryCard).toContainText("Under ₩15,000");
    await expect(categoryCard).toContainText("Maximum spice 1 of 3");
    await expect(categoryCard).toContainText("No pork");
    await page.getByText("Catalog sources").first().click();
    await expect(page.getByText(/Synthetic demo menu · \d+ catalog references/).first()).toBeVisible();
    await page.getByRole("button", { name: `Recommend ${firstCategory}`, exact: true }).click();
    await expect(menuCard).toBeVisible();
    await expect(menuCard.locator("article").first()).toContainText(
      new RegExp(escapeRegExp(firstCategory), "i"),
    );
  } else {
    await expect(menuCard.locator("article").first()).toBeVisible();
    await expect(menuCard.getByText(/₩\d{1,3}(?:,\d{3})*/).first()).toBeVisible();
  }
});

test("direct chicken kalguksu question returns grounded Wiki explanation", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);
  await page.getByLabel("Ask YOBI").fill("Tell me about chicken kalguksu.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("heading", { name: "What Chicken kalguksu is like" })).toBeVisible();
  await page.getByText("Evidence sources").click();
  await expect(page.getByText(/\d+ grounded references/).first()).toBeVisible();
});

test("merchant comparison uses shared trade-off axes", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  const conversationEvents: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "POST" || !request.url().endsWith("/events")) return;
    const payload = request.postDataJSON() as { event_type?: string };
    if (payload.event_type) conversationEvents.push(payload.event_type);
  });
  await startSession(page);
  await page.getByLabel("Ask YOBI").fill("Recommend a mild meal under 15,000 won.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("heading", { name: "Grounded menu matches" })).toBeVisible();
  await page.getByRole("button", { name: "Compare these" }).click();
  await expect(page.getByRole("heading", { name: "Compare the saved recommendations" })).toBeVisible();
  await expect(page.getByText("Flavour").first()).toBeVisible();
  await expect(page.getByText("Portion").first()).toBeVisible();
  await expect(page.getByText(/current constraints reapplied/)).toBeVisible();
  expect(conversationEvents).toContain("COMPARE_MENUS");
});

test("mock payment failure preserves checkout and permits safe retry", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);
  await page.getByRole("button", { name: "Try the demo question" }).click();
  await page.getByTestId("menu-menu_001_01").getByRole("button", { name: "Choose this menu" }).click();
  await page.getByRole("button", { name: /^Mild/ }).click();
  await page.getByRole("button", { name: /^Regular/ }).click();
  await page.getByRole("button", { name: /^Add cheese/ }).click();
  await page.getByRole("button", { name: /^Remove fish cake/ }).click();
  await page.getByRole("button", { name: "Add to cart" }).click();
  await page.getByRole("button", { name: "No, continue to delivery" }).click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();
  await page.getByRole("button", { name: "Proceed to payment" }).click();

  await page.getByRole("button", { name: "Simulate failure" }).click();
  await expect(page.getByText(/cart is unchanged/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Pay ₩15,900/ })).toBeEnabled();
  await page.getByRole("button", { name: /^Pay ₩15,900/ }).click();
  await expect(page).toHaveURL(/\/order\/YOBI-DEMO_/);
});
