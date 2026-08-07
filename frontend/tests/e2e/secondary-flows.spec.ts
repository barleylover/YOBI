import { expect, test } from "@playwright/test";

async function startSession(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Check delivery address" }).click();
  await page.getByRole("button", { name: "Confirm & start" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
}

test("abstract request becomes a grounded warm category shortlist", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);
  await page.getByLabel("Ask YOBI").fill(
    "Something warm and mild after walking in the rain. No pork and under 15,000 won.",
  );
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("heading", { name: "Warm, mild directions" })).toBeVisible();
  await expect(page.getByText("Chicken kalguksu", { exact: true })).toBeVisible();
  await expect(page.getByText("Under ₩15,000 · no pork · spice 1/5 or below")).toBeVisible();
  await page.getByText("Catalog sources").first().click();
  await expect(page.getByText(/menu_003_01/)).toBeVisible();
  await page.getByRole("button", { name: "Show me chicken kalguksu" }).click();
  await expect(page.getByRole("heading", { name: "What this dish will feel like" })).toBeVisible();
  await page.getByText("Evidence sources").click();
  await expect(page.getByText("ev_003_01_1 · ev_003_01_2", { exact: true })).toBeVisible();
});

test("merchant comparison uses shared trade-off axes", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);
  await page.getByRole("button", { name: "Try the demo question" }).click();
  await page.getByRole("button", { name: "Compare mild rose options" }).click();
  await expect(page.getByRole("heading", { name: "Rose tteokbokki comparison" })).toBeVisible();
  await expect(page.getByText("Flavour").first()).toBeVisible();
  await expect(page.getByText("Portion").first()).toBeVisible();
  await expect(page.getByText(/Synthetic restaurants/)).toBeVisible();
});

test("mock payment failure preserves checkout and permits safe retry", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);
  await page.getByRole("button", { name: "Try the demo question" }).click();
  await page.getByRole("button", { name: "Choose this menu" }).click();
  await page.getByRole("button", { name: /^Mild/ }).click();
  await page.getByRole("button", { name: /^Regular/ }).click();
  await page.getByRole("button", { name: /^Add cheese/ }).click();
  await page.getByRole("button", { name: /^Remove fish cake/ }).click();
  await page.getByRole("button", { name: "Add to mock cart" }).click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();
  await page.getByRole("button", { name: "Proceed to payment" }).click();

  await page.getByRole("button", { name: "Simulate failure" }).click();
  await expect(page.getByText(/cart is unchanged/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Pay ₩15,900/ })).toBeEnabled();
  await page.getByRole("button", { name: /^Pay ₩15,900/ }).click();
  await expect(page).toHaveURL(/\/order\/YOBI-DEMO_/);
});
