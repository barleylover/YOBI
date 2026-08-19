import { expect, test } from "@playwright/test";
import { completeCurrentOptions, selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

function yobiKeys(page: import("@playwright/test").Page) {
  return page.evaluate(() => Object.keys(sessionStorage).filter((key) => key.startsWith("yobi-")).sort());
}

test("Back to YOBI erases the visitor's records and returns to the untouched locale screen", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One end-of-demo reset proof is sufficient.");

  await startStructuredSession(page);
  await selectFirstPreferenceAndRecommend(page);

  const stored = await page.evaluate(() => JSON.parse(sessionStorage.getItem("yobi-demo-session") ?? "null"));
  const profileId: string = stored.state.profile.profile_id;
  expect(profileId).toMatch(/^profile_/);
  // The journey really did record a preference before we assert it is gone.
  expect(stored.state.committedCriteria).not.toBeNull();

  // Walk to the terminal handoff screen through the real cart.
  await page.getByRole("button", { name: "Choose this menu" }).first().click();
  await completeCurrentOptions(page);
  await page.getByRole("button", { name: "No, continue to delivery" }).click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();

  // The demo merchants set a minimum order on the item subtotal, so a single
  // cheap menu can leave the handoff disabled. Add servings until it clears.
  const yogiyo = page.getByRole("button", { name: "Yogiyo" });
  await expect(yogiyo).toBeVisible();
  for (let quantity = 1; quantity < 6 && await yogiyo.isDisabled(); quantity += 1) {
    await page.locator(".quantity-stepper button").last().click();
    // Wait for the cart response to land before re-reading the button state.
    await expect(page.locator(".quantity-stepper span")).toHaveText(String(quantity + 1));
  }
  await expect(yogiyo).toBeEnabled();
  await yogiyo.click();
  await expect(page).toHaveURL(/\/handoff$/);
  await expect(page.locator(".handoff-cart-summary")).toBeVisible();
  await page.getByRole("button", { name: "Yogiyo" }).click();
  await expect(page.getByRole("heading", { name: /YOBI demo ends here/ })).toBeVisible();

  // Caches are populated before the reset.
  expect(await yobiKeys(page)).toContain("yobi-demo-session");
  expect((await page.request.get(`/api/v1/profiles/${profileId}`)).status()).toBe(200);

  await page.getByRole("button", { name: "Back to YOBI" }).click();

  // Back at the very first country/language screen.
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator(".welcome-locale select").first()).toBeVisible();

  // The preference-catalog and pending-request caches are gone outright. The
  // store entry is rewritten by the locale screen's own draft effect, so assert
  // it carries no trace of the finished journey rather than that it is absent.
  expect(await yobiKeys(page)).toEqual(["yobi-demo-session"]);
  const after = await page.evaluate(() => JSON.parse(sessionStorage.getItem("yobi-demo-session") ?? "null"));
  expect(after.state).toMatchObject({
    profile: null,
    session: null,
    addressRefId: "",
    addressSummary: "",
    cartQuantity: 0,
    committedCriteria: null,
    criteriaVersion: 0,
    latestRecommendation: null,
    pendingRecommendation: null,
    recommendationPhase: "SELECTING",
    draftLanguage: "English",
    draftCountry: "United States",
  });
  expect(after.state.draftCriteria.price_bands).toEqual([]);

  // Locale selections are back to the untouched defaults.
  await expect(page.locator(".welcome-locale select").first()).toHaveValue("English");
  await expect(page.locator(".welcome-locale select").nth(1)).toHaveValue("United States");

  // The server-side records are deleted, not merely abandoned.
  expect((await page.request.get(`/api/v1/profiles/${profileId}`)).status()).toBe(404);
});
