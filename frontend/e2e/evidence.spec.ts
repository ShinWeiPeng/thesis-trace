import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", (route) => route.fulfill({ json: { kind: "owner", user_id: "owner", display_name: "Owner", session_expires_at: "2030-01-01T00:00:00Z", is_recovery_session: false, capabilities: ["research"] } }));
  await page.route("**/api/companies", async (route) => {
    if (route.request().method() === "POST") return route.fulfill({ json: { company_id: "2454", ticker: "2454", name: "聯發科", version: 1 }, status: 201 });
    return route.fulfill({ json: [{ company_id: "2330", ticker: "2330", name: "台積電", version: 4 }] });
  });
  await page.route("**/api/evidence", (route) => route.fulfill({ json: { evidence_id: "evidence-1", version: 1, status: "received" }, status: 202 }));
  await page.route("**/api/evidence/evidence-1", (route) => route.fulfill({ json: { evidence_id: "evidence-1", source_snapshot_id: "snapshot-1", version: 2, status: "succeeded" } }));
  await page.route("**/api/evidence/evidence-1/stage", (route) => route.fulfill({ json: { code: "not_found" }, status: 404 }));
});

test("Owner confirms facts and sees the server-derived stage", async ({ page }) => {
  let submittedBody: Record<string, unknown> | undefined;
  await page.route("**/api/evidence/evidence-1/stage-confirmations", async (route) => {
    submittedBody = await route.request().postDataJSON();
    await route.fulfill({ status: 201, json: {
      actor_id: "owner", confirmed_at: "2026-08-20T00:00:00Z", evidence_id: "evidence-1",
      facts: (submittedBody as { facts: Record<string, unknown> }).facts,
      gate_trace: [{ gate: "E0", passed: true, code: "confirmed_source" }, { gate: "E1", passed: true, code: "product_established" }, { gate: "E2", passed: true, code: "commercialization_established" }, { gate: "E3", passed: true, code: "identifiable_revenue" }, { gate: "E4", passed: false, code: "profit_or_cash_flow_not_identifiable" }],
      policy_version: "e-stage-v1", reason: "official filing reviewed", source_snapshot_id: "snapshot-1", stage: "E3", version: 1,
    } });
  });
  await page.goto("/");
  await page.getByLabel("Evidence URL").fill("https://example.com/evidence");
  await page.getByRole("button", { name: "提交 Evidence" }).click();
  await page.getByRole("button", { name: "重新整理狀態" }).click();
  await page.getByLabel("來源確認").selectOption("official");
  await page.getByLabel("已建立產品").check();
  await page.getByLabel("已建立商業化").check();
  await page.getByLabel("確認理由").fill("official filing reviewed");
  await page.getByRole("button", { name: "確認事實並儲存階段" }).click();

  await expect(page.getByLabel("伺服器推導階段")).toHaveText("E3");
  await expect(page.getByText("由伺服器依 e-stage-v1 推導")).toBeVisible();
  expect(submittedBody).not.toHaveProperty("stage");
  expect(submittedBody).toMatchObject({ expected_version: 0, source_snapshot_id: "snapshot-1" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("Learner sees the server stage without confirmation controls", async ({ page }) => {
  await page.route("**/api/session", (route) => route.fulfill({ json: { kind: "learner", user_id: "learner", display_name: "Learner", session_expires_at: "2030-01-01T00:00:00Z", is_recovery_session: false, capabilities: ["research"] } }));
  await page.route("**/api/evidence/evidence-1/stage", (route) => route.fulfill({ json: {
    actor_id: "owner", confirmed_at: "2026-08-20T00:00:00Z", evidence_id: "evidence-1",
    facts: { source_confirmation: "official", product_established: true, commercialization_established: true, identifiable_revenue: false, identifiable_profit_or_cash_flow: false, consecutive_financial_quarters: 0 },
    gate_trace: [{ gate: "E1", passed: true, code: "passed" }, { gate: "E2", passed: true, code: "passed" }, { gate: "E3", passed: true, code: "passed" }, { gate: "E4", passed: false, code: "predicate_unmet" }],
    policy_version: "e-stage-v1", reason: "reviewed", source_snapshot_id: "snapshot-1", stage: "E3", version: 1,
  } }));
  await page.goto("/");
  await page.getByLabel("Evidence URL").fill("https://example.com/evidence");
  await page.getByRole("button", { name: "提交 Evidence" }).click();
  await page.getByRole("button", { name: "重新整理狀態" }).click();

  await expect(page.getByLabel("伺服器推導階段")).toHaveText("E3");
  await expect(page.getByRole("button", { name: "確認事實並儲存階段" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
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
