# Dynamo 工具箱啟動器

桌面捷徑有兩種開法。兩種都先確認 Revit 2025 已經關閉。啟動器寫一份系統 ANSI、沒有 BOM 的 journal，然後啟動 Revit、開啟宿主 `.rvt`，並以手動模式載入 `.dyn`。圖形不會自動執行，執行按鈕在 Dynamo 裡，由你按下。

Revit 2025 如果已經在跑，視窗會請你先關閉它，然後停止。不會接到已經開啟的 Revit。

## 安裝

在存放這個資料夾的電腦上，用 Windows PowerShell 5.1，於儲存庫根目錄執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\Install-DynamoToolbox.ps1
```

桌面會出現 **Dynamo Toolbox**。資料夾若搬移，再執行一次安裝腳本。捷徑只寫在目前使用者的桌面，不會改任何 `.dyn` 或專案檔。

## 單次開啟

1. 關閉 Revit 2025。
2. 開啟桌面上的 Dynamo Toolbox。選單後面會有一個 PowerShell 視窗，關掉選單後它會結束。
3. 留在「單次開啟」。選一個工具。名稱來自 `launcher/tools.json`：
   - `copy-view-templates`：批次複製視圖樣板
   - `fill-scada-params`：批次填寫 SCADA 參數
   - `assign-worksets`：批次分配工作集
   - `param-tools`：Revit 參數工具
   - `excel-sync`：Excel／Revit 同步
   - `batch-scada-setup`：批次 SCADA 設定
4. Browse 選一個已經存在的 `.rvt`。不要選 `.rte` 樣板。
5. Launch。

Revit 會開啟該專案，Dynamo 載入圖形後停在手動模式。你選的 `.rvt` 是宿主。批次要處理的檔案，是圖形裡 Directory Path 指到的資料夾。

## 批次佇列

第二個分頁「批次佇列」讓一個工作階段依序排好幾個工具。每個工具的輸入存在一份 JSON 任務設定。順序就是檔案裡 `jobs` 的順序。

1. 勾選工具，按「加入勾選」。勾選的工具會依 `tools.json` 的順序加到佇列尾端。同一個工具可以再加一次，例如先試跑、之後再排一筆寫入。
2. 選佇列裡的一筆，右邊照 Dynamo 的輸入填值。必填的目標資料夾若還是空的，按「套用」可把上方的資料夾填進還沒填的工作。
3. 「儲存設定」寫出任務設定。「載入設定」讀回。範例是 `launcher/examples/task-config.example.json`。
4. 宿主 `.rvt` 跟單次開啟一樣，必須是已經存在的檔案。
5. 寫入開關預設是 False。要允許某一筆改成 True，先勾「我確認這次佇列可以寫入模型」，視窗會再問一次。沒有這次確認，`run: true` 不能用。
6. 「開啟下一步」只開佇列裡第一個還沒做的工作。開啟前會列出要在 Dynamo 手動填的值。若這一筆是寫入，還會再問一次。
7. Revit 開起來之後，圖形停在手動模式。對照畫面上的值自己按執行。做完後關閉 Revit，不要把宿主存進錯誤的檔案。
8. 回到啟動器，按「記錄結果」，填狀態、計數與錯誤。記錄完才能開下一步。
9. 「開啟報告」打開這次工作階段的 HTML 報告。

一個工作開啟一次 Revit。佇列是同一份工作階段裡的順序，不是在同一個 Revit 行程裡自動連跑。

紀錄寫在 `%LOCALAPPDATA%\DynamoToolbox\sessions\<工作階段代號>\`：

| 檔案 | 內容 |
| --- | --- |
| `run-log.json` | 每個工作一筆的最新狀態 |
| `run-log.csv` | 同一份內容，UTF-8 有 BOM，給 Excel 開 |
| `report.md` | Markdown 摘要 |
| `report.html` | 同一份摘要的網頁 |
| `job-01-card.txt` | 這一筆要在 Dynamo 手動填的值 |

每一筆都有工具、輸入檔、開始與結束時間、狀態、計數、錯誤。`manualMode` 是 `true`，`graphExecutedByLauncher` 是 `false`。計數與錯誤是你記錄的，啟動器不會去讀 Dynamo 的 Watch。

狀態：

| 狀態 | 意思 |
| --- | --- |
| `planned` | 已排程，還沒開 Revit |
| `opened-manual` | 圖形已用手動模式開啟，還沒記錄結果 |
| `dry-run` | 已記錄為試跑 |
| `written` | 已記錄為寫入。只有確認過、而且這一筆的寫入開關是 True 才接受 |
| `failed` | 已記錄為失敗 |
| `skipped` | 已記錄為略過 |

## 任務設定

```json
{
  "version": 1,
  "sessionName": "sample-batch",
  "hostProject": "C:/Models/sample-host.rvt",
  "confirmWrite": false,
  "jobs": [
    {
      "toolId": "fill-scada-params",
      "inputs": {
        "directory": "C:/Models/sample-batch",
        "value": "SAMPLE",
        "run": false
      }
    }
  ]
}
```

- `version` 必須是 `1`。
- `hostProject` 必須以 `.rvt` 結尾。佇列不開啟 `.rte`。
- `confirmWrite` 省略時當作 `false`。
- `jobs` 至少一筆。重複的 `toolId` 會照檔案順序保留，不會改回工具清單的順序。
- `inputs` 的名稱要對上該工具在 `tools.json` 的輸入。省略的欄位用工具宣告的預設值。支援試跑的工具若省略 `run`，結果是 `false`。
- `run: true` 必須同時有 `confirmWrite: true`。
- 布林值要寫 `true` / `false`，不要寫 `"false"` 或 `0`。

結構檔是 `launcher/schemas/task-config.schema.json`。執行紀錄的欄位在 `launcher/schemas/run-log.schema.json`。

## 如何加入新工具

1. 準備一支 `.dyn`。Dynamo 的 RunType 維持 Manual。不要做成會自己按執行的圖。
2. 在 `launcher/tools.json` 的 `tools` 加一筆。既有的六筆只需要 `id`、`name`、`dyn` 也能開單次選單；要進佇列並使用試跑規則，加上 `supportsDryRun`、`dryRunInput`、`inputs`。
3. `dyn` 是相對於儲存庫根目錄的路徑，使用 `/`，結尾是 `.dyn`，不要寫磁碟機代號，也不要寫 `..`。
4. 每個輸入有 `name`、`type`、`label`。`type` 是 `string`、`boolean`、`integer`、`number`、`directory`、`file`、`string-list` 其中一個。選填欄位必須有 `default`。
5. 圖形有 Run=False 這種試跑開關時，`supportsDryRun` 設為 `true`，`dryRunInput` 指向那個布林輸入。該輸入的 `default` 必須是 `false`，`writesModel` 必須是 `true`。
6. 沒有寫入開關的唯讀工具把 `supportsDryRun` 設為 `false`，並且不要宣告 `dryRunInput`。
7. 再執行一次 `Install-DynamoToolbox.ps1`。捷徑名稱仍是 Dynamo Toolbox。

契約與兩個還沒實作的例子（模型檢查、DWG 匯入 Revit）在 `launcher/docs/工具契約.md`。那兩個例子不要寫進 `tools.json`，因為儲存庫裡還沒有對應的 `.dyn`。

## 編碼

Journal 以 Windows PowerShell 5.1 的 `[System.Text.Encoding]::Default` 寫出（繁體中文 Windows 為 cp950），沒有 BOM。寫入前會把全文做一次 ANSI 往返；任何無法表示的字元會使腳本停止，不會改成 `?`。英文 ANSI 碼頁（例如 cp1252）無法寫入中文路徑。

任務設定、執行紀錄與報告是 UTF-8。CSV 另加 BOM，方便 Excel 開啟中文。這些檔案不是 journal，不走 cp950。

## 測試

不需要 Revit。在儲存庫根目錄：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\tests\Invoke-QueueTests.ps1
```

有 Pester 5 時也可以：

```powershell
Invoke-Pester .\launcher\tests\DynamoQueue.Tests.ps1
```

這兩支測的是任務設定解析、佇列順序，以及 JSON / CSV / Markdown / HTML 報告。它們也檢查 journal 腳本仍是手動模式、無 BOM、並保留 cp950 往返檢查。

## 尚未在 Revit 2025 實機驗證

下列項目要在 Windows、Revit 2025、Dynamo 3.3.2 上再確認：

- 批次佇列分頁的勾選、載入與儲存設定、寫入確認對話框、記錄結果對話框。
- 「開啟下一步」確實呼叫既有的 `New-DynamoJournal.ps1`，Revit 已開啟時會停下來，journal 沒有 BOM，中文路徑在 cp950 上可以寫入。
- 圖形載入後仍停在手動模式，而且沒有被按執行。
- 操作者依照工作卡把輸入填進 Dynamo 之後，試跑與寫入的結果與記錄下來的計數一致。
- 桌面捷徑在安裝後仍打開同一個選單，六個既有工具的單次開啟跟以前一樣。

自動測試沒有啟動 Revit，也沒有建立桌面捷徑。
