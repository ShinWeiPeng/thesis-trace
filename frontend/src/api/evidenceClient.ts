import {
  create_company_api_companies_post,
  list_companies_api_companies_get,
  status_api_evidence__evidence_id__get,
  submit_api_evidence_post,
  type CompanyCreateBody,
  type CompanyResponse,
  type EvidenceResponse,
  type EvidenceSubmissionBody,
} from "../generated/api";
export type { CompanyResponse, EvidenceResponse, EvidenceStatus } from "../generated/api";

export interface EvidenceIntake extends EvidenceResponse { company: CompanyResponse; submittedUrl: string }
export interface EvidenceClient {
  listCompanies(): Promise<CompanyResponse[]>;
  createCompany(input: CompanyCreateBody): Promise<CompanyResponse>;
  submitEvidenceUrl(input: { company: CompanyResponse; submittedUrl: string; idempotencyKey?: string }): Promise<EvidenceIntake>;
  getEvidenceIntake(evidenceId: string): Promise<EvidenceResponse>;
}
export class ApiError extends Error {
  constructor(public readonly code: string, message: string, public readonly status: number) { super(message); this.name = "ApiError"; }
}
async function safe<T>(operation: Promise<T>): Promise<T> {
  try { return await operation; } catch (error) {
    if (!(error instanceof Response)) throw error;
    let detail = "伺服器目前無法完成要求，請稍後重試。";
    try { const body = (await error.json()) as { detail?: string }; detail = typeof body.detail === "string" ? body.detail : detail; } catch { /* bounded fallback */ }
    throw new ApiError(detail, detail, error.status);
  }
}
export function createEvidenceClient({ baseUrl, fetcher = fetch, idempotencyKey = () => crypto.randomUUID() }: { baseUrl: string; fetcher?: typeof fetch; idempotencyKey?: () => string }): EvidenceClient {
  return {
    listCompanies: () => safe(list_companies_api_companies_get(baseUrl, fetcher)),
    createCompany: (input) => safe(create_company_api_companies_post(baseUrl, input, fetcher)),
    async submitEvidenceUrl(input) {
      const body: EvidenceSubmissionBody = { company_id: input.company.company_id, company_version: input.company.version, url: input.submittedUrl, idempotency_key: input.idempotencyKey ?? idempotencyKey() };
      return { ...await safe(submit_api_evidence_post(baseUrl, body, fetcher)), company: input.company, submittedUrl: input.submittedUrl };
    },
    getEvidenceIntake: (id) => safe(status_api_evidence__evidence_id__get(baseUrl, id, fetcher)),
  };
}
export const evidenceClient = createEvidenceClient({ baseUrl: "/api" });
