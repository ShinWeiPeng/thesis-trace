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
});
