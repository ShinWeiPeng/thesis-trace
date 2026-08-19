export type { AccountResponse as AccountSummary, ConfirmationChallengeResponse as ConfirmationChallenge, ImpactSummaryResponse } from "../generated/api";
import type { AdminSessionResponse, LearnerSessionResponse, OwnerSessionResponse } from "../generated/api";
export type SessionProfile = OwnerSessionResponse | LearnerSessionResponse | AdminSessionResponse;
