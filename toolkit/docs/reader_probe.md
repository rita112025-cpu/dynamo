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

**只能使用新建並另存的測試模型。不得使用正式模型或其複本。**

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

## 6. 結果紀錄（第一次探針，2026-11-09，使用者實機執行）

報告：`C:\Users\user\Downloads\ProbeOut\reader_probe_20261109-141531.json`，SHA-256 `50d46ac22f56b13bd8e19b68306dae519e5c3be1c11c6d98f33b33a6856fa0db`。
測試模型：`C:\Users\user\Downloads\ReaderProbe_Test.rvt`（Revit 2025，非協作，1 個連結 `建築結構_1.rvt`）。
結果：731 步，703 成功，28 失敗（全部為 `ElementType.Name` 的 `TypeError: property cannot be read`，見 E3e）。

| 編號 | 問題 | 探針結果（報告 records） | 結論 |
|---|---|---|---|
| E1 | 版本、PathName、Title、IsWorkshared、IsModified 前後 | Revit `2025`（VersionName `Autodesk Revit 2025`）；PathName 為 `ReaderProbe_Test.rvt` 的完整路徑；Title `ReaderProbe_Test`；IsWorkshared False；IsModified 前 True、後 True | 已答。文件在執行前已修改（存檔後又有未存的變更），無法用 IsModified 證明未修改（見 9.3） |
| E2 | 7 品類含與不含 WhereElementIsNotElementType | Conduit 全部 9／實例 1／類型 8；ConduitFitting 15／0／15；CableTray 9／2／7；CableTrayFitting 25／1／24；ElectricalEquipment 26／6／20；ElectricalFixtures 2／0／2；Wire 2／0／2 | 已證實：不加過濾會混入大量類型元素（D1 必要） |
| E3a | Id.Value 與 Id.IntegerValue | 9 個樣本全部可用且相同（9/9） | 已證實 |
| E3b | 系統族群的 FamilyName | 導管「不含配件的電管」、電纜架「含配件的電纜架」，皆有值，不為 null | 已證實 |
| E3c | 可載入族群的 FamilyName | 機櫃樣本的類型為 `SCADA_機櫃_XLSX-003-01_機廠TSS` | 已證實 |
| E3d | Symbol.Family.Name | `Symbol` 只存在於 FamilyInstance（配件、設備 hasattr True；導管、電纜架 False） | 已證實 |
| E3e | ElementType.Name | 28 個失敗全部為 `TypeError: property cannot be read` | 已證實：不可讀，reader 不得依賴 `.Name` |
| E4a | 服務類型與備註：BuiltInParameter 與名稱備援 | 服務類型：BuiltInParameter `RBS_CTC_SERVICE_TYPE` 找到，但 Definition.Name 為「服務類型:」（含冒號）；名稱「服務類型」「Service Type」皆找不到。備註：BuiltInParameter 找到；名稱「備註」找到；「Comments」找不到 | 已證實：內建參數必須以 BuiltInParameter 為主；現行名稱備援在本機無效 |
| E4b | 同名參數在類型上是否存在 | 樣本的類型上 LookupParameter 皆 False | 樣本不足，未定論 |
| E4c | IsReadOnly 能否回 True | CURVE_ELEM_LENGTH（長度）IsReadOnly True（導管、電纜架）；服務類型與備註 False | 已證實：唯讀可判定（以長度參數為例；候選參數原為 [憑記憶]） |
| E4d | StorageType 比對方式 | 字串化結果為 `'3'`（String）與 `'2'`（Double，長度） | 已證實：reader 應與列舉比較，不比對文字名稱 |
| E4e | HasValue、AsString（服務類型／備註） | 所有 BuiltInParameter 樣本 HasValue False、AsString None | 已證實：測試模型的服務類型與備註皆空。非空值尚未測（見 9.2） |
| E5 | 16 個共用參數：GUID 查找與名稱查找 | 2 個機櫃樣本皆為 Excel 版（`SCADA_機櫃_XLSX-003-01_機廠TSS`）。GUID 查找 0/32 找到；名稱查找每台 8 個找到，且讀到非空值（編號 `XLSX-003-01`、機櫃類型、寬 `600`、深 `800`、高 `2100`、尺寸、來源文件、定位來源） | 已證實：SoW V6 的 GUID 在此模型不符（見 9.1）。同名的 8 個參數，GUID 全部與字典不同 |
| E6 | 工作集 | 非協作模型（IsWorkshared False），記 N/A | 未測 |
| E7 | 連結模型 | 1 個 RevitLinkInstance，名稱 `建築結構_1.rvt`，位置未共用 | 數量已證實；連結內元件未測 |
| E8 | 執行前後 IsModified | 前 True、後 True | 無法證明未修改（見 9.3） |

### 9.1 共用參數衝突（最重要）

Excel 版共用參數檔 `D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\Excel_機櫃族群\族群\SCADA_Excel_SharedParameters.txt`（只讀比對）：16 個參數，群組 `SCADA_Excel_Racks`。

- 與字典同名的 8 個參數（編號、機櫃類型、寬、深、高、尺寸、來源文件、定位來源）：**GUID 全部不同**。
- 只存在於 Excel 版的 8 個參數：`SCADA_項次`、`SCADA_安裝位置`、`SCADA_機櫃規格`、`SCADA_配置數量`、`SCADA_台序`、`SCADA_BIM設計與應用說明`、`SCADA_來源工作表`、`SCADA_來源列`。
- 字典中不存在於 Excel 版的 8 個參數：期別、站點、建物、房間、附錄D項次、UPS電源110V、附錄F項次、備註。

結論：專案同時有兩套 SCADA 機櫃族群（SoW V6 與 Excel 版），同名參數的 GUID 不同。字典目前只涵蓋 SoW V6。

### 9.2 尚未實證（需第二次探針）

- **非空字串讀取**：機櫃共用參數已讀到非空字串（HasValue True，AsString 有值，見 E5）。但服務類型與備註的 BuiltInParameter 樣本全部為空（HasValue False），尚未測試非空值。審核方原文「全部 9 個樣本 HasValue=False」僅指服務類型與備註樣本，不包含機櫃共用參數。
- **唯讀共用參數**：只有長度參數測過唯讀（True）；共用參數中的唯讀者尚未測。
- **工作集**：非協作模型，未測。
- **連結模型內元件**：未測。
- **類型參數**：本次樣本的類型上找不到同名參數，樣本不足。

### 9.3 IsModified 基準

執行前 IsModified 即為 True（模型存檔於 14:06，探針執行於 14:15，之間有未存的變更）。因此本次**無法**用 IsModified 證明探針未修改文件。第二次探針須先存檔，再執行。

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

## 10. 第二次探針（不需修改程式）

測試模型要求：

1. 先把測試模型**存檔**，再執行探針（預期 IsModified 前後皆 False）。
2. 放入 SoW V6 版機櫃族群 RFA（`D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\族群\`）與 Excel 版機櫃族群 RFA（`...\SCADA_機櫃_Dynamo\Excel_機櫃族群\`）各一，各放置 1 個。
3. 至少一個電氣設備，備註 = `SCADA`。
4. 至少一條電管，服務類型 = `SCADA`。
5. 其餘同第 2 節（只使用新建並另存的測試模型）。

目的：補測非空值（內建的服務類型與備註）、SoW V6 機櫃的 GUID 查找、唯讀共用參數，以及 IsModified 前後不變。
