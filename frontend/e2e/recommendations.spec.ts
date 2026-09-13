import { expect, test } from "@playwright/test";

test("Owner follows the exact Inbox source, sees risk, confirms with a reason and returns", async ({
  page,
}, testInfo) => {
  let decided = false;
  const decisionBodies: Record<string, unknown>[] = [];
  const view = () => ({
    record_id: "record",
    version: 1,
    decision_sequence: decided ? 1 : 0,
    decision_status: decided ? "accepted" : null,
    input_validity: "valid",
    allowed_actions: decided ? [] : ["accept", "reject", "defer"],
    reason_codes: [],
  });
  const task = () => ({
    item_id: "task",
    version: decided ? 2 : 1,
    item_type: "recommendation_decision",
    source_domain: "recommendation",
    source_record_id: "record",
    source_version: 1,
    company_id: "company",
    company_ticker: "2330",
    company_name: "測試公司",
    reason: "請核對建議",
    status: decided ? "completed" : "pending",
    system_priority: "normal",
    effective_priority: "normal",
    safety_floor: null,
    safety_locked: false,
    priority_rule_ids: ["workflow.recommendation-decision-v1"],
    priority_policy_version: "action-priority-v1",
    priority_reason: "需要 Owner 作成決策",
    created_at: "2026-09-05T00:00:00Z",
    updated_at: "2026-09-05T00:00:00Z",
    due_at: null,
    defer_until: null,
    recurrence_of: null,
    allowed_transitions: decided
      ? []
      : ["in_progress", "deferred", "dismissed"],
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = async (value: unknown) => route.fulfill({ json: value });
    if (path === "/api/session")
      return json({
        kind: "owner",
        user_id: "owner",
        display_name: "Owner",
        session_expires_at: "2099-01-01T00:00:00Z",
        is_recovery_session: false,
        capabilities: ["research"],
      });
    if (path === "/api/action-items/task") return json(task());
    if (path === "/api/action-items")
      return json({
        summary: {
          urgent: 0,
          due_today: 0,
          deferred: 0,
          all_open: decided ? 0 : 1,
        },
        total_count: decided ? 0 : 1,
        items: decided ? [] : [task()],
        next_cursor: null,
        as_of: "2026-09-05T00:00:00Z",
      });
    if (path === "/api/companies/company/theses") return json([]);
    if (path === "/api/portfolio")
      return json({
        version: 2,
        cash: "20000",
        cash_as_of: null,
        cost_profile: { version: 1 },
        exposure: {},
        holdings: [],
        trades: [],
        corrections: [],
        company_actions: [],
        updated_at: "2026-09-05T00:00:00Z",
      });
    if (path === "/api/companies/company/recommendation-requests")
      return json({ items: [], next_cursor: null });
    if (path === "/api/recommendations/record/decision-previews")
      return json({
        view: view(),
        challenge_token: "test-only-token",
        expires_at: "2099-09-05T00:05:00Z",
        impact_summary: "接受這份建議，結束審查待辦；不會建立交易或扣除現金。",
      });
    if (path === "/api/recommendations/record/decisions") {
      decisionBodies.push(route.request().postDataJSON());
      decided = true;
      return json(view());
    }
    if (path === "/api/recommendations/record/versions/1")
      return json({
        view: view(),
        company_id: "company",
        thesis_id: "thesis",
        thesis_title: "需求支持長期獲利",
        published_at: "2026-09-05T00:00:00Z",
        checked_at: "2026-09-05T00:01:00Z",
        direction: "buy",
        publication_reasons: [],
        raw_ceiling: "1",
        final_multiplier: "0.5",
        annualized_return: "0.06",
        minimum_return: "0.05",
        benchmark_source: "company_history",
        source_selection_reason: "核對公司歷史與同儕後採用公司歷史",
        valuation_id: "valuation",
        portfolio_snapshot_id: "risk",
        sources: [
          {
            snapshot_id: "snapshot",
            publisher: "官方公開資訊",
            excerpt: "這是瀏覽器測試的固定來源摘錄，不是真實投資建議。",
            url: "https://example.test/source",
            category: "A",
            lineage: "original-report",
            published_at: null,
            retrieved_at: "2026-09-05T00:00:00Z",
          },
        ],
        claims: [{ text: "固定測試主張", citations: ["snapshot"] }],
        decisions: decided
          ? [
              {
                sequence: 1,
                status: "accepted",
                reason: "已確認來源與風險",
                recorded_at: "2026-09-05T00:02:00Z",
                defer_until: null,
                confirmation_id: "test-confirmation",
                checks: [],
              },
            ]
          : [],
        next_decision_sequence: null,
        facts: [{ label: "成本設定版本", value: "1" }],
        risk: [
          {
            dimension: "個股",
            subject: "2330",
            current_ratio: "0.04",
            projected_ratio: "0.08",
            limit_ratio: "0.1",
          },
        ],
      });
    return route.fulfill({
      status: 404,
      json: { detail: "unexpected_test_route" },
    });
  });
  await page.goto("/actions/task?return=search%3D2330%26open_only%3Dtrue");
  await page.getByRole("link", { name: "開啟建議與人工決策" }).click();
  await expect(page).toHaveURL(
    /\/companies\/company\/recommendations\?.*sourceRecord=record/,
  );
  await expect(
    page.getByRole("heading", { name: "需求支持長期獲利" }),
  ).toBeVisible();
  await expect(page.getByText("8.00%")).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "接受建議" }).click();
  const prompt = page.getByRole("alertdialog");
  await expect(prompt).toContainText("請填寫決策理由");
  await prompt.getByRole("button", { name: "返回填寫" }).click();
  await expect(page.getByLabel("決策理由")).toBeFocused();
  await page.getByLabel("決策理由").fill("已確認來源與風險");
  await page.getByRole("button", { name: "接受建議" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("不會建立交易或扣除現金");
  await page.screenshot({
    path: testInfo.outputPath("decision-preview.png"),
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "取消" }).click();
  expect(decisionBodies).toHaveLength(0);
  await page.getByRole("button", { name: "接受建議" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "確認決策" })
    .click();
  await expect(page.getByText("#1 已接受")).toBeVisible();
  expect(decisionBodies).toHaveLength(1);
  expect(decisionBodies[0]).toMatchObject({
    version: 1,
    expected_sequence: 0,
    reason: "已確認來源與風險",
    challenge_token: "test-only-token",
  });
  expect(decisionBodies[0]).not.toHaveProperty("actor_id");
  await page.getByRole("link", { name: "返回原待辦" }).click();
  await expect(page).toHaveURL(
    /\/actions\/task\?return=search%3D2330%26open_only%3Dtrue/,
  );
  await expect(page.locator(".action-detail .status-completed")).toHaveText(
    "已完成",
  );
});

for (const role of ["learner", "admin"]) {
  test(`${role} cannot open the Owner recommendation workspace`, async ({
    page,
  }) => {
    const forbiddenRequests: string[] = [];
    await page.route("**/api/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/session")
        return route.fulfill({
          json: {
            kind: role,
            user_id: role,
            display_name: role,
            capabilities: [],
            session_expires_at: "2099-01-01T00:00:00Z",
          },
        });
      forbiddenRequests.push(path);
      return route.abort();
    });
    await page.goto(
      "/companies/company/recommendations?record=record&version=1",
    );
    await expect(
      page.getByRole("heading", { name: "資源無法使用" }),
    ).toBeVisible();
    expect(forbiddenRequests).toHaveLength(0);
  });
}
