# pyRevit 功能區單鍵檢查

把高頻檢查做成 Revit 功能區按鈕（參考 [pyRevit](https://github.com/pyrevitlabs/pyRevit) 的擴充格式）。兩顆按鈕都是**唯讀**，結果顯示在 pyRevit 輸出視窗，可點連結選取元件。

| 按鈕 | 做什麼 |
|---|---|
| 讀取 SCADA 參數 | 找出族群名稱含「機櫃」的電氣設備（實際模型有 `SB11_RTU機櫃_…` 這類不含 `SCADA_機櫃` 的名稱），列出 16 個 `SCADA_*` 共用參數中「缺少」與「空白」者（以 GUID 查找，失敗再用名稱）；不含「機櫃」的電氣設備會列在「未納入」清單 |
| 盤點視圖電纜架 | 盤點目前作用中視圖的電纜架與配件，依類型＋尺寸統計數量與長度 |

## 安裝

1. 安裝 pyRevit（需 5.x 才支援 Revit 2025）。
2. pyRevit 設定 → Custom Extension Directories，加入本資料夾 `pyrevit`（是 `.extension` 的上一層，不是 `.extension` 本身）。
3. Save Settings and Reload。功能區出現「SCADA檢查」頁籤。

## 使用方式

功能區有 pyRevit 內建頁籤和本擴充的「**SCADA檢查**」頁籤，按鈕在後者的「高頻檢查」面板。兩顆按鈕都只讀取，不修改模型。

1. **讀取 SCADA 參數**：不需選取任何東西，直接按。視窗會列出所有族群名稱含「機櫃」的設備，標出缺少與空白的 SCADA 參數，並在下方列出未納入的電氣設備。元件編號可點選，Revit 會選取該元件。
2. **盤點視圖電纜架**：先切到要盤點的視圖（平面、剖面或 3D），再按。只統計該視圖可見的電纜架與配件，依類型與尺寸列出數量和長度。在明細表或圖紙上按會出現提示，需回到圖形視圖。
3. 結果視窗看完直接關閉即可。修改 `script.py` 後，按 pyRevit 頁籤的 Reload，或直接重按按鈕。

## 結構

```
DynamoToolbox.extension/
  extension.json
  lib/check_logic.py        純 Python 邏輯（無 Revit API，可單獨測試）
  lib/scada_params.json     複製自 toolkit/config/parameter_dictionary.json（有測試比對一致）
  SCADA檢查.tab/高頻檢查.panel/<按鈕>.pushbutton/script.py
```

## 測試

```powershell
cd pyrevit; python -m pytest tests
```

## 執行環境與尚未驗證

- 腳本刻意相容 IronPython 2.7 與 CPython 3（無 f-string），未加 `#! python3`，走 pyRevit 預設引擎。
- 若要把既有 Dynamo CPython 腳本移植進來，要核對：pyRevit CPython 為 3.12（pythonnet）、不支援具名索引器（用 `get_Parameter()`）、一個 Revit session 只有一個直譯器（重載不會重啟）。
- **已實測（2026-11-24，Revit 2025.5＋pyRevit 7.1.0，模型 DN-ESC-SB11-0000-v2.2）**：頁籤與兩顆按鈕載入；盤點電纜架在 3D 視圖得 9 段、8 個配件、24.59 m（小計加總一致），配件尺寸如預期顯示 `-`；SCADA 參數檢查找到 2 台機櫃（`SCADA_機櫃_GEN-RJ45-PP-01` 完整；`SB11_RTU機櫃_600x1000x2100` 的 `SCADA_備註` 空白，空白參數顯示正常），`linkify` 正常。
- **尚未實測**：「缺少」參數的顯示（只有單元測試涵蓋）、非圖形視圖（明細表、圖紙）的提示、多台機櫃的模型。icon.png 規格未查證，圖示尚未提供（按鈕先以文字顯示）。

## Smart App Control 封鎖 DLL（已知問題）

pyRevit 每次載入擴充，會在 `%APPDATA%\pyRevit\2025\` 現場編譯沒有簽章的 DLL。Windows 11 的 Smart App Control 開著時，可能擋下這些 DLL，Revit 啟動時 pyRevit 輸出視窗出現：

```
Error building/loading extension 'DynamoToolbox': ... 應用程式控制原則已封鎖此檔案。 (0x800711C7)
```

- **確認方式**：事件檢視器 → 應用程式及服務記錄檔 → Microsoft → Windows → CodeIntegrity → Operational，看事件 3077／3033；登錄值 `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState = 1` 代表 Smart App Control 開啟。
- **官方狀態**：[pyRevit issue 4011](https://github.com/pyrevitlabs/pyRevit/issues/4011) 已於 2026-11-16 以 not planned 結案，沒有官方修法。
- **暫行做法**：斷網後啟動 Revit，等「SCADA檢查」頁籤出現再連回網路（出自 issue 回報，非官方）。
- **實測（2026-11-24，Revit 2025.5＋pyRevit 7.1.0）**：把擴充路徑從 worktree 改成另 clone 的資料夾後，連網啟動被擋（0x800711C7）；改回原路徑可載入；再改成新路徑並離線啟動，載入成功，兩顆按鈕結果與先前一致，之後近 15 分鐘沒有新的封鎖事件。**原因（離線、或 DLL 先前已被放行）未釐清**。
- **注意**：改動擴充內任何腳本會使 pyRevit 重新產生 DLL，可能再被擋，需再離線啟動一次。
- **不建議**關閉 Smart App Control：Windows 無法再重新開啟，除非重置系統。

