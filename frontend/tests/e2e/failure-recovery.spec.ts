import { expect, test } from "@playwright/test";

test("onboarding and v3 conditions remain accessible without internal boundary wording", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Korean food/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Language.*English/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Country.*United States/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.getByRole("button", { name: "Get started", exact: true }).click();
  await expect(page.getByText(/Age range|Religion|Favourite comfort foods/i)).toHaveCount(0);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("button", { name: "Continue with this address" }).click();

  await expect(page.getByRole("heading", { name: "What are you craving?" })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("radio")).toHaveCount(3);
  await expect(page.locator("input[type='range']")).toHaveCount(2);
  await expect(page.getByRole("switch")).toHaveCount(2);
  await expect(page.locator("body")).not.toContainText(/demo|mock|synthetic/i);
});

test("catalog load failure shows a localized retry and no free-text fallback", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile recovery proof is sufficient.");
  let failCatalog = true;
  await page.route("**/api/v1/recommendation/preferences/catalog**", async (route) => {
    if (failCatalog) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "PREFERENCE_CATALOG_NOT_AVAILABLE" } }),
      });
      return;
    }
    await route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Get started", exact: true }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("button", { name: "Continue with this address" }).click();
  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  failCatalog = false;
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "What are you craving?" })).toBeVisible();
});

test("Japanese is localized while Arabic selection uses the English LTR fallback", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One mobile locale-layout proof is sufficient.");

  await page.goto("/");
  await page.getByRole("button", { name: /Language.*English/ }).click();
  await page.getByRole("button", { name: /日本語.*Japanese/ }).click();
  await page.locator(".v2-appbar-action").click();
  await expect(page.getByRole("button", { name: "始める" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "ja");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");

  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/");
  await page.getByRole("button", { name: /Language.*English/ }).click();
  await page.getByRole("button", { name: /العربية.*Arabic/ }).click();
  await page.locator(".v2-appbar-action").click();
  await expect(page.getByRole("button", { name: "Get started" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.getByText(/مرحبًا|العرض|تجريبي/)).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("reduced-motion preference disables smooth motion", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One computed-style proof is sufficient.");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const styles = await page.getByRole("button", { name: "Get started" }).evaluate((element) => {
    const style = getComputedStyle(element);
    const duration = Number.parseFloat(style.transitionDuration);
    return {
      scrollBehavior: style.scrollBehavior,
      transitionSeconds: style.transitionDuration.endsWith("ms") ? duration / 1000 : duration,
    };
  });
  expect(styles.scrollBehavior).toBe("auto");
  expect(styles.transitionSeconds).toBeLessThanOrEqual(0.00001);
});
