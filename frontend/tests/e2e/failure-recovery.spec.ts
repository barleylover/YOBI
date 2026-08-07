import { expect, test } from "@playwright/test";

const configuredBaseUrl = process.env.YOBI_E2E_BASE_URL;
const configuredHost = configuredBaseUrl ? new URL(configuredBaseUrl).hostname : "";
const expectsProtectedControl = Boolean(
  configuredBaseUrl && !["127.0.0.1", "localhost", "::1"].includes(configuredHost),
);

test("onboarding remains accessible at every required viewport", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Order K-food with context/ })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /I agree/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Check delivery address" })).toBeDisabled();
  await expect(page.getByLabel("Language").locator("option")).toHaveCount(16);
  await page.getByLabel("Language").selectOption("한국어");
  await expect(page.getByLabel("Country").locator("option").first()).toHaveText("South Korea");
  await expect(page.getByLabel("Gender")).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "Vegan" })).toBeVisible();
  await expect(page.getByLabel("Religion (optional)")).toBeVisible();
  await expect(page.getByRole("radio")).toHaveCount(3);
  await expect(page.getByRole("heading", { name: "Delivery address" })).toBeVisible();
  await page.goto("/demo/qr");
  await expect(page.getByRole("img", { name: /QR code for/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download presentation SVG" })).toBeVisible();
  await page.goto("/demo/control");
  await page.getByRole("button", { name: "Load safe status" }).click();
  if (expectsProtectedControl) {
    await expect(page.getByRole("status")).toHaveText(/Status is protected/);
  } else {
    await expect(page.getByText("demo-2026.08.06-v1")).toBeVisible();
    await expect(page.getByText("2026-08-06", { exact: true })).toBeVisible();
  }
});

test("dietary-risk option starts locked and explains how to proceed", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await page.goto("/");
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Check delivery address" }).click();
  await page.getByRole("button", { name: "Confirm & start" }).first().click();
  await page.getByRole("button", { name: "Try the demo question" }).click();
  await page.getByTestId("menu-menu_001_01").getByRole("button", { name: "Choose this menu" }).click();
  await page.getByRole("button", { name: /^Mild/ }).click();
  await page.getByRole("button", { name: /^Regular/ }).click();
  await page.getByRole("button", { name: /^Add cheese/ }).click();
  const riskyOption = page.getByRole("button", { name: /^Keep fish cake/ });
  await expect(riskyOption).toBeDisabled();
  await expect(page.getByText("Blocked for your dietary profile")).toBeVisible();
  await page.getByRole("button", { name: "Unlock option" }).click();
  await expect(riskyOption).toBeEnabled();
  await expect(page.getByText(/server checks still apply/i)).toBeVisible();
});
