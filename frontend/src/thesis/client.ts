import {
  autosave_thesis_reflection_api_theses__thesis_id__reflection_draft_put,
  complete_thesis_reflection_api_theses__thesis_id__reflections_post,
  create_thesis_api_companies__company_id__theses_post,
  get_thesis_api_theses__thesis_id__get,
  list_companies_api_companies_get,
  list_theses_api_companies__company_id__theses_get,
  preview_thesis_transition_api_theses__thesis_id__transition_previews_post,
  save_thesis_api_theses__thesis_id__put,
  save_thesis_outcome_api_theses__thesis_id__outcomes_post,
  transition_thesis_api_theses__thesis_id__transitions_post,
  save_valuation_draft_api_theses__thesis_id__valuation_draft_put,
  preview_valuation_publication_api_theses__thesis_id__valuation_publication_previews_post,
  publish_valuation_api_theses__thesis_id__valuations_post,
  type CompanyResponse,
  type ThesisCreateBody,
  type ThesisOutcomeBody,
  type ThesisReflectionCompleteBody,
  type ThesisReflectionDraftBody,
  type ThesisResponse,
  type ThesisSaveBody,
  type ThesisTransitionBody,
  type ThesisTransitionPreviewBody,
  type ThesisTransitionPreviewResponse,
  type ValuationDraftSaveBody,
  type ValuationPublicationBody,
  type ValuationPublicationPreviewBody,
  type ValuationPublicationPreviewResponse,
} from "../generated/api";

export interface ThesisClient {
  listCompanies(): Promise<CompanyResponse[]>;
  list(companyId: string): Promise<ThesisResponse[]>;
  get(thesisId: string): Promise<ThesisResponse>;
  create(companyId: string, input: ThesisCreateBody): Promise<ThesisResponse>;
  save(thesisId: string, input: ThesisSaveBody): Promise<ThesisResponse>;
  previewTransition(thesisId: string, input: ThesisTransitionPreviewBody): Promise<ThesisTransitionPreviewResponse>;
  transition(thesisId: string, input: ThesisTransitionBody): Promise<ThesisResponse>;
  saveOutcome(thesisId: string, input: ThesisOutcomeBody): Promise<ThesisResponse>;
  autosaveReflection(thesisId: string, input: ThesisReflectionDraftBody): Promise<ThesisResponse>;
  completeReflection(thesisId: string, input: ThesisReflectionCompleteBody): Promise<ThesisResponse>;
  saveValuation(thesisId: string, input: ValuationDraftSaveBody): Promise<ThesisResponse>;
  previewValuationPublication(thesisId: string, input: ValuationPublicationPreviewBody): Promise<ValuationPublicationPreviewResponse>;
  publishValuation(thesisId: string, input: ValuationPublicationBody): Promise<ThesisResponse>;
}

async function safe<T>(operation: Promise<T>): Promise<T> {
  try { return await operation; }
  catch (error) {
    if (!(error instanceof Response)) throw error;
    let message = "伺服器目前無法完成要求，請重新載入後再試。";
    try {
      const body = await error.json() as { detail?: string };
      if (typeof body.detail === "string") message = body.detail;
    } catch { /* stable fallback */ }
    throw new Error(message);
  }
}

export function createThesisClient({ baseUrl, fetcher = fetch }: { baseUrl: string; fetcher?: typeof fetch }): ThesisClient {
  return {
    listCompanies: () => safe(list_companies_api_companies_get(baseUrl, fetcher)),
    list: (companyId) => safe(list_theses_api_companies__company_id__theses_get(baseUrl, companyId, fetcher)),
    get: (thesisId) => safe(get_thesis_api_theses__thesis_id__get(baseUrl, thesisId, fetcher)),
    create: (companyId, input) => safe(create_thesis_api_companies__company_id__theses_post(baseUrl, companyId, input, fetcher)),
    save: (thesisId, input) => safe(save_thesis_api_theses__thesis_id__put(baseUrl, thesisId, input, fetcher)),
    previewTransition: (thesisId, input) => safe(preview_thesis_transition_api_theses__thesis_id__transition_previews_post(baseUrl, thesisId, input, fetcher)),
    transition: (thesisId, input) => safe(transition_thesis_api_theses__thesis_id__transitions_post(baseUrl, thesisId, input, fetcher)),
    saveOutcome: (thesisId, input) => safe(save_thesis_outcome_api_theses__thesis_id__outcomes_post(baseUrl, thesisId, input, fetcher)),
    autosaveReflection: (thesisId, input) => safe(autosave_thesis_reflection_api_theses__thesis_id__reflection_draft_put(baseUrl, thesisId, input, fetcher)),
    completeReflection: (thesisId, input) => safe(complete_thesis_reflection_api_theses__thesis_id__reflections_post(baseUrl, thesisId, input, fetcher)),
    saveValuation: (thesisId, input) => safe(save_valuation_draft_api_theses__thesis_id__valuation_draft_put(baseUrl, thesisId, input, fetcher)),
    previewValuationPublication: (thesisId, input) => safe(preview_valuation_publication_api_theses__thesis_id__valuation_publication_previews_post(baseUrl, thesisId, input, fetcher)),
    publishValuation: (thesisId, input) => safe(publish_valuation_api_theses__thesis_id__valuations_post(baseUrl, thesisId, input, fetcher)),
  };
}

export const thesisClient = createThesisClient({ baseUrl: "/api" });
export type { ThesisResponse, ThesisTransitionPreviewResponse } from "../generated/api";
