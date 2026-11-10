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
