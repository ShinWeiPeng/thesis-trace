import { FormEvent, useEffect, useMemo, useState } from "react";

import type { ActionInboxResponse, ActionItemResponse, ActionItemTransitionBody } from "../generated/api";
import { workflowClient, type ActionInboxQuery, type WorkflowClient } from "./client";

const statusLabels: Record<ActionItemResponse["status"], string> = {
  pending: "待處理", in_progress: "處理中", deferred: "已延後",
  completed: "已完成", dismissed: "已略過",
};
const transitionLabels: Record<ActionItemTransitionBody["target_status"], string> = {
  pending: "移回待處理", in_progress: "開始處理", deferred: "延後",
  completed: "完成", dismissed: "略過",
};

function queryFrom(path: URL): ActionInboxQuery {
  const encoded = path.pathname.startsWith("/actions/") ? path.searchParams.get("return") : null;
  const source = encoded === null ? path.searchParams : new URLSearchParams(encoded);
  const pageSize = Number(source.get("page_size"));
  return {
    search: source.get("search"), company_id: source.get("company_id"),
    status: source.get("status"), priority: source.get("priority"),
    open_only: source.get("open_only") !== "false", sort: source.get("sort") ?? "effective_priority",
    direction: source.get("direction") ?? "desc",
    page_size: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
    cursor: source.get("cursor"),
  };
}

function queryString(query: ActionInboxQuery): string {
  const result = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "") result.set(key, String(value));
  }
  return result.toString();
}

function Detail({ item, client, onChanged, returnQuery }: {
  item: ActionItemResponse; client: WorkflowClient;
  onChanged(item: ActionItemResponse): void; returnQuery: string;
}) {
  const [reason, setReason] = useState(""); const [deferUntil, setDeferUntil] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const transition = async (target: ActionItemTransitionBody["target_status"]) => {
    setBusy(true); setError("");
    try {
      const changed = await client.transitionActionItem(item.item_id, {
        expected_version: item.version, target_status: target, reason: reason.trim(),
        defer_until: target === "deferred" ? new Date(deferUntil).toISOString() : null,
        idempotency_key: crypto.randomUUID(),
      });
      onChanged(changed); setReason("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "操作失敗"); }
    finally { setBusy(false); }
  };
  return <article className="action-detail" aria-labelledby="action-detail-title">
    <a className="action-back" href={`/actions${returnQuery ? `?${returnQuery}` : ""}`}>← 返回待辦</a>
    <div className="action-detail-heading"><div><p className="eyebrow">{item.item_type === "anomaly_review" ? "Anomaly review" : item.item_type}</p><h2 id="action-detail-title">{item.company_ticker} · {item.company_name}</h2></div><span className={`action-status status-${item.status}`}>{statusLabels[item.status]}</span></div>
    <p className="action-reason">{item.reason}</p>
    <dl className="action-facts"><div><dt>優先級</dt><dd>{item.effective_priority}</dd></div><div><dt>版本</dt><dd>{item.version}</dd></div><div><dt>來源</dt><dd>{item.source_domain} / {item.source_record_id} / v{item.source_version}</dd></div><div><dt>政策</dt><dd>{item.priority_policy_version}</dd></div></dl>
    <p className="priority-explanation">{item.priority_reason}</p>
    <a className="secondary-button context-link" href={`/companies/${encodeURIComponent(item.company_id)}?fromAction=${encodeURIComponent(item.item_id)}&return=${encodeURIComponent(returnQuery)}`}>開啟公司脈絡</a>
    {item.allowed_transitions.length > 0 && <section className="action-controls" aria-label="待辦操作"><label>處理理由<input value={reason} onChange={(event) => setReason(event.target.value)} /></label>{item.allowed_transitions.includes("deferred") && <label>延後至<input type="datetime-local" value={deferUntil} onChange={(event) => setDeferUntil(event.target.value)} /></label>}<div className="action-buttons">{item.allowed_transitions.map((target) => <button key={target} type="button" className={target === "completed" ? "primary-button" : "secondary-button"} disabled={busy || !reason.trim() || (target === "deferred" && !deferUntil)} onClick={() => transition(target)}>{transitionLabels[target]}</button>)}</div></section>}
    {error && <p role="alert" className="error-banner">{error}</p>}
  </article>;
}

export function ActionInboxRoutes({ client = workflowClient, initialPath }: { client?: WorkflowClient; initialPath?: string }) {
  const rawPath = initialPath ?? `${location.pathname}${location.search}`;
  const path = useMemo(() => new URL(rawPath, "http://thesis-trace.local"), [rawPath]);
  const selectedId = path.pathname.startsWith("/actions/") ? decodeURIComponent(path.pathname.slice("/actions/".length)) : null;
  const initialQuery = useMemo(() => queryFrom(path), [path]);
  const [query, setQuery] = useState<ActionInboxQuery>(initialQuery);
  const [page, setPage] = useState<ActionInboxResponse | null>(null);
  const [detail, setDetail] = useState<ActionItemResponse | null>(null);
  const [search, setSearch] = useState(initialQuery.search ?? ""); const [error, setError] = useState("");
  const load = async (nextQuery: ActionInboxQuery) => {
    setError("");
    try { setPage(await client.queryInbox(nextQuery)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "無法載入待辦"); }
  };
  useEffect(() => {
    let active = true;
    client.queryInbox(initialQuery).then((value) => active && setPage(value)).catch(() => active && setError("無法載入待辦"));
    if (selectedId) client.getActionItem(selectedId).then((value) => active && setDetail(value)).catch(() => active && setError("資源無法使用"));
    return () => { active = false; };
  }, [client, initialQuery, selectedId]);
  const applySearch = (event: FormEvent) => { event.preventDefault(); const next = { ...query, search: search.trim() || null, cursor: null }; setQuery(next); void load(next); };
  const returnQuery = queryString({ ...query, cursor: null });
  return <main className="action-page"><header className="action-page-header"><div><p className="eyebrow">Workflow</p><h1>Action Inbox</h1><p>由伺服器計算優先級、合法操作與一致摘要。</p></div><form className="action-search" role="search" onSubmit={applySearch}><label htmlFor="action-search">搜尋公司或理由</label><div><input id="action-search" value={search} onChange={(event) => setSearch(event.target.value)} /><button className="primary-button">搜尋</button></div></form></header>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {page && <section className="action-summary" aria-label="待辦摘要"><span>緊急 {page.summary.urgent}</span><span>今日到期 {page.summary.due_today}</span><span>已延後 {page.summary.deferred}</span><span>全部待處理 {page.summary.all_open}</span></section>}
    <div className={`action-master-detail${selectedId ? " has-detail" : ""}`}><section className="action-list" aria-label="待辦清單">{!page ? <p>載入中…</p> : page.items.length === 0 ? <p className="empty-state">目前沒有符合條件的待辦。</p> : page.items.map((item) => <a className={`action-row${selectedId === item.item_id ? " selected" : ""}`} key={item.item_id} href={`/actions/${encodeURIComponent(item.item_id)}?return=${encodeURIComponent(returnQuery)}`}><span className={`priority-dot priority-${item.effective_priority}`} aria-label={`${item.effective_priority} 優先級`} /><span><strong>{item.company_ticker} · {item.company_name}</strong><small>{item.reason}</small></span><span className={`action-status status-${item.status}`}>{statusLabels[item.status]}</span></a>)}{page?.next_cursor && <button className="secondary-button load-more" onClick={() => { const next = { ...query, cursor: page.next_cursor }; setQuery(next); void load(next); }}>載入下一頁</button>}</section>
      {selectedId && <aside className="action-detail-pane">{detail ? <Detail item={detail} client={client} returnQuery={returnQuery} onChanged={(changed) => { setDetail(changed); setPage((current) => current && ({ ...current, items: current.items.map((item) => item.item_id === changed.item_id ? changed : item) })); }} /> : <p>載入明細…</p>}</aside>}
    </div>
  </main>;
}
