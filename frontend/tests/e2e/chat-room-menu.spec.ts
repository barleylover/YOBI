import { expect, test } from "@playwright/test";
import { selectFirstPricePreference, startStructuredSession } from "./structured-helpers";

test("structured draft survives profile editing without allergy or chat controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startStructuredSession(page);
  const firstChip = await selectFirstPricePreference(page);
  const label = (await firstChip.innerText()).trim();
  await page.getByRole("button", { name: "Back", exact: true }).click();

  await expect(page).toHaveURL(/\/profile\?edit=1/);
  await expect(page.getByText("Current address")).toBeVisible();
  await expect(page.getByText(/Allerg/i)).toHaveCount(0);
  await expect(page.getByText(/Age range|Religion|Favourite comfort foods/i)).toHaveCount(0);
  await expect(page.getByRole("radio")).toHaveCount(0);
  await page.getByRole("button", { name: "Keep this address" }).click();

  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("textbox")).toHaveCount(0);
});

test("Korean conditions use three relative spice choices, two price handles and enabled diet switches", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startStructuredSession(page, true);

  await page.getByRole("button", { name: "다음", exact: true }).click();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.getByRole("radio")).toHaveCount(3);
  await expect(page.getByRole("radio", { name: "기준과 비슷하게" })).toBeChecked();
  await expect(page.locator("[data-category='price_range_krw'] input[type='range']")).toHaveCount(2);
  await expect(page.getByRole("switch", { name: /할랄 인증만/ })).toBeEnabled();
  await expect(page.getByRole("switch", { name: /비건 옵션만/ })).toBeEnabled();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
