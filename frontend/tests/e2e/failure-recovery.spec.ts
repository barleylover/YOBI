import { expect, test } from "@playwright/test";

test("onboarding remains accessible at every required viewport", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Order K-food with context/ })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /I agree/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start ordering" })).toBeDisabled();
  await page.goto("/demo/qr");
  await expect(page.getByRole("img", { name: /QR code for/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download presentation SVG" })).toBeVisible();
  await page.goto("/demo/control");
  await page.getByRole("button", { name: "Load safe status" }).click();
  if (process.env.YOBI_E2E_BASE_URL) {
    await expect(page.getByRole("status")).toHaveText(/Status is protected/);
  } else {
    await expect(page.getByText("demo-2026.08.06-v1")).toBeVisible();
    await expect(page.getByText("2026-08-06", { exact: true })).toBeVisible();
  }
});
