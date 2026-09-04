import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { AccessApp } from "./routes";
import type { AccessClient } from "./client";
import type { SessionProfile } from "./contracts";

const owner = { kind: "owner" as const, user_id: "u-owner", display_name: "Owner", session_expires_at: "2030-01-01T00:00:00Z", is_recovery_session: false, capabilities: ["research"] };
const admin = { kind: "admin" as const, user_id: "u-admin", display_name: "Admin", session_expires_at: "2030-01-01T00:00:00Z", is_recovery_session: false, capabilities: ["accounts"] };
const client = (profile: SessionProfile = owner): AccessClient => ({
  getSession: vi.fn().mockResolvedValue(profile), logout: vi.fn().mockResolvedValue(undefined),
  listAccounts: vi.fn().mockResolvedValue([{ user_id: "u-1", masked_identity: "Learner", role: "learner", status: "active", version: 3 }]),
  getAccount: vi.fn().mockResolvedValue({ user_id: "u-1", masked_identity: "Learner", role: "learner", status: "active", version: 3 }),
  previewAccountAction: vi.fn().mockResolvedValue({ challenge_token: "secret", expires_at: "2030-01-01T00:05:00Z", target_version: 3, impact_summary: { subject: "停用 Learner", action_label: "確認高風險操作", before: { status: "active" }, after: { status: "disabled" }, consequences: ["工作階段將失效"], confirmation_verb: "確認停用" } }),
  confirmAccountAction: vi.fn().mockResolvedValue({ accepted: true, challenge_id: "c-1" }), createAccount: vi.fn().mockResolvedValue({ user_id:"new",masked_identity:"google",role:"learner",status:"active",version:1 }),
});

it("renders role-safe Owner navigation and profile", async () => {
  render(<AccessApp client={client()} initialPath="/profile" />);
  expect(await screen.findByRole("heading", { name: "Owner 個人資料" })).toBeVisible();
  expect(screen.getByRole("link", { name: "帳號管理" })).toHaveClass("access-nav-link");
  expect(screen.getByRole("link", { name: "個人資料" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "登出" })).toHaveClass("secondary-button");
});

it("isolates Learner profile fields and keeps research navigation", async () => {
  render(<AccessApp client={client({ ...owner, kind: "learner" })} initialPath="/profile" />);
  expect(await screen.findByRole("heading", { name: "Learner 個人資料" })).toBeVisible();
  expect(screen.getByRole("link", { name: "公司研究" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "帳號管理" })).not.toBeInTheDocument();
});

it("shows recovery as a persistent critical Owner banner without an activation control", async () => {
  render(<AccessApp client={client({ ...owner, is_recovery_session: true, recovery_task_url: "/tasks/disable-recovery" })} initialPath="/profile" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("緊急復原工作階段啟用中");
  expect(screen.getByRole("link", { name: "查看停用任務" })).toHaveAttribute("href", "/tasks/disable-recovery");
  expect(screen.queryByRole("button", { name: /啟用復原/ })).not.toBeInTheDocument();
});

it("shows uniform unavailable for an Admin company deep link", async () => {
  render(<AccessApp client={client(admin)} initialPath="/companies/secret" />);
  expect(await screen.findByRole("heading", { name: "資源無法使用" })).toBeVisible();
  expect(screen.queryByText("secret")).not.toBeInTheDocument();
});

it.each(["learner", "admin"] as const)(
  "rejects the company Trades deep link for %s without rendering portfolio data",
  async (kind) => {
    render(<AccessApp client={client({ ...(kind === "admin" ? admin : owner), kind })} initialPath="/companies/2330/trades" />);
    expect(await screen.findByRole("heading", { name: "資源無法使用" })).toBeVisible();
    expect(screen.queryByText("投資組合與交易")).not.toBeInTheDocument();
    expect(screen.queryByText("2330 · 交易")).not.toBeInTheDocument();
  },
);

it("keeps confirmation token volatile and clears it after cancellation", async () => {
  const user = userEvent.setup(); render(<AccessApp client={client(owner)} initialPath="/admin/accounts/u-1" />);
  await user.click(await screen.findByRole("button", { name: "停用帳號" }));
  expect(await screen.findByText("停用 Learner")).toBeVisible();
  expect(location.href).not.toContain("secret");
  expect(localStorage.length + sessionStorage.length).toBe(0);
  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByText("停用 Learner")).not.toBeInTheDocument();
});

it("requires a fresh preview after confirmation expiry or version failure", async () => {
  const user = userEvent.setup(); const failing = client(owner); failing.confirmAccountAction = vi.fn().mockRejectedValue(new Error("challenge_invalid"));
  render(<AccessApp client={failing} initialPath="/admin/accounts/u-1" />);
  await user.click(await screen.findByRole("button", { name: "停用帳號" }));
  await user.type(screen.getByLabelText("原因"), "狀態已變更"); await user.click(screen.getByRole("button", { name: "確認停用" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("請重新預覽");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "停用帳號" }));
  expect(failing.previewAccountAction).toHaveBeenCalledTimes(2);
});

it("offers every consequential account and identity action only to Owner", async () => {
  const ownerView = render(<AccessApp client={client(owner)} initialPath="/admin/accounts/u-1" />);
  for (const name of ["變更角色","停用帳號","新增身分","停用身分","替換身分"]) expect(await screen.findByRole("button",{name})).toBeVisible();
  ownerView.unmount(); render(<AccessApp client={client(admin)} initialPath="/admin/accounts/u-1" />);
  expect(await screen.findByRole("heading",{name:"Learner"})).toBeVisible(); expect(screen.queryByRole("button",{name:"停用帳號"})).not.toBeInTheDocument();
});

it("routes role, status, and identity intents through server preview", async () => {
  const user=userEvent.setup(); const owned=client(owner); render(<AccessApp client={owned} initialPath="/admin/accounts/u-1"/>);
  for(const [button,action] of [["變更角色","change_role"],["停用帳號","change_status"],["新增身分","add_identity"],["停用身分","disable_identity"],["替換身分","replace_identity"]] as const){
    await user.click(await screen.findByRole("button",{name:button})); expect(owned.previewAccountAction).toHaveBeenLastCalledWith(action,"u-1",3,expect.any(Object)); await user.click(screen.getByRole("button",{name:"取消"}));
  }
});

it("previews account creation before sending the generated create contract", async () => {
  const user=userEvent.setup(); const owned=client(owner); render(<AccessApp client={owned} initialPath="/admin/accounts"/>);
  await user.click(await screen.findByRole("button",{name:"預覽建立帳號"})); expect(owned.previewAccountAction).toHaveBeenCalledWith("create_account","new_account",1,expect.objectContaining({role:"learner"}));
});
