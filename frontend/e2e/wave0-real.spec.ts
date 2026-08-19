import { expect, test } from "@playwright/test";

test("real Company Evidence path reaches succeeded through PostgreSQL and worker process", async ({ page }, testInfo) => {
  const ticker = testInfo.project.name === "mobile" ? "2454" : "2330";
  await page.goto("/");
  await page.getByRole("button", { name: "建立新公司" }).click();
  await page.getByLabel("股票代號").fill(ticker);
  await page.getByLabel("公司名稱").fill("台積電");
  await page.getByLabel("Evidence URL").fill("https://example.com/fixture");
  await page.getByRole("button", { name: "建立公司並提交 Evidence" }).click();
  await expect(page.getByRole("status")).toContainText("已接收");
  await expect.poll(async () => {
    await page.getByRole("button", { name: "重新整理狀態" }).click();
    return page.getByRole("status").textContent();
  }).toContain("已完成");
  const evidenceId = await page.locator(".status-card dd").nth(1).textContent();
  const evidence = await page.request.get(`/acceptance/evidence/${evidenceId}`);
  const evidenceState = await evidence.json();
  expect(evidenceState).toMatchObject({ audit_events: 1, collection_jobs: 1 });
  expect(evidenceState.provenance).not.toBeNull();
});
