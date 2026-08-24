import {
  create_anomaly_review_action_api_action_items_anomaly_reviews_post,
  get_action_item_api_action_items__item_id__get,
  query_action_inbox_api_action_items_get,
  transition_action_item_api_action_items__item_id__transitions_post,
  type ActionInboxResponse,
  type ActionItemCreateBody,
  type ActionItemResponse,
  type ActionItemTransitionBody,
} from "../generated/api";

export type ActionInboxQuery = NonNullable<Parameters<typeof query_action_inbox_api_action_items_get>[1]>;

export interface WorkflowClient {
  createAnomalyReview(input: ActionItemCreateBody): Promise<ActionItemResponse>;
  queryInbox(query?: ActionInboxQuery): Promise<ActionInboxResponse>;
  getActionItem(itemId: string): Promise<ActionItemResponse>;
  transitionActionItem(itemId: string, input: ActionItemTransitionBody): Promise<ActionItemResponse>;
}

async function safe<T>(operation: Promise<T>): Promise<T> {
  try { return await operation; }
  catch (error) {
    if (!(error instanceof Response)) throw error;
    let message = "伺服器目前無法完成要求，請稍後重試。";
    try {
      const body = await error.json() as { detail?: string };
      if (typeof body.detail === "string") message = body.detail;
    } catch { /* stable fallback */ }
    throw new Error(message);
  }
}

export function createWorkflowClient({ baseUrl, fetcher = fetch }: { baseUrl: string; fetcher?: typeof fetch }): WorkflowClient {
  return {
    createAnomalyReview: (input) => safe(create_anomaly_review_action_api_action_items_anomaly_reviews_post(baseUrl, input, fetcher)),
    queryInbox: (query = {}) => safe(query_action_inbox_api_action_items_get(baseUrl, query, fetcher)),
    getActionItem: (itemId) => safe(get_action_item_api_action_items__item_id__get(baseUrl, itemId, fetcher)),
    transitionActionItem: (itemId, input) => safe(transition_action_item_api_action_items__item_id__transitions_post(baseUrl, itemId, input, fetcher)),
  };
}

export const workflowClient = createWorkflowClient({ baseUrl: "/api" });
