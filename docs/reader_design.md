# Revit Snapshot Reader：設計文件（修訂版，只設計，不寫程式）

日期：2026-11-09。版本：r2（依審核方意見 D1–D9 修訂）。狀態：**草案，待審核與使用者決定**。
本文件不含任何 Revit API 程式，也不連接 Revit。

## 0. 標示規則與依據

每個 Revit API 斷言都標示來源，四種之一：

- **[repo]**：既有腳本已在實際使用，已在 `G:\Dynamo` 中以 grep 確認存在。
- **[憑記憶]**：來自記憶，**未查證 Autodesk 文件，也未在 Revit 2025.5 實測**。
- **[待確認]**：無法確定，需在 Revit 2025.5 中以唯讀探針確認（見 R1.5）。
- **[參考]**：其他專案已在用（例如 mep_tray 的 `FittingProbeCommand`，唯讀探查的先例），僅作為做法參考。

[repo] 項目（已確認）：`doc.PathName`、`GetWorksharingCentralModelPath`、`DetachFromCentralOption.DetachAndPreserveWorksets`、
`CreateNewLocal`、`LookupParameter`、`get_Parameter(BuiltInParameter)`、`Parameter.IsReadOnly`、`Parameter.StorageType`（String／Integer／Double）、
`AsString`、`AsInteger`、`AsValueString`、`HasValue`、`Definition.Name`、`Category.Name`、`Category.GetCategory`、
`doc.GetElement(el.GetTypeId())`、`t.FamilyName`（在 `try` 中）、`el.Id.Value` 先試後退 `IntegerValue`、`getattr(BuiltInCategory, n)`、
`FilteredElementCollector(...).OfCategory(bic).WhereElementIsNotElementType()`（BatchFill／BatchParamTools／BatchWorksets／ExcelRevitSync 皆用）、
`doc.GetWorksetTable().GetWorkset(id).IsEditable`（BatchWorksets.py:205）、Yes/No → 是／否。

## 1. 執行形態

| 形態 | 做法 | 優點 | 缺點 | 風險 |
|---|---|---|---|---|
| **A. Dynamo 節點讀目前開啟的文件** | 節點取得目前文件（`DocumentManager` [repo]），只讀 | 不開啟其他檔案；與已驗收的節點形態相同 | 只讀使用者開著的模型；工作集狀態即當下狀態；連結模型需另處理 | 低（只讀） |
| B. 批次分離開檔 | 參考 `BatchParamTools`／`BatchWorksets` 的 V3：`DetachAndPreserveWorksets` [repo] | 可一次多檔 | 開檔耗時；分離開啟的文件 `PathName` 為空；可能與已開啟或連結衝突 | 中（需在複本上測） |
| C. Add-in | External Command | 介面佳，長期 | 新專案與部署；目前 `revit/` 未涵蓋 | 高 |

**建議第一版：A**（只讀、單一文件、風險最低）。B 留第二階段。C 不在本階段。

## 2. 讀取範圍

- **收集器必須排除類型元素**：`FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()`（[repo] 的 Fill/Param/WS/Excel 皆如此）。
  否則類型元素會進入快照並被判為缺參數（假 FAIL）。
- **品類**：字典 7 個 `OST_*`。以字典的鍵呼叫 `getattr(BuiltInCategory, key)`，不依賴本地化的 `Category.Name`。
- **機櫃判定**：品類 `OST_ElectricalEquipment` 且族群名稱含 `SCADA_機櫃`。
- **只讀取字典品類**：其他品類不進快照。（**待使用者決定**：是否讀取其他品類並計數，決定 R3 「未涵蓋品類」在真實模型中是否出現，見第 8.2 節。）
- **連結模型：第一版不含。** 連結元件不在主文件收集結果中 [憑記憶]。此事實只顯示在 Watch（見第 2.1 節），**不進 CSV**（見 D2）。
- **工作集未開啟**：元件可能不可見或無法收集 [待確認]。設計：讀取前以 `GetWorksetTable()` [repo] 檢查相關工作集是否開啟；未開啟的事實只顯示在 Watch，**不進 CSV**（D2）。
- **元件不可見**（隱藏於視圖、設計選項、階段）：**待確認**，由 R1.5 探針確認。

### 2.1 model-level 事實的處理（D2）

核心沒有 model-level 檢查（`工作集載入`、`連結模型` 等）；快照 v2 也沒有 model-level 欄位；範圍檔的 model-level 列在 R1、R2 也沒有來源。因此：

- **R1、R2 不做 model-level 註記。** 工作集未開啟、連結模型未涵蓋等事實只在 **Watch 顯示**，**不寫入 CSV，也不寫入快照**。
- **R3 需要改契約（快照 v3 或新增 model-level 區塊）並修改核心**，因此 R3 **另案審核**，不屬於 R1/R2 的「核心不受影響」範圍（見第 9 節）。

## 3. 欄位對應

| 快照欄位 | 來源 | 做法 | 狀態 |
|---|---|---|---|
| `element_id` | `el.Id` | 先試 `Id.Value`，`AttributeError` 時退回 `Id.IntegerValue`（[repo] 寫法）。結果為 `int`。 | `Value`：[憑記憶] 2024 之後加入；`IntegerValue`：[憑記憶] 2024 起過時仍存在。**2025.5 的實際行為：[待確認]，由 R1.5 探針確認。** 內建元件的負值：[待確認]。 |
| `category` | 迴圈的字典鍵 | 不讀本地化的 `Category.Name` | 不需 API 斷言 |
| `family_name` | 類型元素 | `doc.GetElement(el.GetTypeId())` 取類型，再 `t.FamilyName`（在 `try` 中，失敗為空字串）[repo]。無族群 → `null`。 | 系統族群的 `FamilyName` 傳回值：**[待確認]**。`FamilyInstance.Symbol.Family.Name`：[憑記憶]，未採用。 |
| `parameters`（內建） | `get_Parameter(BuiltInParameter)`，失敗再以名稱 `LookupParameter` [repo：`BatchFillScadaParams.get_param`] | 服務類型：`RBS_CTC_SERVICE_TYPE`，備援 `服務類型`、`Service Type`；備註：`ALL_MODEL_INSTANCE_COMMENTS`，備援 `備註`、`Comments` [repo] | 語系備援名單需在目標語系下確認 [待確認] |
| `parameters`（共用） | 16 個 `SCADA_*` | 以字典的 GUID 查找（`get_Parameter(Guid)`：[憑記憶]，**[待確認]**）；失敗才以名稱 `LookupParameter` [repo] | 名稱查找受改名與語系影響；GUID 較穩定。使用哪一種見第 8.2 節第 7 項。 |
| 參數「不存在」（MISSING） | 查找（實例）結果為 `null` | 該名稱**不放入** `parameters` | [repo] 以 `None` 判斷 |
| 參數「存在但空白」 | 參數物件存在，值為空 | `""` | [repo] |
| 值轉字串 — String | `AsString()` | `None` → `""` | [repo] |
| 值轉字串 — Integer | `AsInteger()` | 十進位字串；Yes/No 型別轉「是／否」 [repo] | 字典參數都是文字，此分支目前用不到 |
| 值轉字串 — Double | `AsValueString()` [repo] 含單位格式 | **不穩定**（依使用者單位設定）。換算用 `UnitUtils`／`UnitTypeId`：[憑記憶]，待確認 | **見 D3：字典參數遇到不支援型別 → read_error。** |
| 值轉字串 — ElementId | — | 不支援，同 D3 | — |
| `read_only_parameters` | `Parameter.IsReadOnly` [repo] | 存在且唯讀者列入 | 所有唯讀參數是否都被正確判定：**未實測**（R1.5） |
| `read_error` | 例外或型別不支援 | 見第 3.1 節 | — |

### 3.1 型別不支援與「參數僅存在於類型」（D3、D6）

**D3 — 不支援型別絕不落入 MISSING。** 若字典參數的實際儲存型別為 Double、ElementId 或其他非 String／Integer：
該元件 `read_error = "型別不支援：<參數名> (<StorageType>)"`，`parameters` 與 `read_only_parameters` 皆為空。
**不得**把它從 `parameters` 中省略，否則核心會判為 MISSING_PARAMETER（假的「缺參數」）。

**D6 — 實例參數 vs 類型參數。** 本版**只讀實例參數**。查找順序：

1. 先在元件（實例）上查找字典參數。找到 → 依 3 的規則讀取。
2. 實例上找不到，但元件類型上有同名參數（以 `doc.GetElement(el.GetTypeId()).LookupParameter`，[憑記憶]，待確認）→ 該元件 `read_error = "參數僅存在於類型（本版只讀實例參數）：<參數名>"`。
   **不得**判為 MISSING（那是假缺參數），也不得讀取類型值當成實例值（會改變語意）。
3. 實例與類型都找不到 → MISSING（不放入 `parameters`）。

「類型參數是否也應讀取」列為第 8.2 節決定事項。

## 4. 文件安全限制

### 4.1 必須保證的事

1. 不開啟任何 `Transaction`／`TransactionGroup`／`SubTransaction`，不使用 `TransactionManager`。
2. 不呼叫 `Save`、`SaveAs`、`SaveAsLibrary`、`SynchronizeWithCentral`、`Delete`、`Create`、`Set`、`SetValueString`、`Commit`、`RollBack`、`Regenerate`、`Close`、`OpenDocumentFile`、`CreateNewLocal`、`ForceCloseTransaction`。
3. 不修改任何元件、參數、工作集、視圖。
4. 執行前後比較文件修改狀態與元件數（[待確認]：`doc.IsModified` 的可用性，由 R1.5 探針確認），不一致則報錯。

### 4.2 Reader 專用 AST 規則（D5）

Reader 必須匯入 Revit API，因此現有基本規則（禁止 `clr`、`Autodesk`、`RevitAPI`、`RevitServices`、`System`）**不能直接套用**。
Reader 規則以**明確清單**定義，只套用於 `revit_reader/` 原始碼（node 範本仍只套用基本規則，R2 另行審核）。

**允許的匯入（白名單）**

| 匯入 | 理由 |
|---|---|
| `clr.AddReference('RevitAPI')`、`clr.AddReference('RevitServices')`（字串常數參數） | repo 寫法 [repo] |
| `from RevitServices.Persistence import DocumentManager` | 取得目前文件（形態 A），repo 寫法 [repo] |
| `from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, BuiltInParameter, StorageType, ElementId, ModelPathUtils` | 只讀查詢與型別；`ModelPathUtils` 僅用於 `ConvertModelPathToUserVisiblePath` [repo] |
| `from System import String, Int32, Int64, Guid` | repo 已用 String／Int32／Int64 [repo]；`Guid` 僅在 GUID 查找成立時 [待確認] |

除上表外的 `Autodesk.*`、`System.*`、`clr` 用法一律違規。

**禁止的匯入（黑名單）**：`RevitServices.Transactions`（含 `TransactionManager`）、`Autodesk.Revit.UI`、`Autodesk.Revit.DB.Transaction*`、`System.IO`（Reader 不寫檔，寫檔由既有的 CSV／JSON 輸出器負責）。

**禁止的名稱與屬性**：第 4.1 節第 2 點的全部名稱，以及 `Set.Overloads`、`TransactionManager`、`SubTransaction`、`TransactionGroup`。

**動態存取**：沿用嚴格規則（`getattr` 等只允許非禁止字串常數；`eval`、`exec`、`compile`、`__import__`、`importlib`、`builtins` 禁止）。

**限制**：AST 是靜態規則，無法判定型別。Revit 直接呼叫集中在 `revit_io.py`，讓審核範圍縮小。這些是**護欄，不是沙箱**。

## 5. source_file

| 來源 | 條件 | 決定 |
|---|---|---|
| 使用者路徑（參數） | 批次開檔（B）時必須 | 一律使用使用者路徑，不取 `PathName` |
| `doc.PathName` | 形態 A | 有值則使用，寫入快照 `source_file`（完整路徑） |
| `doc.PathName` 為空 | 未另存文件（例如未存檔的「專案1」） | **報錯**，要求先另存；不得用空字串或假路徑 |

Watch 必須同時顯示 `PathName`、`doc.Title`、中心模型路徑（若有；[repo] 寫法 `GetWorksharingCentralModelPath`，格式 [待確認]）。
CSV 的 `model_file` 仍只寫檔名（既有行為）。

## 6. 與核心的邊界

- **流程**：`revit_io`（Revit 讀取，回傳純資料）→ `normalize`（純 Python：欄位正規化、read_error 組裝）→ `snapshot.validate_elements`（必須通過，否則報錯）→ `check_completeness` → `write_completeness_reports`（CSV）。
- **快照 JSON 輸出（D9）**：Reader 同時把 Snapshot v2 JSON 寫到輸出資料夾，**檔名帶時間戳、不覆寫**，作為可追溯的中間產物。
  日後 Revit 外的程式（例如使用者正在評估的 Tkinter 介面）可直接讀此 JSON，經 `parse_snapshot` 驗證後呼叫核心。
  - **限制**：v2 快照沒有工具版本、執行時間、文件標題等出處欄位。若要把出處寫進 JSON，需契約升版（另案審核）。第一版的出處只在 Watch 與 CSV 的 `tool_version`／`run_time` 中。
  - JSON 寫入採暫存檔再改名，與 CSV 相同的失敗規則。
- **程式碼位置**：新套件 `revit_reader/`，不改 `mep_toolkit` 核心。
  - `revit_reader/normalize.py`：純 Python，無 Revit import，可用假物件測試。
  - `revit_reader/revit_io.py`：唯一含 Revit import 的檔案，只讀，回傳純資料。
- **嵌入 .dyn**：沿用 `tools/make_dyn.py` 的做法，嵌入 `mep_toolkit` 與 `revit_reader`。**建議另建新 .dyn**（例如 `完整度檢查_讀取_<時間戳>.dyn`），不改已驗收的 `完整度檢查_*.dyn` 產生方式。
- **自檢**：雜湊清單擴充為「mep_toolkit + revit_reader + 字典」，建置時寫入，執行時重算。
- **決定性**：建置決定性不變（uuid5、無時間）。執行時的資料（模型內容、執行時間）本來就不決定性；決定性只保證「同一快照、同一執行時間 → 同一 CSV」。

## 7. 測試策略

### 7.1 可自動測試（純 Python，無 Revit）

以**假物件**模擬 Revit 元件、參數、ElementId、類型、工作集表。涵蓋：

- `Id.Value` 存在與不存在（退回 `IntegerValue`）。
- 參數不存在 → MISSING（不放入）；存在但空白 → `""`；唯讀 → 列入 `read_only_parameters`。
- String、Integer 轉換；Double、ElementId → `read_error "型別不支援"`，**且不得出現 MISSING**（D3 的負向測試）。
- 實例上無、類型上有 → `read_error "僅存在於類型"`，**不得出現 MISSING**（D6 的負向測試）。
- 單一元件例外 → 該元件 `read_error`，其他元件照常；參數與唯讀清單為空。
- 整批層級例外 → 報錯，不產生任何輸出。
- 產生的快照通過 `validate_elements`；無效時不進核心。
- `family_name` 為空 → `null`。
- 收集器必須排除類型元素（假收集器只回傳實例，並驗證呼叫鏈包含 `WhereElementIsNotElementType`）。

### 7.2 Revit 內手動驗收

**測試專案（D4 修訂）**：

- **(a) 主要測試**：在空白專案中手動建立少量元件，**先另存為測試資料夾內的新檔**（不是正式模型，也不是未存檔的專案），再執行。
  測試元件：2 條導管、1 條電纜架、1 個電氣設備（備註 SCADA）、1 個名稱含 `SCADA_機櫃_TEST01` 的測試族群、1 個備註為空的設備、1 個缺少某參數的元件。
- **(b) 複本**：正式模型的複本（不得直接使用正式模型）。
- **未存檔專案**：只用於清單第 2 項，驗證報錯。
- 共用參數：為測試 GUID 查找，載入 16 個 SCADA 共用參數（只讀使用共用參數檔，不修改）。

**驗收清單（草案）**：

1. 節點在測試專案執行；Watch 顯示 `PathName`、`Title`、元件數、各品類數量，與手動建立的數量相符。
2. 未存檔專案 → 報錯要求另存（驗證 source_file 規則）。
3. 缺少備註的設備 → FAIL（MISSING，reason 清楚）。
4. 唯讀參數（如何建立唯讀參數：[待確認]）→ 依值判斷。
5. 執行前後文件修改狀態（`doc.IsModified`，[待確認]）不變；Revit「復原」清單無新增操作。
6. 兩次執行，第一次的 CSV 與快照 JSON 未被覆寫。
7. CSV 與快照 JSON 與手動預期結果逐列相符。
8. 類型元素未出現在快照中（D1 的驗證）。

**驗收標準**：清單 1–8 全部通過，AST 護欄與自動測試仍通過。任一項失敗即不放行。

## 8. 風險、未知與需要使用者決定的事項

### 8.1 風險與未知

- ElementId `Value`／`IntegerValue` 在 2025.5 的行為（[待確認]，R1.5）。
- `FamilyName` 對系統族群的傳回值（[待確認]，R1.5）。
- `IsReadOnly` 的判定是否正確（未實測，R1.5）。
- `get_Parameter(Guid)` 的存在與用法（[憑記憶]，[待確認]，R1.5）。
- `IsModified` 的可用性（[待確認]，R1.5）。
- 未開啟工作集的收集行為（[待確認]，R1.5）。
- 類型參數 `LookupParameter` 的行為（[憑記憶]，[待確認]）。
- Double 單位換算 API（[憑記憶]，[待確認]）。
- 連結模型與 `GetLinkedDocuments` 的行為（[待確認]）。
- 大型模型效能（未測）。
- AST 護欄是靜態規則，有意繞過仍可能成功（已註明）。

### 8.2 需要使用者決定

1. **第一版是否只做單檔（形態 A）？** 建議：是。
2. **測試用文件**：正式模型的複本（建議）或測試專案。正式模型一律不用。
3. **是否納入連結模型？** 建議：第一版不含，Watch 註記（不進 CSV，D2）。
4. **工作集未開啟**：Watch 註記並繼續（建議，因不進 CSV），或報錯停止？
5. **元件數上限與大模型執行時間**：可接受範圍？
6. **輸出檔位置**：沿用使用者輸入資料夾（建議）。CSV 與快照 JSON 同一資料夾。
7. **參數查找**：GUID 優先（建議，需 R1.5 確認 API）或名稱優先？
8. **真實模型是否讀取其他品類並計數？** 建議：只讀字典品類。若要 R3「未涵蓋品類」在真實模型出現，需 R3（契約與核心變更，另案）。
9. **Double／ElementId 參數**：依 D3 一律 read_error（建議，不可省略）。是否要日後支援，另案。
10. **類型參數**：第一版只讀實例（D6 的 read_error 處理，建議）；是否改讀類型參數，另案。
11. **新建一支 `.dyn`**（建議）。
12. **Add-in（形態 C）**：是否排入後續規劃？

## 9. 實作分階段計畫

每階段可獨立驗收與回退。**R3 需改契約與核心，不在 R1／R2 的「核心不受影響」範圍內，須另案審核。**

| 階段 | 內容 | 驗收 | 回退 |
|---|---|---|---|
| R0 | 本設計文件審核與使用者決定（第 8.2 節） | 審核通過 | — |
| **R1.5** | **唯讀 API 探針**（D7）：只讀小節點，在**已存檔的測試專案**上實測第 0、3 節的所有 [待確認] 項：`Id.Value`／`IntegerValue`、系統族群 `FamilyName`、`IsReadOnly`、`get_Parameter(Guid)`、`IsModified`、未開啟工作集的收集行為、類型參數查找。結果寫入本文件後才寫 `revit_io`。參考 mep_tray `FittingProbeCommand`（[參考]）。 | 探針結果記錄於文件，所有 [待確認] 改為已確認或維持待確認 | 不影響任何產物 |
| R1 | `revit_reader/normalize.py` 純 Python + 假物件測試；`build_snapshot` 通過 `validate_elements`；Reader 專用 AST 規則（第 4.2 節）與測試 | 自動測試雙環境通過；AST 規則測試通過 | 刪除套件，核心不變 |
| R2 | `revit_io.py` 單檔形態 A 讀取；新 .dyn（只讀）；寫出 CSV 與快照 JSON；Watch 註記工作集與連結（不進 CSV，D2）；手動驗收清單 1–8 | 手動驗收通過；雜湊與決定性測試通過 | 不使用新 .dyn；既有 .dyn 不變 |
| R3 | model-level 註記：契約升版（快照 v3 或 model-level 區塊）與核心修改 | **另案審核**，不在本設計範圍 | 另案決定 |
| R4 | 形態 B 批次開檔，僅在複本上測試 | 批次結果與單檔逐列一致；不寫入任何來源檔 | 不使用 B 的 .dyn |
| R5 | 評估 Add-in（形態 C） | 另案規劃 | — |

## 10. 不在本文件範圍內

- 任何 Revit API 程式（本文件僅為設計）。
- R3 的契約與核心變更（另案審核）。
- 連結模型的座標與重複元件處理。
- 2500 mm 條款、50 mm、1 mm 的判定（M4）。
- 推送與既有工具的修改。
