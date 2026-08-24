import { FormEvent, useEffect, useState } from "react";
import { ApiError, evidenceClient, type AnomalyAssessmentResponse, type CompanyResponse, type DimensionFactsBody, type EvidenceClient, type EvidenceIntake, type EvidenceStageResponse, type EvidenceStatus } from "./api/evidenceClient";
import type { ActionItemResponse } from "./generated/api";
import { workflowClient, type WorkflowClient } from "./workflow/client";
import "./styles.css";

const statuses: Record<EvidenceStatus, [string, string]> = {
  received: ["已接收", "要求已安全保存，等待採集工作開始。"], processing: ["處理中", "採集器正在取得並驗證來源。"],
  retrying: ["等待重試", "來源暫時無法取得，系統會依政策重試。"], succeeded: ["已完成", "來源快照與 provenance 已由伺服器保存。"],
  failed: ["處理失敗", "這次採集無法完成。"], dead_letter: ["需要處理", "自動重試已結束，請交由管理者檢查。"],
};
const messageFor = (error: unknown) => error instanceof ApiError ? error.message : "目前無法連線至伺服器，請確認網路後重試。";
const anomalyLabel = (assessment: AnomalyAssessmentResponse) => {
  if (assessment.status === "pending") return "等待分析";
  if (assessment.status === "superseded") return "已由新版取代";
  if (assessment.status === "failed") return "評估失敗";
  return assessment.trace?.anomaly_class === "would_be_hard" ? "Shadow Hard 候選" : "Soft anomaly";
};

export default function App({ client = evidenceClient, workflow = workflowClient, canConfirmStage = true, canRequestAnomaly = true, canCreateActions = true }: { client?: EvidenceClient; workflow?: WorkflowClient; canConfirmStage?: boolean; canRequestAnomaly?: boolean; canCreateActions?: boolean }) {
  const [companies, setCompanies] = useState<CompanyResponse[]>([]); const [companyId, setCompanyId] = useState("");
  const [createMode, setCreateMode] = useState(false); const [ticker, setTicker] = useState(""); const [companyName, setCompanyName] = useState(""); const [url, setUrl] = useState("");
  const [intake, setIntake] = useState<EvidenceIntake | null>(null); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<EvidenceStageResponse | null>(null); const [stageBusy, setStageBusy] = useState(false);
  const [sourceConfirmation, setSourceConfirmation] = useState<DimensionFactsBody["source_confirmation"]>("unverified");
  const [productEstablished, setProductEstablished] = useState(false); const [commercializationEstablished, setCommercializationEstablished] = useState(false);
  const [identifiableRevenue, setIdentifiableRevenue] = useState(false); const [identifiableProfitOrCashFlow, setIdentifiableProfitOrCashFlow] = useState(false);
  const [consecutiveFinancialQuarters, setConsecutiveFinancialQuarters] = useState(0); const [stageReason, setStageReason] = useState("");
  const [anomaly, setAnomaly] = useState<AnomalyAssessmentResponse | null>(null); const [anomalyBusy, setAnomalyBusy] = useState(false);
  const [anomalyReason, setAnomalyReason] = useState("");
  const [createdAction, setCreatedAction] = useState<ActionItemResponse | null>(null); const [actionBusy, setActionBusy] = useState(false);
  useEffect(() => { let active = true; client.listCompanies().then((items) => { if (active) { setCompanies(items); setCompanyId(items[0]?.company_id ?? ""); } }).catch((reason) => active && setError(messageFor(reason))).finally(() => active && setLoading(false)); return () => { active = false; }; }, [client]);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); setBusy(true); try {
    let company = companies.find((item) => item.company_id === companyId);
    if (createMode) { company = await client.createCompany({ ticker: ticker.trim(), name: companyName.trim() }); setCompanies((items) => [...items, company!]); setCompanyId(company.company_id); }
    if (!company) throw new ApiError("company_required", "請先選擇或建立公司。", 422);
    setStage(null); setAnomaly(null); setIntake(await client.submitEvidenceUrl({ company, submittedUrl: url }));
  } catch (reason) { setError(messageFor(reason)); } finally { setBusy(false); } };
  const refresh = async () => { if (!intake) return; setBusy(true); setError(null); try {
    const statusResult = await client.getEvidenceIntake(intake.evidence_id); setIntake({ ...intake, ...statusResult });
    if (statusResult.status === "succeeded" && statusResult.source_snapshot_id) {
      try { setStage(await client.getEvidenceStage(intake.evidence_id)); } catch (reason) { if (!(reason instanceof ApiError) || reason.status !== 404) throw reason; }
    }
  } catch (reason) { setError(messageFor(reason)); } finally { setBusy(false); } };
  const confirmStage = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!intake?.source_snapshot_id) return; setStageBusy(true); setError(null); try {
    setStage(await client.confirmEvidenceStage(intake.evidence_id, {
      expected_version: stage?.version ?? 0,
      facts: { source_confirmation: sourceConfirmation, product_established: productEstablished, commercialization_established: commercializationEstablished, identifiable_revenue: identifiableRevenue, identifiable_profit_or_cash_flow: identifiableProfitOrCashFlow, consecutive_financial_quarters: consecutiveFinancialQuarters },
      idempotency_key: crypto.randomUUID(), reason: stageReason.trim(), source_snapshot_id: intake.source_snapshot_id,
    }));
  } catch (reason) { setError(messageFor(reason)); } finally { setStageBusy(false); } };
  const requestAnomaly = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!intake?.source_snapshot_id) return; setAnomalyBusy(true); setError(null); try {
    setAnomaly(await client.requestAnomalyAssessment(intake.evidence_id, {
      expected_evidence_version: intake.version,
      idempotency_key: crypto.randomUUID(), reason: anomalyReason.trim(),
      sources: [{ source_snapshot_id: intake.source_snapshot_id }],
    }));
  } catch (reason) { setError(messageFor(reason)); } finally { setAnomalyBusy(false); } };
  const refreshAnomaly = async () => { if (!anomaly) return; setAnomalyBusy(true); setError(null); try { setAnomaly(await client.getAnomalyAssessment(anomaly.assessment_id)); } catch (reason) { setError(messageFor(reason)); } finally { setAnomalyBusy(false); } };
  const createReviewAction = async () => { if (!anomaly) return; setActionBusy(true); setError(null); try { setCreatedAction(await workflow.createAnomalyReview({ assessment_id: anomaly.assessment_id, expected_assessment_version: anomaly.version, reason: "追蹤並人工審查此 anomaly", due_at: null, idempotency_key: crypto.randomUUID() })); } catch (reason) { setError(reason instanceof Error ? reason.message : "無法建立待辦"); } finally { setActionBusy(false); } };
  const status = intake ? statuses[intake.status] : null; const failed = intake?.status === "failed" || intake?.status === "dead_letter";
  return <div className="app-shell"><header className="topbar"><a className="brand" href="/" aria-label="ThesisTrace 首頁"><span className="brand-mark" aria-hidden="true">T</span><span>ThesisTrace</span></a><span className="environment">研究工作台</span></header><main className="workspace"><section className="intro" aria-labelledby="page-title"><p className="eyebrow">Company workspace</p><h1 id="page-title">新增 Evidence</h1><p>提交公開來源網址。伺服器會保存接收紀錄，再由獨立採集器處理來源。</p></section><div className="workspace-grid">
    <section className="panel" aria-labelledby="intake-title"><div className="panel-heading"><div><p className="step">步驟 1</p><h2 id="intake-title">選擇公司與來源</h2></div><button className="text-button" type="button" onClick={() => setCreateMode((value) => !value)}>{createMode ? "選擇現有公司" : "建立新公司"}</button></div><form onSubmit={submit}>
      {createMode ? <div className="field-row"><label>股票代號<input required value={ticker} onChange={(e) => setTicker(e.target.value)} /></label><label>公司名稱<input required value={companyName} onChange={(e) => setCompanyName(e.target.value)} /></label></div> : <label>公司<select required disabled={loading || !companies.length} value={companyId} onChange={(e) => setCompanyId(e.target.value)}>{!companies.length && <option value="">尚無公司</option>}{companies.map((company) => <option key={company.company_id} value={company.company_id}>{company.ticker} · {company.name}</option>)}</select></label>}
      <div className="field"><label htmlFor="evidence-url">Evidence URL</label><input id="evidence-url" required type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} /><span className="field-help">請使用公開可查證的 HTTPS 來源。</span></div>{error && <div className="error-banner" role="alert">{error}</div>}<button className="primary-button" disabled={loading || busy} type="submit">{busy ? "提交中…" : createMode ? "建立公司並提交 Evidence" : "提交 Evidence"}</button>
    </form></section>
    <section className="panel status-panel" aria-labelledby="status-title"><div className="panel-heading"><div><p className="step">步驟 2</p><h2 id="status-title">採集狀態</h2></div>{intake && <button className="secondary-button" type="button" onClick={refresh} disabled={busy}>重新整理狀態</button>}</div>{!intake || !status ? <div className="empty-state"><span aria-hidden="true">↗</span><p>提交後會在這裡顯示伺服器處理狀態。</p></div> : <div className={`status-card status-${intake.status}`} role={failed ? "alert" : "status"}><div className="status-heading"><span className="status-dot" aria-hidden="true" /><strong>{status[0]}</strong><span className="version">版本 {intake.version}</span></div><p>{status[1]}</p><dl><div><dt>公司</dt><dd>{intake.company.name}</dd></div><div><dt>紀錄 ID</dt><dd>{intake.evidence_id}</dd></div><div><dt>來源</dt><dd className="url-value">{intake.submittedUrl}</dd></div></dl></div>}</section>
    {intake?.status === "succeeded" && intake.source_snapshot_id && <section className="panel stage-panel" aria-labelledby="stage-title"><div className="panel-heading"><div><p className="step">步驟 3</p><h2 id="stage-title">確認 Evidence 階段事實</h2></div>{stage && <span className="stage-badge" aria-label="伺服器推導階段">{stage.stage}</span>}</div><p className="stage-guidance">Owner 確認可查證事實；E-stage 一律由伺服器按順序規則推導。</p><div className={`stage-layout${canConfirmStage ? "" : " stage-readonly"}`}>{canConfirmStage && <form className="stage-form" onSubmit={confirmStage}>
      <label>來源確認<select value={sourceConfirmation} onChange={(event) => setSourceConfirmation(event.target.value as DimensionFactsBody["source_confirmation"])}><option value="unverified">尚未確認</option><option value="official">官方來源</option></select></label>
      <fieldset><legend>已確認事實</legend><label className="check-field"><input type="checkbox" checked={productEstablished} onChange={(event) => setProductEstablished(event.target.checked)} />已建立產品</label><label className="check-field"><input type="checkbox" checked={commercializationEstablished} onChange={(event) => setCommercializationEstablished(event.target.checked)} />已建立商業化</label><label className="check-field"><input type="checkbox" checked={identifiableRevenue} onChange={(event) => setIdentifiableRevenue(event.target.checked)} />已有可識別營收</label><label className="check-field"><input type="checkbox" checked={identifiableProfitOrCashFlow} onChange={(event) => setIdentifiableProfitOrCashFlow(event.target.checked)} />已有可識別獲利或現金流</label></fieldset>
      <label>連續財務季度數<input type="number" min="0" step="1" value={consecutiveFinancialQuarters} onChange={(event) => setConsecutiveFinancialQuarters(event.target.valueAsNumber || 0)} /></label><label>確認理由<input required value={stageReason} onChange={(event) => setStageReason(event.target.value)} /></label><button className="primary-button" disabled={stageBusy} type="submit">{stageBusy ? "儲存中…" : "確認事實並儲存階段"}</button>
    </form>}{stage ? <section className="stage-result" aria-live="polite"><p className="stage-label">Server E-stage</p><strong className="stage-value">{stage.stage}</strong><p>由伺服器依 {stage.policy_version} 推導</p><p className="stage-meta">版本 {stage.version} · Snapshot {stage.source_snapshot_id}</p><ol className="gate-trace">{stage.gate_trace.map((gate) => <li key={gate.gate} className={gate.passed ? "gate-pass" : "gate-stop"}><span>{gate.gate}</span><span>{gate.passed ? "通過" : "停止"}</span><code>{gate.code}</code></li>)}</ol></section> : <div className="stage-result stage-placeholder"><p>{canConfirmStage ? "送出確認後，這裡才會顯示伺服器推導的階段與完整 gate trace。" : "尚無已確認的伺服器 E-stage。"}</p></div>}</div></section>}
    {intake?.status === "succeeded" && intake.source_snapshot_id && <section className="panel anomaly-panel" aria-labelledby="anomaly-title"><div className="panel-heading"><div><p className="step">步驟 4</p><h2 id="anomaly-title">Shadow anomaly 評估</h2></div>{anomaly && <span className={`anomaly-badge anomaly-${anomaly.status}`}>{anomalyLabel(anomaly)}</span>}</div><p className="stage-guidance">來源分類與 lineage 取自伺服器保存的不可變 snapshot；AI 只提出候選並由 critic 檢查。正式 Hard 通知仍停用。</p><div className={`stage-layout${canRequestAnomaly ? "" : " stage-readonly"}`}>{canRequestAnomaly && <form className="anomaly-form" onSubmit={requestAnomaly}><p>將使用目前 Evidence 的伺服器來源分類、發布者、lineage、摘錄與時間資料。</p><label>評估理由<input required value={anomalyReason} onChange={(event) => setAnomalyReason(event.target.value)} /></label><button className="primary-button" disabled={anomalyBusy} type="submit">{anomalyBusy ? "建立中…" : "開始 Shadow anomaly 評估"}</button></form>}{anomaly ? <section className="stage-result anomaly-result" aria-live="polite"><p className="stage-label">Server anomaly result</p><strong className="anomaly-value">{anomaly.status === "pending" ? "等待獨立 AI worker" : anomalyLabel(anomaly)}</strong><p className="stage-meta">版本 {anomaly.version} · Evidence {anomaly.evidence_version}</p>{anomaly.trace && <><p>政策 {anomaly.trace.policy_version} · 來源 {anomaly.trace.source_tiers.join(" + ")}</p><ol className="gate-trace">{anomaly.trace.gates.map((gate) => <li key={gate.gate} className={gate.passed ? "gate-pass" : "gate-stop"}><span>{gate.gate}</span><span>{gate.passed ? "通過" : "停止"}</span><code>{gate.code}</code></li>)}</ol></>}{canCreateActions && anomaly.status === "succeeded" && anomaly.trace && (anomaly.trace.anomaly_class === "would_be_hard" || anomaly.trace.clue_route === "human_review") && (createdAction ? <a className="primary-button action-created-link" href={`/actions/${createdAction.item_id}`}>開啟已建立待辦</a> : <button className="primary-button" type="button" onClick={createReviewAction} disabled={actionBusy}>{actionBusy ? "建立待辦中…" : "建立審查待辦"}</button>)}<button className="secondary-button" type="button" onClick={refreshAnomaly} disabled={anomalyBusy}>重新整理評估</button></section> : <div className="stage-result stage-placeholder"><p>{canRequestAnomaly ? "送出後會先顯示 pending，再呈現伺服器保存的 Soft／would-be-Hard trace。" : "尚無可讀取的 anomaly 評估。"}</p></div>}</div></section>}
  </div></main></div>;
}
