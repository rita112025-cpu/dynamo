# 對話框相容性測試（Dynamo 實機，使用者操作）

**狀態：節點、建置與假模組驗證已完成；Revit／Dynamo 實機結果待使用者提供。**
本測試只開兩個標準對話框，**不讀取任何 Revit 元素、不寫入任何檔案、不建立資料夾、不取得文件物件**。

## 1. 產物

| 項目 | 內容 |
|---|---|
| 測試 .dyn（目前版本） | `out/dialog_compat_test_20261109-154005.dyn`，SHA-256 `c2aa3122c95354185fc95922a4076d67d2fc15b40d224538ed4fc5317da2eadb`（不入版控） |
| 已取代的舊產物 | `out/dialog_compat_test_20261109-153750.dyn`（SHA-256 `301ea1a1…4ed54`）。**節點內容已過時，請勿使用**。 |
| 節點原始碼 | `tools/dialog_test/dialog_compat_test.py` |
| 建置腳本 | `tools/dialog_test/make_dialog_test_dyn.py`（重建：`python tools/dialog_test/make_dialog_test_dyn.py`，會產生新時間戳的檔案） |

## 2. 兩種模式與 IN[0]

字串節點 IN[0]：
- **留空**，或填 `no-owner`：對話框不指定擁有者視窗（無擁有者模式）。
- 填 `owner`：以 Revit 主視窗為擁有者（擁有者模式）。

**擁有者只套用在「DIRECT 路徑」**（對話框直接在 Dynamo 目前執行緒顯示）。若第一個對話框觸發「FALLBACK 路徑」（新建 STA 執行緒），該對話框**一律不使用擁有者視窗**（跨執行緒指定 Revit 主視窗可能造成死結或輸入佇列問題，因此不在本測試中嘗試）。

## 3. 每次執行的 OUT 要看什麼

Watch 會列出（節選）：
- `route=DIRECT` 或 `route=FALLBACK`：實際走哪一條路徑。
- `owner applied=yes/no`：是否套用了擁有者。
- `ShowDialog returned=OK/Cancel`：對話框的回傳值（或 `EXCEPTION`）。
- `node reached the last line of the script: yes`：**節點確實執行到最後一行**，證明 Dynamo 能正常結束執行。
- `NO FILES WRITTEN; NO REVIT OBJECTS TOUCHED`：固定最後一行。

## 4. 操作步驟

1. 在 Revit 2025 的 Dynamo 3.3.2 中開啟 `out/dialog_compat_test_20261109-154005.dyn`。
2. 依下表分別執行。**每一列執行一次，並記錄 Watch 全文。**

| 編號 | IN[0] | 操作 |
|---|---|---|
| N1 | 留空 | 檔案對話框選一個 `.rvt`；資料夾對話框選一個資料夾（確定） |
| N2 | 留空 | 第一個對話框按「取消」 |
| N3 | 留空 | 第一個對話框確定，第二個對話框按「取消」 |
| O1 | `owner` | 同 N1 |
| O2 | `owner` | 同 N2 |
| O3 | `owner` | 同 N3 |

3. 檔案對話框選的必須是 `.rvt` 檔（測試不會開啟它）；資料夾對話框選任一資料夾。

## 5. 使用者觀察清單（不能只看對話框有沒有出現）

每一列（N1–O3）都請記錄以下觀察：

| 觀察項 | 說明 | 結果（請填） |
|---|---|---|
| (a) 前景與遮擋 | 對話框是否出現在 Revit 前景？是否被 Revit 主視窗遮住（看不到，或只能在工作列找到）？ | |
| (b) 模態行為 | 對話框開著時，Revit／Dynamo 主視窗是否仍有反應（點擊、捲動、選單）？正常應該是**不能操作主視窗、只能操作對話框**。 | |
| (c) 結束與執行完成 | 按取消或關閉後，Dynamo 狀態列是否回到「執行完成」？Watch 是否出現輸出（含 `node reached the last line`）？ | |
| (d) 模式與選擇 | 本列的模式（無擁有者或 owner）、選對的檔案與資料夾、取消的是哪一個對話框，Watch 是否與實際操作一致？ | |

**請特別注意：**
- 若對話框被遮住，或主視窗完全沒有反應，請標出並附截圖。
- 若 Dynamo 狀態一直停在「執行中」，或 Watch 沒有任何輸出，請記錄等待時間並附 Dynamo 日誌。
- 若出現 Dynamo 紅色錯誤，請附完整訊息。

## 6. 回報內容

請提供：
1. N1–N3、O1–O3 六列各自的 Watch 全文（可複製），以及上面 (a)–(d) 的觀察結果。
2. 所有例外（Watch 中的 `EXCEPTION` 行，或 Dynamo 紅色錯誤）的完整訊息。
3. 若 Watch 出現 `route=FALLBACK`，請附該列完整輸出。
4. Revit 與 Dynamo 版本（Dynamo 3.3.2.11986 是否一致）。
5. Watch 中 `apartment state`、`IsBackground`、`IsThreadPoolThread` 三行，以及 `foreground window` 相關行。

## 7. 已驗證與未驗證

- **已驗證（假模組，Python 3.9.12 隔離程序，38 項檢查全部通過）**：N1–N3、O1–O3 的邏輯；DIRECT 路徑是否套用擁有者；FALLBACK 路徑一律不套用擁有者（即使在擁有者模式下）；`NativeWindow` 建立失敗時的退回；`ShowDialog` 拋 `ThreadStateException` 時的 FALLBACK；節點執行到最後一行；整個過程沒有任何檔案寫入（以替換 `open` 與 `os` 寫入函式驗證）。
- **這些假模組結果只證明節點的邏輯，不證明 Dynamo 或 Revit 的實機行為。**
- **未驗證（待實機）**：標準對話框在 Dynamo 中的實際行為、執行緒的實際 apartment 狀態、擁有者在 Revit 中的實際效果（前景與模態）、`System.Windows.Forms` 的實際組件版本。
- 本測試不在 `tests/` 之下，也沒有自動化的實機測試。
- 本測試不擴大到 Excel GUID、唯讀共用參數、連結模型或類型參數等未測項目。
