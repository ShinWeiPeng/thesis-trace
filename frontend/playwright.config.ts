import { defineConfig, devices } from "@playwright/test";

const hostedBrowser = process.env.PLAYWRIGHT_USE_SYSTEM_CHROME === "1" ? { channel: "chrome" } : {};

export default defineConfig({
  testDir: "./e2e", testIgnore: "wave0-real.spec.ts", webServer: { command: "npm run dev -- --host 127.0.0.1", url: "http://127.0.0.1:5173", reuseExistingServer: true },
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure", ...hostedBrowser },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
});
