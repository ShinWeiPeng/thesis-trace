# 聯發科真實 Evidence 工作區：現況與設計審核點

日期：2026-09-09。SPEC-0001 revision 97 confirmed；本次 `開始執行` 延續原規格，沒有授權付費 AI、正式部署或清空原資料庫。

## 已確認的問題

| 位置 | 實際行為 | 真實驗收影響 |
| --- | --- | --- |
| `platform/source_fetch.py` | 原始前 500 bytes 解碼；observed_at 使用取得時間；source_category 固定 C | HTML/PDF 不保證可讀；不能據此判定公告日、事件日或升級來源 |
| `api.py` EvidenceResponse/get_evidence | 只有 ID/version/status/snapshot ID | 網頁無法透過此介面取得正文、時間、hash、lineage |
| `frontend/src/App.tsx` | 本次 intake 存在 React state；缺少 Evidence 清單／snapshot 閱讀流程 | 重新整理後不能可靠回到原證據，也無法完成使用者要求的來源核對 |
| `tests/fixtures/acceptance_api.py` | 啟動時清除資料並建立假 valuation/portfolio facts | 本次禁止使用此入口；不得把假 forecast 移植到 2454 |
| `validation/on-device.yaml` | 舊 manifest hash；場景針對正式 Cloudflare/Server | 不能宣稱本機網頁已有有效 formal runtime acceptance profile |

以上由唯讀程式盤點建立，沒有啟動舊 fixture、修改使用者資料庫或執行真實 AI。

## 資料來源準備狀態

使用者選定 2454／聯發科。已查到[官方財務資訊](https://www.mediatek.com/zh-tw/investor-relations/financial-information)與[官方投資人行事曆](https://www.mediatek.com/investor-relations/ir-events)。截至本次查詢，財務頁列出 2026 Q2 法說／財報入口及截至 7 月的月營收，行事曆列 8 月營收於 2026-09-10 公布。

這些是 discovery URLs，不是已匯入產品的 Evidence，也不是已確認的 valuation source facts。頁面列有文件名稱不等於已成功取得 PDF；仍須逐一實際取得並核對 hash、時間及正文。尚未確認使用者研究假設、預測期間、估值 forecast 或個人資產設定，不會代填。

## Boundary Design（方向，未替代 manifest design gate）

| Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 公司 Evidence 清單／明細 | Research | HTTP/UI | L0 application | Research-owned immutable query values | L0 read projection / HTTP DTO | L0 | 已授權 Evidence/snapshot | L0→Research；L3→需求方 port | UI→SQL；L0→L2 私有狀態 |
| Bytes→原文片段 | 格式解析 L3 | evidence_collection L2 | research_domain | Collection-owned extraction result | Collection-owned acceptance values | Research/collection | 解析暫存，無私有投資資料 | L3 implements L2 demand | L2 import parser library；parser→網路/AI |
| 讀取→研究草稿 | Research / Thesis | 同公司網頁 | L0 | 各 owner 的 record/version | Thesis evidence reference | L0 | 既有 Evidence / 草稿 | 原本 owner services | 直接改 source snapshot；自造 forecast |

## Type / State ownership

Research L1 擁有新的 Evidence query/page/detail 語意值與 read port；fields 將包含公司／證據／版本／快照 identity、metadata、原文片段、缺漏理由。L2 collection 擁有 extraction command/result 和 demand port。Parser subprocess、library objects、IPC、temporary buffers 由 L3 私有持有。FastAPI wire DTO 與 React fetch/client state 分別屬其 adapters；不把父層 read model 傳入子層 public API。

Snapshot、擷取版本與 provenance 的持久權限留在 Research；parser 不寫 DB。查詢不變更任何 source、stage、Thesis、Recommendation。UI 只持有可放棄的 selection/loading/error state；不保存本機離線領域資料或設定 canonical validity。正式實作前逐欄補齊 manifest Type/State Catalog，無未決 owner 才能通過 design gate。

## Flow 與候選比較

既有：Owner URL→API 原子接收→獨立 collector fetch→快照 commit→狀態查詢。

建議：保留同一路徑，在 collector 加入受控原文擷取，再透過 Research query 將 immutable 明細呈現於同公司頁面。相較 API 同步下載／解析，多了程序/IPC成本，但避免將不可信文件解析放入互動 API。相較聊天灌資料，驗證涵蓋真正的 URL admission、collector、snapshot、HTTP 與 UI。

此為 best-effort 工作流，不宣稱硬／軟即時 deadline。PDF 解析記憶體及終止行為是 load-bearing 未驗證風險；需先做 bounded prototype 與記錄 deployment limits，execution assurance 目前 BLOCKED。不得以 gate PASS 或平均耗時替代資源隔離證據。

新增網站模板的變動集中於 extractor；新增來源權威分類必須沿 ALG-0003 的 Server fact 邊界，不放在 React。新增 OCR 是另一 adapter／隱私費用審核點，不在本次默認能力內。新增 durable subscriber 仍需重新評估 ADR-0002 的 job/outbox 選擇。

## 後續工作與停止點

1. ADR-0010 已於 2026-09-09 由 Owner 以 `核准 ADR-0010` 明確核准現有架構；ALG-0035 仍須先完成 bounded prototype 與精確參數／library 安全檢查，不能在未校準或未另行核准時標記 accepted。
2. 先建立適用本機且與正式 profile 分離的 validation enablement；不覆寫正式場景或繞過既有 Cloudflare policy。
3. 將已決定的 contracts/types/state/flow/exec mappings 寫入唯一 manifest；design gate PASS 後才進 production source。
4. TDD 公開查詢、parser port、錯誤語意與角色拒絕；實際官方資料用於人類可核對驗收，合成資料僅用於程式邊界測試。
5. 以獨立本機 DB 啟動真實前後端，匯入核對過的 2454 官方 URLs；不呼叫 AI，不建立假財務 facts。
6. 使用者在軟體查看來源並提供／確認 Thesis 與估值必要輸入；資料不足就停在清楚的缺漏提示，不發布建議。
7. 付費 candidate/critic 呼叫仍須另外授權。整體 SPEC-0001、REQ-044 與 runtime/release acceptance 均未完成。

## 初始設計檢查紀錄（核准前）

- 工程 router：confirmed SPEC resume PASS；最初自由文字無法分類，改以完整 implementation intent 重跑，沒有略過 gate。
- SPEC validate：revision 97、零 open decisions、REQ→AC traceability PASS。
- 本輪僅新增設計／演算法候選文件；沒有 production implementation、migration、package install、模型 API、資料庫寫入、server startup、commit 或 push。
- Working bundle 保持本機。新 ADR/ALG 的核准、parser prototype、manifest authoring、前後端與真實資料驗收都尚未執行，不以先前 Wave 7 測試代替。

## ADR-0010 核准紀錄（2026-09-09）

- Owner 明確指示 `核准 ADR-0010`，已將 ADR 標記 accepted 並記錄核准人、日期與範圍；未改寫其架構決策內容。
- SPEC-0001 revision 97 保持 confirmed；本次核准沒有新增或修改 REQ／DEC／AC，也沒有擴大付費、部署或資料庫操作權限。
- 下一個工作項是 ALG-0035 的有界解析 prototype 與資源限制驗證；算法尚未核准，production source 與正式 runtime acceptance 仍待後續 gates。
- 核准後檢查：canonical SPEC validate PASS；`architecture_cli.py gate --phase development` exit 0（既有 ADR-0004 dependency exception 與 FLW015 warning 保留）；`git diff --check` PASS。
- 既有來源安全回歸：`backend/.venv/bin/python -m pytest backend/tests/test_source_fetch.py -q --tb=short`，13 passed。涵蓋 redirect 私網拒絕、固定已驗證 IP、MIME／大小限制及 URL normalization；這是 mock transport 的既有行為測試，不是新 parser 或真實來源驗收。
- `git check-ignore` 確認 working snapshot 與 journal 都保持本機忽略。本次沒有 production code、資料庫、套件安裝、AI 呼叫、commit 或 push。

## 後續執行：第一輪解析原型（2026-09-09）

Owner 再次指示 `開始執行` 後，已完成 [ALG-0035 原型實驗](source-extraction-prototype-20260909.md)：14 個隔離邊界案例、兩份真實官方來源、64／128／256 MiB 候選設定及 PDF layout/plain 比較。透過 native permission 僅在 `/tmp` 安裝固定 pypdf/Ruff，沒有改 production dependency。

來源可讀，但前綴選取與正式 container 隔離仍有缺口；ALG-0035 不提前核准。下一項是語境完整性與本機 validation enablement，不是付費 AI 或網頁驗收。正式資料庫、既有服務與 working bundle 均保留。
