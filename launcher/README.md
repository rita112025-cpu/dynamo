# Dynamo 工具箱啟動器

從桌面捷徑選一個工具，再開一個已經存在的 `.rvt`。Revit 2025 必須是關閉的。啟動器會寫一份系統 ANSI、沒有 BOM 的 journal，然後啟動 Revit、開啟該專案，並以手動模式載入對應的 `.dyn`。圖形不會自動執行。

Revit 2025 如果已經在跑，視窗會請你先關閉它，然後停止。不會接到已經開啟的 Revit。

## 安裝

在存放這個資料夾的電腦上，用 Windows PowerShell 5.1，於儲存庫根目錄執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\Install-DynamoToolbox.ps1
```

桌面會出現 **Dynamo Toolbox**。資料夾若搬移，再執行一次安裝腳本。捷徑只寫在目前使用者的桌面，不會改任何 `.dyn` 或專案檔。

## 執行

1. 關閉 Revit 2025。
2. 開啟桌面上的 Dynamo Toolbox。選單後面會有一個 PowerShell 視窗，關掉選單後它會結束。
3. 選一個工具。選單名稱來自 `launcher/tools.json`：
   - `copy-view-templates`：批次複製視圖樣板
   - `fill-scada-params`：批次填寫 SCADA 參數
   - `assign-worksets`：批次分配工作集
   - `param-tools`：Revit 參數工具
   - `excel-sync`：Excel／Revit 同步
   - `batch-scada-setup`：批次 SCADA 設定（`BatchScadaSetup.dyn`）
4. Browse 選一個已經存在的 `.rvt`。不要選 `.rte` 樣板。
5. Launch。

Revit 會開啟該專案，Dynamo 載入圖形後停在手動模式。

## 編碼

Journal 以 Windows PowerShell 5.1 的 `[System.Text.Encoding]::Default` 寫出（繁體中文 Windows 為 cp950），沒有 BOM。寫入前會把全文做一次 ANSI 往返；任何無法表示的字元會使腳本停止，不會改成 `?`。英文 ANSI 碼頁（例如 cp1252）無法寫入中文路徑。

## DPI 與版面

`powershell.exe` 沒有 DPI manifest。縮放大於 100% 時，若未宣告 DPI awareness，Windows 會把整個視窗做點陣放大，中文與控制項會糊。啟動器在建立任何 WinForms 視窗之前，依序嘗試：

1. `SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)`（`-4`）
2. 失敗則 `SetProcessDpiAwareness(2)`（Per-Monitor）
3. 再失敗則 `SetProcessDPIAware()`
4. 最後再試 `SetThreadDpiAwarenessContext(-4)`，因為主控台 HWND 可能已經把處理序預設鎖住

這些呼叫失敗（已經設定過、`ACCESS_DENIED`、舊版 Windows 沒有該 API）不會中止啟動器。接著呼叫 `Application.EnableVisualStyles()`，並在可以的時候呼叫 `SetCompatibleTextRenderingDefault($false)`。

版面是 `TableLayoutPanel` 加 `AutoSize`，字型用點數：內文 10pt、標題 11pt 粗體、說明文字 9pt 灰色。字型順序仍是 Microsoft JhengHei UI、Microsoft JhengHei、PMingLiU、Segoe UI。`AutoScaleMode` 為 `Dpi`。其餘像素間距依表單的 `DeviceDpi` 計算，所以 100%、125%、150%、200% 不會再被點陣拉伸。100% 時客戶區約 640×560（標題列會再高一點；內容需要時可再略增）。

把視窗拖到另一台縮放不同的螢幕時，腳本會處理 `DpiChanged` 與 `WM_DPICHANGED` 並依新的 `DeviceDpi` 重排。Windows PowerShell 5.1 用的是 .NET Framework WinForms，而且不能替 `powershell.exe` 加上 `DpiAwareness=PerMonitorV2` 的應用程式設定檔，所以跨螢幕重縮放是盡力而為，不保證與新版 .NET WinForms 相同。

### 版面測試

在 Windows PowerShell 5.1、STA 下執行。設定 > 系統 > 顯示器 > 縮放與版面配置，分別改成 100%、125%、150%、200%。若 Windows 要求登出，先登出再登入，然後執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File G:\Dynamo\launcher\tests\Test-DynamoToolboxLayout.ps1
```

測試不會呼叫 `New-DynamoJournal.ps1`，也不會啟動 Revit。通過時結束代碼為 0，並把畫面存成 `%TEMP%\DynamoToolboxLayout_<dpi>.png`。

### 手動確認

1. Browse 選到一個檔案，路徑出現在文字框。
2. Close 關掉視窗。
3. 用一個本機測試用的 `.rvt` 按 Launch（Revit 2025 必須先關閉）。不要選 `.rte`。這會走原本的 Revit 啟動流程。
