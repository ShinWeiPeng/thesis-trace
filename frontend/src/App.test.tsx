import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { ApiError, type EvidenceClient } from "./api/evidenceClient";
import type { WorkflowClient } from "./workflow/client";
const company = { company_id: "2330", ticker: "2330", name: "台積電", version: 1 };
it("selects a server company and shows its server receipt", async () => {
  const user = userEvent.setup(); const client: EvidenceClient = { listCompanies: vi.fn().mockResolvedValue([company]), createCompany: vi.fn(), submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 1, status: "received", company, submittedUrl: "https://example.com/a" }), getEvidenceIntake: vi.fn(), getEvidenceStage: vi.fn(), confirmEvidenceStage: vi.fn(), requestAnomalyAssessment: vi.fn(), getAnomalyAssessment: vi.fn() };
  render(<App client={client} />); await screen.findByRole("option", { name: "2330 · 台積電" }); await user.type(screen.getByLabelText("Evidence URL"), "https://example.com/a"); await user.click(screen.getByRole("button", { name: "提交 Evidence" }));
  expect(await screen.findByRole("status")).toHaveTextContent("已接收"); expect(client.submitEvidenceUrl).toHaveBeenCalledWith({ company, submittedUrl: "https://example.com/a" });
});
it("creates a company before evidence submission", async () => {
  const user = userEvent.setup(); const created = { ...company, company_id: "2454", ticker: "2454", name: "聯發科" }; const client: EvidenceClient = { listCompanies: vi.fn().mockResolvedValue([]), createCompany: vi.fn().mockResolvedValue(created), submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-2", version: 1, status: "received", company: created, submittedUrl: "https://example.com/b" }), getEvidenceIntake: vi.fn(), getEvidenceStage: vi.fn(), confirmEvidenceStage: vi.fn(), requestAnomalyAssessment: vi.fn(), getAnomalyAssessment: vi.fn() };
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
    requestAnomalyAssessment: vi.fn(), getAnomalyAssessment: vi.fn(),
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

it("creates a pending shadow assessment and renders a server would-be-Hard trace without formal Hard", async () => {
  const user = userEvent.setup();
  const pending = { assessment_id: "a-1", evidence_id: "e-1", evidence_version: 2, failure_code: null, requested_at: "2026-08-21T10:00:00Z", source_snapshot_ids: ["snapshot-1"], status: "pending" as const, trace: null, version: 1 };
  const completed = { ...pending, status: "succeeded" as const, version: 2, trace: { anomaly_class: "would_be_hard" as const, clue_route: null, clue_score: null, policy_version: "anomaly-policy-v1", source_tiers: ["A" as const], gates: [{ gate: "predeclared_invalidation", passed: true, code: "passed" }] } };
  const superseded = { ...completed, status: "superseded" as const, failure_code: "stale_input", version: 3 };
  const client: EvidenceClient = {
    listCompanies: vi.fn().mockResolvedValue([company]), createCompany: vi.fn(),
    submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 1, status: "received", company, submittedUrl: "https://example.com/a" }),
    getEvidenceIntake: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 2, status: "succeeded", source_snapshot_id: "snapshot-1" }),
    getEvidenceStage: vi.fn(), confirmEvidenceStage: vi.fn(),
    requestAnomalyAssessment: vi.fn().mockResolvedValue(pending),
    getAnomalyAssessment: vi.fn().mockResolvedValueOnce(completed).mockResolvedValueOnce(superseded),
  };
  const workflow: WorkflowClient = {
    createAnomalyReview: vi.fn().mockResolvedValue({
      item_id: "action-1", version: 1, item_type: "anomaly_review", source_domain: "anomaly_assessment",
      source_record_id: "a-1", source_version: 2, company_id: "2330", company_ticker: "2330",
      company_name: "台積電", reason: "追蹤並人工審查此 anomaly", status: "pending", system_priority: "high",
      effective_priority: "high", safety_floor: null, safety_locked: false, priority_rule_ids: ["shadow"],
      priority_policy_version: "action-priority-v1", priority_reason: "review", created_at: "2026-08-24T00:00:00Z",
      updated_at: "2026-08-24T00:00:00Z", due_at: null, defer_until: null, recurrence_of: null,
      allowed_transitions: ["in_progress"],
    }),
    queryInbox: vi.fn(), getActionItem: vi.fn(), transitionActionItem: vi.fn(),
  };
  render(<App client={client} workflow={workflow} />);
  await screen.findByRole("option", { name: "2330 · 台積電" });
  await user.type(screen.getByLabelText("Evidence URL"), "https://example.com/a");
  await user.click(screen.getByRole("button", { name: "提交 Evidence" }));
  await user.click(screen.getByRole("button", { name: "重新整理狀態" }));
  await user.type(await screen.findByLabelText("評估理由"), "review disclosure");
  await user.click(screen.getByRole("button", { name: "開始 Shadow anomaly 評估" }));

  expect(await screen.findByText("等待獨立 AI worker")).toBeInTheDocument();
  expect(client.requestAnomalyAssessment).toHaveBeenCalledWith("e-1", expect.objectContaining({
    expected_evidence_version: 2,
    reason: "review disclosure",
    sources: [{ source_snapshot_id: "snapshot-1" }],
  }));
  await user.click(screen.getByRole("button", { name: "重新整理評估" }));
  expect(await screen.findAllByText("Shadow Hard 候選")).toHaveLength(2);
  expect(screen.getByText(/正式 Hard 通知仍停用/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "建立審查待辦" }));
  expect(workflow.createAnomalyReview).toHaveBeenCalledWith(expect.objectContaining({
    assessment_id: "a-1", expected_assessment_version: 2,
  }));
  expect(await screen.findByRole("link", { name: "開啟已建立待辦" })).toHaveAttribute("href", "/actions/action-1");
  await user.click(screen.getByRole("button", { name: "重新整理評估" }));
  expect(await screen.findAllByText("已由新版取代")).toHaveLength(2);
  expect(screen.queryByText("Shadow Hard 候選")).not.toBeInTheDocument();
});

it("restores the server-backed company and anomaly context from an Action Item route", async () => {
  const linked = { assessment_id: "a-1", evidence_id: "e-1", evidence_version: 2, failure_code: null,
    requested_at: "2026-08-21T10:00:00Z", source_snapshot_ids: ["snapshot-1"], status: "succeeded" as const,
    version: 2, trace: { anomaly_class: "would_be_hard" as const, clue_route: null, clue_score: null,
      policy_version: "anomaly-policy-v1", source_tiers: ["A" as const],
      gates: [{ gate: "predeclared_invalidation", passed: true, code: "passed" }] } };
  const client: EvidenceClient = {
    listCompanies: vi.fn().mockResolvedValue([company]), createCompany: vi.fn(), submitEvidenceUrl: vi.fn(),
    getEvidenceIntake: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 2, status: "succeeded", source_snapshot_id: "snapshot-1" }),
    getEvidenceStage: vi.fn().mockRejectedValue(new ApiError("missing", "missing", 404)),
    confirmEvidenceStage: vi.fn(), requestAnomalyAssessment: vi.fn(), getAnomalyAssessment: vi.fn().mockResolvedValue(linked),
  };

  render(<App client={client} initialCompanyId="2330" actionReturnHref="/actions/action-1?return=search%3DTT" actionSource={{ domain: "anomaly_assessment", recordId: "a-1", version: 2 }} />);

  expect(await screen.findByText(/返回原待辦與清單位置/)).toHaveAttribute("href", "/actions/action-1?return=search%3DTT");
  expect(await screen.findAllByText("Shadow Hard 候選")).toHaveLength(2);
  expect(client.getAnomalyAssessment).toHaveBeenCalledWith("a-1");
  expect(client.getEvidenceIntake).toHaveBeenCalledWith("e-1");
});
