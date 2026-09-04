/* eslint-disable */
// Generated from backend OpenAPI. Do not edit.
export const OPENAPI_SHA256 = "0100281198449c1c40064ad43428e5ca5f0ab29889c2ffb5eca923c01b3b5493";

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

export type CanonicalCsvPreviewBody = { "content": string };

export type CanonicalCsvPreviewResponse = { "issues": Record<string, unknown>[]; "policy_version": string; "trades": Record<string, unknown>[] };

export type CompanyActionConfirmBody = { "action_kind": "split" | "capital_reduction" | "stock_dividend"; "cash_in_lieu": string; "challenge_token": string; "confirmed_post_action_shares": number; "expected_version": number; "idempotency_key": string; "reason": string; "security_id": string };

export type CompanyActionPreviewBody = { "action_kind": "split" | "capital_reduction" | "stock_dividend"; "cash_in_lieu": string; "confirmed_post_action_shares": number; "expected_version": number; "security_id": string };

export type CompanyCreateBody = { "name": string; "ticker": string };

export type CompanyResponse = { "company_id": string; "name": string; "ticker": string; "version": number };

export type ConfirmationChallengeBody = { "action_type": string; "payload": Record<string, unknown>; "target_id": string; "target_version": number };

export type ConfirmationChallengeResponse = { "challenge_token": string; "expires_at": string; "impact_summary": ImpactSummaryResponse; "target_version": number };

export type ConfirmedActionBody = { "action_type": string; "challenge_token": string; "payload": Record<string, unknown>; "reason": string; "target_version": number };

export type ConfirmedActionResponse = { "accepted": boolean; "challenge_id": string };

export type CostProfileSaveBody = { "buy_rate": string; "effective_at": string; "expected_version": number; "idempotency_key": string; "minimum_buy_fee": string; "minimum_sell_fee": string; "reason": string; "sell_rate": string; "tax_rate": string };

export type DimensionFactsBody = { "commercialization_established": boolean; "consecutive_financial_quarters": number; "identifiable_profit_or_cash_flow": boolean; "identifiable_revenue": boolean; "product_established": boolean; "source_confirmation": "unverified" | "official" };

export type EvidenceResponse = { "evidence_id": string; "source_snapshot_id"?: string | null; "status": EvidenceStatus; "version": number };

export type EvidenceStageConfirmationBody = { "expected_version": number; "facts": DimensionFactsBody; "idempotency_key": string; "reason": string; "source_snapshot_id": string };

export type EvidenceStageResponse = { "actor_id": string; "confirmed_at": string; "evidence_id": string; "facts": DimensionFactsBody; "gate_trace": GateResultResponse[]; "policy_version": string; "reason": string; "source_snapshot_id": string; "stage": string; "version": number };

export type EvidenceStatus = "received" | "processing" | "succeeded" | "failed" | "retrying" | "dead_letter";

export type EvidenceSubmissionBody = { "company_id": string; "company_version": number; "idempotency_key": string; "url": string };

export type GateResultResponse = { "code": string; "gate": string; "passed": boolean };

export type HTTPValidationError = { "detail"?: ValidationError[] };

export type ImpactSummaryResponse = { "action_label": string; "after": Record<string, never> & Record<string, string>; "before": Record<string, never> & Record<string, string>; "confirmation_verb": string; "consequences": string[]; "subject": string };

export type InvestableCashSaveBody = { "as_of": string; "cash": string; "expected_version": number; "idempotency_key": string; "reason": string };

export type LearnerSessionResponse = { "capabilities": string[]; "display_name": string; "is_recovery_session": boolean; "kind": "learner"; "session_expires_at": string; "user_id": string };

export type OwnerSessionResponse = { "capabilities": string[]; "display_name": string; "is_recovery_session": boolean; "kind": "owner"; "recovery_task_url"?: string | null; "session_expires_at": string; "user_id": string };

export type PeerValuationMemberBody = { "company_id": string; "inclusion_reason": string; "source": ValuationSourceReferenceBody };

export type PortfolioMutationPreviewResponse = { "allocation"?: Record<string, unknown> | null; "challenge_expires_at": string; "challenge_token": string; "impact_summary": Record<string, unknown>; "original_trade_id"?: string | null; "post_cash": string; "preview_digest": string; "target_version": number };

export type PortfolioResponse = { "cash": string; "cash_as_of": string | null; "company_actions": Record<string, unknown>[]; "corrections": Record<string, unknown>[]; "cost_profile": Record<string, unknown> | null; "exposure": Record<string, unknown>; "holdings": Record<string, unknown>[]; "trades": Record<string, unknown>[]; "updated_at": string; "version": number };

export type ProblemResponse = { "code": string };

export type Role = "owner" | "learner" | "admin";

export type ThesisCreateBody = { "company_version": number; "evidence_refs"?: ThesisResearchReferenceBody[]; "idempotency_key": string; "invalidation_conditions": string[]; "narrative": string; "reason": string; "title": string };

export type ThesisOutcomeBody = { "evidence_refs"?: ThesisResearchReferenceBody[]; "expected_version": number; "idempotency_key": string; "observed_at": string; "reason": string; "result": string };

export type ThesisReflectionCompleteBody = { "expected_version": number; "idempotency_key": string; "improvement": string; "judgment_errors": string; "missing_evidence": string; "original_assumption": string; "reason": string };

export type ThesisReflectionDraftBody = { "expected_draft_version": number; "field": "original_assumption" | "judgment_errors" | "missing_evidence" | "improvement"; "idempotency_key": string; "text": string };

export type ThesisResearchReferenceBody = { "record_id": string; "version": number };

export type ThesisResponse = { "company_id": string; "company_version": number; "conditions": Record<string, unknown>[]; "created_at": string; "cycle": number; "evidence_refs": Record<string, unknown>[]; "narrative": string; "outcome": Record<string, unknown> | null; "owner_user_id": string; "policy_version": string; "reflection": Record<string, unknown> | null; "reflection_draft": Record<string, unknown> | null; "reflection_pending": boolean; "status": "draft" | "active" | "paused" | "invalidated" | "closed"; "thesis_id": string; "title": string; "updated_at": string; "valuation_draft": Record<string, unknown> | null; "valuation_snapshots": Record<string, unknown>[]; "version": number };

export type ThesisSaveBody = { "evidence_refs"?: ThesisResearchReferenceBody[]; "expected_version": number; "idempotency_key": string; "invalidation_conditions": string[]; "narrative": string; "reason": string; "title": string };

export type ThesisTransitionBody = { "challenge_token"?: string | null; "expected_version": number; "idempotency_key": string; "reason": string; "target_status": "draft" | "active" | "paused" | "invalidated" | "closed" };

export type ThesisTransitionPreviewBody = { "expected_version": number; "target_status": "draft" | "active" | "paused" | "invalidated" | "closed" };

export type ThesisTransitionPreviewResponse = { "challenge_expires_at"?: string | null; "challenge_token"?: string | null; "consequences": string[]; "from_status": "draft" | "active" | "paused" | "invalidated" | "closed"; "impact_summary"?: Record<string, unknown> | null; "requires_confirmation": boolean; "target_version": number; "thesis_id": string; "to_status": "draft" | "active" | "paused" | "invalidated" | "closed" };

export type TradeAllocationBody = { "bucket_id": string; "quantity": number };

export type TradeConfirmBody = { "allocations": TradeAllocationBody[]; "broker_reference"?: string | null; "challenge_token": string; "executed_at": string; "expected_version": number; "fees": string; "idempotency_key": string; "price": string; "quantity": number; "reason": string; "security_id": string; "side": "buy" | "sell"; "source_kind": "manual" | "csv"; "source_row_id": string; "tax": string };

export type TradeCorrectionConfirmBody = { "challenge_token": string; "expected_version": number; "idempotency_key": string; "original_trade_id": string; "reason": string };

export type TradeCorrectionPreviewBody = { "expected_version": number; "original_trade_id": string };

export type TradePreviewBody = { "allocations": TradeAllocationBody[]; "broker_reference"?: string | null; "executed_at": string; "expected_version": number; "fees": string; "price": string; "quantity": number; "security_id": string; "side": "buy" | "sell"; "source_kind": "manual" | "csv"; "source_row_id": string; "tax": string };

export type TradePreviewResponse = { "challenge_expires_at": string; "challenge_token": string; "feasible": boolean; "fingerprint": string; "impact_summary": Record<string, unknown>; "nav": string; "policy_version": string; "post_cash": string; "preview_digest": string; "reasons": string[]; "target_version": number };

export type ValidationError = { "ctx"?: Record<string, never>; "input"?: unknown; "loc": (string | number)[]; "msg": string; "type": string };

export type ValuationDraftSaveBody = { "basis_date": string; "benchmark_source": "company_history" | "peer_group" | "abstain"; "benchmark_variant": "median" | "p75"; "buy_price"?: string | null; "cash_dividend"?: string | null; "company_history_samples"?: ValuationHistorySampleBody[]; "expected_draft_version": number; "expected_thesis_version": number; "forecast_source"?: ValuationSourceReferenceBody | null; "horizon_months": 6 | 12 | 24; "idempotency_key": string; "method": "pe" | "pb" | "abstain"; "peer_members"?: PeerValuationMemberBody[]; "quantity"?: string | null; "reason": string; "source_selection_reason": string };

export type ValuationHistorySampleBody = { "source": ValuationSourceReferenceBody };

export type ValuationPublicationBody = { "challenge_token": string; "expected_draft_version": number; "expected_thesis_version": number; "idempotency_key": string; "reason": string };

export type ValuationPublicationPreviewBody = { "expected_draft_version": number; "expected_thesis_version": number };

export type ValuationPublicationPreviewResponse = { "challenge_expires_at": string; "challenge_token": string; "draft_version": number; "impact_summary": Record<string, unknown>; "target_version": number };

export type ValuationSourceReferenceBody = { "fact_id": string; "record_id": string; "version": number };

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

export function list_theses_api_companies__company_id__theses_get(baseUrl: string, company_id: string, fetcher: typeof fetch = fetch): Promise<ThesisResponse[]> {
  return request(fetcher, `${baseUrl}/companies/${encodeURIComponent(company_id)}/theses`);
}

export function create_thesis_api_companies__company_id__theses_post(baseUrl: string, company_id: string, body: ThesisCreateBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/companies/${encodeURIComponent(company_id)}/theses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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

export function get_portfolio_api_portfolio_get(baseUrl: string, fetcher: typeof fetch = fetch): Promise<PortfolioResponse> {
  return request(fetcher, `${baseUrl}/portfolio`);
}

export function preview_portfolio_company_action_api_portfolio_company_action_previews_post(baseUrl: string, body: CompanyActionPreviewBody, fetcher: typeof fetch = fetch): Promise<PortfolioMutationPreviewResponse> {
  return request(fetcher, `${baseUrl}/portfolio/company-action-previews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function confirm_portfolio_company_action_api_portfolio_company_actions_post(baseUrl: string, body: CompanyActionConfirmBody, fetcher: typeof fetch = fetch): Promise<PortfolioResponse> {
  return request(fetcher, `${baseUrl}/portfolio/company-actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function save_cost_profile_api_portfolio_cost_profile_put(baseUrl: string, body: CostProfileSaveBody, fetcher: typeof fetch = fetch): Promise<PortfolioResponse> {
  return request(fetcher, `${baseUrl}/portfolio/cost-profile`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function preview_portfolio_csv_api_portfolio_csv_previews_post(baseUrl: string, body: CanonicalCsvPreviewBody, fetcher: typeof fetch = fetch): Promise<CanonicalCsvPreviewResponse> {
  return request(fetcher, `${baseUrl}/portfolio/csv-previews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function save_investable_cash_api_portfolio_investable_cash_put(baseUrl: string, body: InvestableCashSaveBody, fetcher: typeof fetch = fetch): Promise<PortfolioResponse> {
  return request(fetcher, `${baseUrl}/portfolio/investable-cash`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function preview_portfolio_correction_api_portfolio_trade_correction_previews_post(baseUrl: string, body: TradeCorrectionPreviewBody, fetcher: typeof fetch = fetch): Promise<PortfolioMutationPreviewResponse> {
  return request(fetcher, `${baseUrl}/portfolio/trade-correction-previews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function confirm_portfolio_correction_api_portfolio_trade_corrections_post(baseUrl: string, body: TradeCorrectionConfirmBody, fetcher: typeof fetch = fetch): Promise<PortfolioResponse> {
  return request(fetcher, `${baseUrl}/portfolio/trade-corrections`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function preview_portfolio_trade_api_portfolio_trade_previews_post(baseUrl: string, body: TradePreviewBody, fetcher: typeof fetch = fetch): Promise<TradePreviewResponse> {
  return request(fetcher, `${baseUrl}/portfolio/trade-previews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function confirm_portfolio_trade_api_portfolio_trades_post(baseUrl: string, body: TradeConfirmBody, fetcher: typeof fetch = fetch): Promise<PortfolioResponse> {
  return request(fetcher, `${baseUrl}/portfolio/trades`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function delete_session_api_session_delete(baseUrl: string, fetcher: typeof fetch = fetch): Promise<unknown> {
  return request(fetcher, `${baseUrl}/session`, { method: "DELETE", headers: { "Content-Type": "application/json" } });
}

export function get_session_api_session_get(baseUrl: string, fetcher: typeof fetch = fetch): Promise<OwnerSessionResponse | LearnerSessionResponse | AdminSessionResponse> {
  return request(fetcher, `${baseUrl}/session`);
}

export function get_thesis_api_theses__thesis_id__get(baseUrl: string, thesis_id: string, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}`);
}

export function save_thesis_api_theses__thesis_id__put(baseUrl: string, thesis_id: string, body: ThesisSaveBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function save_thesis_outcome_api_theses__thesis_id__outcomes_post(baseUrl: string, thesis_id: string, body: ThesisOutcomeBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/outcomes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function autosave_thesis_reflection_api_theses__thesis_id__reflection_draft_put(baseUrl: string, thesis_id: string, body: ThesisReflectionDraftBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/reflection-draft`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function complete_thesis_reflection_api_theses__thesis_id__reflections_post(baseUrl: string, thesis_id: string, body: ThesisReflectionCompleteBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/reflections`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function preview_thesis_transition_api_theses__thesis_id__transition_previews_post(baseUrl: string, thesis_id: string, body: ThesisTransitionPreviewBody, fetcher: typeof fetch = fetch): Promise<ThesisTransitionPreviewResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/transition-previews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function transition_thesis_api_theses__thesis_id__transitions_post(baseUrl: string, thesis_id: string, body: ThesisTransitionBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/transitions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function save_valuation_draft_api_theses__thesis_id__valuation_draft_put(baseUrl: string, thesis_id: string, body: ValuationDraftSaveBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/valuation-draft`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function preview_valuation_publication_api_theses__thesis_id__valuation_publication_previews_post(baseUrl: string, thesis_id: string, body: ValuationPublicationPreviewBody, fetcher: typeof fetch = fetch): Promise<ValuationPublicationPreviewResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/valuation-publication-previews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function publish_valuation_api_theses__thesis_id__valuations_post(baseUrl: string, thesis_id: string, body: ValuationPublicationBody, fetcher: typeof fetch = fetch): Promise<ThesisResponse> {
  return request(fetcher, `${baseUrl}/theses/${encodeURIComponent(thesis_id)}/valuations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
