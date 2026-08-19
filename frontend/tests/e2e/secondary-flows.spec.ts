import { expect, test } from "@playwright/test";
import { selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

test("halal and vegan conflicts are resolved explicitly before recommendation", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await page.route("**/structured-recommendations/preview", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        eligible_menu_count: 1,
        eligible_merchant_count: 1,
        zero_reason_codes: [],
        release_id: "client-conflict-contract",
        support_manifest_sha256: "client-conflict-contract",
        ranking_policy_version: "client-conflict-contract",
        timing_ms: 1,
      }),
    });
  });
  await startStructuredSession(page);
  const ingredients = page.locator("[data-category='main_ingredients']");
  await ingredients.getByRole("button", { name: "Pork", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  const halal = page.getByRole("switch", { name: /Halal-certified only/ });
  await halal.click();

  await expect(page.getByRole("alert")).toContainText("conflicts with the halal or vegan filter");
  await expect(page.getByRole("button", { name: "Find my dish" })).toBeDisabled();
  await page.getByRole("tab", { name: /Core/ }).click();
  await ingredients.getByRole("button", { name: "Pork", exact: true }).click();
  await page.getByRole("tab", { name: /Conditions/ }).click();
  await expect(page.getByRole("button", { name: "Find my dish" })).toBeEnabled();
});

test("results omit comparison and selection reason while retaining filter editing", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startStructuredSession(page);
  await selectFirstPreferenceAndRecommend(page);

  await expect(page.getByRole("button", { name: "Compare these menus" })).toHaveCount(0);
  await expect(page.locator(".v2-card-yobi").first()).toBeVisible();
  await expect(page.locator(".v2-card-yogiyo").first()).toBeVisible();
  await page.getByRole("button", { name: "Edit filters" }).click();
  await expect(page.getByRole("heading", { name: "What are you craving?" })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});

test("provider unavailability yields selectable deterministic results", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One local fallback proof is sufficient.");
  await startStructuredSession(page);
  await selectFirstPreferenceAndRecommend(page);

  await expect(page.getByRole("heading", { name: "Closest matching menus" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try recommendation again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Choose this menu" }).first()).toBeEnabled();
  await expect(page.getByRole("button", { name: "Edit filters" })).toBeVisible();
});
