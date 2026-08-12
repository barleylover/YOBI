import { expect, test } from "@playwright/test";
import { startStructuredSession } from "./structured-helpers";

test("selection is deterministic and calls recommendation only after completion", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  const recommendationRequests: Array<Record<string, unknown>> = [];
  const legacyMessageRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/recommendations")) {
      recommendationRequests.push(request.postDataJSON() as Record<string, unknown>);
    }
    if (request.url().includes("/messages")) legacyMessageRequests.push(request.url());
  });

  await startStructuredSession(page);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  const visibleChips = page.locator(".preference-chip:visible");
  await visibleChips.nth(0).click();
  await visibleChips.nth(1).click();
  expect(recommendationRequests).toHaveLength(0);
  expect(legacyMessageRequests).toEqual([]);

  await page.getByRole("button", { name: "Show my recommendations" }).click();
  await expect.poll(() => recommendationRequests.length).toBe(1);
  expect(recommendationRequests[0]).toMatchObject({ mode: "INITIAL" });
  await expect(page.getByRole("button", { name: "Choose this menu" }).first()).toBeVisible();
  expect(legacyMessageRequests).toEqual([]);
});

test("different menus keeps committed criteria and creates one SIMILAR request", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  const modes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "POST" || !request.url().endsWith("/recommendations")) return;
    modes.push((request.postDataJSON() as { mode: string }).mode);
  });

  await startStructuredSession(page);
  await page.locator(".preference-chip:visible").first().click();
  await page.getByRole("button", { name: "Show my recommendations" }).click();
  await expect(page.getByRole("button", { name: "Show different menus" })).toBeVisible();
  await page.getByRole("button", { name: "Show different menus" }).click();

  await expect.poll(() => modes).toEqual(["INITIAL", "SIMILAR"]);
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
