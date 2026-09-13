import {
  list_recommendation_requests_api_companies__company_id__recommendation_requests_get,
  request_recommendation_api_companies__company_id__recommendation_requests_post,
  get_recommendation_request_api_recommendation_requests__request_id__get,
  get_recommendation_api_recommendations__record_id__versions__version__get,
  preview_recommendation_decision_api_recommendations__record_id__decision_previews_post,
  decide_recommendation_api_recommendations__record_id__decisions_post,
  list_theses_api_companies__company_id__theses_get,
  get_portfolio_api_portfolio_get,
  type RecommendationRequestPage,
  type RecommendationRequestView,
  type RecommendationDetailView,
  type RecommendationAdmissionBody,
  type RecommendationDecisionBody,
  type RecommendationConfirmBody,
  type RecommendationDecisionPreview,
  type RecommendationView,
  type ThesisResponse,
  type PortfolioResponse,
} from "../../generated/api";

export interface RecommendationClient {
  list(companyId: string, before?: string): Promise<RecommendationRequestPage>;
  request(
    companyId: string,
    input: RecommendationAdmissionBody,
  ): Promise<RecommendationRequestView>;
  status(requestId: string): Promise<RecommendationRequestView>;
  detail(
    recordId: string,
    version: number,
    beforeSequence?: number,
  ): Promise<RecommendationDetailView>;
  preview(
    recordId: string,
    input: RecommendationDecisionBody,
  ): Promise<RecommendationDecisionPreview>;
  decide(
    recordId: string,
    input: RecommendationConfirmBody,
  ): Promise<RecommendationView>;
  theses(companyId: string): Promise<ThesisResponse[]>;
  portfolio(): Promise<PortfolioResponse>;
}

async function safe<T>(operation: Promise<T>): Promise<T> {
  try {
    return await operation;
  } catch (error) {
    if (!(error instanceof Response)) throw error;
    let code = "recommendation_unavailable";
    try {
      const body = (await error.json()) as { detail?: unknown };
      if (typeof body.detail === "string") code = body.detail;
    } catch {
      /* stable fallback */
    }
    throw new Error(code);
  }
}

export function recommendationMessage(value: unknown): string {
  const code =
    value instanceof Error
      ? value.message
      : typeof value === "string"
        ? value
        : "";
  if (code.startsWith("input_version_changed"))
    return "關鍵輸入已更新，這份建議不能再接受；請確認最新資料後重新建立分析請求。";
  if (code.startsWith("input_expired"))
    return "綁定估值已超過有效期間，請重新發布估值，再建立分析請求。";
  const messages: Record<string, string> = {
    minimum_return_unconfigured:
      "尚未設定最低年化淨報酬門檻，因此暫不發布可接受的建議。請由 Owner 確認伺服器設定。",
    minimum_return_invalid: "最低年化淨報酬門檻設定無效，因此暫不建議。",
    minimum_return_not_met:
      "依最終可行規模重新計算後，年化淨報酬未達最低門檻，因此暫不建議。",
    no_feasible_size:
      "計入現金、最低手續費及集中度上限後，沒有可行的買入規模。",
    benchmark_abstained: "估值選擇暫不估值，因此不提供可接受的投資建議。",
    final_size_return_unavailable: "最終規模的報酬無法可靠計算，因此暫不建議。",
    portfolio_snapshot_unavailable:
      "缺少可靠的投資組合風險快照，因此暫不建議。",
    missing_reason: "請填寫決策理由；每次決策都會保存獨立的稽核紀錄。",
    invalid_defer_time:
      "請選擇未來的延後日期與時間。延後不會延長建議的有效期間。",
    challenge_invalid:
      "確認已逾時或與目前內容不符。原理由已保留，請重新預覽後確認。",
    version_conflict:
      "資料版本已更新，請重新整理並核對最新內容，再重新預覽或送出。",
    idempotency_conflict: "這次請求的內容已改變，請重新核對內容後再次送出。",
    superseded_inputs: "關鍵輸入已更新，請核對最新資料後重新建立分析請求。",
    resource_unavailable: "資源不存在，或目前帳號無法使用這份資料。",
    invalid_transition: "目前狀態不允許這項操作，請重新整理確認決策歷史。",
    invalid_source_selection:
      "請重新確認目前估值使用的比較來源，並填寫選擇理由。",
    invalid_admission_intent:
      "請確認 Thesis、已發布估值、投資組合版本及來源選擇理由。",
    invalid_recommendation_request:
      "分析前提尚未齊備。請確認 Thesis 已啟用、具有失效條件，並已發布有效估值及設定現金與成本。",
    forecast_expired: "估值已失效，請重新計算並發布估值後再試。",
    cost_profile_version_conflict:
      "成本設定已更新，請重新計算並發布估值後再建立分析請求。",
    portfolio_prerequisites_missing:
      "請先在投資組合設定有效的成本與可投資現金。",
    official_security_missing:
      "缺少官方價格或分類資料，請補齊伺服器來源資料後再試。",
    invalid_candidate:
      "AI 輸出未通過格式或引用檢查，沒有發布建議。請檢查來源後重新建立請求。",
    invalid_critic:
      "引用檢查結果不完整，沒有發布建議。請檢查來源後重新建立請求。",
    critic_rejected: "引用檢查未通過，沒有發布建議；請先核對原始來源。",
    provider_unavailable:
      "AI 服務目前不可用，請確認服務設定後再試；不會以假資料產生建議。",
    provider_transport_failure:
      "AI 服務連線逾時或暫時失敗，工作會依伺服器重試規則處理。",
    critic_transport_failure:
      "引用檢查服務暫時連線失敗，請稍後重新整理工作狀態。",
    recommendation_unavailable:
      "伺服器目前無法完成操作。請稍後重新整理；原輸入不會自動送出。",
  };
  return (
    messages[code] ?? "這項操作未完成，請重新整理並確認輸入與來源資料後再試。"
  );
}

export function createRecommendationClient(
  baseUrl = "/api",
  fetcher: typeof fetch = fetch,
): RecommendationClient {
  return {
    list: (company, before) =>
      safe(
        list_recommendation_requests_api_companies__company_id__recommendation_requests_get(
          baseUrl,
          company,
          { before },
          fetcher,
        ),
      ),
    request: (company, input) =>
      safe(
        request_recommendation_api_companies__company_id__recommendation_requests_post(
          baseUrl,
          company,
          input,
          fetcher,
        ),
      ),
    status: (id) =>
      safe(
        get_recommendation_request_api_recommendation_requests__request_id__get(
          baseUrl,
          id,
          fetcher,
        ),
      ),
    detail: (id, version, beforeSequence) =>
      safe(
        get_recommendation_api_recommendations__record_id__versions__version__get(
          baseUrl,
          id,
          String(version),
          { before_sequence: beforeSequence },
          fetcher,
        ),
      ),
    preview: (id, input) =>
      safe(
        preview_recommendation_decision_api_recommendations__record_id__decision_previews_post(
          baseUrl,
          id,
          input,
          fetcher,
        ),
      ),
    decide: (id, input) =>
      safe(
        decide_recommendation_api_recommendations__record_id__decisions_post(
          baseUrl,
          id,
          input,
          fetcher,
        ),
      ),
    theses: (company) =>
      safe(
        list_theses_api_companies__company_id__theses_get(
          baseUrl,
          company,
          fetcher,
        ),
      ),
    portfolio: () => safe(get_portfolio_api_portfolio_get(baseUrl, fetcher)),
  };
}

export const recommendationClient = createRecommendationClient();
