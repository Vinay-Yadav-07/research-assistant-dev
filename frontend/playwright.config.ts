import { defineConfig } from "@playwright/test";

/**
 * E2E against a deployed (or local) app. `E2E_BASE_URL` defaults to the local dev server;
 * `E2E_BROWSER_CHANNEL=chrome` uses an installed Chrome where Playwright's own browsers do not run.
 */
export default defineConfig({
  testDir: "e2e",
  // Ingestion and the answer run on a CPU Space, so one test needs minutes, not seconds.
  timeout: 8 * 60 * 1000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: process.env.E2E_BROWSER_CHANNEL,
    trace: "on",
    video: "on",
  },
});
