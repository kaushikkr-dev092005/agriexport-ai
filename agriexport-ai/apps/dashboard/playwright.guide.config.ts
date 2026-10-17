import { defineConfig } from "@playwright/test";

/** Focused overlay checks against a development server; full suite uses production config. */
export default defineConfig({
  testDir: "./tests", testMatch: "guide.spec.ts", workers: 1, timeout: 45000,
  use: { baseURL: "http://127.0.0.1:3100", channel: "msedge", headless: true, viewport: { width: 1440, height: 1100 }, trace: "retain-on-failure" },
  webServer: { command: "npm run dev -- --port 3100", url: "http://127.0.0.1:3100", reuseExistingServer: true, timeout: 60000 }
});
