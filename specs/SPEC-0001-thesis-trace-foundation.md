---
spec_version: "1"
spec_id: SPEC-0001
revision: 87
status: confirmed
change_set: thesis-trace-foundation
---

# SPEC-0001: ThesisTrace Foundation

## Problem

個人投資研究散落在交易所公告、公司資訊、新聞、估值試算與交易紀錄中，缺乏一致的證據分級、可追溯因果鏈、後續驗證與決策反思。使用者需要一套以台灣上市櫃證券為起點的個人研究系統，將事件證據連結到 Thesis、估值、交易建議、實際交易與後續結果，用於訓練投資思考邏輯，而不是自動替使用者下單。

## Solution

建立以 Cloudflare Tunnel／Access 保護、無需 VPN／WARP 的 ThesisTrace 響應式 Web 應用程式；application runtime、PostgreSQL 與領域資料仍保留在本地 Linux Server VM，origin 不開放 Internet inbound port。系統由 React/TypeScript 前端、FastAPI API、PostgreSQL、Caddy，以及互相隔離的來源採集、AI 分析與郵件工作程序組成。

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
| REQ-001 | 使用 Ubuntu Server 26.04 LTS、Docker Compose、Caddy、PostgreSQL、React/TypeScript 與 FastAPI 部署。應用程式只能透過 REQ-012 定義的 Cloudflare Access 保護 HTTPS 入口存取，不公開任何 origin inbound port、SSH、PostgreSQL、Docker API 或管理子網。 |
| REQ-002 | 支援 TWSE、TPEx、MOPS，以及管理員白名單或使用者提交的非官方 URL。保存來源網址、時間、發布者、必要摘錄、雜湊、取得狀態與 provenance。AI 搜尋結果不得直接成為 source of record。 |
| REQ-003 | 每條 Evidence Chain 必須分別保存來源可信度、產品成熟度、商業化、財務影響及延續性等維度，並由 deterministic code 以逐級閘門推導摘要階段：E0 未驗證線索；E1 官方來源或兩項獨立可信來源確認具體事件；E2 產品、技術、產能或合作已成立；E3 出現合約、訂單、客戶或出貨等商業化證據；E4 營收已可辨識地反映；E5 獲利或現金流已可辨識地反映；E6 財務影響至少連續兩個季度成立。AI 只能提出有來源的候選事實，不得直接設定最終階段。高階證據可直接跳級，但必須滿足該階及所有前置閘門；更正、撤銷或來源失效時必須從保存的來源快照重新計算並可降級或失效。每次維度及階段變更均保存事件時間、觀測時間、原因與來源快照。E2 至 E6 的首次達成與正常升級進入每日 21:00 Asia/Taipei 摘要；更正、撤銷、降級與失效立即寄送。Hard anomaly、交易建議與建議撤回也立即寄送。 |
| REQ-004 | 核心領域透過 RecommendationProvider 與 RecommendationCritic 使用 AI，不得依賴特定 AI SDK。OpenAI 為初始主 provider；發生 provider-wide 故障時以相同來源快照完整重跑 Claude。雙方失敗、schema 無效或 critic 失敗時必須 fail closed。 |
| REQ-005 | 每個 Thesis 的 Owner 必須明確確認 valuation method 為 PE、PB 或 abstain，並選擇 6、12 或 24 個日曆月的估值期間，預設 12 個月；系統必須保存估值基準時間及明確 target date。AI 只能提出附來源與理由的候選方法及假設，不得自行啟用估值。forecast EPS 或 forecast BVPS 必須對齊 target date 並由 Owner 確認；預測輸入於新季報發布、發生影響該假設的重大事件或保存滿 90 天時失效，以最早者為準。target PE/PB 必須同時支援公司自身歷史分布及 Owner 管理的 peer group 比較，保存各方法的資料期間、有效樣本、排除原因、分布與來源；公司歷史基準候選值為至少五年有效月資料的中位數，樂觀候選值為第 75 百分位，少於三年有效資料時不得自動產生自身歷史候選值。EPS 或 BVPS 非正值的期間不得分別納入 PE 或 PB 樣本。公司歷史與 peer group 必須分開計算及顯示，不得自動加權或合併；Owner 必須為每個 Recommendation 明確選擇 company_history、peer_group 或 abstain 並保存理由，兩組結果及差異均須保留。peer group 必須由 Owner 逐一確認並版本化，包含 5 至 12 家台灣上市櫃公司；每家須保存相近主要商業模式或營收驅動因素的納入理由，使用相同 valuation method，排除目標公司、資料失效或來源不完整者，PE 排除 EPS 非正值者，PB 排除 BVPS 非正值者。每個 Recommendation 必須固定 peer-group snapshot；有效同業少於 5 家時 peer_group 必須 abstain。方法或來源未確認、選擇 abstain、輸入不完整、輸入失效或所選方法不適用時，不得產生目標價或買進建議。有效時由 deterministic code 使用 forecast EPS 乘 target PE 或 forecast BVPS 乘 target PB 計算目標價、股息、費用、稅與報酬。Owner 必須建立版本化 Cost Profile，包含買進與賣出手續費率、各自最低手續費、適用證券交易稅規則及生效時間；未設定時不得產生買進建議。purchase_outflow 等於買進價金加買進手續費；terminal_inflow 等於目標賣出價金扣除賣出手續費與證券交易稅，再加預計現金股息；holding_days 為估值基準時間至 target date 的實際日數；annualized_net_total_return 等於 (terminal_inflow / purchase_outflow)^(365 / holding_days) - 1。計算使用 decimal 精度且只在顯示時四捨五入。結果必須標示為扣除交易成本與證交稅、未計個人綜合所得稅及補充保費；不同期間以此公式換算。最低年化淨總報酬未設定、holding_days 非正值或資料不足時不得產生買進建議。 |
| REQ-006 | DCA 倍率限於 0x、0.5x、1x、1.5x；單一證券曝險上限 10%，單一產業上限 30%。每個 Recommendation 必須建立不可變 Portfolio Snapshot：portfolio_nav 等於所有持股依最近交易日 TWSE／TPEx 官方收盤價計算的市值，加上 Owner 維護的可投資現金；保存持股、現金、價格、價格日期及來源。security_exposure 為建議交易後該證券全部持股市值除以建議交易後 portfolio_nav；industry_exposure 為建議交易後該產業全部證券市值除以建議交易後 portfolio_nav。同一證券跨多個 Thesis 的部位必須合併計算。產業曝險必須同時計算兩套分類：(a) TWSE／TPEx 官方主要產業，每檔證券恰有一個；(b) Owner 確認並版本化的零至多個自訂風險主題，每檔證券在每個主題中完整計入。AI 可提出自訂主題但不得自行生效。任何官方產業或任何自訂主題的建議交易後曝險超過 30% 都必須阻擋買進；缺少有效官方分類時不得產生買進建議。Recommendation 必須保存官方分類與自訂主題的不可變快照、來源、生效時間及各自曝險結果，後續分類變更不得改寫歷史結果。缺少完整持股、可投資現金或有效官方價格時不得產生買進建議。10% 與 30% 為 deterministic hard cap，Owner 不得對單筆 Recommendation 覆寫。程式必須在可投資現金及兩項上限內，將原始 DCA 建議依 1.5x、1x、0.5x、0x 順序向下選擇最高可行倍率；現有證券或產業已超限時所有追加買進必須為 0x，但可產生持有、減碼或退出建議，不得因超限自動下單或自動賣出。風險上限只能透過新的版本化政策變更，且不得改寫歷史 Recommendation。實際投入金額、portfolio_nav 與完整持股不得出現在郵件。基準目標建議賣出 Thesis 整體部位 25%，樂觀目標再賣出 25%，保留 50% 核心部位。Hard invalidation 可建議全部退出。 |
| REQ-007 | anomaly 來源模型必須同時保留固定來源層級與可解釋評分。原始來源分為：(A) 權威第一方，包括 TWSE、TPEx、MOPS、主管機關、法院、公司及交易對手的正式公告；(B) 可信獨立來源，包括具編輯責任、署名及可驗證原始證據的新聞、產業資料或研究機構；(C) 未驗證線索，包括社群、論壇、匿名消息、無原始來源轉載、AI 搜尋摘要及單純價格／成交量異常。經評分的線索為保留原始來源、底層證據、特徵與相依關係後的衍生狀態，不是能取代 A/B/C 的新原始來源。C 級線索以時效性、原始來源可追溯性、事件具體程度、獨立佐證程度及 Thesis／invalidation 關聯五項各 0 至 2 分，由 AI 提出附引用的候選特徵、deterministic code 加總、critic 驗證。8 至 10 分立即要求人工檢查與尋找 A/B 證據；5 至 7 分進入觀察清單與每日摘要；0 至 4 分只保存。任何分數都不得把 C 級線索改列 A/B、計入 Hard-anomaly quorum 或直接產生 hard sell；只有後續取得的新 A/B 證據可重新評估。轉載、共同引用同一匿名消息或相同底層報告只能算一項來源。Hard anomaly 必須對應 Thesis 預先定義的 hard invalidation condition，並具有一項直接支持的 A 級證據，或兩項具有不同發布者及不同底層證據的 B 級來源。RecommendationCritic 必須逐項驗證來源可取得、引用直接支持事實、公司／證券／事件主體一致、發布與事件時間合理、符合預定 invalidation、B 級底層證據獨立，且沒有較新 A 級證據直接否定事件；必須輸出有效結構化 PASS。任何欄位缺失、schema 錯誤、模型失敗、來源衝突、無法證明獨立性或 critic 非 PASS 都必須降為 Soft anomaly。deterministic policy 通過後才能形成 Hard anomaly；只能產生退出建議，不得自動交易。價格、成交量或證據不足的事件只能形成 Soft anomaly／經評分線索與人工檢查。正式啟用 Hard anomaly 前必須通過版本化 100 案例資料集：20 個單一 A 正例、20 個兩項獨立 B 正例、20 個單一 B／高分 C／證據不足負例、15 個同源／共同匿名／衝突案例、15 個 critic timeout／schema／引用／主體／時間錯誤及 10 個價格／成交量／novel event；至少涵蓋 10 家公司及 5 個官方產業。40 個 Hard 正例必須全部形成 Hard，60 個非 Hard 不得形成任何 Hard，來源分類、同源去重、線索評分及 critic fail-closed 必須 100% 符合標註。其後必須在正式 Linux Server VM 以真實資料執行連續 30 天 shadow mode；would-be Hard 只供 Owner 審查，不得寄送正式退出建議。任何 false Hard 都必須修正並重新開始完整 30 天；模型、prompt 或 policy 變更必須重跑 100 案例。完成後仍需 Owner 明確啟用 Hard 通知。 |
| REQ-008 | v1 的一般登入必須由 Cloudflare Access 使用 Google identity provider 驗證，Access Allow policy 只能逐一列出 Owner 核准的完整 Google email，不得以整個 email domain、任何已驗證 Google 使用者或公開規則放行。一般 Google Allow policy 的 Access application token/session duration 必須固定為 8 小時；到期後的下一次存取必須重新完成 Google identity 驗證與 Access MFA，不得只以 ThesisTrace 自有 cookie 延長。ThesisTrace 若保存 Server-side session，只能綁定目前已驗證 Access JWT、內部 user ID 與最晚不超過該 Access token 的到期時間；登出後必須立即撤銷本身 session。另保留一個只對同一位 Owner 開放的 Cloudflare account identity 作為緊急備援；該 identity 不得對 Learner、Admin 或其他 Cloudflare account member 開放，也不得取得高於 Owner 原有角色的權限。兩種登入都必須通過 Access MFA 要求，FastAPI 必須依 REQ-012 驗證 JWT，並以穩定的內部 user ID 對應已核准 identity；相同 email 字串不得自動合併兩個 provider identity。新增、停用、替換 identity 或使用緊急備援都必須留下不可修改的稽核紀錄。Owner 可使用完整研究與交易建議；Learner 只能使用共享證據、E0 至 E6 Dashboard 及自己的手動 Thesis；Admin 只能管理帳號與營運狀態。最多 10 個啟用帳號，個人資料由應用層 scope 與 PostgreSQL RLS 隔離。Email Magic Link 不屬於 v1 登入方式。 |
| REQ-009 | 交易資料使用 canonical CSV 或手動輸入，經預覽、驗證、去重與使用者確認後寫入。保留 BrokerStatementParser Port，但在取得真實券商樣本前不實作特定 parser。系統不得保存券商憑證或呼叫下單 API。 |
| REQ-010 | Gmail API OAuth 實作 EmailDeliveryPort，採 at-least-once、冪等鍵、1 分鐘、5 分鐘與 30 分鐘重試及 dead-letter。郵件不得包含實際投入金額、總資產、完整持股或預估獲利金額。 |
| REQ-011 | 採集、AI 分析及郵件寄送為三類獨立 worker，使用 PostgreSQL durable queue/outbox。慢速 AI 不得阻塞來源採集或已排程郵件。官方事件五分鐘輪詢；十分鐘目標屬 freshness SLO，不宣稱 CPU 即時排程保證。 |
| REQ-012 | 舊悠行館 OpenVPN 與 WireGuard 均不得作為 v1 使用者入口。必須先建立覆蓋完整 hostname 及所有 path 的 deny-by-default Cloudflare Access self-hosted public application，再建立 named Cloudflare Tunnel public-hostname route；不得使用 Quick Tunnel、Access Bypass policy 或不受 Access 保護的公開 path。`cloudflared` 只能從本地 Server 主動連出 Cloudflare 所需的 tunnel egress，origin 防火牆不得開放任何 Internet inbound port；tunnel ingress 只能代理至本地 Caddy HTTPS 的 ThesisTrace Web/API，不得路由 SSH、PostgreSQL、Docker API、其他 VM 或管理子網。FastAPI 必須對每個受保護請求獨立驗證 Access JWT 的簽章、issuer、application audience、有效期間及允許 identity，驗證金鑰更新或 Cloudflare 不可用且無可驗證快取時 fail closed；不得只信任可由 client 偽造的 identity header。Access application、tunnel、DNS、token audience、policy、cloudflared credential 與 origin route 必須版本化或可重建，secret 不得提交 Git。 |
| REQ-013 | PostgreSQL 備份先執行 client-side encryption，再上傳 Backblaze B2。保存 30 份每日與 12 份每月備份，新備份套用 30 天 Object Lock，每月必須實際解密並還原到隔離資料庫。 |
| REQ-014 | 使用者已決定不啟用全磁碟加密。專案必須記錄實體磁碟遭存取時的資料曝光風險，並實施主機實體安全、鎖定畫面、敏感欄位加密與加密雲端備份，不得宣稱這些控制等同全磁碟加密。 |
| REQ-031 | 研究閉環必須以明確狀態機及追加式稽核紀錄保存於 PostgreSQL。Thesis 狀態為 draft、active、paused、invalidated、closed；每次 Recommendation 都是不可修改的新版本並連結來源快照、估值假設及失效條件；Owner Decision 為 accepted、rejected、deferred 或 expired；Trade 必須把全部成交股數明確分配至一個或多個 active Thesis 及／或 independent decision 桶，分配合計必須等於成交股數；Recommendation 的建議數量只歸屬指定 Thesis，但證券與產業風控合併該證券全部分配桶。賣出必須由 Owner 指定扣減桶且不得超過其可用股數，不採跨 Thesis 自動 FIFO；交易更正以追加式紀錄修正交易與分配；股票分割、減資及股票股利按各桶持有比例處理。Outcome 保存後續結果；Reflection 保存原假設、判斷錯誤、遺漏證據與改進。系統以正常化資料表保存目前狀態，另以 append-only audit events 保存所有合法轉移。不得覆寫 Recommendation、Decision、Trade 或歷史事件；交易更正必須使用反向或更正紀錄並保存原因。證據可立即使 Thesis invalidated，不得因尚未完成反思而延遲；但系統必須標示 reflection pending，且 Thesis 關閉前必須完成結果與反思。 |
| REQ-032 | UI 必須同時提供跨公司的工作流程入口與單一公司的公司工作區，兩者使用相同 Server 資料與權限，不得形成兩套紀錄。工作流程入口用於呈現跨公司的待辦與狀態；公司工作區至少整合總覽、Evidence、Thesis、Valuation、Recommendation、Trade、Outcome／Reflection 及 History 等研究脈絡。使用者可由工作流程項目開啟對應公司及內容位置，完成處理後回到工作流程。Server 是正式資料與規則的唯一權威，負責 provenance、E0–E6 推導、Thesis 狀態轉移、估值與風控計算、AI orchestration、Recommendation／Decision／Trade／Outcome／Reflection 保存、audit、通知及授權；UI 負責呈現、收集使用者輸入及提交意圖，不得在 client 端自行作出最終 E 階段、Hard anomaly、估值、風控或權限判定。所有改變狀態的要求都必須由 Server 重新驗證並以一致結果回應不同 UI 入口。 |
| REQ-033 | 工作流程首頁必須提供一個跨公司的統一行動收件匣，只將需要人處理的事項建立為 Action Item，不得把所有系統事件都轉成待辦。Server 必須為需要人工查證的線索、anomaly 審查、失效或過期估值、待決 Recommendation、未完成的交易分配，以及到期的 Outcome／Reflection 建立可追溯 Action Item；使用者亦可建立連結至公司及相關領域紀錄的手動追蹤事項。Action Item 必須保存類型、來源領域紀錄及版本、建立原因、狀態、建立時間、最後變更時間，以及適用時的到期時間；狀態至少包含 pending、in_progress、deferred、completed、dismissed。自動產生規則必須具冪等性，同一觸發條件與來源版本不得產生重複未結項項目。completed 或 dismissed 必須保存操作者、時間及處理理由；dismissed 只結束待辦，不得改寫或隱藏底層 Evidence、anomaly、Thesis、Recommendation、Trade、Outcome、Reflection 或 audit history。所有狀態變更都由 Server 驗證並留下追加式稽核紀錄。 |
| REQ-034 | 行動收件匣首頁必須使用「摘要卡＋優先清單」。摘要卡至少呈現緊急、今日到期、deferred 及全部未結項 Action Item 的數量，並可作為清單篩選入口；清單必須顯示公司／證券、事項類型、簡短原因、狀態、Server 提供的優先級、建立時間及適用時的到期時間，並支援以公司／證券、事項類型、狀態及時間條件搜尋、篩選與排序。摘要數量、清單結果及分頁資訊必須由相同 Server 查詢契約產生，在相同查詢時間點與權限範圍內一致；UI 不得自行重算優先級或以隱藏資料補算摘要。窄畫面必須將摘要卡與清單改為垂直排列，保留核心資訊、篩選及開啟待辦能力，不得要求水平捲動才能完成主要操作。 |
| REQ-035 | 從行動收件匣開啟 Action Item 時，寬畫面必須保留清單脈絡並在右側顯示詳情；窄畫面必須改用可返回原清單位置與查詢條件的完整詳情頁。詳情必須顯示建立原因、公司／證券、來源領域紀錄與版本、必要證據摘要、目前狀態及該類型允許的操作，並提供前往公司工作區相對應 Evidence、Thesis、Valuation、Recommendation、Trade、Outcome／Reflection 或 History 位置的入口。選取的 Action Item 必須反映在可分享及重新載入的應用程式路由中；瀏覽器返回、重新整理、直接開啟連結及寬窄畫面切換不得遺失項目身分、清單搜尋／篩選／排序條件或返回位置。詳情中的狀態及可執行操作必須以 Server 回應為準，UI 不得僅依本地狀態假設操作成功。 |
| REQ-036 | v1 使用單一響應式 Web 應用程式，同一套 React UI 必須支援桌機與手機瀏覽器，並僅能經 REQ-012 定義的 Cloudflare Access 保護 HTTPS 入口連線至 ThesisTrace Server，不要求使用者安裝 VPN、WARP 或其他 device client。v1 不提供原生 iOS／Android／desktop App、不宣稱可安裝 PWA，也不支援離線讀取或離線寫入領域資料。應用程式在失去 Server 連線時必須清楚顯示離線狀態、禁止會改變狀態的操作且不得排隊等待稍後自動提交；恢復連線後必須重新從 Server 取得 Access identity、應用程式授權、目前版本及狀態。敏感 API 回應與 HTML 不得由 service worker、application cache 或其他應用程式控制的持久離線快取保存；靜態版本化資產可依部署政策快取，但不得包含使用者或投資資料。 |
| REQ-037 | 每個 Action Item 必須由 Server 的版本化 deterministic policy 指定 system_priority，採 critical、high、normal、low 四級，並保存命中的規則 ID、規則版本及可顯示原因；AI 輸出不得直接設定或修改 system_priority。Owner 可對非 safety-locked 項目設定 owner_priority override，調高或調低其個人收件匣排序，但必須保存原 system_priority、調整後優先級、理由、操作者及時間，且不得改寫其他使用者視圖或歷史政策結果。safety-locked 項目不得被 Owner、UI 或 AI 降低至 policy 指定的最低優先級以下；其確切項目類型另行明定。清單有效優先級必須由 Server 根據 system_priority、有效 owner override 及 safety floor 計算並回傳；政策或 override 變更後必須以新版本重新評估仍未結項的項目、保留前後結果及原因，不得改寫已完成／dismissed 項目的歷史排序。相同有效優先級的預設次序依到期時間升冪、建立時間升冪及穩定 ID 排序。 |
| REQ-038 | safety-locked Action Item 類型及最低優先級必須固定如下：(a) 已形成的 Hard anomaly，以及 A/B 證據更正、撤銷或失效導致 active Thesis 的 E 階段降級或 Thesis invalidated，最低為 critical；(b) 使用者已確認實際成交但交易尚未成功匯入、對帳不一致、成交股數未完整分配或分配違反持有量，以及缺少／失效的持股、可投資現金或官方價格使 REQ-006 風控無法正確計算，最低為 high。只有對應底層狀況經 Server 規則判定已解決、被較新有效紀錄 supersede，或原觸發經可稽核更正證明不存在時，才可移除 safety lock；優先級 policy 重新發布或 Owner override 不得單獨解除。其他自動或手動 Action Item 不得因來源為 Server 而自動 safety-lock，仍依 REQ-037 允許 Owner 調整。 |
| REQ-039 | v1 Action Item 採私人系統的自動歸屬，不提供領取、共用待辦池、關注者或人工轉派功能。投資組合、個人化 Recommendation、交易、曝險及 Owner Thesis 的 Action Item 必須歸屬該資料 Owner；Learner 只能收到並處理自己建立之 Thesis、Outcome／Reflection 及其可存取共享證據所衍生的個人待辦；服務狀態、郵件、採集、備份還原與帳號營運待辦歸屬部署時指定且同時間唯一啟用的 primary Admin。Server 必須在建立待辦前依資料 ownership 與角色授權決定 assignee_user_id，不得接受 client 或 AI 指定。找不到唯一合法 assignee 時必須 fail closed，保存 unassigned operational exception 並向 primary Admin 的可用營運告警通道報告，不得把內容顯示給其他帳號。停權或變更 primary Admin 時，未結項營運待辦由 Server 以可稽核交易重新歸屬新的 primary Admin；其他使用者資料待辦不得因停權自動轉交他人。 |
| REQ-040 | safety-locked Action Item 只允許 pending、in_progress，以及由 Server 驗證底層條件已依 REQ-038 解決後形成的 completed；任何 defer、dismiss 或未經底層驗證的直接 complete 要求都必須拒絕。標記 in_progress 只表示 Owner 正在處理，不得降低優先級、從未結項摘要移除或解除 safety lock。非 safety-locked Action Item 可由合法 assignee 設為 deferred，必須提供未來的 defer_until，並保存適用時的理由；到達 defer_until 時由 Server 冪等地轉回 pending。合法 assignee 可 dismiss 非安全項目，但必須提供理由；dismissed 只終止該 Action Item，不得更動來源領域紀錄。若 deferred 項目的來源版本在 defer_until 前出現會提高 system_priority 或改變必要處理內容的 material change，Server 必須立即取消延後並轉回 pending。所有轉移使用 Server time、版本檢查與 append-only audit；重複請求不得造成重複轉移或通知。completed／dismissed 後出現新來源版本時的重開或新建規則另行明定。 |
| REQ-041 | completed 或 dismissed Action Item 必須保持終結且不可因後續事件改回未結項。若較新的來源版本、再次發生的底層條件或新的 material evidence 依同一 deterministic creation rule 仍需要人處理，Server 必須建立具有新 ID、建立時間、來源版本及 priority evaluation 的新 Action Item，並以 recurrence_of 或 continues 關係連結最相關的既有終結項目；不得把新證據附加成改寫舊項目的建立原因或處理結果。相同來源版本及相同觸發 fingerprint 的重送不得建立新項目；只有來源版本號變更但內容 fingerprint 與處理需求均未改變時也不得建立。新項目必須重新執行 ownership、priority、safety lock 及通知規則，不得繼承舊項目的 dismissed、deferred、owner override 或處理中狀態。UI 必須可從新項目查看關聯舊項目的終結狀態、理由及時間，但舊項目內容仍受原權限控制。 |
| REQ-042 | 公司工作區必須以角色過濾的 Overview 為預設頁，並提供可直接以應用程式路由開啟的 Evidence、Theses、Valuation、Recommendations、Trades、Outcomes／Reflections 及 History 分頁。所有分頁共用一個固定公司標頭，至少顯示公司名稱、證券代號、市場、目前 E 階段及其 as-of／來源狀態、目前使用者可見的 active Thesis 狀態，以及該使用者未結項 critical／high Action Item；Owner 才可看到個人持倉、security exposure、industry/theme exposure、個人化 Recommendation 與交易摘要，Learner／Admin 的 response payload 與 UI 都不得包含這些欄位。Overview 必須摘要目前可見的 Evidence freshness、Thesis、valuation validity、Recommendation status、持倉／曝險（Owner only）及待辦，並以可追溯連結開啟對應分頁與 record/version。直接開啟分頁、重新整理及瀏覽器返回／前進必須保持公司與分頁身分；不存在或無權存取的公司／分頁／紀錄必須使用不洩漏存在性的拒絕行為。窄畫面可將分頁轉為可捲動導覽或選單，但不得改變資料權限或缺少任何允許功能。 |
| REQ-043 | 公司可同時具有零至多個彼此獨立的 Thesis；Overview 與 Theses 分頁必須以各自可路由的 Thesis 卡片呈現，不得指定隱含 primary Thesis，也不得自動合併為公司綜合 Thesis。每張卡片至少顯示 Thesis 標題、Owner、狀態、建立／最後變更時間、相關 Evidence Chain 與目前 E 階段、預先定義的 invalidation condition 摘要、valuation method／target date／validity、最新 Recommendation version／Owner Decision，以及 Owner 可見的分配持股、Outcome／Reflection 狀態。不同 Thesis 的假設、evidence relevance、valuation inputs、Recommendation、Decision、交易分配、Outcome 與 Reflection 必須分開保存和查詢；同一 Evidence record 可用關聯表連結多個 Thesis，但不得複製或改寫來源紀錄。公司標頭的持股、security exposure、industry/theme exposure 及重大 Action Items 必須合併該證券所有 Thesis 與 independent bucket；彙總值不得回填到單一 Thesis 卡片或用來合併其績效。角色權限必須先由 Server 過濾卡片及欄位，再計算可見數量與摘要。 |
| REQ-044 | Evidence 分頁必須以 Evidence Chain 為第一層，每條 chain 顯示主題／事件、目前 E0–E6 階段、來源可信度／產品成熟度／商業化／財務影響／延續性維度、freshness、anomaly 狀態、相關 Thesis 數量及最後更新時間；可依 E 階段、A／B／C 來源層級、freshness、有效／更正／撤銷／失效及 anomaly 狀態搜尋、篩選與排序。展開 chain 後必須以事件時間為主、觀測／取得時間為輔顯示來源與階段演進時間軸；每一節點至少顯示來源層級、發布者、來源 URL、必要摘錄、發布／事件／取得時間、access status、content hash、與其他來源的底層 lineage／independence，以及該來源支持、反駁、更正、撤銷或失效的事實。deterministic stage transition 必須以獨立節點顯示前後階段、命中／未命中的 gate、policy version、reason 及 source snapshot；AI 候選事實及 critic 結果必須標示為衍生分析，不得與 source-of-record 混同。窄畫面必須保持 chain→timeline 的階層及來源可追溯性，不得只顯示無來源的摘要。 |
| REQ-045 | v1 的 React Web、FastAPI API、採集／AI／郵件 workers、PostgreSQL、durable queue／outbox 及主要領域資料必須部署並持久化於使用者管理的本地 Linux Server VM。非 VPN 的遠端入口供應商只可提供連線代理、TLS／edge protection 及適用時的外層身分閘門，不得託管 ThesisTrace application runtime、主要 PostgreSQL、領域資料副本、離線快取或備份；供應商不可用時本地服務與資料必須保持完整，但遠端入口可明確失敗。API 不得為雲端前端提供繞過既定入口的長連線資料庫通道；所有遠端請求仍須經相同 Server authentication、authorization、RLS、audit 與 fail-closed 規則。備份依 REQ-013 例外允許加密後上傳 Backblaze B2。 |
| REQ-046 | Owner 的 Cloudflare account 備援 Allow policy 必須預設停用，且不得出現在一般登入選項。只有在 Google identity provider 無法使用或必須修復主要 identity 設定時，Owner 才能從 Cloudflare 管理介面以該 Cloudflare account 及 MFA 手動啟用；不得建立自動啟用、公開 Bypass、共用帳號、第二位 account member 或本地免驗證入口。備援 policy 必須要求每次登入重新完成 MFA，Access session 最長 30 分鐘，FastAPI 只能把該 provider identity 對應至既有的同一 Owner user ID，權限不得提升。首次成功進入 ThesisTrace 時必須建立含 provider、時間及 recovery reason 的不可修改 security audit event 與要求關閉備援的 safety-locked Action Item；修復主要登入後必須立即停用備援 policy，記錄停用確認，並使所有備援 ThesisTrace sessions 失效。Cloudflare account 的 MFA recovery material 必須安全保存於 Server VM、Git repository 與主要 Google identity 之外；若管理登入或 recovery material 皆不可用，系統必須維持 fail closed，不得以公開 origin 或繞過 Access 恢復。 |
| REQ-047 | Action Item 必須採混合處理流程。桌機右側詳情面板、手機全頁詳情可顯示來源、原因、證據摘要、歷史及允許的待辦層級操作；待辦層級操作包括開始處理、非 safety-locked 項目的延後／忽略、Owner priority override，以及在不改變底層領域紀錄時完成手動追蹤項目並填寫理由。任何會建立或改變 Evidence 評分／確認、anomaly 判定、Thesis 狀態、Valuation 假設或結果、Recommendation／Owner Decision、Trade／allocation、Outcome 或 Reflection 的操作，必須從詳情開啟同一公司的正確工作區頁籤及目標 record/version，不得把縮減版領域表單塞入待辦面板。導覽必須攜帶 return context，至少包含收件匣查詢、篩選、排序、分頁或游標、捲動位置及原 Action Item；完成或取消後返回原位置，重新向 Server 取得該待辦與摘要計數，若待辦已結束則從未結項清單移除並清楚顯示結果。直接進入公司工作區與由待辦進入必須操作相同領域 record；Server 必須以版本或等效 optimistic concurrency 阻擋過期提交。 |
| REQ-048 | 寫入操作必須依風險分級。一般草稿、筆記與尚未發布的估值假設可直接儲存，但仍須通過權限、欄位驗證、optimistic concurrency 與 audit。下列 consequential action 必須使用 Server 驗證的兩步確認：發布會供 Recommendation 使用的 Valuation snapshot；接受或拒絕 Recommendation；確認交易匯入、allocation 或交易更正；使 Thesis invalidated、closed 或重新啟用；確認 Hard anomaly 已讀或套用其失效／賣出處置；以及新增、停用、替換 identity 或變更使用者角色。第一步必須由 Server 依目前資料產生清楚的人類可讀影響摘要，至少列出公司／證券、動作、目標 record/version、重要前後差異、關聯 Recommendation／Thesis／Trade、風控或不可逆效果；第二步要求授權使用者填寫非空白理由並明確確認。Server 必須發出單次使用、最長 5 分鐘且綁定 actor、action type、target version 與 payload digest 的 confirmation challenge；confirm 時重新驗證角色、資料版本、challenge 與 payload，任一變更或逾期都必須拒絕並要求重新預覽。成功後必須在同一交易中寫入領域變更、理由、confirmation metadata 與 append-only audit；重送不得重複執行。UI 確認視窗不得用預先勾選、模糊的「確定」文字或把取消設為不易發現；一般低風險寫入不得濫用此確認流程。 |
| REQ-049 | 公司工作區必須採混合儲存。只有長文字型的未發布草稿欄位可自動儲存，包括 Thesis narrative／notes、一般研究筆記及尚未完成的 Reflection 文字；Evidence 來源或評分、E 階段、Valuation 輸入與結果、Recommendation／Decision、Trade／allocation、Outcome 結果欄位、Thesis 或 Action Item 狀態、角色與 identity 均不得自動提交，必須使用明確的儲存或 REQ-048 確認流程。長文字在使用者停止輸入 2 秒後可送出 autosave，且 UI 必須持續顯示未儲存、儲存中、已儲存時間、失敗或版本衝突之一；不得在尚未得到 Server 成功回應時顯示已儲存。Autosave 必須攜帶 expected version 與 idempotency key；Server 每次接受後建立可追溯 draft revision，但不得把 draft 視為已發布領域狀態。若網路中斷，UI 可在目前頁面的 volatile memory 保留未送出文字並顯示失敗，但不得寫入 localStorage、IndexedDB、service worker queue 或稍後自動背景提交；恢復連線後必須由使用者明確重試。發生版本衝突時必須停止該欄位後續 autosave，保留使用者文字並提供比較、複製或重新載入，不得覆寫 Server 版本。離開頁面前若仍有未完成／失敗 autosave 必須警告；正在送出的請求可在 bounded completion 後導覽，逾時則視為未儲存。發布或將草稿用於估值、建議及其他正式流程仍須明確動作。 |
| REQ-050 | Email 通知可包含公司名稱及／或股票代號與 Action Item 類型，並可包含待辦優先級、產生時間及一般性動作提示；不得包含 Evidence 標題或摘要、來源 URL、Thesis 內容、E 階段細節、Hard anomaly 證據或判斷內容、Valuation 輸入／結果、Recommendation 買賣方向或數量、Owner Decision、Trade／allocation、持股、曝險、資產、金額、報酬、Outcome／Reflection 內容、使用者角色、Access／session／reset token 或任何秘密。郵件必須由版本化的結構化 allowlist template 產生，不得把 AI 生成文字或任意領域欄位直接插入 subject、preheader、text 或 HTML；無法安全映射時退化為一般提醒。每封只能寄給在 queue 建立時及實際寄送時都仍有權查看該 Action Item 的單一收件者，不得使用 CC、BCC 或群組地址。連結只能是 Access 保護 hostname 上帶 opaque Action Item ID 的 HTTPS deep link，不得把公司、類型、資料內容或 authentication token 放入 URL；開啟後仍須通過 REQ-008、REQ-012 與應用程式授權。郵件不得含附件、外部圖片、tracking pixel 或第三方分析資源；投遞日誌只能保存 template/version、事件與 Action Item ID、收件者不可逆識別、狀態與 provider message ID，不得保存完整 body。 |
| REQ-051 | 官方來源 freshness 是軟體 SLO，不是 CPU 即時或硬體保證。每個 eligible official event 的計時起點優先使用來源提供且通過合理性驗證的 publication timestamp；若來源沒有可靠 timestamp，使用第一次成功取得且回應內容已包含該事件的觀測時間，並標示 measurement basis。完成時間是 Server transaction 已提交 canonical Evidence、provenance、去重鍵與必要的 deterministic Action Item 或後續分析 durable job 的時間；不得以收到 HTTP response、開始處理或只存在記憶體佇列視為完成。以 UTC rolling 30 days 計算，在來源可正常取得的 eligible events 中至少 95% 必須在 10 分鐘內完成、至少 99% 必須在 30 分鐘內完成，報表必須同時顯示分子、分母、各分位數及 measurement basis。預定輪詢時來源連線失敗、限流或回傳不可解析服務錯誤的區間列為 external-source outage，不納入 reachable-event 百分比，但必須獨立記錄 outage duration、受影響來源、未處理 backlog 及恢復時間；來源恢復後，無可靠 publication timestamp 的 backlog 從第一個成功含事件回應開始計時。任何 reachable event 超過 30 分鐘、排程連續錯過兩個五分鐘週期或 outage 恢復後 backlog 未持續清空，都必須建立營運 Action Item；事件不得因超時而丟棄或跳過 provenance、去重、授權及 audit。發布前以至少 100 個含邊界延遲、worker 壅塞、重啟、重複事件與來源故障的 deterministic fixture events 驗證門檻；上線後相同定義持續量測。 |
| REQ-052 | Claude 在通過資格閘門前不得接收正式 failover 流量。資格資料集必須版本化並至少包含 30 個由 Owner 核准預期結果的代表案例，涵蓋 A／B／C 來源、獨立性、正反例、abstain、引用缺漏、schema 錯誤、Hard／Soft anomaly、Thesis 影響與 RecommendationCritic；Claude 對 decision-critical structured fields 至少 29／30 與預期一致，且不得有任何 safety-critical discrepancy、錯誤 Hard anomaly、錯誤引用、無來源主張、schema／policy violation 或應 abstain 而未 abstain。離線案例通過後，必須完成連續 10 個 production shadow tasks；一個 shadow task 是同一個 production-eligible immutable input snapshot、prompt、policy 與 schema version 先由主 provider 處理，再由 Claude 獨立重跑，Claude 結果只比較不影響任何正式 Recommendation、Action Item、E 階段或通知。十個 shadow tasks 的 decision-critical fields 不得有 major discrepancy，且所有 safety、citation、schema 與 critic gates 必須 100% 通過；任何失敗都把連續計數歸零。Owner 必須以不可修改 approval record 核准 dataset version、Claude model/version、prompt、policy、schema、結果與日期後才可啟用。自動切換只允許在 OpenAI provider-wide circuit breaker 依版本化 retry／health policy 開啟時發生，不得因單一 timeout、內容不合格、schema 錯誤、critic 拒絕或個別 rate limit 直接切換；每個 job 必須以相同來源快照從頭重跑，不得混合兩個 provider 的部分輸出。Claude 任一輸出未通過 deterministic schema、citation、source、policy、risk、abstain 或 critic validation 時不得發布，必須建立人工 Action Item。OpenAI 恢復且 circuit breaker 關閉後新 job 回到 OpenAI，既有 job 不得在執行中切回。Claude model、prompt、decision-critical schema、policy 或 critic gate 有 material change 時核准自動失效，必須重新完成 30 案例、10 次 shadow 與 Owner approval。 |

| REQ-053 | v1 的共用 React UI 必須使用語意化 HTML5 與 mobile-first 響應式設計，採 Tailwind CSS、Radix Primitives 及 project-owned shared UI wrappers；feature modules 不得直接散佈 Radix imports 或硬編碼主題色。原生 viewport 360–2560 CSS px 的主要流程不得出現 page-level horizontal scrolling、內容／控制項重疊、必要內容截斷或不可達操作；1280 CSS px viewport 在 400% browser zoom 時必須 reflow 至相當於 320 CSS px，並完整符合 WCAG 2.2 AA，包括鍵盤、focus、語意、錯誤識別、非僅依色彩、對比、target size 與 200% 文字放大。多欄研究資料在窄畫面使用摘要加完整詳情；只有意義確實需要二維比較的局部語意化容器可水平捲動，全部授權欄位仍須可達且共用同一 Server record/version。視覺採現代專業研究工作台、Slate 中性基底與 Blue／Indigo 互動強調色、單一自動調整的平衡密度；同時支援 light、dark、system，主題偏好以 system/light/dark 保存於 Server 使用者設定。台灣市場方向為紅漲、綠跌、持平中性且必須搭配符號／文字／accessible name，並與 application success/error/safety tokens 分離。字型只使用各裝置 system UI／繁體中文 fallback，金融數字使用 tabular numerals，不得從第三方載入字型。正式支援 current 與 previous major 的 Windows／Linux Chrome、Edge、Android Chrome，以及 current 與 previous iOS／iPadOS major 的 Safari；Firefox 與 macOS Safari 僅 best effort 並顯示非阻斷未驗證提示。 |

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
| DEC-021 | 證據模型採固定 E0 至 E6 摘要階梯與多維度狀態並存；E 階段由多維資料推導，不取代原始維度。 | 保留跨公司可比較、可通知的共同語言，同時避免單一階段掩蓋來源、產品、商業化、財務與延續性差異。 |
| DEC-022 | E0 至 E6 採 deterministic 逐級閘門；來源失效時重算，AI 不具階段寫入權限。 | 確保分類可解釋、可重現、可回測並能 fail closed；產業差異以明確補充規則處理，不以不透明加權抵銷必要證據。 |
| DEC-023 | 研究閉環採明確狀態機、正常化目前狀態及 append-only audit events，不採自由關聯圖或只實作部分閉環。 | 讓每次建議、使用者決定、交易、結果與反思可追溯，同時避免完整 Event Sourcing 的額外複雜度。 |
| DEC-024 | 估值方法由 Owner 對每個 Thesis 明確選擇 PE、PB 或 abstain；AI 僅提供候選方法與來源。 | 保持估值責任透明且可追溯，避免產業映射或 AI 在未確認的情況下決定核心估值方法。 |
| DEC-025 | Owner 可為每個 Thesis 選擇 6、12 或 24 個日曆月估值期間，預設 12 個月；預測輸入最長 90 天並受新財報與重大事件提前失效。 | 讓短期催化、一般基本面與長期轉型使用適合的目標期間，同時以明確 target date 和年化報酬維持可比較性。 |
| DEC-026 | target PE/PB 同時支援公司自身歷史分布及 Owner 管理的 peer group 比較，兩組資料及假設均需獨立保存。 | 歷史分布提供可重現的公司自身基準，peer group 則支援新公司、轉型或歷史結構已改變的情境。 |
| DEC-027 | 公司歷史與 peer group 估值分開呈現；Owner 對每個 Recommendation 選擇其中一項或 abstain，系統不得自動混合。 | 保留兩種模型各自的經濟意義與完整計算鏈，避免無依據的權重或保守取低掩蓋模型差異。 |
| DEC-028 | peer group 由 Owner 確認並版本化 5 至 12 家台灣上市櫃可比公司；少於 5 家有效同業時不得使用 peer-group 估值。 | 限制樣本選擇偏誤並確保中位數與百分位具有最低可用樣本，同時保持 v1 市場與幣別一致。 |
| DEC-029 | 年化淨總報酬扣除版本化券商買賣手續費、最低手續費與證券交易稅，但不估算個人綜合所得稅或補充保費。 | 取得可重現且接近實際交易的報酬，同時避免保存及錯估高度個人化的年度所得資料。 |
| DEC-030 | 證券與產業曝險以 Recommendation 當下的持股官方收盤市值加 Owner 維護可投資現金形成 Portfolio NAV，並以建議交易後快照計算。 | 讓限制反映實際持股、價格變化與可用資金，而不是固定本金或忽略現金的持股比例。 |
| DEC-031 | 單一證券 10% 與單一產業 30% 為不可覆寫 hard cap；DCA 倍率向下限制至最高可行值，現有超限部位禁止追加但不觸發自動賣出。 | 確保風控在追價或高信心情境仍有效，且所有結果可由 deterministic code 重現。 |
| DEC-032 | 產業 hard cap 同時計算官方 TWSE／TPEx 主要產業與 Owner 版本化自訂風險主題，任一分類結果超限即阻擋買進。 | 以官方分類維持客觀基準，並以自訂主題捕捉供應鏈、技術或題材造成的跨官方產業集中風險。 |
| DEC-033 | 每筆成交股數由 Owner 明確分配至一個或多個 active Thesis 或 independent decision 桶，賣出亦指定扣減桶；風控仍按證券合併。 | 同時保留多重投資理由的績效歸因與整體曝險正確性，避免自動 FIFO 扭曲實際決策理由。 |
| DEC-034 | anomaly 採 A/B/C 固定來源層級與可解釋線索評分並存；評分狀態不得抹除原始來源或把相同底層消息誤算為獨立來源。 | 固定層級提供安全證據門檻，評分則協助排序大量未驗證線索及人工檢查工作。 |
| DEC-035 | 線索評分僅控制人工檢查、觀察與保存優先級，無論分數多高都不得升格來源或參與 Hard-anomaly quorum。 | 防止大量具體但未證實的訊息或同源轉載累積成退出建議。 |
| DEC-036 | Hard anomaly 需要一項直接 A 級證據，或兩項底層證據真正獨立的 B 級來源，並通過 strict structured critic；任何不確定性 fail closed 為 Soft。 | 延續明確證據邊界並防止同源媒體回音、引用錯配或模型失敗觸發退出建議。 |
| DEC-037 | Hard anomaly 發布閘門為版本化 100 案例零誤判驗收，加上正式 Linux Server VM 連續 30 天 shadow mode；false Hard 重置觀察期。 | 以可重現案例證明 deterministic 邊界，再用真實來源與正式資源條件捕捉資料、模型及整合問題。 |
| DEC-038 | SPEC-0001 管理 ThesisTrace 軟體功能、資料、安全行為與軟體 SLO；Proxmox、VM CPU／RAM／磁碟配置及硬體容量驗證由 SPEC-0002 與 runtime validation profile 管理。 | 防止軟體功能訪談被基礎設施容量決策阻塞，同時保留跨規格的部署與驗證責任。 |
| DEC-039 | 先確認 Server 能力、UI 工作流程與敏感操作，再決定登入及 session 實作；既有 Magic Link 提案暫不視為最終決定。 | 驗證方式與重新驗證邊界應由實際使用流程導出，避免先選登入技術後限制產品操作。 |
| DEC-040 | UI 採「工作流程＋公司工作區」的混合導覽；工作流程回答目前應處理什麼，公司工作區保存並呈現單一公司的完整研究脈絡。 | 同時支援跨公司的每日處理效率與公司層級的長期研究可追溯性，且不複製資料或商業規則。 |
| DEC-041 | 工作流程首頁採統一行動收件匣，由 Server 自動建立需要人工處理的事項，並允許使用者建立手動追蹤事項；一般資訊事件只保留在活動或歷史紀錄。 | 避免重要決策被大量事件淹沒，同時讓跨公司的未完成工作具有一致狀態、回到公司脈絡的連結及完整稽核紀錄。 |
| DEC-042 | 行動收件匣首頁採摘要卡與可搜尋、篩選、排序的優先清單，而不採看板或純表格作為主要介面。 | 在維持高資訊密度的同時突出緊急與到期工作，並能在窄畫面維持主要操作。 |
| DEC-043 | Action Item 在寬畫面使用保留清單脈絡的右側詳情，在窄畫面使用可返回原清單狀態的完整詳情頁；複雜研究則從詳情進入公司工作區。 | 兼顧連續處理多項待辦的效率、窄畫面可用性、可重載的深層連結及完整研究脈絡。 |
| DEC-044 | v1 只交付 VPN-only 響應式 Web 應用程式；原生 App、PWA 安裝與離線領域資料能力均不在 v1 範圍。 | 以一套 UI 覆蓋桌機與手機，降低私人小規模系統的開發、發布及版本維護成本，並避免敏感投資資料的離線同步複雜度。 |
| DEC-045 | Action Item 優先順序由 Server deterministic policy 提供可解釋的預設值；Owner 可調整非安全項目的個人排序，但安全項目具有不可降低的最低優先級，AI 不具排序決定權。 | 同時維持一致且可測試的風險排序，以及 Owner 對一般研究工作的個人控制，並防止模型或人工操作壓低重大事項。 |
| DEC-046 | safety lock 涵蓋 Hard anomaly、使 active Thesis 降級／失效的證據品質事件、已成交交易匯入／對帳／分配異常，以及使風控不可計算的持股、現金或官方價格資料失效；前兩類最低 critical，後兩類最低 high。 | 將不可降低的排序集中在投資風險與投資組合完整性，同時保留一般研究、估值及反思工作的人工排序彈性。 |
| DEC-047 | v1 依資料 ownership 與角色自動歸屬 Action Item，不提供多人領取、關注或轉派；營運事項固定給唯一 primary Admin。 | ThesisTrace 是私人系統，不需要團隊工作分派；移除協作功能可簡化 UI、權限、通知與稽核邏輯。 |
| DEC-048 | safety-locked Action Item 不得延後、忽略或人工直接完成，只能保持待處理／處理中直到 Server 驗證底層問題解決；一般項目可延後至指定時間或附理由忽略。 | 防止重大風險與資料完整性問題從收件匣消失，同時保留一般研究工作的排程與清理彈性。 |
| DEC-049 | 終結後出現需處理的新證據時建立新 Action Item 並連結舊項目，不重新開啟或改寫舊項目；無實質變化的重送不建立。 | 每次待辦保存獨立的觸發證據、處理過程與結果，同時透過 recurrence／continuation 關係維持問題脈絡及去重。 |
| DEC-050 | 公司工作區預設使用角色過濾的公司 Overview，並以 Evidence、Theses、Valuation、Recommendations、Trades、Outcomes／Reflections、History 等可路由分頁提供完整脈絡。 | 讓使用者先看目前狀態與重大待辦，再按任務進入完整資料；同時保持桌機／手機導覽與深層連結一致。 |
| DEC-051 | 同一公司的多個 Thesis 以獨立卡片及完整獨立鏈呈現；公司層級只彙總全部 allocation bucket 的持股與風控，不建立 primary 或綜合 Thesis。 | 保留不同投資理由、失效條件、估值、建議及績效歸因，同時維持證券與產業曝險的整體正確性。 |
| DEC-052 | Evidence 分頁以 Evidence Chain 與 E 階段／多維摘要為第一層，展開後使用保留事件時間、觀測時間、來源 lineage 及 deterministic stage transition 的來源時間軸。 | 同時支援快速辨識目前成熟度與完整查核每一來源如何形成、修正或撤銷階段判定。 |
| DEC-053 | v1 的 Web、API、workers、PostgreSQL 與領域資料保留在本地 Linux Server VM；遠端服務只提供入口與外層保護，不把應用程式或資料庫搬到 VPS／雲端。 | 延續本地資料控制、既有 VM 與備份設計，避免雲端 API 與家中資料庫之間新增長期資料通道及雙重營運邊界。 |
| DEC-054 | v1 使用 Cloudflare Tunnel public hostname 加 Cloudflare Access 作為唯一一般使用者遠端入口，不使用 WireGuard、WARP、Tailscale Funnel、ngrok 或公開 Caddy origin。 | 在保留本地 Server／PostgreSQL 的前提下，讓桌機與手機直接以瀏覽器存取且不開放家中入站 port；Access 提供外層 identity gate，ThesisTrace 仍執行內層角色與資料授權。 |
| DEC-055 | v1 使用 Google 帳號作為逐一核准使用者的主要 Cloudflare Access identity，並只為 Owner 保留 Cloudflare account identity 作為緊急備援。 | 一般使用者沿用熟悉的 Google 登入；獨立的 Owner 備援可在 Google identity provider 不可用時維持恢復入口，同時避免把 Cloudflare account membership 當成一般應用程式授權。 |
| DEC-056 | 一般 Google Access session 固定為 8 小時，session 到期後下一次使用必須重新通過 Google identity 與 Access MFA。 | 將一般使用情境控制在約一個工作日內，同時避免一小時方案的頻繁登入與 Cloudflare 預設 24 小時方案的較長暴露時間。 |
| DEC-057 | Owner Cloudflare 備援 policy 平時停用，只能由 Owner 手動啟用；每次要求 MFA、session 最長 30 分鐘，修復後立即停用。 | 降低第二登入管道長期暴露，同時在 Google identity provider 故障時保留明確且可稽核的恢復程序。 |
| DEC-058 | 待辦採混合完成流程：待辦層級操作留在詳情面板，領域資料變更開啟公司工作區的對應頁籤，完成後返回原收件匣位置。 | 保留快速處理簡單事項的效率，又避免在狹窄面板複製估值、交易及研究狀態等複雜表單與規則。 |
| DEC-059 | 寫入操作採風險分級；一般草稿直接儲存，投資決策、交易確認、重大 Thesis／anomaly 狀態及帳號權限變更使用 Server 綁定資料版本的兩步確認。 | 將額外摩擦集中於錯誤成本較高的操作，並確保確認內容與實際提交完全一致，避免所有寫入都跳出確認而造成習慣性忽略。 |
| DEC-060 | 公司工作區採混合儲存：長文字未發布草稿自動保存，數字、評分、分配、狀態與決策必須明確儲存或確認。 | 降低長篇研究文字遺失風險，同時避免金融數值與正式狀態因誤觸或欄位失焦而直接生效。 |
| DEC-061 | Email 通知採中度揭露：允許公司／股票代號與待辦類型，但禁止投資內容、數值、方向、證據與秘密。 | 讓收件者能判斷是哪家公司及哪類工作，同時把實際研究與資產資訊留在 Access 保護的應用程式內。 |
| DEC-062 | 官方來源 freshness 採 rolling 30-day SLO：reachable events 至少 95% 在 10 分鐘內、99% 在 30 分鐘內完成；外部來源中斷另行量測。 | 對本地 Server 與家用網路保留合理容錯，同時以明確完成點、百分位與遲到告警判定軟體是否及時處理事件。 |
| DEC-063 | 架構治理升級至 schema 2.2.0 並維持 exact 2.1.0 compatibility；原 REQ-015／REQ-016 與 AC-014／AC-015 從產品需求／驗收移至 Engineering Delivery Constraints。 | Git、秘密排除、架構 manifest 與生成視圖仍是強制交付 gate，但不應被誤解為 ThesisTrace 使用者功能或產品行為。 |
| DEC-064 | v1 交付響應式 Web，桌機與手機均經 Cloudflare Tunnel／Access 使用，不要求 VPN／WARP；原生 App、installable PWA 與離線領域資料仍排除。 | 完整取代舊 DEC-044 的 VPN-only 表述，同時保留已確認的單一 Web UI 與無離線資料邊界。 |
| DEC-065 | Gmail API OAuth 只用於 EmailDeliveryPort；使用者登入採逐一核准 Google identity 與 Owner-only Cloudflare 備援，不使用 Email Magic Link。 | 完整取代舊 DEC-008 與登入技術延後決策，將郵件供應商憑證和應用程式使用者驗證分離。 |
| DEC-066 | Claude 只有在 30 個版本化案例、連續 10 個 production shadow tasks 與 Owner 明確核准全部通過後，才可於 OpenAI provider-wide outage 自動備援；任何安全或驗證失敗均 fail closed。 | 以可重現案例、真實輸入比較與人工責任核准控制 provider 差異，同時保留整體供應商中斷時的可用性。 |

| DEC-067 | v1 採用現代專業研究工作台作為共用桌機／手機設計語言：中性基底、克制的狀態強調色、清楚資訊層級、適中資訊密度，以及適合長時間閱讀 Evidence、Thesis、估值與待辦的排版。 | 研究與決策工作需要兼顧可讀性、資訊密度及手機重排；不採高密度交易終端或大留白消費型卡片作為主要風格。 |

| DEC-068 | 響應式版面以 360 至 2560 CSS px 為連續驗收範圍；在此範圍內主要流程必須可操作，頁面本身不得產生水平捲動，版面不得重疊、截斷必要內容或把必要操作移出可達範圍。 | 涵蓋一般手機、平板、筆電、桌機與寬螢幕，並以可量測的 viewport envelope 取代只宣稱支援 HTML5 或特定裝置型號。 |

| DEC-069 | UI 必須同時提供明亮與深色主題，首次使用預設跟隨作業系統 prefers-color-scheme，並提供可由使用者手動切換的控制；所有狀態色、圖表、表單、Focus、disabled、error 及文字層級在兩種主題均須保持可辨識。 | 兼顧白天、夜間及不同裝置使用環境；接受雙主題帶來的設計 token、視覺回歸及對比驗證成本。 |

| DEC-070 | 每個應用程式使用者的主題偏好以 system、light、dark 三值保存於 Server 使用者設定並同步至 PostgreSQL；新使用者預設 system，跨桌機與手機登入時沿用同一偏好，選擇 system 時仍依當前裝置 prefers-color-scheme 呈現。 | 提供跨裝置一致性，同時保留每台裝置的系統主題能力；主題偏好是非敏感 UI 設定，不得與角色、權限或投資資料混用。 |

| DEC-071 | 已驗證身分後的完整 React 應用程式必須符合 WCAG 2.2 Level AA，涵蓋鍵盤可操作與無 trap、可見且不被遮蔽的焦點、語意名稱／角色／值、錯誤識別、非僅依色彩傳意、文字與非文字對比、觸控目標，以及 200% 文字放大不遺失內容或功能；在 1280 CSS px viewport 的 400% browser zoom 下，內容必須 reflow 至相當於 320 CSS px，除 WCAG 允許且其意義確實需要二維配置的局部內容外，不得要求雙向捲動。 | 將可讀性、鍵盤操作與縮放穩定性變成可測試的產品契約；原生裝置支援範圍仍為 360–2560 CSS px，320 CSS px 是縮放後的 reflow 驗收，不宣稱原生支援 320px 裝置。 |

| DEC-072 | Evidence、估值、交易、歷史及其他多欄資料在寬畫面可使用語意化完整表格；窄畫面或 zoomed reflow 必須改為摘要列／卡片加可路由完整詳情，摘要保留辨識、狀態、關鍵時間及主要操作，詳情提供全部授權欄位。只有其意義確實需要二維比較的局部表格可在具可見提示、可命名且鍵盤可操作的容器內水平捲動，並保留列／欄標頭關係；頁面本身不得水平捲動，也不得僅因 viewport 較窄而永久隱藏資料。 | 兼顧研究資料完整性、手機操作與 WCAG reflow；摘要與詳情共用相同 Server record/version，不建立第二份資料或分歧計算。 |

| DEC-073 | v1 的正式瀏覽器支援窗口為：(a) Windows／Linux 桌機 Chrome 與 Edge 的目前穩定主要版本及前一主要版本；(b) Android Chrome 的目前穩定主要版本及前一主要版本；(c) iPhone／iPad Safari 所屬目前 iOS／iPadOS 主要版本及前一主要版本。Firefox 與 macOS Safari 可 best effort 使用但不納入發布保證；偵測到不支援瀏覽器時應顯示非阻斷提示，不得偽稱功能已驗證。 | 符合選定的實際桌機與手機範圍，同時限制跨瀏覽器測試成本；仍須以 Chromium 與 WebKit 測試避免 iPhone 相容性被 Chromium 測試掩蓋。 |

| DEC-074 | React UI 採 Tailwind CSS 負責 mobile-first responsive／container-query layout 與 design tokens，採 Radix Primitives 提供 Dialog、Menu、Tabs、Select、Tooltip 等複雜互動的基礎語意、鍵盤與 focus 行為，並由專案在 shared UI 層包裝為自有 Button、FormField、Card、DataSummary 等公開元件。Feature modules 不得直接散佈 Radix import 或硬編碼主題色；明暗主題使用語意 CSS variables／Tailwind tokens。 | 保留現代專業研究工作台的視覺控制，同時重用經過設計的 accessible interaction primitives；以單一包裝層限制供應商耦合並集中 WCAG、響應式與視覺回歸修正。 |

| DEC-075 | 設計系統採 Slate 灰藍中性基底與 Blue／Indigo 主要強調色：背景、surface、border 與文字使用語意化 slate tokens；連結、選取、主要按鈕與 focus 使用 blue／indigo tokens。明亮與深色主題各自定義可驗證對比，不以固定色階值跨主題硬套。主要強調色不得兼作 success、warning、error 或市場方向的唯一訊號。 | 冷中性基底適合長時間研究閱讀，藍／靛藍能清楚表達互動狀態且較不會與紅／綠財務方向混淆；語意 token 允許兩種主題分別達成 WCAG 對比。 |

| DEC-076 | 台灣市場的價格、報酬及明確標示之市場方向採上漲紅、下跌綠、持平中性色；每個方向值必須同時提供正負號與／或 ▲／▼、可讀文字或 accessible name，不能只依顏色。市場方向 tokens 與 application success、warning、error、Hard anomaly 及安全狀態 tokens 分離，禁止以相同顏色單獨推導不同語意。 | 符合台灣市場閱讀習慣，同時以冗餘符號與語意標示滿足辨色及螢幕閱讀需求，避免紅色同時表示上漲與系統錯誤造成無上下文混淆。 |

| DEC-077 | UI 採依可用寬度自動調整的單一平衡密度，不提供使用者密度切換：桌機清單／表格維持適中資訊密度與清楚掃描節奏；手機、觸控及 zoomed layout 自動使用較大的控制項與間距，主要觸控目標以至少 44×44 CSS px 為設計目標且不得低於 WCAG 2.2 AA 要求。密度調整不得改變資料、權限、排序、狀態或可用功能。 | 避免雙主題再乘上多密度造成測試組合膨脹，同時兼顧桌機研究效率與手機觸控；不採交易終端式高密度。 |

| DEC-078 | 繁體中文與一般 UI 文字使用裝置 system UI font stack：Windows 優先使用可用的繁體中文系統字型，Apple 平台使用 PingFang TC 類系統字型，Android 使用裝置 Noto Sans CJK 類系統字型；不得呼叫第三方 font service，也不在 v1 自託管大型 CJK webfont。表格、價格、百分比與對齊比較數字使用 font-variant-numeric: tabular-nums。 | 避免大型中文字型下載、外部依賴與 font-swap layout shift，提升首次載入與隱私；接受不同作業系統字形略有差異，並以固定 typography tokens、行高及跨平台視覺回歸控制版面。 |
| DEC-079 | 後端採適度拆分的模組化單體，正式 L1 領域為 Access、Research、Thesis、Portfolio、Recommendation、Workflow 與 Notification。Research 內含 Catalog、Evidence、Evidence Stage 與 Anomaly；Thesis 內含生命週期、Valuation、Outcome 與 Reflection；Portfolio 內含 Holdings、Trades、Allocation、Exposure 與 Risk Snapshot。Operations、Audit、AI provider、來源 adapter 與郵件 delivery 為 L0/L3 技術能力，不建立為產品領域。所有 L1 模組在同一 FastAPI application 與 PostgreSQL 部署，但各自擁有資料、公開 Ports/Events，不得直接存取其他模組的私有資料表。 | 在私人系統可承擔的結構成本內分離獨立變更的研究、Thesis、資產、建議與工作流程規則；避免每個名詞各自成為淺模組，也避免三個大型模組混合不同責任。 |
| DEC-080 | 跨模組協調採 hybrid model：會影響使用者可見不變量的 command 由 L0 application flow 同步協調，使用明確 Ports、具版本的不可變 snapshot 與單一 PostgreSQL transaction，全部成功後才回覆 UI；通知、AI、採集、projection 等可延後副作用，以同一 transaction 寫入 durable outbox／job，再由隔離 worker 至少一次處理。Consumer 必須具 idempotency key、重試與 dead-letter；模組不得直接呼叫 sibling 內部實作或讀寫其私有資料表。 | 讓決策、交易與分配維持原子一致，同時讓 Gmail、AI 或採集故障不阻塞核心操作；接受必須治理 command、event、snapshot、冪等與重試契約的成本。 |
| DEC-081 | Browser-to-Server 採版本化 JSON HTTP API，由 FastAPI 產生 OpenAPI 並據此產生前端 TypeScript contract types。查詢使用 resource／purpose-built read endpoints；狀態轉移與高風險操作使用明確 command endpoints，不暴露任意欄位 patch。所有 response、validation、authorization、not-found、optimistic concurrency conflict、idempotency 與 retryable failure 使用統一 error envelope 和 machine-readable code；UI 不實作或重算 Server authority 規則。v1 不導入 GraphQL。 | 與 FastAPI、授權稽核、contract testing 及前端型別生成直接配合，並讓金融操作的意圖與失敗可驗證；接受為複合畫面設計少量專用讀取 endpoint，而非讓 client 任意選欄位。 |
| DEC-082 | 單一 PostgreSQL database 以 `access`、`research`、`thesis`、`portfolio`、`recommendation`、`workflow`、`notification` 與 `platform` schemas 建立實體 ownership；前七者各由對應 L1 domain 擁有，`platform` 僅存 outbox、jobs、dead-letter、migration／operational metadata 等技術資料。每個模組 migration 與 repository 必須 schema-qualified，runtime grants 採最小權限；不得以跨 schema 任意 join/write 取代 Ports、Events 或 L0 flow。跨領域 reference 使用穩定 ID 及必要不可變 snapshot，由 application flow 驗證；RLS 與 tenant/user authorization policy 位於資料 owner schema。整體仍作為單一備份、restore 與 transaction boundary。 | 讓 PostgreSQL 可以實際協助檢查資料所有權，同時保留單一資料庫的原子交易、簡單部署與復原；接受 schema-qualified migration、grant 與跨領域 reference 設計成本。 |
| DEC-083 | React frontend 採分離狀態 ownership：Server-owned records 只由集中 query/cache layer 經 generated OpenAPI client 取得；搜尋、篩選、排序、分頁、目前選取與 detail route 由 URL 擁有；未提交表單草稿與暫時互動狀態由 feature/form/component local state 擁有。Feature 不得建立第二份可獨立變更的 Thesis、Recommendation、Portfolio 或 Workflow global domain store；mutation 成功後依 contract 精準 invalidation/refetch，optimistic update 僅限可安全回復的低風險 UI，Server version conflict 必須撤回本地假設並呈現最新 record/version。 | 保持 Server 為唯一金融資料權威，同時讓返回、重新整理、deep link 與 responsive list/detail 導覽可恢復；接受需治理 query keys、cache invalidation 與 draft lifecycle。 |
| DEC-084 | Backend 使用同一個版本化 application image 建立四個獨立 executable/process roles：`api`、`collector-worker`、`ai-worker`、`email-worker`；三種 worker 只訂閱自己的 PostgreSQL job types，重用相同 L0 flows、L1 domain modules、Ports、Events 與 generated contracts，不建立分叉程式碼。Docker Compose 為每個 role 設定獨立 health check、graceful shutdown、CPU／memory、database pool、timeout、retry 與必要 secrets；任一 worker unhealthy、restart 或 resource exhaustion 不得停止 API 或其他 worker。所有 process 必須回報相同 build/version identity，不相容 job payload 必須 fail closed。 | 以單一程式版本避免規則漂移，同時隔離 AI、來源與 Gmail 的延遲、故障、秘密及資源；接受 Compose service、監控與容量設定增加。 |
| DEC-085 | PostgreSQL jobs 採 leased parallel claim：worker 以 row locking／skip-locked 類機制認領到期工作並記錄 owner、lease expiry、attempt、available_at 與 heartbeat；失聯 lease 可安全重新認領。不同 subject key 可並行，同一 company／aggregate／notification recipient 等具衝突風險的工作依明確 concurrency key 序列化。每項 job 保存 input record IDs/versions、policy/model/prompt/build version、idempotency key 與 correlation/causation IDs；提交結果前必須重查版本，stale 結果保存為 superseded evidence 但不得更新 current state 或觸發副作用。重試超限進 dead-letter 並建立可操作告警。 | 在不相關公司間保留吞吐量，同時防止舊 AI、重複 delivery 或重新啟動後的 job 覆蓋較新狀態；接受 lease、heartbeat、concurrency key 與 stale-result 測試成本。 |
| DEC-086 | 領域 persistence 採 relational current state 加 append-only domain/audit history，不採 full event sourcing。每個 command 在同一 PostgreSQL transaction 中更新 owner schema 的 current-state row／version、附加具 actor、occurred_at、reason、before/after reference、correlation/causation、policy/build version 的 immutable event，並在需要背景副作用時新增 outbox。歷史 event 不得 update/delete；更正、撤銷與公司行動以新 event 和新 current version 表示。Current state 是 UI 與規則判定的查詢權威，history 是追溯與驗證權威，但一般 restore 不要求由零 replay 全部事件才能啟動。 | 同時取得直接 SQL constraint／高效率目前狀態查詢與可靠因果歷史，避免 full event sourcing 的 projection、schema evolution 與 replay 複雜度；接受所有 modifying flow 都必須原子寫入 history 的成本。 |
| DEC-087 | Repository 採 domain/feature-first vertical organization。Backend 以 `bootstrap`、`entrypoints`、L0 `application/flows`、`modules/{access,research,thesis,portfolio,recommendation,workflow,notification}` 與 `platform` 為頂層；每個 L1 module 只在需要時建立 `domain`、`application`、`ports`、`infrastructure`、`api` L2/L3 子目錄，不建立全域 controllers/services/models/repositories dumping grounds。Frontend 以 `app`、`routes`、`features`、`shared` 組織，feature 名稱映射使用者能力與後端 contract。跨領域 orchestration 只在 L0 flows；shared/kernel 僅允許無領域所有權的 primitives，新增 shared abstraction 必須有至少兩個實際 consumer 並通過 architecture review。 | 讓檔案位置直接表達 ownership、依賴方向與變更原因，便於架構工具與測試檢查；接受各 feature 重複少量明確模板，以避免錯誤共用。 |
| DEC-088 | Python persistence 採 SQLAlchemy 2 typed ORM/Core hybrid、Alembic migrations 與 Psycopg driver，使用 request/job-scoped synchronous Session／Unit of Work。一般 aggregate/current-state persistence 使用 owner module 的 typed ORM mapping；queue claim、locking、bulk/reporting 與 PostgreSQL-specific constraints 可在同一 repository boundary 使用 SQLAlchemy Core 或審查過的參數化 SQL。每個 API command 或 worker job 明確 begin/commit/rollback 並立即釋放 session；不得跨 thread/task 共用 session，也不得在等待 AI、Gmail、來源 HTTP 或其他長時間 I/O 時保持 transaction。Alembic revisions 必須標示 owner schema、可在空資料庫及 production-like snapshot 驗證 forward migration，且 production deploy 不自動執行 destructive downgrade。 | 以成熟 typed mapping、明確 SQL 與可重現 migration 平衡領域維護性和 PostgreSQL 控制；最多 10 位使用者與隔離 worker 尚無全面 async database stack 的負載證據，選擇較易驗證的同步 transaction lifetime。 |
| DEC-089 | E-stage、Hard anomaly、valuation、return、exposure/sizing 與 Workflow priority 以各 owner module 內的 explicit pure policy functions 實作，不導入 generic rules engine/DSL。每個 policy 接受 typed immutable input snapshot 與 policy version，回傳 typed result、abstain/error reason 及逐條 structured decision trace；不得讀取 clock、database、network、environment 或 mutable global state，時間與市場資料必須作為明確輸入。AI output 只能經 adapter/critic/schema validation 成為候選輸入，不能直接設定 policy result。每個演算法必須在實作前建立 Algorithm Design Record，包含公式、優先順序、邊界、rounding、complexity、golden/property/metamorphic tests 與 fail-closed 條件。 | 讓安全相關規則可重現、可解釋、可獨立測試並固定歷史語義；接受每個政策變更都需要新版本、程式審查與測試，而不是任意執行期配置。 |
| DEC-090 | Policy definitions 與 released versions immutable 且由 code/build identity 管理；每個 policy family 同時只有一個 active version，必須由 Owner 透過高風險兩步確認明確啟用，記錄 actor、effective_at、reason、old/new version 與 validation evidence。新事件只使用其 evaluation time 的 active version；既有 Recommendation、valuation、anomaly、exposure、priority 與 decision trace 永不被新版本原地重算或覆寫。針對 open/current items 的 re-evaluation 必須是明確 command，建立 linked new evaluation、保留舊結果並顯示差異；若 safety policy 要求處理，產生新的 Action Item 而非改寫歷史。Rollback 以啟用另一個已發布版本完成，不修改版本內容。 | 保留歷史決策真實語義和可重現性，同時允許受控地把修正套用到目前項目；接受啟用、差異檢查和 re-evaluation 工作流程。 |
| DEC-091 | Runtime secrets 由 Linux host 上 repository/image/database 之外的專用 root-owned files 管理，以 read-only file mount 只提供給需要的 Compose service；不得以單一 shared `.env` 把全部 secrets 注入所有程序，也不在 v1 新增 network secret-manager service。API、collector、AI、email、cloudflared、backup 與 database 取得各自最小 secret set；應用程式只接受 file reference／secret provider port，不記錄值，錯誤、health、metrics、traces、support bundle、API 與 UI 必須 redaction。Secret inventory 記錄 owner、consumer、建立／輪替／到期時間但不含值；輪替採 staged replacement、受影響 process targeted restart、old credential revoke 與 audit，並具缺失／錯誤權限／過期／撤銷 fail-closed tests。 | 在單一私人 VM 上達成 process-scoped least privilege 和可操作輪替，而不增加另一個必須高可用與復原的秘密服務；接受 host 權限、離線 recovery 與人工 rotation runbook 的責任。 |
| DEC-092 | v1 只保留一份 VM 與 B2 storage/credential 之外的 encrypted offline recovery-material copy，內容涵蓋備份解密與敏感欄位 key hierarchy 的必要 root material；具體媒介、加密方式、保管位置與 custodian 是部署前必填且不得與 Server 同址或與 B2 credential 共置。每月 restore drill 必須從該 offline copy 實際取得 key、驗證指紋、解密當期備份並還原；任何讀取、完整性、密碼或解密失敗立即使 backup readiness FAIL 並建立 safety-locked Action Item。Owner 明確接受：此唯一副本遺失、損壞、密碼失效或與 VM 同時受災時，加密資料可能永久不可復原；系統不得宣稱已消除 recovery single point of failure。 | 符合 Owner 選擇的較低管理成本，但保留可見、可測且不能被文件淡化的永久資料損失風險；每月驗證只能提早發現問題，不能消除單份副本的失竊或共同災害風險。 |
| DEC-093 | Production 採 balanced local observability：所有 process 輸出 schema-versioned structured logs，使用 request/job/event correlation 與 causation IDs；提供分離的 liveness/readiness、bounded operational metrics，以及只針對跨 process、外部 provider、queue claim/retry 與高風險 command 的 targeted traces。必要 signals 至少涵蓋 API latency/error、auth denial、各 worker heartbeat、job backlog/oldest age/lease expiry/retry/dead-letter、來源 freshness/outage、AI/critic/Gmail latency/result、PostgreSQL pool/transaction/lock、disk/memory、backup/restore 與 build/version mismatch。Telemetry 僅保存 opaque IDs、分類、狀態、duration 與 counts，不得保存 Evidence/Thesis/Recommendation/Portfolio/Email body、來源內容、prompt/output、token、secret 或完整 email；export 前集中 redaction。健康 signal 觸發可去重 Operations Action Item，critical 狀況才使用允許欄位通知；不得依賴同一已故障 channel 作為唯一告警證據。v1 不部署高容量全文 log analytics 平台，retention 與 disk cap 由 deployment profile 依 SPEC-0002 容量驗證。 | 足以判定可服務性、資料新鮮度、queue 卡住與外部依賴故障，又限制單一 VM 的資源與敏感資料擴散；接受需維護 signal schema、redaction 和 Action Item 去重。 |
| DEC-094 | 單一正式 VM 採 planned maintenance release，不承諾 zero downtime。Release gate 依序要求 immutable image/build、OpenAPI/generated contract 與 architecture manifest 一致；測試與 migration rehearsal 通過；最新 backup 與 recovery evidence 有效；進入 maintenance/read-only、停止新 command 與 job claim、bounded drain 既有 transaction；執行 forward Alembic migration；同時切換 API/collector/AI/email 至同一 build；驗證 schema/build compatibility、health/readiness、auth、queue、主要 API/UI smoke；全部通過才恢復寫入。失敗時保持 maintenance，不把未驗證版本開放；只有 schema backward-compatible 才可 image rollback，否則依 runbook restore。Destructive schema change 必須使用至少跨兩個 release 的 expand-migrate-contract，禁止 deploy-time destructive downgrade 或未驗證自動 latest migration。 | 在 4 GiB 單一 VM 上用可預期短暫停機換取 code/schema/worker 一致與明確復原點，避免雙棧資源壓力及不可逆 migration 被誤當成換回 image 即可修復。 |
| DEC-095 | Validation 採 layered evidence strategy。Pure policies/state machines 使用 deterministic unit、boundary、example/golden、property 與適用的 metamorphic tests；repository、RLS、constraints、transactions、migrations、outbox/jobs、leases/concurrency 使用每個 suite 隔離的真實 PostgreSQL，不以 SQLite 或 repository mocks 作為通過證據；外部 source/AI/Cloudflare/Gmail/B2 使用版本化 fixtures、fake ports 與 provider contract tests；OpenAPI/API 層驗證 auth、error envelope、idempotency、optimistic concurrency；Playwright 只覆蓋關鍵登入、Inbox、workspace、Thesis、Recommendation、Trade 與 responsive/accessibility flows。正式 VM shadow、freshness、fault injection、backup restore 與 capacity evidence 保留為 runtime/release gates。每個 AC 必須指定 primary evidence layer，測試失敗不得由較高層 smoke test 取代。 | 讓組合性規則、PostgreSQL 真實語義、外部契約與使用者流程各自在最有效且可定位的層級驗證，避免 mock 假信心或全部依賴脆弱 E2E。 |
| DEC-096 | 實作採 walking skeleton 加 risk-first vertical slices。第一個 skeleton 必須以同一條可執行路徑貫穿 responsive React UI、generated OpenAPI client、FastAPI command/query、PostgreSQL transaction、audit event、outbox job、獨立 worker 與 UI 狀態更新，並同時建立 project skeleton、architecture manifest、Compose、migration 與 CI。後續每一片均包含必要的資料模型、backend、API、UI、自動測試與文件，依序完成 Access 與角色邊界、Company/Evidence/provenance/去重/更正、E0–E6、anomaly/critic/fail-closed、Action Inbox/company workspace、Thesis/Outcome/Reflection、估值/Portfolio/Trade/Exposure、Recommendation/Owner decision，最後完成 email、backup、observability、release 與正式 VM validation。任何 slice 不得以只有 backend、只有 UI 或以 mock/SQLite 取代其主要驗收證據而宣告完成。 | 儘早證明跨層契約、PostgreSQL transaction/outbox、worker 與響應式 UI 能共同運作，再優先消除證據、Hard anomaly、權限與交易一致性等高風險；代價是每片都要維持全棧與文件同步，初期可見功能較窄。 |
| DEC-097 | 第一個產品原始碼變更前必須完成 schema/standard 2.2.0 的最小但完整 authoring-first architecture package：單一 system manifest、L0–L3+ module/parent/dependency boundaries、source-set classification、release composition root、Type Catalog 與 Type Ownership Matrix、State Object Ownership Matrix、Boundary Design Table、commands/queries/ports/events 與 delivery/failure contracts、runtime executables/mappings/channels、所有關鍵 end-to-end Flows 的候選比較與 flow-cost review、每個產品功能的 algorithm screening、適用的 proposed ADR 與完整 Algorithm Design Records，以及由 manifest 產生且無 stale diff 的 System/Parent/ownership/flow views。開始 walking skeleton 前，design-phase architecture gate 必須 PASS；任何未決 owner、非法 dependency、缺失 mapping、未定 delivery/failure、未完成 algorithm record 或需要但缺少的人類核准均維持 BLOCKED。架構文件在每個 vertical slice 與程式、測試同步更新。 | 使正式架構成為實作前的可檢查契約，而不是事後描述；成本是第一個產品畫面前要先完成一輪完整建模與檢查，但能顯著降低跨模組、型別、狀態與背景工作的結構性返工。 |
| DEC-098 | 第一個 user-visible walking skeleton 為 authenticated Owner 的 Company/Evidence intake：Owner 在 responsive Web 選擇或建立 Company 並提交 Evidence URL；API 在同一 PostgreSQL transaction 內驗證 admission、保存 `received` 狀態、audit event 與 durable outbox job，立即回傳可查詢的 record/version ID。Collector worker 以 at-least-once、leased claim 與 idempotency 執行受限制的來源取得，成功時保存 immutable content snapshot/hash、URL、publisher、published/observed/retrieved times、必要摘錄、source category、lineage/provenance 與 `succeeded` 狀態，失敗時保存可理解但不洩密的 `failed`／retrying／dead-letter 狀態；同 URL 或同內容不得產生重複 source-of-record。UI 以該 Server record/version 查詢並顯示 received、processing、succeeded 或 failed，不建立 client-only 真實狀態。此 slice 必須通過 Cloudflare identity/JWT 邊界、PostgreSQL transaction/outbox/dedup integration、collector adapter contract、API/OpenAPI 及 responsive Playwright flow；不執行 AI、E0–E6、Hard anomaly、Thesis、估值或 Recommendation。 | 第一片就證明產品核心的證據入口以及 UI、API、PostgreSQL、audit/outbox、獨立 worker、錯誤處理和響應式狀態更新能共同運作，同時把高風險 AI 與 anomaly policy 留在後續專屬 slices；代價是第一片即需安全的來源擷取 adapter 與完整 provenance/dedup 語義。 |
| DEC-099 | URL canonicalization policy `url-normalization-v1` 採保守規則：只接受通過來源政策的 HTTPS URL；hostname 轉小寫、移除明確的預設 `:443` 與 fragment、空 path 轉為 `/`；非空 path 的字面內容與 percent encoding，以及 query 的內容、重複參數與順序均原樣保留。每個 canonical source、snapshot 與 URL dedup key 必須保存 normalization policy version，歷史 key 不得用新規則原地重新解讀；未來規則變更必須使用新版本及明確 migration／coexistence policy。 | 這只合併可安全證明等價的 URL 形式，避免 query 順序、重複參數、percent encoding 或來源特定 path 語義被積極正規化後錯誤合併；代價是部分實際別名仍可能分成不同 URL identity，需由 content hash 與 lineage 去重補足。 |

## Discussion Context

### DISC-001: Confirm PostgreSQL persistence

- **Situation:** The implementation-readiness review reconfirmed the persistence platform before resolving the remaining semantic gaps.
- **Question:** May ThesisTrace use PostgreSQL for primary data, durable jobs, outbox, and dead-letter storage?
- **Options and tradeoffs:** The user proactively confirmed PostgreSQL; no alternative was requested.
- **User answer:** 可以使用 PostgreSQL
- **Explicit rationale:** not stated
- **Resulting impact:** Confirms REQ-001 and DEC-002 without changing the existing contract.

### DISC-002: Select the evidence maturity model

- **Situation:** A single E0-E6 stage is easy to compare and notify but can hide material differences between evidence dimensions.
- **Question:** Should the evidence model use a fixed ladder, independent dimensions, or a combination?
- **Options and tradeoffs:** A fixed ladder is simpler; independent dimensions are more faithful but more complex; the combined model preserves both at the cost of a defined derivation rule.
- **User answer:** 可以結合1跟2。
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-003 and AC-003 and adds DEC-021. The derivation rule remains open.

### DISC-003: Select the E0-E6 derivation rule

- **Situation:** The combined evidence model needs a deterministic rule that turns independent dimensions into the E0-E6 summary stage.
- **Question:** Should derivation use sequential gates, a weighted score, or AI proposal with human confirmation?
- **Options and tradeoffs:** Sequential gates are explainable and testable; weighted scoring is nuanced but needs calibration and can mask missing evidence; AI proposal is flexible but weakens reproducibility.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-003 and AC-003 and adds DEC-022. E0-E6 now uses deterministic sequential gates.

### DISC-004: Select the research-loop lifecycle

- **Situation:** The original Problem promises traceability from evidence through Thesis, recommendation, trade, outcome, and reflection, but no lifecycle was defined.
- **Question:** Should the loop use an explicit state machine with append-only audit history, a flexible graph, or a partial first release?
- **Options and tradeoffs:** The state machine is more work but testable and traceable; a flexible graph is faster but permits incomplete chains; a partial release contradicts the stated product promise.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-031, DEC-023, and AC-025 and establishes normalized current state plus append-only audit events in PostgreSQL.

### DISC-005: Select valuation-method authority

- **Situation:** PE and PB are not equally meaningful for every company, and the system must not let AI silently choose the valuation basis.
- **Question:** Should the valuation method be confirmed by the Owner, selected by deterministic sector rules, or calculated both ways with the lower result?
- **Options and tradeoffs:** Owner confirmation is transparent but manual; sector rules automate selection but require maintenance and exceptions; taking the lower of PE and PB appears conservative but can combine economically unsuitable methods.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-005 and AC-005 and adds DEC-024. Each Thesis now requires an Owner-confirmed PE, PB, or abstain method.

### DISC-006: Select the valuation horizon

- **Situation:** A fixed twelve-month horizon is comparable but may not match short catalysts or long transformations.
- **Question:** Should valuation use a fixed twelve months, an Owner-selected six/twelve/twenty-four months, or an arbitrary target date?
- **Options and tradeoffs:** A fixed horizon is simplest; the bounded choices preserve comparability with moderate complexity; arbitrary dates are flexible but harder to compare and test.
- **User answer:** 2
- **Explicit rationale:** Selected after asking how twelve months had been determined; no additional rationale stated.
- **Resulting impact:** Changes REQ-005 and AC-005 and adds DEC-025. Each Thesis now records a six, twelve, or twenty-four month target date, defaulting to twelve months.

### DISC-007: Select target-multiple evidence

- **Situation:** Company history is reproducible but can become irrelevant after structural change, while peer comparison supports new or transformed companies but depends on peer selection.
- **Question:** Should target multiples use company history, peer comparison, or both?
- **Options and tradeoffs:** Company history is objective but backward-looking; peer comparison handles structural change but introduces peer-selection risk; retaining both provides broader evidence but requires a conflict rule.
- **User answer:** 1+2
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-005 and AC-005 and adds DEC-026. Both evidence methods are retained; the final selection/combination rule remains open.

### DISC-008: Resolve disagreement between valuation evidence methods

- **Situation:** Company history and peer comparison may produce materially different multiples, and blending can hide why they differ.
- **Question:** Should the system keep both results separate for Owner selection, take the lower result, or calculate a weighted average?
- **Options and tradeoffs:** Separate selection is transparent but manual; taking the lower value is conservative but can preserve an obsolete regime; weighting appears comprehensive but lacks a defensible calibration basis.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-005 and AC-005 and adds DEC-027. Each Recommendation now records an explicit company_history, peer_group, or abstain selection.

### DISC-009: Define peer-group eligibility

- **Situation:** Peer valuation is vulnerable to sample selection and unstable percentiles when too few companies are used.
- **Question:** Should peers be an Owner-confirmed versioned group of five to twelve, an automatic exchange-industry group, or a freely selected minimum of three?
- **Options and tradeoffs:** The governed group is auditable but may abstain for niche sectors; automatic classification is easy but often economically broad; three free-form peers are flexible but statistically and behaviorally fragile.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-005 and AC-005 and adds DEC-028. Peer valuation now requires a versioned Owner-confirmed group of five to twelve eligible Taiwan-listed peers.

### DISC-010: Define net annualized return and transaction costs

- **Situation:** Taiwan stock commissions depend on the broker, while securities transaction tax applies on sale; personal dividend taxation depends on the Owner's annual tax circumstances.
- **Question:** Should return be net of transaction costs and transaction tax only, include personal income tax, or remain gross?
- **Options and tradeoffs:** Transaction-cost net return is reproducible without sensitive tax data; personal-tax modeling is more individualized but complex and sensitive; gross return is simple but cannot be called net.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-005 and AC-005 and adds DEC-029. Recommendations now use a versioned broker Cost Profile and report transaction-cost-net, pre-personal-income-tax annualized total return.

### DISC-011: Select the exposure denominator

- **Situation:** Security and industry caps require a denominator that reflects both existing positions and deployable cash.
- **Question:** Should exposure use current portfolio NAV, a fixed Owner risk budget, or invested holdings only?
- **Options and tradeoffs:** Portfolio NAV is economically accurate but requires maintained cash; a fixed budget is stable but can become stale; holdings-only is derivable but ignores cash.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-006 and AC-005 and adds DEC-030. Exposure now uses an immutable post-trade Portfolio Snapshot based on official closes plus Owner-maintained investable cash.

### DISC-012: Define over-limit behavior

- **Situation:** The 10% security and 30% industry limits are ineffective if individual Recommendations can override them.
- **Question:** Should the limits be hard caps, Owner-overridable soft caps, or warning thresholds below separate hard caps?
- **Options and tradeoffs:** Hard caps are deterministic but inflexible; soft caps preserve discretion but invite confirmation bias; two-tier limits add flexibility but change the stated risk contract.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-006 and AC-005 and adds DEC-031. The caps are now non-overridable, DCA is clipped downward, and existing over-limit positions cannot receive additional buy recommendations.

### DISC-013: Select the industry-risk taxonomy

- **Situation:** Official classifications are reproducible but can miss cross-industry concentration such as a shared technology or supply-chain theme.
- **Question:** Should the 30% cap use official classification, Owner classification, or both with the higher exposure governing?
- **Options and tradeoffs:** Official-only is objective but broad; Owner-only is expressive but subjective; applying both is conservative and captures thematic concentration at the cost of more blocking and classification maintenance.
- **User answer:** 3
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-006 and AC-005 and adds DEC-032. Any official industry or Owner-confirmed custom risk theme above 30% now blocks buying.

### DISC-014: Allocate one security across multiple Theses

- **Situation:** A security may be held for several independent reasons, while portfolio risk must still aggregate the entire position.
- **Question:** Should each trade explicitly allocate shares to Thesis/independent buckets, use automatic FIFO, or permit only one active Thesis per security?
- **Options and tradeoffs:** Explicit allocation preserves decision attribution but adds input; FIFO is easy but can misstate intent; one Thesis per security is simple but too restrictive.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-031 and AC-025 and adds DEC-033. Trades and sells now use explicit allocation buckets while exposure remains security-wide.

### DISC-015: Combine source tiers with scored clues

- **Situation:** Fixed source classes are safe but do not prioritize large volumes of uncertain signals; scoring helps triage but must not hide provenance or duplicate common origins.
- **Question:** Should anomaly handling use fixed tiers, scoring, or both?
- **Options and tradeoffs:** Fixed tiers are reproducible but coarse; scoring is expressive but calibration-sensitive; the combined model preserves a hard evidence policy while ranking uncertain work.
- **User answer:** 1+2。我認為來源分為權威、可信獨立來源、未驗證線索、經過評分的線索
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-007 and AC-006, corrects REQ-007 dependencies, and adds DEC-034. The role of a high scored clue in Hard-anomaly promotion remains open.

### DISC-016: Define whether scored clues can become Hard evidence

- **Situation:** Scoring improves triage, but allowing a score to upgrade an unverified source would let plausibility substitute for provenance.
- **Question:** Should scoring remain triage-only, promote very high scores to B, or combine a high score with one B source?
- **Options and tradeoffs:** Triage-only is slower but preserves the evidence boundary; promotion reacts faster but can elevate rumors; mixed quorum still risks common-origin double counting.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-007 and AC-006 and adds DEC-035. Scored clues can never satisfy Hard-anomaly evidence requirements.

### DISC-017: Define the B-source quorum and critic failure policy

- **Situation:** Hard anomaly needs a precise non-AI evidence quorum and fail-closed critic contract.
- **Question:** Should the quorum be one A or two independent B, one A or three B, or one A/one B with Owner confirmation?
- **Options and tradeoffs:** Two B balances timeliness and corroboration; three B is safer but slower; one B plus Owner is fast but weakens the fixed evidence boundary.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-007 and AC-006 and adds DEC-036. Hard anomaly now requires one direct A or two genuinely independent B plus a strict structured critic PASS.

### DISC-018: Select the Hard-anomaly release validation gate

- **Situation:** Hard anomaly can stop further buying and produce an exit recommendation, so deterministic cases alone should be complemented by real-source observation before activation.
- **Question:** Should release require a fixed 100-case zero-misclassification suite plus thirty-day shadow mode, a statistical dataset, or unquantified manual review?
- **Options and tradeoffs:** The fixed suite plus shadow is reproducible and conservative but delays activation; a large statistical gate needs more labels and permits errors; manual review is fast but not repeatable.
- **User answer:** 選擇1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-007 and AC-006 and adds DEC-037. Hard notification activation now requires the 100-case gate and thirty continuous shadow days on the production Linux Server VM.

### DISC-019: Correct the scope of Linux Server VM capacity testing

- **Situation:** The discussion moved from SPEC-0001 software behavior into the CPU, memory, disk, and hypervisor capacity owned by SPEC-0002.
- **Question:** Should VM hardware-capacity thresholds block the current SPEC-0001 software-function interview?
- **Options and tradeoffs:** Keeping them here conflates product and infrastructure contracts; moving them to SPEC-0002 preserves ownership while SPEC-0001 retains software SLOs and observable behavior.
- **User answer:** 這個不是硬體測試？我們不是在討論SPEC-0001軟體的功能討論？
- **Explicit rationale:** The user expects the current discussion to remain about SPEC-0001 software functions.
- **Resulting impact:** Adds DEC-038 and removes Linux VM resource-capacity thresholds from the current open software decisions. No SPEC-0002 content is modified.

### DISC-020: Order Server/UI design before authentication selection

- **Situation:** Authentication and session behavior depend on the actual Server operations, UI workflows, and which actions are sensitive.
- **Question:** Should the login mechanism be finalized before or after the Server/UI behavior is clarified?
- **Options and tradeoffs:** Choosing authentication first can constrain the product prematurely; defining workflows first allows the login and reauthentication design to match actual risk.
- **User answer:** 我認為先確認後面功能，才能決定這個要怎樣實作。我們先討論server跟UI該如何進行
- **Explicit rationale:** The remaining product behavior should determine the authentication implementation.
- **Resulting impact:** Adds DEC-039. Magic Link remains an unconfirmed proposal while Server/UI workflows are discussed first.

### DISC-021: Select the overall UI organization

- **Situation:** ThesisTrace must support both daily handling of new items across companies and longitudinal research within one company.
- **Question:** Should the UI be hybrid workflow plus company workspace, company-first only, or workflow-first only?
- **Options and tradeoffs:** The hybrid model preserves both a cross-company action queue and complete company context but requires consistent deep links and return behavior; company-first is context-rich but weak for daily triage; workflow-first is efficient for queues but fragments long-term company research.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-032, DEC-040, and AC-026. The UI now has two coordinated views over the same Server-authoritative records rather than two data models.

### DISC-022: Select the workflow-home model

- **Situation:** The workflow entry can operate as an actionable inbox, a chronological event wall, or separate module queues.
- **Question:** Which model should the workflow home use?
- **Options and tradeoffs:** A unified action inbox separates required human work from informational events but needs explicit lifecycle and deduplication rules; an event wall is comprehensive but noisy; separate queues simplify each module while forcing users to check several places.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-033, DEC-041, and AC-027. The Server now creates deduplicated actionable items while ordinary events remain in activity/history views.

### DISC-023: Select the action-inbox presentation

- **Situation:** The unified action inbox can be shown as summary cards plus a priority list, a kanban board, or a dense table.
- **Question:** Which presentation should be the primary inbox interface?
- **Options and tradeoffs:** Summary cards plus a priority list highlights urgent work while retaining filters and narrow-screen usability; kanban visualizes status but becomes long with many items; a pure table maximizes density but makes important items and mobile operation harder.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-034, DEC-042, and AC-028. Summary cards and list results share a Server query contract; the exact priority policy remains open.

### DISC-024: Select the action-item detail interaction

- **Situation:** Opening an inbox item can use a desktop side detail with a mobile full page, always navigate to a full page, or use a modal.
- **Question:** How should Action Item details open?
- **Options and tradeoffs:** A desktop side detail preserves list context and a mobile full page preserves usable space but requires responsive routing; always using full pages is simpler but slows repeated triage; modals are quick for small items but weak for complex evidence and deep links.
- **User answer:** 選擇1。
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-035, DEC-043, and AC-029. Item selection becomes route-addressable and preserves the originating inbox state across navigation and responsive layouts.

### DISC-025: Confirm the v1 delivery surface

- **Situation:** ThesisTrace can ship as a responsive Web application, an installable PWA, or native applications in addition to Web.
- **Question:** Which delivery surface should v1 support?
- **Options and tradeoffs:** Responsive Web minimizes deployment and update paths while serving desktop and mobile online; PWA adds installation and cache/version concerns; native applications improve device integration but create additional clients, release processes, and security surfaces.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-036, DEC-044, and AC-030. v1 is online-only responsive Web over VPN; native applications, installable PWA behavior, and offline domain data are excluded.

### DISC-026: Select the Action Item priority authority

- **Situation:** Inbox priority can be determined by Server rules with bounded Owner adjustments, by Server rules alone, or entirely by users.
- **Question:** Who should control Action Item priority?
- **Options and tradeoffs:** Deterministic defaults plus bounded Owner adjustment preserve testable safety ordering and personal research control but need an explicit safety floor; Server-only ordering is consistent but inflexible; manual-only ordering is flexible but can leave important new items under-prioritized.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-037, DEC-045, and AC-031. Priority is Server-authoritative and explainable; Owner overrides are personal and audited, and the exact safety-locked categories remain open.

### DISC-027: Define safety-locked Action Item categories

- **Situation:** The priority safety floor can cover risk and portfolio-integrity failures, only Hard anomaly and Thesis invalidation, or every Server-generated item.
- **Question:** Which Action Item categories must be impossible to deprioritize?
- **Options and tradeoffs:** Locking risk and portfolio-integrity items protects decisions and exposure calculations while preserving flexibility elsewhere; locking only anomaly/invalidation leaves trade and risk-data failures adjustable; locking every automatic item removes useful personal prioritization.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-038, DEC-046, and AC-032. Critical and high safety floors are now tied to explicit domain conditions and can only clear when the underlying condition is resolved or corrected.

### DISC-028: Select Action Item ownership for a private system

- **Situation:** With multiple permitted accounts, Action Items can be automatically owned by the data owner or role, transferred between peers, or placed in a shared pool.
- **Question:** Does v1 need collaborative assignment, or should ownership be automatic and private?
- **Options and tradeoffs:** Automatic private ownership removes collaboration complexity and prevents accidental disclosure; same-role transfer supports teams but expands authorization and audit behavior; a shared pool weakens accountability and privacy.
- **User answer:** 是私人系統沒錯，所以選擇1
- **Explicit rationale:** ThesisTrace is a private system.
- **Resulting impact:** Adds REQ-039, DEC-047, and AC-033. v1 has no claim, watcher, shared-pool, or transfer workflow; ownership is derived by the Server from data ownership and role.

### DISC-029: Define defer and dismiss behavior

- **Situation:** Safety Action Items can remain visible until verified resolution, allow a bounded defer, or use the same defer/dismiss rules as ordinary work.
- **Question:** May safety Action Items be deferred or dismissed?
- **Options and tradeoffs:** Keeping them visible until verified resolution prevents risk from disappearing but can leave persistent items; a short defer reduces interruption but delays review; uniform flexibility is simple but can hide material failures.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-040, DEC-048, and AC-034. Safety items cannot be deferred, dismissed, or manually completed; ordinary items can be scheduled or dismissed with an audit trail.

### DISC-030: Define post-closure recurrence behavior

- **Situation:** Material evidence arriving after completion or dismissal can create a linked new item, reopen the old item, or produce only a notification.
- **Question:** How should a previously closed issue return to the inbox?
- **Options and tradeoffs:** A linked new item preserves each decision record and supports recurrence history but creates more rows; reopening reduces rows but mixes separate evidence and outcomes; notification-only risks leaving new evidence unhandled.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-041, DEC-049, and AC-035. Closed items remain immutable; material new evidence creates a fully re-evaluated linked item, while duplicates and non-material source-version changes are suppressed.

### DISC-031: Select the company-workspace landing page

- **Situation:** A company workspace can open on a status overview with functional tabs, an event timeline, or the current Thesis.
- **Question:** What should users see first when opening a company?
- **Options and tradeoffs:** An overview plus tabs exposes current state and urgent work while preserving complete drill-down; a timeline emphasizes history but obscures current decisions; a Thesis-first page is decision-oriented but weak for companies without an active Thesis.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-042, DEC-050, and AC-036. Company pages now have a role-filtered overview, stable shared header, and route-addressable functional tabs.

### DISC-032: Select multi-Thesis presentation

- **Situation:** A company may have several active investment rationales that can be shown independently, subordinated to a primary Thesis, or merged into one composite.
- **Question:** How should multiple Theses for one company appear?
- **Options and tradeoffs:** Independent cards preserve hypotheses, valuation, invalidation, and attribution while requiring a separate company aggregate; a primary Thesis simplifies the overview but hides secondary rationale; a composite mixes assumptions and breaks traceability.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-043, DEC-051, and AC-037. Thesis chains remain independent while security-level position and exposure aggregate every Thesis and independent bucket.

### DISC-033: Select the Evidence-page presentation

- **Situation:** Evidence can be organized by Evidence Chain with stage and source timeline, as a chronological event wall, or as a flat source table.
- **Question:** Which structure should be primary?
- **Options and tradeoffs:** Chain-first presentation connects sources to E-stage evolution but needs drill-down; a chronological wall emphasizes recency but fragments corroboration; a flat table supports bulk sorting but obscures causal and maturity relationships.
- **User answer:** 選擇1。
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-044, DEC-052, and AC-038. Evidence is navigated chain-first with auditable source and stage-transition timelines.

### DISC-034: Reassess VPN-only access

- **Situation:** The user finds VPN-only browser access cumbersome and asks whether Cloudflare Tunnel can replace it.
- **Question:** Should SPEC-0001 retain WireGuard, use a Cloudflare public hostname protected by Access, or use a private Cloudflare application that still requires a device client?
- **Options and tradeoffs:** Pending discussion after verifying Cloudflare's current official behavior; Tunnel connectivity alone is not treated as application authentication.
- **User answer:** 感覺VPN有點麻煩。可以使用Cloudflare Tunnels？
- **Explicit rationale:** Reduce access friction.
- **Resulting impact:** Opens a possible supersession of REQ-012 and DEC-009. The current VPN-only contract remains effective until an access-boundary option is explicitly selected.

### DISC-035: Keep the application and database local

- **Situation:** Removing the VPN can be achieved by publishing the local service through an ingress provider or by moving some or all runtime and data to a VPS/cloud platform.
- **Question:** Must the Server and PostgreSQL remain local?
- **Options and tradeoffs:** Keeping everything local preserves data and deployment control but still needs a secure ingress; moving everything to cloud removes home-network dependency but changes hosting and privacy; splitting cloud API from local PostgreSQL creates the most complex persistent network boundary.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-045, DEC-053, and AC-039. The remaining access decision is limited to non-VPN ingress for the local application; cloud application/database hosting is excluded from v1.

### DISC-036: Select the non-VPN local ingress

- **Situation:** With application and data remaining local, the shortlisted browser-only ingress choices were Cloudflare Tunnel plus Access, Tailscale Funnel plus application authentication, or directly published Caddy HTTPS.
- **Question:** Which ingress should v1 use?
- **Options and tradeoffs:** Cloudflare supplies an outbound-only tunnel and mature identity-aware gate but becomes an external trust and availability dependency; Tailscale Funnel preserves relay content confidentiality but is beta and leaves more protection to the app; direct HTTPS avoids a tunnel vendor but exposes the home origin and requires full edge hardening.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-001, REQ-012, REQ-036, AC-001, AC-011, and AC-030; adds DEC-054. DEC-054 supersedes DEC-009, so WireGuard is no longer the v1 user-access path.

### DISC-037: Select the Cloudflare Access identities

- **Situation:** Cloudflare Tunnel and Access are selected, but the private system still needs a primary identity method and a recoverable Owner path.
- **Question:** Should v1 use Google identities, Cloudflare account identities, or both?
- **Options and tradeoffs:** Google gives ordinary users a familiar sign-in but requires Google OAuth configuration; Cloudflare account identity centralizes membership but is unsuitable as the routine account system for every private user; combining them permits Google for normal use and a narrowly scoped Owner-only Cloudflare identity for emergency recovery, at the cost of maintaining and testing two identity paths.
- **User answer:** 1+2
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-008 and AC-007; adds DEC-055. Google becomes the exact-email-allowlisted primary identity, while Cloudflare account identity is restricted to the same Owner as an audited emergency path; Magic Link is removed from v1 authentication.

### DISC-038: Select the normal Access session duration

- **Situation:** Google is the normal identity path, but the duration of its Access application token and the point at which MFA is required again must be testable.
- **Question:** Should the normal session last 8 hours, 24 hours, or 1 hour?
- **Options and tradeoffs:** Eight hours approximates one workday; 24 hours reduces prompts but extends exposure on a lost or shared device; one hour limits exposure but interrupts desktop and mobile use frequently.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Changes REQ-008 and AC-007; adds DEC-056. The normal Google Access session is eight hours, the next access after expiry requires Google and MFA again, and ThesisTrace may not outlive the Access token with its own session.

### DISC-039: Select the Owner break-glass activation policy

- **Situation:** The Owner has a separate Cloudflare account identity, but leaving it permanently enabled creates an unnecessary second attack path.
- **Question:** Should the break-glass policy be disabled until manually activated, remain enabled with a short session, or be removed?
- **Options and tradeoffs:** Disabled-by-default minimizes exposure but requires a Cloudflare dashboard recovery step; always-enabled is faster during failure but permanently exposes a second identity path; removal is simplest but leaves no login recovery when Google identity is unavailable.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-046, DEC-057, and AC-040. The Owner manually enables the otherwise-disabled policy, authenticates with MFA for at most 30 minutes, receives an auditable safety-locked shutdown task, and disables the path immediately after recovery; no bypass is permitted if the recovery credential is unavailable.

### DISC-040: Select the Action Item completion flow

- **Situation:** The inbox already has a desktop detail panel and mobile full-page detail, but complex domain changes such as valuation updates or trade allocation do not fit safely in a compact panel.
- **Question:** Should all work happen in the detail panel, all work navigate to the company workspace, or should simple and domain-changing work use different paths?
- **Options and tradeoffs:** A hybrid keeps lightweight task actions in context and sends domain changes to the full authoritative form; panel-only duplicates complex forms in constrained space; workspace-only creates unnecessary navigation for simple task handling.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-047, DEC-058, and AC-041. Simple task-level actions stay in the detail view, domain mutations open the exact company tab and record version, and return navigation restores and refreshes the original inbox context.

### DISC-041: Select sensitive-action confirmation

- **Situation:** Some writes are ordinary drafts while others commit investment decisions, trade attribution, Thesis state, anomaly handling, or account authority; treating them identically either creates confirmation fatigue or leaves costly mistakes too easy.
- **Question:** Should confirmation apply by risk, to every write, or to no writes?
- **Options and tradeoffs:** Risk-tiered confirmation adds a bounded review step only to consequential actions; confirmation on every write creates repetitive friction and habituation; no additional confirmation is fastest but weakens protection against accidental state changes.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-048, DEC-059, and AC-042. Consequential actions use a short-lived, single-use, actor/version/payload-bound Server preview and reasoned confirmation; ordinary drafts retain direct validated saves.

### DISC-042: Select company-workspace save behavior

- **Situation:** Long research prose is costly to lose, while automatically committing financial values, scores, allocations, or state changes can silently alter official results.
- **Question:** Should saving be hybrid, entirely manual, or entirely automatic?
- **Options and tradeoffs:** Hybrid autosaves only long-form unpublished text and requires explicit saves for structured or official data; manual-only is simpler but risks lost prose; autosave-all is convenient but makes accidental financial and state changes too easy.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-049, DEC-060, and AC-043. Long-form drafts autosave with visible Server-confirmed status and conflict handling; structured and official fields never autosave, and offline text is not persisted or queued by the browser.

### DISC-043: Select email notification disclosure

- **Situation:** Generic email best protects privacy but gives little triage value, while a full summary exposes investment research outside the Access-protected application.
- **Question:** Should email be generic, include company and item type, or include a full summary?
- **Options and tradeoffs:** Company plus item type supports useful triage without values or direction; generic mail minimizes disclosure; full summaries are convenient but materially increase exposure through email accounts and previews.
- **User answer:** 2
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-050, DEC-061, and AC-044. Email is generated from a strict allowlist template, may name the company/ticker and Action Item type, excludes investment details and secrets, and uses only an opaque Access-protected deep link.

### DISC-044: Select the software freshness SLO

- **Situation:** Five-minute polling alone does not prove that an official event becomes durable and actionable promptly, but a home-hosted system also needs a realistic allowance for outages and worker delays.
- **Question:** Should the 30-day threshold be 99% within 10 minutes and all within 30, 95% within 10 and 99% within 30, or polling without a completion-rate objective?
- **Options and tradeoffs:** The selected 95%/99% target is measurable and tolerant of bounded local interruptions; the stricter target gives less margin; polling-only cannot verify end-to-end freshness.
- **User answer:** 2
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-051, DEC-062, and AC-045. Freshness runs from trustworthy publication or first observable availability to durable Evidence and required work, uses a rolling 30-day denominator, reports external outages separately, and alerts without dropping late events.

### DISC-045: Select architecture schema and governance placement

- **Situation:** Git tracking and architecture-document format are mandatory engineering controls but were represented as product requirements, while the active governance contract now uses schema 2.2.0 with exact compatibility for 2.1.0 inputs.
- **Question:** Should the project upgrade and move these controls to delivery constraints, upgrade but retain them as product requirements, or remain on 2.1.0?
- **Options and tradeoffs:** Moving upgraded controls keeps product acceptance focused on user-visible behavior while preserving hard implementation gates; retaining them as product requirements mixes delivery mechanics with product scope; remaining on 2.1.0 conflicts with the active governance toolchain.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-063; removes the former Git and architecture governance rows from product requirements and product acceptance, then rematerializes their substance under Engineering Delivery Constraints. Architecture governance uses schema 2.2.0 and must accept valid 2.1.0 sources exactly as defined by the compatibility contract.

### DISC-046: Reconcile superseded authentication and access decisions

- **Situation:** The semantic readiness audit found historical decision rows that still said Email Magic Link and VPN-only even though later user choices established Cloudflare Access with Google/Owner identities and browser access without VPN.
- **Question:** Is a new product choice required, or can the already-recorded later choices explicitly supersede the stale decisions?
- **Options and tradeoffs:** The prior choices are unambiguous, so explicit superseding decisions preserve history without reopening settled product behavior; rewriting old rows would erase history; leaving them unrelated would make implementation guidance contradictory.
- **User answer:** Derived from the previously recorded selections for responsive Web, Cloudflare Tunnel/Access, Google plus Owner backup identity, and removal of Magic Link.
- **Explicit rationale:** Preserve the latest user-approved behavior while retaining auditable decision history.
- **Resulting impact:** Adds DEC-064 and DEC-065. DEC-064 supersedes DEC-044; DEC-065 supersedes DEC-008 and DEC-039. No product behavior changes from the latest approved requirements.

### DISC-047: Define Claude backup qualification and failover

- **Situation:** The original backup decision named 30 cases, 10 shadow runs, and human approval without defining agreement metrics, what one run means, the approver, reset behavior, or when automatic failover is permitted.
- **Question:** Should Claude become an automatic qualified backup, remain manual-only, or be excluded from v1?
- **Options and tradeoffs:** Qualified automatic failover improves provider-outage continuity but requires strict repeatable gates; manual-only reduces automatic risk but delays recovery; exclusion is simplest but leaves no AI continuity.
- **User answer:** 1
- **Explicit rationale:** not stated
- **Resulting impact:** Adds REQ-052, DEC-066, and AC-046. DEC-066 supersedes DEC-005. Qualification requires 29/30 decision-field agreement with zero safety/schema/citation violations, ten consecutive immutable-input production shadow tasks with zero major discrepancy, and recorded Owner approval; failover is provider-wide only and all invalid output fails closed to a human Action Item.

### DISC-048: Correct the current Solution ingress summary

- **Situation:** The final semantic audit found that the current Solution summary still said VPN-only even though the requirements and superseding decisions consistently require Cloudflare Tunnel/Access without VPN.
- **Question:** Does this require a new product decision?
- **Options and tradeoffs:** No; this is a stale summary correction derived directly from the already-approved ingress, deployment, and responsive-Web decisions. Historical superseded rows remain unchanged for auditability.
- **User answer:** Derived from the previously approved Cloudflare Tunnel/Access and no-VPN selections.
- **Explicit rationale:** Keep the top-level implementation guidance consistent with the normative requirements.
- **Resulting impact:** Aligns the Solution summary with DEC-064 without changing normative product behavior.

### DISC-049: Select the modern responsive UI visual style

- **Situation:** REQ-034 through REQ-036 and REQ-042 through REQ-049 already require one responsive React Web UI for desktop and mobile, including narrow-screen navigation and no horizontal scrolling for primary inbox operations. They do not yet define the intended modern visual language or measurable layout-quality envelope.
- **Question:** Which modern visual style should govern the shared desktop and mobile design system?
- **Options and tradeoffs:** A calm professional research workspace prioritizes readability and balanced information density; a dense financial terminal prioritizes simultaneous data visibility at the cost of mobile simplicity; a consumer-style card interface is approachable but requires more navigation for evidence-heavy work.
- **User answer:** 1 — 現代專業研究工作台。
- **Explicit rationale:** The UI should look modern and remain compatible on both computer and phone screens without layout breakage.
- **Resulting impact:** Adds DEC-067. The shared design system will use a calm professional research-workspace language; the measurable viewport support envelope remains open.
### DISC-050: Select the responsive viewport acceptance envelope

- **Situation:** A responsive implementation needs a measurable CSS-pixel width range; HTML5 alone does not guarantee layout stability across desktop and mobile.
- **Question:** Which viewport-width envelope should all primary workflows support without page-level horizontal scrolling or layout breakage?
- **Options and tradeoffs:** 360–2560 CSS px balances common phone through wide-desktop coverage and test cost; 320–2560 adds legacy narrow phones with substantially more layout variants; 390–1920 lowers cost but excludes narrower phones, split windows, and wider desktops.
- **User answer:** 1 — 360–2560 CSS px.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-068. Responsive acceptance will use continuous behavior across the selected envelope rather than a small list of device models.
### DISC-051: Select supported color modes

- **Situation:** The selected professional research-workspace style still needs a color-mode contract because theme support affects every component, chart, state color, focus indicator, and visual-regression test.
- **Question:** Should v1 support both light and dark themes, light only, or dark only?
- **Options and tradeoffs:** Both themes with system default and manual override provide the best environmental flexibility but double theme validation; light only minimizes cost and favors long-form reading and printing but is less comfortable at night; dark only favors low-light use but conflicts with daytime reading, printing, and the selected non-terminal style.
- **User answer:** 1 — support both light and dark themes, default to the device system setting, and allow manual switching.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-069. Theme preference persistence remains open because browser-local and server-account storage have different cross-device behavior.
### DISC-052: Select theme-preference persistence

- **Situation:** Manual light/dark switching needs a persistence owner. Browser-local storage is device-specific, while Server profile storage can synchronize desktop and mobile.
- **Question:** Should the manual theme override be saved to the Server user profile, current browser only, or not persisted?
- **Options and tradeoffs:** Server profile storage adds a small PostgreSQL field and API but synchronizes devices; browser-only storage is simpler but differs across devices and disappears when storage is cleared; session-only behavior has the lowest cost but makes manual switching transient.
- **User answer:** 1 — save the preference to the Server user profile.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-070. The preference contract uses system, light, and dark values; the next UI-quality decision is the accessibility and zoom acceptance level.
### DISC-053: Select accessibility and zoom acceptance

- **Situation:** Native viewport support alone does not prove that enlarged text, browser zoom, keyboard navigation, focus, contrast, or error handling remains usable.
- **Question:** Should the authenticated application fully target WCAG 2.2 AA, adopt a partial accessibility subset, or validate only ordinary responsive layouts?
- **Options and tradeoffs:** Full AA provides measurable keyboard, contrast, focus, target-size, resize, and reflow guarantees at the highest validation cost; a partial subset costs less but cannot claim consistent AA behavior; ordinary responsive testing is cheapest but does not cover zoom or keyboard breakage.
- **User answer:** 1 — fully adopt WCAG 2.2 AA, including 200% text resizing and 400% zoom/reflow acceptance.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-071. Native support remains 360–2560 CSS px, while zoomed desktop reflow is additionally tested at an effective 320 CSS px width. Handling of inherently two-dimensional research tables remains open.
### DISC-054: Select responsive handling for research tables

- **Situation:** Evidence, valuation comparisons, trades, and history can exceed mobile width and are the most likely components to break reflow.
- **Question:** Should narrow layouts use responsive summaries plus complete details, keep all tables with local horizontal scrolling, or hide secondary columns?
- **Options and tradeoffs:** Summary plus complete detail gives the best mobile and reflow behavior at the cost of additional components; table-only scrolling is simpler but makes row context and keyboard use harder; hiding columns is compact but can conceal research data and creates ambiguous importance rules.
- **User answer:** 1 — use responsive summaries plus complete details, allowing local horizontal scrolling only for genuinely two-dimensional comparisons.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-072. All authorized data remains reachable from the same Server record/version, page-level horizontal scrolling remains prohibited, and browser support is the next open compatibility boundary.
### DISC-055: Select the browser support window

- **Situation:** Responsive HTML/CSS behavior and accessibility can differ across browser engines, so “desktop and mobile compatible” needs a maintained support boundary.
- **Question:** Should v1 guarantee all mainstream evergreen browsers, Chromium desktop plus the principal Android/iPhone browsers, or Chrome/Edge only?
- **Options and tradeoffs:** Full mainstream support provides the broadest compatibility at the highest test cost; Chromium desktop plus Android Chrome and iPhone Safari covers the selected practical device classes while excluding Firefox and macOS Safari guarantees; Chrome/Edge only is cheapest but cannot safely claim iPhone compatibility.
- **User answer:** 2 — guarantee Chromium desktop plus Android Chrome and iPhone Safari.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-073. The moving support window is current stable and one previous major release/OS generation; UI component strategy remains open.
### DISC-056: Select the React styling and component strategy

- **Situation:** The selected responsive, dual-theme, WCAG AA interface needs a component strategy that balances visual control, accessible interaction behavior, and maintenance.
- **Question:** Should the project use Tailwind CSS plus Radix Primitives behind project-owned wrappers, Material UI, or fully custom CSS Modules and controls?
- **Options and tradeoffs:** Tailwind plus Radix preserves a custom research-workspace identity and reuses keyboard/focus primitives but requires a maintained wrapper layer; Material UI ships more styled components but imposes a Material visual model and greater theme override; fully custom controls minimize dependencies but maximize accessibility and interaction risk.
- **User answer:** 1 — Tailwind CSS plus Radix Primitives and a project-owned design system.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-074. Vendor imports are isolated behind shared UI wrappers; semantic tokens own light/dark styling. The visual accent palette remains open.
### DISC-057: Select the neutral and accent palette

- **Situation:** The professional research-workspace style needs one neutral foundation and interaction accent that works in light and dark themes without colliding with financial or safety semantics.
- **Question:** Should the design use slate plus blue/indigo, neutral gray plus teal, or warm stone plus amber?
- **Options and tradeoffs:** Slate plus blue/indigo is professional and keeps interaction colors separate from red/green market semantics; neutral plus teal is calm but can collide with positive or Taiwan-market down colors; stone plus amber is warm but can collide with warning semantics and requires harder contrast tuning.
- **User answer:** 1 — Slate neutral base with Blue/Indigo accent.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-075. Theme-specific semantic tokens own contrast; the Taiwan market gain/loss convention remains open.
### DISC-058: Select Taiwan-market direction colors

- **Situation:** Red and green can represent market direction, generic success/error, or safety states, so the Taiwan-market convention must be explicit and cannot rely on color alone.
- **Question:** Should financial gain/loss values use Taiwan red-up/green-down, international green-up/red-down, or no directional color?
- **Options and tradeoffs:** Taiwan convention matches the product market but requires strict separation from app error/success colors; international convention is familiar globally but conflicts with Taiwan-market reading habits; neutral-only display is safest for color interpretation but slows scanning.
- **User answer:** 1 — Taiwan convention: red for gains, green for losses, neutral for unchanged values.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-076. Direction always includes a sign, arrow, text, or accessible name; information density remains open.
### DISC-059: Select responsive information density

- **Situation:** Desktop research efficiency favors tighter lists, while mobile touch and zoomed layouts require larger controls and spacing.
- **Question:** Should density adapt automatically with one balanced design, offer a comfortable/compact user preference, or default to a dense terminal layout?
- **Options and tradeoffs:** Automatic balanced density minimizes configuration and test combinations while adapting touch sizes; a user toggle adds flexibility but multiplies theme, density, and viewport combinations; dense default maximizes visible rows but conflicts with the chosen research-workspace and accessibility goals.
- **User answer:** 1 — one balanced density that adapts automatically across desktop and mobile.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-077. Mobile and zoomed layouts enlarge controls without changing available data or actions; typography loading remains the final major visual decision.
### DISC-060: Select Traditional Chinese font loading

- **Situation:** Traditional Chinese webfonts can be large and can introduce first-load delay and layout shift, while system fonts vary slightly across Windows, Apple, and Android.
- **Question:** Should v1 use device system fonts, self-host Noto Sans TC, or self-host a Latin/numeric font while leaving Chinese to the system?
- **Options and tradeoffs:** System fonts load fastest and avoid external dependencies but vary by OS; self-hosted Noto Sans TC is visually consistent but materially increases font payload and font-loading complexity; a mixed Latin/CJK strategy aligns numbers but can create mismatched metrics.
- **User answer:** 1 — use device system UI and Traditional Chinese fonts.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-078 and completes the visual decisions. REQ-053 and AC-047 consolidate the full responsive UI contract and its release evidence.
### DISC-061: Select domain-module granularity

- **Situation:** SPEC-0001 already chooses a modular monolith, but the formal L1 domain boundaries are not yet fixed. The boundary size determines data ownership, allowed dependencies, transaction scope, test seams and future maintainability; these modules remain inside one backend and are not separate network services.
- **Question:** Should ThesisTrace use a balanced set of L1 domains, many fine-grained L1 domains, or three coarse L1 domains?
- **Options and tradeoffs:** A balanced set keeps cohesive ownership while limiting mapping overhead; fine-grained domains maximize isolation but create many shallow interfaces and coordination points for a private system; coarse domains reduce initial structure but mix independently changing research, valuation, portfolio, recommendation and workflow rules.
- **User answer:** 1 — use the balanced domain-module split.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-079 and refines REQ-001. The architecture will use seven L1 domains with cohesive L2 ownership while retaining one FastAPI and PostgreSQL deployment.
### DISC-062: Select cross-module coordination model

- **Situation:** A single user action can affect several owners. For example, accepting a Recommendation records the decision immediately, may update a Workflow item, and may later produce a notification. The architecture must decide which results commit together and which may complete safely in the background without allowing modules to read one another's private PostgreSQL tables.
- **Question:** Should cross-module work use a hybrid of synchronous application flows plus durable events, direct module calls over shared tables, or event-only coordination?
- **Options and tradeoffs:** Hybrid coordination commits user-visible invariants synchronously and writes a PostgreSQL outbox in the same transaction for retryable background effects; it adds explicit commands, snapshots and event contracts. Direct calls and shared-table access are initially simpler but couple ownership and make changes unsafe. Event-only coordination maximizes isolation but introduces eventual consistency, compensating actions and more difficult user feedback for trading and allocation operations.
- **User answer:** 1 — use synchronous core operations plus durable background events.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-080 and refines REQ-001, REQ-011, REQ-031 and REQ-032. User-visible invariants commit atomically; retryable side effects use PostgreSQL outbox/jobs and idempotent workers.
### DISC-063: Select browser-to-server API style

- **Situation:** The responsive React UI needs a stable contract for lists, detail views, version-conflict handling, commands and validation errors. The API style determines generated documentation, client typing, caching, authorization review and testing complexity.
- **Question:** Should v1 use resource-oriented JSON HTTP APIs described by OpenAPI, GraphQL, or a hybrid of REST plus GraphQL?
- **Options and tradeoffs:** OpenAPI JSON endpoints fit FastAPI directly, make authorization and command semantics explicit, generate TypeScript types and are straightforward to test; some screens may require purpose-built read endpoints. GraphQL gives flexible field selection but adds schema/resolver authorization, query-cost and caching complexity. A hybrid provides both but duplicates conventions and infrastructure before the private system has evidence that both are needed.
- **User answer:** 1 — use JSON HTTP APIs described by OpenAPI.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-081 and refines REQ-001, REQ-032, REQ-034 and REQ-035. FastAPI owns the contract, TypeScript types are generated, and commands, conflicts and errors are explicit.
### DISC-064: Select PostgreSQL ownership isolation

- **Situation:** All seven L1 domains use one PostgreSQL instance so synchronous core flows can commit atomically. The physical layout must still make it difficult for one module to bypass another module's rules by directly reading or writing its tables.
- **Question:** Should the single database use one PostgreSQL schema per L1 domain, one shared public schema with naming conventions, or a separate database per domain?
- **Options and tradeoffs:** Per-domain schemas provide visible ownership, scoped migration paths and grants while preserving one backup and cross-schema transactions; they require explicit schema-qualified access and governance for cross-domain references. One public schema is simpler but ownership is only a coding convention and accidental joins/writes are easier. Separate databases maximize isolation but remove simple atomic transactions and add deployment, backup and consistency complexity unsuitable for v1.
- **User answer:** 1 — use one PostgreSQL schema per L1 domain in a single database.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-082 and refines REQ-001, REQ-008, REQ-013, REQ-031 and REQ-046. Domain schemas provide enforceable ownership while preserving atomic transactions and one backup/restore unit.
### DISC-065: Select frontend state architecture

- **Situation:** The responsive React UI combines Server-owned records, URL-addressable list/detail state, unsaved form drafts and temporary interaction state. Without a fixed ownership rule, the browser can create multiple stale copies of Thesis, Recommendation, Portfolio or Workflow data and appear to disagree with the Server.
- **Question:** Should frontend state use separated server/URL/local ownership, one central global application store, or independent page-local fetching and state?
- **Options and tradeoffs:** Separated ownership keeps Server records in one query cache, search/filter/pagination/detail selection in the URL, and only drafts or transient controls locally; it requires consistent query keys and invalidation rules. A central global store provides one client API but duplicates Server domain state and adds synchronization logic. Page-local fetching is simple per screen but duplicates requests and loses list/detail continuity and conflict handling.
- **User answer:** 1 — separate Server, URL and local/draft state ownership.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-083 and refines REQ-032, REQ-034, REQ-035, REQ-036 and REQ-053. Server data has one cache authority, navigation is URL-addressable, and only drafts or transient controls stay local.
### DISC-066: Select worker process topology

- **Situation:** Collection, AI analysis and email delivery have different latency, failure, secret and resource profiles. They share domain/application code but must not block one another or the Web/API process on the Linux Server VM.
- **Question:** Should v1 run one shared backend image as separate API, collector, AI and email containers/processes, combine all jobs into one worker process, or maintain separate codebases/images for every worker type?
- **Options and tradeoffs:** Separate processes from one versioned image isolate failures and resource limits while reusing exactly the same domain contracts and deployment version; Compose has more services to monitor. One combined worker is simpler to start but a slow AI call or crash can delay collection and email. Separate codebases/images maximize deployment independence but duplicate contracts, builds and release coordination for a single-VM private system.
- **User answer:** 1 — use one versioned backend image with separate API, collector, AI and email processes/containers.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-084 and refines REQ-001, REQ-010, REQ-011, REQ-051 and REQ-052. Processes share contracts but have isolated queues, limits, health and secrets.
### DISC-067: Select job concurrency and ordering policy

- **Situation:** Multiple jobs may target the same company or record. For example, an Evidence item can be corrected while an older AI analysis is still running. The queue must allow unrelated companies to run in parallel without allowing an older result to overwrite a newer state.
- **Question:** Should jobs use parallel leased claims with per-subject serialization and version checks, one global FIFO worker, or unrestricted parallel execution?
- **Options and tradeoffs:** Leased parallel claims let workers use PostgreSQL row locking to claim different jobs, while aggregate/subject keys and record-version checks serialize only conflicting work and reject stale output; this adds lease-expiry and ordering rules. One global FIFO is easiest to reason about but one slow job delays every company and queue. Unrestricted parallelism has highest throughput but creates races, duplicate side effects and stale-result overwrite risk.
- **User answer:** 1 — use parallel leased claims with per-subject serialization and version checks.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-085 and refines REQ-003, REQ-010, REQ-011, REQ-051 and REQ-052. Unrelated work runs concurrently; stale results and duplicate side effects cannot become current state.
### DISC-068: Select current-state and history persistence model

- **Situation:** ThesisTrace must load current screens efficiently while retaining who changed what, previous versions, source corrections, decisions and outcomes. The architecture must decide whether current state is stored directly, reconstructed entirely from events, or kept without a trustworthy domain history.
- **Question:** Should v1 keep normal relational current-state tables plus append-only domain/audit history, use full event sourcing, or keep only current state with ordinary application logs?
- **Options and tradeoffs:** Relational current state plus append-only history gives simple queries and constraints while preserving traceability; write flows must atomically update state and append events. Full event sourcing makes events the sole source of truth and maximizes replay but greatly expands projection, migration, debugging and correction complexity. Current state plus ordinary logs is simplest but logs cannot reliably support domain reconstruction, immutable decision history or audit validation.
- **User answer:** 1 — use relational current-state tables plus append-only domain/audit history.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-086 and refines REQ-002, REQ-003, REQ-031, REQ-032 and REQ-048. Current records remain efficient while every modifying flow atomically appends immutable history.
### DISC-069: Select repository folder organization

- **Situation:** The seven L1 domains now have explicit ownership. The source tree must make those boundaries obvious to developers and architecture tooling; a global controllers/services/models/repositories layout would scatter one feature across the repository and invite unrelated modules to share internal code.
- **Question:** Should backend and frontend use domain/feature-first vertical folders, global technical-layer folders, or separate top-level packages for every domain?
- **Options and tradeoffs:** Domain/feature-first folders keep each domain's API/application/domain/infrastructure parts together and mirror frontend features while a small L0 application area owns cross-domain flows; this adds a repeated internal template. Global technical layers look familiar but mix every domain in shared folders and weaken ownership. Separate packages provide strongest packaging barriers but add build, dependency and release overhead without separate deployment needs.
- **User answer:** 1 — use domain/feature-first vertical folders.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-087 and refines REQ-001, REQ-032 and REQ-053. Backend and frontend paths mirror owned capabilities; L0 flows own orchestration and shared code remains deliberately small.
### DISC-070: Select Python PostgreSQL access stack

- **Situation:** The backend needs typed aggregate persistence, explicit transactions, schema-qualified migrations, PostgreSQL queue locking and efficient reporting queries. With at most 10 users and isolated workers, correctness and understandable transaction lifetime matter more than maximizing concurrent database operations.
- **Question:** Should v1 use SQLAlchemy 2 ORM/Core plus Alembic with short-lived synchronous units of work, use asynchronous SQLAlchemy throughout, or use raw Psycopg SQL for all persistence?
- **Options and tradeoffs:** A typed SQLAlchemy ORM/Core hybrid maps aggregates and ordinary CRUD while allowing explicit SQL/Core for queues and reports; Alembic manages migrations, and synchronous request/job-scoped sessions keep transaction ownership simple. Async SQLAlchemy can increase I/O concurrency but requires strict one-session-per-task discipline and more lifecycle/testing complexity without a demonstrated load need. Raw Psycopg gives maximum SQL control but requires hand-written mapping, change tracking and migration conventions across every domain.
- **User answer:** 1 — use SQLAlchemy 2 ORM/Core plus Alembic with short-lived synchronous units of work.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-088 and refines REQ-001, REQ-011, REQ-031 and REQ-046. Typed repositories and explicit PostgreSQL queries share one transaction model, with no database transaction held across external I/O.
### DISC-071: Select deterministic policy implementation style

- **Situation:** Evidence stages, Hard anomaly classification, valuation, exposure caps, sizing and Workflow priority are safety-relevant product algorithms. They must be reproducible from saved inputs and versions, explain their outcome, remain independent of AI prose and evolve without silently changing historical recommendations.
- **Question:** Should these algorithms use explicit pure policy functions with versioned inputs/results and decision traces, a generic database-configurable rules engine/DSL, or imperative rules distributed across services, ORM hooks and SQL?
- **Options and tradeoffs:** Explicit policy modules make each algorithm deterministic, typed, independently testable and able to emit a structured decision trace; adding a new policy version requires code and review. A generic rules engine allows runtime configuration but introduces a second language, complex validation and the risk of unsafe rule combinations. Distributed imperative rules are quick initially but make execution order, coverage and historical reproducibility difficult to prove.
- **User answer:** 1 — use explicit pure policy functions with versioned inputs/results and decision traces.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-089 and refines REQ-003, REQ-005, REQ-006, REQ-007, REQ-037 and REQ-052. Safety-related algorithms become deterministic modules with formal Algorithm Design Records and fail-closed tests.
### DISC-072: Select policy-version activation and re-evaluation behavior

- **Situation:** A new valuation, anomaly, exposure or priority policy may correct or improve future decisions. Historical Recommendation and decision records must remain reproducible, while open/current items may need an explicit re-evaluation under the new policy.
- **Question:** Should policy versions be immutable and explicitly activated with opt-in re-evaluation, automatically replace and recompute all historical/current results, or remain editable database rows without immutable version identities?
- **Options and tradeoffs:** Immutable code-defined versions with explicit activation preserve history; new events use the active version and re-evaluation creates a new linked result without overwriting the old one. Automatic global recomputation keeps everything on the newest logic but silently changes historical meaning and can generate widespread actions. Editable rules are convenient but cannot reliably reproduce which exact semantics produced a saved decision.
- **User answer:** 1 — use immutable policy versions, explicit Owner activation and opt-in linked re-evaluation.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-090 and refines REQ-003, REQ-005, REQ-006, REQ-007, REQ-037 and REQ-048. New policy versions affect new evaluations; historical results remain unchanged and re-evaluation creates a new traceable record.
### DISC-073: Select runtime secret delivery model

- **Situation:** API, collector, AI and email processes need different subsets of Cloudflare, Gmail, AI, backup and field-encryption secrets. Secrets must remain outside Git, images, database dumps, logs and browser responses, and compromise of one worker should not automatically expose every credential.
- **Question:** Should v1 use host-managed file-mounted secrets scoped per container, a shared `.env` file injected into every service, or add a dedicated network secret-management service?
- **Options and tradeoffs:** Host-managed root-owned secret files mounted read-only only into required containers provide least privilege without another always-on service; rotation requires an operational procedure and targeted restart. A shared `.env` is easy but exposes all secrets broadly through process/container configuration and encourages over-sharing. A dedicated secret manager provides dynamic leases and centralized rotation but adds a new critical service, unseal/recovery process and backup dependency for a single private VM.
- **User answer:** 1 — use host-managed root-owned secret files mounted read-only and scoped per container.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-091 and refines REQ-001, REQ-004, REQ-010, REQ-012, REQ-013 and REQ-045. Secrets stay outside code/data artifacts, each process receives least privilege, and rotation is explicit and auditable.
### DISC-074: Select encryption-key recovery custody

- **Situation:** The production VM needs runtime keys for sensitive fields and encrypted backups, but loss of the VM or its disk must not make every B2 backup permanently unreadable. Keeping recovery keys beside the encrypted backup defeats separation if the backup account is compromised.
- **Question:** Should recovery material have two independently stored offline copies separated from the VM and B2 credentials, one offline copy, or be bundled beside each encrypted backup?
- **Options and tradeoffs:** Two independent offline copies reduce single-loss risk and remain separated from ciphertext and storage credentials; they require inventory, access control and periodic recovery drills. One copy is simpler but its loss or corruption permanently destroys recoverability. Bundling the key with backups simplifies restore but lets compromise of the same location expose both ciphertext and decryption capability.
- **User answer:** 2 — retain one offline recovery copy.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-092 and refines REQ-013 and REQ-014. Monthly drills must prove the single copy works, while the Owner explicitly accepts that loss or corruption of that copy can make encrypted data permanently unrecoverable.
### DISC-075: Select observability depth

- **Situation:** A private system still needs to distinguish a healthy but idle worker from failed collection, stalled AI, email backlog, database pressure, Access/Tunnel failure or stale official data. Observability must support diagnosis without copying investment content or secrets into telemetry.
- **Question:** Should v1 use balanced structured logs, metrics, health/readiness and targeted traces, keep only container/application logs, or deploy a full high-volume centralized tracing/log analytics stack?
- **Options and tradeoffs:** Balanced observability records redacted structured events with correlation IDs, bounded operational metrics, dependency health and traces only for selected cross-process flows; it supports alerts and diagnosis at moderate storage/CPU cost. Logs only have the smallest footprint but cannot reliably detect backlog, freshness SLO or stuck leases before a user notices. A full analytics stack offers deepest search and traces but consumes substantial single-VM resources and increases retention/security operations.
- **User answer:** 1 — use balanced structured logs, metrics, health/readiness and targeted traces.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-093 and refines REQ-001, REQ-010, REQ-011, REQ-012, REQ-051 and REQ-052. Production gains bounded diagnostic signals and operational alerts without copying investment content or secrets into telemetry.
### DISC-076: Select single-VM release and migration strategy

- **Situation:** API, workers, PostgreSQL schema and generated contracts must remain compatible during a release. A single 4 GiB production VM cannot assume enough capacity for a permanent duplicate stack, and a failed or destructive migration cannot be made safe merely by restarting an old container image.
- **Question:** Should releases use a planned maintenance window with staged preflight/backup/migration/health gates and expand-contract migrations, replace containers in place with latest migrations, or run a full blue-green duplicate stack on the same VM?
- **Options and tradeoffs:** A gated maintenance release temporarily blocks writes, verifies backup and migration compatibility, deploys one version set, resumes only after health/smoke checks, and uses expand-contract across releases for destructive changes; it accepts bounded downtime. In-place latest is fastest but can leave mixed code/schema versions or no safe rollback. Blue-green minimizes downtime but duplicates application/database resources and still requires careful data migration on the constrained VM.
- **User answer:** 1 — use planned maintenance with staged release, migration and health gates.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-094 and refines REQ-001, REQ-011, REQ-012, REQ-013 and REQ-046. Production favors one compatible code/schema set and bounded downtime; destructive changes use expand-migrate-contract.
### DISC-077: Select automated test-layer strategy

- **Situation:** Pure policies, PostgreSQL constraints/transactions, provider adapters, OpenAPI contracts and responsive browser flows fail in different ways. A test strategy dominated by mocks can miss PostgreSQL behavior, while a strategy dominated by browser tests is slow and makes failures difficult to localize.
- **Question:** Should v1 use layered automated tests with real PostgreSQL integration and fake external ports, mostly mocked unit tests, or mostly end-to-end tests against a full stack?
- **Options and tradeoffs:** Layered testing puts most cases in pure unit/property tests, uses ephemeral real PostgreSQL for repositories/RLS/migrations/queue concurrency, contract suites for external adapters, and a focused set of API/Playwright E2E flows; it needs multiple fixtures but gives localized evidence. Mostly mocked tests run fastest but cannot prove SQL constraints, transaction races, RLS or migration behavior. Mostly E2E tests exercise the stack but are slower, more brittle and insufficient for combinatorial policy boundaries.
- **User answer:** 1 — use layered automated tests with real PostgreSQL integration and fake external ports.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-095 and refines AC-001 plus every mapped acceptance criterion. Each risk receives a primary evidence layer, and PostgreSQL-specific behavior cannot pass through mocks or SQLite.
### DISC-078: Select implementation sequencing strategy

- **Situation:** The system has many modules and acceptance gates but no product source yet. Building all database/backend layers first delays UI and contract feedback; building all UI first requires fake domain behavior; implementing requirements in document order may postpone the highest-risk evidence/anomaly/transaction seams.
- **Question:** Should implementation proceed as risk-first thin vertical slices with a walking skeleton, complete backend then frontend, or build infrastructure/database foundations before all product flows?
- **Options and tradeoffs:** A walking skeleton first proves build, migration, auth boundary, one OpenAPI query/command, PostgreSQL transaction/outbox, worker and responsive UI path; subsequent slices close the riskiest end-to-end behaviors one at a time. Backend-first gives stable APIs later but postpones usability and generated-client feedback. Infrastructure-first creates reusable foundations early but risks speculative abstractions without a complete consumer flow.
- **User answer:** 1 — use a walking skeleton followed by risk-first vertical slices.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-096 and refines REQ-001, REQ-007, REQ-031, REQ-032 and REQ-053 by fixing the first executable path, risk order, integration cadence and per-slice definition of done.
### DISC-079: Select the pre-code formal architecture package

- **Situation:** The major runtime, domain, data, UI, deployment and validation choices are now settled, but the repository does not yet contain the formal schema 2.2.0 architecture package needed to prove boundaries, ownership and flows before product source is written.
- **Question:** How complete must the formal architecture package be before the first walking-skeleton product code is allowed?
- **Options and tradeoffs:** A complete minimum authoring-first package defines the system manifest, L0–L3 boundaries, Type Catalog, ports/events, state ownership, executables, critical flows, proposed ADRs and Algorithm Design Records, generates deterministic views and passes the architecture gate; it costs more upfront but makes the implementation contract reviewable and limits structural rework. An L0/L1-only package is faster initially but leaves types, state and cross-module flow decisions to emerge during coding, weakening the pre-code gate. Code-first reverse engineering gives the fastest first files but cannot demonstrate implementation readiness and makes architecture documentation descriptive rather than governing.
- **User answer:** 1 — complete the minimum but full formal architecture package and pass its gate before product code.
- **Explicit rationale:** not stated
- **Resulting impact:** Adds DEC-097 and refines DEC-096 and REQ-001 by making the authoring-first architecture package and design gate mandatory before the first product slice.
### DISC-080: Select the first user-visible walking-skeleton flow

- **Situation:** The architecture package scope is fixed, but the walking skeleton still needs one real user journey to determine the first UI route, API command/query, PostgreSQL state transition, outbox event, worker responsibility and end-to-end test. An overly narrow infrastructure-only path would not prove product value; an oversized anomaly path would pull most high-risk policy work into the first slice.
- **Question:** Which user-visible journey should be the first walking-skeleton flow?
- **Options and tradeoffs:** An authenticated Owner manually selects or creates a Company, submits an Evidence URL, and watches a collector worker retrieve and persist an immutable source snapshot/provenance or an explicit failure state; this proves the core research intake, deduplication, transaction/outbox, worker and responsive UI path with no AI decision yet, but requires a bounded external-source adapter from the start. An Access-and-role administration journey proves Cloudflare identity, sessions, RLS and audit first and has the strongest security-first benefit, but does not exercise the research domain or background worker. A Hard-anomaly journey reaches the highest-risk feature immediately, but depends on source taxonomy, E-stage policy, critic, versioned fixtures and safety workflow, making the first slice large and slow to diagnose.
- **User answer:** 1 — start with authenticated Company selection/creation and Evidence URL intake through the collector worker to a visible terminal status.
- **Explicit rationale:** The user accepted the clarification that this selects only the first fully operable development path, not the system's final feature priority.
- **Resulting impact:** Adds DEC-098 and refines DEC-096, REQ-001, REQ-002, REQ-008, REQ-011, REQ-012 and REQ-032 by fixing the first concrete end-to-end product journey while explicitly deferring AI, E-stage and Hard-anomaly decisions to later slices.

### DISC-081: Select the versioned URL normalization policy

- **Situation:** ALG-0001 implementation review found that non-empty path/query equivalence and historical normalization-version ownership were not explicit. These rules determine whether two submitted URLs share one source-of-record and whether historical provenance remains reproducible after policy changes.
- **Question:** Should v1 preserve non-empty path/query spelling, apply RFC path normalization, or also normalize query ordering and tracking parameters?
- **Options and tradeoffs:** Conservative normalization only merges clearly equivalent HTTPS authority, fragment and empty-root forms and minimizes false merges; RFC path normalization merges more aliases but can conflict with source-specific path handling; aggressive query normalization improves deduplication but risks merging order-sensitive, duplicate-parameter or source-specific resources.
- **User answer:** 1 — use conservative normalization.
- **Explicit rationale:** The user selected the recommended policy after asking what behavior the decision affects; no additional rationale was provided.
- **Resulting impact:** Adds DEC-099 and refines REQ-002 and AC-002. `url-normalization-v1` preserves non-empty path/query representation, is persisted with canonical identity and snapshots, and requires a new version plus explicit migration/coexistence handling for future policy changes.
## Acceptance Criteria

| ID | Requirements | Scenario | Validation Method | Evidence |
| --- | --- | --- | --- | --- |
| AC-001 | REQ-001 | 從全新 Ubuntu Server 依版本鎖定設定部署本地 application stack 與 Cloudflare ingress。 | Docker Compose config 驗證、容器健康檢查、Cloudflare Access/Tunnel contract test、origin 防火牆及 Internet/LAN port 掃描；只有 Access 保護 hostname 可達 Web/API，origin inbound、SSH、PostgreSQL、Docker API 與管理子網均不可達。 | Pending execution |
| AC-002 | REQ-002 | 同一官方事件以 hostname 大小寫、明確 `:443`、fragment、空 path、不同非空 path spelling／percent encoding、query 順序或重複參數等 URL 形式重複取得，且非官方來源缺少必要 provenance；其後以新 normalization policy version 與既有 v1 資料並存。 | Adapter golden/property tests 驗證 `url-normalization-v1` 冪等、只合併明確等價形式並保留非空 path/query；來源去重整合測試與資料庫 constraint tests 驗證 URL key、content hash、lineage、policy version、歷史 key 不被重解讀及版本 coexistence／migration。 | Pending execution |
| AC-003 | REQ-003 | 對固定來源快照執行 E0 至 E6 各階正例、缺少前置閘門負例、直接跳級、更正、撤銷、來源失效、兩季延續性及 21:00 停機後恢復。 | 決策表 unit/property tests 與 Fake Clock 整合測試；同一快照必須產生唯一階段，缺少任一必要閘門不得升級，AI 輸出不得直接改寫階段，重算、摘要、即時事件與補寄必須冪等。 | Pending execution |
| AC-004 | REQ-004 | OpenAI 成功、OpenAI provider-wide 失敗、Claude 失敗、critic 失敗與 schema 無效。 | Provider contract suite 與 fail-closed orchestration tests；所有 schema、引用、曝險與 abstain 檢查必須 100% 通過。 | Pending execution |
| AC-005 | REQ-005 REQ-006 | Owner 選擇 PE、PB、abstain 或未確認方法，選擇 6、12、24 個月或使用 12 個月預設；測試自身歷史與 peer group 候選倍數不同、peer group 4/5/12/13 家、重複或不合格同業、名單改版、未選來源、company_history、peer_group、abstain、無效分母、樣本不足、新季報、重大事件、90 天失效，以及費稅、股息、年化、曝險、預算衝突與分批獲利。 | Deterministic unit/property tests、Fake Clock 與固定黃金案例；少於 5 或超過 12 家、未逐一確認、重複、包含目標公司、方法不一致或資料無效時 peer_group 必須 abstain；Recommendation 必須保留不可變 peer snapshot。兩組計算、差異及 Owner 理由不得自動混合；歷史分布、樣本排除和來源必須可重現，target date 必須正確，AI 不得改寫方法、期間、peer 名單或來源選擇；測試 6/12/24 個月、零與負 holding_days、手續費率、最低手續費、賣出證交稅、股息、Cost Profile 版本切換、decimal rounding、完整與缺漏的持股／現金／官方價格、跨 Thesis 同證券合併、交易後 Portfolio NAV、官方主要產業、自訂零／單一／重疊風險主題、任一分類 30% 邊界、分類改版、缺少官方分類、原始 1.5x/1x/0.5x 向下限制、現有超限、減碼與 Hard invalidation，公式必須符合 REQ-005 且歷史 Recommendation 不得因新 Cost Profile 改變；未確認、abstain、不適用、資料不足、資料失效、Cost Profile 未設定或最低報酬未設定時必須輸出 0x 且不產生目標價或買進建議；任何買進結果不得超過 security、任一官方產業、任一自訂風險主題或 cash hard cap；重疊主題必須各自完整計入，缺少官方分類或現有超限不得產生正倍率，AI 不得啟用或修改自訂主題，歷史 Recommendation 不得因分類或風險政策新版本改變。 | Pending execution |
| AC-006 | REQ-007 | 在至少 10 家公司、5 個官方產業的版本化 100 案例中分類 A/B/C 與評分線索，涵蓋 20 個單一 A Hard、20 個雙獨立 B Hard、20 個證據不足、15 個同源／匿名／衝突、15 個 critic／引用／主體／時間故障及 10 個市場／novel event；其後在正式 Linux Server VM 執行連續 30 天 shadow mode。 | Source-lineage、deterministic policy、critic contract 與整合測試：40/40 Hard 正例正確，60/60 非 Hard 無 Hard，分類、去重、評分及 fail-closed 100% 符合標註。shadow 期間保存每個 would-be Hard、來源快照、policy/模型/prompt 版本、critic 結果與 Owner 標註，不寄正式退出建議；任何 false Hard 修正後重置 30 天，模型／prompt／policy 變更重跑 100 案例；完成後須 Owner 明確啟用。 | Pending execution |
| AC-007 | REQ-008 | 以核准與未核准的 Google email、同網域但未列名 email、核准與未核准的 Cloudflare account、未通過 MFA、相同 email 但不同 provider identity 登入；以可控時鐘測試登入後未滿、等於及超過 8 小時的請求、登出及偽造較長效 ThesisTrace cookie；停用或替換 identity；由 Owner 使用緊急備援；並由 Learner 透過 UI、API、匯出與猜測 ID 嘗試讀取 Owner 資料。 | Cloudflare Access policy export/schema check、identity/JWT/session contract tests、PostgreSQL RLS integration tests、API authorization tests、audit tests 與 Playwright E2E；只有逐一核准的 Google identity 可一般登入，只有明確綁定同一 Owner 的 Cloudflare identity 可走備援，domain-wide、其他 account member、未通過 MFA、停用或 provider 混淆一律拒絕；一般 session 未滿 8 小時可持續使用，等於或超過 8 小時的下一次存取必須重新完成 Google 與 MFA，Server session 不得超過 Access token 且登出後不可重用；備援不得提升權限，每次 identity 管理與備援使用均可稽核，所有越權操作必須拒絕且不洩漏資料存在性。 | Pending execution |
| AC-008 | REQ-009 | 合法 CSV、欄位錯誤、重複交易、無法配對建議及手動輸入。 | Import parser unit tests、preview/confirm integration tests 與 transaction reconciliation tests。 | Pending execution |
| AC-009 | REQ-010 | Gmail 逾時、暫時失敗、程序重啟、重複投遞與永久失敗。 | Fake EmailDeliveryPort 與 outbox integration tests，驗證 1/5/30 分鐘重試、冪等及 dead-letter。 | Pending execution |
| AC-010 | REQ-011 | AI 呼叫長時間延遲，同時持續產生來源事件與待寄郵件。 | 隔離 worker load test 與 freshness metrics；AI worker 不得阻塞下一輪採集或郵件投遞。 | Pending execution |
| AC-011 | REQ-012 | 以未登入、允許 identity、拒絕 identity、過期／錯誤 audience／錯誤 issuer／偽造 header／失效簽章 JWT 存取所有 Web/API path；移除或誤設 Access application、加入 Bypass path、停止 cloudflared、輪替 signing key／tunnel credential，並嘗試由 Internet 直連 origin、SSH、PostgreSQL、Docker API 與管理子網。 | Cloudflare Access policy export/schema check、tunnel ingress validation、JWT verifier contract/integration tests、secret scan、故障注入與 Internet/LAN port scan；未通過完整 Access 與 app JWT 驗證一律拒絕，不得存在 Bypass／未覆蓋 path，key 更新須正確且不可驗證時 fail closed，只有本地 Caddy Web/API 可由 tunnel 抵達，所有 origin inbound 與非 Web service 必須不可達。 | Pending execution |
| AC-012 | REQ-013 | 從一份受 Object Lock 保護的加密備份復原至全新隔離 PostgreSQL。 | 每月 restore drill，記錄解密、migration、資料列數、關聯與雜湊驗證結果。 | Pending execution |
| AC-013 | REQ-014 | 主機磁碟未加密且秘密與敏感欄位採補償控制。 | Security checklist、秘密掃描、欄位加密測試及風險揭露人工簽核。 | Pending execution |
| AC-025 | REQ-031 | 建立、暫停、恢復、失效及關閉 Thesis；產生多版 Recommendation；接受、拒絕、延後及逾期；將買進分配至單一／多個 Thesis 與 independent 桶；指定賣出桶；測試分配不足、超額、超賣、交易更正、股票分割、減資及股票股利；保存 Outcome 與 Reflection。 | Domain state-machine unit/property tests、PostgreSQL constraint/transaction integration tests 及 API tests；非法轉移與分配合計不等於成交股數必須拒絕，不得跨桶超賣或自動 FIFO，不可變紀錄不得更新或刪除，更正與公司行動後各桶及證券總部位必須正確，風控合併全部桶，Outcome 可按桶歸因，所有目前狀態均可追溯至完整 audit events，失效不得被 reflection pending 阻塞，關閉不得缺少 Outcome 與 Reflection。 | Pending execution |
| AC-026 | REQ-032 | 同一項跨公司待辦可從工作流程開啟對應公司的正確 Evidence／Thesis／Recommendation 等位置，處理後回到工作流程；另以直接公司入口查看同一紀錄。模擬 client 偽造 E 階段、Hard anomaly、估值、風控、狀態轉移或權限結果，以及兩個 UI 入口同時提交互相衝突的更新。 | Navigation component tests、Playwright E2E、API contract/integration tests 與 PostgreSQL transaction tests；兩入口必須讀取同一 record/version ID 且處理狀態一致，不得複製領域紀錄；重新整理或改用另一入口後結果不得分歧；Server 必須拒絕 client 偽造或過期版本並回傳可辨識的衝突，不得信任 client 計算或權限判定。 | Pending execution |
| AC-027 | REQ-033 | 對每一種需人工處理的觸發建立 Action Item，重送相同事件及版本，完成、忽略、延後與重新開啟事項，建立手動追蹤事項，並產生不需要處理的一般資訊事件。 | Deterministic rule unit/property tests、PostgreSQL uniqueness/transaction tests、API tests 與 Playwright E2E；同一觸發與來源版本最多一個未結項 Action Item，一般事件不得出現在行動收件匣，所有合法狀態轉移及處理理由可稽核，dismissed 不得刪除或改寫底層領域紀錄，從待辦開啟的公司及紀錄版本必須正確。 | Pending execution |
| AC-028 | REQ-034 | 以多家公司、多類型、不同狀態、優先級及到期時間的 Action Items 載入首頁，依序點擊各摘要卡並組合搜尋、篩選、排序及分頁；在寬與窄畫面重複主要操作，並於查詢期間新增或完成一項待辦。 | API contract tests 與 Playwright responsive E2E；相同查詢時間點下摘要數量必須等於對應清單總數，權限外項目不得計入，篩選／排序／分頁結果必須穩定且由 Server 欄位決定；窄畫面不得水平捲動即可辨識並開啟待辦，並保留搜尋與核心篩選功能。 | Pending execution |
| AC-029 | REQ-035 | 在已套用搜尋、篩選、排序及分頁的收件匣開啟待辦，於寬畫面切換多項右側詳情、進入公司工作區再返回，並在窄畫面、重新整理、瀏覽器返回／前進及直接開啟詳情連結下重複操作；同時測試 Server 拒絕過期或無權操作。 | Route/component tests 與 Playwright responsive E2E；寬畫面必須保留清單，窄畫面必須使用完整詳情頁，兩者路由指向相同 Action Item；所有返回路徑必須恢復原查詢與可辨識的清單位置，深層連結必須載入正確授權內容，Server 拒絕時 UI 不得顯示已成功或保留錯誤的樂觀狀態。 | Pending execution |
| AC-030 | REQ-036 | 以未安裝 VPN／WARP 的桌機與手機瀏覽器通過 Cloudflare Access 執行主要流程，測試 Access／Tunnel／Server 中斷時的已開啟頁面與狀態變更、斷線期間重複操作及恢復連線；檢查瀏覽器儲存與 service worker/cache。 | Playwright responsive E2E、網路與 provider 故障注入、Access session/JWT test 及 browser-storage inspection；未驗證 identity 不得載入應用程式，斷線時所有狀態變更必須禁止且不得背景排隊，恢復後必須重新取得 Access identity 與 Server 狀態；Cache Storage、IndexedDB、localStorage 及 service worker 不得含領域或敏感 API 資料，靜態快取不得含使用者內容。 | Pending execution |
| AC-031 | REQ-037 | 對四個 system priority 產生項目，嘗試由 AI、UI、Owner 及未授權角色修改；對一般與 safety-locked 項目執行升降級，變更 policy 與 override 後重新評估未結項項目，並以相同優先級、不同到期時間／建立時間／ID 驗證穩定排序。 | Deterministic policy unit/property tests、PostgreSQL audit/constraint tests、API authorization tests 與 Playwright E2E；AI／client 欄位不得控制 system priority，Owner override 只影響本人且理由不可缺少，safety floor 不得被降低，歷史值與規則版本必須可追溯，完成項目不得被新 policy 改寫，同一資料集及 policy 必須產生穩定順序。 | Pending execution |
| AC-032 | REQ-038 | 分別觸發 Hard anomaly、active Thesis 因 A/B 證據更正／撤銷／失效而降級或 invalidated、已確認成交未匯入、對帳差異、分配不足／超額／超賣，以及持股／現金／官方價格缺失或失效；嘗試以 Owner override、UI 欄位及新 policy 降低或解除 safety lock，再以底層解決、superseding record 與可稽核誤觸發更正解除。 | Deterministic policy/state-machine unit tests、PostgreSQL constraint/transaction tests 與 API authorization tests；前兩類有效優先級不得低於 critical，後兩類不得低於 high，非列舉項目不得自動鎖定；只有底層條件合法解決、取代或更正才能解除，所有前後狀態與原因必須留在 audit history。 | Pending execution |
| AC-033 | REQ-039 | 以 Owner、兩名 Learner、primary Admin 及另一 Admin 建立各類自動與手動待辦，偽造 assignee、嘗試領取／關注／轉派及猜測他人 Action Item ID；再測試缺少或重複 primary Admin、停權資料 Owner，以及更換 primary Admin。 | Deterministic assignment tests、PostgreSQL RLS/constraint/transaction tests、API authorization tests 與 Playwright E2E；每項待辦只能由規則得到唯一合法 assignee，client／AI 不得指定或改寫，其他帳號不得得知項目存在；缺少唯一 assignee 必須 fail closed 且可營運告警，primary Admin 更換時只有營運待辦可完整稽核地重新歸屬，個人資料待辦不得轉交。 | Pending execution |
| AC-034 | REQ-040 | 對 safety-locked 項目嘗試 defer、dismiss、直接 complete 及僅標示 in_progress；對一般項目設定未來、現在及過去 defer_until，時間到期，dismiss 缺少／具有理由，並在延後期間加入提高優先級或改變處理內容的新來源版本；重送每個要求。 | State-machine unit/property tests、Fake Clock、PostgreSQL transaction/audit tests、API authorization tests 與 Playwright E2E；非法安全轉移與無效時間必須拒絕，in_progress 安全項目仍計入未結項摘要，時間到期或 material change 必須冪等回到 pending，dismiss 不得更動來源紀錄，重複要求不得產生重複事件或通知，所有轉移保存 Server time、actor、版本及理由。 | Pending execution |
| AC-035 | REQ-041 | 對 completed 與 dismissed 項目依序重送相同事件、只變更來源版本但內容相同、加入 material evidence、再次發生相同底層條件及產生不同處理需求；檢查新舊項目導覽，並以不同使用者嘗試讀取關聯舊項目。 | Deterministic fingerprint/property tests、PostgreSQL uniqueness/relationship tests、API authorization tests 與 Playwright E2E；重送及非實質版本變更不得產生新項目，material change／recurrence 必須建立新 ID 並正確連結且重新計算 ownership／priority／safety／通知，不得繼承舊狀態或 override；舊項目不可變，關聯導覽不得繞過原權限。 | Pending execution |
| AC-036 | REQ-042 | 以 Owner、Learner、Admin 開啟同一家公司 Overview 及每個分頁，直接貼入分頁與 record/version 路由、重新整理、返回／前進、切換寬窄畫面，並猜測不存在、他人或無權紀錄；同步改變 E 階段、Action Item、valuation validity 與 Owner 持倉。 | API field-level authorization/RLS tests、route/component tests 與 Playwright responsive E2E；共用標頭與 Overview 必須反映同一 Server snapshot/as-of，所有摘要連結指向正確分頁與版本；Owner-only 欄位不得出現在 Learner／Admin payload、DOM 或快取，無權與不存在不得洩漏差異，路由與窄畫面導覽不得遺失公司／分頁身分或允許功能。 | Pending execution |
| AC-037 | REQ-043 | 對同一證券建立零、一及多個 Owner／Learner Thesis，讓相同 Evidence 連結多個 Thesis，使用不同 invalidation、valuation、Recommendation、Decision 及交易 allocation，另加入 independent bucket；在各角色下檢查 Overview、卡片、詳情與公司彙總。 | PostgreSQL relationship/RLS tests、domain/API tests 與 Playwright E2E；不得產生隱含 primary／composite Thesis或複製 Evidence，所有 Thesis 欄位與績效保持獨立，Owner 公司持股與風控精確合併全部 buckets，單一 Thesis 卡片只顯示其 allocation/Outcome，角色過濾後的數量與 payload 不得洩漏不可見 Thesis。 | Pending execution |
| AC-038 | REQ-044 | 建立多條含 A／B／C、相同底層來源、支持／反駁／更正／撤銷／失效、AI 候選、critic 結果、事件／觀測時間逆序及 E0–E6 升降級的 Evidence Chains；組合搜尋、篩選、排序並在寬窄畫面展開時間軸。 | API snapshot/ordering tests、source-lineage and stage-policy integration tests 與 Playwright responsive E2E；chain 摘要必須等於 Server snapshot，時間軸以事件時間穩定排序並保留觀測時間，所有來源及 transition 可追溯至 URL/hash/snapshot/policy，AI 衍生內容不得呈現為 source-of-record，篩選不得改變 chain 或階段結果，窄畫面不得遺失 provenance。 | Pending execution |
| AC-039 | REQ-045 | 盤點並部署所有 application／worker／database 元件，模擬遠端入口供應商中斷、Server 重新啟動及惡意 client 嘗試直連 API／PostgreSQL；檢查本機與供應商側儲存，並執行加密 B2 備份例外。 | Compose/runtime inventory、network boundary tests、provider outage integration test、storage inspection 與 restore drill；除加密備份外所有 runtime 與領域持久資料只存在本地 VM，入口中斷不得損壞或遺失本地資料，無既定入口不得直連 API／PostgreSQL，恢復入口後所有請求仍通過相同 auth/RLS/audit。 | Pending execution |
| AC-040 | REQ-046 | 在備援 policy 停用時分別模擬 Google identity 正常與故障；由核准 Owner 與其他 Cloudflare account member 嘗試登入；由 Owner 手動啟用後測試缺少 MFA、未滿／等於／超過 30 分鐘、權限映射、主要登入修復、policy 停用、舊 session 重用及 recovery material 遺失。 | Cloudflare policy export/schema check、guided recovery drill、JWT/session contract tests、API authorization tests、audit tests 與 Playwright E2E；平時不得顯示或接受備援登入，只有核准 Owner 經 MFA 可在啟用窗登入且只能取得原 Owner 權限，首次登入必須產生 security audit 與 safety-locked 關閉事項，30 分鐘後、手動停用後或完成修復後的 session 均不可重用；無管理登入與 recovery material 時仍須 fail closed，任何 Bypass 或公開 origin 都使驗收失敗。 | Pending execution |
| AC-041 | REQ-047 | 從具有搜尋、複合篩選、排序、分頁與捲動位置的收件匣，依序以桌機及手機開啟一般與 safety-locked 待辦；在詳情執行開始、延後、忽略、priority override 及手動追蹤完成；再由待辦進入 Evidence、anomaly、Thesis、Valuation、Recommendation／Decision、Trade／allocation、Outcome／Reflection 的目標表單，分別完成、取消及以另一視窗先修改造成版本衝突。 | Route/component tests、API contract/concurrency tests 與 Playwright responsive E2E；待辦層級操作可在詳情完成且受既有 safety policy 約束，所有領域變更只能在正確公司、頁籤及 record/version 的完整工作區表單提交；完成或取消後必須恢復原查詢與位置並刷新待辦與摘要，直接入口與待辦入口不得產生重複領域紀錄，過期版本必須拒絕並提示重新載入，不得靜默覆寫。 | Pending execution |
| AC-042 | REQ-048 | 對每種 consequential action 取得預覽後，分別以正確確認、空白理由、錯誤角色、不同 actor、修改 payload、修改目標版本、重複使用、超過 5 分鐘及另一視窗先更新資料提交；同時對一般草稿與筆記寫入檢查不出現多餘確認。 | Domain/API contract tests、可控時鐘、PostgreSQL transaction/idempotency tests、authorization tests 與 Playwright E2E；影響摘要必須對應精確 action、版本與重要前後差異，只有未逾期且 actor／action／version／payload 全部相符的單次 challenge 加非空白理由可成功；成功時領域變更與 audit 原子提交，重送不重複，任何差異都拒絕並要求重新預覽；低風險儲存仍須驗證與稽核但不得跳出 consequential confirmation。 | Pending execution |
| AC-043 | REQ-049 | 依序編輯各種長文字草稿與所有結構化／正式欄位，測試停止輸入未滿／等於／超過 2 秒、慢速回應、失敗、重送、同時分頁衝突、送出中或失敗時離頁、網路中斷與恢復，以及草稿發布；檢查 browser storage 與背景請求。 | 可控時鐘的 component tests、API concurrency/idempotency tests、PostgreSQL revision tests、Playwright responsive E2E 與 browser-storage inspection；只有允許的長文字 draft 可 autosave，狀態文字必須反映 Server 實際結果，接受的 autosave 可追溯且不發布；所有結構化與正式欄位在明確儲存前不得改變 Server；衝突不得覆寫，離頁不得靜默遺失，離線內容不得持久化或背景排隊，恢復後未經明確重試不得送出。 | Pending execution |
| AC-044 | REQ-050 | 對每種通知事件填入公司／股票代號、類型及所有禁止欄位，包含惡意 HTML、超長文字、AI 輸出、URL 內容與 token；在 enqueue 後撤銷收件者權限，測試多人地址、附件、外部資源、deep link 未登入／錯誤角色及投遞失敗日誌。 | Template allowlist unit/property tests、snapshot tests、authorization-at-send integration tests、HTML sanitizer／URL contract tests、EmailDeliveryPort tests、log inspection 與 Access-protected E2E；輸出只可包含允許欄位，禁止資料不得出現在 subject、preview、text、HTML、URL、header、附件或 log，撤權後不得寄送，郵件只能單一授權收件者，deep link 未經完整登入及應用授權不得顯示待辦。 | Pending execution |
| AC-045 | REQ-051 | 以至少 100 個可控 publication／availability time 的 official fixture events 注入正常、9:59／10:00／10:01、29:59／30:00／30:01、五分鐘排程漂移、worker 壅塞、程序重啟、重複事件、無 timestamp、來源限流／故障與恢復 backlog；分別讓比例落在門檻上下。 | Fake Clock、scheduler/worker integration tests、PostgreSQL queue/outbox transaction tests、fault injection 與 SLO report assertions；只有 durable Evidence 加必要 Action Item／job 才算完成，rolling 30-day 的 reachable numerator/denominator 與分位數必須可重算且達 95%≤10 分鐘、99%≤30 分鐘；外部 outage 必須獨立且不可用來排除已可取得的慢事件，遲到與連續漏排程必須建立 Action Item，所有事件最終仍須處理且去重。 | Pending execution |
| AC-046 | REQ-052 | 執行 30 案例於 28／29／30 個 decision-field 一致、各種 safety／Hard anomaly／citation／schema／abstain 錯誤；執行 10 個 shadow tasks 並在第 1／9／10 個注入 major discrepancy；測試無 Owner 核准、model／prompt／schema／policy 改版、單次 timeout、個別 rate limit、provider-wide circuit breaker、Claude invalid output、OpenAI 恢復與重送。 | Versioned golden-suite runner、provider contract tests、shadow comparator、Fake Clock、circuit-breaker/fault-injection integration tests、PostgreSQL approval/audit/idempotency tests；未達 29／30、任何 safety 類錯誤、未連續通過 10 次或缺 Owner approval 都不得啟用；只有 provider-wide breaker 可觸發完整快照重跑，兩 provider 輸出不得混合，Claude 驗證失敗不得發布且必須建人工待辦，material change 必須撤銷核准並重新驗證。 | Pending execution |

| AC-047 | REQ-053 | 以具代表性的 Inbox、Action Item detail、Company Overview、Evidence Chain、Thesis cards、Valuation comparison、Recommendation confirmation、Trades、Outcome／Reflection、History、長繁體中文、長 URL、極端數字、錯誤、loading、empty、offline 及權限拒絕狀態，依序測試 360、390、768、1024、1440、1920、2560 CSS px；在 1280px 執行 200% text resize 與 400% browser zoom／320px-equivalent reflow；測試 light/dark/system、跨兩裝置保存主題、鍵盤-only、focus、screen reader、觸控、支援與不支援瀏覽器、局部二維表格、紅漲綠跌及字型網路請求。 | Story/component visual tests、Playwright Chromium/WebKit responsive E2E、支援版本 Chrome／Edge／Android Chrome／實機 iOS Safari release smoke、axe-core 加人工 WCAG 2.2 AA keyboard/focus/reflow/contrast/target-size checklist、NVDA 或 VoiceOver spot checks、DOM/network/font inspection 及 screenshot regression；所有主要流程在原生 360–2560px 與 zoomed 320px-equivalent 下不得有 page-level horizontal scroll、重疊、必要截斷、功能或資料遺失，局部二維 scroll 必須具名稱、提示、標頭關係及鍵盤可達性；摘要／詳情 record/version 一致，雙主題對比與狀態可辨識，主題跨裝置同步且 system 仍跟隨當前裝置，方向不只靠色彩，無第三方 font request，不支援瀏覽器顯示非阻斷提示；自動掃描零 critical/serious violations，人工 AA checklist 全部 PASS。 | Pending execution |

## Relationships

| Source | Relation | Target |
| --- | --- | --- |
| REQ-003 | depends_on | REQ-002 |
| REQ-003 | depends_on | REQ-010 |
| REQ-003 | depends_on | REQ-011 |
| REQ-005 | depends_on | REQ-004 |
| REQ-006 | refines | REQ-005 |
| REQ-007 | depends_on | REQ-002 |
| REQ-007 | depends_on | REQ-004 |
| REQ-008 | depends_on | REQ-001 |
| REQ-008 | depends_on | REQ-012 |
| REQ-010 | depends_on | REQ-011 |
| REQ-012 | refines | REQ-001 |
| REQ-013 | depends_on | REQ-001 |
| REQ-031 | depends_on | REQ-002 |
| REQ-031 | depends_on | REQ-004 |
| REQ-031 | depends_on | REQ-009 |
| REQ-032 | depends_on | REQ-003 |
| REQ-032 | depends_on | REQ-005 |
| REQ-032 | depends_on | REQ-006 |
| REQ-032 | depends_on | REQ-007 |
| REQ-032 | depends_on | REQ-031 |
| REQ-033 | depends_on | REQ-032 |
| REQ-033 | depends_on | REQ-031 |
| REQ-034 | depends_on | REQ-033 |
| REQ-035 | depends_on | REQ-034 |
| REQ-035 | depends_on | REQ-032 |
| REQ-036 | depends_on | REQ-001 |
| REQ-036 | depends_on | REQ-012 |
| REQ-036 | depends_on | REQ-032 |
| REQ-037 | depends_on | REQ-033 |
| REQ-037 | depends_on | REQ-007 |
| REQ-038 | depends_on | REQ-037 |
| REQ-038 | depends_on | REQ-006 |
| REQ-038 | depends_on | REQ-009 |
| REQ-038 | depends_on | REQ-031 |
| REQ-039 | depends_on | REQ-033 |
| REQ-039 | depends_on | REQ-008 |
| REQ-039 | depends_on | REQ-031 |
| REQ-040 | depends_on | REQ-038 |
| REQ-040 | depends_on | REQ-039 |
| REQ-041 | depends_on | REQ-033 |
| REQ-041 | depends_on | REQ-040 |
| REQ-042 | depends_on | REQ-032 |
| REQ-042 | depends_on | REQ-003 |
| REQ-042 | depends_on | REQ-005 |
| REQ-042 | depends_on | REQ-006 |
| REQ-042 | depends_on | REQ-008 |
| REQ-042 | depends_on | REQ-031 |
| REQ-043 | depends_on | REQ-042 |
| REQ-043 | depends_on | REQ-003 |
| REQ-043 | depends_on | REQ-005 |
| REQ-043 | depends_on | REQ-006 |
| REQ-043 | depends_on | REQ-031 |
| REQ-044 | depends_on | REQ-042 |
| REQ-044 | depends_on | REQ-002 |
| REQ-044 | depends_on | REQ-003 |
| REQ-044 | depends_on | REQ-007 |
| REQ-045 | depends_on | REQ-001 |
| REQ-045 | depends_on | REQ-008 |
| REQ-045 | depends_on | REQ-012 |
| REQ-045 | depends_on | REQ-013 |
| REQ-046 | depends_on | REQ-008 |
| REQ-046 | depends_on | REQ-012 |
| REQ-046 | depends_on | REQ-038 |
| REQ-047 | depends_on | REQ-032 |
| REQ-047 | depends_on | REQ-033 |
| REQ-047 | depends_on | REQ-034 |
| REQ-047 | depends_on | REQ-035 |
| REQ-048 | depends_on | REQ-007 |
| REQ-048 | depends_on | REQ-008 |
| REQ-048 | depends_on | REQ-031 |
| REQ-048 | depends_on | REQ-047 |
| REQ-049 | depends_on | REQ-031 |
| REQ-049 | depends_on | REQ-036 |
| REQ-049 | depends_on | REQ-048 |
| REQ-050 | depends_on | REQ-008 |
| REQ-050 | depends_on | REQ-010 |
| REQ-050 | depends_on | REQ-012 |
| REQ-050 | depends_on | REQ-033 |
| REQ-051 | refines | REQ-011 |
| REQ-051 | depends_on | REQ-002 |
| REQ-051 | depends_on | REQ-033 |
| REQ-052 | refines | REQ-004 |
| REQ-052 | depends_on | REQ-007 |
| REQ-052 | depends_on | REQ-033 |
| REQ-053 | refines | REQ-036 |
| REQ-053 | depends_on | REQ-032 |
| DEC-067 | depends_on | REQ-053 |
| DEC-068 | depends_on | REQ-053 |
| DEC-069 | depends_on | REQ-053 |
| DEC-070 | depends_on | REQ-053 |
| DEC-071 | depends_on | REQ-053 |
| DEC-072 | depends_on | REQ-053 |
| DEC-073 | depends_on | REQ-053 |
| DEC-074 | depends_on | REQ-053 |
| DEC-075 | depends_on | REQ-053 |
| DEC-076 | depends_on | REQ-053 |
| DEC-077 | depends_on | REQ-053 |
| DEC-078 | depends_on | REQ-053 |
| DEC-079 | depends_on | REQ-001 |
| DEC-080 | depends_on | REQ-001 |
| DEC-080 | depends_on | REQ-011 |
| DEC-080 | depends_on | REQ-031 |
| DEC-080 | depends_on | REQ-032 |
| DEC-081 | depends_on | REQ-001 |
| DEC-081 | depends_on | REQ-032 |
| DEC-081 | depends_on | REQ-034 |
| DEC-081 | depends_on | REQ-035 |
| DEC-082 | depends_on | REQ-001 |
| DEC-082 | depends_on | REQ-008 |
| DEC-082 | depends_on | REQ-013 |
| DEC-082 | depends_on | REQ-031 |
| DEC-082 | depends_on | REQ-046 |
| DEC-083 | depends_on | REQ-032 |
| DEC-083 | depends_on | REQ-034 |
| DEC-083 | depends_on | REQ-035 |
| DEC-083 | depends_on | REQ-036 |
| DEC-083 | depends_on | REQ-053 |
| DEC-084 | depends_on | REQ-001 |
| DEC-084 | depends_on | REQ-010 |
| DEC-084 | depends_on | REQ-011 |
| DEC-084 | depends_on | REQ-051 |
| DEC-084 | depends_on | REQ-052 |
| DEC-085 | depends_on | REQ-003 |
| DEC-085 | depends_on | REQ-010 |
| DEC-085 | depends_on | REQ-011 |
| DEC-085 | depends_on | REQ-051 |
| DEC-085 | depends_on | REQ-052 |
| DEC-086 | depends_on | REQ-002 |
| DEC-086 | depends_on | REQ-003 |
| DEC-086 | depends_on | REQ-031 |
| DEC-086 | depends_on | REQ-032 |
| DEC-086 | depends_on | REQ-048 |
| DEC-087 | depends_on | REQ-001 |
| DEC-087 | depends_on | REQ-032 |
| DEC-087 | depends_on | REQ-053 |
| DEC-088 | depends_on | REQ-001 |
| DEC-088 | depends_on | REQ-011 |
| DEC-088 | depends_on | REQ-031 |
| DEC-088 | depends_on | REQ-046 |
| DEC-089 | depends_on | REQ-003 |
| DEC-089 | depends_on | REQ-005 |
| DEC-089 | depends_on | REQ-006 |
| DEC-089 | depends_on | REQ-007 |
| DEC-089 | depends_on | REQ-037 |
| DEC-089 | depends_on | REQ-052 |
| DEC-090 | depends_on | REQ-003 |
| DEC-090 | depends_on | REQ-005 |
| DEC-090 | depends_on | REQ-006 |
| DEC-090 | depends_on | REQ-007 |
| DEC-090 | depends_on | REQ-037 |
| DEC-090 | depends_on | REQ-048 |
| DEC-091 | depends_on | REQ-001 |
| DEC-091 | depends_on | REQ-004 |
| DEC-091 | depends_on | REQ-010 |
| DEC-091 | depends_on | REQ-012 |
| DEC-091 | depends_on | REQ-013 |
| DEC-091 | depends_on | REQ-045 |
| DEC-092 | depends_on | REQ-013 |
| DEC-092 | depends_on | REQ-014 |
| DEC-093 | depends_on | REQ-001 |
| DEC-093 | depends_on | REQ-010 |
| DEC-093 | depends_on | REQ-011 |
| DEC-093 | depends_on | REQ-012 |
| DEC-093 | depends_on | REQ-051 |
| DEC-093 | depends_on | REQ-052 |
| DEC-094 | depends_on | REQ-001 |
| DEC-094 | depends_on | REQ-011 |
| DEC-094 | depends_on | REQ-012 |
| DEC-094 | depends_on | REQ-013 |
| DEC-094 | depends_on | REQ-046 |
| DEC-095 | depends_on | AC-001 |
| DEC-096 | depends_on | REQ-001 |
| DEC-096 | depends_on | REQ-007 |
| DEC-096 | depends_on | REQ-031 |
| DEC-096 | depends_on | REQ-032 |
| DEC-096 | depends_on | REQ-053 |
| DEC-097 | depends_on | REQ-001 |
| DEC-097 | depends_on | REQ-053 |
| DEC-097 | depends_on | DEC-096 |
| DEC-098 | depends_on | REQ-001 |
| DEC-098 | depends_on | REQ-002 |
| DEC-099 | refines | REQ-002 |
| DEC-098 | depends_on | REQ-008 |
| DEC-098 | depends_on | REQ-011 |
| DEC-098 | depends_on | REQ-012 |
| DEC-098 | depends_on | REQ-032 |
| DEC-098 | depends_on | DEC-096 |
| DEC-004 | depends_on | REQ-003 |
| DEC-021 | depends_on | REQ-003 |
| DEC-022 | depends_on | REQ-003 |
| DEC-023 | depends_on | REQ-031 |
| DEC-024 | depends_on | REQ-005 |
| DEC-025 | depends_on | REQ-005 |
| DEC-026 | depends_on | REQ-005 |
| DEC-027 | depends_on | REQ-005 |
| DEC-028 | depends_on | REQ-005 |
| DEC-029 | depends_on | REQ-005 |
| DEC-030 | depends_on | REQ-006 |
| DEC-031 | depends_on | REQ-006 |
| DEC-032 | depends_on | REQ-006 |
| DEC-033 | depends_on | REQ-031 |
| DEC-034 | depends_on | REQ-007 |
| DEC-035 | depends_on | REQ-007 |
| DEC-036 | depends_on | REQ-007 |
| DEC-037 | depends_on | REQ-007 |
| DEC-038 | depends_on | REQ-001 |
| DEC-039 | depends_on | REQ-008 |
| DEC-039 | depends_on | REQ-031 |
| DEC-040 | depends_on | REQ-032 |
| DEC-041 | depends_on | REQ-033 |
| DEC-042 | depends_on | REQ-034 |
| DEC-043 | depends_on | REQ-035 |
| DEC-044 | depends_on | REQ-036 |
| DEC-045 | depends_on | REQ-037 |
| DEC-046 | depends_on | REQ-038 |
| DEC-047 | depends_on | REQ-039 |
| DEC-048 | depends_on | REQ-040 |
| DEC-049 | depends_on | REQ-041 |
| DEC-050 | depends_on | REQ-042 |
| DEC-051 | depends_on | REQ-043 |
| DEC-052 | depends_on | REQ-044 |
| DEC-053 | depends_on | REQ-045 |
| DEC-054 | depends_on | REQ-012 |
| DEC-054 | supersedes | DEC-009 |
| DEC-055 | depends_on | REQ-008 |
| DEC-055 | depends_on | REQ-012 |
| DEC-056 | depends_on | REQ-008 |
| DEC-057 | depends_on | REQ-046 |
| DEC-058 | depends_on | REQ-047 |
| DEC-059 | depends_on | REQ-048 |
| DEC-060 | depends_on | REQ-049 |
| DEC-061 | depends_on | REQ-050 |
| DEC-062 | depends_on | REQ-051 |
| DEC-064 | depends_on | REQ-012 |
| DEC-064 | depends_on | REQ-036 |
| DEC-064 | supersedes | DEC-044 |
| DEC-065 | depends_on | REQ-008 |
| DEC-065 | depends_on | REQ-010 |
| DEC-065 | supersedes | DEC-008 |
| DEC-065 | supersedes | DEC-039 |
| DEC-066 | depends_on | REQ-052 |
| DEC-066 | supersedes | DEC-005 |
| DEC-067 | depends_on | REQ-032 |
| DEC-067 | depends_on | REQ-036 |
| DEC-068 | depends_on | REQ-036 |
| DEC-069 | depends_on | REQ-036 |
| DEC-070 | depends_on | REQ-008 |
| DEC-070 | depends_on | REQ-036 |
| DEC-071 | depends_on | REQ-036 |
| DEC-072 | depends_on | REQ-036 |
| DEC-072 | depends_on | REQ-044 |
| DEC-073 | depends_on | REQ-036 |
| DEC-074 | depends_on | REQ-036 |
| DEC-075 | depends_on | REQ-036 |
| DEC-076 | depends_on | REQ-036 |
| DEC-077 | depends_on | REQ-036 |
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

- None.

## Engineering Delivery Constraints

| ID | Constraint |
| --- | --- |
| ENG-001 | 專案必須使用 Git 版本控管，追蹤 production source、lockfiles、database migrations、tests、canonical specs、architecture authoring sources 與必要生成視圖。秘密、OAuth／Access／session token、AI／B2／Cloudflare 金鑰、PostgreSQL data、郵件內容、匯入檔、備份、runtime logs、個人投資資料與 build output 不得提交；例外必須有明確 ADR、最小範圍及 non-secret 證據。 |
| ENG-002 | 架構治理必須使用 govern-modular-event-architecture schema 2.2.0，並依工具的 exact 2.1.0 compatibility contract 接受及驗證既有 2.1.0 authoring sources。實作前必須完成 authoring-first L0–L3+ responsibilities、module／port／event boundaries、Type Catalog、named-type ownership、runtime-state ownership、dependency inversion、contracts、Boundary Design、Flows、Algorithm Design Records、Execution Profiles／scheduling analysis、Description Views 與 ADR-controlled exceptions；architecture、production code、tests 與 deterministic generated views 必須一致。未通過 boundary、type、state、scheduling、compatibility 或 generated-view gate 時不得進入對應 production implementation。 |

| ID | Constraint | Validation | Evidence |
| --- | --- | --- | --- |
| ENG-AC-001 | Git tracking and secret exclusion | 對允許與禁止檔案執行 repository status、ignore、history 與 secret scanning；驗證 migration、spec、architecture source 及 tests 可追溯，禁止資料未被追蹤且不在歷史或 artifact。 | Pending execution |
| ENG-AC-002 | Architecture schema and conformance | 以 schema 2.2.0 authoring source 與代表性 2.1.0 compatibility fixtures 執行 design／development gates、deterministic render、type／state／boundary／scheduling analyzers、ADR／Algorithm Record／Description View link checks；全部必須 PASS 且重跑輸出一致。 | Pending execution |

## Routing/Gates

- ask-matt: PASS
- project state at materialization: implementation absent, stateful context absent
- grill-me: PASS, decision-complete working spec
- clarify-improvement-proposals: required for the confirmed architecture proposal
- govern-modular-event-architecture: required, schema 2.2.0 with exact 2.1.0 compatibility
- spec-governance materialize: authorized
- spec-governance verify: pending repository validation
- TDD and product implementation: not started
- Architecture ADRs and Algorithm Design Records remain proposed until explicit non-AI approval.
- Production completion requires Validation Enablement, per-change development validation, final runtime acceptance, release acceptance, architecture gate, deterministic generated-view comparison and code review.

## Revision History

| Revision | Date | Status | Changes |
| --- | --- | --- | --- |
| 1 | 2026-08-02 | confirmed | Materialized the greenfield ThesisTrace discussion. Recorded platform, evidence ladder, E2-E6 digest policy, replaceable AI, valuation and risk rules, roles, mail, portfolio import, worker isolation, VPN decision, backup, disk-encryption risk, architecture governance and Git policy. Replaced the earlier E2 immediate-volume rule with a daily 21:00 E2-E6 digest and replaced conditional reuse of the legacy OpenVPN profile with WireGuard. |
| 2 | 2026-08-10 | Reopened before clarification: Resolve semantic and acceptance gaps identified by the 2026-08-10 review before implementation. |
| 86 | 2026-08-20 | Reopened before clarification: Clarify the versioned URL path and query normalization policy exposed by ALG-0001 implementation review. |
| 87 | 2026-08-20 | working | Selected conservative `url-normalization-v1`, required persisted policy versions, preserved non-empty path/query representation, and added future migration/coexistence rules. |
