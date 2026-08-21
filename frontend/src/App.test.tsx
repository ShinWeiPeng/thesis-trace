import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { EvidenceClient } from "./api/evidenceClient";
const company = { company_id: "2330", ticker: "2330", name: "台積電", version: 1 };
it("selects a server company and shows its server receipt", async () => {
  const user = userEvent.setup(); const client: EvidenceClient = { listCompanies: vi.fn().mockResolvedValue([company]), createCompany: vi.fn(), submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 1, status: "received", company, submittedUrl: "https://example.com/a" }), getEvidenceIntake: vi.fn(), getEvidenceStage: vi.fn(), confirmEvidenceStage: vi.fn() };
  render(<App client={client} />); await screen.findByRole("option", { name: "2330 · 台積電" }); await user.type(screen.getByLabelText("Evidence URL"), "https://example.com/a"); await user.click(screen.getByRole("button", { name: "提交 Evidence" }));
  expect(await screen.findByRole("status")).toHaveTextContent("已接收"); expect(client.submitEvidenceUrl).toHaveBeenCalledWith({ company, submittedUrl: "https://example.com/a" });
});
it("creates a company before evidence submission", async () => {
  const user = userEvent.setup(); const created = { ...company, company_id: "2454", ticker: "2454", name: "聯發科" }; const client: EvidenceClient = { listCompanies: vi.fn().mockResolvedValue([]), createCompany: vi.fn().mockResolvedValue(created), submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-2", version: 1, status: "received", company: created, submittedUrl: "https://example.com/b" }), getEvidenceIntake: vi.fn(), getEvidenceStage: vi.fn(), confirmEvidenceStage: vi.fn() };
  render(<App client={client} />); await user.click(await screen.findByRole("button", { name: "建立新公司" })); await user.type(screen.getByLabelText("股票代號"), "2454"); await user.type(screen.getByLabelText("公司名稱"), "聯發科"); await user.type(screen.getByLabelText("Evidence URL"), "https://example.com/b"); await user.click(screen.getByRole("button", { name: "建立公司並提交 Evidence" }));
  expect(client.createCompany).toHaveBeenCalledWith({ ticker: "2454", name: "聯發科" });
});

it("lets an Owner confirm facts and displays only the server-derived E-stage", async () => {
  const user = userEvent.setup();
  const stage = {
    actor_id: "owner-1", confirmed_at: "2026-08-20T00:00:00Z", evidence_id: "e-1",
    facts: { source_confirmation: "official" as const, product_established: true, commercialization_established: true, identifiable_revenue: false, identifiable_profit_or_cash_flow: false, consecutive_financial_quarters: 0 },
    gate_trace: [
      { gate: "E0", passed: true, code: "confirmed_source" },
      { gate: "E1", passed: true, code: "product_established" },
      { gate: "E2", passed: true, code: "commercialization_established" },
      { gate: "E3", passed: true, code: "identifiable_revenue" },
      { gate: "E4", passed: false, code: "profit_or_cash_flow_not_identifiable" },
      { gate: "E5", passed: false, code: "insufficient_consecutive_financial_quarters" },
    ],
    policy_version: "e-stage-v1", reason: "official filing reviewed", source_snapshot_id: "snapshot-1", stage: "E3", version: 1,
  };
  const client: EvidenceClient = {
    listCompanies: vi.fn().mockResolvedValue([company]), createCompany: vi.fn(),
    submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 1, status: "received", company, submittedUrl: "https://example.com/a" }),
    getEvidenceIntake: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 2, status: "succeeded", source_snapshot_id: "snapshot-1" }),
    getEvidenceStage: vi.fn(), confirmEvidenceStage: vi.fn().mockResolvedValue(stage),
  };

  render(<App client={client} />);
  await screen.findByRole("option", { name: "2330 · 台積電" });
  await user.type(screen.getByLabelText("Evidence URL"), "https://example.com/a");
  await user.click(screen.getByRole("button", { name: "提交 Evidence" }));
  await user.click(screen.getByRole("button", { name: "重新整理狀態" }));
  await user.selectOptions(await screen.findByLabelText("來源確認"), "official");
  await user.click(screen.getByLabelText("已建立產品"));
  await user.click(screen.getByLabelText("已建立商業化"));
  await user.type(screen.getByLabelText("確認理由"), "official filing reviewed");
  await user.click(screen.getByRole("button", { name: "確認事實並儲存階段" }));

  expect(client.confirmEvidenceStage).toHaveBeenCalledWith("e-1", expect.objectContaining({
    expected_version: 0, source_snapshot_id: "snapshot-1", reason: "official filing reviewed",
    facts: expect.objectContaining({ commercialization_established: true, identifiable_revenue: false }),
  }));
  expect(await screen.findByLabelText("伺服器推導階段")).toHaveTextContent("E3");
  expect(screen.getByText("由伺服器依 e-stage-v1 推導")).toBeInTheDocument();
});
