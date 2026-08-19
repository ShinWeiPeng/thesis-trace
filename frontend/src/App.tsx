import { FormEvent, useEffect, useState } from "react";
import { ApiError, evidenceClient, type CompanyResponse, type EvidenceClient, type EvidenceIntake, type EvidenceStatus } from "./api/evidenceClient";
import "./styles.css";

const statuses: Record<EvidenceStatus, [string, string]> = {
  received: ["已接收", "要求已安全保存，等待採集工作開始。"], processing: ["處理中", "採集器正在取得並驗證來源。"],
  retrying: ["等待重試", "來源暫時無法取得，系統會依政策重試。"], succeeded: ["已完成", "來源快照與 provenance 已由伺服器保存。"],
  failed: ["處理失敗", "這次採集無法完成。"], dead_letter: ["需要處理", "自動重試已結束，請交由管理者檢查。"],
};
const messageFor = (error: unknown) => error instanceof ApiError ? error.message : "目前無法連線至伺服器，請確認網路後重試。";

export default function App({ client = evidenceClient }: { client?: EvidenceClient }) {
  const [companies, setCompanies] = useState<CompanyResponse[]>([]); const [companyId, setCompanyId] = useState("");
  const [createMode, setCreateMode] = useState(false); const [ticker, setTicker] = useState(""); const [companyName, setCompanyName] = useState(""); const [url, setUrl] = useState("");
  const [intake, setIntake] = useState<EvidenceIntake | null>(null); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  useEffect(() => { let active = true; client.listCompanies().then((items) => { if (active) { setCompanies(items); setCompanyId(items[0]?.company_id ?? ""); } }).catch((reason) => active && setError(messageFor(reason))).finally(() => active && setLoading(false)); return () => { active = false; }; }, [client]);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); setBusy(true); try {
    let company = companies.find((item) => item.company_id === companyId);
    if (createMode) { company = await client.createCompany({ ticker: ticker.trim(), name: companyName.trim() }); setCompanies((items) => [...items, company!]); setCompanyId(company.company_id); }
    if (!company) throw new ApiError("company_required", "請先選擇或建立公司。", 422);
    setIntake(await client.submitEvidenceUrl({ company, submittedUrl: url }));
  } catch (reason) { setError(messageFor(reason)); } finally { setBusy(false); } };
  const refresh = async () => { if (!intake) return; setBusy(true); setError(null); try { setIntake({ ...intake, ...await client.getEvidenceIntake(intake.evidence_id) }); } catch (reason) { setError(messageFor(reason)); } finally { setBusy(false); } };
  const status = intake ? statuses[intake.status] : null; const failed = intake?.status === "failed" || intake?.status === "dead_letter";
  return <div className="app-shell"><header className="topbar"><a className="brand" href="/" aria-label="ThesisTrace 首頁"><span className="brand-mark" aria-hidden="true">T</span><span>ThesisTrace</span></a><span className="environment">研究工作台</span></header><main className="workspace"><section className="intro" aria-labelledby="page-title"><p className="eyebrow">Company workspace</p><h1 id="page-title">新增 Evidence</h1><p>提交公開來源網址。伺服器會保存接收紀錄，再由獨立採集器處理來源。</p></section><div className="workspace-grid">
    <section className="panel" aria-labelledby="intake-title"><div className="panel-heading"><div><p className="step">步驟 1</p><h2 id="intake-title">選擇公司與來源</h2></div><button className="text-button" type="button" onClick={() => setCreateMode((value) => !value)}>{createMode ? "選擇現有公司" : "建立新公司"}</button></div><form onSubmit={submit}>
      {createMode ? <div className="field-row"><label>股票代號<input required value={ticker} onChange={(e) => setTicker(e.target.value)} /></label><label>公司名稱<input required value={companyName} onChange={(e) => setCompanyName(e.target.value)} /></label></div> : <label>公司<select required disabled={loading || !companies.length} value={companyId} onChange={(e) => setCompanyId(e.target.value)}>{!companies.length && <option value="">尚無公司</option>}{companies.map((company) => <option key={company.company_id} value={company.company_id}>{company.ticker} · {company.name}</option>)}</select></label>}
      <div className="field"><label htmlFor="evidence-url">Evidence URL</label><input id="evidence-url" required type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} /><span className="field-help">請使用公開可查證的 HTTPS 來源。</span></div>{error && <div className="error-banner" role="alert">{error}</div>}<button className="primary-button" disabled={loading || busy} type="submit">{busy ? "提交中…" : createMode ? "建立公司並提交 Evidence" : "提交 Evidence"}</button>
    </form></section>
    <section className="panel status-panel" aria-labelledby="status-title"><div className="panel-heading"><div><p className="step">步驟 2</p><h2 id="status-title">採集狀態</h2></div>{intake && <button className="secondary-button" type="button" onClick={refresh} disabled={busy}>重新整理狀態</button>}</div>{!intake || !status ? <div className="empty-state"><span aria-hidden="true">↗</span><p>提交後會在這裡顯示伺服器處理狀態。</p></div> : <div className={`status-card status-${intake.status}`} role={failed ? "alert" : "status"}><div className="status-heading"><span className="status-dot" aria-hidden="true" /><strong>{status[0]}</strong><span className="version">版本 {intake.version}</span></div><p>{status[1]}</p><dl><div><dt>公司</dt><dd>{intake.company.name}</dd></div><div><dt>紀錄 ID</dt><dd>{intake.evidence_id}</dd></div><div><dt>來源</dt><dd className="url-value">{intake.submittedUrl}</dd></div></dl></div>}</section>
  </div></main></div>;
}
