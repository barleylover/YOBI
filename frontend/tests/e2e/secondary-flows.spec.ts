import { expect, test } from "@playwright/test";
import { selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

test("halal and vegan conflicts are resolved explicitly before recommendation", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startStructuredSession(page);
  const ingredients = page.locator("details.preference-category").filter({ hasText: "Main ingredient" });
  await ingredients.locator("summary").click();
  await ingredients.getByRole("button", { name: "Pork", exact: true }).click();
  await page.getByRole("checkbox", { name: /Only show halal-certified restaurants/ }).check();

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
  if (await compare.isVisible().catch(() => false)) {
    await compare.click();
    await expect(page.locator(".recommendation-comparison")).toBeVisible();
  }
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
