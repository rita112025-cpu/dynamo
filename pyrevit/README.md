# pyRevit 功能區單鍵檢查

把高頻檢查做成 Revit 功能區按鈕（參考 [pyRevit](https://github.com/pyrevitlabs/pyRevit) 的擴充格式）。兩顆按鈕都是**唯讀**，結果顯示在 pyRevit 輸出視窗，可點連結選取元件。

| 按鈕 | 做什麼 |
|---|---|
| 讀取 SCADA 參數 | 找出族群名稱含 `SCADA_機櫃` 的電氣設備，列出 16 個 `SCADA_*` 共用參數中「缺少」與「空白」者（以 GUID 查找，失敗再用名稱） |
| 盤點視圖電纜架 | 盤點目前作用中視圖的電纜架與配件，依類型＋尺寸統計數量與長度 |

## 安裝

1. 安裝 pyRevit（需 5.x 才支援 Revit 2025）。
2. pyRevit 設定 → Custom Extension Directories，加入本資料夾 `pyrevit`（是 `.extension` 的上一層，不是 `.extension` 本身）。
3. Save Settings and Reload。功能區出現「SCADA檢查」頁籤。

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
- **以下未在 Revit 2025 實測**：按鈕載入、`RBS_CABLETRAY_WIDTH_PARAM`／`HEIGHT_PARAM` 在配件上多半無值（顯示 `-`）、`ALL_MODEL_TYPE_NAME` 取類型名、`output.linkify` 單一 ElementId。pyRevit 文件中 `.tab/.panel` 命名、icon.png 規格、`extension.json` 欄位也未逐頁查證，圖示尚未提供（按鈕先以文字顯示）。
