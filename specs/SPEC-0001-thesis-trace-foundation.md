---
spec_version: "1"
spec_id: SPEC-0001
revision: 1
status: confirmed
change_set: thesis-trace-foundation
---

# SPEC-0001: ThesisTrace Foundation

## Problem

個人投資研究散落在交易所公告、公司資訊、新聞、估值試算與交易紀錄中，缺乏一致的證據分級、可追溯因果鏈、後續驗證與決策反思。使用者需要一套以台灣上市櫃證券為起點的個人研究系統，將事件證據連結到 Thesis、估值、交易建議、實際交易與後續結果，用於訓練投資思考邏輯，而不是自動替使用者下單。

## Solution

建立 VPN-only 的 ThesisTrace Web 應用程式。系統由 React/TypeScript 前端、FastAPI API、PostgreSQL、Caddy，以及互相隔離的來源採集、AI 分析與郵件工作程序組成。

系統從 TWSE、TPEx、MOPS 與經核准的外部來源收集證據，依 E0 至 E6 分級，保留來源 provenance，並把 E2 至 E6 的正常進展整理成每日郵件。證據更正、撤銷、Hard anomaly 與交易建議採立即通知。

AI 經由 provider-neutral Ports 接入。OpenAI 為初始主 provider，Anthropic Claude 為通過評估後的備援。AI 負責提出有來源的分析與假設；估值、報酬、曝險限制與通知規則由 deterministic code 執行。所有實際交易均由使用者手動完成。

## User Stories

- 作為 Owner，我要追蹤台灣上市櫃公司的 E0 至 E6 證據演進，以便分辨事件、產品、商業化、財務反映與延續性。
- 作為 Owner，我要在每日摘要中收到所有 E2 至 E6 正常進展，並即時收到證據失效與重大風險，以便安排後續觀察或動作。
- 作為 Owner，我要取得附帶來源、反證、估值假設及失效條件的 AI 買賣建議，以便訓練決策思考而不是盲目遵循答案。
- 作為 Owner，我要記錄接受、拒絕或延後建議，以及其後的實際交易與反思。
- 作為 Learner，我要閱讀共享證據並建立自己的手動 Thesis，但不能取得個人化 AI 買賣建議。
- 作為 Admin，我要管理邀請、停權與服務狀態，但不應透過應用程式讀取其他使用者的投資組合。

## Requirements

| ID | Requirement |
| --- | --- |
| REQ-001 | 使用 Ubuntu Server 26.04 LTS、Docker Compose、Caddy、PostgreSQL、React/TypeScript 與 FastAPI 部署。應用程式只能透過 VPN HTTPS 存取，不公開 SSH、PostgreSQL、Docker API 或管理子網。 |
| REQ-002 | 支援 TWSE、TPEx、MOPS，以及管理員白名單或使用者提交的非官方 URL。保存來源網址、時間、發布者、必要摘錄、雜湊、取得狀態與 provenance。AI 搜尋結果不得直接成為 source of record。 |
| REQ-003 | 支援 E0 至 E6 證據階段。E2、E3、E4、E5、E6 的首次達成與正常升級都必須進入每日 21:00 Asia/Taipei 摘要；更正、撤銷、降級與失效必須立即寄送。Hard anomaly、交易建議與建議撤回也必須立即寄送。 |
| REQ-004 | 核心領域透過 RecommendationProvider 與 RecommendationCritic 使用 AI，不得依賴特定 AI SDK。OpenAI 為初始主 provider；發生 provider-wide 故障時以相同來源快照完整重跑 Claude。雙方失敗、schema 無效或 critic 失敗時必須 fail closed。 |
| REQ-005 | AI 只提出有來源的估值假設；deterministic code 使用 forecast EPS 乘 target PE 或 forecast BVPS 乘 target PB 計算目標價、股息、費用、稅與報酬。最低年化淨總報酬未設定或資料不足時不得產生買進建議。 |
| REQ-006 | DCA 倍率限於 0x、0.5x、1x、1.5x；單一證券曝險上限 10%，單一產業上限 30%。基準目標建議賣出 Thesis 整體部位 25%，樂觀目標再賣出 25%，保留 50% 核心部位。Hard invalidation 可建議全部退出。 |
| REQ-007 | Hard anomaly 必須有一項官方證據，或兩項獨立可信證據，並通過 critic。價格、成交量異常或尚未確認的事件只能形成 Soft anomaly 與人工檢查要求；證據不足不得產生 hard sell。 |
| REQ-008 | 使用 10 分鐘、單次使用的 Email Magic Link，資料庫只保存 token hash。Owner 可使用完整研究與交易建議；Learner 只能使用共享證據、E0 至 E6 Dashboard 及自己的手動 Thesis；Admin 只能管理帳號與營運狀態。最多 10 個啟用帳號，個人資料由應用層 scope 與 PostgreSQL RLS 隔離。 |
| REQ-009 | 交易資料使用 canonical CSV 或手動輸入，經預覽、驗證、去重與使用者確認後寫入。保留 BrokerStatementParser Port，但在取得真實券商樣本前不實作特定 parser。系統不得保存券商憑證或呼叫下單 API。 |
| REQ-010 | Gmail API OAuth 實作 EmailDeliveryPort，採 at-least-once、冪等鍵、1 分鐘、5 分鐘與 30 分鐘重試及 dead-letter。郵件不得包含實際投入金額、總資產、完整持股或預估獲利金額。 |
| REQ-011 | 採集、AI 分析及郵件寄送為三類獨立 worker，使用 PostgreSQL durable queue/outbox。慢速 AI 不得阻塞來源採集或已排程郵件。官方事件五分鐘輪詢；十分鐘目標屬 freshness SLO，不宣稱 CPU 即時排程保證。 |
| REQ-012 | 舊悠行館 OpenVPN 設定不得用於正式環境。向今網取得 UDP port 與 DDNS 後部署 WireGuard，並只路由 ThesisTrace HTTPS。 |
| REQ-013 | PostgreSQL 備份先執行 client-side encryption，再上傳 Backblaze B2。保存 30 份每日與 12 份每月備份，新備份套用 30 天 Object Lock，每月必須實際解密並還原到隔離資料庫。 |
| REQ-014 | 使用者已決定不啟用全磁碟加密。專案必須記錄實體磁碟遭存取時的資料曝光風險，並實施主機實體安全、鎖定畫面、敏感欄位加密與加密雲端備份，不得宣稱這些控制等同全磁碟加密。 |
| REQ-015 | 專案採 Git 版本控管，追蹤程式碼、lockfiles、migrations、測試、canonical specs 與架構文件。秘密、OAuth token、AI/B2 金鑰、資料庫、郵件內容、匯入檔、備份、日誌與建置輸出不得提交。 |
| REQ-016 | 依 govern-modular-event-architecture schema 2.1.0 建立模組、Ports、Events、Type Ownership、State Ownership、Boundary Design、Flows、Algorithm Design Records、Execution Profiles、Description Views 與 proposed ADR。架構、程式、測試與生成視圖必須同步驗證。 |

## Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| DEC-001 | 使用 Ubuntu Server 26.04 LTS，不使用 Windows Server。 | 專案以 Linux containers、PostgreSQL、無頭背景工作與最小主機介面為核心。 |
| DEC-002 | PostgreSQL 同時負責主要資料、durable jobs、outbox 與 dead-letter，不增加 Redis。 | 降低單機部署元件與額外資料持久化負擔。 |
| DEC-003 | 採集、AI 分析、郵件投遞使用三類獨立 worker。 | 外部 AI 延遲不得阻塞來源輪詢或通知。 |
| DEC-004 | E2 至 E6 正常進展於每日 21:00 寄送摘要；更正、撤銷、失效與高風險事件即時寄送。 | 降低通知疲勞，同時確保風險與證據品質變化不被延遲。 |
| DEC-005 | OpenAI 為初始主 provider，Claude 為完成 30 個人工標註案例、10 次 live shadow run 與人工核准後的備援。 | 保留模型替換能力並以相同品質閘門控制風險。 |
| DEC-006 | 個人化 AI 買賣、目標價、預估報酬與 DCA 倍率只提供 Owner。 | Learner 定位為研究與思考訓練角色，並降低向他人提供個人化投資建議的法規風險。 |
| DEC-007 | 不提供券商 API 或自動下單。 | 所有交易決策與執行責任保留給人。 |
| DEC-008 | 使用 Gmail API OAuth 與 Email Magic Link。 | 以可替換郵件 Port 隔離供應商，並避免保存傳統密碼。 |
| DEC-009 | 淘汰現有悠行館 OpenVPN 設定，正式環境改採 WireGuard。 | 該設定使用 AES-128-CBC、comp-lzo、未加密內嵌私鑰與泛用 client 憑證，且無法證明路由隔離。 |
| DEC-010 | 使用 Backblaze B2、client-side encryption 與 Object Lock，並以實際還原作為備份驗收。 | 單一 NVMe 主機必須具備可驗證且抗誤刪的異地復原能力。 |
| DEC-011 | 接受不使用全磁碟加密的剩餘風險。 | 這是使用者明確選擇；補償控制不得被描述為等效保護。 |
| DEC-012 | v1 僅支援台灣上市與上櫃證券、TWD、官方收盤後價格與成交量分析。 | 控制資料來源、交易日曆、稅費與法規範圍；不宣稱盤中即時行情。 |

## Acceptance Criteria

| ID | Requirements | Scenario | Validation Method | Evidence |
| --- | --- | --- | --- | --- |
| AC-001 | REQ-001 | 從全新 Ubuntu Server 依版本鎖定設定部署。 | Docker Compose config 驗證、容器健康檢查、VPN 內外連線測試及公開 port 掃描。 | Pending execution |
| AC-002 | REQ-002 | 同一官方事件被重複取得，且非官方來源缺少必要 provenance。 | Adapter contract tests、來源去重整合測試與資料庫 constraint tests。 | Pending execution |
| AC-003 | REQ-003 | E2 至 E6 首次達成、連續升級、更正、撤銷及 21:00 停機後恢復。 | Fake Clock 整合測試，驗證摘要窗口、完整階段演進、即時事件與唯一補寄。 | Pending execution |
| AC-004 | REQ-004 | OpenAI 成功、OpenAI provider-wide 失敗、Claude 失敗、critic 失敗與 schema 無效。 | Provider contract suite 與 fail-closed orchestration tests；所有 schema、引用、曝險與 abstain 檢查必須 100% 通過。 | Pending execution |
| AC-005 | REQ-005 REQ-006 | PE/PB 估值、費稅、股息、不同期間、曝險上限、預算衝突與分批獲利。 | Deterministic unit tests、property tests 與固定黃金案例；未設定最低報酬時必須輸出 0x 且不產生買進建議。 | Pending execution |
| AC-006 | REQ-007 | Hard anomaly 正例、來源不足負例及 novel event。 | 人工標註資料集與 policy tests；關鍵正例全部偵測，hard-anomaly 負例不得出現 hard sell。 | Pending execution |
| AC-007 | REQ-008 | Learner 嘗試透過 UI、API、匯出與猜測 ID 讀取 Owner 資料。 | RLS integration tests、API authorization tests 與 Playwright E2E；所有越權操作必須拒絕且不洩漏資料存在性。 | Pending execution |
| AC-008 | REQ-009 | 合法 CSV、欄位錯誤、重複交易、無法配對建議及手動輸入。 | Import parser unit tests、preview/confirm integration tests 與 transaction reconciliation tests。 | Pending execution |
| AC-009 | REQ-010 | Gmail 逾時、暫時失敗、程序重啟、重複投遞與永久失敗。 | Fake EmailDeliveryPort 與 outbox integration tests，驗證 1/5/30 分鐘重試、冪等及 dead-letter。 | Pending execution |
| AC-010 | REQ-011 | AI 呼叫長時間延遲，同時持續產生來源事件與待寄郵件。 | 隔離 worker load test 與 freshness metrics；AI worker 不得阻塞下一輪採集或郵件投遞。 | Pending execution |
| AC-011 | REQ-012 | VPN client 僅存取 ThesisTrace HTTPS，無法存取 SSH、PostgreSQL、Docker API 或管理網段。 | WireGuard 設定檢查、路由測試與 VPN 內部 port 掃描。 | Pending execution |
| AC-012 | REQ-013 | 從一份受 Object Lock 保護的加密備份復原至全新隔離 PostgreSQL。 | 每月 restore drill，記錄解密、migration、資料列數、關聯與雜湊驗證結果。 | Pending execution |
| AC-013 | REQ-014 | 主機磁碟未加密且秘密與敏感欄位採補償控制。 | Security checklist、秘密掃描、欄位加密測試及風險揭露人工簽核。 | Pending execution |
| AC-014 | REQ-015 | 提交 source、migration 與文件，同時在工作區放置測試秘密與生成輸出。 | git status、git check-ignore 與 secret scan；允許檔案被追蹤，禁止項目必須忽略或阻擋。 | Pending execution |
| AC-015 | REQ-016 | 建立及修改架構 manifest、ADR、演算法紀錄與 generated views。 | 執行 architecture_cli.py design/development gate、deterministic render check、Python analyzer 及描述連結檢查，全部必須 PASS。 | Pending execution |

## Relationships

| Source | Relation | Target |
| --- | --- | --- |
| REQ-003 | depends_on | REQ-002 |
| REQ-003 | depends_on | REQ-010 |
| REQ-005 | depends_on | REQ-004 |
| REQ-006 | refines | REQ-005 |
| REQ-007 | refines | REQ-006 |
| REQ-008 | depends_on | REQ-001 |
| REQ-010 | depends_on | REQ-011 |
| REQ-012 | refines | REQ-001 |
| REQ-013 | depends_on | REQ-001 |
| REQ-016 | refines | REQ-011 |
| DEC-004 | depends_on | REQ-003 |
| DEC-005 | depends_on | REQ-004 |
| DEC-006 | depends_on | REQ-008 |
| DEC-009 | depends_on | REQ-012 |
| DEC-010 | depends_on | REQ-013 |

## Out of Scope

- 自動券商下單、保存券商密碼或交易憑證。
- 台灣上市與上櫃以外市場。
- 盤中即時行情、低延遲交易或硬即時期限保證。
- Learner 的個人化 AI 買賣方向、目標價、預估報酬或 DCA 倍率。
- 在沒有真實樣本前實作特定券商 CSV parser。
- 公網 Web、SSH、PostgreSQL、Docker API 或管理介面。
- 宣稱系統或營運者提供持牌投資顧問服務。
- 將外部文章全文大量保存或以 AI 搜尋結果取代來源證據。

## Deployment Inputs

最低年化淨總報酬數值、Gmail OAuth、OpenAI/Claude、Backblaze B2 憑證，以及今網 UDP port/DDNS 是部署輸入或啟用條件，不是尚未決定的產品或架構行為。缺少必要輸入時，受影響功能必須維持停用或 fail closed。

## Open Decisions

無未決事項

## Routing/Gates

- ask-matt: PASS
- project state at materialization: implementation absent, stateful context absent
- grill-me: PASS, decision-complete working spec
- clarify-improvement-proposals: required for the confirmed architecture proposal
- govern-modular-event-architecture: required, schema 2.1.0
- spec-governance materialize: authorized
- spec-governance verify: pending repository validation
- TDD and product implementation: not started
- Architecture ADRs and Algorithm Design Records remain proposed until explicit non-AI approval.
- Production completion requires Validation Enablement, per-change development validation, final runtime acceptance, release acceptance, architecture gate, deterministic generated-view comparison and code review.

## Revision History

| Revision | Date | Status | Changes |
| --- | --- | --- | --- |
| 1 | 2026-08-02 | confirmed | Materialized the greenfield ThesisTrace discussion. Recorded platform, evidence ladder, E2-E6 digest policy, replaceable AI, valuation and risk rules, roles, mail, portfolio import, worker isolation, VPN decision, backup, disk-encryption risk, architecture governance and Git policy. Replaced the earlier E2 immediate-volume rule with a daily 21:00 E2-E6 digest and replaced conditional reuse of the legacy OpenVPN profile with WireGuard. |
