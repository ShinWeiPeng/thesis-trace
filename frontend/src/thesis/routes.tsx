import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { thesisClient, type ThesisClient, type ThesisResponse, type ThesisTransitionPreviewResponse } from "./client";
import type { ValuationPublicationPreviewResponse } from "../generated/api";

const statusLabel: Record<ThesisResponse["status"], string> = {
  draft: "草稿", active: "進行中", paused: "已暫停", invalidated: "已失效", closed: "已關閉",
};

const transitionTargets: Record<ThesisResponse["status"], ThesisResponse["status"][]> = {
  draft: ["active", "invalidated"],
  active: ["paused", "invalidated", "closed"],
  paused: ["active", "invalidated", "closed"],
  invalidated: ["active", "closed"],
  closed: ["active"],
};

function conditionSummary(value: Record<string, unknown>): string {
  return typeof value.summary === "string" ? value.summary : "未命名失效條件";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textValue(value: unknown, fallback = "—"): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function percentageValue(value: unknown): string {
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat("zh-TW", { style: "percent", maximumFractionDigits: 2 }).format(numeric)
    : "—";
}

function valuationErrorMessage(caught: unknown, fallback: string): string {
  const message = caught instanceof Error ? caught.message : fallback;
  if (message === "cost_profile_version_conflict") {
    return "成本設定已更新。請填寫草稿儲存理由，重新儲存並計算估值草稿，再預覽發布。";
  }
  if (message === "forecast_target_date_mismatch") {
    return "估值基準日與 Forecast 目標日期不一致。請調整基準日或估值期間後，重新儲存並計算。";
  }
  if (message === "forecast_expired") {
    return "Forecast 已失效。請更新 Evidence 後重新儲存並計算估值草稿，再預覽發布。";
  }
  if (message === "research_version_conflict") {
    return "Evidence 已更新。請重新載入頁面，確認來源後再儲存估值草稿。";
  }
  if (["challenge_invalid", "valuation_draft_conflict", "valuation_source_invalid", "version_conflict"].includes(message)) {
    return "發布條件已改變或確認已逾期。這次沒有發布；請重新載入資料並重新預覽。";
  }
  if (/^[a-z0-9_]+$/.test(message)) return `${fallback}。請重新載入資料後再試一次。`;
  return message;
}

function coverageLabel(value: unknown): string {
  if (value === "limited_history") return "有限歷史（36–59 個月）";
  if (value === "standard_history") return "標準歷史";
  return "未提供涵蓋狀態";
}

function exclusionLabel(value: unknown): string {
  const [subject, code] = textValue(value).split(":", 2);
  const labels: Record<string, string> = {
    duplicate_sample: "重複樣本", duplicate_month: "重複月份", wrong_company: "公司不符",
    invalid_source: "來源無效", invalid_multiple: "倍數無效", nonpositive_denominator: "分母非正值",
    duplicate_peer: "重複同業", target_company: "包含目標公司", missing_inclusion_reason: "缺少納入理由",
    method_mismatch: "估值方法不一致", not_taiwan_listed: "非台灣上市櫃", unconfirmed_peer: "同業未確認",
  };
  return code ? `${subject}：${labels[code] ?? "未納入"}` : textValue(value);
}

function BenchmarkSummary({ title, benchmark }: { title: string; benchmark: Record<string, unknown> }) {
  const distribution = recordValue(benchmark.distribution);
  const samples = arrayValue(benchmark.valid_samples).map(recordValue);
  const sourceGroups = new Map<string, number>();
  samples.forEach((sample) => {
    const source = recordValue(sample.source);
    const key = `${textValue(source.record_id)} v${textValue(source.version)}`;
    sourceGroups.set(key, (sourceGroups.get(key) ?? 0) + 1);
  });
  const exclusions = arrayValue(benchmark.exclusions);
  const sortedSamples = arrayValue(distribution.sorted_samples).map((value) => textValue(value));
  return <article className="valuation-benchmark">
    <div className="valuation-benchmark-heading"><h4>{title}</h4><span>{coverageLabel(distribution.coverage)}</span></div>
    <dl><div><dt>中位數</dt><dd>{textValue(distribution.median)}</dd></div><div><dt>P75</dt><dd>{textValue(distribution.p75)}</dd></div><div><dt>有效樣本</dt><dd>{textValue(distribution.sample_count)} 筆</dd></div><div><dt>資料期間</dt><dd>{textValue(benchmark.data_start)} 至 {textValue(benchmark.data_end)}</dd></div></dl>
    <p className="valuation-source">來源：{sourceGroups.size ? [...sourceGroups].map(([key, count]) => `Evidence ${key}（${count} 個 fact）`).join("、") : "未提供"}</p>
    <p className="valuation-percentile">P75 位於第 {textValue(distribution.p75_position)} 個位置；排序樣本第 {textValue(distribution.p75_lower_index)} 至 {textValue(distribution.p75_upper_index)} 筆，內插比例 {percentageValue(distribution.p75_interpolation_fraction)}。</p>
    <p className={exclusions.length ? "valuation-exclusions" : "valuation-no-exclusions"}>排除：{exclusions.length ? exclusions.map(exclusionLabel).join("、") : "無"}</p>
    <details className="valuation-samples"><summary>查看排序樣本</summary><p>{sortedSamples.length ? sortedSamples.join("、") : "未提供"}</p></details>
  </article>;
}

function ValuationImpactSummary({ summary }: { summary: Record<string, unknown> }) {
  const before = recordValue(summary.before); const after = recordValue(summary.after);
  const consequences = arrayValue(summary.consequences);
  return <section className="valuation-impact" aria-label="發布影響摘要">
    <h4>{textValue(summary.action_label, "發布估值")}</h4>
    <p className="valuation-impact-subject">目標 Thesis：{textValue(summary.subject)}</p>
    <div className="valuation-impact-change"><span>發布前</span><strong>Thesis v{textValue(before.thesis_version)} · 草稿 v{textValue(before.draft_version)}</strong><span>發布後</span><strong>{after.outcome === "abstain" ? "不產生目標價" : `NT$ ${textValue(after.target_price)}`}</strong></div>
    <ul>{consequences.length ? consequences.map((value, index) => <li key={index}>{textValue(value)}</li>) : <li>將保存不可變估值快照。</li>}</ul>
  </section>;
}

function ThesisImpactSummary({ summary }: { summary: unknown }) {
  const value = recordValue(summary); const before = recordValue(value.before); const after = recordValue(value.after);
  const consequences = Array.isArray(value.consequences) ? value.consequences : [];
  return <section aria-label="狀態變更影響摘要"><p>目標 Thesis：{textValue(value.subject)}</p><dl><div><dt>變更前</dt><dd>{Object.entries(before).map(([key, item]) => `${key}: ${textValue(item)}`).join("、") || "—"}</dd></div><div><dt>變更後</dt><dd>{Object.entries(after).map(([key, item]) => `${key}: ${textValue(item)}`).join("、") || "—"}</dd></div></dl><ul>{consequences.map((item, index) => <li key={index}>{textValue(item)}</li>)}</ul></section>;
}

function ValuationDraftSummary({ draft, snapshotCount }: { draft: Record<string, unknown>; snapshotCount: number }) {
  const result = recordValue(draft.result); const validity = recordValue(draft.validity);
  const distribution = recordValue(draft.distribution);
  const method = textValue(draft.method).toUpperCase();
  const source = draft.benchmark_source === "company_history" ? "自身歷史" : draft.benchmark_source === "peer_group" ? "同業群組" : "不估值";
  const variant = draft.benchmark_variant === "median" ? "中位數" : draft.benchmark_variant === "p75" ? "P75" : "—";
  const targetPrice = result.target_price;
  return <section className="valuation-result" aria-labelledby="valuation-result-title">
    <div className="valuation-result-heading"><div><p className="eyebrow">Draft v{textValue(draft.version)}</p><h3 id="valuation-result-title">目前估值草稿</h3></div><span className="valuation-snapshot-count">已發布 {snapshotCount} 份</span></div>
    <div className="valuation-key-metrics">
      <article><span>目標價</span><strong>{targetPrice == null ? "不估值" : `NT$ ${textValue(targetPrice)}`}</strong></article>
      <article><span>年化淨報酬</span><strong>{percentageValue(result.annualized_return)}</strong></article>
      <article><span>採用基準</span><strong>{method} · {source} {variant}</strong></article>
    </div>
    <div className="valuation-comparison" aria-label="估值基準比較"><BenchmarkSummary title="自身歷史" benchmark={recordValue(draft.company_history)} /><BenchmarkSummary title="同業群組" benchmark={recordValue(draft.peer_group)} /></div>
    <dl className="valuation-validity"><div><dt>有效樣本</dt><dd>{textValue(distribution.sample_count)} 筆 · {coverageLabel(distribution.coverage)}</dd></div><div><dt>目標日期</dt><dd>{textValue(validity.target_date)}</dd></div><div><dt>有效期限</dt><dd>{textValue(validity.expires_at)}</dd></div><div><dt>成本版本</dt><dd>Cost Profile v{textValue(draft.cost_profile_version)}</dd></div></dl>
    <p className="valuation-tax-note">已扣除交易成本與證交稅；未計個人綜合所得稅及補充保費。</p>
    <details className="valuation-trace"><summary>查看計算依據</summary><p>{textValue(draft.source_selection_reason, "未提供來源選擇理由")}</p><p>兩組 P75 差異：{textValue(draft.benchmark_difference_p75)}</p></details>
  </section>;
}

function Detail({ item, client, onChanged, companyId, view }: { item: ThesisResponse; client: ThesisClient; onChanged(value: ThesisResponse): void; companyId: string; view: "overview" | "valuation" | "outcomes" }) {
  const [lifecycleReason, setLifecycleReason] = useState(""); const [outcomeReason, setOutcomeReason] = useState("");
  const [reflectionReason, setReflectionReason] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [valuationError, setValuationError] = useState("");
  const [missingReason, setMissingReason] = useState<"狀態變更" | "Outcome 儲存" | "Reflection 完成" | null>(null);
  const lifecycleReasonRef = useRef<HTMLInputElement>(null); const outcomeReasonRef = useRef<HTMLInputElement>(null);
  const reflectionReasonRef = useRef<HTMLInputElement>(null);
  const missingReasonActionRef = useRef<HTMLButtonElement>(null);
  const valuationPreviewRef = useRef<HTMLButtonElement>(null); const valuationReasonRef = useRef<HTMLInputElement>(null);
  const valuationCancelRef = useRef<HTMLButtonElement>(null); const valuationPublishRef = useRef<HTMLButtonElement>(null);
  const [pending, setPending] = useState<ThesisTransitionPreviewResponse | null>(null);
  const [outcome, setOutcome] = useState(""); const [observedAt, setObservedAt] = useState("");
  const [original, setOriginal] = useState(""); const [errors, setErrors] = useState("");
  const [missing, setMissing] = useState(""); const [improvement, setImprovement] = useState("");
  type ReflectionField = "original_assumption" | "judgment_errors" | "missing_evidence" | "improvement";
  const [dirtyFields, setDirtyFields] = useState<ReflectionField[]>([]);
  const [draftConflict, setDraftConflict] = useState(false);
  const [autosaveFailure, setAutosaveFailure] = useState<"offline" | "network" | null>(null);
  const [autosaveInFlight, setAutosaveInFlight] = useState(false);
  const [autosave, setAutosave] = useState("");
  const [valuationMethod, setValuationMethod] = useState<"pe" | "pb" | "abstain">("pe"); const [benchmarkSource, setBenchmarkSource] = useState<"company_history" | "peer_group" | "abstain">("company_history"); const [benchmarkVariant, setBenchmarkVariant] = useState<"median" | "p75">("p75");
  const [historySourceId, setHistorySourceId] = useState("10000000-0000-0000-0000-000000000001"); const [historySourceVersion, setHistorySourceVersion] = useState("3"); const [historySamples, setHistorySamples] = useState(Array.from({ length: 36 }, (_, index) => `pe-history-${index + 1}`).join("\n")); const [peerRows, setPeerRows] = useState(["2301,相近電子營收驅動,10000000-0000-0000-0000-000000000002,3,pe-peer", "2302,相近電子營收驅動,10000000-0000-0000-0000-000000000003,3,pe-peer", "2303,相近半導體商業模式,10000000-0000-0000-0000-000000000004,3,pe-peer", "2304,相近電子景氣循環,10000000-0000-0000-0000-000000000005,3,pe-peer", "2305,相近硬體營收驅動,10000000-0000-0000-0000-000000000006,3,pe-peer"].join("\n")); const [sourceReason, setSourceReason] = useState("採用已保存且可重現的來源樣本"); const [horizon, setHorizon] = useState<6 | 12 | 24>(12); const [basisDate, setBasisDate] = useState(new Date().toISOString().slice(0, 10)); const [valuationQuantity, setValuationQuantity] = useState("10"); const [buyPrice, setBuyPrice] = useState("100"); const [cashDividend, setCashDividend] = useState("0"); const [valuationReason, setValuationReason] = useState(""); const [publicationReason, setPublicationReason] = useState(""); const [valuationPending, setValuationPending] = useState<ValuationPublicationPreviewResponse | null>(null);
  const draftValues = useMemo(() => ({ original_assumption: original, judgment_errors: errors, missing_evidence: missing, improvement }), [original, errors, missing, improvement]);
  const draftValuesRef = useRef(draftValues);
  draftValuesRef.current = draftValues;

  useEffect(() => {
    if (valuationMethod === "abstain") return;
    setHistorySamples((value) => value.replace(/^(pe|pb)-history-/gm, `${valuationMethod}-history-`));
    setPeerRows((value) => value.replace(/,(pe|pb)-peer$/gm, `,${valuationMethod}-peer`));
  }, [valuationMethod]);

  useEffect(() => { if (missingReason) missingReasonActionRef.current?.focus(); }, [missingReason]);
  useEffect(() => { if (valuationPending) valuationReasonRef.current?.focus(); }, [valuationPending]);

  useEffect(() => {
    if (draftConflict || dirtyFields.length) return;
    const draft = recordValue(item.reflection_draft);
    const completed = recordValue(item.reflection);
    setOriginal(textValue(draft.original_assumption ?? completed.original_assumption, ""));
    setErrors(textValue(draft.judgment_errors ?? completed.judgment_errors, ""));
    setMissing(textValue(draft.missing_evidence ?? completed.missing_evidence, ""));
    setImprovement(textValue(draft.improvement ?? completed.improvement, ""));
  }, [draftConflict, dirtyFields.length, item.reflection, item.reflection_draft, item.thesis_id]);

  useEffect(() => {
    if (!dirtyFields.length || draftConflict || autosaveFailure || autosaveInFlight) return;
    setAutosave("等待自動儲存…");
    const timer = setTimeout(async () => {
      if (!navigator.onLine) {
        setAutosave("離線：草稿尚未送出，恢復連線後請手動重試");
        setAutosaveFailure("offline");
        return;
      }
      setAutosave("儲存中…");
      setAutosaveInFlight(true);
      const valuesAtSend = { ...draftValues };
      try {
        let revision = Number((item.reflection_draft as { revision?: number } | null)?.revision ?? 0);
        let changed = item;
        const fields = [...dirtyFields];
        for (const field of fields) {
          changed = await client.autosaveReflection(item.thesis_id, {
            expected_draft_version: revision, field, text: valuesAtSend[field],
            idempotency_key: crypto.randomUUID(),
          });
          revision = Number((changed.reflection_draft as { revision?: number } | null)?.revision ?? revision + 1);
        }
        const newerEditExists = fields.some(
          (field) => draftValuesRef.current[field] !== valuesAtSend[field],
        );
        setDirtyFields((current) => current.filter(
          (field) => !fields.includes(field) || draftValuesRef.current[field] !== valuesAtSend[field],
        ));
        onChanged(changed);
        const savedAt = (changed.reflection_draft as { saved_at?: string } | null)?.saved_at;
        setAutosave(newerEditExists
          ? "較早版本已儲存；目前編輯仍待儲存…"
          : `已由伺服器儲存草稿${savedAt ? ` · ${new Date(savedAt).toLocaleString("zh-TW")}` : ""}`);
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : "自動儲存失敗";
        if (/version_conflict|draft_version/i.test(message)) {
          setAutosave("草稿版本衝突，需要選擇如何處理"); setDraftConflict(true); setError(message);
          try { onChanged(await client.get(item.thesis_id)); } catch { /* keep the last safe server projection */ }
        } else {
          setAutosave("草稿儲存失敗；內容仍保留在本機，請手動重試");
          setAutosaveFailure("network"); setError("無法連線到伺服器，草稿尚未送出");
        }
      } finally { setAutosaveInFlight(false); }
    }, 2000);
    return () => clearTimeout(timer);
  }, [autosaveFailure, autosaveInFlight, client, dirtyFields, draftConflict, draftValues, item, onChanged]);

  useEffect(() => {
    if (!dirtyFields.length && !draftConflict) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyFields.length, draftConflict]);

  const transition = async (target: ThesisResponse["status"], challengeToken?: string) => {
    if (!lifecycleReason.trim()) { setMissingReason("狀態變更"); return; }
    setBusy(true); setError("");
    try {
      if (!challengeToken) {
        const preview = await client.previewTransition(item.thesis_id, { expected_version: item.version, target_status: target });
        if (preview.requires_confirmation) { setPending(preview); return; }
      }
      const changed = await client.transition(item.thesis_id, {
        expected_version: item.version, target_status: target, reason: lifecycleReason.trim(),
        idempotency_key: crypto.randomUUID(), challenge_token: challengeToken,
      });
      setPending(null); setLifecycleReason(""); onChanged(changed);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "狀態變更失敗"); }
    finally { setBusy(false); }
  };
  const saveOutcome = async (event: FormEvent) => { event.preventDefault(); if (!outcomeReason.trim()) { setMissingReason("Outcome 儲存"); return; } setBusy(true); setError(""); try {
    const changed = await client.saveOutcome(item.thesis_id, { expected_version: item.version, observed_at: new Date(observedAt).toISOString(), result: outcome.trim(), evidence_refs: [], reason: outcomeReason.trim(), idempotency_key: crypto.randomUUID() });
    setOutcomeReason(""); onChanged(changed);
  } catch (caught) { setError(caught instanceof Error ? caught.message : "Outcome 儲存失敗"); } finally { setBusy(false); } };
  const complete = async (event: FormEvent) => { event.preventDefault(); if (!reflectionReason.trim()) { setMissingReason("Reflection 完成"); return; } setBusy(true); setError(""); try {
    const changed = await client.completeReflection(item.thesis_id, { expected_version: item.version, original_assumption: original.trim(), judgment_errors: errors.trim(), missing_evidence: missing.trim(), improvement: improvement.trim(), reason: reflectionReason.trim(), idempotency_key: crypto.randomUUID() });
    setReflectionReason(""); onChanged(changed);
  } catch (caught) { setError(caught instanceof Error ? caught.message : "Reflection 儲存失敗"); } finally { setBusy(false); } };
  const saveValuation = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); setValuationError(""); try {
    const draft = item.valuation_draft as { version?: number } | null;
    const history = valuationMethod === "abstain" ? [] : historySamples.split("\n").filter(Boolean).map((line) => ({ source: { record_id: historySourceId.trim(), version: Number(historySourceVersion), fact_id: line.trim() } }));
    const peers = valuationMethod === "abstain" ? [] : peerRows.split("\n").filter(Boolean).map((line) => { const [company_id, inclusion_reason, record_id, version, fact_id] = line.split(",").map((value) => value.trim()); return { company_id, inclusion_reason, source: { record_id, version: Number(version), fact_id } }; });
    const changed = await client.saveValuation(item.thesis_id, { expected_thesis_version: item.version, expected_draft_version: Number(draft?.version ?? 0), method: valuationMethod, benchmark_source: valuationMethod === "abstain" ? "abstain" : benchmarkSource, benchmark_variant: benchmarkVariant, company_history_samples: history, peer_members: peers, source_selection_reason: sourceReason.trim(), basis_date: basisDate, horizon_months: horizon, forecast_source: valuationMethod === "abstain" ? null : { record_id: historySourceId.trim(), version: Number(historySourceVersion), fact_id: `${valuationMethod}-forecast` }, quantity: valuationMethod === "abstain" ? null : valuationQuantity, buy_price: valuationMethod === "abstain" ? null : buyPrice, cash_dividend: valuationMethod === "abstain" ? null : cashDividend, reason: valuationReason.trim(), idempotency_key: crypto.randomUUID() });
    setValuationReason(""); onChanged(changed);
  } catch (caught) { setValuationError(valuationErrorMessage(caught, "估值草稿儲存失敗")); } finally { setBusy(false); } };
  const previewValuation = async () => { const draft = item.valuation_draft as { version?: number } | null; if (!draft?.version) return; setBusy(true); setError(""); setValuationError(""); try { setValuationPending(await client.previewValuationPublication(item.thesis_id, { expected_thesis_version: item.version, expected_draft_version: draft.version })); } catch (caught) { setValuationError(valuationErrorMessage(caught, "估值發布預覽失敗")); } finally { setBusy(false); } };
  const closeValuationDialog = () => { setValuationPending(null); setPublicationReason(""); valuationPreviewRef.current?.focus(); };
  const publishValuation = async () => { if (!valuationPending || !publicationReason.trim()) return; setBusy(true); setError(""); setValuationError(""); try { const changed = await client.publishValuation(item.thesis_id, { expected_thesis_version: valuationPending.target_version, expected_draft_version: valuationPending.draft_version, challenge_token: valuationPending.challenge_token, reason: publicationReason.trim(), idempotency_key: crypto.randomUUID() }); closeValuationDialog(); onChanged(changed); } catch (caught) { const message = valuationErrorMessage(caught, "估值發布失敗，請重新預覽"); closeValuationDialog(); setValuationError(message); } finally { setBusy(false); } };
  const handleValuationDialogKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") { event.preventDefault(); closeValuationDialog(); return; }
    if (event.key !== "Tab") return;
    if (event.shiftKey && document.activeElement === valuationReasonRef.current) { event.preventDefault(); (publicationReason.trim() ? valuationPublishRef.current : valuationCancelRef.current)?.focus(); }
    if (!event.shiftKey && (document.activeElement === valuationPublishRef.current || (!publicationReason.trim() && document.activeElement === valuationCancelRef.current))) { event.preventDefault(); valuationReasonRef.current?.focus(); }
  };
  const closeMissingReason = () => {
    if (missingReason === "狀態變更") lifecycleReasonRef.current?.focus();
    if (missingReason === "Outcome 儲存") outcomeReasonRef.current?.focus();
    if (missingReason === "Reflection 完成") reflectionReasonRef.current?.focus();
    setMissingReason(null);
  };
  const handleMissingReasonKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") { event.preventDefault(); closeMissingReason(); return; }
    if (event.key === "Tab") { event.preventDefault(); missingReasonActionRef.current?.focus(); }
  };
  const draft = (field: ReflectionField, update: (value: string) => void) => (value: string) => { update(value); setDirtyFields((current) => current.includes(field) ? current : [...current, field]); };
  const retryAutosave = () => { setError(""); setAutosaveFailure(null); setAutosave("等待重新儲存…"); };
  const loadServerDraft = async () => {
    const fresh = await client.get(item.thesis_id);
    const server = recordValue(fresh.reflection_draft);
    setOriginal(textValue(server.original_assumption, "")); setErrors(textValue(server.judgment_errors, ""));
    setMissing(textValue(server.missing_evidence, "")); setImprovement(textValue(server.improvement, ""));
    setDirtyFields([]); setDraftConflict(false); setAutosaveFailure(null); setError(""); setAutosave("已重新載入伺服器草稿"); onChanged(fresh);
  };
  const keepLocalDraft = () => { setDraftConflict(false); setError(""); setDirtyFields(["original_assumption", "judgment_errors", "missing_evidence", "improvement"]); setAutosave("保留本機內容，等待重新儲存…"); };
  return <article className="thesis-detail">
    <div className="thesis-detail-heading"><div><p className="eyebrow">Cycle {item.cycle} · v{item.version}</p><h2>{item.title}</h2></div><span className={`thesis-status status-${item.status}`}>{statusLabel[item.status]}</span></div>
    <nav className="thesis-detail-tabs" aria-label="Thesis 詳情">
      <a aria-current={view === "overview" ? "page" : undefined} href={`/companies/${encodeURIComponent(companyId)}/theses/${encodeURIComponent(item.thesis_id)}`}>Overview</a>
      <a aria-current={view === "valuation" ? "page" : undefined} href={`/companies/${encodeURIComponent(companyId)}/theses/${encodeURIComponent(item.thesis_id)}/valuation`}>Valuation</a>
      <a aria-current={view === "outcomes" ? "page" : undefined} href={`/companies/${encodeURIComponent(companyId)}/theses/${encodeURIComponent(item.thesis_id)}/outcomes`}>Outcomes / Reflections</a>
    </nav>
    {view === "overview" && <><p className="thesis-narrative">{item.narrative}</p><section><h3>預先定義的失效條件</h3><ul>{item.conditions.map((condition, index) => <li key={index}>{conditionSummary(condition)}</li>)}</ul></section></>}
    {view === "outcomes" && item.reflection_pending && <p className="warning-banner">此 Thesis 已失效，Outcome 與 Reflection 尚未完成。</p>}
    {view === "valuation" && <form className="thesis-learning valuation-form" onSubmit={saveValuation}><h3>估值</h3><p className="field-help">方法、來源選擇與預測由 Owner 明確確認；數值與事件日期由 Server 依 Evidence fact ID 解析，瀏覽器不能提交倍數、分母或預測值。</p><div className="field-row"><label>方法<select value={valuationMethod} onChange={(e) => setValuationMethod(e.target.value as "pe"|"pb"|"abstain")}><option value="pe">PE</option><option value="pb">PB</option><option value="abstain">Abstain（不估值）</option></select></label>{valuationMethod !== "abstain" && <label>基準來源<select value={benchmarkSource} onChange={(e) => setBenchmarkSource(e.target.value as "company_history"|"peer_group")}><option value="company_history">自身歷史</option><option value="peer_group">同業群組</option></select></label>}<label>候選<select value={benchmarkVariant} onChange={(e) => setBenchmarkVariant(e.target.value as "median"|"p75")}><option value="median">中位數</option><option value="p75">P75</option></select></label><label>期間<select value={horizon} onChange={(e) => setHorizon(Number(e.target.value) as 6|12|24)}><option value="6">6 個月</option><option value="12">12 個月</option><option value="24">24 個月</option></select></label><label>基準日<input type="date" required value={basisDate} onChange={(e) => setBasisDate(e.target.value)} /></label>{valuationMethod !== "abstain" && <><label>試算股數<input required value={valuationQuantity} onChange={(e) => setValuationQuantity(e.target.value)} /></label><label>買進價格<input required value={buyPrice} onChange={(e) => setBuyPrice(e.target.value)} /></label><label>現金股利<input required value={cashDividend} onChange={(e) => setCashDividend(e.target.value)} /></label></>}</div>{valuationMethod !== "abstain" && <><div className="field-row"><label>歷史／Forecast Evidence ID<input required value={historySourceId} onChange={(e) => setHistorySourceId(e.target.value)} /></label><label>Evidence 版本<input required type="number" min="1" value={historySourceVersion} onChange={(e) => setHistorySourceVersion(e.target.value)} /></label></div><label>自身歷史 fact ID（每行一筆）<textarea required value={historySamples} onChange={(e) => setHistorySamples(e.target.value)} /></label><label>Peer（每行：公司ID,納入理由,Evidence ID,版本,fact ID）<textarea value={peerRows} onChange={(e) => setPeerRows(e.target.value)} /></label></>}<label>來源選擇理由<input required value={sourceReason} onChange={(e) => setSourceReason(e.target.value)} /></label><label>草稿儲存理由<input required value={valuationReason} onChange={(e) => setValuationReason(e.target.value)} /></label><div className="action-buttons"><button className="primary-button" disabled={busy}>儲存並由伺服器計算</button>{item.valuation_draft && <button ref={valuationPreviewRef} className="secondary-button" type="button" disabled={busy} onClick={() => void previewValuation()}>預覽發布</button>}</div></form>}
    {valuationError && <p className="error-banner valuation-recovery" role="alert">{valuationError}</p>}
    {item.valuation_draft && view !== "outcomes" && <ValuationDraftSummary draft={item.valuation_draft} snapshotCount={item.valuation_snapshots.length} />}
    {view === "overview" && <section className="thesis-lifecycle"><h3>生命週期操作</h3><label>狀態變更理由<input ref={lifecycleReasonRef} value={lifecycleReason} onChange={(event) => setLifecycleReason(event.target.value)} /></label><p className="field-help">理由會寫入稽核紀錄；每次狀態變更都必須重新填寫。</p><div className="action-buttons">{transitionTargets[item.status].map((target) => <button className={target === "invalidated" || target === "closed" ? "danger-button" : "secondary-button"} disabled={busy} key={target} onClick={() => void transition(target)}>{statusLabel[target]}</button>)}</div></section>}
    {view === "outcomes" && (item.status === "invalidated" || item.status === "paused" || item.status === "active") && <form className="thesis-learning" onSubmit={saveOutcome}><h3>Outcome</h3><label>觀察時間<input required type="datetime-local" value={observedAt} onChange={(event) => setObservedAt(event.target.value)} /></label><label>後續結果<textarea required value={outcome} onChange={(event) => setOutcome(event.target.value)} /></label><label>Outcome 儲存理由<input ref={outcomeReasonRef} value={outcomeReason} onChange={(event) => setOutcomeReason(event.target.value)} /></label><p className="field-help">這是本次 Outcome 的稽核理由，不會沿用其他操作的理由。</p><button className="primary-button" disabled={busy}>儲存 Outcome</button></form>}
    {view === "outcomes" && <form className="thesis-learning" onSubmit={complete}><h3>Reflection</h3><p className="field-help">停止輸入兩秒後會依序保存所有已修改欄位的完整草稿；「完成 Reflection」才會完成學習紀錄。</p><label>原始假設<textarea required value={original} onChange={(event) => draft("original_assumption", setOriginal)(event.target.value)} /></label><label>判斷錯誤<textarea required value={errors} onChange={(event) => draft("judgment_errors", setErrors)(event.target.value)} /></label><label>遺漏證據<textarea required value={missing} onChange={(event) => draft("missing_evidence", setMissing)(event.target.value)} /></label><label>下次改進<textarea required value={improvement} onChange={(event) => draft("improvement", setImprovement)(event.target.value)} /></label><p aria-live="polite">{autosave}</p>{autosaveFailure && <button className="secondary-button" type="button" onClick={retryAutosave}>重新嘗試儲存草稿</button>}<label>Reflection 完成理由<input ref={reflectionReasonRef} value={reflectionReason} onChange={(event) => setReflectionReason(event.target.value)} /></label><p className="field-help">這是完成學習紀錄的稽核理由，不會沿用狀態變更理由。</p><button className="primary-button" disabled={busy}>完成 Reflection</button></form>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {pending && <div className="dialog-backdrop" role="presentation"><section className="confirmation-dialog" role="dialog" aria-modal="true"><h3>確認 Thesis 狀態變更</h3><p>{pending.from_status} → {pending.to_status} · 目標版本 v{pending.target_version}</p><ThesisImpactSummary summary={pending.impact_summary} /><div className="dialog-actions"><button onClick={() => setPending(null)}>取消</button><button className="danger-button" onClick={() => void transition(pending.to_status, pending.challenge_token ?? undefined)}>{textValue(recordValue(pending.impact_summary).confirmation_verb, "確認變更")}</button></div></section></div>}
    {valuationPending && <div className="dialog-backdrop" role="presentation"><section className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="valuation-publication-title" onKeyDown={handleValuationDialogKeyDown}><h3 id="valuation-publication-title">發布不可變估值快照</h3><ValuationImpactSummary summary={valuationPending.impact_summary} /><p className="field-help">確認有效至 {valuationPending.challenge_expires_at}；逾期或資料變更時不會發布。</p><label>發布理由<input ref={valuationReasonRef} value={publicationReason} onChange={(e) => setPublicationReason(e.target.value)} /></label><div className="dialog-actions"><button ref={valuationCancelRef} onClick={closeValuationDialog}>取消</button><button ref={valuationPublishRef} className="danger-button" disabled={!publicationReason.trim()} onClick={() => void publishValuation()}>{textValue(recordValue(valuationPending.impact_summary).confirmation_verb, "發布估值")}</button></div></section></div>}
    {missingReason && <div className="dialog-backdrop" role="presentation"><section className="confirmation-dialog" role="alertdialog" aria-modal="true" aria-labelledby="missing-reason-title" aria-describedby="missing-reason-description" onKeyDown={handleMissingReasonKeyDown}><h3 id="missing-reason-title">尚未填寫 {missingReason}理由</h3><p id="missing-reason-description">此理由會寫入稽核紀錄，請返回目前操作區塊填寫後再送出。</p><div className="dialog-actions"><button ref={missingReasonActionRef} className="primary-button" onClick={closeMissingReason}>返回填寫</button></div></section></div>}
    {draftConflict && <div className="dialog-backdrop" role="presentation"><section className="confirmation-dialog" role="alertdialog" aria-modal="true" aria-labelledby="draft-conflict-title"><h3 id="draft-conflict-title">Reflection 草稿版本衝突</h3><p>伺服器草稿已有較新的版本。請比較後選擇保留版本；系統不會自動覆蓋。</p><div className="draft-comparison"><section><h4>本機內容</h4><p>{original}／{errors}／{missing}／{improvement}</p></section><section><h4>上次載入的伺服器內容</h4><p>{textValue(recordValue(item.reflection_draft).original_assumption)}／{textValue(recordValue(item.reflection_draft).judgment_errors)}／{textValue(recordValue(item.reflection_draft).missing_evidence)}／{textValue(recordValue(item.reflection_draft).improvement)}</p></section></div><div className="dialog-actions"><button onClick={() => void loadServerDraft()}>重新取得伺服器草稿</button><button className="primary-button" onClick={keepLocalDraft}>保留本機內容並重試</button></div></section></div>}
  </article>;
}

export function ThesisRoutes({ client = thesisClient, companyId, initialPath }: { client?: ThesisClient; companyId: string; initialPath?: string }) {
  const rawPath = initialPath ?? `${location.pathname}${location.search}`;
  const view = useMemo(() => {
    const value = new URL(rawPath, "http://thesis-trace.local").pathname.split("/")[5];
    return value === "valuation" || value === "outcomes" ? value : "overview";
  }, [rawPath]);
  const selectedId = useMemo(() => {
    const parts = new URL(rawPath, "http://thesis-trace.local").pathname.split("/");
    return parts[3] === "theses" && parts[4] ? decodeURIComponent(parts[4]) : null;
  }, [rawPath]);
  const [company, setCompany] = useState<{ company_id: string; ticker: string; name: string; version: number } | null>(null);
  const [items, setItems] = useState<ThesisResponse[]>([]); const [selected, setSelected] = useState<ThesisResponse | null>(null);
  const [creating, setCreating] = useState(false); const [title, setTitle] = useState(""); const [narrative, setNarrative] = useState("");
  const [condition, setCondition] = useState(""); const [reason, setReason] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useEffect(() => { let active = true; Promise.all([client.listCompanies(), client.list(companyId)]).then(([companies, theses]) => {
    if (!active) return; setCompany(companies.find((value) => value.company_id === companyId) ?? null); setItems(theses);
    if (selectedId) client.get(selectedId).then((value) => active && setSelected(value)).catch(() => active && setError("資源無法使用"));
  }).catch(() => active && setError("資源無法使用")); return () => { active = false; }; }, [client, companyId, selectedId]);
  const changed = (value: ThesisResponse) => { setSelected(value); setItems((current) => current.map((item) => item.thesis_id === value.thesis_id ? value : item)); };
  const create = async (event: FormEvent) => { event.preventDefault(); if (!company) return; setBusy(true); setError(""); try {
    const value = await client.create(companyId, { company_version: company.version, title: title.trim(), narrative: narrative.trim(), invalidation_conditions: [condition.trim()], evidence_refs: [], reason: reason.trim(), idempotency_key: crypto.randomUUID() });
    setItems((current) => [...current, value]); setCreating(false); setTitle(""); setNarrative(""); setCondition(""); setReason("");
  } catch (caught) { setError(caught instanceof Error ? caught.message : "建立失敗"); } finally { setBusy(false); } };
  return <main className="thesis-page"><header className="company-header"><div><p className="eyebrow">Company workspace · Theses</p><h1>{company ? `${company.ticker} · ${company.name}` : "Thesis"}</h1></div><nav aria-label="公司工作區"><a href={`/companies/${encodeURIComponent(companyId)}`}>Evidence</a><a aria-current="page" href={`/companies/${encodeURIComponent(companyId)}/theses`}>Theses</a><a href={`/companies/${encodeURIComponent(companyId)}/trades`}>Trades</a></nav></header>
    {error && <p className="error-banner" role="alert">{error}</p>}
    <section className="thesis-toolbar"><div><h2>個人 Thesis</h2><p>每個 Thesis 都有獨立假設、失效條件與生命週期。</p></div><button className="primary-button" onClick={() => setCreating((value) => !value)}>建立 Thesis</button></section>
    {creating && <form className="panel thesis-create" onSubmit={create}><label>Thesis 標題<input required value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>研究假設<textarea required value={narrative} onChange={(event) => setNarrative(event.target.value)} /></label><label>失效條件<textarea required value={condition} onChange={(event) => setCondition(event.target.value)} /></label><label>建立理由<input required value={reason} onChange={(event) => setReason(event.target.value)} /></label><button className="primary-button" disabled={busy}>儲存草稿</button></form>}
    <div className={`thesis-master-detail${selected ? " has-detail" : ""}`}><section className="thesis-cards" aria-label="Thesis 清單">{items.length === 0 ? <p className="empty-state">這家公司目前沒有你的 Thesis。</p> : items.map((item) => <a className="thesis-card" key={item.thesis_id} href={`/companies/${encodeURIComponent(companyId)}/theses/${encodeURIComponent(item.thesis_id)}`}><div><strong>{item.title}</strong><small>Cycle {item.cycle} · v{item.version} · {new Date(item.updated_at).toLocaleString("zh-TW")}</small><small>{item.conditions.map(conditionSummary).join("、")}</small></div><span className={`thesis-status status-${item.status}`}>{statusLabel[item.status]}</span></a>)}</section>{selected && <aside className="thesis-detail-pane"><Detail item={selected} client={client} onChanged={changed} companyId={companyId} view={view} /></aside>}</div>
  </main>;
}
