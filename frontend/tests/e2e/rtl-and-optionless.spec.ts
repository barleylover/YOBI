import { expect, test, type Route } from "@playwright/test";
import type { CartPreview } from "../../src/types";
import { selectFirstPreferenceAndRecommend, startStructuredSession } from "./structured-helpers";

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

test("an optionless menu reaches the cart and Yogiyo handoff without a restaurant note", async ({ page }, testInfo) => {
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
        display_name: selectedMenuName,
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
  const selectedCard = page.locator(".v2-alimtalk-card").first();
  const selectedTestId = await selectedCard.getAttribute("data-testid");
  const selectedMenuId = selectedTestId!.replace(/^menu-/, "");
  selectedMenuName = await selectedCard.getByRole("heading").innerText();
  selectedMenuPrice = Number((await selectedCard.locator(".v2-card-title-row > strong").innerText()).replace(/\D/g, ""));

  await page.getByRole("button", { name: "Choose this dish" }).first().click();
  await expect(page.locator("[data-testid^='option-group-']")).toHaveCount(0);
  await page.locator("textarea.v2-note-input").fill("");
  await page.getByRole("button", { name: "Add to cart" }).click();

  await expect.poll(() => addPayload).not.toBeNull();
  expect(addPayload).toMatchObject({ menu_id: selectedMenuId, option_item_ids: [], user_note: "" });
  await page.getByRole("button", { name: "No, continue to delivery" }).click();
  await page.getByRole("button", { name: "Confirm delivery details" }).click();
  await expect(page.getByTestId("cart-review")).toContainText(selectedMenuName);
  await page.getByRole("button", { name: /Place order/ }).click();

  await expect(page).toHaveURL(/\/handoff$/);
  await expect(page.getByRole("heading", { name: "Ready to order" })).toBeVisible();
  await page.getByRole("button", { name: /Open in Yogiyo/ }).click();
  await expect(page.getByRole("status")).toContainText("Continue your order in Yogiyo");
  await expect(page.locator("body")).not.toContainText(/demo|mock|synthetic/i);
});
