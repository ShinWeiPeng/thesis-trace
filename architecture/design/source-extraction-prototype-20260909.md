# ALG-0035 解析原型紀錄（2026-09-09）

## 結論與範圍

已完成第一輪本機 throwaway 原型：14 個邊界案例符合預期；透過既有 HTTPS／SSRF fetcher 實際取得兩份聯發科官方來源，再於隔離程序擷取文字。這不是產品實作、完整財務證據驗收或正式環境資源校準。

最重要的反例是「可抽文字 ≠ 必要證據完整」。總覽 HTML 的前八段只到一月資料；PDF 的固定前綴與 layout 模式不能可靠保留可比對的查核註記。ALG-0035 仍為 proposed，不可因原型成功就標記 accepted。

## 邊界與可重現入口

- 原型：[source_extraction_probe.py](../../backend/tests/prototypes/source_extraction_probe.py)，屬既有 `development` source set，不被任何 production entrypoint 匯入。沒有新增 production type/state/port、manifest 或 migration。
- Parent 僅在 `--case sources` 呼叫既有 `RestrictedHttpSourceFetcher`，只下載程式中明列的兩個官方 URL。原始 bytes 透過有生命週期的暫存 FD 交给 child；FD 關閉後不保存原文檔案。
- Child 使用 bubblewrap 0.11.1，獨立 user/PID/network 等 namespaces、禁止再建 user namespace、移除 capabilities、清空繼承環境；只唯讀掛載 `/usr`、原型程式及隔離套件目录。沒有專案、home、`/run/secrets`、Docker socket 或 DB 連線。
- Resource limits 先於不可信內容解析設定。Parent 在等待或輸出超限時終止自己的 process group，等待回收；新 PID namespace 與 die-with-parent 限制後代存活。這是具體案例觀察，不是全面 sandbox 安全認證。
- 原型對 bytes／程序控制負責；不改 E-stage、來源分類、Thesis、估值或 Recommendation。HTML line／PDF page 是候選定位，未被當作確認後 fact。

已獲 native permission 後，套件只安裝在 `/tmp/thesis-trace-extraction-prototype.H66cBJ/venv`。本輪重跑命令：

```bash
backend/.venv/bin/python backend/tests/prototypes/source_extraction_probe.py --library /tmp/thesis-trace-extraction-prototype.H66cBJ/venv/lib/python3.14/site-packages --case all
backend/.venv/bin/python backend/tests/prototypes/source_extraction_probe.py --library /tmp/thesis-trace-extraction-prototype.H66cBJ/venv/lib/python3.14/site-packages --case sources
```

省略 `--case` 可選擇合成邊界或真實來源；`--report <new-path>` 以 create-only 寫出少量診斷 JSON。暫存環境若已消失，須重新獲准安裝，不可默認使用另一套 parser。未建立 throwaway Git commit／issue pointer：本輪沒有 commit、push 或 tracker write 授權；原型仍是本機未提交的 development 檔案。

## 套件依據

候選 pypdf **6.18.0**、BSD-3-Clause、wheel SHA-256 `05b762b77bcb9dcb4a7c91fcf5dded585b25bee7269ab3d3001d7c55fa1b324b`；安裝時透過 URL hash 檢驗，未安裝 OCR／crypto extras，也未修改 backend lockfile。[PyPI 發行 metadata](https://pypi.org/pypi/pypdf/6.18.0/json)

已核對維護者公告：間接物件解析的資源消耗問題修於 6.18.0；Roman page label 問題修於 6.17.0。這不是「套件沒有漏洞」的保證；production lock 前仍須重查公告並保留隔離。[GHSA-5jq2-8x83-x246](https://github.com/py-pdf/pypdf/security/advisories/GHSA-5jq2-8x83-x246)、[GHSA-qv6h-rv94-w285](https://github.com/py-pdf/pypdf/security/advisories/GHSA-qv6h-rv94-w285)

官方文件也說明 PDF 解析可能大量耗用記憶體、沒有可靠表格語意且不提供 OCR；因此不能把 2 MB 下載限制當作解析記憶體上界。[pypdf 文字擷取說明](https://pypdf.readthedocs.io/en/6.18.0/user/extract-text.html)

## 原型參數（不是 production 政策）

| 項目 | 實验設定 | 證據及限制 |
| --- | --- | --- |
| 下載 | 2,000,000 bytes；15 s HTTP timeout；3 redirects | 重用現有 fetcher；timeout 不是完整 Flow deadline |
| 解析位址空間 | RLIMIT_AS 64／128／256 MiB 候選 | 兩份來源在三種設定皆可讀；不是 RSS、併發或正式 reserve 校準 |
| CPU／等待 | child RLIMIT_CPU 2 s；parent wall wait 5 s | 只為本輪失控程序實驗設定，不是 freshness SLO／正式預設 |
| 頁數 | 40 | 41 空白頁回報 page_limit；正式允許文件範圍尚未定案 |
| 輸出 | 最多 8 段、總計 4,000 字元；每段 1,000，另比較 2,000；IPC 16,384 bytes | 實驗顯示純前綴選取不足；Unicode UTF-8／JSON 展開仍可能先碰 IPC limit |
| 其他 | core/file size 0；FD 16；NPROC 1 | 避免原型留下 core、檔案或無限制產生程序；尚未完成正式 container 的相容性驗證 |

## 實際觀察

14 個案例：可讀 HTML 且 script/nav 內容不出現、無效 UTF-8、script-only、損壞 PDF、空白 PDF、加密 PDF、41 頁 PDF、261,466-byte 合成 PDF 含 256 MiB 解壓縮內容、輸入超限、無 egress／home／secrets 的探測、記憶體配置超限、CPU loop、wall wait、輸出洪流。最終每案 `matches_expected=true`、`child_ready=true`、`child_reaped=true`；CPU 案 exit 137。資料全部是工程邊界 fixture，不是聯發科資料。

初始原型曾因 bubblewrap 參數缺 `--unshare-user` 而無法啟動；已修正並加入 child-ready 證明，避免把 launcher 失敗當作 CPU 防護成功。空白頁的 `/Contents` 缺值與合成壓縮 stream 建立方式也在重跑前修正。不得引用初始失敗 run 為成功證據。

真實來源最後一輪取得時間為 2026-09-09 08:45 UTC：

| 來源 | 大小／raw SHA-256 | 原型結果 |
| --- | --- | --- |
| [官方財務總覽](https://www.mediatek.com/investor-relations/financial-information) | 631,437 bytes；`2ff694db2da6c8cd2df2bb6678da4a391f0115ca24112b24b6c8fc46bb6990cd` | 可讀，前八段只到一月；selection_incomplete=true，不代表已包含最新月份或註記 |
| [2026 年 7 月營收 PDF](https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/Monthly%20Reports/2026/Monthly%20Sales%20Revenue%20July,%202026.pdf) | 97,126 bytes；`3d13775b3d1922b5500492a22f8cc79cbc5bcee0151f2f96ff1208a1eebf5545` | PDF 第 1 頁；plain 模式在 2,000 字元內可匹配期間、幣別單位、樣本金額與未查核註記；仍不是 financial fact confirmation |

同一 PDF 原文 hash 下，layout 1,000 字元、整理空白後 layout 2,000 字元與 plain 2,000 字元比較：前兩者均未匹配完整 `not been audited` token，plain 可匹配全部四個手動核對的 fixture tokens。這只支持此樣本的解析模式比較，不證明所有 PDF 都應使用 plain，也不能把 token matching 當作語意驗證。

HTML 重複取得時 raw hash 有變而大小相同；原型不推論是哪段變動，也不以擷取文字 hash 覆寫原始 identity。公告／事件時間仍為 null，`document_verified=false`；沒有將 fetcher 的 retrieved_at 冒充公告時間。

## 剩餘 gate 與下一步

1. 先完成片段選取與完整性設計：保留標題、表格欄位／單位／註記等語境，不用固定前幾段或單一 keyword 宣告所需證據完整。HTML table cell 結構、未知編碼、混合掃描頁、多頁 PDF、日期衝突與 UTF-8 輸出展開需補實驗。
2. 本機 prototype host 是 Python 3.14.4；既有後端映像 `9bc91c201c9a` 為 Python 3.13.7、無 bubblewrap。一次無網路／無掛載的暫時容器已驗證此差異並自動移除，沒有改現有服務。不能把 host 結果當作 release-equivalent PASS，也不能以關閉 no-new-privileges 或掛 Docker socket 繞過隔離。
3. 依 ADR-0010 建立與正式 Cloudflare profile 分離的 local validation enablement，再確認部署工具、container 限制與 resource reserve；既有 profile hash 過期且沒有適用的本機場景，不作替代。未執行正式 `validate-on-device run/evaluate`，未宣稱 perf/ftrace／CPU／RSS／scheduler 驗收。
4. 完成上述缺口後才提出 ALG-0035 最終內容供 Owner 核准，並補齊精確 manifest catalog、通過新設計 gate 後做 production TDD。現有 manifest 的 design/development PASS 只涵蓋既有設計，不替未建模的新 parser 背書。

## 本機證據與檢查

- `build/extraction-prototype/20260909-boundaries.json` SHA-256：`0fd8ecbd7861d48a8b0a0607d44eb8fbc036fbe8917ad01463ab135a96e6226d`。
- `build/extraction-prototype/20260909-sources.json` SHA-256：`67edc64ccc209f557f81cd14af3db004ca57b952591e91be7004da1961d3d30c`。
- 原型 source SHA-256：`3728d915a036c46ad598aa373aec2ec4a85bcb4bda43d1464d0acdad9fff2cfd`。兩份結果內含同一 source hash；只保存少量預覽、定位與布林核對結果，未保存原文全文。
- Ruff 0.12.12 scoped format/check、formatter gate PASS；既有 `test_source_fetch.py` 13 passed。沒有改正式 Python／TypeScript 程式。
- `architecture_cli.py gate --phase design/development` exit 0，保留原 ADR-0004 dependency exception 及 FLW015 warning。
- `git check-ignore` 確認診斷 JSON 仍為本機忽略。working bundle 保留，原 `thesis_trace` DB 未讀寫；沒有付費 AI、OCR、commit 或 push。
