# Proxmox A620AI WiFi／Bluetooth 直通與代碼 43 排錯筆記

[TOC]

---

## 1. 目的與結論

ASRock A620AI WiFi 主機板具備 Wi-Fi 6E 與 Bluetooth 5.2。雖然兩個功能來自同一張 M.2 Key E 無線模組，但在作業系統內是兩個不同裝置：

| 功能 | 連接方式 | Proxmox 裝置 |
| --- | --- | --- |
| Wi-Fi | PCIe | `05:00.0`，MediaTek MT7922 |
| Bluetooth | USB | `0e8d:0616`，MediaTek Wireless_Device |

本次檢查後的結論：

- 內建 Wi-Fi 不適合直接直通給 Windows VM，因為它與多個主機必要裝置共用 IOMMU group 14。
- Windows VM 已透過 VirtIO 網卡與 `vmbr0` 上網，不需要為一般網路用途直通 Wi-Fi。
- 內建 Bluetooth 可獨立以 USB Vendor/Device ID 直通。
- Bluetooth 直通後 Windows 已能辨識裝置，但目前出現裝置管理員「代碼 43」，下一步是安裝 ASRock 官方 MediaTek Bluetooth 驅動並進行完整關機／啟動測試。

---

## 2. 主機板無線模組架構

ASRock 官方規格列出：

- 802.11axe Wi-Fi 6E。
- 2x2 天線。
- Bluetooth 5.2。
- 垂直 M.2 Key E 2230 WiFi/BT 模組插槽。

Wi-Fi 與 Bluetooth 雖然在同一張實體卡上，但資料路徑不同：

```text
M.2 WiFi/BT 模組
├── PCIe → MediaTek MT7922 Wi-Fi
└── USB  → MediaTek Bluetooth
```

因此 Proxmox 無法使用一筆硬體設定同時加入兩個功能；必須分別處理 PCIe 與 USB 直通。

---

## 3. 透過 SSH 識別裝置

### 3.1 登入 Proxmox

在管理用 Windows 電腦開啟 PowerShell：

```powershell
ssh root@192.168.2.10
```

若只輸入：

```powershell
ssh 192.168.2.10
```

SSH 會預設使用目前 Windows 帳號，例如 `Hugo`，而不是 Proxmox 的 `root`，因此可能驗證失敗。

### 3.2 識別 Wi-Fi PCIe 裝置

執行：

```bash
lspci -nnk | grep -A3 -Ei 'network controller|wireless'
```

確認結果：

```text
05:00.0 Network controller [0280]:
MEDIATEK Corp. MT7922 802.11ax PCI Express Wireless Network Adapter
[14c3:0616]

Subsystem:
MEDIATEK Corp. MT7922 802.11ax PCI Express Wireless Network Adapter
[14c3:0616]

Kernel driver in use: mt7921e
Kernel modules: mt7921e
```

已確認 Wi-Fi 裝置資訊：

| 項目 | 值 |
| --- | --- |
| PCI 位址 | `05:00.0` |
| Vendor/Device ID | `14c3:0616` |
| 型號 | MediaTek MT7922 |
| Proxmox 驅動 | `mt7921e` |

### 3.3 識別 Bluetooth USB 裝置

執行：

```bash
lsusb | grep -Ei 'mediatek|bluetooth|wireless'
```

確認結果：

```text
Bus 001 Device 002: ID 0e8d:0616 MediaTek Inc. Wireless_Device
```

已確認 Bluetooth 裝置資訊：

| 項目 | 值 |
| --- | --- |
| USB Vendor/Device ID | `0e8d:0616` |
| 顯示名稱 | MediaTek Inc. Wireless_Device |
| USB 模式 | USB 2.0 |

---

## 4. Wi-Fi IOMMU 群組檢查

### 4.1 檢查指令

```bash
WIFI_DEVICE=0000:05:00.0
WIFI_GROUP=$(basename "$(readlink /sys/bus/pci/devices/$WIFI_DEVICE/iommu_group)")
echo "Wi-Fi IOMMU group: $WIFI_GROUP"

for device in /sys/kernel/iommu_groups/$WIFI_GROUP/devices/*; do
  lspci -nns "${device##*/}"
done
```

### 4.2 檢查結果

Wi-Fi 位於：

```text
IOMMU group 14
```

群組中包含：

```text
03:00.0 AMD USB controller
03:00.1 AMD 500 Series Chipset SATA Controller
03:00.2 AMD 500 Series Chipset Switch Upstream Port
04:00.0 AMD 500 Series Chipset Switch Downstream Port
04:01.0 AMD 500 Series Chipset Switch Downstream Port
04:02.0 AMD 500 Series Chipset Switch Downstream Port
05:00.0 MediaTek MT7922 Wi-Fi
06:00.0 Realtek RTL8125 2.5GbE Controller
07:00.0 Realtek RTL8111/8168 Gigabit Ethernet Controller
```

### 4.3 為何不能直通內建 Wi-Fi

IOMMU 的安全邊界是整個 group，而不是單一 PCI function。若將 `05:00.0` 單獨交給 VM，其他同組裝置仍由 Proxmox 使用，隔離條件並不理想；部分系統也可能直接拒絕啟動 VM。

若把 group 14 整組交給 Windows VM，Proxmox 可能同時失去：

- USB 控制器。
- SATA 控制器。
- 兩張有線網卡。
- 多個晶片組 PCI bridge。

這可能導致主機網路、USB 或儲存失效，因此不能這樣設定。

本次也不採用 ACS override。ACS override 會在軟體層將群組拆開，但不能保證硬體真的具有對等的 DMA 隔離，且會增加安全性與穩定性風險。

### 4.4 Windows VM 的網路替代方案

目前 Windows VM 已使用：

```text
VirtIO 網卡 → vmbr0 → 實體有線 LAN
```

對遊戲而言，有線 VirtIO 網路通常比 Wi-Fi 具有更穩定的延遲，因此一般上網、下載與線上遊戲不需要直通內建 Wi-Fi。

若 Windows 必須具備原生 Wi-Fi、Wi-Fi Direct 或行動熱點功能，建議另外使用一支 USB Wi-Fi 網卡，再依 Vendor/Device ID 直通給 Windows VM。

---

## 5. Bluetooth USB 直通

### 5.1 Proxmox 設定

正常關閉 Windows VM，等待狀態成為 `stopped`，再進入：

```text
100 (windows-gaming) → 硬體 → 增加 → USB 裝置
```

設定：

| 選項 | 值 |
| --- | --- |
| 方式 | 使用 USB Vendor/Device ID |
| 裝置 | `0e8d:0616 MediaTek Inc. Wireless_Device` |
| USB3 | 不勾選 |

此 Bluetooth 介面是 USB 2.0 裝置，因此不需要開啟 USB3。

重新啟動 Windows VM 後，裝置管理員已出現：

```text
藍牙
└── Generic Bluetooth Adapter
```

這代表 USB passthrough 已將裝置交給 Windows；若直通完全失敗，Windows 通常不會看到這個裝置。

---

## 6. Generic Bluetooth Adapter 代碼 43

### 6.1 目前現象

Windows 裝置管理員顯示黃色驚嘆號，裝置狀態為：

```text
Windows 已停止這個裝置，因為它發生了問題。（代碼 43）
```

代碼 43 表示其中一個控制裝置的驅動向 Windows 回報裝置初始化失敗。它不等於 Proxmox 沒有直通 USB，也不一定代表硬體損壞。

在目前情境中，優先考慮：

1. Windows 使用 Generic Bluetooth Adapter，而非適合 MT7922 的 MediaTek 驅動。
2. 藍牙 USB 裝置需要在 QEMU 完整結束後重新掛接。
3. Windows 11 26H1 預覽版本可能存在驅動相容性問題。

### 6.2 安裝官方 Bluetooth 驅動

在 Windows VM 開啟 ASRock A620AI WiFi 官方頁面：

```text
Support → Download → Windows 11 64-bit
```

下載並安裝：

```text
MediaTek Bluetooth Driver
```

注意事項：

- 優先使用 ASRock 官方驅動，不使用第三方驅動下載網站。
- 不需要安裝 MediaTek Wi-Fi 驅動，因為 PCIe Wi-Fi 沒有直通給 Windows。
- 若下載項目是 MediaTek WLAN/Bluetooth 統合包，可以安裝；Windows 只會對實際存在的裝置套用驅動。
- 不建議依賴 ASRock Auto Driver Installer，因為 VM 對 Windows 顯示的是虛擬 `q35` 主機板，工具可能無法判定實體主機板型號。

### 6.3 必須完整關機再啟動

安裝驅動後不要只在 Windows 執行「重新啟動」，請：

1. 在 Windows 選擇「關機」。
2. 等待 Proxmox 顯示 VM 為 `stopped`。
3. 等待約 10 秒。
4. 從 Proxmox 重新啟動 Windows VM。

原因是一般 Windows 重新啟動不一定會結束 QEMU 程序，也不一定會讓 USB passthrough 裝置完整釋放。VM 完整停止後重新啟動，QEMU 會重新宣告並掛接 `0e8d:0616`。

### 6.4 若代碼 43 仍存在

依序執行：

1. 確認 Proxmox 中 Bluetooth USB 裝置的 USB3 未勾選。
2. 在裝置管理員右鍵 `Generic Bluetooth Adapter`。
3. 選擇「解除安裝裝置」。
4. 不勾選刪除驅動程式。
5. 將 VM 完整關機，等待成為 `stopped`。
6. 再次啟動 VM，讓 Windows 使用已安裝的 MediaTek 驅動重新列舉裝置。

若仍顯示代碼 43，再進行下一層檢查：

- 檢查裝置的「驅動程式」頁籤，確認供應商是否已從 Microsoft／Generic 改為 MediaTek。
- 重新確認 Proxmox 硬體清單只有一筆 `0e8d:0616`，避免同一 USB 裝置被重複設定。
- 在 Windows VM 關機狀態重新啟動 Proxmox 主機，讓內建 Bluetooth USB 裝置重新上電初始化。
- 確認 ASRock 官方驅動是否明確支援目前的 Windows 11 build。
- 若官方驅動仍不支援 Windows 11 26H1 預覽版本，考慮改用正式支援版 Windows 11，或使用獨立 USB Bluetooth dongle。

---

## 7. 安全與所有權限制

- Bluetooth 直通後，同一時間只能由 Windows VM 使用，Proxmox 主機不能同時使用它。
- 若 Windows VM 關機，裝置才會被 QEMU 釋放。
- 不要把同一個 `0e8d:0616` 同時以 USB Port 與 Vendor/Device ID 重複加入。
- Linux Server VM 預計長時間運作，不應再加入同一個 Bluetooth 裝置。
- Windows VM 與 Development VM 即使不會同時開機，仍應明確指定哪一部 VM 擁有固定裝置。

---

## 8. 驗收清單

### 8.1 已完成

- 確認 A620AI WiFi 支援 Wi-Fi 6E 與 Bluetooth 5.2。
- 識別 PCIe Wi-Fi：`05:00.0`、`14c3:0616`。
- 識別 USB Bluetooth：`0e8d:0616`。
- 確認 Wi-Fi 位於 IOMMU group 14。
- 確認 group 14 另有 USB、SATA、PCI bridge 與兩張有線網卡。
- 決定不直通內建 Wi-Fi，也不使用 ACS override。
- 以 Vendor/Device ID 將 Bluetooth 加入 Windows VM。
- Windows 已辨識 `Generic Bluetooth Adapter`。

### 8.2 尚待完成

- 安裝 ASRock 官方 MediaTek Bluetooth Driver。
- 完整關閉並重新啟動 Windows VM。
- 確認裝置管理員代碼 43 消失。
- 確認「設定 → 藍牙與裝置」出現正常藍牙開關。
- 實際配對藍牙手把、耳機或其他裝置。
- 測試 VM 多次關機／啟動後 Bluetooth 是否持續可用。

---

## 9. References

- [ASRock A620AI WiFi 官方規格與支援頁](https://www.asrock.com/mb/AMD/A620AI%20WiFi/index.asp)
- [ASRock A620AI WiFi 使用手冊](https://download.asrock.com/Manual/A620AI%20WiFi.pdf)
- [Microsoft：裝置管理員錯誤代碼](https://support.microsoft.com/en-US/Windows/Hardware/Drivers/error-codes-in-device-manager-in-windows)
- [Microsoft Learn：Code 43／CM_PROB_FAILED_POST_START](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/cm-prob-failed-post-start)

###### tags: `Proxmox` `A620AI-WiFi` `Bluetooth` `IOMMU` `USB-Passthrough` `Windows11`
