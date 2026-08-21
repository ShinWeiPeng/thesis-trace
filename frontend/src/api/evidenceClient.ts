import {
  get_anomaly_assessment_api_anomaly_assessments__assessment_id__get,
  confirm_evidence_stage_api_evidence__evidence_id__stage_confirmations_post,
  create_company_api_companies_post,
  get_evidence_stage_api_evidence__evidence_id__stage_get,
  list_companies_api_companies_get,
  request_anomaly_assessment_api_evidence__evidence_id__anomaly_assessments_post,
  status_api_evidence__evidence_id__get,
  submit_api_evidence_post,
  type AnomalyAssessmentRequestBody,
  type AnomalyAssessmentResponse,
  type CompanyCreateBody,
  type CompanyResponse,
  type EvidenceResponse,
  type EvidenceStageConfirmationBody,
  type EvidenceStageResponse,
  type EvidenceSubmissionBody,
} from "../generated/api";
export type { AnomalyAssessmentRequestBody, AnomalyAssessmentResponse, CompanyResponse, DimensionFactsBody, EvidenceResponse, EvidenceStageConfirmationBody, EvidenceStageResponse, EvidenceStatus } from "../generated/api";

export interface EvidenceIntake extends EvidenceResponse { company: CompanyResponse; submittedUrl: string }
export interface EvidenceClient {
  listCompanies(): Promise<CompanyResponse[]>;
  createCompany(input: CompanyCreateBody): Promise<CompanyResponse>;
  submitEvidenceUrl(input: { company: CompanyResponse; submittedUrl: string; idempotencyKey?: string }): Promise<EvidenceIntake>;
  getEvidenceIntake(evidenceId: string): Promise<EvidenceResponse>;
  getEvidenceStage(evidenceId: string): Promise<EvidenceStageResponse>;
  confirmEvidenceStage(evidenceId: string, input: EvidenceStageConfirmationBody): Promise<EvidenceStageResponse>;
  requestAnomalyAssessment(evidenceId: string, input: AnomalyAssessmentRequestBody): Promise<AnomalyAssessmentResponse>;
  getAnomalyAssessment(assessmentId: string): Promise<AnomalyAssessmentResponse>;
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
    getEvidenceStage: (id) => safe(get_evidence_stage_api_evidence__evidence_id__stage_get(baseUrl, id, fetcher)),
    confirmEvidenceStage: (id, input) => safe(confirm_evidence_stage_api_evidence__evidence_id__stage_confirmations_post(baseUrl, id, input, fetcher)),
    requestAnomalyAssessment: (id, input) => safe(request_anomaly_assessment_api_evidence__evidence_id__anomaly_assessments_post(baseUrl, id, input, fetcher)),
    getAnomalyAssessment: (id) => safe(get_anomaly_assessment_api_anomaly_assessments__assessment_id__get(baseUrl, id, fetcher)),
  };
}
export const evidenceClient = createEvidenceClient({ baseUrl: "/api" });
