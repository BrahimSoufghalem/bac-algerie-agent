import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";
const root = path.join(os.tmpdir(), "masar-e2e-" + process.pid);
process.env.TEST_DATA_DIR = root;
export default defineConfig({
  testDir: "tests/browser",
  timeout: 90000,
  workers: 1,
  reporter: "list",
  outputDir: "browser-results",
  use: {
    baseURL: "http://127.0.0.1:8091",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"] }
      : {},
  },
  webServer: {
    command: `${process.env.BAC_PYTHON || "python"} -m uvicorn tests.browser.server:app --host 127.0.0.1 --port 8091`,
    url: "http://127.0.0.1:8091/health",
    reuseExistingServer: false,
    timeout: 30000,
    env: { TEST_DATA_DIR: root },
  },
});
