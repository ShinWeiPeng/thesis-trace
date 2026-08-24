/* eslint-disable */
// Generated from backend OpenAPI. Do not edit.
export const OPENAPI_SHA256 = "0043f557f6bb79cac57d753df61d297a4af30ff99a1fac32a77a3dbe9fdd7221";

export type AccountCreateBody = { "challenge_token": string; "email_fact": string; "provider_id": string; "provider_subject": string; "provider_type": string; "reason": string; "role": Role };

export type AccountResponse = { "masked_identity": string; "role": Role; "status": "active" | "disabled"; "user_id": string; "version": number };

export type ActionInboxResponse = { "as_of": string; "items": ActionItemResponse[]; "next_cursor": string | null; "summary": ActionInboxSummaryResponse; "total_count": number };

export type ActionInboxSummaryResponse = { "all_open": number; "deferred": number; "due_today": number; "urgent": number };

export type ActionItemCreateBody = { "assessment_id": string; "due_at"?: string | null; "expected_assessment_version": number; "idempotency_key": string; "reason": string };

export type ActionItemResponse = { "allowed_transitions": ("pending" | "in_progress" | "deferred" | "completed" | "dismissed")[]; "company_id": string; "company_name": string; "company_ticker": string; "created_at": string; "defer_until": string | null; "due_at": string | null; "effective_priority": "critical" | "high" | "normal" | "low"; "item_id": string; "item_type": "anomaly_review"; "priority_policy_version": string; "priority_reason": string; "priority_rule_ids": string[]; "reason": string; "recurrence_of": string | null; "safety_floor": "critical" | "high" | "normal" | "low" | null; "safety_locked": boolean; "source_domain": string; "source_record_id": string; "source_version": number; "status": "pending" | "in_progress" | "deferred" | "completed" | "dismissed"; "system_priority": "critical" | "high" | "normal" | "low"; "updated_at": string; "version": number };

export type ActionItemTransitionBody = { "defer_until"?: string | null; "expected_version": number; "idempotency_key": string; "reason": string; "target_status": "pending" | "in_progress" | "deferred" | "completed" | "dismissed" };

export type AdminSessionResponse = { "capabilities": string[]; "display_name": string; "is_recovery_session": boolean; "kind": "admin"; "session_expires_at": string; "user_id": string };

export type AnomalyAssessmentRequestBody = { "expected_evidence_version": number; "idempotency_key": string; "reason": string; "sources": AnomalySourceBody[] };

export type AnomalyAssessmentResponse = { "assessment_id": string; "evidence_id": string; "evidence_version": number; "failure_code": string | null; "requested_at": string; "source_snapshot_ids": string[]; "status": "pending" | "succeeded" | "failed" | "superseded"; "trace": AnomalyTraceResponse | null; "version": number };

export type AnomalyGateResponse = { "code": string; "gate": string; "passed": boolean };

export type AnomalySourceBody = { "source_snapshot_id": string };

export type AnomalyTraceResponse = { "anomaly_class": "soft" | "would_be_hard"; "clue_route": "save_only" | "watch_daily" | "human_review" | null; "clue_score": number | null; "gates": AnomalyGateResponse[]; "policy_version": string; "source_tiers": ("A" | "B" | "C")[] };

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

export function query_action_inbox_api_action_items_get(baseUrl: string, query: { "search"?: string | null; "company_id"?: string | null; "item_type"?: string | null; "status"?: string | null; "priority"?: string | null; "created_from"?: string | null; "created_to"?: string | null; "due_from"?: string | null; "due_to"?: string | null; "open_only"?: boolean; "sort"?: string; "direction"?: string; "page_size"?: number; "cursor"?: string | null } = {}, fetcher: typeof fetch = fetch): Promise<ActionInboxResponse> {
  const queryString = new URLSearchParams();
  if (query.search !== undefined && query.search !== null) queryString.set("search", String(query.search));
  if (query.company_id !== undefined && query.company_id !== null) queryString.set("company_id", String(query.company_id));
  if (query.item_type !== undefined && query.item_type !== null) queryString.set("item_type", String(query.item_type));
  if (query.status !== undefined && query.status !== null) queryString.set("status", String(query.status));
  if (query.priority !== undefined && query.priority !== null) queryString.set("priority", String(query.priority));
  if (query.created_from !== undefined && query.created_from !== null) queryString.set("created_from", String(query.created_from));
  if (query.created_to !== undefined && query.created_to !== null) queryString.set("created_to", String(query.created_to));
  if (query.due_from !== undefined && query.due_from !== null) queryString.set("due_from", String(query.due_from));
  if (query.due_to !== undefined && query.due_to !== null) queryString.set("due_to", String(query.due_to));
  if (query.open_only !== undefined && query.open_only !== null) queryString.set("open_only", String(query.open_only));
  if (query.sort !== undefined && query.sort !== null) queryString.set("sort", String(query.sort));
  if (query.direction !== undefined && query.direction !== null) queryString.set("direction", String(query.direction));
  if (query.page_size !== undefined && query.page_size !== null) queryString.set("page_size", String(query.page_size));
  if (query.cursor !== undefined && query.cursor !== null) queryString.set("cursor", String(query.cursor));
  const suffix = queryString.size ? `?${queryString}` : "";
  return request(fetcher, `${baseUrl}/action-items${suffix}`);
}

export function create_anomaly_review_action_api_action_items_anomaly_reviews_post(baseUrl: string, body: ActionItemCreateBody, fetcher: typeof fetch = fetch): Promise<ActionItemResponse> {
  return request(fetcher, `${baseUrl}/action-items/anomaly-reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function get_action_item_api_action_items__item_id__get(baseUrl: string, item_id: string, fetcher: typeof fetch = fetch): Promise<ActionItemResponse> {
  return request(fetcher, `${baseUrl}/action-items/${encodeURIComponent(item_id)}`);
}

export function transition_action_item_api_action_items__item_id__transitions_post(baseUrl: string, item_id: string, body: ActionItemTransitionBody, fetcher: typeof fetch = fetch): Promise<ActionItemResponse> {
  return request(fetcher, `${baseUrl}/action-items/${encodeURIComponent(item_id)}/transitions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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

export function get_anomaly_assessment_api_anomaly_assessments__assessment_id__get(baseUrl: string, assessment_id: string, fetcher: typeof fetch = fetch): Promise<AnomalyAssessmentResponse> {
  return request(fetcher, `${baseUrl}/anomaly-assessments/${encodeURIComponent(assessment_id)}`);
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

export function request_anomaly_assessment_api_evidence__evidence_id__anomaly_assessments_post(baseUrl: string, evidence_id: string, body: AnomalyAssessmentRequestBody, fetcher: typeof fetch = fetch): Promise<AnomalyAssessmentResponse> {
  return request(fetcher, `${baseUrl}/evidence/${encodeURIComponent(evidence_id)}/anomaly-assessments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
