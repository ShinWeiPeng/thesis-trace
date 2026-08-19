import { expect, test } from "@playwright/test";

const admin = { kind: "admin", user_id: "admin", display_name: "Admin", session_expires_at: "2030-01-01T00:00:00Z", is_recovery_session: false, capabilities: ["accounts"] };
const owner = { ...admin, kind: "owner", user_id: "owner", display_name: "Owner" };
test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", (route) => route.request().method() === "DELETE" ? route.fulfill({ status: 204 }) : route.fulfill({ json: page.url().includes("/admin/accounts") ? owner : admin }));
  await page.route("**/api/confirmation-challenges", (route) => route.fulfill({ json: { challenge_token: "never-persist", expires_at: "2030-01-01T00:05:00Z", target_version: 3, impact_summary: { subject: "停用 Learner", action_label: "確認高風險操作", before: { status: "active" }, after: { status: "disabled" }, consequences: ["工作階段將失效"], confirmation_verb: "確認停用" } } }));
  await page.route("**/api/confirmed-actions", (route) => route.fulfill({ json: { accepted: true, challenge_id: "c-1" } }));
  await page.route("**/api/admin/accounts/u-1", (route) => route.fulfill({ json: { user_id: "u-1", masked_identity: "Learner", role: "learner", status: "active", version: 3 } }));
});

test("Admin deep link is non-disclosing and responsive", async ({ page }) => {
  await page.goto("/companies/private"); await expect(page.getByRole("heading", { name: "資源無法使用" })).toBeVisible();
  await expect(page.getByText("private")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("confirmation is explicit and leaves no browser storage", async ({ page }) => {
  await page.goto("/admin/accounts/u-1"); await page.getByRole("button", { name: "停用帳號" }).click();
  await expect(page.getByRole("dialog")).toContainText("目標版本");
  await expect(page.getByRole("button", { name: "確認停用" })).toBeDisabled();
  await page.getByLabel("原因").fill("帳號離職"); await page.getByRole("button", { name: "確認停用" }).click();
  expect(await page.evaluate(async () => ({ local: localStorage.length, session: sessionStorage.length, caches: "caches" in window ? (await caches.keys()).length : 0, url: location.href }))).toEqual({ local: 0, session: 0, caches: 0, url: expect.not.stringContaining("never-persist") });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
