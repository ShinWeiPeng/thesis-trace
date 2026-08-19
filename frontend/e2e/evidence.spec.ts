import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", (route) => route.fulfill({ json: { kind: "owner", user_id: "owner", display_name: "Owner", session_expires_at: "2030-01-01T00:00:00Z", is_recovery_session: false, capabilities: ["research"] } }));
  await page.route("**/api/companies", async (route) => {
    if (route.request().method() === "POST") return route.fulfill({ json: { company_id: "2454", ticker: "2454", name: "聯發科", version: 1 }, status: 201 });
    return route.fulfill({ json: [{ company_id: "2330", ticker: "2330", name: "台積電", version: 4 }] });
  });
  await page.route("**/api/evidence", (route) => route.fulfill({ json: { evidence_id: "evidence-1", version: 1, status: "received" }, status: 202 }));
  await page.route("**/api/evidence/evidence-1", (route) => route.fulfill({ json: { evidence_id: "evidence-1", version: 2, status: "succeeded" } }));
});

test("server company evidence flow remains usable and within the viewport", async ({ page }) => {
  await page.goto("/");
  const company = page.getByRole("combobox");
  await expect(company).toBeVisible();
  await expect(company).toHaveValue("2330");
  await expect(company.locator("option:checked")).toHaveText("2330 · 台積電");
  await page.getByLabel("Evidence URL").fill("https://example.com/evidence");
  await page.getByRole("button", { name: "提交 Evidence" }).click();
  await expect(page.getByRole("status")).toContainText("已接收");
  await page.getByRole("button", { name: "重新整理狀態" }).click();
  await expect(page.getByRole("status")).toContainText("已完成");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("company creation flow is responsive", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "建立新公司" }).click();
  await page.getByLabel("股票代號").fill("2454");
  await page.getByLabel("公司名稱").fill("聯發科");
  await page.getByLabel("Evidence URL").fill("https://example.com/new");
  await page.getByRole("button", { name: "建立公司並提交 Evidence" }).click();
  await expect(page.getByRole("status")).toContainText("聯發科");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
