import {
  confirm_portfolio_trade_api_portfolio_trades_post,
  get_portfolio_api_portfolio_get,
  preview_portfolio_trade_api_portfolio_trade_previews_post,
  preview_portfolio_csv_api_portfolio_csv_previews_post,
  preview_portfolio_correction_api_portfolio_trade_correction_previews_post,
  confirm_portfolio_correction_api_portfolio_trade_corrections_post,
  preview_portfolio_company_action_api_portfolio_company_action_previews_post,
  confirm_portfolio_company_action_api_portfolio_company_actions_post,
  save_cost_profile_api_portfolio_cost_profile_put,
  save_investable_cash_api_portfolio_investable_cash_put,
  type CostProfileSaveBody,
  type InvestableCashSaveBody,
  type PortfolioResponse,
  type TradeConfirmBody,
  type TradePreviewBody,
  type TradePreviewResponse,
  type CanonicalCsvPreviewResponse,
  type TradeCorrectionPreviewBody,
  type TradeCorrectionConfirmBody,
  type CompanyActionPreviewBody,
  type CompanyActionConfirmBody,
  type PortfolioMutationPreviewResponse,
} from "../generated/api";

export interface PortfolioClient {
  get(): Promise<PortfolioResponse>;
  saveCostProfile(input: CostProfileSaveBody): Promise<PortfolioResponse>;
  saveCash(input: InvestableCashSaveBody): Promise<PortfolioResponse>;
  previewTrade(input: TradePreviewBody): Promise<TradePreviewResponse>;
  confirmTrade(input: TradeConfirmBody): Promise<PortfolioResponse>;
  previewCsv(content: string): Promise<CanonicalCsvPreviewResponse>;
  previewCorrection(input: TradeCorrectionPreviewBody): Promise<PortfolioMutationPreviewResponse>;
  confirmCorrection(input: TradeCorrectionConfirmBody): Promise<PortfolioResponse>;
  previewCompanyAction(input: CompanyActionPreviewBody): Promise<PortfolioMutationPreviewResponse>;
  confirmCompanyAction(input: CompanyActionConfirmBody): Promise<PortfolioResponse>;
}

async function safe<T>(operation: Promise<T>): Promise<T> {
  try { return await operation; }
  catch (error) {
    if (!(error instanceof Response)) throw error;
    let message = error.status === 404 ? "尚未建立投資組合，請先設定成本。" : "伺服器目前無法完成要求。";
    try { const body = await error.json() as { detail?: string }; if (body.detail) message = body.detail; } catch { /* fallback */ }
    throw new Error(message);
  }
}

export function createPortfolioClient({ baseUrl, fetcher = fetch }: { baseUrl: string; fetcher?: typeof fetch }): PortfolioClient {
  return {
    get: () => safe(get_portfolio_api_portfolio_get(baseUrl, fetcher)),
    saveCostProfile: (input) => safe(save_cost_profile_api_portfolio_cost_profile_put(baseUrl, input, fetcher)),
    saveCash: (input) => safe(save_investable_cash_api_portfolio_investable_cash_put(baseUrl, input, fetcher)),
    previewTrade: (input) => safe(preview_portfolio_trade_api_portfolio_trade_previews_post(baseUrl, input, fetcher)),
    confirmTrade: (input) => safe(confirm_portfolio_trade_api_portfolio_trades_post(baseUrl, input, fetcher)),
    previewCsv: (content) => safe(preview_portfolio_csv_api_portfolio_csv_previews_post(baseUrl, { content }, fetcher)),
    previewCorrection: (input) => safe(preview_portfolio_correction_api_portfolio_trade_correction_previews_post(baseUrl, input, fetcher)),
    confirmCorrection: (input) => safe(confirm_portfolio_correction_api_portfolio_trade_corrections_post(baseUrl, input, fetcher)),
    previewCompanyAction: (input) => safe(preview_portfolio_company_action_api_portfolio_company_action_previews_post(baseUrl, input, fetcher)),
    confirmCompanyAction: (input) => safe(confirm_portfolio_company_action_api_portfolio_company_actions_post(baseUrl, input, fetcher)),
  };
}

export const portfolioClient = createPortfolioClient({ baseUrl: "/api" });
export type { PortfolioResponse, TradePreviewBody, TradePreviewResponse } from "../generated/api";
