import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type FormEvent,
} from "react";
import type {
  PortfolioResponse,
  ThesisResponse,
  RecommendationDetailView,
  RecommendationRequestPage,
  RecommendationRequestView,
  RecommendationDecisionBody,
  RecommendationDecisionPreview,
  RecommendationAdmissionBody,
} from "../../generated/api";
import {
  recommendationClient,
  recommendationMessage,
  type RecommendationClient,
} from "./client";
import "./recommendations.css";

function label(status: string | null): string {
  return (
    (
      {
        pending: "排隊中",
        processing: "分析中",
        retrying: "等待重試",
        succeeded: "已發布",
        failed: "分析失敗",
        accepted: "已接受",
        rejected: "已拒絕",
        deferred: "已延後",
        expired: "已過期",
        buy: "買入候選",
        hold: "維持觀察",
        abstain: "暫不建議",
      } as Record<string, string>
    )[status ?? ""] ?? "尚未決策"
  );
}
function percent(value: string | null): string {
  return value !== null && Number.isFinite(Number(value))
    ? `${(Number(value) * 100).toFixed(2)}%`
    : "不可用";
}
function dateText(value: string | null): string {
  return value ? new Date(value).toLocaleString("zh-TW") : "未提供";
}
function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
function sourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function RecommendationDialog({
  title,
  alert = false,
  children,
  onClose,
}: {
  title: string;
  alert?: boolean;
  children: ReactNode;
  onClose(): void;
}) {
  const box = useRef<HTMLElement>(null);
  useEffect(() => {
    const original = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      if (original?.isConnected) original.focus();
    };
  }, []);
  return (
    <div className="dialog-backdrop">
      <section
        ref={box}
        role={alert ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby="recommendation-dialog-title"
        className="confirmation-dialog"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
          }
          if (event.key === "Tab") {
            const items = box.current?.querySelectorAll<HTMLElement>(
              "button:not(:disabled),input:not(:disabled),a[href]",
            );
            if (!items?.length) return;
            const first = items[0],
              last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <h2 id="recommendation-dialog-title">{title}</h2>
        {children}
      </section>
    </div>
  );
}

export function RecommendationWorkspace({
  companyId,
  client = recommendationClient,
  initialPath,
}: {
  companyId: string;
  client?: RecommendationClient;
  initialPath?: string;
}) {
  const route = useMemo(
    () =>
      new URL(
        initialPath ?? `${location.pathname}${location.search}`,
        "http://thesis-trace.local",
      ),
    [initialPath],
  );
  const initialId =
    route.searchParams.get("record") ??
    (route.searchParams.get("sourceDomain") === "recommendation"
      ? route.searchParams.get("sourceRecord")
      : null);
  const initialVersion = Number(
    route.searchParams.get("version") ??
      route.searchParams.get("sourceVersion") ??
      1,
  );
  const [selection, setSelection] = useState<{
    id: string;
    version: number | null;
  } | null>(
    initialId
      ? {
          id: initialId,
          version:
            Number.isInteger(initialVersion) && initialVersion > 0
              ? initialVersion
              : null,
        }
      : null,
  );
  const [page, setPage] = useState<RecommendationRequestPage | null>(null);
  const [theses, setTheses] = useState<ThesisResponse[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [thesisId, setThesisId] = useState("");
  const [benchmark, setBenchmark] = useState("");
  const [analysisReason, setAnalysisReason] = useState("");
  const [detail, setDetail] = useState<RecommendationDetailView | null>(null);
  const [requestState, setRequestState] =
    useState<RecommendationRequestView | null>(null);
  const [reason, setReason] = useState("");
  const [deferUntil, setDeferUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState<{
    message: string;
    field?: "reason" | "analysis" | "date";
  } | null>(null);
  const [pending, setPending] = useState<{
    recordId: string;
    body: RecommendationDecisionBody;
    preview: RecommendationDecisionPreview;
  } | null>(null);
  const reasonRef = useRef<HTMLInputElement>(null),
    analysisRef = useRef<HTMLInputElement>(null),
    dateRef = useRef<HTMLInputElement>(null);
  const admissionIntent = useRef<{ digest: string; key: string } | null>(null);
  const fromAction = route.searchParams.get("fromAction");
  const returnQuery = route.searchParams.get("return");
  const returnHref = fromAction
    ? `/actions/${encodeURIComponent(fromAction)}${returnQuery ? `?return=${encodeURIComponent(returnQuery)}` : ""}`
    : undefined;
  const selectedThesis = theses.find((item) => item.thesis_id === thesisId);
  const snapshot = selectedThesis?.valuation_snapshots.at(-1);
  const showError = (error: unknown) => {
    setPending(null);
    setNotice({ message: recommendationMessage(error) });
  };
  const closeNotice = () => {
    const field = notice?.field;
    setNotice(null);
    setTimeout(() => {
      if (field === "reason") reasonRef.current?.focus();
      if (field === "analysis") analysisRef.current?.focus();
      if (field === "date") dateRef.current?.focus();
    }, 0);
  };
  const reloadInputs = async () => {
    setBusy(true);
    try {
      const [items, current, requests] = await Promise.all([
        client.theses(companyId),
        client.portfolio(),
        client.list(companyId),
      ]);
      setTheses(items);
      setPortfolio(current);
      setPage(requests);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    let active = true;
    Promise.all([
      client.theses(companyId),
      client.portfolio(),
      client.list(companyId),
    ])
      .then(([items, current, requests]) => {
        if (active) {
          setTheses(items);
          setPortfolio(current);
          setPage(requests);
        }
      })
      .catch((error) => {
        if (active) showError(error);
      });
    return () => {
      active = false;
    };
  }, [client, companyId]);
  useEffect(() => {
    let active = true;
    setPending(null);
    setDetail(null);
    setRequestState(null);
    setReason("");
    setDeferUntil("");
    if (selection) {
      (async () => {
        try {
          if (selection.version !== null) {
            const value = await client.detail(selection.id, selection.version);
            if (active) {
              if (value.company_id !== companyId)
                throw new Error("resource_unavailable");
              setDetail(value);
            }
          } else {
            const value = await client.status(selection.id);
            if (active) setRequestState(value);
          }
        } catch (error) {
          if (active) showError(error);
        }
      })();
    }
    return () => {
      active = false;
    };
  }, [client, companyId, selection?.id, selection?.version]);
  const select = (id: string, version: number | null) => {
    setPending(null);
    setSelection({ id, version });
    if (initialPath === undefined) {
      const query = new URLSearchParams(route.search);
      query.set("record", id);
      query.set("version", String(version ?? 0));
      history.replaceState(
        null,
        "",
        `/companies/${encodeURIComponent(companyId)}/recommendations?${query}`,
      );
    }
  };
  const refreshSelection = async () => {
    if (!selection) return;
    setBusy(true);
    setPending(null);
    try {
      if (selection.version === null) {
        const state = await client.status(selection.id);
        setRequestState(state);
        if (state.result_version !== null)
          select(state.request_id, state.result_version);
      } else {
        const value = await client.detail(selection.id, selection.version);
        if (value.company_id !== companyId)
          throw new Error("resource_unavailable");
        setDetail(value);
      }
      setPage(await client.list(companyId));
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (
      !selectedThesis ||
      !portfolio ||
      !snapshot ||
      typeof snapshot.valuation_id !== "string" ||
      typeof snapshot.version !== "number"
    ) {
      setNotice({
        message:
          "請選擇已啟用且具有已發布估值的 Thesis，並先設定投資組合的成本與現金。",
        field: "analysis",
      });
      return;
    }
    if (!benchmark || !analysisReason.trim()) {
      setNotice({
        message: "請重新確認估值比較來源，並填寫來源選擇與分析理由。",
        field: "analysis",
      });
      return;
    }
    const intent = {
      thesis_id: selectedThesis.thesis_id,
      expected_thesis_version: selectedThesis.version,
      valuation_id: snapshot.valuation_id,
      expected_valuation_version: snapshot.version,
      expected_portfolio_version: portfolio.version,
      benchmark_source:
        benchmark as RecommendationAdmissionBody["benchmark_source"],
      source_selection_reason: analysisReason.trim(),
    };
    const digest = JSON.stringify(intent);
    if (admissionIntent.current?.digest !== digest)
      admissionIntent.current = { digest, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const value = await client.request(companyId, {
        ...intent,
        idempotency_key: admissionIntent.current.key,
      });
      admissionIntent.current = null;
      setMessage("分析請求已建立。請使用重新整理查看 worker 處理結果。");
      setRequestState(value);
      select(value.request_id, value.result_version);
      try {
        setPage(await client.list(companyId));
      } catch {
        setNotice({
          message:
            "分析請求已建立，但無法重新整理清單。請重新整理，不需要重送請求。",
        });
      }
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const completeDecision = async (
    recordId: string,
    body: RecommendationDecisionBody,
    token?: string | null,
  ) => {
    setBusy(true);
    try {
      const view = await client.decide(recordId, {
        ...body,
        challenge_token: token ?? null,
      });
      setPending(null);
      setDetail((current) => (current ? { ...current, view } : null));
      setReason("");
      setMessage(
        view.decision_status === "expired"
          ? "資料已失效，伺服器已記錄過期，未接受這份建議。"
          : "決策已保存，不會自動建立交易。若需再次延後，請填寫新的決策理由。",
      );
      try {
        const latest = await client.detail(recordId, body.version);
        setDetail((current) =>
          (latest.view.decision_sequence ?? 0) >= (view.decision_sequence ?? 0)
            ? latest
            : current,
        );
        setPage(await client.list(companyId));
      } catch {
        setNotice({
          message:
            "決策已保存，但無法重新整理最新明細。請重新整理，不需要重送決策。",
        });
      }
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const startDecision = async (
    target: RecommendationDecisionBody["target_status"],
  ) => {
    if (!detail) return;
    if (!reason.trim()) {
      setNotice({
        message: recommendationMessage("missing_reason"),
        field: "reason",
      });
      return;
    }
    if (
      target === "deferred" &&
      (!deferUntil ||
        !Number.isFinite(new Date(deferUntil).getTime()) ||
        new Date(deferUntil).getTime() <= Date.now())
    ) {
      setNotice({
        message: recommendationMessage("invalid_defer_time"),
        field: "date",
      });
      return;
    }
    const body: RecommendationDecisionBody = {
      version: detail.view.version,
      expected_sequence: detail.view.decision_sequence ?? 0,
      target_status: target,
      reason: reason.trim(),
      defer_until:
        target === "deferred" ? new Date(deferUntil).toISOString() : null,
      idempotency_key: crypto.randomUUID(),
    };
    if (target === "deferred") {
      await completeDecision(detail.view.record_id, body);
      return;
    }
    setBusy(true);
    try {
      const preview = await client.preview(detail.view.record_id, body);
      if (!preview.challenge_token) {
        setDetail({ ...detail, view: preview.view });
        setNotice({
          message:
            preview.view.reason_codes.map(recommendationMessage).join(" ") ||
            "目前建議不能執行這項決策，請重新整理。",
        });
        return;
      }
      setPending({ recordId: detail.view.record_id, body, preview });
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const loadOlder = async () => {
    if (!detail?.next_decision_sequence) return;
    setBusy(true);
    try {
      const older = await client.detail(
        detail.view.record_id,
        detail.view.version,
        detail.next_decision_sequence,
      );
      setDetail((current) =>
        current
          ? {
              ...current,
              decisions: [...older.decisions, ...current.decisions],
              next_decision_sequence: older.next_decision_sequence,
            }
          : null,
      );
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="action-page recommendation-page">
      <header className="action-page-header">
        <div>
          <p className="eyebrow">Recommendation · Owner Decision</p>
          <h1>建議與決策</h1>
          <p>AI 提出有引用的候選；最終規模、報酬門檻與有效性由伺服器判定。</p>
        </div>
        <div className="recommendation-links">
          <a
            className="secondary-button"
            href={`/companies/${encodeURIComponent(companyId)}/theses`}
          >
            Thesis／估值
          </a>
          {returnHref && (
            <a className="secondary-button" href={returnHref}>
              返回原待辦
            </a>
          )}
        </div>
      </header>
      {message && (
        <p className="priority-explanation" role="status">
          {message}
        </p>
      )}
      <section className="panel recommendation-panel">
        <h2>建立分析請求</h2>
        <form onSubmit={submit} noValidate className="recommendation-form">
          <label>
            研究 Thesis
            <select
              value={thesisId}
              onChange={(event) => {
                setThesisId(event.target.value);
                setBenchmark("");
              }}
            >
              <option value="">請選擇已啟用的 Thesis</option>
              {theses
                .filter((item) => item.status === "active")
                .map((item) => (
                  <option key={item.thesis_id} value={item.thesis_id}>
                    {item.title}
                  </option>
                ))}
            </select>
          </label>
          <label>
            重新確認估值比較來源
            <select
              value={benchmark}
              onChange={(event) => setBenchmark(event.target.value)}
            >
              <option value="">請明確選擇</option>
              <option value="company_history">公司歷史</option>
              <option value="peer_group">同儕比較</option>
              <option value="abstain">資料不足／暫不估值</option>
            </select>
          </label>
          <p className="field-help">
            需與已發布估值的來源一致；切換來源前，請先重新發布估值。
            {selectedThesis &&
              ` Thesis v${selectedThesis.version}；估值 v${snapshot?.version ?? "未發布"}；`}
            投資組合 v{portfolio?.version ?? "載入中"}。
          </p>
          <label className="recommendation-full">
            來源選擇與分析理由
            <input
              ref={analysisRef}
              value={analysisReason}
              onChange={(event) => setAnalysisReason(event.target.value)}
            />
          </label>
          <div className="recommendation-links recommendation-full">
            <button className="primary-button" disabled={busy} type="submit">
              建立分析請求
            </button>
            <button
              className="secondary-button"
              disabled={busy}
              type="button"
              onClick={() => void reloadInputs()}
            >
              重新整理輸入與請求
            </button>
          </div>
        </form>
      </section>
      <div className="recommendation-layout">
        <section
          className="panel recommendation-panel"
          aria-label="分析請求清單"
        >
          <h2>分析請求</h2>
          {page === null ? (
            <p>載入中…</p>
          ) : page.items.length === 0 ? (
            <p>尚無分析請求。</p>
          ) : (
            page.items.map((item) => (
              <button
                className={`recommendation-request${selection?.id === item.request_id ? " selected" : ""}`}
                key={item.request_id}
                disabled={busy || pending !== null}
                onClick={() => select(item.request_id, item.result_version)}
              >
                <strong>
                  {theses.find((value) => value.thesis_id === item.thesis_id)
                    ?.title ?? "研究分析"}
                </strong>
                <span>{label(item.status)}</span>
                <small>{dateText(item.submitted_at)}</small>
              </button>
            ))
          )}
          {page?.next_cursor && (
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                client
                  .list(companyId, page.next_cursor!)
                  .then(setPage)
                  .catch(showError)
                  .finally(() => setBusy(false));
              }}
            >
              下一頁請求
            </button>
          )}
        </section>
        <section
          className="panel recommendation-panel recommendation-detail"
          aria-label="建議明細"
        >
          {selection && (
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => void refreshSelection()}
            >
              重新整理建議狀態
            </button>
          )}
          {!selection ? (
            <p>選擇一筆請求以檢視結果與決策歷史。</p>
          ) : !detail ? (
            <div>
              <h2>{requestState ? label(requestState.status) : "載入建議…"}</h2>
              {requestState?.error_code ? (
                <p role="alert">
                  {recommendationMessage(requestState.error_code)}
                </p>
              ) : (
                <p>
                  尚未取得已發布建議。分析由獨立 worker
                  處理，重新整理不會建立新請求。
                </p>
              )}
            </div>
          ) : (
            <>
              <div className="panel-heading">
                <h2>{detail.thesis_title}</h2>
                <span className="stage-badge">
                  {label(detail.view.decision_status)}
                </span>
              </div>
              <p>
                {label(detail.direction)} · 建議 v{detail.view.version} ·
                決策序號 {detail.view.decision_sequence ?? 0}
              </p>
              <dl className="recommendation-facts">
                <div>
                  <dt>AI 規模上限</dt>
                  <dd>{detail.raw_ceiling} 倍</dd>
                </div>
                <div>
                  <dt>伺服器最終規模</dt>
                  <dd>{detail.final_multiplier} 倍</dd>
                </div>
                <div>
                  <dt>最終規模年化淨報酬</dt>
                  <dd>{percent(detail.annualized_return)}</dd>
                </div>
                <div>
                  <dt>最低門檻</dt>
                  <dd>{percent(detail.minimum_return)}</dd>
                </div>
              </dl>
              <p>
                來源：
                {detail.benchmark_source === "company_history"
                  ? "公司歷史"
                  : detail.benchmark_source === "peer_group"
                    ? "同儕比較"
                    : "暫不估值"}{" "}
                · {detail.source_selection_reason}
              </p>
              <p className="field-help">
                發布：{dateText(detail.published_at)}；有效性查核：
                {dateText(detail.checked_at)}。確認時會再次查核，不會自動交易。
              </p>
              {detail.view.reason_codes.map((code, index) => (
                <p className="priority-explanation" key={`${code}-${index}`}>
                  {recommendationMessage(code)}
                </p>
              ))}
              {detail.view.input_validity !== "valid" && (
                <button
                  className="secondary-button"
                  onClick={() => {
                    setThesisId(detail.thesis_id);
                    setBenchmark("");
                    analysisRef.current?.focus();
                  }}
                >
                  重新建立分析請求
                </button>
              )}
              {detail.publication_reasons.map((code, index) => (
                <p
                  className="priority-explanation"
                  key={`publication-${index}`}
                >
                  {recommendationMessage(code)}
                </p>
              ))}
              <h3>主張與引用</h3>
              {detail.claims.map((claim, index) => (
                <div key={index} className="recommendation-claim">
                  <p>{claim.text}</p>
                  <small>引用：{claim.citations.join("、")}</small>
                </div>
              ))}
              <h3>保存的來源快照</h3>
              {detail.sources.map((source) => (
                <article
                  className="recommendation-source"
                  key={source.snapshot_id}
                >
                  <strong>
                    {source.publisher} · {source.category ?? "分類未提供"}
                  </strong>
                  <p>{source.excerpt}</p>
                  <p className="field-help">
                    發布 {dateText(source.published_at)} · 取得{" "}
                    {dateText(source.retrieved_at)} · Lineage{" "}
                    {source.lineage ?? "未提供"}
                  </p>
                  <a
                    href={sourceUrl(source.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    開啟原始來源
                  </a>
                  <small>Snapshot {source.snapshot_id}</small>
                </article>
              ))}
              <h3>全投資組合風險快照</h3>
              <p className="field-help">
                所有分桶合併計算；試算後比例不是已成交持倉。快照{" "}
                {detail.portfolio_snapshot_id ?? "不可用"}
              </p>
              <div className="recommendation-table">
                <table>
                  <thead>
                    <tr>
                      <th>維度／標的</th>
                      <th>目前比例</th>
                      <th>試算後比例</th>
                      <th>上限</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.risk.map((row) => (
                      <tr key={`${row.dimension}-${row.subject}`}>
                        <th>
                          {row.dimension}／{row.subject}
                        </th>
                        <td>{percent(row.current_ratio)}</td>
                        <td>{percent(row.projected_ratio)}</td>
                        <td>{percent(row.limit_ratio)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>估值、成本與運算稽核</summary>
                <dl className="recommendation-audit">
                  {detail.facts.map((fact, index) => (
                    <div key={`${fact.label}-${index}`}>
                      <dt>{fact.label}</dt>
                      <dd>{fact.value}</dd>
                    </div>
                  ))}
                </dl>
              </details>
              {detail.view.allowed_actions.length > 0 && (
                <section className="action-controls" aria-label="Owner 決策">
                  <h3>人工決策</h3>
                  <label>
                    決策理由
                    <input
                      ref={reasonRef}
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                    />
                  </label>
                  <p className="field-help">
                    每次決策需填寫獨立理由。接受／拒絕會先顯示確認視窗。
                  </p>
                  <label>
                    延後至
                    <input
                      ref={dateRef}
                      type="datetime-local"
                      value={deferUntil}
                      onChange={(event) => setDeferUntil(event.target.value)}
                    />
                  </label>
                  <div className="recommendation-links">
                    {detail.view.allowed_actions.includes("accept") && (
                      <button
                        className="primary-button"
                        disabled={busy}
                        onClick={() => void startDecision("accepted")}
                      >
                        接受建議
                      </button>
                    )}
                    {detail.view.allowed_actions.includes("reject") && (
                      <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() => void startDecision("rejected")}
                      >
                        拒絕建議
                      </button>
                    )}
                    {detail.view.allowed_actions.includes("defer") && (
                      <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() => void startDecision("deferred")}
                      >
                        延後決策
                      </button>
                    )}
                  </div>
                </section>
              )}
              <h3>決策歷史</h3>
              {detail.decisions.length === 0 ? (
                <p>尚無決策紀錄。</p>
              ) : (
                detail.decisions.map((item) => (
                  <article
                    className="recommendation-source"
                    key={item.sequence}
                  >
                    <strong>
                      #{item.sequence} {label(item.status)}
                    </strong>
                    <p>{item.reason}</p>
                    <small>
                      {dateText(item.recorded_at)}
                      {item.defer_until
                        ? ` · 延後至 ${dateText(item.defer_until)}`
                        : ""}
                    </small>
                    {item.checks.length > 0 && (
                      <details>
                        <summary>當時核對的版本與確認紀錄</summary>
                        <dl className="recommendation-audit">
                          {item.checks.map((check) => (
                            <div key={check.label}>
                              <dt>{check.label}</dt>
                              <dd>{check.value}</dd>
                            </div>
                          ))}
                        </dl>
                        <p>
                          確認紀錄：{item.confirmation_id ?? "未使用確認權杖"}
                        </p>
                      </details>
                    )}
                  </article>
                ))
              )}
              {detail.next_decision_sequence && (
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => void loadOlder()}
                >
                  載入較早決策
                </button>
              )}
            </>
          )}
        </section>
      </div>
      {notice && (
        <RecommendationDialog title="操作提示" alert onClose={closeNotice}>
          <p>{notice.message}</p>
          <div className="dialog-actions">
            <button className="primary-button" onClick={closeNotice}>
              {notice.field ? "返回填寫" : "了解"}
            </button>
          </div>
        </RecommendationDialog>
      )}
      {pending && (
        <RecommendationDialog
          title="確認建議決策"
          onClose={() => {
            if (!busy) setPending(null);
          }}
        >
          {pending.preview.impact_summary.split("\n").map((line, index) => (
            <p key={index}>{line}</p>
          ))}
          <p>
            建議 v{pending.body.version} · 決策序號{" "}
            {pending.body.expected_sequence}
          </p>
          <p>理由：{pending.body.reason}</p>
          <p className="field-help">
            確認有效至 {dateText(pending.preview.expires_at)}
            ；逾時需重新預覽，並不代表建議已過期。
          </p>
          <div className="dialog-actions">
            <button disabled={busy} onClick={() => setPending(null)}>
              取消
            </button>
            <button
              className="primary-button"
              disabled={busy}
              onClick={() =>
                void completeDecision(
                  pending.recordId,
                  pending.body,
                  pending.preview.challenge_token,
                )
              }
            >
              確認決策
            </button>
          </div>
        </RecommendationDialog>
      )}
    </main>
  );
}
