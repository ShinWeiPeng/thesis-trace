# ALG-0035: 可追溯且有界的來源文字擷取

## Metadata

- Status: proposed
- Owner module: evidence_collection
- Product feature: 真實 HTML／文字型 PDF 的必要原文摘錄與解析狀態
- Flow IDs: 延續現有 Evidence admission/collection flow；精確 manifest links 在核准後 authoring gate 補齊
- Related ADRs: ADR-0010
- Source paths: planned collection contracts/ports/service; restricted source fetch adapter; new adapter-private extraction implementation
- Test and benchmark paths: planned demand-side extraction contract suite and real MediaTek source acceptance
- Supersedes: none; 保留 ALG-0001 的 URL/content identity 語意

## Problem and observable success

目前把回應前 500 bytes 解碼會得到 HTML 標籤或 PDF binary。成功必須表示有可讀、可定位的原文摘錄；不代表完整解析財務表格、確認來源事實、E-stage 升級或投資判斷。

## Inputs, outputs, units, ranges, and data-quality assumptions

輸入是經既有 HTTPS/DNS/SSRF 與 MIME/大小檢查的 bytes、canonical URL、content type、取得時間和原始 hash。文件與 metadata 皆不可信。

輸出是 immutable 擷取結果：原始 hash、extractor identity、policy version、帶定位的必要摘錄、解析狀態、完整性提示、可證明的日期或 null。正文內的提示詞不是系統指令；不同 source snapshot 不可混合。

## Constraints and quantitative acceptance thresholds

零容忍：binary 當正文、script 執行、時間捏造、無定位的數值解讀、失敗當成功、原始 hash 被擷取文字 hash 取代、歷史快照重寫、額外網路／付費 OCR／AI 呼叫。

保留現有單次下載上限 2,000,000 bytes、HTTP timeout 15 s、最多 3 次 redirect。PDF 壓縮後大小不能代表解析記憶體上限。解析程序的 CPU／wall-time／address-space／page／輸出上限必須經 bounded prototype 與實際部署限制決定，寫入版本化設定及 manifest 後才可進 production implementation；目前未校準，不宣稱 resource feasibility PASS。

## Candidate methods and comparative evidence

1. 原始前綴 bytes：現在實作；不符合正文與 PDF 語意，淘汰。
2. API 同步 HTML/PDF library：可抽文字，但不可信文件可阻塞請求或耗盡同程序記憶體，淘汰此部署位置。
3. collector 的受控解析程序：可保留 fetch/lease/state authority 並終止失控 parser；新增程序啟停／IPC 成本與 dependency 維護，為建議方向。

[pypdf 官方文字擷取說明](https://pypdf.readthedocs.io/en/6.18.0/user/extract-text.html) 指出 PDF 文字擷取可能大量耗用記憶體，且不是 OCR；沒有文字層不能假設可以解析。該文件是候選工具能力依據，不是本專案的成功測試。實際套件版本、license/security 與可用性需在安裝前核對並 lock。

## Selected method and reasons for rejecting alternatives

採用 deterministic local extraction 的方向，不用生成式 AI 補正文。HTML 以結構化 parser 排除 script/style 與非正文標記；PDF 以文字層及頁碼擷取。由既有 L2 collection 決定何時接受／拒絕結果，L3 封装格式工具與受控程序。精確 library configuration 與資源參數仍待 prototype；本文不是執行可行性已確認的宣告。

## Exact behavior, formula or pseudocode, boundaries, and tie-breaking

1. 驗證 bytes/MIME；計算原始 bytes hash，保留 canonical URL 與版本。
2. 依 MIME 分派 HTML、純文字／JSON 或 PDF；不因副檔名而略過驗證。
3. 解析只在無網路、無 secrets、可終止且受資源限制的程序完成；不可執行 shell 字串或文件內動作。
4. 依原文件區塊／頁碼順序產生片段。保留段落與表格語境；不把孤立數字自動綁成財務 fact。空文字、歧義編碼、損壞／加密／掃描 PDF、limit violation 回傳明確不可用原因。
5. 正規化換行與空白，但不得改寫文字、重排數值或生成摘要。必要摘錄若截斷，回傳定位及截斷資訊；沒有取得完整所需證據不得讓 critic 以完整文件已核對通過。
6. 未經核對的公告／事件日期保持缺值；retrieved_at 只表示取得時間。多個相衝突日期不自行選最新一個。
7. 原始 snapshot 和擷取 artifact 分別以原文 identity 與 extractor/policy identity 管理；同原文重新解析不能假裝新來源，也不能覆寫既有決策引用。

## Parameters, calibration, versioning, and compatibility

建議 policy identity `source-text-extraction-v1`。所有影響文字或接受範圍的設定必須一起 version；legacy excerpt 明確顯示未經新 policy 驗證。Parser/library 升級須重跑 golden 與不可信文件測試，不能静默更換。

## Time and space complexity and resource budgets

HTML／純文字 traversal 對受限输入近似 O(n)；不能替第三方 PDF parser 宣稱相同上界。PDF 需外部程序強制限制並有 termination/reap 證據。新增一次 bounded IPC；不可建立無上限程序池。此處 execution assurance 為 BLOCKED，直到 prototype、實際限制與 reserve 來源已確認。

## Errors, degradation, fallback, and forbidden behavior

區分 network failure、unsupported format、no text layer、invalid encoding、parser failure、resource limit、missing metadata。失敗保留來源連結及重試／人工核對提示，不回填虛構數據。掃描 PDF 的付費 OCR 或手動輸入原文是未選擇的後續能力，不自動啟用。

## Validation cases and evidence

2026-09-09 第一輪 [throwaway 原型紀錄](../design/source-extraction-prototype-20260909.md)：14 個隔離邊界案例符合預期，實際取得兩份聯發科官方來源並比較 PDF 模式。原型發現前綴片段選取會遺漏所需語境；plain 模式在單一營收 PDF 的必要 token 核對優於 layout，但不足以宣告通用解析成功。原型數值不是已核准政策，也不是正式環境資源校準。

Pending: production demand-owned contract suite、完整語境選取、多頁／混合掃描／編碼與 metadata 邊界、正式容器隔離與資源證據、同 hash 重解析兼容、source binding、API serialization、桌面/手機呈現、角色拒絕及新設計的 architecture gates。現有後端映像 Python 3.13.7 不含原型使用的 bubblewrap；host Python 3.14.4 的結果不得冒充 release-equivalent PASS。

生產來源實作前須通過確切 manifest 與參數設計 gate。真實驗收樣本只使用可核對的已發布資料；future-dated、抓取失敗或僅搜尋片段都不是正式原文快照。不得用 synthetic contract fixtures 宣稱投資假設已獲支持。

## Risks and monitoring

PDF 排版及表格可能失去語意，網頁模板變更可能抽到導覽文字。監控解析失敗與缺漏碼，不記錄全文、secret 或個人投資資料。使用者必須能開啟原文核對。

## Human approval

Pending. 僅為候選演算法及待驗證方向，尚未 accepted；參數與 prototype 缺口需解決後才可要求最終算法核准。
