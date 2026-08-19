import { expect, test } from "@playwright/test";
import { completeCurrentOptions, selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

test("primary tourist flow selects criteria, recommends once and reaches the order builder", async ({ page }) => {
  const consoleErrors: string[] = [];
  const recommendationModes: string[] = [];
  const conversationEvents: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/recommendations")) {
      recommendationModes.push((request.postDataJSON() as { mode: string }).mode);
    }
    if (request.method() === "POST" && request.url().endsWith("/events")) {
      const payload = request.postDataJSON() as { event_type?: string };
      if (payload.event_type) conversationEvents.push(payload.event_type);
    }
  });

  await startStructuredSession(page);
  await selectFirstPreferenceAndRecommend(page);
  await expect(page.locator(".v2-bot-message").first()).toBeVisible();
  await expect(page.locator(".v2-alimtalk-card")).toHaveCount(3);
  await expect(page.locator(".rank-bar")).toHaveCount(0);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  const carouselSizing = await page.locator(".v2-card-carousel").evaluate((carousel) => {
    const card = carousel.querySelector<HTMLElement>(".v2-alimtalk-card");
    const style = getComputedStyle(carousel);
    return {
      carouselWidth: carousel.clientWidth,
      cardWidth: card?.getBoundingClientRect().width ?? 0,
      snapType: style.scrollSnapType,
    };
  });
  expect(Math.abs(carouselSizing.carouselWidth - carouselSizing.cardWidth)).toBeLessThanOrEqual(2);
  expect(carouselSizing.snapType).toContain("mandatory");
  await expect(page.getByText("YOBI:").first()).toBeVisible();
  await expect(page.getByText("YOGIYO:").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "View additional explanation" }).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/demo|mock|synthetic/i);
  await page.getByRole("button", { name: "Choose this menu" }).first().click();
  await expect(page.getByTestId("order-flow")).toBeVisible();
  await completeCurrentOptions(page);

  await expect(page.getByRole("button", { name: "Yes, show more menus" })).toBeVisible();
  expect(recommendationModes).toEqual(["INITIAL"]);
  expect(conversationEvents[0]).toBe("SELECT_MENU");
  expect(consoleErrors).toEqual([]);
});
