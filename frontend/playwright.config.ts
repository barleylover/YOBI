import { defineConfig, devices } from "@playwright/test";

const appUrl = process.env.YOBI_E2E_BASE_URL ?? "http://127.0.0.1:5173";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 45_000,
  fullyParallel: false,
  // Local and deployed demos both use one shared stateful backend. Serial browser
  // journeys prevent test sessions from changing global demo controls concurrently.
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  expect: { timeout: process.env.YOBI_E2E_BASE_URL ? 30_000 : 5_000 },
  use: {
    baseURL: appUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: process.env.YOBI_E2E_BASE_URL
    ? undefined
    : [
        {
          command: "../.venv/bin/uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8000",
          url: "http://127.0.0.1:8000/healthz",
          reuseExistingServer: true,
          timeout: 30_000,
        },
        {
          command: "pnpm dev --host 127.0.0.1",
          url: appUrl,
          reuseExistingServer: true,
          timeout: 30_000,
        },
      ],
  projects: [
    { name: "iPhone 13", use: { ...devices["iPhone 13"], browserName: "chromium" } },
    { name: "Pixel 7", use: { ...devices["Pixel 7"] } },
    { name: "desktop-1366", use: { viewport: { width: 1366, height: 768 } } },
    { name: "desktop-1920", use: { viewport: { width: 1920, height: 1080 } } },
  ],
});
