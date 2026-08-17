import { expect, test } from "@playwright/test";

const configuredBaseUrl = process.env.YOBI_E2E_BASE_URL;
const configuredHost = configuredBaseUrl ? new URL(configuredBaseUrl).hostname : "";
const expectsProtectedControl = Boolean(
  configuredBaseUrl && !["127.0.0.1", "localhost", "::1"].includes(configuredHost),
);

test("onboarding and structured selector remain accessible at every required viewport", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Hi, I’m YOBI/ })).toBeVisible();
  const languageSelect = page.locator(".welcome-locale select").first();
  const countrySelect = page.locator(".welcome-locale select").nth(1);
  await expect(languageSelect.locator("option")).toHaveCount(16);
  await languageSelect.selectOption("한국어");
  await expect(countrySelect).toHaveValue("South Korea");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole("button", { name: "시작하기" }).click();
  await expect(page.getByText(/나이|종교|좋아하는 음식/)).toHaveCount(0);
  await expect(page.getByRole("checkbox")).toHaveCount(1);
  await expect(page.getByRole("radio")).toHaveCount(0);
  await expect(page.getByText(/알레르기/)).toHaveCount(0);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "데모 주소 찾기" }).click();
  await page.getByRole("button", { name: "이 주소 선택" }).first().click();

  await expect(page.getByRole("heading", { name: "어떤 음식이 끌리세요?" })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await expect(page.locator(".spice-reference-choice")).toHaveCount(5);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  const discoveryToggle = page.locator(".discovery-nav-toggle");
  await discoveryToggle.click();
  await page.getByRole("button", { name: "케데헌 특집" }).click();
  const discoveryDialog = page.getByRole("dialog");
  await expect(discoveryDialog).toBeVisible();
  await expect(discoveryDialog.locator(".dialog-close")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await discoveryDialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(discoveryDialog).toBeHidden();
  await expect(discoveryToggle).toBeFocused();
  await page.goto("/demo/qr");
  await expect(page.getByRole("img", { name: /QR code for/ })).toBeVisible();
  await page.goto("/demo/control");
  const statusResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "GET" && response.url().endsWith("/api/v1/demo/status")
  ));
  await page.getByRole("button", { name: "Load safe status" }).click();
  const statusResponse = await statusResponsePromise;
  if (expectsProtectedControl) {
    await expect(page.getByRole("status")).toHaveText(/Status is protected/);
  } else {
    expect(statusResponse.ok()).toBe(true);
  }
});

test("catalog load failure shows retry and never exposes a free-text fallback", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  let failCatalog = true;
  await page.route("**/api/v1/recommendation/preferences/catalog**", async (route) => {
    if (failCatalog) {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: { code: "PREFERENCE_CATALOG_NOT_AVAILABLE" } }) });
      return;
    }
    await route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Get started!" }).click();
  await page.getByRole("checkbox", { name: /neutral profile/ }).check();
  await page.getByRole("button", { name: "Find the demo address" }).click();
  await page.getByRole("button", { name: "Select this address" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  failCatalog = false;
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "What sounds good?" })).toBeVisible();
});

test("Japanese and Arabic product copy persist into the address step and Arabic stays RTL without overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One mobile locale-layout proof is sufficient.");

  await page.goto("/");
  await page.locator(".welcome-locale select").first().selectOption("日本語");
  await expect(page.getByRole("heading", { name: /こんにちは、YOBIです/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /始める/ })).toBeVisible();
  await page.getByRole("button", { name: /始める/ }).click();
  await expect(page.getByRole("heading", { name: "YOBIはどこへ配達しますか？" }).first()).toBeVisible();
  await expect(page.getByRole("tab", { name: "検索" })).toBeVisible();
  await expect(page.getByText(/Where should YOBI deliver|Booking image|Find the demo address/)).toHaveCount(0);

  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/");
  await page.locator(".welcome-locale select").first().selectOption("العربية");
  await expect(page.getByRole("heading", { name: /مرحبًا، أنا YOBI/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "اختر الطعام الكوري بمعلومات واضحة، لا بالتخمين." })).toBeVisible();
  await expect(page.getByText("ما الطعام الذي ترغب فيه؟")).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole("button", { name: /ابدأ/ }).click();
  await expect(page.getByRole("heading", { name: "إلى أين يجب أن يوصّل YOBI؟" }).first()).toBeVisible();
  await expect(page.getByText(/عنوان ثابت مُعدّ مسبقًا/)).toBeVisible();
  await expect(page.getByRole("tab", { name: "بحث" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expect(page.getByText(/Where should YOBI deliver|Booking image|Find the demo address/)).toHaveCount(0);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "البحث عن عنوان العرض" }).click();
  const arabicAddress = page.getByRole("button", { name: "اختيار هذا العنوان" }).first();
  await expect(arabicAddress).toBeVisible();
  await expect(page.getByRole("button", { name: "اختيار هذه الوجبة" })).toHaveCount(0);
  await arabicAddress.click();
  await expect(page.getByRole("heading", { name: "ما الطعام الذي ترغب فيه؟" })).toBeVisible();
  await expect(page.locator(".preference-preview")).not.toContainText(/menus|restaurants|selected/i);
  await expect(page.locator(".preference-preview")).toContainText(/وجبة من .* مطعم/);
});

test("reduced-motion preference disables smooth motion in the new flow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One computed-style proof is sufficient.");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const styles = await page.getByRole("button", { name: "Get started!" }).evaluate((element) => {
    const style = getComputedStyle(element);
    const duration = Number.parseFloat(style.transitionDuration);
    return {
      scrollBehavior: style.scrollBehavior,
      transitionSeconds: style.transitionDuration.endsWith("ms") ? duration / 1000 : duration,
    };
  });
  expect(styles.scrollBehavior).toBe("auto");
  expect(styles.transitionSeconds).toBeLessThanOrEqual(0.00001);
});
