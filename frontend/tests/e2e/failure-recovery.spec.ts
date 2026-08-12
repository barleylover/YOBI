import { expect, test } from "@playwright/test";

const configuredBaseUrl = process.env.YOBI_E2E_BASE_URL;
const configuredHost = configuredBaseUrl ? new URL(configuredBaseUrl).hostname : "";
const expectsProtectedControl = Boolean(
  configuredBaseUrl && !["127.0.0.1", "localhost", "::1"].includes(configuredHost),
);

test("onboarding and structured selector remain accessible at every required viewport", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Hi, I’m YOBI/ })).toBeVisible();
  await expect(page.locator("main")).toHaveCSS("overflow", "hidden");
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)).toBe(true);
  await page.getByRole("button", { name: "Get started!" }).click();
  await expect(page.getByLabel("Language").locator("option")).toHaveCount(16);
  await page.getByLabel("Language").selectOption("한국어");
  await expect(page.getByLabel("Country").locator("option").first()).toHaveText("South Korea");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByLabel("종교 (선택)")).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(1);
  await expect(page.getByRole("radio")).toHaveCount(0);
  await expect(page.getByText(/알레르기/)).toHaveCount(0);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "배달 주소 확인" }).click();
  await page.getByRole("button", { name: "확인하고 시작" }).first().click();

  await expect(page.getByRole("heading", { name: "어떤 음식이 끌리세요?" })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await expect(page.locator(".spice-reference-choice")).toHaveCount(5);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await page.goto("/demo/qr");
  await expect(page.getByRole("img", { name: /QR code for/ })).toBeVisible();
  await page.goto("/demo/control");
  const statusResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "GET" && response.url().endsWith("/api/v1/demo/status")
  ));
  await page.getByRole("button", { name: "Load safe status" }).click();
  const statusResponse = await statusResponsePromise;
  if (expectsProtectedControl) {
    await expect(page.getByRole("status")).toHaveText(/Status is protected/);
  } else {
    expect(statusResponse.ok()).toBe(true);
  }
});

test("catalog load failure shows retry and never exposes a free-text fallback", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  let failCatalog = true;
  await page.route("**/api/v1/recommendation/preferences/catalog**", async (route) => {
    if (failCatalog) {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: { code: "PREFERENCE_CATALOG_NOT_AVAILABLE" } }) });
      return;
    }
    await route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Get started!" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Check delivery address" }).click();
  await page.getByRole("button", { name: "Confirm & start" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  failCatalog = false;
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "What sounds good?" })).toBeVisible();
});
