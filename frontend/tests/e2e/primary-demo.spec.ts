import { expect, test } from "@playwright/test";

test("primary tourist order completes with evidence and no real charge", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Order K-food with context/ })).toBeVisible();
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Start ordering" }).click();

  await expect(page).toHaveURL(/\/chat\/session_/);
  await page.getByRole("button", { name: "Try the demo question" }).click();
  await expect(page.getByRole("heading", { name: "Why I would avoid the classic version" })).toBeVisible();
  await expect(page.getByText("Cross-contamination is not verified")).toBeVisible();
  await page.getByRole("button", { name: "Choose this menu" }).click();

  await page.getByRole("button", { name: /^Mild/ }).click();
  await page.getByRole("button", { name: /^Regular/ }).click();
  await page.getByRole("button", { name: /^Add cheese/ }).click();
  await page.getByRole("button", { name: /^Remove fish cake/ }).click();
  await page.getByRole("button", { name: "Add to mock cart" }).click();
  await page.getByRole("button", { name: "Use stable demo booking image" }).click();
  await expect(page.getByText("YOBI Myeongdong Hotel")).toBeVisible();
  await page.getByRole("button", { name: "Confirm" }).first().click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();
  await expect(page.getByText("₩15,900", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Proceed to payment" }).click();
  await expect(page.getByText("Demo payment — no real charge")).toBeVisible();
  await page.getByRole("button", { name: /^Pay ₩15,900/ }).click();

  await expect(page).toHaveURL(/\/order\/YOBI-DEMO_/);
  await expect(page.getByRole("heading", { name: "Your first K-food order is in." })).toBeVisible();
  await expect(page.getByText(/no real restaurant or courier was contacted/i)).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

