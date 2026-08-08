import { expect, test, type Page } from "@playwright/test";

interface AssistantMetadata {
  dialogue_act?: string;
  readiness?: { status?: string } | null;
  cards?: Array<{ type?: string }>;
}

interface ConversationView {
  meal_need_state: {
    rejected_menu_ids: string[];
  };
  messages: Array<{
    role: "user" | "assistant";
    safe_metadata: AssistantMetadata;
  }>;
}

async function startSession(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Get started!" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: /I agree/ }).check();
  await page.getByRole("button", { name: "Check delivery address" }).click();
  await page.getByRole("button", { name: "Confirm & start" }).first().click();
  await expect(page).toHaveURL(/\/chat\/session_/);
}

async function sendMessage(page: Page, content: string) {
  await page.getByLabel("Ask YOBI").fill(content);
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
      && response.url().includes("/messages/stream")
  ));
  await page.getByRole("button", { name: "Send message" }).click();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  await response.finished();
  await expect(page.getByLabel("Ask YOBI")).toBeEnabled();
}

async function getConversation(page: Page): Promise<ConversationView> {
  const sessionId = new URL(page.url()).pathname.split("/").at(-1);
  expect(sessionId).toMatch(/^session_/);
  const response = await page.request.get(`/api/v1/sessions/${sessionId}/conversation`);
  expect(response.ok()).toBe(true);
  return response.json() as Promise<ConversationView>;
}

function latestAssistant(conversation: ConversationView): AssistantMetadata {
  const message = [...conversation.messages].reverse().find((item) => item.role === "assistant");
  expect(message).toBeDefined();
  return message?.safe_metadata ?? {};
}

test("greeting stays card-free until accumulated needs are recommendation-ready", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  await startSession(page);

  await sendMessage(page, "hi");
  let assistant = latestAssistant(await getConversation(page));
  expect(assistant.dialogue_act).toBe("GREET");
  expect(assistant.readiness?.status).toBe("NOT_READY");
  expect(assistant.cards).toEqual([]);
  await expect(page.locator("[data-testid^='menu-']")).toHaveCount(0);

  await sendMessage(page, "I want something warm.");
  assistant = latestAssistant(await getConversation(page));
  expect(assistant.dialogue_act).toBe("COLLECT_NEEDS");
  expect(assistant.readiness?.status).toBe("NOT_READY");
  expect(assistant.cards).toEqual([]);

  await sendMessage(page, "Savory and chewy, please.");
  await expect(page.locator("[data-testid^='menu-']").first()).toBeVisible();
  assistant = latestAssistant(await getConversation(page));
  expect(assistant.dialogue_act).toBe("RECOMMEND");
  expect(assistant.readiness?.status).toBe("READY");
  expect(assistant.cards?.some((card) => card.type === "menu_recommendations")).toBe(true);
});

test("something-else records rejection events before requesting revised cards", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "iPhone 13", "One primary mobile proof is sufficient.");
  const conversationEvents: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "POST" || !request.url().endsWith("/events")) return;
    const payload = request.postDataJSON() as { event_type?: string };
    if (payload.event_type) conversationEvents.push(payload.event_type);
  });
  await startSession(page);

  await sendMessage(page, "Recommend a mild meal under 15,000 won.");
  await expect(page.getByRole("button", { name: "Something else" })).toBeVisible();
  await page.getByRole("button", { name: "Something else" }).click();
  await expect.poll(
    () => conversationEvents.filter((event) => event === "REJECT_MENU").length,
  ).toBeGreaterThan(0);
  await expect(page.getByLabel("Ask YOBI")).toBeEnabled();

  const conversation = await getConversation(page);
  expect(conversation.meal_need_state.rejected_menu_ids.length).toBeGreaterThan(0);
});
