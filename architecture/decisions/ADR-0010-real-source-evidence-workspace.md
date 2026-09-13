# ADR-0010: 真實來源擷取與可追溯 Evidence 工作區

- Status: accepted
- Date: 2026-09-09
- Decision owner: project owner
- Related specification: SPEC-0001, REQ-002/003/004/042/044/047, DEC-096
- Related algorithms: proposed ALG-0035; preserve accepted ALG-0001/0002/0003/0008/0009/0032
- Related review: [聯發科真實資料驗收前置設計](../design/mediatek-real-evidence-workspace.md)

## Context

使用者選定聯發科（2454），要求由實際網頁完成證據查閱後再進行分析，不以虛構資料或聊天搜尋取代產品驗收。

目前 production `RestrictedHttpSourceFetcher` 以回應前 500 bytes 解碼作為 excerpt，並將取得時間同時當作 observed_at；它不能證明正文、公告時間或財務事件時間。Evidence HTTP 查詢只有 ID、version、status、snapshot ID。既有 local acceptance fixture 會清除資料並注入虛構估值，不適合本次真實公司驗收。

## Decision

1. 延續現有真實 React/FastAPI/PostgreSQL 工作流，不另建展示用網頁。以公司 Evidence 頁呈現可重新開啟的紀錄與來源明細，保留 record/version 及待辦返回 context。
2. Research L1 擁有 Evidence 讀取契約與查詢需求；L0 負責 Access 授權及 Research 映射。PostgreSQL 只透過 Research-owned port 提供資料；HTTP/browser 不直接取得資料庫連線或查詢 sibling 私有資料。
3. 查詢回傳來源 URL、publisher、content hash、必要原文摘錄、取得／公告／事件時間、來源分類、lineage、擷取政策與缺漏提示。未能證明的時間維持 null；取得時間不冒充公告時間。摘錄是原文片段，不是 AI 摘要或確認後的財務事實。
4. ALG-0035 在 collector 中增加格式辨識及隔離的 bounded 文字擷取。保留原始位元組 hash 和既有 URL 正規化／SSRF 規則；HTML 不執行 script，PDF 不執行文件動作。無文字層、損壞、編碼不明或資源上限等情形明確失敗，不用亂碼或 AI 補寫的文字宣告成功。
5. 新擷取結果記錄 extractor/policy version；既有快照不重寫，不把歷史舊 excerpt 默認為已通過新解析。解析器版本變更不等同來源內容改變，必須保持原文 identity 與衍生擷取 identity 可區分。
6. 來源可信度仍由既有政策與可驗證事實決定。公司官網 URL 是來源歸屬的線索，不代表每個段落都是已實現財務事實；不因網站網域或使用者勾選就讓 AI 任意升級 A/B/C。
7. 只保存必要摘錄與 provenance，不持久化大量文章全文。每一段應有頁碼或區塊定位及完整性／截斷標示；安全地以文字呈現，不能以外部 HTML 注入 DOM。
8. 本次先完成真實 Evidence 呈現與研究草稿準備；不自動建立使用者投資假設、預測 EPS、歷史估值倍數、持股、現金或交易成本。缺少真實估值或風控必要資料時，分析入口清楚列出缺漏並保持阻擋，不複用 Wave 6 假資料。
9. 本機驗收使用獨立、明確命名且可重啟保留的資料庫與 test-only identity。不得執行會清空原 `thesis_trace` 的舊 fixture。正式 Cloudflare profile 不改作本機驗收；本機與正式驗收證據分開保存。兩種環境都不能把 provider mock 標示為真實 AI。
10. 目前付費 AI、OCR 外部服務與 production activation 均未授權。批准本 ADR 不代表批准上述費用、外傳或部署。

## Alternatives and tradeoffs

- 聊天搜尋後直接灌入一份建議：無法驗證產品採集、快照或查詢，不採用。
- 在 API 請求內下載、解析 PDF：少一個處理階段，但將不可信文件成本帶入互動請求，違反既有 collector 隔離方向，不採用。
- 保留獨立 collector，增加可終止的本機解析程序及 typed Research 查詢：可保留 durable admission/retry 與原始 hash；代價是 parser dependency、受控程序、衍生 metadata 與更多回歸測試。選擇此方向是為了可信度和故障隔離，不宣稱效能較快。

## Compatibility and governance

這是既有 SPEC-0001 的未完成能力，不修改 5% 本機門檻、Recommendation 決策規則、權限或正式 Hard 啟用條件。新增 API/client/storage metadata 應 additive；舊 status endpoint 保持相容。完整 chain/fact 搜尋與更正／撤銷歷史不得因本次最小來源明細頁完成就標記 REQ-044 全部通過。

本 ADR 不豁免任何 MUST。批准後仍須把精確 Type/State/Port/Mapping/Execution Catalog 寫入 manifest，通過 design gate，才可改 production source。generated views 只能由 CLI 產生。

## Validation

以同一 demand-owned contract suite 測 Fake 與 real extraction/read adapters；涵蓋正常 HTML、文字型 PDF、缺少文字層、HTML script、錯誤編碼、惡意壓縮／資源耗盡、重新導向 SSRF、時間缺漏、舊 snapshot 相容、外部資料不進入私有模型與角色拒絕。真實聯發科文件只作手動核對過的驗收證據；不以測試合成資料支持投資結論。

Desktop/mobile 需證明重整與返回保留公司及 evidence 身分，原文可核對，缺漏清楚，沒有付費 provider 呼叫。完整 runtime acceptance、release gate 與 review 另外執行。

## Human approval

- Approver: project owner
- Approval date: 2026-09-09
- Approval reference: ongoing SPEC-0001 conversation, explicit instruction `核准 ADR-0010`.
- Scope: 本 ADR 的現有架構內容。ALG-0035 仍為 proposed，須完成解析參數與 bounded prototype 後另行核准；不代表 production implementation、runtime acceptance 或 SPEC-0001 完成。
- Authorization boundary: 未授權付費 AI／OCR、正式部署、清空原資料庫、commit 或 push；working bundle 保留本機。
