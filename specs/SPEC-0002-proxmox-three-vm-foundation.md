---
spec_version: "1"
spec_id: SPEC-0002
revision: 13
status: confirmed
change_set: proxmox-three-vm-foundation
---

# SPEC-0002: Proxmox Three-VM Foundation

## Problem

家用服務（包含 ThesisTrace、未來的語音秘書等）需要可長期運行的伺服器、與伺服器資料隔離的開發環境，以及可使用 RTX 5060 Ti 的 Windows 遊戲環境。現有 Proxmox 主機只有 6 核心／12 執行緒、約 31 GiB 記憶體及單顆約 1 TB NVMe；若未明確限制 VM 的資源、啟動模式、儲存位置與 GPU 所有權，三種工作負載可能互相爭用資源，或在 GPU 直通失敗時使主機失去可復原的管理路徑。

## Solution

在 Proxmox VE 9.2.10 上建立三台彼此分離的 VM：Ubuntu Server 26.04 LTS 正式伺服器、Ubuntu Server 26.04 LTS 開發環境，以及 Windows 11 遊戲環境。Linux Server 長期運行；Windows Gaming 與 Linux Development 可同時啟動，以支援遊戲期間的 GPT 輔助程式修改，但整體固定記憶體配置必須為 Proxmox 保留主機餘裕。Windows 先以虛擬顯示器完成基礎安裝，建立可回復狀態後，才將 RTX 5060 Ti 與其 HDMI 音訊完整直通。

## Verified Host Baseline

| Item | Verified State |
| --- | --- |
| Hypervisor | Proxmox VE 9.2.10 |
| CPU | AMD Ryzen 5 7500F, 6 cores / 12 threads |
| Memory | 30.93 GiB |
| Motherboard | ASRock A620AI WiFi |
| Physical storage | ADATA LEGEND 900 NVMe, approximately 1.02 TB |
| VM thin pool | `local-lvm`, 875.49 GB, 0 B initially used |
| ISO directory | `local`, `/var/lib/vz`, approximately 93.93 GiB root filesystem |
| IOMMU | AMD-Vi active, translated domains and interrupt remapping enabled |
| GPU | `01:00.0`, NVIDIA GeForce RTX 5060 Ti, PCI ID `10de:2d04` |
| GPU audio | `01:00.1`, NVIDIA High Definition Audio, PCI ID `10de:22eb` |
| GPU isolation | Both GPU functions are the only observed devices in IOMMU group 12 |

## User Stories

- 作為 Owner，我要讓 Home Service Server 在遊戲或開發工作期間仍能持續運行，以便 ThesisTrace、語音秘書與其他家用服務不中斷。
- 作為 Developer，我要在與正式資料及秘密隔離的 Linux VM 中開發、測試與建置 ThesisTrace。
- 作為 Gamer，我要讓 Windows VM 直接使用 RTX 5060 Ti、電視影像及 HDMI 音訊，以便測試《鳴潮》與 Steam 遊戲。
- 作為 Administrator，我要在 GPU 直通失敗時仍可經由 Proxmox Web 或 SSH 回復 VM 與主機設定。
- 作為 Owner，我要保留足夠的記憶體與磁碟緩衝，避免三台 VM 造成主機交換、磁碟耗盡或不可預期停機。

## Requirements

| ID | Requirement |
| --- | --- |
| REQ-017 | 系統必須建立三台獨立 VM：`home-service`、`home-service-dev` 與 `windows-gaming`；不得以同一 VM 混用正式部署、開發資料與遊戲工作負載。 |
| REQ-018 | `home-service` 必須使用 Ubuntu Server 26.04 LTS、q35、OVMF、CPU type `host`、4 vCPU、4 GiB 固定記憶體、120 GB `local-lvm` 磁碟、VirtIO 網路與 QEMU Guest Agent，並設定自動開機。 |
| REQ-019 | `home-service-dev` 必須使用 Ubuntu Server 26.04 LTS、q35、OVMF、CPU type `host`、8 vCPU、8 GiB 固定記憶體、200 GB `local-lvm` 磁碟、VirtIO 網路與 QEMU Guest Agent，且不得自動開機。Development 必須在 Server 基礎安裝後加裝 XFCE 與 xrdp，並同時提供 SSH，讓筆電可使用圖形遠端桌面及本機 VS Code Remote SSH；不改用 Ubuntu Desktop ISO。 |
| REQ-020 | `windows-gaming` 必須使用 Windows 11 x64、q35、OVMF、TPM 2.0、CPU type `host`、8 vCPU、14 GiB 固定記憶體、400 GiB `local-lvm` 磁碟、VirtIO 網路與 QEMU Guest Agent；記憶體 ballooning 與自動開機必須關閉。 |
| REQ-021 | Windows 必須先使用 Proxmox 虛擬顯示器完成基礎安裝、VirtIO 驅動、QEMU Guest Agent、Windows Update 與至少三次重新啟動驗證，建立可回復狀態後才能進行 GPU 直通。 |
| REQ-022 | GPU 直通必須同時包含 `01:00.0` RTX 5060 Ti 與 `01:00.1` NVIDIA HDMI Audio。不得使用 ACS override，不得將 GPU 同時提供給其他 VM。 |
| REQ-023 | GPU 直通前必須驗證 Proxmox Web 與 SSH 的遠端管理能力。RTX 5060 Ti 交給 Windows 後，Proxmox 必須被視為無螢幕主機，不得依賴主機本機畫面完成日常管理或回復。 |
| REQ-024 | Server、Windows 與 Development 必須能同時啟動；三台 VM 的固定記憶體總量不得超過 26 GiB，為 Proxmox 與虛擬化開銷保留約 4.93 GiB。遊戲期間允許 GPT 輔助程式修改、完整建置、Docker image build 與完整測試；CPU 爭用造成的掉幀或測試變慢可接受，但不得造成主機或 VM 崩潰。 |
| REQ-025 | 三台 VM 磁碟必須建立在 `local-lvm`；Windows、VirtIO 與 Ubuntu ISO 必須存放在 `local`。初始 VM 磁碟配置總量不得超過 720 GiB，必須保留至少約 150 GiB thin-pool 緩衝。 |
| REQ-026 | 三台 VM 必須連接 `vmbr0`。預定地址為 Server `[REDACTED: personal data]`、Windows `[REDACTED: personal data]`、Development `[REDACTED: personal data]`；正式配置前必須先確認 Edimax DHCP 範圍，並優先使用 DHCP reservation 避免衝突。 |
| REQ-027 | Development VM 只能使用測試資料與測試憑證，不得直接共用 Server VM 的正式 PostgreSQL、正式秘密、郵件內容、匯入檔或備份。ThesisTrace 正式服務仍必須遵守 SPEC-0001 的 VPN-only、秘密管理與加密異地備份要求。 |
| REQ-028 | 《鳴潮》與其他遊戲的 VM 相容性必須透過實際執行驗證。不得隱藏虛擬機、修改或繞過 Anti-Cheat Expert，且不得把單次成功啟動描述為未來版本的相容性保證。 |
| REQ-029 | 鍵盤、滑鼠與控制器初期必須以個別 USB 裝置或專用接收器直通。未驗證 IOMMU 群組與主機依賴前，不得直通整組主機板 USB 控制器。 |
| REQ-030 | 每一安裝階段必須具備停止條件與回復步驟。GPU 直通失敗時，必須能停止 Windows VM、移除 PCIe 裝置、恢復虛擬顯示器，並在必要時解除 VFIO 綁定。 |
| REQ-031 | `home-service-dev` 的 SSH 與 xrdp 必須只接受已驗證家中 LAN 來源範圍的連線；不得直接暴露至公網，也不得將 VPN 來源列入允許範圍。SSH 必須使用筆電端公鑰、停用密碼與 root 登入；xrdp 必須使用獨立強密碼，且不得在規格、儲存庫或腳本中保存明文憑證。 |

## Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| DEC-013 | 採三台獨立 VM，不以容器或單一 VM 混用正式、開發與遊戲環境。 | 分離秘密、資料、故障範圍與資源生命週期。 |
| DEC-014 | Server 與 Development 均採 Ubuntu Server 26.04 LTS，不安裝完整桌面。 | 符合 SPEC-0001，並以 VS Code Remote SSH 降低記憶體與圖形環境負擔。 |
| DEC-015 | Windows 先作為 GPU 與遊戲相容性閘門，再繼續完整環境建置。 | 《鳴潮》使用核心層級 ACE，VM 支援無法事前保證。 |
| DEC-016 | RTX 5060 Ti 採完整 PCIe passthrough，不採 NVIDIA vGPU 或共享 GPU。 | GeForce 遊戲用途需要完整裝置，且目前只有一台 Windows VM 需要 GPU。 |
| DEC-017 | Windows 與 Development 採互斥高負載模式；Server 維持 4 GiB 長期運行。 | 主機只有約 31 GiB 記憶體，三台同時重載會超出安全容量。 |
| DEC-018 | 初始磁碟配置為 Server 120 GiB、Development 200 GiB、Windows 400 GiB。 | Windows 需容納至少 150 GB 的《鳴潮》與 Steam 遊戲；磁碟可擴大但不易安全縮小，仍需為 thin pool 保留緩衝。 |
| DEC-019 | 不使用 ACS override、VM 隱藏或防作弊繞過。 | 避免破壞 IOMMU 隔離與違反遊戲規則；現有 group 12 已具備理想隔離。 |
| DEC-020 | Windows VM 不自動開機，必須由使用者透過 Proxmox 手動啟動。 | 避免主機開機後立即占用 GPU 與 20 GiB 記憶體。 |
| DEC-021 | Server 維持 4 GiB、Windows 採 16 GiB、Development 採 6 GiB，三台可同時啟動；此決策取代 DEC-017 的互斥運行模式。 | 26 GiB 客體固定記憶體可保留約 4.93 GiB 給 Proxmox；Windows 達到《鳴潮》目前列出的 16 GB 最低需求，Development 則支援 Remote SSH、Git、GPT 程式修改與輕量 Docker 工作。 |
| DEC-022 | 遊戲期間允許 Development 執行完整建置、Docker image build 與完整測試，不設定互斥或低 CPU 權重政策。 | 使用者選擇工作完成度優先，並接受 20 個已配置 vCPU 在 12 個主機執行緒上競爭時可能出現遊戲掉幀與測試變慢。 |
| DEC-023 | `home-service` 維持無桌面；`home-service-dev` 在 Ubuntu Server 上加裝 XFCE 與 xrdp，日常程式編輯優先使用筆電端 VS Code Remote SSH。此決策取代 DEC-014 對 Development 不安裝桌面的限制。 | XFCE 提供需要的 Linux 圖形工具且比 GNOME 節省 6 GiB Development VM 的記憶體；VS Code Remote SSH 將編輯介面留在筆電，遠端執行程式、終端與擴充套件。 |
| DEC-027 | Linux Server 與 Development VM 分別命名為 `home-service` 與 `home-service-dev`，不再使用 ThesisTrace 專屬名稱。 | Server 將長期承載 ThesisTrace、語音秘書與其他家用服務，名稱應反映通用用途。 |
| DEC-024 | Development 的 SSH 與 xrdp 僅限家中 LAN，不允許公網或 VPN 來源。 | 使用者選擇最小遠端暴露面，並接受離開家中網路後無法連入 Development。 |
| DEC-025 | Server 維持 4 GiB、Windows 改為 14 GiB、Development 改為 8 GiB；此決策取代 DEC-021 的 16/6 分配。 | 使用者提高 XFCE、VS Code Server、Docker 與測試可用的 Development 記憶體，並接受 Windows 低於《鳴潮》目前列出的 16 GB 最低需求。三台客體固定記憶體仍為 26 GiB。 |
| DEC-026 | Development 的 VS Code Remote SSH 採公鑰驗證並停用 SSH 密碼/root 登入；xrdp 使用獨立強密碼。 | SSH 金鑰適合日常自動連線且避免共用密碼；xrdp 依賴系統帳號/PAM 密碼，因此以獨立強密碼及 LAN 防火牆限制其風險。 |

## Installation Sequence

1. 從官方來源取得 Windows 11 x64、VirtIO Windows drivers 與 Ubuntu Server 26.04 LTS ISO，驗證檔案完整性並上傳至 `local`。
2. 建立 Windows 基礎 VM，不加入實體 GPU，完成 Windows、VirtIO、QEMU Guest Agent 與更新驗證。
3. 建立 Windows 基礎快照或等效可回復狀態。
4. 驗證 Proxmox Web 與 SSH，再進行 VFIO 綁定、主機重新啟動及 GPU／Audio 直通。
5. 驗證電視影像、HDMI 音訊、NVIDIA 驅動及多次重新啟動，再測試《鳴潮》與 Steam 遊戲。
6. 建立 Linux Server VM，驗證自動開機、網路、SSH、QEMU Guest Agent 與基礎 Docker 主機能力；尚未通過 SPEC-0001 部署閘門前不得啟用正式 ThesisTrace。
7. 建立 Linux Development VM，在 Ubuntu Server 基礎上配置 XFCE、xrdp、SSH、Git、Docker、VS Code Remote SSH、測試資料與架構／測試工具。
8. 只在 Development 驗證完成後，依 SPEC-0001 的架構、測試、安全、VPN 與備份閘門部署 Server。

## Acceptance Criteria

| ID | Requirements | Scenario | Validation Method | Evidence |
| --- | --- | --- | --- | --- |
| AC-016 | REQ-017 REQ-018 REQ-019 REQ-020 REQ-025 | 建立三台 VM 且尚未部署應用。 | 比對 Proxmox VM hardware、options、storage 與資源總量；確認名稱、CPU、記憶體、磁碟、啟動設定及儲存位置符合規格。 | Pending execution |
| AC-017 | REQ-021 | Windows 尚未加入實體 GPU。 | 完成 VirtIO、QEMU Guest Agent、Windows Update，連續重新啟動三次並從 Proxmox Console 驗證可登入與連網。 | Pending execution |
| AC-018 | REQ-022 REQ-023 REQ-030 | 將唯一 RTX 5060 Ti 交給 Windows。 | 檢查 VFIO driver、VM PCI 設定、電視影像、HDMI 音訊、Proxmox Web／SSH，以及移除 PCI 裝置後的回復演練。 | Pending execution |
| AC-019 | REQ-028 | 執行《鳴潮》與選定 Steam 遊戲。 | 記錄遊戲版本、防作弊名稱、啟動結果、錯誤及更新後重測日期；不採任何規避措施。 | Pending execution |
| AC-020 | REQ-018 REQ-026 REQ-027 | Server VM 啟動與重新啟動。 | 驗證自動開機、IP、SSH、Guest Agent、Docker 基礎能力及未公開管理服務；正式應用驗收仍由 SPEC-0001 管理。 | Pending execution |
| AC-021 | REQ-019 REQ-027 | Development VM 建立可重建的圖形與遠端開發環境。 | 從筆電分別驗證 xrdp 登入 XFCE、VS Code Remote SSH 開啟遠端專案、遠端終端與擴充套件執行，並驗證 Git、Docker Compose、測試資料隔離、秘密掃描與 ThesisTrace 開發／架構工具。 | PARTIAL (2026-08-13): `home-service-dev` is running Ubuntu 26.04 LTS at `[REDACTED: personal data]` with an expanded 194 GiB root filesystem, active QEMU Guest Agent, XFCE 4.20/xrdp, key-only SSH, LAN-only UFW rules for TCP 22/3389, Docker 29.7.2, Compose 5.4.0, Git 2.53.0, and Python 3.14.4. User-submitted screenshots verify successful XFCE/xrdp login and VS Code Remote SSH connection from the designated laptop. Remote project, terminal/extension execution, test-data isolation, secret scanning, and ThesisTrace development/architecture tooling remain pending. |
| AC-022 | REQ-024 | Server、Windows 與 Development 同時運行，並在 Windows 遊戲期間進行 GPT 輔助修改、完整建置、Docker image build 與完整測試。 | 核對三台 VM 固定記憶體總量為 26 GiB，記錄 Proxmox 記憶體、swap、CPU、I/O、VM 狀態及工作完成結果；允許 CPU 飽和、遊戲掉幀與測試變慢，但不得發生 VM 啟動失敗、OOM、非預期 VM 終止、持續性主機 swap，且開發工作必須完成或回報正常的應用層失敗。 | Pending execution |
| AC-023 | REQ-026 | 三台 VM 取得網路位址。 | 核對 Edimax DHCP reservation、`vmbr0`、Gateway、DNS 與位址唯一性。 | Pending execution |
| AC-024 | REQ-029 REQ-030 | USB 或 GPU 直通失敗。 | 執行個別 USB 移除及 GPU rollback；確認 Proxmox 與其他 VM 不失去網路、儲存或管理能力。 | Pending execution |
| AC-025 | REQ-031 | 筆電從允許的家中 LAN 與不允許的來源嘗試連入 Development。 | 從 LAN 驗證 SSH 金鑰與 VS Code Remote SSH 成功、SSH 密碼及 root 登入被拒、xrdp 強密碼可登入 XFCE且錯誤密碼被拒；核對防火牆規則，並從非允許來源驗證 TCP 22/3389 無法建立連線。 | Pending execution |

## Relationships

| Source | Relation | Target |
| --- | --- | --- |
| REQ-027 | depends_on | REQ-018 |
| REQ-027 | depends_on | REQ-019 |
| REQ-023 | depends_on | REQ-022 |
| DEC-014 | refines | DEC-013 |
| DEC-021 | supersedes | DEC-017 |
| DEC-023 | supersedes | DEC-014 |
| DEC-025 | supersedes | DEC-021 |
| DEC-026 | refines | DEC-024 |

## Out of Scope

- 在本 SPEC 中完成 ThesisTrace 功能開發、正式部署或資料遷移。
- 保證《鳴潮》或任何 Steam 遊戲長期支援虛擬機。
- 隱藏 VM、繞過 ACE 或修改遊戲防作弊。
- NVIDIA vGPU、GPU 分割或讓 Development VM 共用 RTX 5060 Ti。
- ACS override 或在未隔離群組中強制直通主機必要裝置。
- 公網暴露 Proxmox、SSH、PostgreSQL、Docker API 或 ThesisTrace。
- 在未確認 IOMMU 群組前直通整組 USB 控制器。
- 將單顆 NVMe 當作可替代異地備份的保護措施。

## Deployment Inputs

- Windows 11 合法授權。
- Windows 11 x64 ISO、VirtIO Windows drivers ISO、Ubuntu Server 26.04 LTS ISO 及其完整性證據。
- Edimax DHCP 發放範圍與三個 DHCP reservations。
- 電視 HDMI 連線、鍵盤／滑鼠／控制器與必要 USB 接收器。
- 《鳴潮》及其他測試遊戲的清單與測試日期。
- SPEC-0001 所列 Gmail OAuth、AI providers、Backblaze B2、WireGuard UDP port／DDNS 與其他正式部署輸入。

## Discussion Context

### DISC-001: Retain the separate Linux Development VM

- **Situation:** Windows with WSL2/Docker could replace a dedicated development VM, but the original proposal separates development and production workloads.
- **Question:** Should SPEC-0002 remove the Linux Development VM or retain the original three-VM design?
- **Options and tradeoffs:** Remove it to reduce resource and maintenance cost; defer it for later flexibility; or retain it for stronger production/development isolation at the cost of 12 GiB RAM and a 200 GiB thin-provisioned disk while active.
- **User answer:** 還是按照原本提案好了。維持linux dev跟linux server
- **Explicit rationale:** The user explicitly chose the original proposal; no additional rationale was provided.
- **Resulting impact:** REQ-019, DEC-013, DEC-014, DEC-017, AC-016, and AC-021 remain in force; both Linux Server and Linux Development VM stay in scope.

### DISC-002: Keep Linux Server running during concurrent gaming and development

- **Situation:** The host has 30.93 GiB RAM, while the current fixed allocations total 36 GiB for Server, Development, and Windows before reserving memory for Proxmox.
- **Question:** Must Linux Server remain online while Windows Gaming and Linux Development run concurrently?
- **Options and tradeoffs:** Stop Server to maximize gaming memory; keep Server online and reduce guest allocations; or switch modes according to the current task.
- **User answer:** 2
- **Explicit rationale:** Linux Server must remain running while gaming and GPT-assisted development occur concurrently; no additional rationale was provided.
- **Resulting impact:** REQ-020, REQ-024, DEC-017, and AC-022 require a revised concurrent memory allocation that reserves sufficient host memory.

### DISC-003: Select the concurrent fixed memory allocation

- **Situation:** Keeping Server online leaves 26.93 GiB before accounting for Proxmox; the guest allocation must also preserve enough Windows memory for gaming and enough Development memory for GPT-assisted editing.
- **Question:** Which fixed RAM split should be used for Windows Gaming and Linux Development?
- **Options and tradeoffs:** Use Windows 16 GiB and Development 6 GiB for gaming priority with about 4.93 GiB host reserve; use Windows 14 GiB and Development 8 GiB for development priority but fall below the game's listed minimum; or upgrade to 64 GB and retain the original allocations.
- **User answer:** 1
- **Explicit rationale:** The user selected the recommended balanced allocation; no additional rationale was provided.
- **Resulting impact:** REQ-019, REQ-020, REQ-024, DEC-021, and AC-022 now require Server 4 GiB, Windows 16 GiB, and Development 6 GiB; DEC-021 supersedes DEC-017.

### DISC-004: Allow CPU-heavy development during gameplay

- **Situation:** The three VMs expose 20 vCPU in total on a host with 12 hardware threads, so simultaneous gaming, builds, Docker image creation, and tests can contend for CPU.
- **Question:** Should CPU-heavy development work be delayed, deprioritized, or allowed without restriction during gameplay?
- **Options and tradeoffs:** Delay heavy work for stable gaming; allow all work and accept performance degradation; or lower Development CPU weight to balance both workloads.
- **User answer:** 2
- **Explicit rationale:** The user selected unrestricted concurrent work; no additional rationale was provided.
- **Resulting impact:** REQ-024, DEC-022, and AC-022 allow full builds and tests during gameplay, accept performance degradation, and retain crash/OOM prevention as the required safety boundary.

### DISC-005: Use XFCE/xrdp with laptop-side VS Code Remote SSH

- **Situation:** The user plays in Windows VM while using a separate laptop to develop in the Linux Development VM; Development has 6 GiB RAM and needs optional Linux GUI tools without turning the production Server into a desktop system.
- **Question:** Which Development interface should be used: XFCE/xrdp, GNOME/xrdp, or laptop-side VS Code Remote SSH without a full desktop?
- **Options and tradeoffs:** XFCE/xrdp provides a lightweight full desktop; GNOME provides the standard Ubuntu desktop at higher memory cost; Remote SSH alone is most efficient but lacks a complete Linux desktop.
- **User answer:** 選擇1再搭配筆電安裝 VS Code，再用 Remote SSH 連 Development VM
- **Explicit rationale:** The user wants both a complete remote Linux desktop and the smoother daily coding experience of laptop-side VS Code Remote SSH.
- **Resulting impact:** REQ-019, DEC-023, and AC-021 require Ubuntu Server plus XFCE/xrdp and SSH on Development, laptop-side VS Code Remote SSH as the primary coding path, and a headless Server; DEC-023 supersedes DEC-014 for Development.

### DISC-006: Restrict Development remote access to the home LAN

- **Situation:** Development exposes SSH and xrdp for a separate laptop, so the allowed network sources determine its attack surface and whether off-site access is possible.
- **Question:** Should SSH/xrdp be available from LAN only, LAN plus VPN, or directly from the public Internet?
- **Options and tradeoffs:** LAN-only minimizes exposure but prevents off-site access; LAN plus VPN adds secure remote flexibility; direct public exposure is simplest off-site but carries the highest attack risk.
- **User answer:** 選擇2
- **Explicit rationale:** The user selected home-LAN-only access; no additional rationale was provided.
- **Resulting impact:** REQ-031, DEC-024, and AC-025 restrict Development SSH/xrdp to the verified home LAN and deny public and VPN sources.

### DISC-007: Rebalance memory toward the graphical Development VM

- **Situation:** XFCE, xrdp, VS Code Server, Docker, and tests increase Development memory demand while all three VMs must remain within a 26 GiB fixed guest budget.
- **Question:** Should the previous Windows 16 GiB / Development 6 GiB split remain, or be changed?
- **Options and tradeoffs:** Retain 16/6 to meet the game's listed minimum; use 14/8 to improve graphical development while accepting game-memory risk; or upgrade host memory.
- **User answer:** 記憶體配置變更為Windows 14 GiB + Development 8 GiB
- **Explicit rationale:** The user prioritizes more memory for the graphical Development workflow; no additional rationale was provided.
- **Resulting impact:** REQ-019, REQ-020, DEC-025, AC-016, and AC-022 require Windows 14 GiB and Development 8 GiB; DEC-025 supersedes DEC-021 while the total guest budget remains 26 GiB.

### DISC-008: Use SSH keys and an independent xrdp password

- **Situation:** Development exposes SSH for VS Code Remote SSH and xrdp for XFCE within the home LAN; the two protocols support different authentication mechanisms.
- **Question:** Should both services use passwords, use SSH keys with an always-on xrdp password, or keep xrdp disabled except when needed?
- **Options and tradeoffs:** SSH keys plus an xrdp strong password balance security and convenience; passwords for both are simpler but weaker; on-demand xrdp minimizes exposure but adds manual steps.
- **User answer:** 1
- **Explicit rationale:** The user selected the recommended authentication split; no additional rationale was provided.
- **Resulting impact:** REQ-031, DEC-026, and AC-025 require SSH public-key authentication with password/root login disabled, plus an independent xrdp strong password; DEC-026 refines DEC-024.

### DISC-009: Rename Linux VMs for general home-service use

- **Situation:** The Server will host ThesisTrace as well as other programs such as a voice assistant, while the existing VM names are ThesisTrace-specific.
- **Question:** What names should identify the Linux Server and Development VMs?
- **Options and tradeoffs:** Retain the project-specific names for continuity, or use general home-service names that better reflect multiple workloads.
- **User answer:** Rename them to `home-service` and `home-service-dev`.
- **Explicit rationale:** The Server will also run programs other than ThesisTrace, including voice-assistant functionality.
- **Resulting impact:** REQ-017, REQ-018, REQ-019, REQ-031, DEC-023, DEC-027, and AC-016 use the general home-service names; resource, network, desktop, and isolation requirements do not change.

## Open Decisions

None.

## Routing/Gates

- Proposal review: pending user confirmation.
- ISO acquisition and integrity verification: pending.
- Windows base VM gate: pending.
- GPU passthrough and rollback gate: pending.
- Game compatibility gate: pending and non-guaranteed.
- Game compatibility, Windows disk expansion, a possible 64 GB host-memory upgrade, and a possible native-Windows fallback are conditional execution findings. They do not change the confirmed initial three-VM design and require a later specification change only if their measured trigger occurs.
- Linux Server baseline gate: pending.
- Linux Development baseline gate: pending.
- SPEC-0001 architecture, security, backup and deployment gates remain authoritative for ThesisTrace production.
- No VM creation or Proxmox mutation is authorized merely by materializing this SPEC.

## Revision History

| Revision | Date | Status | Changes |
| --- | --- | --- | --- |
| 1 | 2026-08-09 | proposed | Materialized the three-VM Proxmox plan, verified host baseline, resource modes, staged Windows GPU passthrough, Linux Server and Development isolation, rollback requirements and execution gates. |
| 2 | 2026-08-10 | confirmed | Confirmed the original three-VM proposal, retained separate Linux Server and Linux Development VMs, converted runtime-dependent observations into execution gates, and normalized specification relationships. |
| 3 | 2026-08-13 | Reopened before clarification: Lower Windows VM memory so Windows gaming and Linux Development can run concurrently while GPT modifies code. |
| 7 | 2026-08-13 | Reopened before clarification: Add a graphical desktop and laptop remote-access workflow to thesis-trace-dev while Windows gaming and thesis-trace-server remain active. |
| 11 | 2026-08-13 | working | Reopened to rename the Linux VMs `home-service` and `home-service-dev` for general home-service workloads. |
| 13 | 2026-08-13 | confirmed | Recorded Development VM baseline, LAN security, xrdp/XFCE, Docker/tooling, Guest Agent, and user-submitted VS Code Remote SSH evidence while retaining the remaining AC-021 project-specific validation seams. |
