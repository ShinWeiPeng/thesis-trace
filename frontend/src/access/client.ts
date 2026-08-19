import { account_detail_api_admin_accounts__user_id__get, confirm_action_api_confirmed_actions_post, create_account_api_admin_accounts_post, delete_session_api_session_delete, get_session_api_session_get, list_accounts_api_admin_accounts_get, preview_confirmation_api_confirmation_challenges_post, type AccountResponse, type AdminSessionResponse, type ConfirmationChallengeResponse, type ConfirmedActionResponse, type LearnerSessionResponse, type OwnerSessionResponse, type Role } from "../generated/api";
export type AccountAction = "create_account" | "change_role" | "change_status" | "add_identity" | "disable_identity" | "replace_identity";
export interface AccessClient {
  getSession(): Promise<OwnerSessionResponse | LearnerSessionResponse | AdminSessionResponse>; logout(): Promise<unknown>;
  listAccounts(): Promise<AccountResponse[]>; getAccount(id: string): Promise<AccountResponse>;
  previewAccountAction(action: AccountAction, targetId: string, version: number, payload: Record<string, unknown>): Promise<ConfirmationChallengeResponse>;
  confirmAccountAction(action: Exclude<AccountAction, "create_account">, version: number, payload: Record<string, unknown>, token: string, reason: string): Promise<ConfirmedActionResponse>;
  createAccount(payload: { role: Role; provider_id: string; provider_type: string; provider_subject: string; email_fact: string }, token: string, reason: string): Promise<AccountResponse>;
}
const baseUrl = "/api";
export const accessClient: AccessClient = {
  getSession: () => get_session_api_session_get(baseUrl), logout: () => delete_session_api_session_delete(baseUrl),
  listAccounts: () => list_accounts_api_admin_accounts_get(baseUrl), getAccount: (id) => account_detail_api_admin_accounts__user_id__get(baseUrl, id),
  previewAccountAction: (action_type, target_id, target_version, payload) => preview_confirmation_api_confirmation_challenges_post(baseUrl, { action_type, target_id, target_version, payload }),
  confirmAccountAction: (action_type, target_version, payload, challenge_token, reason) => confirm_action_api_confirmed_actions_post(baseUrl, { action_type, target_version, payload, challenge_token, reason }),
  createAccount: (payload, challenge_token, reason) => create_account_api_admin_accounts_post(baseUrl, { ...payload, challenge_token, reason }),
};
