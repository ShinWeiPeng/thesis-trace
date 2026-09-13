import { FormEvent, useEffect, useMemo, useState } from "react";

import type {
  ActionInboxResponse,
  ActionItemResponse,
  ActionItemTransitionBody,
} from "../generated/api";
import {
  workflowClient,
  type ActionInboxQuery,
  type WorkflowClient,
} from "./client";

const statusLabels: Record<ActionItemResponse["status"], string> = {
  pending: "待處理",
  in_progress: "處理中",
  deferred: "已延後",
  completed: "已完成",
  dismissed: "已略過",
};
const transitionLabels: Record<
  ActionItemTransitionBody["target_status"],
  string
> = {
  pending: "移回待處理",
  in_progress: "開始處理",
  deferred: "延後",
  completed: "完成",
  dismissed: "略過",
};

function queryFrom(path: URL): ActionInboxQuery {
  const encoded = path.pathname.startsWith("/actions/")
    ? path.searchParams.get("return")
    : null;
  const source =
    encoded === null ? path.searchParams : new URLSearchParams(encoded);
  const pageSize = Number(source.get("page_size"));
  return {
    search: source.get("search"),
    company_id: source.get("company_id"),
    item_type: source.get("item_type"),
    status: source.get("status"),
    priority: source.get("priority"),
    created_from: source.get("created_from"),
    created_to: source.get("created_to"),
    due_from: source.get("due_from"),
    due_to: source.get("due_to"),
    open_only: source.get("open_only") !== "false",
    sort: source.get("sort") ?? "effective_priority",
    direction: source.get("direction") ?? "desc",
    page_size: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
    cursor: source.get("cursor"),
  };
}

function queryString(query: ActionInboxQuery): string {
  const result = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "")
      result.set(key, String(value));
  }
  return result.toString();
}

function Detail({
  item,
  client,
  onChanged,
  returnQuery,
}: {
  item: ActionItemResponse;
  client: WorkflowClient;
  onChanged(item: ActionItemResponse): Promise<void>;
  returnQuery: string;
}) {
  const [reason, setReason] = useState("");
  const [deferUntil, setDeferUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const transition = async (
    target: ActionItemTransitionBody["target_status"],
  ) => {
    setBusy(true);
    setError("");
    try {
      const changed = await client.transitionActionItem(item.item_id, {
        expected_version: item.version,
        target_status: target,
        reason: reason.trim(),
        defer_until:
          target === "deferred" ? new Date(deferUntil).toISOString() : null,
        idempotency_key: crypto.randomUUID(),
      });
      await onChanged(changed);
      setReason("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失敗");
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="action-detail" aria-labelledby="action-detail-title">
      <a
        className="action-back"
        href={`/actions${returnQuery ? `?${returnQuery}` : ""}`}
      >
        ← 返回待辦
      </a>
      <div className="action-detail-heading">
        <div>
          <p className="eyebrow">
            {item.item_type === "anomaly_review"
              ? "Anomaly review"
              : item.item_type}
          </p>
          <h2 id="action-detail-title">
            {item.company_ticker} · {item.company_name}
          </h2>
        </div>
        <span className={`action-status status-${item.status}`}>
          {statusLabels[item.status]}
        </span>
      </div>
      <p className="action-reason">{item.reason}</p>
      <dl className="action-facts">
        <div>
          <dt>優先級</dt>
          <dd>{item.effective_priority}</dd>
        </div>
        <div>
          <dt>版本</dt>
          <dd>{item.version}</dd>
        </div>
        <div>
          <dt>來源</dt>
          <dd>
            {item.source_domain} / {item.source_record_id} / v
            {item.source_version}
          </dd>
        </div>
        <div>
          <dt>政策</dt>
          <dd>{item.priority_policy_version}</dd>
        </div>
      </dl>
      <p className="priority-explanation">{item.priority_reason}</p>
      <a
        className="secondary-button context-link"
        href={`/companies/${encodeURIComponent(item.company_id)}${item.source_domain === "recommendation" ? "/recommendations" : ""}?fromAction=${encodeURIComponent(item.item_id)}&sourceDomain=${encodeURIComponent(item.source_domain)}&sourceRecord=${encodeURIComponent(item.source_record_id)}&sourceVersion=${item.source_version}&return=${encodeURIComponent(returnQuery)}`}
      >
        {item.source_domain === "recommendation"
          ? "開啟建議與人工決策"
          : "開啟公司脈絡"}
      </a>
      {item.source_domain === "recommendation" && (
        <p className="field-help">
          這裡只處理待辦。延後／略過待辦不會延後或拒絕建議；請開啟建議頁面作成正式決策。
        </p>
      )}
      {item.allowed_transitions.length > 0 && (
        <section className="action-controls" aria-label="待辦操作">
          <label>
            處理理由
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          {item.allowed_transitions.includes("deferred") && (
            <label>
              延後至
              <input
                type="datetime-local"
                value={deferUntil}
                onChange={(event) => setDeferUntil(event.target.value)}
              />
            </label>
          )}
          <div className="action-buttons">
            {item.allowed_transitions.map((target) => (
              <button
                key={target}
                type="button"
                className={
                  target === "completed" ? "primary-button" : "secondary-button"
                }
                disabled={
                  busy ||
                  !reason.trim() ||
                  (target === "deferred" && !deferUntil)
                }
                onClick={() => transition(target)}
              >
                {transitionLabels[target]}
              </button>
            ))}
          </div>
        </section>
      )}
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
    </article>
  );
}

export function ActionInboxRoutes({
  client = workflowClient,
  initialPath,
}: {
  client?: WorkflowClient;
  initialPath?: string;
}) {
  const rawPath = initialPath ?? `${location.pathname}${location.search}`;
  const path = useMemo(
    () => new URL(rawPath, "http://thesis-trace.local"),
    [rawPath],
  );
  const selectedId = path.pathname.startsWith("/actions/")
    ? decodeURIComponent(path.pathname.slice("/actions/".length))
    : null;
  const initialQuery = useMemo(() => queryFrom(path), [path]);
  const [query, setQuery] = useState<ActionInboxQuery>(initialQuery);
  const [page, setPage] = useState<ActionInboxResponse | null>(null);
  const [detail, setDetail] = useState<ActionItemResponse | null>(null);
  const [search, setSearch] = useState(initialQuery.search ?? "");
  const [error, setError] = useState("");
  const updateRoute = (next: ActionInboxQuery) => {
    if (initialPath === undefined)
      history.replaceState(null, "", `/actions?${queryString(next)}`);
  };
  const load = async (nextQuery: ActionInboxQuery) => {
    setError("");
    try {
      setPage(await client.queryInbox(nextQuery));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "無法載入待辦");
    }
  };
  useEffect(() => {
    let active = true;
    client
      .queryInbox(initialQuery)
      .then((value) => active && setPage(value))
      .catch(() => active && setError("無法載入待辦"));
    if (selectedId)
      client
        .getActionItem(selectedId)
        .then((value) => active && setDetail(value))
        .catch(() => active && setError("資源無法使用"));
    return () => {
      active = false;
    };
  }, [client, initialQuery, selectedId]);
  useEffect(() => {
    if (!page) return;
    const encoded = selectedId ? path.searchParams.get("return") : null;
    const scroll = Number(
      new URLSearchParams(encoded ?? path.search).get("scroll"),
    );
    if (Number.isFinite(scroll) && scroll > 0) scrollTo({ top: scroll });
  }, [page, path, selectedId]);
  const apply = (next: ActionInboxQuery) => {
    setQuery(next);
    updateRoute(next);
    void load(next);
  };
  const applySearch = (event: FormEvent) => {
    event.preventDefault();
    apply({ ...query, search: search.trim() || null, cursor: null });
  };
  const returnQuery = queryString(query);
  const returnContext = `${returnQuery}${returnQuery ? "&" : ""}scroll=${typeof scrollY === "number" ? scrollY : 0}`;
  const summaryFilter = (kind: "urgent" | "today" | "deferred" | "open") => {
    const today = new Date();
    const start = new Date(today);
    start.setHours(0, 0, 0, 0);
    const end = new Date(today);
    end.setHours(23, 59, 59, 999);
    apply({
      ...query,
      cursor: null,
      priority: kind === "urgent" ? "urgent" : null,
      status: kind === "deferred" ? "deferred" : null,
      open_only: kind !== "deferred" ? true : query.open_only,
      due_from: kind === "today" ? start.toISOString() : null,
      due_to: kind === "today" ? end.toISOString() : null,
    });
  };
  return (
    <main className="action-page">
      <header className="action-page-header">
        <div>
          <p className="eyebrow">Workflow</p>
          <h1>Action Inbox</h1>
          <p>由伺服器計算優先級、合法操作與一致摘要。</p>
        </div>
        <form className="action-search" role="search" onSubmit={applySearch}>
          <label htmlFor="action-search">搜尋公司或理由</label>
          <div>
            <input
              id="action-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <button className="primary-button">搜尋</button>
          </div>
        </form>
      </header>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {page && (
        <section className="action-summary" aria-label="待辦摘要">
          <button onClick={() => summaryFilter("urgent")}>
            緊急 {page.summary.urgent}
          </button>
          <button onClick={() => summaryFilter("today")}>
            今日到期 {page.summary.due_today}
          </button>
          <button onClick={() => summaryFilter("deferred")}>
            已延後 {page.summary.deferred}
          </button>
          <button onClick={() => summaryFilter("open")}>
            全部待處理 {page.summary.all_open}
          </button>
        </section>
      )}
      <section className="action-filters" aria-label="待辦篩選">
        <label>
          事項類型
          <select
            value={query.item_type ?? ""}
            onChange={(event) =>
              apply({
                ...query,
                item_type: event.target.value || null,
                cursor: null,
              })
            }
          >
            <option value="">全部</option>
            <option value="anomaly_review">Anomaly review</option>
            <option value="recommendation_decision">建議決策</option>
          </select>
        </label>
        <label>
          狀態
          <select
            value={query.status ?? ""}
            onChange={(event) =>
              apply({
                ...query,
                status: event.target.value || null,
                cursor: null,
              })
            }
          >
            <option value="">全部</option>
            {Object.entries(statusLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          優先級
          <select
            value={query.priority ?? ""}
            onChange={(event) =>
              apply({
                ...query,
                priority: event.target.value || null,
                cursor: null,
              })
            }
          >
            <option value="">全部</option>
            <option value="urgent">critical + high</option>
            <option value="critical">critical</option>
            <option value="high">high</option>
            <option value="normal">normal</option>
            <option value="low">low</option>
          </select>
        </label>
        <label>
          排序
          <select
            value={query.sort}
            onChange={(event) =>
              apply({ ...query, sort: event.target.value, cursor: null })
            }
          >
            <option value="effective_priority">優先級</option>
            <option value="due_at">到期時間</option>
            <option value="created_at">建立時間</option>
            <option value="updated_at">更新時間</option>
          </select>
        </label>
        <label>
          方向
          <select
            value={query.direction}
            onChange={(event) =>
              apply({ ...query, direction: event.target.value, cursor: null })
            }
          >
            <option value="desc">遞減</option>
            <option value="asc">遞增</option>
          </select>
        </label>
        <label className="check-field">
          <input
            type="checkbox"
            checked={query.open_only}
            onChange={(event) =>
              apply({ ...query, open_only: event.target.checked, cursor: null })
            }
          />
          僅未結項
        </label>
      </section>
      <div className={`action-master-detail${selectedId ? " has-detail" : ""}`}>
        <section className="action-list" aria-label="待辦清單">
          {!page ? (
            <p>載入中…</p>
          ) : page.items.length === 0 ? (
            <p className="empty-state">目前沒有符合條件的待辦。</p>
          ) : (
            page.items.map((item) => (
              <a
                className={`action-row${selectedId === item.item_id ? " selected" : ""}`}
                key={item.item_id}
                href={`/actions/${encodeURIComponent(item.item_id)}?return=${encodeURIComponent(returnContext)}`}
              >
                <span
                  className={`priority-dot priority-${item.effective_priority}`}
                  aria-label={`${item.effective_priority} 優先級`}
                />
                <span>
                  <strong>
                    {item.company_ticker} · {item.company_name}
                  </strong>
                  <small>
                    {item.item_type} · {item.reason}
                  </small>
                  <small>
                    {item.created_at}
                    {item.due_at ? ` · 到期 ${item.due_at}` : ""}
                  </small>
                </span>
                <span className={`action-status status-${item.status}`}>
                  {statusLabels[item.status]}
                </span>
              </a>
            ))
          )}
          {page?.next_cursor && (
            <button
              className="secondary-button load-more"
              onClick={() => apply({ ...query, cursor: page.next_cursor })}
            >
              載入下一頁
            </button>
          )}
        </section>
        {selectedId && (
          <aside className="action-detail-pane">
            {detail ? (
              <Detail
                item={detail}
                client={client}
                returnQuery={returnContext}
                onChanged={async (changed) => {
                  setDetail(changed);
                  await load(query);
                }}
              />
            ) : (
              <p>載入明細…</p>
            )}
          </aside>
        )}
      </div>
    </main>
  );
}
