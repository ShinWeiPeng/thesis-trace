import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PortfolioClient } from "./client";
import { PortfolioRoutes } from "./routes";

const configured = {
  version: 2, cost_profile: { version: 1 }, cash: "1000", cash_as_of: "2026-08-29T05:00:00Z",
  holdings: [], trades: [], corrections: [], company_actions: [], updated_at: "2026-08-29T05:00:00Z",
  exposure: {
    nav: "1000", feasible: true, reasons: [],
    security_exposure: { "2330": "0.42" },
    industry_exposure: { 半導體: "0.42" },
    theme_exposure: { AI: "0.42" },
  },
};

function client(): PortfolioClient {
  return {
    get: vi.fn().mockResolvedValue(configured), saveCostProfile: vi.fn().mockResolvedValue(configured),
    saveCash: vi.fn().mockResolvedValue(configured),
    previewTrade: vi.fn().mockResolvedValue({
      target_version: 2, fingerprint: "fp", preview_digest: "digest", post_cash: "900", nav: "1000",
      feasible: true, reasons: [], policy_version: "trade-preview-v1", challenge_token: "token",
      challenge_expires_at: "2026-08-29T05:05:00Z",
      impact_summary: {
        subject: "2330", action_label: "確認交易與桶分配",
        before: { portfolio_version: "2" }, after: { cash: "900", nav: "1000" },
        consequences: ["交易、分配、持股、曝險與稽核將一併保存"], confirmation_verb: "確認交易",
      },
    }),
    confirmTrade: vi.fn().mockResolvedValue({ ...configured, version: 3, cash: "900" }),
    previewCsv: vi.fn().mockResolvedValue({
      trades: [{ source_kind: "csv", source_row_id: "row-1", broker_reference: null,
        security_id: "2330", side: "buy", quantity: 1, price: "100", fees: "0", tax: "0",
        executed_at: "2026-08-29T05:00:00+00:00" }],
      issues: [], policy_version: "canonical-trade-csv-v1",
    }),
    previewCorrection: vi.fn(), confirmCorrection: vi.fn(),
    previewCompanyAction: vi.fn(), confirmCompanyAction: vi.fn(),
  };
}

describe("PortfolioRoutes", () => {
  it("provides the company-scoped Trades workspace over the same portfolio record", async () => {
    render(<PortfolioRoutes client={client()} companyId="2330" />);
    expect(await screen.findByRole("heading", { name: "2330 · 交易" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Trades" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByLabelText("證券代號")).toHaveValue("2330");
  });

  it("shows server preview and requires a reason before confirmed trade", async () => {
    const api = client(); const user = userEvent.setup();
    render(<PortfolioRoutes client={api} />);
    expect(await screen.findByText(/NAV：1000/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "預覽交易與風控" }));
    expect(await screen.findByRole("dialog", { name: "確認交易與桶分配" })).toBeInTheDocument();
    expect(screen.getByText("交易、分配、持股、曝險與稽核將一併保存")).toBeVisible();
    const confirm = screen.getByRole("button", { name: "確認交易" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("確認理由"), "依預覽確認");
    await user.click(confirm);
    expect(api.confirmTrade).toHaveBeenCalledWith(expect.objectContaining({
      challenge_token: "token", reason: "依預覽確認",
    }));
  });

  it("submits every entered allocation bucket in one trade preview", async () => {
    const api = client(); const user = userEvent.setup();
    render(<PortfolioRoutes client={api} />);
    await screen.findByText(/NAV：1000/);
    await user.clear(screen.getByLabelText("股數"));
    await user.type(screen.getByLabelText("股數"), "3");
    const allocations = screen.getByLabelText("分配桶（每行：bucket ID,股數）");
    await user.clear(allocations);
    await user.type(allocations, "thesis-1,2{enter}independent,1");
    await user.click(screen.getByRole("button", { name: "預覽交易與風控" }));
    expect(api.previewTrade).toHaveBeenCalledWith(expect.objectContaining({
      quantity: 3,
      allocations: [
        { bucket_id: "thesis-1", quantity: 2 },
        { bucket_id: "independent", quantity: 1 },
      ],
    }));
  });

  it("renders every server exposure dimension", async () => {
    render(<PortfolioRoutes client={client()} />);
    expect(await screen.findByRole("heading", { name: "證券曝險" })).toBeVisible();
    expect(screen.getByText("2330")).toBeVisible();
    expect(screen.getByRole("heading", { name: "產業曝險" })).toBeVisible();
    expect(screen.getByText("半導體")).toBeVisible();
    expect(screen.getByRole("heading", { name: "主題曝險" })).toBeVisible();
    expect(screen.getByText("AI")).toBeVisible();
  });

  it("moves a validated CSV row into the existing trade preview and confirmation flow", async () => {
    const api = client(); const user = userEvent.setup();
    render(<PortfolioRoutes client={api} />);
    await screen.findByText(/NAV：1000/);
    await user.click(screen.getByRole("button", { name: "驗證 CSV" }));
    await user.click(await screen.findByRole("button", { name: "帶入第 1 筆交易" }));
    expect(screen.getByLabelText("證券代號")).toHaveValue("2330");
    await user.click(screen.getByRole("button", { name: "預覽交易與風控" }));
    expect(api.previewTrade).toHaveBeenCalledWith(expect.objectContaining({
      source_kind: "csv", source_row_id: "row-1", security_id: "2330",
    }));
  });
});
