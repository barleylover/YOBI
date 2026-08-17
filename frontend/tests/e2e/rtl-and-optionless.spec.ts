import { expect, test, type Page, type Route } from "@playwright/test";
import { getProductCopy } from "../../src/lib/productI18n";
import type { CartPreview, MenuSummary } from "../../src/types";
import { selectFirstPreferenceAndRecommend, selectFirstPricePreference, startStructuredSession } from "./structured-helpers";

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function startArabicSession(page: Page) {
  await page.goto("/");
  await page.locator(".welcome-locale select").first().selectOption("العربية");
  await page.getByRole("button", { name: "ابدأ" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "البحث عن عنوان العرض" }).click();
  await page.getByRole("button", { name: "اختيار هذا العنوان" }).first().click();
  await expect(page.getByRole("heading", { name: "ما الطعام الذي ترغب فيه؟" })).toBeVisible();
}

async function carouselGeometry(page: Page, selector: string) {
  return page.locator(selector).evaluate((carousel) => {
    const cards = Array.from(carousel.children) as HTMLElement[];
    const first = cards[0]?.getBoundingClientRect();
    const second = cards[1]?.getBoundingClientRect();
    return {
      clientWidth: (carousel as HTMLElement).clientWidth,
      cardWidth: first?.width ?? 0,
      step: first && second ? Math.abs(second.left - first.left) : (carousel as HTMLElement).clientWidth,
    };
  });
}

test("a selected menu with no option groups continues through the authoritative cart to the Yogiyo handoff", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile contract proof is sufficient.");

  let cart: CartPreview | null = null;
  let addPayload: { menu_id: string; option_item_ids: string[]; user_note: string } | null = null;
  let selectedMenuName = "";
  let selectedMenuPrice = 0;

  await page.route(/\/api\/v1\/menus\/[^/]+\/options(?:\?.*)?$/, async (route) => fulfillJson(route, []));
  await page.route(/\/api\/v1\/sessions\/[^/]+\/cart\/items$/, async (route) => {
    addPayload = route.request().postDataJSON() as typeof addPayload;
    cart = {
      cart_id: "cart_optionless_e2e",
      version: 1,
      items: [{
        cart_item_id: "cart_item_optionless_e2e",
        menu_id: addPayload!.menu_id,
        menu_name: selectedMenuName,
        menu_name_ko: selectedMenuName,
        quantity: 1,
        unit_price: selectedMenuPrice,
        options: [],
        line_total: selectedMenuPrice,
      }],
      subtotal: selectedMenuPrice,
      delivery_fee: 2_000,
      total_price: selectedMenuPrice + 2_000,
      missing_slots: ["delivery_preferences"],
      dietary_warnings: [],
      minimum_order_amount: 0,
      minimum_order_shortfall: 0,
      ready_to_checkout: false,
      confirmed: false,
    };
    await fulfillJson(route, cart);
  });
  await page.route(/\/api\/v1\/sessions\/[^/]+\/delivery$/, async (route) => {
    cart = { ...cart!, version: 2, missing_slots: [], ready_to_checkout: true };
    await fulfillJson(route, cart);
  });
  await page.route(/\/api\/v1\/sessions\/[^/]+\/cart\/confirm$/, async (route) => {
    cart = { ...cart!, version: 3, confirmed: true };
    await fulfillJson(route, cart);
  });
  await page.route(/\/api\/v1\/sessions\/[^/]+\/cart$/, async (route) => fulfillJson(route, cart));

  await startStructuredSession(page);
  await selectFirstPreferenceAndRecommend(page);
  const selectedCard = page.locator(".structured-menu-card").first();
  const selectedTestId = await selectedCard.getAttribute("data-testid");
  const selectedMenuId = selectedTestId!.replace(/^menu-/, "");
  selectedMenuName = await selectedCard.locator(".structured-menu-title-row h2").innerText();
  selectedMenuPrice = Number((await selectedCard.locator(".structured-menu-title-row > strong").innerText()).replace(/\D/g, ""));
  expect(selectedMenuPrice).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Choose this menu" }).first().click();
  await expect(page.locator("[data-testid^='option-group-']")).toHaveCount(0);
  const note = page.getByRole("textbox");
  await expect(note).toBeVisible();
  await note.fill("Please pack the sauce separately.");
  await page.getByRole("button", { name: "Add to cart" }).click();

  await expect.poll(() => addPayload).not.toBeNull();
  expect(addPayload).toMatchObject({
    menu_id: selectedMenuId,
    option_item_ids: [],
    user_note: "Please pack the sauce separately.",
  });
  await page.getByRole("button", { name: "No, continue to delivery" }).click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();
  const review = page.getByTestId("cart-review");
  await expect(review).toContainText(selectedMenuName);
  await expect(review).toContainText(`₩${selectedMenuPrice.toLocaleString("en-US")}`);

  await page.getByRole("button", { name: "Yogiyo" }).click();
  await expect(page).toHaveURL(/\/handoff$/);
  await expect(page.getByRole("heading", { name: "Continue in Yogiyo to order" })).toBeVisible();
  await expect(page.locator(".handoff-cart-summary")).toContainText(selectedMenuName);
  await page.getByRole("button", { name: "Yogiyo" }).click();
  await expect(page.getByRole("heading", { name: /YOBI demo ends here/ })).toBeVisible();
});

test("Arabic recommendation and K-Demon carousels move one card in RTL with controls and physical arrow keys", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile RTL geometry proof is sufficient.");
  const productCopy = getProductCopy("العربية");
  const featureMenus: MenuSummary[] = [
    {
      menu_id: "feature_ar_1", merchant_id: "feature_merchant_ar", merchant_name: "YOBI Feature Kitchen",
      name_en: "Gimbap", name_ko: "김밥", category: "Gimbap", description: "Seasoned rice wrapped in seaweed.",
      cultural_description: "Seasoned rice and fillings wrapped in seaweed.", price: 9_000, delivery_fee: 2_000,
      eta_min: 20, eta_max: 30, spice_level: 1, serves_min: 1, serves_max: 1, dietary_summary: "",
      evidence_status: "VERIFIED", match_reasons: [], risk_hints: [], evidence_ids: [], grounded_claim_ids: [],
      grounded_passage_ids: [], is_synthetic: true,
    },
    {
      menu_id: "feature_ar_2", merchant_id: "feature_merchant_ar", merchant_name: "YOBI Feature Kitchen",
      name_en: "Tteokbokki", name_ko: "떡볶이", category: "Tteokbokki", description: "Chewy rice cakes in red sauce.",
      cultural_description: "Chewy rice cakes served in a red sauce.", price: 10_000, delivery_fee: 2_000,
      eta_min: 22, eta_max: 32, spice_level: 3, serves_min: 1, serves_max: 2, dietary_summary: "",
      evidence_status: "VERIFIED", match_reasons: [], risk_hints: [], evidence_ids: [], grounded_claim_ids: [],
      grounded_passage_ids: [], is_synthetic: true,
    },
  ];
  await page.route(/\/api\/v1\/sessions\/[^/]+\/featured\/kpop-demon-hunters$/, async (route) => fulfillJson(route, {
    snapshot_id: "feature_snapshot_ar_e2e",
    items: [
      { dish_name: "Gimbap", description: featureMenus[0].cultural_description, menu: featureMenus[0] },
      { dish_name: "Tteokbokki", description: featureMenus[1].cultural_description, menu: featureMenus[1] },
    ],
  }));

  await startArabicSession(page);
  await selectFirstPricePreference(page);
  const recommendationResponse = page.waitForResponse((response) => (
    response.request().method() === "POST" && response.url().endsWith("/recommendations")
  ));
  await page.getByRole("button", { name: "عرض الاقتراحات" }).click();
  expect((await recommendationResponse).ok()).toBe(true);
  const recommendationCarousel = page.locator(".structured-menu-carousel");
  await expect(recommendationCarousel).toBeVisible();
  const recommendationCount = await recommendationCarousel.locator(".structured-menu-card").count();
  expect(recommendationCount).toBeGreaterThan(1);
  const recommendationGeometry = await carouselGeometry(page, ".structured-menu-carousel");
  expect(Math.abs(recommendationGeometry.cardWidth - recommendationGeometry.clientWidth)).toBeLessThanOrEqual(2);

  await page.getByRole("button", { name: productCopy.recommendation.next }).click();
  await expect.poll(async () => Math.round(Math.abs(await recommendationCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(Math.round(recommendationGeometry.step));
  await expect(page.getByText(productCopy.recommendation.cardPosition(2, recommendationCount))).toBeVisible();
  await page.getByRole("button", { name: productCopy.recommendation.previous }).click();
  await expect.poll(async () => Math.round(Math.abs(await recommendationCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(0);

  await recommendationCarousel.focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => Math.round(Math.abs(await recommendationCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(Math.round(recommendationGeometry.step));
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => Math.round(Math.abs(await recommendationCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(0);

  await page.getByRole("button", { name: productCopy.navigation.expand }).click();
  await page.getByRole("button", { name: productCopy.navigation.feature }).click();
  const dialog = page.getByRole("dialog");
  const featureCarousel = dialog.locator(".feature-carousel");
  await expect(featureCarousel).toBeVisible();
  const featureGeometry = await carouselGeometry(page, ".feature-carousel");
  expect(Math.abs(featureGeometry.cardWidth - featureGeometry.clientWidth)).toBeLessThanOrEqual(2);

  await dialog.getByRole("button", { name: productCopy.recommendation.next }).click();
  await expect.poll(async () => Math.round(Math.abs(await featureCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(Math.round(featureGeometry.step));
  await expect(dialog.getByText("2 / 2")).toBeVisible();
  await dialog.getByRole("button", { name: productCopy.recommendation.previous }).click();
  await expect.poll(async () => Math.round(Math.abs(await featureCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(0);

  await featureCarousel.focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => Math.round(Math.abs(await featureCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(Math.round(featureGeometry.step));
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => Math.round(Math.abs(await featureCarousel.evaluate((node) => (node as HTMLElement).scrollLeft))))
    .toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
