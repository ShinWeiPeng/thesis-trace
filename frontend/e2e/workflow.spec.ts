import { expect, test } from "@playwright/test";

const action = {
  item_id: "action-1", version: 1, item_type: "anomaly_review",
  source_domain: "anomaly_assessment", source_record_id: "assessment-1", source_version: 2,
  company_id: "company-1", company_ticker: "TT", company_name: "Thesis Trace",
  reason: "Review the immutable anomaly", status: "pending", system_priority: "high",
  effective_priority: "high", safety_floor: null, safety_locked: false,
  priority_rule_ids: ["workflow.shadow-anomaly-review-v1"],
  priority_policy_version: "action-priority-v1", priority_reason: "Shadow anomaly requires Owner review.",
  created_at: "2026-08-24T00:00:00Z", updated_at: "2026-08-24T00:00:00Z",
  due_at: null, defer_until: null, recurrence_of: null,
  allowed_transitions: ["in_progress", "deferred", "completed", "dismissed"],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", (route) => route.fulfill({ json: {
    kind: "owner", user_id: "owner", display_name: "Owner",
    session_expires_at: "2030-01-01T00:00:00Z", is_recovery_session: false,
    capabilities: ["research"],
  } }));
  await page.route("**/api/action-items**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/transitions")) return route.fulfill({ json: { ...action, version: 2, status: "completed", allowed_transitions: [] } });
    if (url.pathname === "/api/action-items/action-1") return route.fulfill({ json: action });
    return route.fulfill({ json: {
      summary: { urgent: 1, due_today: 0, deferred: 0, all_open: 1 }, total_count: 1,
      items: [action], next_cursor: null, as_of: "2026-08-24T00:00:00Z",
    } });
  });
});

test("signed-query inbox keeps list context and transitions responsively", async ({ page, isMobile }) => {
  let transitionBody: Record<string, unknown> | undefined;
  await page.route("**/api/action-items/action-1/transitions", async (route) => {
    transitionBody = await route.request().postDataJSON();
    await route.fulfill({ json: { ...action, version: 2, status: "completed", allowed_transitions: [] } });
  });
  await page.goto("/actions/action-1?return=search%3DTT%26open_only%3Dtrue");
  await expect(page.getByRole("heading", { name: "Action Inbox" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "TT · Thesis Trace" })).toBeVisible();
  await expect(page.getByText("緊急 1")).toBeVisible();
  if (isMobile) await expect(page.getByRole("region", { name: "待辦清單" })).toBeHidden();
  await expect(page.getByRole("link", { name: "開啟公司脈絡" })).toHaveAttribute("href", /fromAction=action-1/);
  await page.getByLabel("處理理由").fill("Reviewed against primary evidence");
  await page.getByRole("button", { name: "完成" }).click();
  await expect(page.locator(".action-detail .status-completed")).toHaveText("已完成");
  expect(transitionBody).toMatchObject({ expected_version: 1, target_status: "completed", reason: "Reviewed against primary evidence" });
  expect(transitionBody).not.toHaveProperty("priority");
  expect(transitionBody).not.toHaveProperty("assignee_user_id");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
