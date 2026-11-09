# UNVERIFIED 何時可以出現

UNVERIFIED 的意思是「這個檢查對這個元件（或模型）無法下結論」。它**不是** PASS，也不是輕微的 FAIL。
規則：寧可標 UNVERIFIED，也不可在沒有依據時標 PASS。FAIL 與 UNVERIFIED 都必須有 `reason`。

## 合法情境

| 情境 | 例子 | 狀態 |
|---|---|---|
| 規範值或門檻未經確認 | 高程範圍規則尚未獲業主確認，只能列出實際高程 | 對每個受影響元件標 UNVERIFIED |
| 需要的資料讀不到 | 參數存在但值無法讀取、Connector 清單取得時發生例外 | 該元件標 UNVERIFIED，reason 寫例外原因 |
| 需要的外部資料不在手邊 | 檢查淨距需要另一專業的連結模型，但連結未載入 | 以模型為單位（`element_id` 空白）標 UNVERIFIED |
| 元件在未開啟的工作集中 | 只在**檢查目前已開啟的文件**時才可能出現（見下） | 以模型為單位標 UNVERIFIED，並在範圍檔註明未涵蓋 |

## 不應標 UNVERIFIED 的情況

- 規則明確、資料齊全、結果不符 → FAIL。
- 元件類別在模型中根本不存在 → 不產生結果，在範圍檔記錄 `examined = 0` 並寫 `note`。
- 例外被吞掉而沒有記錄。程式碼不可為了讓流程跑完而把例外當成「沒有資料」。

## 工作集未開啟

唯讀批次開檔的提案是 `OpenAllWorksets`。依此設定，批次模式下所有工作集都會開啟，
因此「工作集未開啟 → UNVERIFIED」**不會在批次模式出現**。
它只可能出現在檢查使用者目前已開啟、且部分工作集關閉的文件時。

注意：這是依既有腳本（`BatchFillScadaParams`、`BatchParamTools`、`BatchWorksets` 使用 OpenAllWorksets）
與提案設計推得的結論，**尚未在 Revit 實機驗證**。`BatchCopyViewTemplates` 使用 CloseAllWorksets，
若日後唯讀檢查沿用該設定，就會出現這種情況。

## 每個元件一筆結果（計數口徑）

- **元件層級的檢查**：每個被檢查的元件，對該檢查**恰好送出一筆** Finding（PASS、FAIL 或 UNVERIFIED）。
  不可只送有問題的，也不可對同一元件、同一檢查送兩筆。同一元件有多個原因時，合併成一筆（`reason` 寫全部原因）；
  若是兩條獨立規則，就拆成兩個檢查項目。
- **模型層級的檢查**（`element_id` 空白，例如「工作集載入」）：`examined = 1`，恰好一筆 Finding。
- **沒有可檢查的元件**：不送 Finding，`examined = 0`，並在 `note` 寫原因。
- 「沒有結果」絕不等於通過。範圍檔輸出器會驗證 `pass + fail + unverified = examined`，
  不符就拒絕寫入、不留檔。因此「規則未確認」時，所有受影響元件都要各自標 UNVERIFIED，
  不能只標其中一筆。

### 「設備編號重複」的口徑

兩個元件共用同一編號時，**每個涉及的元件各一筆 FAIL**，`reason` 寫對方元件的 ElementId
（三個以上時列出其餘全部）。沒有重複的元件各一筆 PASS。範例見 `examples/sample_findings.csv`。

## 與範圍檔的關係

每個結果都計入範圍檔的 `pass`、`fail`、`unverified` 欄，三欄加總永遠等於 `examined`。報告讀者應先看範圍檔：
`examined` 很大、`unverified` 也很大，代表規則尚未確認，不代表模型沒問題。

## 完整性保證的範圍

`write_findings_csv` **不強制**完整性：它只忠實寫出收到的 Finding。
「每個被檢查元件恰好一筆」只有在走 `write_scope_csv`（並提供對應的 `CheckScope`）時才會被驗證與保證。
只輸出結果檔而不輸出範圍檔的報告，無法分辨「沒有問題」與「沒有檢查」。

## 報告大小

依此設計，大模型的每個元件、每個檢查都有一列（包含 PASS），結果檔會很大
（例如 5 萬個元件 × 5 個檢查 ≈ 25 萬列）。目前採用此設計，因為它是「沒有結果就不是通過」的前提；
是否接受、或改為只輸出 FAIL／UNVERIFIED 並以範圍檔的計數佐證，由使用者決定（尚未決定）。
