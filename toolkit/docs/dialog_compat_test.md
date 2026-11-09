# 對話框相容性測試（Dynamo 實機，使用者操作）

**狀態：節點與建置已完成；假模組驗證已完成；Revit／Dynamo 實機結果待使用者提供。**
本測試只開兩個標準對話框，**不讀取任何 Revit 元素、不寫入任何檔案、不建立資料夾、不取得文件物件**。

## 1. 產物

| 項目 | 內容 |
|---|---|
| 測試 .dyn | `out/dialog_compat_test_<時間戳>.dyn`（不入版控） |
| 目前建置的產物 | `out/dialog_compat_test_20261109-153750.dyn`，SHA-256 `301ea1a1dbc5b0272e00ef5845a13f72e8f8cec82dc11d93bcb275e24d44ed54` |
| 節點原始碼 | `tools/dialog_test/dialog_compat_test.py` |
| 建置腳本 | `tools/dialog_test/make_dialog_test_dyn.py`（重建：`python tools/dialog_test/make_dialog_test_dyn.py`） |

## 2. 操作步驟

1. 在 Revit 2025 的 Dynamo 3.3.2 中開啟 `out/dialog_compat_test_<時間戳>.dyn`。
2. 字串節點「IN[0]」有兩種用法：
   - **留空**，或填 `no-owner`：對話框不指定擁有者視窗。
   - 填 `owner`：以 Revit 主視窗為擁有者。
3. 執行。依序會出現兩個對話框，**請分別測試下列情境**（每次執行只測一個情境，並記錄結果）：

| 情境 | 操作 | 預期 |
|---|---|---|
| A | IN[0] 留空；兩個對話框都按「確定」，檔案選任一 `.rvt`，資料夾選任一資料夾 | Watch 顯示兩個 `selected` 行與 `NO FILES WRITTEN; NO REVIT OBJECTS TOUCHED` |
| B | IN[0] 為 `owner`；同 A | 同 A，另外顯示 `owner window: NativeWindow assigned` |
| C | 第一個對話框按「取消」 | `CANCELLED: file dialog`；不出現第二個對話框 |
| D | 第二個對話框按「取消」 | `CANCELLED: folder dialog` |
| E | 第一個對話框選非 `.rvt` 的檔案（例如 `.txt`，需用「所有檔案」篩選或另建 `.txt` 測試檔） | `INVALID FILE: extension '.txt' is not .rvt` |

**不得**在測試中選擇正式模型以外的任何東西；測試本身不會開啟所選的檔案。

## 3. 回報內容

請提供：

1. 每個情境（A–E）的 Watch 完整文字（可複製）。
2. 若出現例外（Dynamo 紅色錯誤或 Watch 中的 `EXCEPTION` 行），請附完整訊息。
3. Revit 與 Dynamo 的版本（Dynamo 3.3.2.11986 是否一致）。
4. Watch 中的 `apartment state`、`IsBackground`、`IsThreadPoolThread` 三行，以及 `foreground window` 相關行。

## 4. 已驗證與未驗證

- **已驗證（假模組，Python 3.9.12 隔離程序）**：情境 A–E 的邏輯、擁有者模式的建立與釋放、`NativeWindow` 失敗時的退回、`ShowDialog` 拋 `ThreadStateException` 時的 STA 執行緒後備路徑，以及整個過程沒有任何檔案寫入（以替換 `open` 與 `os` 寫入函式驗證）。
- **這些假模組結果只證明節點的邏輯，不證明 Dynamo 或 Revit 的實機行為。**
- **未驗證（待實機）**：標準對話框在 Dynamo 中的實際行為、執行緒的實際 apartment 狀態、前景視窗與擁有者的實際效果、`System.Windows.Forms` 的實際組件版本。
- 本測試不在 `tests/` 之下，也沒有自動化的實機測試。
