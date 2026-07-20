import { defineConfig } from "@playwright/test";

/** Playwright config for live production smoke tests (no local dev server). */
export default defineConfig({
  testDir: "./tests",
  testMatch: "prod-smoke.spec.ts",
  timeout: 180_000,
  workers: 1,
  use: {
    browserName: "chromium",
    channel: "msedge",
    headless: true,
    viewport: { width: 1600, height: 1000 },
  },
});
