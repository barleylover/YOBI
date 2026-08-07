import { expect, test } from "@playwright/test";

test("Korean remains active from profile through payment and confirmation", async ({ page }) => {
  await page.goto("/start");
  await page.locator("select").first().selectOption({ label: "한국어" });
  await page.locator("select").nth(1).selectOption({ label: "South Korea" });
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByText("2/2 · 음식 및 배달 정보")).toBeVisible();
  await expect(page.getByRole("heading", { name: "YOBI가 무엇을 기억하면 좋을까요?" })).toBeVisible();
  await page.getByRole("checkbox", { name: /합성 데모 프로필/ }).check();
  await page.getByRole("button", { name: "배달 주소 확인" }).click();
  await page.getByRole("button", { name: "확인하고 시작" }).first().click();

  await expect(page).toHaveURL(/\/chat\/session_/);
  await expect(page.getByText("데모 카탈로그 준비됨")).toBeVisible();
  await page.getByRole("button", { name: "데모 질문 사용하기" }).click();
  await page.getByTestId("menu-menu_001_01").getByRole("button", { name: "이 메뉴 선택" }).click();

  await expect(page.getByRole("heading", { name: "맵기" })).toBeVisible();
  await page.getByRole("button", { name: /^순한맛/ }).click();
  await expect(page.getByRole("heading", { name: "사이즈" })).toBeVisible();
  await page.getByRole("button", { name: /^보통/ }).click();
  await expect(page.getByRole("heading", { name: "치즈" })).toBeVisible();
  await page.getByRole("button", { name: /^치즈 추가/ }).click();
  await expect(page.getByRole("heading", { name: "어묵" })).toBeVisible();
  await page.getByRole("button", { name: /^어묵 빼기/ }).click();
  await expect(page.getByText("가게 요청 사항")).toBeVisible();
  await page.getByRole("button", { name: "데모 장바구니에 담기" }).click();
  await expect(page.getByRole("button", { name: "네, 다른 메뉴 보기" })).toBeVisible();
  await page.getByRole("button", { name: "아니요, 배달 단계로" }).click();

  await expect(page.getByText("프런트에 맡길까요?")).toBeVisible();
  await page.getByRole("button", { name: "배달 정보 확인" }).click();
  await expect(page.getByText("식이 조건 확인")).toBeVisible();
  await expect(page.getByText("가게 최소 주문금액")).toBeVisible();
  await page.getByRole("button", { name: "결제로 이동" }).click();

  await expect(page.getByRole("heading", { name: "데모 주문 결제하기" })).toBeVisible();
  await expect(page.getByText("외부 결제 시뮬레이션")).toBeVisible();
  await page.getByRole("button", { name: /^결제 ₩/ }).click();
  await expect(page.getByRole("heading", { name: "첫 한국 음식 주문이 접수됐어요." })).toBeVisible();
  await expect(page.getByText(/실제 가게나 배달원에게 전달되지 않았습니다/)).toBeVisible();
});
