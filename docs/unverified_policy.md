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

## 與範圍檔的關係

每個 UNVERIFIED 都會計入範圍檔的 `unverified` 欄。報告讀者應先看範圍檔：
`examined` 很大、`unverified` 也很大，代表規則尚未確認，不代表模型沒問題。
