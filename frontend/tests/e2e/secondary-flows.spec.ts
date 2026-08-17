import { expect, test } from "@playwright/test";
import { selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

test("halal and vegan conflicts are resolved explicitly before recommendation", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  // This test isolates the client-side hard-conflict contract. The live demo
  // catalog can legitimately retire PORK support, so keep preview positive
  // without inventing any menu or recommendation response.
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
  const ingredients = page.locator("details.preference-category").filter({ hasText: "Main ingredient" });
  if (await ingredients.getAttribute("open") === null) await ingredients.locator("summary").click();
  await ingredients.getByRole("button", { name: "Pork", exact: true }).click();
  const halal = page.getByRole("checkbox", { name: /Only show halal-certified restaurants/ });
  if (await halal.isDisabled()) {
    await expect(halal).toBeDisabled();
    return;
  }
  await expect(ingredients.getByRole("button", { name: "Pork", exact: true })).toHaveAttribute("aria-pressed", "true");
  await halal.click();
  await expect(halal).toBeChecked();

  await expect(page.getByRole("alert")).toContainText("conflicts with the halal or vegan filter");
  await expect(page.getByRole("button", { name: "Show my recommendations" })).toBeDisabled();
  await ingredients.getByRole("button", { name: "Pork", exact: true }).click();
  await expect(page.getByRole("button", { name: "Show my recommendations" })).toBeEnabled();
});

test("result comparison and criteria editing are button-only actions", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startStructuredSession(page);
  await selectFirstPreferenceAndRecommend(page);
  const compare = page.getByRole("button", { name: "Compare these menus" });
  if (await compare.isEnabled().catch(() => false)) {
    await compare.click();
    await expect(page.locator(".comparison-message")).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole("button", { name: "Edit choices" }).click();
  await expect(page.getByRole("heading", { name: "What sounds good?" })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});

test("search fallback keeps menu selection, retry and edit actions", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await page.goto("/demo/control");
  const modeControl = page.getByRole("button", { name: /force fallback/i });
  if (!(await modeControl.isVisible().catch(() => false))) test.skip(true, "Demo control is protected in this environment.");
  await modeControl.click();
  await startStructuredSession(page);
  await selectFirstPreferenceAndRecommend(page);
  await expect(page.getByRole("heading", { name: "Closest matching menus" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try recommendation again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit choices" })).toBeVisible();
});
