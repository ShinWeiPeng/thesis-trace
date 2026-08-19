import { defineConfig, devices } from "@playwright/test";

const hostedBrowser = process.env.PLAYWRIGHT_USE_SYSTEM_CHROME === "1" ? { channel: "chrome" } : {};

export default defineConfig({
  testDir: ".", testMatch: "wave0-real.spec.ts",
  webServer: { command: "bash ../scripts/run-wave0-acceptance.sh", cwd: "..", url: "http://127.0.0.1:5173", timeout: 120_000 },
  use: { baseURL: "http://127.0.0.1:5173", ...hostedBrowser },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"] } }, { name: "mobile", use: { ...devices["Pixel 7"] } }],
});
