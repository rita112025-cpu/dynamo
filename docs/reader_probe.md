# Revit 唯讀 API 探針：操作步驟與結果紀錄範本

日期：2026-11-09。狀態：**程式與自動測試已完成；Revit 2025 實機結果待使用者提供。**
本文件**不含結論**。結論待探針報告回來後，才依報告更新 `docs/reader_design.md` 的待決事項與風險清單。

## 0. 這支探針做什麼、不做什麼

- 做：在使用者開著的**測試模型**上，只讀地記錄 Revit API 的實際行為（回傳值或例外），把設計文件中所有 [待確認] 項目變成有證據的答案。
- 不做：不開啟、不儲存、不同步、不關閉任何文件；不開 Transaction；不修改任何元件、參數、工作集或視圖；不開其他文件；不寫入任何 RVT。
- 探針只寫**一份報告 JSON**（檔名帶時間戳、不覆寫）到你指定的輸出資料夾。

## 1. 產物

| 項目 | 內容 |
|---|---|
| 探針 .dyn | `out/reader_probe_20261109-110915.dyn`（不入版控，由 `tools/probe/make_probe_dyn.py` 產生） |
| 探針 .dyn 的 SHA-256 | `2c4938b73db9c06ff5d688a8d1501d1bc3ab47f3965b63211a1690ae578a5de3` |
| 探針原始碼 | `tools/probe/reader_api_probe.py`（Python 節點內容與此檔逐字相同，測試驗證） |
| 完整度檢查 .dyn（不變） | `out/完整度檢查_20261109-104100.dyn`，SHA-256 `b6143d78084f041f6cc34c811fe72cf451215f1ac17f904a1c18aff4bb82e4a5` |

重建探針 .dyn：`python tools/probe/make_probe_dyn.py`（輸出到 `out/`；同一份原始碼重建兩次位元組相同）。

## 2. 測試模型準備（手動，由使用者執行）

**只能使用新建的測試模型。不得使用正式模型，也不得使用正式模型的複本以外的檔案。**

1. Revit 2025 → 新建**空白專案**。
2. 放置少量元件（尺寸與位置不重要）：
   - 2 條電管（Conduit）。
   - 1 條電纜架（Cable Tray）。
   - 1 個電氣設備，**備註 = `SCADA`**。
   - 1 個電氣設備，**備註留空**。
   - 載入一個 SCADA 機櫃族群（RFA，**測試用**，名稱含 `SCADA_機櫃`），放置 **1 個**。
3. 若要測試共用參數 GUID 查找：在測試專案中載入 SCADA 共用參數檔（**唯讀使用**，不修改該檔）。
4. **另存為**測試資料夾內的新檔（例如 `TEST-probe-model.rvt`）。未另存的專案會被探針拒絕。
5. 保持該檔開著。**探針不存檔；執行後也不要存檔。** 關閉時選擇「不存檔」。

## 3. 執行探針（Dynamo 3.3.2）

1. 在 Revit 2025 的 Dynamo 中開啟 `out/reader_probe_20261109-110915.dyn`（無載入錯誤即可）。
2. 填寫兩個字串節點：
   - `IN[0]`：步驟 2.4 另存的**測試模型完整路徑**（必須與目前開啟文件的路徑完全相同，否則探針拒絕執行）。
   - `IN[1]`：一個**已存在**的輸出資料夾完整路徑（探針不會自動建立資料夾）。
3. 執行。
4. 預期結果：
   - Watch 顯示摘要：模型路徑、Revit 版本、`IsModified before/after`、步驟數、成功數、失敗數、各品類數量、報告檔路徑。
   - 在 `IN[1]` 產生一個 `reader_probe_<時間戳>.json`。
5. 若 Watch 顯示 `REFUSED`：探針拒絕執行（未另存，或 IN[0] 與開啟的文件不同）。請修正後再執行，**這不是錯誤，是保護機制**。
6. 若 Watch 顯示 `NOT RUN`：IN[0] 或 IN[1] 留空。
7. **執行後，`IsModified after` 應與 before 相同。** 若不同，請告知。

## 4. 回傳給審核方的內容

請提供：

1. 報告 JSON 的完整檔案（`reader_probe_<時間戳>.json`）。
2. Watch 的摘要截圖。
3. Revit 與 Dynamo 的版本（Revit 2025.5？Dynamo 3.3.2.11986？）。
4. 任何非預期的 Dynamo 對話框或日誌錯誤（既有的 `AlsoKnownAs InvalidOperationException` 啟動雜訊可忽略，請註明）。

## 5. 報告結構（給審核方閱讀用）

| 區段 | 內容 | 對應的待確認項目 |
|---|---|---|
| `environment` | PathName、Title、IsWorkshared、Revit 版本、IsModified 前後 | E1 |
| `category_counts` | 每個品類：全部／實例（WhereElementIsNotElementType）／類型數量 | E2（驗證 D1） |
| `records` 中 `section=sample` | 每品類最多 5 個實例：Id.Value、Id.IntegerValue、是否相等、類別名稱、GetTypeId、類型 FamilyName／Name、`Symbol.Family.Name` 是否存在 | E3 |
| `records` 中 `section=type` | 每品類最多 3 個類型元素：類別、FamilyName、Name | E3 |
| `records` 中 `section=param` | 服務類型／備註：BuiltInParameter 與名稱備援（實例與類型）：找到與否、Definition.Name、StorageType、IsReadOnly、HasValue、AsString；CURVE_ELEM_LENGTH 的 IsReadOnly（預期唯讀，[憑記憶]） | E4 |
| `records` 中 `section=shared` | 機櫃樣本的 16 個 SCADA_* 共用參數：GUID 查找 vs 名稱查找、是否指向同一參數、StorageType、IsReadOnly、值 | E5 |
| `records` 中 `section=workset` | 協作模型：工作集清單與是否開啟；非協作：N/A | E6 |
| `records` 中 `section=links` | RevitLinkInstance 數量與名稱 | E7 |
| `summary` | 步驟數、成功數、失敗數 | — |

每筆紀錄的格式：`{"section", "name", "ok", "value"}`；失敗的紀錄為 `{"section", "name", "ok": false, "exception": "型別名: 訊息"}`。

## 6. 結果紀錄範本（審核方與使用者共同填寫；尚未填寫）

| 編號 | 問題（對應 `docs/reader_design.md` 的待確認） | 探針結果（填入報告的值與例外） | 結論 |
|---|---|---|---|
| E1 | Revit 版本號與組建；PathName；Title；IsWorkshared；IsModified 前後 | | 待填 |
| E2 | 7 品類：含與不含 `WhereElementIsNotElementType` 的數量（驗證 D1） | | 待填 |
| E3a | `Id.Value` 與 `Id.IntegerValue` 是否都可用，數值是否相同 | | 待填 |
| E3b | 系統族群（導管、電纜架）的 `t.FamilyName` 值 | | 待填 |
| E3c | 可載入族群（機櫃）的 `t.FamilyName` 值 | | 待填 |
| E3d | `Symbol.Family.Name` 是否可用 | | 待填 |
| E4a | 服務類型與備註：BuiltInParameter 與名稱備援各自是否找到；StorageType、HasValue、AsString | | 待填 |
| E4b | 同名參數在類型上是否存在（D6） | | 待填 |
| E4c | IsReadOnly 能否回 True（以 CURVE_ELEM_LENGTH 為候選；[憑記憶]） | | 待填 |
| E5 | 16 個共用參數：GUID 查找與名稱查找是否一致；StorageType；IsReadOnly；值 | | 待填 |
| E6 | 工作集清單與開啟狀態（協作模型）；非協作記 N/A | | 待填 |
| E7 | 連結模型數量（取不到則記錄例外） | | 待填 |
| E8 | 執行前後 IsModified 是否不變 | | 待填 |

## 7. 自動驗收（已完成）

- 雙環境測試：pytest 3.12 與 Dynamo 內建 Python 3.9.12 的 unittest 皆通過（`tests/test_reader_probe.py`）。
- 讀取護欄（`tools/reader_rules.py`）的正反案例測試通過；探針原始碼通過護欄。
- 探針 .dyn 建置決定性（兩次位元組相同）通過。
- 完整度檢查 .dyn 的 SHA-256 仍為 `b6143d78…e4a5`。
- 既有 10 個 `.dyn`／`.py` 與 2 個文件的 SHA-256 與基準逐檔比對（見 `docs/dyn_build.md`）。
- 假 Revit 模組在 Dynamo 內建 Python 3.9.12 中執行：拒絕未存檔、拒絕不同文件、拒絕空輸入、單一 API 失敗不中止、報告不覆寫、未觸及任何寫入類方法。

## 8. 未驗證（請保留）

- 所有 Revit API 的實際行為：必須由第 3 節的手動執行確認。
- 探針在真實 Revit 中的完整執行（僅假模組驗證）。
- 探針報告的內容是否完整（以審核方閱讀為準）。
- 探針不做的事：不驗證 reader 本身、不驗證快照契約與真實資料、不驗證 Excel 開啟 CSV。
