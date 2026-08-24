import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ActionInboxResponse, ActionItemResponse } from "../generated/api";
import { ActionInboxRoutes } from "./routes";
import type { WorkflowClient } from "./client";

const action: ActionItemResponse = {
  item_id: "action-1", version: 1, item_type: "anomaly_review",
  source_domain: "anomaly_assessment", source_record_id: "assessment-1", source_version: 2,
  company_id: "company-1", company_ticker: "TT", company_name: "Thesis Trace",
  reason: "Review source conflict", status: "pending", system_priority: "high",
  effective_priority: "high", safety_floor: null, safety_locked: false,
  priority_rule_ids: ["workflow.shadow-anomaly-review-v1"],
  priority_policy_version: "action-priority-v1", priority_reason: "Shadow review",
  created_at: "2026-08-24T00:00:00Z", updated_at: "2026-08-24T00:00:00Z",
  due_at: null, defer_until: null, recurrence_of: null,
  allowed_transitions: ["in_progress", "deferred", "completed", "dismissed"],
};
const page: ActionInboxResponse = {
  summary: { urgent: 1, due_today: 0, deferred: 0, all_open: 1 },
  total_count: 1, items: [action], next_cursor: null, as_of: "2026-08-24T00:00:00Z",
};

const client = (): WorkflowClient => ({
  createAnomalyReview: vi.fn(), queryInbox: vi.fn().mockResolvedValue(page),
  getActionItem: vi.fn().mockResolvedValue(action),
  transitionActionItem: vi.fn().mockResolvedValue({ ...action, version: 2, status: "completed", allowed_transitions: [] }),
});

it("renders server summary and a wide/narrow-compatible list-detail route", async () => {
  const api = client();
  render(<ActionInboxRoutes client={api} initialPath="/actions/action-1?return=search%3DTT" />);
  expect(await screen.findByRole("heading", { name: "Action Inbox" })).toBeVisible();
  expect(screen.getByText("緊急 1")).toBeVisible();
  expect(await screen.findByRole("heading", { name: "TT · Thesis Trace" })).toBeVisible();
  expect(screen.getByRole("link", { name: "開啟公司脈絡" })).toHaveAttribute(
    "href", expect.stringContaining("/companies/company-1"),
  );
  expect(api.queryInbox).toHaveBeenCalledWith(expect.objectContaining({ search: "TT" }));
});

it("submits only transition intent and reloads the server projection", async () => {
  const user = userEvent.setup(); const api = client();
  render(<ActionInboxRoutes client={api} initialPath="/actions/action-1" />);
  await screen.findByRole("heading", { name: "TT · Thesis Trace" });
  await user.type(screen.getByLabelText("處理理由"), "Reviewed against the filing");
  await user.click(screen.getByRole("button", { name: "完成" }));
  expect(api.transitionActionItem).toHaveBeenCalledWith("action-1", expect.objectContaining({
    expected_version: 1, target_status: "completed", reason: "Reviewed against the filing",
  }));
  expect(api.queryInbox).toHaveBeenCalledTimes(2);
  expect((await screen.findAllByText("已完成"))[0]).toBeVisible();
});

it("uses summary cards and controls as server query inputs", async () => {
  const user = userEvent.setup(); const api = client();
  render(<ActionInboxRoutes client={api} initialPath="/actions" />);
  await screen.findByText("緊急 1");

  await user.click(screen.getByRole("button", { name: "緊急 1" }));
  expect(api.queryInbox).toHaveBeenLastCalledWith(expect.objectContaining({ priority: "urgent" }));

  await user.selectOptions(screen.getByLabelText("排序"), "created_at");
  expect(api.queryInbox).toHaveBeenLastCalledWith(expect.objectContaining({ sort: "created_at" }));
});

it("restores the complete query, cursor, and scroll position after data renders", async () => {
  const api = client(); const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  const returned = new URLSearchParams({ item_type: "anomaly_review", created_from: "2026-08-01T00:00:00Z",
    due_to: "2026-08-31T23:59:59Z", cursor: "signed-cursor", scroll: "120" }).toString();
  render(<ActionInboxRoutes client={api} initialPath={`/actions/action-1?return=${encodeURIComponent(returned)}`} />);

  await screen.findByRole("heading", { name: "TT · Thesis Trace" });
  expect(api.queryInbox).toHaveBeenCalledWith(expect.objectContaining({
    item_type: "anomaly_review", created_from: "2026-08-01T00:00:00Z",
    due_to: "2026-08-31T23:59:59Z", cursor: "signed-cursor",
  }));
  expect(scroll).toHaveBeenCalledWith({ top: 120 });
  scroll.mockRestore();
});
