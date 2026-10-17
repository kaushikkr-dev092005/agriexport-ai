import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
export default defineConfig({
  testDir: "./tests", workers: 1, timeout: 45000, retries: 0,
  use: { baseURL: "http://127.0.0.1:3123", channel: "msedge", headless: true, viewport: { width: 1440, height: 1100 }, trace: "retain-on-failure" },
  webServer: [
    { command: `"${resolve("../../.venv/Scripts/python.exe")}" -m uvicorn tests.browser_api:create_app --app-dir "${resolve("../..")}" --factory --host 127.0.0.1 --port 8123`, url: "http://127.0.0.1:8123/api/v1/health", reuseExistingServer: false, timeout: 60000 },
    { command: "node node_modules/next/dist/bin/next start --hostname 127.0.0.1 -p 3123", url: "http://127.0.0.1:3123", reuseExistingServer: false, timeout: 60000, env: { AGRI_API_ORIGIN: "http://127.0.0.1:8123", NEXT_TELEMETRY_DISABLED: "1" } }
  ]
});
