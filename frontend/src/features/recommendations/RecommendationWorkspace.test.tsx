import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import type { RecommendationClient } from "./client";
import type {
  RecommendationDetailView,
  ThesisResponse,
} from "../../generated/api";
import { RecommendationWorkspace } from "./RecommendationWorkspace";

const thesis: ThesisResponse = {
  thesis_id: "thesis",
  company_id: "company",
  company_version: 1,
  owner_user_id: "owner",
  version: 3,
  title: "伺服器需求",
  narrative: "長期需求",
  status: "active",
  cycle: 1,
  reflection_pending: false,
  created_at: "2026-09-05T00:00:00Z",
  updated_at: "2026-09-05T00:00:00Z",
  conditions: [],
  evidence_refs: [],
  outcome: null,
  reflection: null,
  reflection_draft: null,
  valuation_draft: null,
  valuation_snapshots: [
    {
      valuation_id: "valuation",
      version: 1,
      draft: { benchmark_source: "company_history" },
    },
  ],
  policy_version: "thesis-lifecycle-v1",
};
const detail: RecommendationDetailView = {
  view: {
    record_id: "record",
    version: 1,
    decision_status: null,
    decision_sequence: 0,
    input_validity: "valid",
    allowed_actions: ["accept", "reject", "defer"],
    reason_codes: [],
  },
  company_id: "company",
  thesis_id: "thesis",
  thesis_title: "伺服器需求",
  published_at: "2026-09-05T00:00:00Z",
  checked_at: "2026-09-05T00:01:00Z",
  direction: "buy",
  publication_reasons: [],
  raw_ceiling: "1",
  final_multiplier: "0.5",
  annualized_return: "0.06",
  minimum_return: "0.05",
  benchmark_source: "company_history",
  source_selection_reason: "比較後採用公司歷史",
  valuation_id: "valuation",
  portfolio_snapshot_id: "risk",
  sources: [
    {
      snapshot_id: "source",
      publisher: "官方公告",
      excerpt: "可核對的摘要",
      url: "https://example.test/source",
      category: "A",
      lineage: "report",
      published_at: null,
      retrieved_at: "2026-09-05T00:00:00Z",
    },
  ],
  claims: [{ text: "需求支持獲利", citations: ["source"] }],
  decisions: [],
  next_decision_sequence: null,
  facts: [{ label: "成本設定版本", value: "2" }],
  risk: [
    {
      dimension: "個股",
      subject: "2330",
      current_ratio: "0.04",
      projected_ratio: "0.08",
      limit_ratio: "0.1",
    },
  ],
};
function fixture(): RecommendationClient {
  return {
    list: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    theses: vi.fn().mockResolvedValue([thesis]),
    portfolio: vi.fn().mockResolvedValue({
      version: 2,
      cash: "20000",
      cash_as_of: null,
      cost_profile: { version: 2 },
      exposure: {},
      holdings: [],
      trades: [],
      corrections: [],
      company_actions: [],
      updated_at: "2026-09-05T00:00:00Z",
    }),
    request: vi.fn().mockResolvedValue({
      request_id: "new",
      thesis_id: "thesis",
      status: "pending",
      error_code: null,
      result_version: null,
      submitted_at: "2026-09-05T00:00:00Z",
    }),
    status: vi.fn().mockResolvedValue({
      request_id: "record",
      thesis_id: "thesis",
      status: "succeeded",
      error_code: null,
      result_version: 1,
      submitted_at: "2026-09-05T00:00:00Z",
    }),
    detail: vi.fn().mockResolvedValue(detail),
    preview: vi.fn().mockResolvedValue({
      view: detail.view,
      challenge_token: "exact-token",
      expires_at: "2099-09-05T00:05:00Z",
      impact_summary: "接受後結束待辦，不會建立交易。",
    }),
    decide: vi.fn().mockResolvedValue({
      ...detail.view,
      decision_status: "accepted",
      decision_sequence: 1,
      allowed_actions: [],
    }),
  };
}
const path =
  "/companies/company/recommendations?record=record&version=1&fromAction=task&return=status%3Dpending";

describe("Recommendation workspace", () => {
  it.each([
    ["接受建議", "accepted", "已接受"],
    ["拒絕建議", "rejected", "已拒絕"],
  ] as const)(
    "renders the server-bound target and transition before %s",
    async (action, target, after) => {
      const client = fixture();
      const lines = [
        "公司／證券：2454 · 聯發科（company）",
        "目標建議：record / v1",
        "關聯 Thesis：thesis / 週期 1",
        `動作：${action}`,
        `決策狀態：已延後 → ${after}`,
        "審查待辦：結束；保留建議與決策歷史。",
        "交易與資金：不會建立交易、下單、保留或扣除現金。",
      ];
      vi.mocked(client.preview).mockResolvedValue({
        view: detail.view,
        challenge_token: "bound-summary-token",
        expires_at: "2099-09-05T00:05:00Z",
        impact_summary: lines.join("\n"),
      });
      const user = userEvent.setup();
      render(
        <RecommendationWorkspace
          client={client}
          companyId="company"
          initialPath={path}
        />,
      );
      await user.type(
        await screen.findByLabelText("決策理由"),
        "已核對本次影響",
      );
      await user.click(screen.getByRole("button", { name: action }));
      const dialog = await screen.findByRole("dialog", {
        name: "確認建議決策",
      });
      for (const line of lines) {
        expect(
          within(dialog).getByText(line, { exact: true }),
        ).toBeInTheDocument();
      }
      expect(dialog).toHaveTextContent("理由：已核對本次影響");
      expect(client.decide).not.toHaveBeenCalled();
      await user.click(
        within(dialog).getByRole("button", { name: "確認決策" }),
      );
      expect(client.decide).toHaveBeenCalledWith(
        "record",
        expect.objectContaining({
          target_status: target,
          version: 1,
          expected_sequence: 0,
          challenge_token: "bound-summary-token",
          reason: "已核對本次影響",
        }),
      );
    },
  );
  it("preserves a saved decision when its follow-up read fails", async () => {
    const client = fixture();
    vi.mocked(client.detail)
      .mockResolvedValueOnce(detail)
      .mockRejectedValue(new Error("unavailable"));
    const user = userEvent.setup();
    render(
      <RecommendationWorkspace
        client={client}
        companyId="company"
        initialPath={path}
      />,
    );
    await user.type(await screen.findByLabelText("決策理由"), "已核對風險");
    await user.click(screen.getByRole("button", { name: "接受建議" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "確認決策",
      }),
    );
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "決策已保存，但無法重新整理",
    );
    expect(client.decide).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("button", { name: "接受建議" }),
    ).not.toBeInTheDocument();
  });
  it("shows human-readable sources and frozen risk with the original Inbox return link", async () => {
    render(
      <RecommendationWorkspace
        client={fixture()}
        companyId="company"
        initialPath={path}
      />,
    );
    expect(await screen.findByText("可核對的摘要")).toBeInTheDocument();
    expect(screen.getByText("8.00%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回原待辦" })).toHaveAttribute(
      "href",
      "/actions/task?return=status%3Dpending",
    );
    expect(screen.getByText("5.00%")).toBeInTheDocument();
  });
  it("opens a reason prompt instead of silently disabling Accept", async () => {
    const user = userEvent.setup();
    const client = fixture();
    render(
      <RecommendationWorkspace
        client={client}
        companyId="company"
        initialPath={path}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "接受建議" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("請填寫決策理由");
    expect(client.preview).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "返回填寫" }));
    expect(screen.getByLabelText("決策理由")).toHaveFocus();
  });
  it("binds confirmation to the reviewed sequence and cancels without mutation", async () => {
    const user = userEvent.setup();
    const client = fixture();
    render(
      <RecommendationWorkspace
        client={client}
        companyId="company"
        initialPath={path}
      />,
    );
    await user.type(
      await screen.findByLabelText("決策理由"),
      "已核對引用與風險",
    );
    await user.click(screen.getByRole("button", { name: "接受建議" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("不會建立交易");
    await user.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(client.decide).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "接受建議" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "確認決策",
      }),
    );
    expect(client.decide).toHaveBeenCalledWith(
      "record",
      expect.objectContaining({
        expected_sequence: 0,
        version: 1,
        challenge_token: "exact-token",
        reason: "已核對引用與風險",
      }),
    );
  });
  it("explains stale inputs and offers regeneration without an acceptance action", async () => {
    const client = fixture();
    vi.mocked(client.detail).mockResolvedValue({
      ...detail,
      view: {
        ...detail.view,
        input_validity: "invalid",
        allowed_actions: [],
        reason_codes: ["input_version_changed:portfolio:owner"],
      },
    });
    render(
      <RecommendationWorkspace
        client={client}
        companyId="company"
        initialPath={path}
      />,
    );
    expect(await screen.findByText(/關鍵輸入已更新/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "接受建議" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重新建立分析請求" }),
    ).toBeInTheDocument();
  });
  it("requires an explicit benchmark and reason before submitting analysis", async () => {
    const user = userEvent.setup();
    const client = fixture();
    render(
      <RecommendationWorkspace
        client={client}
        companyId="company"
        initialPath="/companies/company/recommendations"
      />,
    );
    await screen.findByRole("option", { name: "伺服器需求" });
    await user.selectOptions(screen.getByLabelText("研究 Thesis"), "thesis");
    await user.selectOptions(
      screen.getByLabelText("重新確認估值比較來源"),
      "company_history",
    );
    await user.type(
      screen.getByLabelText("來源選擇與分析理由"),
      "已比較公司歷史與同儕",
    );
    await user.click(screen.getByRole("button", { name: "建立分析請求" }));
    await waitFor(() =>
      expect(client.request).toHaveBeenCalledWith(
        "company",
        expect.objectContaining({
          expected_thesis_version: 3,
          expected_portfolio_version: 2,
          valuation_id: "valuation",
          benchmark_source: "company_history",
        }),
      ),
    );
  });
});
