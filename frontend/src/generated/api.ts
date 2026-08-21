/* eslint-disable */
// Generated from backend OpenAPI. Do not edit.
export const OPENAPI_SHA256 = "baff18c1514e178d0b4718a51277384cdae9dc8665f537a2f0a2369fe4089917";

export type AccountCreateBody = { "challenge_token": string; "email_fact": string; "provider_id": string; "provider_subject": string; "provider_type": string; "reason": string; "role": Role };

export type AccountResponse = { "masked_identity": string; "role": Role; "status": "active" | "disabled"; "user_id": string; "version": number };

export type AdminSessionResponse = { "capabilities": string[]; "display_name": string; "is_recovery_session": boolean; "kind": "admin"; "session_expires_at": string; "user_id": string };

export type CompanyCreateBody = { "name": string; "ticker": string };

export type CompanyResponse = { "company_id": string; "name": string; "ticker": string; "version": number };

export type ConfirmationChallengeBody = { "action_type": string; "payload": Record<string, unknown>; "target_id": string; "target_version": number };

export type ConfirmationChallengeResponse = { "challenge_token": string; "expires_at": string; "impact_summary": ImpactSummaryResponse; "target_version": number };

export type ConfirmedActionBody = { "action_type": string; "challenge_token": string; "payload": Record<string, unknown>; "reason": string; "target_version": number };

export type ConfirmedActionResponse = { "accepted": boolean; "challenge_id": string };

export type DimensionFactsBody = { "commercialization_established": boolean; "consecutive_financial_quarters": number; "identifiable_profit_or_cash_flow": boolean; "identifiable_revenue": boolean; "product_established": boolean; "source_confirmation": "unverified" | "official" };

export type EvidenceResponse = { "evidence_id": string; "source_snapshot_id"?: string | null; "status": EvidenceStatus; "version": number };

export type EvidenceStageConfirmationBody = { "expected_version": number; "facts": DimensionFactsBody; "idempotency_key": string; "reason": string; "source_snapshot_id": string };

export type EvidenceStageResponse = { "actor_id": string; "confirmed_at": string; "evidence_id": string; "facts": DimensionFactsBody; "gate_trace": GateResultResponse[]; "policy_version": string; "reason": string; "source_snapshot_id": string; "stage": string; "version": number };

export type EvidenceStatus = "received" | "processing" | "succeeded" | "failed" | "retrying" | "dead_letter";

export type EvidenceSubmissionBody = { "company_id": string; "company_version": number; "idempotency_key": string; "url": string };

export type GateResultResponse = { "code": string; "gate": string; "passed": boolean };

export type HTTPValidationError = { "detail"?: ValidationError[] };

export type ImpactSummaryResponse = { "action_label": string; "after": Record<string, never> & Record<string, string>; "before": Record<string, never> & Record<string, string>; "confirmation_verb": string; "consequences": string[]; "subject": string };

export type LearnerSessionResponse = { "capabilities": string[]; "display_name": string; "is_recovery_session": boolean; "kind": "learner"; "session_expires_at": string; "user_id": string };

export type OwnerSessionResponse = { "capabilities": string[]; "display_name": string; "is_recovery_session": boolean; "kind": "owner"; "recovery_task_url"?: string | null; "session_expires_at": string; "user_id": string };

export type ProblemResponse = { "code": string };

export type Role = "owner" | "learner" | "admin";

export type ValidationError = { "ctx"?: Record<string, never>; "input"?: unknown; "loc": (string | number)[]; "msg": string; "type": string };

async function request<T>(fetcher: typeof fetch, url: string, init?: RequestInit): Promise<T> {
  const response = await fetcher(url, { credentials: "same-origin", ...init });
  if (!response.ok) throw response;
  return (await response.json()) as T;
}

export function list_accounts_api_admin_accounts_get(baseUrl: string, fetcher: typeof fetch = fetch): Promise<AccountResponse[]> {
  return request(fetcher, `${baseUrl}/admin/accounts`);
}

export function create_account_api_admin_accounts_post(baseUrl: string, body: AccountCreateBody, fetcher: typeof fetch = fetch): Promise<AccountResponse> {
  return request(fetcher, `${baseUrl}/admin/accounts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function account_detail_api_admin_accounts__user_id__get(baseUrl: string, user_id: string, fetcher: typeof fetch = fetch): Promise<AccountResponse> {
  return request(fetcher, `${baseUrl}/admin/accounts/${encodeURIComponent(user_id)}`);
}

export function list_companies_api_companies_get(baseUrl: string, fetcher: typeof fetch = fetch): Promise<CompanyResponse[]> {
  return request(fetcher, `${baseUrl}/companies`);
}

export function create_company_api_companies_post(baseUrl: string, body: CompanyCreateBody, fetcher: typeof fetch = fetch): Promise<CompanyResponse> {
  return request(fetcher, `${baseUrl}/companies`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function preview_confirmation_api_confirmation_challenges_post(baseUrl: string, body: ConfirmationChallengeBody, fetcher: typeof fetch = fetch): Promise<ConfirmationChallengeResponse> {
  return request(fetcher, `${baseUrl}/confirmation-challenges`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function confirm_action_api_confirmed_actions_post(baseUrl: string, body: ConfirmedActionBody, fetcher: typeof fetch = fetch): Promise<ConfirmedActionResponse> {
  return request(fetcher, `${baseUrl}/confirmed-actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function submit_api_evidence_post(baseUrl: string, body: EvidenceSubmissionBody, fetcher: typeof fetch = fetch): Promise<EvidenceResponse> {
  return request(fetcher, `${baseUrl}/evidence`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function status_api_evidence__evidence_id__get(baseUrl: string, evidence_id: string, fetcher: typeof fetch = fetch): Promise<EvidenceResponse> {
  return request(fetcher, `${baseUrl}/evidence/${encodeURIComponent(evidence_id)}`);
}

export function get_evidence_stage_api_evidence__evidence_id__stage_get(baseUrl: string, evidence_id: string, fetcher: typeof fetch = fetch): Promise<EvidenceStageResponse> {
  return request(fetcher, `${baseUrl}/evidence/${encodeURIComponent(evidence_id)}/stage`);
}

export function confirm_evidence_stage_api_evidence__evidence_id__stage_confirmations_post(baseUrl: string, evidence_id: string, body: EvidenceStageConfirmationBody, fetcher: typeof fetch = fetch): Promise<EvidenceStageResponse> {
  return request(fetcher, `${baseUrl}/evidence/${encodeURIComponent(evidence_id)}/stage-confirmations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function delete_session_api_session_delete(baseUrl: string, fetcher: typeof fetch = fetch): Promise<unknown> {
  return request(fetcher, `${baseUrl}/session`, { method: "DELETE", headers: { "Content-Type": "application/json" } });
}

export function get_session_api_session_get(baseUrl: string, fetcher: typeof fetch = fetch): Promise<OwnerSessionResponse | LearnerSessionResponse | AdminSessionResponse> {
  return request(fetcher, `${baseUrl}/session`);
}
