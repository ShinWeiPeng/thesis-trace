import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { EvidenceClient } from "./api/evidenceClient";
const company = { company_id: "2330", ticker: "2330", name: "台積電", version: 1 };
it("selects a server company and shows its server receipt", async () => {
  const user = userEvent.setup(); const client: EvidenceClient = { listCompanies: vi.fn().mockResolvedValue([company]), createCompany: vi.fn(), submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-1", version: 1, status: "received", company, submittedUrl: "https://example.com/a" }), getEvidenceIntake: vi.fn() };
  render(<App client={client} />); await screen.findByRole("option", { name: "2330 · 台積電" }); await user.type(screen.getByLabelText("Evidence URL"), "https://example.com/a"); await user.click(screen.getByRole("button", { name: "提交 Evidence" }));
  expect(await screen.findByRole("status")).toHaveTextContent("已接收"); expect(client.submitEvidenceUrl).toHaveBeenCalledWith({ company, submittedUrl: "https://example.com/a" });
});
it("creates a company before evidence submission", async () => {
  const user = userEvent.setup(); const created = { ...company, company_id: "2454", ticker: "2454", name: "聯發科" }; const client: EvidenceClient = { listCompanies: vi.fn().mockResolvedValue([]), createCompany: vi.fn().mockResolvedValue(created), submitEvidenceUrl: vi.fn().mockResolvedValue({ evidence_id: "e-2", version: 1, status: "received", company: created, submittedUrl: "https://example.com/b" }), getEvidenceIntake: vi.fn() };
  render(<App client={client} />); await user.click(await screen.findByRole("button", { name: "建立新公司" })); await user.type(screen.getByLabelText("股票代號"), "2454"); await user.type(screen.getByLabelText("公司名稱"), "聯發科"); await user.type(screen.getByLabelText("Evidence URL"), "https://example.com/b"); await user.click(screen.getByRole("button", { name: "建立公司並提交 Evidence" }));
  expect(client.createCompany).toHaveBeenCalledWith({ ticker: "2454", name: "聯發科" });
});
