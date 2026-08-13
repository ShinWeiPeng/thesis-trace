# Proxmox 三 VM 規劃與 Windows Gaming VM 安裝、GPU 直通排錯筆記

[TOC]

---

## 1. 目標與目前進度

本次工作是在一台 Proxmox VE 主機上規劃三部彼此用途分離的 VM：

| VM | 用途 | 目前狀態 |
| --- | --- | --- |
| `windows-gaming` | Windows 遊戲、Steam、鳴潮，使用 RTX 5060 Ti | Windows 已安裝，GPU 直通與 HDMI 輸出成功；NVIDIA 正式驅動與最終驗證尚待完成 |
| `thesis-trace-server` | 長時間運作的 ThesisTrace 服務 | 僅完成規劃，尚未建立 |
| `thesis-trace-dev` | ThesisTrace 功能開發 | 僅完成規劃，尚未建立 |

Windows VM 與 Development VM 預計不會同時進行高負載工作；Linux Server VM 則預計持續運作。

相關架構規格位於：

- `SPEC-0001-thesis-trace-foundation.md`
- `SPEC-0002-proxmox-three-vm-foundation.md`

---

## 2. 已確認的 Proxmox 主機環境

| 項目 | 已確認內容 |
| --- | --- |
| Hypervisor | Proxmox VE 9.2.10 |
| CPU | AMD Ryzen 5 7500F，6 核心／12 執行緒 |
| 記憶體 | 約 30.93 GiB |
| 主機板 | ASRock A620AI WiFi |
| 實體磁碟 | ADATA LEGEND 900 NVMe，約 1.02 TB |
| ISO 儲存區 | `local`，路徑 `/var/lib/vz`，主機根檔案系統約 93.93 GiB |
| VM 磁碟儲存區 | `local-lvm`，LVM-Thin 約 875.49 GB |
| 網路橋接 | `vmbr0`，Proxmox IP `192.168.2.10/24` |
| GPU | NVIDIA GeForce RTX 5060 Ti 16 GB |
| GPU PCI 位址 | `01:00.0`，PCI ID `10de:2d04` |
| GPU 音訊 PCI 位址 | `01:00.1`，PCI ID `10de:22eb` |
| IOMMU | AMD-Vi 已啟用，支援 interrupt remapping |
| GPU IOMMU 群組 | 群組 12，只有 GPU 與其音訊功能，隔離狀況良好 |

### 2.1 儲存配置判讀

安裝 Proxmox 後，唯一的 NVMe 已被分成主機系統與 LVM-Thin：

- `local` 用來存放 ISO、CT 範本、備份或匯入檔案。
- `local-lvm` 用來存放 VM 的虛擬磁碟。
- `local-lvm` 是 Thin Provisioning；建立 400 GiB VM 磁碟不代表立刻實際占用完整 400 GiB，但仍須監控 thin pool 的真實使用量。

### 2.2 三部 VM 的資源規劃

| VM | vCPU | RAM | 磁碟 | 自動啟動 | 備註 |
| --- | ---: | ---: | ---: | --- | --- |
| Linux Server | 4 | 4 GiB | 120 GiB | 是 | 長時間運作 |
| Linux Development | 8 | 12 GiB | 200 GiB | 否 | 與 Windows 避免同時重載 |
| Windows Gaming | 8 | 固定 20 GiB | 400 GiB | 否 | RTX 5060 Ti 完整直通 |

三部 VM 規劃磁碟總量為 720 GiB，為 `local-lvm` 保留約 150 GiB 的彈性空間。

---

## 3. 安裝媒體準備與上傳

已透過區域網路，從管理電腦的瀏覽器直接上傳 ISO 到 Proxmox 的 `local` 儲存區：

```text
資料中心 → pve → local (pve) → ISO 映像 → 上傳
```

實際使用的檔案：

```text
Windows_11_26H1_28000.1575_7in1.iso
virtio-win-0.1.285.iso
```

`virtio-win.iso` 不是強制檔名；帶版本號的 `virtio-win-0.1.285.iso` 完全可以使用。重要的是內容必須是可信來源的 VirtIO Windows 驅動 ISO。

Windows ISO 是自行下載的多版本統合包。由於不是標準單一版本媒體，需自行承擔來源、完整性、授權、更新與相容性風險。Proxmox 的客體作業系統設定選擇 `Microsoft Windows` 與 `11/2022/2025`，只是讓 Proxmox 套用適合 Windows 11 的 VM 預設值，不需要與 ISO 的 `26H1` 名稱完全相同。

---

## 4. Windows Gaming VM 建立設定

### 4.1 一般與作業系統

| 設定 | 值 |
| --- | --- |
| VM ID | `100` |
| 名稱 | `windows-gaming` |
| Windows ISO | `Windows_11_26H1_28000.1575_7in1.iso` |
| 客體類型 | Microsoft Windows |
| 版本設定 | Windows 11／2022／2025 |
| 額外 VirtIO ISO | `virtio-win-0.1.285.iso` |

### 4.2 系統

| 設定 | 值 |
| --- | --- |
| Machine | `q35` |
| BIOS | OVMF（UEFI） |
| EFI 磁碟 | `local-lvm` |
| Pre-Enroll keys | 開啟 |
| TPM | TPM 2.0，儲存在 `local-lvm` |
| SCSI 控制器 | VirtIO SCSI single |
| QEMU Guest Agent | 開啟 |

Pre-Enroll keys 會在 OVMF UEFI 中預先放入 Microsoft Secure Boot 信任金鑰，讓 Windows 11 可使用 Secure Boot。它不是 Windows 產品金鑰。

### 4.3 系統磁碟

| 設定 | 值 |
| --- | --- |
| Bus | SCSI 0 |
| 儲存區 | `local-lvm` |
| 容量 | 400 GiB |
| Discard | 開啟 |
| IO thread | 開啟 |
| SSD emulation | 開啟 |
| Async IO | `io_uring` |
| Backup | 關閉 |

`io_uring` 是 Linux 的非同步 I/O 介面。QEMU 可同時送出多個磁碟請求，不必等待每個請求完成後才能提交下一個，有助於降低虛擬磁碟 I/O 額外負擔。

關閉 `Backup` 是因為 VM 磁碟已有 400 GiB，而且目前尚未規劃足夠的 Proxmox 備份儲存空間；這不等於不需要備份，之後仍應建立正式備份策略。

### 4.4 CPU 與記憶體

| 設定 | 值 |
| --- | --- |
| CPU 類型 | `host` |
| Sockets | 1 |
| Cores | 8 |
| NUMA | 關閉 |
| 記憶體 | 20480 MiB |
| Ballooning | 關閉，`balloon=0` |
| KSM | 關閉，`allow-ksm=0` |

Ballooning 允許 Proxmox 動態向 VM 收回或補回記憶體。遊戲 VM 為了效能與延遲較穩定，採用固定 20 GiB，不使用 Ballooning。

Proxmox 曾顯示約 `100.27%（20.05 GiB／20.00 GiB）`。這不代表 Windows 應用程式真的用光 RAM，而是 Ballooning 關閉後，Proxmox 主要看到 QEMU 已配置或觸及的固定客體記憶體，加上少量程序開銷。實際 Windows 記憶體壓力應以 Windows 工作管理員為準。

### 4.5 網路

| 設定 | 值 |
| --- | --- |
| Bridge | `vmbr0` |
| Model | VirtIO（paravirtualized） |
| VLAN | 無 |
| Proxmox Firewall | 開啟 |
| Rate limit | Unlimited |

Windows 安裝完成並載入 NetKVM 驅動後，曾取得 DHCP 位址：

```text
192.168.2.105
```

此位址可能隨 DHCP 改變，若要長期使用 RDP 或遊戲串流，應在路由器建立 DHCP reservation。

---

## 5. Windows 安裝過程

### 5.1 從 ISO 啟動

第一次啟動時出現：

```text
Press any key to boot from CD or DVD......
```

必須及時按任意鍵。若逾時，OVMF 會依序嘗試 PXE、HTTP Boot，畫面可能出現：

```text
Start PXE over IPv4
PXE-E16: No valid offer received
Start HTTP Boot over IPv4
```

這不是網路故障，而是錯過從 Windows ISO 開機的按鍵時機。重新啟動 VM，在提示出現時立即按鍵即可。

### 5.2 安裝程式找不到 400 GB 磁碟

Windows 安裝程式一開始看不到任何磁碟，原因是系統磁碟使用 VirtIO SCSI，Windows ISO 沒有內建相應驅動。

解決方式：

1. 點選「載入驅動程式」。
2. 瀏覽 VirtIO 光碟。
3. 選擇：

```text
vioscsi\w11\amd64
```

4. 載入後，安裝程式顯示：

```text
磁碟機 0 未配置的空間 400.0 GB
```

5. 選取未配置空間，直接按「下一步」，讓 Windows 自動建立 EFI、MSR、系統與復原分割區。

### 5.3 Windows 初始設定找不到網路

Windows OOBE 顯示「讓我們將您連線到網路」，但無網路介面。原因是 VM 使用 VirtIO 網卡，Windows 尚未載入 NetKVM 驅動。

解決方式：

1. 點選「安裝驅動程式」。
2. 從 VirtIO 光碟選擇：

```text
NetKVM\w11\amd64
```

3. 驅動載入後，系統要求重新開機。
4. 重新啟動後完成 OOBE 並進入 Windows 桌面。

### 5.4 安裝 VirtIO Guest Tools

進入桌面後，從 VirtIO 光碟執行：

```text
virtio-win-guest-tools.exe
```

完成後可提供 VirtIO 驅動、QEMU Guest Agent 與其他整合元件。QEMU Guest Agent 正常後，Proxmox 能顯示 VM 的 IP，並可較可靠地執行關機等操作。

### 5.5 Windows Update 與裝置檢查

完成 Windows Update，直到顯示系統為最新狀態。裝置管理員未看到明顯黃色警告符號，VirtIO 磁碟與網路皆正常。

安裝完成後，兩個 ISO 已從 VM 卸載；CD/DVD 裝置仍可保留為空的 `media=cdrom`，不影響使用。

---

## 6. 基準快照

在 GPU 直通前、Windows VM 關機狀態下建立快照：

```text
win-base-updated
```

快照內容包含：

- Windows 系統磁碟。
- EFI 磁碟。
- TPM 狀態。
- 當時的 VM 設定。

快照說明記錄 Windows、VirtIO、QEMU Guest Agent 與 Windows Update 已完成，GPU 尚未直通。建立時未勾選 RAM 是正確的，因為 VM 已關機，不需要保存執行中記憶體狀態。

快照適合作為短期設定回復點，但不能取代獨立備份；若 NVMe 故障，位於同一顆磁碟上的快照也會一起遺失。

---

## 7. IOMMU 與 GPU 隔離確認

### 7.1 `dmesg` 的檢查目的

使用：

```bash
dmesg | grep -Ei 'AMD-Vi|IOMMU'
```

主要確認：

- AMD IOMMU 是否啟用。
- 核心是否建立 IOMMU groups。
- DMA remapping 是否運作。
- Interrupt remapping 是否啟用。
- 是否出現初始化失敗或韌體錯誤。

已觀察到 AMD-Vi、translated domain、interrupt remapping 與 IOMMU group 建立訊息，因此不需要額外加入 `amd_iommu=on`。

### 7.2 IOMMU 群組 12

群組 12 只有：

```text
01:00.0 NVIDIA GeForce RTX 5060 Ti
01:00.1 NVIDIA High Definition Audio Controller
```

一張顯示卡通常同時提供顯示與 HDMI/DisplayPort 音訊功能；兩者放在同一 IOMMU group 是合理結果。群組內沒有 NVMe、網卡或其他主機必要裝置，因此可將整組安全交給同一部 Windows VM，不需要 ACS override。

PCI ID 確認結果：

```text
01:00.0 → 10de:2d04
01:00.1 → 10de:22eb
```

---

## 8. 建立 SSH 後備管理通道

Ryzen 5 7500F 沒有內顯，而 RTX 5060 Ti 是唯一顯示卡。GPU 交給 VM 後，Proxmox 主機可能不再輸出本機畫面，因此先確認 Web UI 與 SSH 可用。

在管理用 Windows 電腦開啟 PowerShell：

```powershell
ssh root@192.168.2.10
```

第一次連線輸入 `yes` 接受主機指紋，再輸入 Proxmox `root` 密碼。密碼輸入時不顯示字元是正常行為。

登入成功的提示字元：

```text
root@pve:~#
```

驗證：

```bash
hostname
ip -br address
```

已確認主機名稱為 `pve`，`vmbr0` 位址為 `192.168.2.10/24`。

SSH 不是 GPU 直通的必要條件，而是沒有本機畫面時的後備管理入口。它與 Proxmox Web UI 一樣依賴網路；若主機網路完全中斷，兩者都無法使用。

---

## 9. VFIO 綁定 RTX 5060 Ti

### 9.1 綁定前狀態

使用：

```bash
lspci -nnk -s 01:00.0
lspci -nnk -s 01:00.1
cat /proc/cmdline
proxmox-boot-tool status
```

觀察結果：

- `01:00.0` 當時沒有 `Kernel driver in use`，只有可用模組 `nvidiafb`、`nouveau`。
- `01:00.1` 當時由 `snd_hda_intel` 使用。
- 核心命令列為 `root=/dev/mapper/pve-root ro quiet`。
- `proxmox-boot-tool status` 顯示 `/etc/kernel/proxmox-boot-uuids does not exist`。

最後一項表示這次安裝不是由 `proxmox-boot-tool` 管理 ESP 同步，不代表系統故障。因此本次沒有執行 `proxmox-boot-tool refresh`，也沒有修改 GRUB 核心參數。

### 9.2 檢查既有設定

先確認沒有既有 VFIO 規則，避免覆寫使用者設定：

```bash
grep -RniE 'vfio|10de:2d04|10de:22eb' \
  /etc/modprobe.d /etc/modules-load.d 2>/dev/null \
  || echo "沒有既有 VFIO 設定"
```

並確認 PCI ID 只對應目標裝置：

```bash
lspci -nn | grep -E '10de:(2d04|22eb)'
```

### 9.3 建立 VFIO 設定

先備份原始 initramfs 模組清單：

```bash
cp -a /etc/initramfs-tools/modules \
  /root/initramfs-modules.before-vfio
```

加入開機早期載入的模組：

```bash
for module in vfio vfio_iommu_type1 vfio_pci; do
  grep -qxF "$module" /etc/initramfs-tools/modules \
    || echo "$module" >> /etc/initramfs-tools/modules
done
```

建立 `/etc/modprobe.d/vfio.conf`：

```bash
printf '%s\n' \
'options vfio-pci ids=10de:2d04,10de:22eb disable_vga=1' \
'softdep nouveau pre: vfio-pci' \
'softdep snd_hda_intel pre: vfio-pci' \
> /etc/modprobe.d/vfio.conf
```

檔案內容：

```text
options vfio-pci ids=10de:2d04,10de:22eb disable_vga=1
softdep nouveau pre: vfio-pci
softdep snd_hda_intel pre: vfio-pci
```

`/etc/modules` 在目前系統已標示為 obsolete，因此本次改用 `/etc/initramfs-tools/modules`，確保 VFIO 模組被放入 initramfs 並在開機早期載入。

### 9.4 更新與驗證 initramfs

先驗證模組存在：

```bash
modinfo vfio >/dev/null &&
modinfo vfio_iommu_type1 >/dev/null &&
modinfo vfio_pci >/dev/null &&
echo "VFIO 模組檢查通過"
```

重建所有已安裝核心的 initramfs：

```bash
update-initramfs -u -k all
```

輸出的：

```text
No /etc/kernel/proxmox-boot-uuids found, skipping ESP sync.
```

符合此主機的啟動方式，不是錯誤。

確認目前核心的 initramfs 已包含設定與模組：

```bash
lsinitramfs /boot/initrd.img-$(uname -r) \
  | grep -E 'vfio.*\.ko|etc/modprobe.d/vfio.conf'
```

已確認包含：

```text
etc/modprobe.d/vfio.conf
vfio.ko
vfio-pci.ko
vfio-pci-core.ko
vfio_iommu_type1.ko
```

### 9.5 重開機後驗證

Windows VM 保持關機，執行：

```bash
reboot
```

主機重新上線後，再透過 SSH 執行：

```bash
uname -r
lspci -nnk -s 01:00.0
lspci -nnk -s 01:00.1
```

兩個功能均成功顯示：

```text
Kernel driver in use: vfio-pci
```

這表示 Proxmox 主機已不再使用 RTX 5060 Ti，而是將其保留給虛擬機。

### 9.6 回復 VFIO 主機設定

若尚未把 GPU 加入 VM，且需要讓主機重新使用裝置，可透過 SSH 執行回復：

```bash
cp -a /root/initramfs-modules.before-vfio \
  /etc/initramfs-tools/modules
rm /etc/modprobe.d/vfio.conf
update-initramfs -u -k all
reboot
```

這會移除本次建立的 PCI ID 綁定。執行前仍應確認備份檔存在，避免覆蓋錯誤目標：

```bash
ls -l /root/initramfs-modules.before-vfio
```

---

## 10. 將 GPU 加入 Windows VM

Windows VM 關機後，在 Proxmox：

```text
100 (windows-gaming) → 硬體 → 增加 → PCI 裝置
```

選擇：

```text
0000:01:00.0 NVIDIA GB206 [GeForce RTX 5060 Ti]
```

設定：

| 選項 | 設定 |
| --- | --- |
| Raw Device | `0000:01:00.0` |
| All Functions | 開啟 |
| PCI Express | 開啟 |
| Primary GPU | 開啟 |
| ROM-Bar | 保持預設開啟 |
| ROM file | 不指定 |

All Functions 會同時帶入 `01:00.1` 音訊，所以不需要再新增第二個 PCI 裝置。

最後的 VM 設定顯示：

```text
PCI 裝置 (hostpci0)  0000:01:00,pcie=1,x-vga=1
```

首次啟動時保留 Proxmox 的「顯示卡：預設」，讓 noVNC 暫時作為後備畫面。實體電視直接連接 RTX 5060 Ti HDMI；啟動 Windows VM 後，電視已成功顯示 Windows 畫面，證明 GPU 直通、OVMF 與實體輸出可運作。

目前尚未確認 NVIDIA Game Ready Driver 安裝完成。後續應從 NVIDIA 官方下載 NVIDIA App，安裝 Game Ready Driver；安裝過程中電視可能短暫黑畫面、閃爍或改變解析度，這屬正常驅動切換現象。

---

## 11. USB 直通與 Logi Receiver 問題

### 11.1 USB 直通的所有權

實體 USB 裝置同一時間只能由主機或一部 VM 控制，不能同時交給所有 VM。即使各 VM 不會同時開機，也應避免把同一裝置同時以多種規則重複加入同一 VM。

兩種常用方式：

| 方式 | 行為 | 適用情境 |
| --- | --- | --- |
| USB Vendor/Device ID | 跟著特定裝置，不受插入哪個 USB 埠影響 | Logi Receiver、固定鍵盤、固定設備 |
| USB Port | 跟著特定實體埠，插入該埠的裝置交給 VM | 隨身碟、臨時更換的 USB 裝置 |

Windows VM 原本已加入：

```text
usb0 → host=2-3
usb1 → host=2-4
```

### 11.2 Logi 滑鼠無法使用

Receiver 插入主機後，Windows VM 無法使用滑鼠。透過 SSH 執行：

```bash
lsusb
lsusb -t
```

確認 Receiver：

```text
046d:c52b Logitech, Inc. Unifying Receiver
Bus 001 → Port 003
```

根本原因是同一個實體 USB 3.x 插孔，USB 2.0 與 USB 3.x 裝置可能使用不同的邏輯 root hub／路徑：

- VM 原規則是 `2-3`、`2-4`，對應 USB 3.x 路徑。
- Logi Unifying Receiver 是 USB 2.0 裝置，實際列舉在 Bus 001 Port 003。
- 因此只設定 USB 3.x 邏輯埠，不一定會涵蓋插在相同實體孔位的 USB 2.0 裝置。

解決方式是在 VM 關機後新增 USB 裝置，使用 Vendor/Device ID：

```text
046d:c52b Logitech Unifying Receiver
```

不勾選 USB3。重新啟動 Windows VM 後，Logi 滑鼠即可使用。

原本的 `2-3`、`2-4` 可繼續保留給 USB 3.x 隨身碟。Logi Receiver 則依 `046d:c52b` 固定交給 Windows VM。

同一次檢查也看到鍵盤：

```text
0a5f:1012 Jing-Mold USB Keyboard
```

如果此鍵盤日後無法在 VM 使用，可用相同方式按 Vendor/Device ID 單獨加入。

---

## 12. 遠端操作方式

### 12.1 Proxmox noVNC

```text
100 (windows-gaming) → 主控台旁的小箭頭 → noVNC
```

noVNC 適合安裝、維護與 GPU 故障排除，不適合高畫質或低延遲遊戲。GPU 設為 Primary 後，noVNC 與電視可能顯示不同桌面，或其中一邊暫時黑畫面。

### 12.2 Windows Remote Desktop

Windows Pro／Enterprise 可啟用內建 RDP：

```text
設定 → 系統 → 遠端桌面
```

VM 內的帳號必須有密碼。在管理電腦按 `Win + R`，輸入：

```text
mstsc
```

再連線到 Windows VM 的 IPv4 位址。RDP 適合管理與安裝軟體，但不適合判斷實體 HDMI、低延遲遊戲或部分反作弊遊戲的實際行為；連線時電視的本機工作階段也可能鎖定或切換。

Windows Home 不能作為內建 RDP 主機。遊戲串流工具應等 NVIDIA 驅動與 GPU 重啟穩定性驗證完成後再規劃。

---

## 13. 遊戲與反作弊限制

Windows VM 的 GPU 直通成功，不代表所有遊戲都允許在 VM 中執行。

已知使用情境包含：

- 鳴潮。
- Steam 遊戲。

鳴潮使用核心層級的 Anti-Cheat Expert（ACE）。不同遊戲、版本與反作弊政策可能封鎖、限制或不支援虛擬機，因此無法在安裝前保證相容。應以實際安裝、啟動與官方政策驗證為準。

本規劃不採用：

- 隱藏 VM 身分。
- 修改反作弊系統。
- 規避遊戲平台限制。
- ACS override。

---

## 14. Linux Server 與 Development VM 待辦

兩部 Linux VM 尚未建立，後續預定順序：

1. 完成 NVIDIA 驅動與 Windows GPU 重開機測試。
2. 驗證 RTX 5060 Ti 16 GB、HDMI 音訊與 USB 輸入。
3. 建立 GPU 直通完成後的第二個里程碑快照。
4. 實際測試 Steam 與鳴潮相容性。
5. 建立 Linux Server VM。
6. 建立 Linux Development VM。

Linux Server VM 預計承載 ThesisTrace：

- Ubuntu Server 26.04 LTS。
- Docker Compose。
- Caddy。
- PostgreSQL。
- FastAPI。
- React／TypeScript 前端。
- 背景 workers。
- VPN-only 管理。
- Backblaze B2 加密備份。

Development VM 僅作為開發環境，使用 Git、Docker、VS Code Remote SSH 等工具，不直接取代正式 Server VM。

---

## 15. 目前驗收狀態與下一步

### 15.1 已完成

- Proxmox 9.2.10 更新與重新啟動。
- 磁碟、`local`、`local-lvm` 容量確認。
- Windows Gaming VM 建立與 Windows 安裝。
- VirtIO SCSI、NetKVM、Guest Tools、QEMU Guest Agent 安裝。
- Windows Update 完成至當時最新狀態。
- 建立 `win-base-updated` 快照。
- AMD IOMMU 與 GPU IOMMU group 驗證。
- SSH 後備通道驗證。
- VFIO 綁定 GPU 與 GPU 音訊。
- RTX 5060 Ti 加入 Windows VM。
- 電視透過 RTX 5060 Ti HDMI 顯示 Windows。
- Logi Unifying Receiver USB 直通問題排除。

### 15.2 尚待完成

- 安裝並確認 NVIDIA Game Ready Driver。
- 在 Windows 裝置管理員確認 RTX 5060 Ti 無錯誤。
- 驗證顯示記憶體為 16 GB。
- 驗證 NVIDIA HDMI Audio 與電視聲音。
- 執行 Windows 正常重新啟動、關機再開機測試。
- 評估是否停用 Windows Fast Startup，以降低 GPU 重新初始化問題。
- 決定是否保留 Proxmox 虛擬顯示卡作為 noVNC 後備。
- 建立 GPU 完成里程碑快照。
- 實測 Steam、鳴潮與 ACE 相容性。
- 建立 Linux Server VM 與 Development VM。
- 規劃獨立備份目的地與 DHCP reservations。

---

## 16. Preserved discussion

### 16.1 Superseded or corrected points

- `virtio-win.iso` 曾被當作示意檔名；實際檔名可以包含版本號，本次使用 `virtio-win-0.1.285.iso`。
- Proxmox 的 Windows `11/2022/2025` 客體設定不需要與 ISO 的 `26H1` 名稱完全一致；它是 VM 最佳化類型，不是嚴格的 Windows build 驗證。
- 曾嘗試查看 `/etc/modules`，系統提示此介面已 obsolete。本次最終使用 `/etc/initramfs-tools/modules` 讓 VFIO 在 initramfs 階段提早載入。
- `proxmox-boot-tool status` 回報缺少 `proxmox-boot-uuids`，後續確認這代表該工具未管理此安裝的 ESP，而非 Proxmox 啟動故障。
- Proxmox 顯示 Windows VM 記憶體略高於 100%，不是 Windows 應用程式真的超出 20 GiB，而是固定記憶體配置與 QEMU 開銷的呈現方式。
- 最初假設固定 USB 實體埠可以涵蓋所有裝置；實際排錯確認 USB 2.0 與 USB 3.x 可能走不同邏輯路徑，固定 Receiver 使用 Vendor/Device ID 較可靠。

---

## 17. References

- [Proxmox VE Administration Guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf)
- [Proxmox PCI(e) Passthrough](https://pve.proxmox.com/wiki/PCI(e)_Passthrough)
- [Debian mkinitramfs manual](https://manpages.debian.org/trixie/initramfs-tools-core/mkinitramfs.8.en.html)
- [Stable VirtIO Windows drivers](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/)
- [NVIDIA App official download](https://www.nvidia.com/en-us/software/nvidia-app/)

###### tags: `Proxmox` `Windows11` `GPU-Passthrough` `VFIO` `VirtIO` `ThesisTrace`
