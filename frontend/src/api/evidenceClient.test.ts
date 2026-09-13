import { describe, expect, it, vi } from "vitest";
import { createEvidenceClient } from "./evidenceClient";
describe("generated API adapter", () => {
  it("uses generated company and evidence operations", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify([{ company_id: "2330", ticker: "2330", name: "台積電", version: 2 }]))).mockResolvedValueOnce(new Response(JSON.stringify({ evidence_id: "e-1", version: 1, status: "received" }), { status: 202 }));
    const client = createEvidenceClient({ baseUrl: "/api", fetcher, idempotencyKey: () => "key-1" }); const company = (await client.listCompanies())[0];
    await client.submitEvidenceUrl({ company, submittedUrl: "https://example.com/a" });
    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/companies", { credentials: "same-origin" });
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/evidence", expect.objectContaining({ body: JSON.stringify({ company_id: "2330", company_version: 2, url: "https://example.com/a", idempotency_key: "key-1" }) }));
  });

  it("confirms E-stage through the generated server operation", async () => {
    const response = {
      actor_id: "owner-1", confirmed_at: "2026-08-20T00:00:00Z", evidence_id: "e-1",
      facts: { source_confirmation: "official" as const, product_established: true, commercialization_established: true, identifiable_revenue: false, identifiable_profit_or_cash_flow: false, consecutive_financial_quarters: 0 },
      gate_trace: [{ gate: "E0", passed: true, code: "confirmed_source" }], policy_version: "e-stage-v1", reason: "owner review", source_snapshot_id: "snapshot-1", stage: "E3", version: 1,
    };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 201 }));
    const client = createEvidenceClient({ baseUrl: "/api", fetcher });
    const body = { expected_version: 0, facts: response.facts, idempotency_key: "stage-key-1", reason: "owner review", source_snapshot_id: "snapshot-1" };

    await expect(client.confirmEvidenceStage("e-1", body)).resolves.toEqual(response);
    expect(fetcher).toHaveBeenCalledWith("/api/evidence/e-1/stage-confirmations", expect.objectContaining({ method: "POST", body: JSON.stringify(body) }));
  });

  it("uses generated anomaly request and query operations", async () => {
    const pending = { assessment_id: "a-1", evidence_id: "e-1", evidence_version: 2, failure_code: null, requested_at: "now", source_snapshot_ids: ["s-1"], status: "pending", trace: null, version: 1 };
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(pending), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(pending), { status: 200 }));
    const client = createEvidenceClient({ baseUrl: "/api", fetcher });
    const body = { expected_evidence_version: 2, idempotency_key: "a-key", reason: "review", sources: [{ source_snapshot_id: "s-1" }] };

    await client.requestAnomalyAssessment("e-1", body);
    await client.getAnomalyAssessment("a-1");

    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/evidence/e-1/anomaly-assessments", expect.objectContaining({ method: "POST", body: JSON.stringify(body) }));
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/anomaly-assessments/a-1", { credentials: "same-origin" });
  });
});
