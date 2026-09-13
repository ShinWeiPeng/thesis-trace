import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ThesisResponse } from "../generated/api";
import type { ThesisClient } from "./client";
import { ThesisRoutes } from "./routes";

const thesis = {
  thesis_id: "thesis-1", version: 1, owner_user_id: "owner-1", company_id: "company-1",
  company_version: 1, title: "AI 伺服器需求", narrative: "需求支持長期現金流。", status: "draft" as const,
  cycle: 1, reflection_pending: false, created_at: "2026-08-29T03:00:00+00:00",
  updated_at: "2026-08-29T03:00:00+00:00", conditions: [{ summary: "營收連續兩季衰退" }],
  evidence_refs: [], outcome: null, reflection: null, reflection_draft: null,
  valuation_draft: null, valuation_snapshots: [],
  policy_version: "thesis-lifecycle-v1",
};

const thesisWithValuation = {
  ...thesis,
  version: 2,
  valuation_draft: {
    version: 1,
    method: "pe",
    benchmark_source: "company_history",
    benchmark_variant: "p75",
    distribution: { median: "27.5", p75: "36.25", coverage: "limited_history", sample_count: 36 },
    validity: { target_date: "2027-08-29", expires_at: "2026-10-01T00:00:00+00:00" },
    result: { target_price: "435.00", annualized_return: "3.232303921568627" },
    cost_profile_version: 2,
    company_history: {
      data_start: "2023-01-01", data_end: "2025-12-01", exclusions: ["pe-history-old:nonpositive_denominator"],
      valid_samples: [{ source: { record_id: "evidence-history", version: 3, fact_id: "pe-history-1" } }],
      distribution: {
        median: "27.5", p75: "36.25", coverage: "limited_history", sample_count: 36,
        sorted_samples: ["12", "27.5", "36.25"], p75_position: "27.25",
        p75_lower_index: 27, p75_upper_index: 28, p75_interpolation_fraction: "0.25",
      },
    },
    peer_group: {
      data_start: "2026-08-29", data_end: "2026-08-29", exclusions: [],
      valid_samples: [{ source: { record_id: "evidence-peer", version: 3, fact_id: "pe-peer" } }],
      distribution: {
        median: "23", p75: "24", coverage: "standard_history", sample_count: 5,
        sorted_samples: ["20", "22", "23", "24", "25"], p75_position: "4",
        p75_lower_index: 4, p75_upper_index: 4, p75_interpolation_fraction: "0",
      },
    },
    benchmark_difference_p75: "12.25",
    source_selection_reason: "採用已保存且可重現的來源樣本",
  },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function client(): ThesisClient {
  return {
    listCompanies: vi.fn().mockResolvedValue([{ company_id: "company-1", ticker: "TT", name: "Thesis Trace", version: 1 }]),
    list: vi.fn().mockResolvedValue([thesis]), get: vi.fn().mockResolvedValue(thesis),
    create: vi.fn().mockResolvedValue({ ...thesis, thesis_id: "thesis-2", title: "新 Thesis" }),
    save: vi.fn(), previewTransition: vi.fn(), transition: vi.fn(), saveOutcome: vi.fn(),
    autosaveReflection: vi.fn(), completeReflection: vi.fn(),
    saveValuation: vi.fn(), previewValuationPublication: vi.fn(), publishValuation: vi.fn(),
  };
}

describe("ThesisRoutes", () => {
  it("lists independent thesis cards and creates a server-owned draft", async () => {
    const api = client(); const user = userEvent.setup();
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses" />);
    expect(await screen.findByText("AI 伺服器需求")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "建立 Thesis" }));
    await user.type(screen.getByLabelText("Thesis 標題"), "新 Thesis");
    await user.type(screen.getByLabelText("研究假設"), "新的可驗證研究假設");
    await user.type(screen.getByLabelText("失效條件"), "營收衰退");
    await user.type(screen.getByLabelText("建立理由"), "建立研究週期");
    await user.click(screen.getByRole("button", { name: "儲存草稿" }));
    expect(api.create).toHaveBeenCalledWith("company-1", expect.objectContaining({
      company_version: 1, title: "新 Thesis", invalidation_conditions: ["營收衰退"],
    }));
  });

  it("explains that a completion reason is missing instead of silently disabling Reflection completion", async () => {
    const api = client(); const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({ ...thesis, status: "invalidated", reflection_pending: true });
    vi.mocked(api.completeReflection).mockResolvedValue({
      ...thesis, status: "invalidated", reflection_pending: false, version: 2,
    });
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/outcomes" />);

    await screen.findByRole("heading", { name: "Reflection" });
    await user.type(screen.getByLabelText("原始假設"), "原本認為需求會持續成長");
    await user.type(screen.getByLabelText("判斷錯誤"), "忽略成長率下滑");
    await user.type(screen.getByLabelText("遺漏證據"), "未追蹤客戶資本支出");
    await user.type(screen.getByLabelText("下次改進"), "加入季度資本支出檢查");
    await user.click(screen.getByRole("button", { name: "完成 Reflection" }));

    const dialog = await screen.findByRole("alertdialog", { name: "尚未填寫 Reflection 完成理由" });
    expect(api.completeReflection).not.toHaveBeenCalled();

    const returnButton = screen.getByRole("button", { name: "返回填寫" });
    await waitFor(() => expect(returnButton).toHaveFocus());
    await user.tab();
    expect(returnButton).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(dialog).not.toBeInTheDocument();
    const reason = screen.getByLabelText("Reflection 完成理由");
    expect(reason).toHaveFocus();
    await user.type(reason, "記錄本次研究學習");
    await user.click(screen.getByRole("button", { name: "完成 Reflection" }));
    expect(api.completeReflection).toHaveBeenCalledWith("thesis-1", expect.objectContaining({
      reason: "記錄本次研究學習",
    }));
  });

  it("restores all four Reflection draft fields from the server projection", async () => {
    const api = client();
    vi.mocked(api.get).mockResolvedValue({
      ...thesis,
      reflection_draft: {
        revision: 4, cycle: 1, original_assumption: "原始假設草稿",
        judgment_errors: "判斷錯誤草稿", missing_evidence: "遺漏證據草稿",
        improvement: "下次改進草稿", saved_at: "2026-08-29T03:00:00+00:00",
      },
    });
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/outcomes" />);
    expect(await screen.findByLabelText("原始假設")).toHaveValue("原始假設草稿");
    expect(screen.getByLabelText("判斷錯誤")).toHaveValue("判斷錯誤草稿");
    expect(screen.getByLabelText("遺漏證據")).toHaveValue("遺漏證據草稿");
    expect(screen.getByLabelText("下次改進")).toHaveValue("下次改進草稿");
    expect(screen.getByRole("link", { name: "Outcomes / Reflections" })).toHaveAttribute("aria-current", "page");
  });

  it("autosaves every dirty Reflection field with sequential server revisions", async () => {
    const api = client(); const user = userEvent.setup();
    const invalidated = { ...thesis, status: "invalidated" as const, reflection_pending: true };
    vi.mocked(api.get).mockResolvedValue(invalidated);
    vi.mocked(api.autosaveReflection)
      .mockResolvedValueOnce({ ...invalidated, reflection_draft: {
        revision: 1, cycle: 1, original_assumption: "假設 A", judgment_errors: "",
        missing_evidence: "", improvement: "", saved_at: "2026-08-29T03:01:00+00:00",
      } })
      .mockResolvedValueOnce({ ...invalidated, reflection_draft: {
        revision: 2, cycle: 1, original_assumption: "假設 A", judgment_errors: "錯誤 B",
        missing_evidence: "", improvement: "", saved_at: "2026-08-29T03:02:00+00:00",
      } });
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/outcomes" />);
    await user.type(await screen.findByLabelText("原始假設"), "假設 A");
    await user.type(screen.getByLabelText("判斷錯誤"), "錯誤 B");
    await waitFor(() => expect(api.autosaveReflection).toHaveBeenCalledTimes(2), { timeout: 4000 });
    expect(api.autosaveReflection).toHaveBeenNthCalledWith(1, "thesis-1", expect.objectContaining({
      expected_draft_version: 0, field: "original_assumption", text: "假設 A",
    }));
    expect(api.autosaveReflection).toHaveBeenNthCalledWith(2, "thesis-1", expect.objectContaining({
      expected_draft_version: 1, field: "judgment_errors", text: "錯誤 B",
    }));
    expect(await screen.findByText(/已由伺服器儲存草稿/)).toBeVisible();
  });

  it("keeps a newer same-field edit queued while an older autosave is in flight", async () => {
    const api = client(); const user = userEvent.setup(); const first = deferred<ThesisResponse>();
    const invalidated = { ...thesis, status: "invalidated" as const, reflection_pending: true };
    vi.mocked(api.get).mockResolvedValue(invalidated);
    vi.mocked(api.autosaveReflection)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ ...invalidated, reflection_draft: {
        revision: 2, cycle: 1, original_assumption: "AB", judgment_errors: "",
        missing_evidence: "", improvement: "", saved_at: "2026-08-29T03:02:00+00:00",
      } });
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/outcomes" />);
    const assumption = await screen.findByLabelText("原始假設");
    await user.type(assumption, "A");
    await waitFor(() => expect(api.autosaveReflection).toHaveBeenCalledTimes(1), { timeout: 4000 });
    await user.type(assumption, "B");
    first.resolve({ ...invalidated, reflection_draft: {
      revision: 1, cycle: 1, original_assumption: "A", judgment_errors: "",
      missing_evidence: "", improvement: "", saved_at: "2026-08-29T03:01:00+00:00",
    } });
    expect(assumption).toHaveValue("AB");
    await waitFor(() => expect(api.autosaveReflection).toHaveBeenCalledTimes(2), { timeout: 4000 });
    expect(api.autosaveReflection).toHaveBeenNthCalledWith(2, "thesis-1", expect.objectContaining({
      expected_draft_version: 1, field: "original_assumption", text: "AB",
    }));
  });

  it("requires an explicit retry after an offline autosave failure", async () => {
    const api = client(); const user = userEvent.setup();
    const invalidated = { ...thesis, status: "invalidated" as const, reflection_pending: true };
    vi.mocked(api.get).mockResolvedValue(invalidated);
    vi.mocked(api.autosaveReflection).mockResolvedValue({ ...invalidated, reflection_draft: {
      revision: 1, cycle: 1, original_assumption: "離線草稿", judgment_errors: "",
      missing_evidence: "", improvement: "", saved_at: "2026-08-29T03:01:00+00:00",
    } });
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/outcomes" />);
    await user.type(await screen.findByLabelText("原始假設"), "離線草稿");
    const retry = await screen.findByRole("button", { name: "重新嘗試儲存草稿" }, { timeout: 4000 });
    expect(api.autosaveReflection).not.toHaveBeenCalled();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
    await new Promise((resolve) => setTimeout(resolve, 2200));
    expect(api.autosaveReflection).not.toHaveBeenCalled();
    await user.click(retry);
    await waitFor(() => expect(api.autosaveReflection).toHaveBeenCalledTimes(1), { timeout: 4000 });
  }, 10000);

  it("provides a direct Valuation route for the selected Thesis", async () => {
    const api = client();
    vi.mocked(api.get).mockResolvedValue(thesisWithValuation);
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/valuation" />);
    expect(await screen.findByRole("link", { name: "Valuation" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "估值" })).toBeVisible();
  });

  it("presents a human-readable valuation comparison instead of raw JSON", async () => {
    const api = client();
    vi.mocked(api.get).mockResolvedValue(thesisWithValuation);
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/valuation" />);

    const heading = await screen.findByRole("heading", { name: "目前估值草稿" });
    const summary = heading.closest("section");
    expect(summary).not.toBeNull();
    expect(within(summary!).getByText("目標價")).toBeVisible();
    expect(within(summary!).getByText("NT$ 435.00")).toBeVisible();
    expect(within(summary!).getByRole("heading", { name: "自身歷史" })).toBeVisible();
    expect(within(summary!).getByRole("heading", { name: "同業群組" })).toBeVisible();
    expect(within(summary!).getByText("有限歷史（36–59 個月）")).toBeVisible();
    expect(within(summary!).getByText("2023-01-01 至 2025-12-01")).toBeVisible();
    expect(within(summary!).getByText(/pe-history-old：分母非正值/)).toBeVisible();
    expect(within(summary!).getByText(/Evidence evidence-history v3/)).toBeVisible();
    expect(within(summary!).getByText(/第 27.25 個位置/)).toBeVisible();
    expect(within(summary!).getByText("已扣除交易成本與證交稅；未計個人綜合所得稅及補充保費。")).toBeVisible();
    expect(within(summary!).queryByText(/"target_price"/)).not.toBeInTheDocument();
  });

  it("shows the server impact summary and keeps publication confirmation keyboard accessible", async () => {
    const api = client(); const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue(thesisWithValuation);
    vi.mocked(api.previewValuationPublication).mockResolvedValue({
      target_version: 2, draft_version: 1, challenge_token: "challenge-1",
      challenge_expires_at: "2026-08-29T03:05:00+00:00",
      impact_summary: {
        subject: "thesis-1", action_label: "發布不可變估值快照",
        before: { thesis_version: "2", draft_version: "1" },
        after: { target_price: "435.00", outcome: "valued" },
        consequences: ["估值方法、來源、成本版本與計算 trace 將不可變保存"],
        confirmation_verb: "發布估值",
      },
    });
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/valuation" />);

    const previewButton = await screen.findByRole("button", { name: "預覽發布" });
    await user.click(previewButton);
    const dialog = await screen.findByRole("dialog", { name: "發布不可變估值快照" });
    expect(within(dialog).getByText("目標 Thesis：thesis-1")).toBeVisible();
    expect(within(dialog).getByText("Thesis v2 · 草稿 v1")).toBeVisible();
    expect(within(dialog).getByText("NT$ 435.00")).toBeVisible();
    expect(within(dialog).getByText("估值方法、來源、成本版本與計算 trace 將不可變保存")).toBeVisible();
    const reason = within(dialog).getByLabelText("發布理由");
    await waitFor(() => expect(reason).toHaveFocus());
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(within(dialog).getByRole("button", { name: "取消" })).toHaveFocus();
    await user.tab();
    expect(reason).toHaveFocus();
    await user.type(reason, "確認發布");
    await user.tab();
    expect(within(dialog).getByRole("button", { name: "取消" })).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole("button", { name: "發布估值" })).toHaveFocus();
    await user.tab();
    expect(reason).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(dialog).not.toBeInTheDocument();
    expect(previewButton).toHaveFocus();
  });

  it("closes a stale publication dialog and asks for a fresh preview", async () => {
    const api = client(); const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue(thesisWithValuation);
    vi.mocked(api.previewValuationPublication).mockResolvedValue({
      target_version: 2, draft_version: 1, challenge_token: "challenge-1",
      challenge_expires_at: "2026-08-29T03:05:00+00:00", impact_summary: {},
    });
    vi.mocked(api.publishValuation).mockRejectedValue(new Error("challenge_invalid"));
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/valuation" />);

    await user.click(await screen.findByRole("button", { name: "預覽發布" }));
    const dialog = await screen.findByRole("dialog", { name: "發布不可變估值快照" });
    await user.type(within(dialog).getByLabelText("發布理由"), "確認發布");
    await user.click(within(dialog).getByRole("button", { name: "發布估值" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("發布條件已改變或確認已逾期");
    expect(alert).toHaveTextContent("重新預覽");
    expect(alert).not.toHaveTextContent("challenge_invalid");
  });

  it("explains how to recalculate when the Cost Profile changed", async () => {
    const api = client(); const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue(thesisWithValuation);
    vi.mocked(api.previewValuationPublication).mockRejectedValue(new Error("cost_profile_version_conflict"));
    render(<ThesisRoutes client={api} companyId="company-1" initialPath="/companies/company-1/theses/thesis-1/valuation" />);

    await user.click(await screen.findByRole("button", { name: "預覽發布" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("成本設定已更新");
    expect(alert).toHaveTextContent("重新儲存並計算估值草稿");
    expect(alert).not.toHaveTextContent("cost_profile_version_conflict");
  });
});
