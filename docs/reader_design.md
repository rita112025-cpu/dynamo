# Revit Snapshot Reader：設計文件（修訂版，只設計，不寫程式）

日期：2026-11-09。版本：r2（依審核方意見 D1–D9 修訂）。狀態：**草案，待審核與使用者決定**。
本文件不含任何 Revit API 程式，也不連接 Revit。

## 0. 標示規則與依據

每個 Revit API 斷言都標示來源，四種之一：

- **[repo]**：既有腳本已在實際使用，已在 `G:\Dynamo` 中以 grep 確認存在。
- **[憑記憶]**：來自記憶，**未查證 Autodesk 文件，也未在 Revit 2025.5 實測**。
- **[待確認]**：無法確定，需在 Revit 2025.5 中以唯讀探針確認（見 R1.5）。
- **[實測]**：已由第一次探針（2026-11-09，Revit 2025，報告 `reader_probe_20261109-141531.json`）證實，詳見 `docs/reader_probe.md` 第 6 節。
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
| `element_id` | `el.Id` | 先試 `Id.Value`，`AttributeError` 時退回 `Id.IntegerValue`（[repo] 寫法）。結果為 `int`。 | `Value`：[憑記憶] 2024 之後加入；`IntegerValue`：[憑記憶] 2024 起過時仍存在。**2025 實測 [實測]：兩者皆可用且相同（9/9）。** 內建元件的負值：[待確認]。 |
| `category` | 迴圈的字典鍵 | 不讀本地化的 `Category.Name` | 不需 API 斷言 |
| `family_name` | 類型元素 | `doc.GetElement(el.GetTypeId())` 取類型，再 `t.FamilyName`（在 `try` 中，失敗為空字串）[repo]。無族群 → `null`。 | 系統族群的 `FamilyName` 有值 [實測]；`Symbol` 僅 FamilyInstance 有 [實測]；**不得讀 `ElementType.Name`（[實測] TypeError）**。`FamilyInstance.Symbol.Family.Name`：[憑記憶]，未採用。 |
| `parameters`（內建） | `get_Parameter(BuiltInParameter)`，失敗再以名稱 `LookupParameter` [repo：`BatchFillScadaParams.get_param`] | 服務類型：`RBS_CTC_SERVICE_TYPE`，備援 `服務類型`、`Service Type`；備註：`ALL_MODEL_INSTANCE_COMMENTS`，備援 `備註`、`Comments` [repo] | 語系備援名單需在目標語系下確認 [待確認] |
| `parameters`（共用） | 16 個 `SCADA_*` | 以字典的 GUID 查找（`get_Parameter(Guid)`：探針 [實測] 可呼叫不拋例外；對 Excel 版機櫃查找 0/32 找到）；失敗才以名稱 `LookupParameter` [repo] | 名稱查找受改名與語系影響；GUID 較穩定。使用哪一種見第 8.2 節第 7 項。 |
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
4. 執行前後比較文件修改狀態與元件數（`doc.IsModified` 可讀 [實測]；第一次探針前後皆 True，無法作為未修改的證明），不一致則報錯。

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

### 8.1 風險與未知（第一次探針後更新）

**已由第一次探針實測（報告 `reader_probe_20261109-141531.json`，SHA-256 `50d46ac22f56b13bd8e19b68306dae519e5c3be1c11c6d98f33b33a6856fa0db`，見 `docs/reader_probe.md` 第 6 節）：**

- `Id.Value` 與 `Id.IntegerValue` 皆可用且相同（[實測] 9/9）。
- 系統族群的 `FamilyName` 有值，不為 null（[實測]）。
- `Symbol` 只存在於 FamilyInstance（[實測]）。
- `IsReadOnly` 可判定唯讀（[實測]：長度參數 True；服務類型與備註 False）。
- `get_Parameter(Guid)` 可呼叫且不拋例外（[實測]：32 次呼叫 0 例外，Guid 建構 32/32 成功）；對本模型的 Excel 版機櫃，以 SoW GUID 查找結果 0/32 找到（屬預期的跨組結果，見 9.1 的衝突）。
- `StorageType` 字串化後為列舉數值（[實測]：`'3'`、`'2'`）；reader 應與列舉比較。
- **不可讀 `ElementType.Name`**（[實測] `TypeError: property cannot be read`，28 次失敗皆為此）。
- 內建參數名稱備援無效：服務類型的 Definition.Name 為「服務類型:」，名稱查找找不到；「Comments」找不到（中文介面）（[實測]）。
- 連結模型數量可取得（[實測]：1 個）。

**仍待確認（需第二次探針，見 `docs/reader_probe.md` 第 10 節）：**

- 非空值讀取：機櫃共用參數已讀到非空字串（[實測]）；內建服務類型與備註的非空值尚未測（樣本皆空）。
- 唯讀共用參數：只有長度參數測過唯讀；共用參數中的唯讀者未測。
- `IsModified` 作為「未修改」證明：本次執行前即為 True，無法判定（[實測] 前 True、後 True）。第二次探針須先存檔。
- 未開啟工作集的收集行為與工作集內容：本次為非協作模型，未測。
- 連結模型內的元件：未測。
- 類型參數的實際行為：本次樣本的類型上找不到同名參數，樣本不足。
- Double 單位換算（`UnitUtils`）：未測（目前設計不支援 Double，不受影響）。
- 大型模型效能：未測。

### 8.2 需要使用者決定

1. **第一版是否只做單檔（形態 A）？** 建議：是。
2. **測試用文件**：正式模型的複本（建議）或測試專案。正式模型一律不用。
3. **是否納入連結模型？** 建議：第一版不含，Watch 註記（不進 CSV，D2）。
4. **工作集未開啟**：Watch 註記並繼續（建議，因不進 CSV），或報錯停止？
5. **元件數上限與大模型執行時間**：可接受範圍？
6. **輸出檔位置**：沿用使用者輸入資料夾（建議）。CSV 與快照 JSON 同一資料夾。
7. **參數查找（已決定規則）**：共用參數只用 GUID（見 11.4）；BuiltInParameter（服務類型、備註）以 BuiltInParameter 為唯一來源（見第 14 項）；名稱只用於顯示。
8. **真實模型是否讀取其他品類並計數？** 建議：只讀字典品類。若要 R3「未涵蓋品類」在真實模型出現，需 R3（契約與核心變更，另案）。
9. **Double／ElementId 參數**：依 D3 一律 read_error（建議，不可省略）。是否要日後支援，另案。
10. **類型參數**：第一版只讀實例（D6 的 read_error 處理，建議）；是否改讀類型參數，另案。
11. **新建一支 `.dyn`**（建議）。
12. **Add-in（形態 C）**：是否排入後續規劃？

13. **兩套機櫃族群與 GUID 衝突（已決定：兩套都納入，見第 11 節）**：專案同時有 SoW V6 與 Excel 版機櫃族群；Excel 版共用參數檔中，與字典同名的 8 個參數 GUID 全部不同（[實測] 與 [檔案比對]，見第 12 節）。字典目前只涵蓋 SoW V6，待第 11 節核准後才會擴充。
    **仍待決定的子決定（僅限第 11 節）**：(i) Snapshot 契約 v2 維持或升 v3（見 11.5）；(ii) 判定機櫃屬於哪一組的方案 A／B／C（見 11.3）；(iii) Excel 版「值不可為空」清單與族群名稱規則的出處（見 11.2、11.6）。
    *歷史選項（已不採用）*：原 (a) 只支援 SoW V6、(b) 兩套都納入、(c) 僅以名稱前綴區分。其中 (b) 即現行決定；(a)、(c) 已不採用。
14. **內建參數的名稱備援**：中文介面下，服務類型的名稱查找無效（[實測]）。建議：內建參數以 BuiltInParameter 為唯一來源；名稱備援刪除，或只作為「找不到時的提示」。
15. **類型名稱**：reader 不得讀 `ElementType.Name`（[實測] 不可讀）。類型名稱改用 `FamilyName`，或不納入快照。

### 8.3 探針後新增的風險

- **字典與模型不一致時的靜默錯誤**：本次 GUID 查找 0/32，若 reader 不區分「找不到」與「不符」，會產生誤導性的 MISSING_PARAMETER。設計要求：reader 測試必須包含「字典 GUID 全部找不到」的案例，並在報告中明確註記（不得只顯示為缺參數）。
- **IsModified 基準**：驗收程序必須先存檔再執行，否則「未修改」無法證明（第 7.2 節清單第 5 項的前提）。
- **文件安全護欄的證據**：探針原始碼通過 `reader_rules.py` 的白名單與黑名單（靜態證據）。實機報告只記錄 `IsModified` 前後值，並未記錄寫入類呼叫的執行證據；因 `IsModified` 前後皆 True，也無法由此證明未修改。這一點需要第二次探針補強（先存檔後比對）。


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

## 11. 兩套機櫃族群都納入（使用者決定）：待核准的修改設計

**狀態：文件設計，尚未實作，未獲核准任何程式、字典、核心或契約修改。**
**M3 驗收基準（commit 與狀態）維持不變**：基準 commit 為 **`13028af`**（M3 推定版驗收，最後一個 M3 commit；見 `docs/M3_acceptance.md`）。自 `13028af` 起，`mep_toolkit/`、`config/`、`docs/snapshot_format.md`、`docs/parameter_dictionary.md` 未變（審核方已核對）。其後 `tools/`（建置腳本、探針）與 `tests/`（探針、建置測試）的變更，屬各自獲核准的階段（建置腳本階段、R1.5 探針），**不屬 M3 基準**。
本節的任何設計若被核准實作，**需另案重新驗收**，本節本身不構成 M3 重新驗收，也不得被視為 M3 重新驗收。

### 11.1 決定

使用者於 2026-11-09 決定：**SoW V6 與 Excel 版兩套機櫃族群都納入**。以下為該決定的影響設計（第 11.2–11.8 節）。第 8.2 節第 13 項因此標為「已決定」。

### 11.2 字典結構（待核准）

現有 `rack` 區塊只有一套共用參數（SoW V6，群組 `SCADA_SoW_V6`）。擬改為兩套**參數組**，每組各自有來源檔與 SHA-256：

| 參數組 | 來源檔 | SHA-256 | 群組 | 參數數 | 與另一組的關係 |
|---|---|---|---|---|---|
| `SoW_V6` | `NWC\SCADA_SoW_V6_SharedParameters.txt`（`D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\NWC\`） | `5d8ced89fe445bf10b5e4e17bb47acca81bc0ff13544954328e57ecb58bc9711` | `SCADA_SoW_V6` | 16 | 同名 8 個（編號、機櫃類型、寬、深、高、尺寸、來源文件、定位來源）GUID 與 Excel 版**全不同** |
| `Excel` | `Excel_機櫃族群\族群\SCADA_Excel_SharedParameters.txt`（同上資料夾下） | `e9830267101a6612a0433966a584ac3565c11461c24973d823c48a39ce7ed9db` | `SCADA_Excel_Racks` | 16 | 同名 8 個（同上）；另 8 個僅 Excel 有（項次、安裝位置、機櫃規格、配置數量、台序、BIM設計與應用說明、來源工作表、來源列） |

**名稱、GUID、型別一律由程式從來源檔讀出，不得手填。** 讀取與雙向比對沿用 `verify_against_shared_file` 的做法（名稱↔GUID↔型別、群組、來源 sha256），**每一組各自比對**。
測試以假資料的 UTF-16 檔驗證（沿用 `tests/test_shared_consistency.py`），不讀 D: 真實路徑；真實檔案的核對由手動執行 `verify_against_shared_file` 完成。

**「值不可為空」清單與出處（每組各自列出，不得沿用另一組）：**

| 參數組 | 值不可為空（推定） | 出處（既有程式） | 狀態 |
|---|---|---|---|
| `SoW_V6` | 編號、站點、房間、機櫃類型、寬mm、深mm、高mm（7 個） | `validate_racks.py` 的 `REQUIRED_COLUMNS`，以及 `scada_racks.py` 的欄位定義 | 依既有程式推定，非業主確認（與現行一致） |
| `Excel` | 編號、機櫃類型、寬mm、深mm、高mm（5 個） | `excel_rack_runtime.py`：`family_name()` 拒絕空編號（第 100 行）；`main()` 拒絕空機櫃類型，且寬／深／高須為有限正數（第 233–241 行） | **依既有程式推定，非業主確認**；Excel 版無對應的 `validate_racks.py`，清單出處僅為產生程式，**待確認**是否有其他驗證 |

「只要求存在」的參數：SoW 組為其餘 9 個（期別、建物、尺寸、附錄D項次、UPS電源110V、附錄F項次、來源文件、備註、定位來源）；Excel 組為其 16 個中除上列 5 個以外的 11 個。**出處不明者列待確認**：Excel 版「尺寸」等欄位是否必填，以及 Excel 版是否還有其他驗證。

淨距參數（`SCADA_前方淨距mm`、`SCADA_後方淨距mm`、`SCADA_淨距依據`）維持**待確認、不檢查、不補造 GUID**，不因兩組而改變。

### 11.3 判定機櫃屬於哪一組

| 方案 | 做法 | 優點 | 缺點 |
|---|---|---|---|
| (A) 族群名稱前綴 | `SCADA_機櫃_XLSX-` 前綴歸 Excel，其餘歸 SoW | 簡單、可讀 | 前綴是 Excel CSV 的編號慣例，**不是保證**；不同編號格式會誤判；與實際參數不一致時無法發現 |
| (B) 依實際找到的 GUID 集合 | 用各組 GUID 在該元件查找，哪一組的參數**全部**找到就歸該組 | 以參數本身為證據；不依賴名稱 | 需要兩組 GUID 查找都成功；若兩組都部分找到，無法判定 |
| (C) 兩者都要成立（**建議**） | (A) 與 (B) 同時判定；兩者一致才歸組；不一致或皆不明，標 UNVERIFIED | 衝突可見；不猜 | 規則較複雜；需實機資料驗證 |

**衝突處理（建議）：** 名稱像 Excel、GUID 像 SoW（或反之）→ 該機櫃的共用參數相關檢查標 **UNVERIFIED**，reason 註明「族群名稱指向 X 組，參數 GUID 指向 Y 組，無法判定」，**不猜**。
皆不明（例如 GUID 全部找不到）→ UNVERIFIED，reason 註明「兩組 GUID 皆查無完整參數組」。（注意：若已判定為某組但該組 GUID 找不到，屬 MISSING_PARAMETER，FAIL，而不是 UNVERIFIED。）

**實測依據：** 第一次探針兩個機櫃樣本名稱含 `SCADA_機櫃_XLSX-003-01_機廠TSS`，SoW GUID 查找 0/32；Excel 組的 GUID 查找**尚未實測**（須第二次探針確認 16/16）。

### 11.4 查找規則（待核准）

1. 共用參數**一律依該機櫃所屬參數組的 GUID 查找**。
2. **不得以名稱查找共用參數**（同名不同 GUID 會讀到錯的參數）。
3. 名稱只用於報告顯示（例如 reason 中的參數名）。
4. 機櫃未能判定參數組時，共用參數相關檢查 UNVERIFIED，不查找、不猜。

### 11.5 契約影響：Snapshot v2 與未來 v3

| 項目 | v2（現行） | v3（擬，需核准契約修改） |
|---|---|---|
| 機櫃的參數組識別 | 無；`parameters` 以參數名稱為鍵，無法記錄值來自哪一組 GUID | 新增機櫃元件欄位 `shared_parameter_group`（值為 `SoW_V6`、`Excel`，或 `null` 表示無法判定） |
| 追溯 | 只能由族群名稱推得參數組 | 快照本身記錄判定的參數組，以及 `shared_group_found` 計數（找到幾個參數） |
| 舊快照 | 目前只有 v1 被明確拒絕 | 建議：**明確拒絕 v2**（訊息指出需要 version 3 以記錄參數組）；理由：v2 無法判定機櫃參數組，接受會產生不可追溯的結果 |

**兩個選項的比較：**

- **(a) 維持 v2**：Reader 與核心各自以族群名稱推得參數組。缺點：追溯性不足；Reader 與核心的判定可能不一致；快照無法證明判定依據。
- **(b) 契約升版為 v3（建議）**：機櫃元件加上參數組識別。缺點：需核准契約修改；舊快照須明確拒絕；核心與 Reader 須同步。

**影響範圍（若選 b）：**

| 對象 | 影響 |
|---|---|
| Reader（設計，未實作） | 必須判定參數組並輸出 `shared_parameter_group`；必須依組 GUID 查找 |
| 核心 `mep_toolkit`（`snapshot.py`、`completeness.py`） | 讀取 v3；依參數組選擇 GUID 組與值不可為空清單；v2 拒絕 |
| `.dyn` | 完整度檢查 `.dyn` 與探針 `.dyn` 需重建（程式內嵌核心與字典）；既有產物 SHA-256 會改變 |
| GUI（設計，未實作） | 只顯示 `shared_parameter_group` 與判定結果，不自行判定 |

### 11.6 族群名稱規則（待確認）

- **SoW 組**：族群名稱為 `SCADA_機櫃_<編號>`（`scada_racks.py` 的 `family_name`，已有出處）。規則「名稱編號 = SCADA_編號」僅適用此組。
- **Excel 組**：族群名稱為 `SCADA_機櫃_<編號>_<安裝位置標籤>`（`excel_rack_runtime.py` 的 `family_name()`，已有出處）。標籤由「安裝位置」對應：`Phase 1 SBxx Station` → `SBxx`；另有三個固定名稱；其他位置直接拋出例外。
- **第一次探針的樣本**：名稱 `SCADA_機櫃_XLSX-003-01_機廠TSS`，`SCADA_編號` 值 `XLSX-003-01`，與上述結構一致。
- **待確認**：Excel 組的「名稱中的編號部分」與 `SCADA_編號` 是否必須相等（樣本一致，但規則未經多個樣本驗證）。**不得把 SoW 的「名稱編號 = SCADA_編號」規則直接套用到 Excel 組，除非有出處。**

### 11.7 影響範圍清單（若核准）

| 檔案／對象 | 需要改 | 說明 |
|---|---|---|
| `config/parameter_dictionary.json` | **是** | `shared_parameters` 與 `rack` 區塊改為兩組參數組；各組有來源檔、sha256、群組、參數、值不可為空清單與出處 |
| `mep_toolkit/dictionary.py` | **是** | 驗證器支援兩組；雙向比對對每組執行；拒絕未知組 |
| `mep_toolkit/completeness.py` | **是** | 依參數組選擇 GUID 組；判定參數組（方案 C）；衝突標 UNVERIFIED |
| `mep_toolkit/snapshot.py` | **是（若選 b）** | v3 欄位；拒絕 v2 |
| `mep_toolkit/csv_report.py` | 否 | 輸出器不變，仍遵守「每元件每檢查恰好一筆」 |
| `tests/test_dictionary.py`、`tests/test_shared_consistency.py`、`tests/test_completeness.py`、`tests/test_snapshot.py` | **是** | 新增兩組與判定測試；16 組 GUID 固定常數增為兩組 |
| `tests/test_dyn_build.py` | **是** | `REFERENCE_PYTHON_NODE_KEYS` 不變；嵌入字典的測試隨之更新 |
| `tests/test_reader_probe.py` | **是** | `SHARED_PARAMETERS` 常數與字典比對隨之更新（探針原始碼需同步修改，需核准） |
| `tools/probe/reader_api_probe.py`、探針 `.dyn` | **是（若要第二次探針查兩組 GUID）** | 探針的共用參數常數須加入 Excel 組 |
| `tools/make_dyn.py`、`tools/dyn_checks.py` | 否 | 建置機制不變；只重建產物 |
| `tools/reader_rules.py` | 否 | Reader 護欄不變 |
| `docs/parameter_dictionary.md`、`docs/snapshot_format.md`、`docs/M3_acceptance.md`、`docs/M2_spec.md`、`docs/dyn_build.md` | **是** | 文件更新；`M3_acceptance.md` 須註明基準變更與重新驗收 |
| `docs/reader_design.md`、`docs/gui_design.md`、`docs/reader_probe.md` | 本次僅設計，已記錄 | 實作核准後再更新 |
| 既有五組 Dynamo 工具（`G:\Dynamo\批次*`、`Excel參數同步`）與 `dwg_batch_tool` | **否** | 本設計不涉及 |
| `examples/sample_snapshot.json` | **是（若選 b）** | 升為 v3 樣本；v2 樣本保留於 `examples/legacy/` 作拒絕測試 |

**重新驗收：** 若核准實作，字典與核心皆需變更，**M3 須重新驗收**（雙環境測試、10 檔雜湊、新產物雜湊、第二次探針）。在核准前，本設計不改變 M3 的驗收基準。

### 11.8 第二次探針的新增需求

測試模型須同時放入：SoW V6 版機櫃族群 RFA（`SCADA_機櫃_Dynamo\族群\`）與 Excel 版機櫃族群 RFA（`SCADA_機櫃_Dynamo\Excel_機櫃族群\`）各一。
探針需回答：(1) 兩套 GUID 在各自族群上的查找結果（SoW 組對 SoW 族群、Excel 組對 Excel 族群，應各為 16/16）；(2) 跨組查找（SoW GUID 對 Excel 族群、反之）的結果；(3) 非空值讀取；(4) 唯讀共用參數；(5) IsModified 前後（須先存檔）。

---

## 12. 規則證據表（第一次探針與本次文件）

標示：**[實測]** 已由探針報告證實（報告 `reader_probe_20261109-141531.json`，SHA-256 `50d46ac22f56b13bd8e19b68306dae519e5c3be1c11c6d98f33b33a6856fa0db`）；**[檔案比對]** 唯讀比對來源檔，非 Revit 實測；**[自動測試]** 假模組或純 Python 測試；**[待第二次探針]** 尚無實機證據。

| 規則 | 證據類型 | 證據（報告中的項目） | 狀態 |
|---|---|---|---|
| `Id.Value` 與 `Id.IntegerValue` 可用且相同 | [實測] | E3a：9/9 相同 | 已證實 |
| 系統族群的 `FamilyName` 有值，不為 null | [實測] | E3b：導管、電纜架 | 已證實 |
| `Symbol` 僅存在於 FamilyInstance | [實測] | E3d：hasattr 結果 | 已證實 |
| 不可讀 `ElementType.Name` | [實測] | E3e：28 次 TypeError | 已證實 |
| 服務類型 BuiltInParameter 可找到；Definition.Name 含冒號；名稱備援無效 | [實測] | E4a | 已證實 |
| 「Comments」名稱查找無效（中文介面） | [實測] | E4a | 已證實 |
| `IsReadOnly` 可判定唯讀 | [實測] | E4c：CURVE_ELEM_LENGTH True（僅此參數） | 部分證實（共用參數唯讀未測） |
| `StorageType` 字串化為數值，應與列舉比較 | [實測] | E4d | 已證實 |
| 服務類型與備註樣本為空（HasValue False） | [實測] | E4e | 已證實（僅空值） |
| 機櫃共用參數可讀非空字串 | [實測] | E5：編號、寬、深、高等 | 已證實 |
| SoW GUID 對 Excel 機櫃查找 0/32 | [實測] | E5 | 已證實（跨組反向） |
| `get_Parameter(Guid)` 可呼叫且不拋例外 | [實測] | E5 相關探針報告：32 次呼叫 0 例外；Guid 建構 32/32 成功 | 已證實（可呼叫；以 SoW GUID 查 Excel 機櫃找不到，屬預期的跨組結果） |
| 名稱查找對 Excel 機櫃每台找到 8 個 | [實測] | E5 | 已證實 |
| Excel 組與字典同名 8 個 GUID 全部不同 | [檔案比對] | 第 11.2 節（唯讀比對） | 已證實（檔案層級） |
| Excel 組 GUID 查找 16/16 | [待第二次探針] | — | 待確認 |
| SoW 組 GUID 查找對 SoW 機櫃 16/16 | [待第二次探針] | — | 待確認 |
| 非協作模型的工作集為 N/A | [實測] | E6 | 已證實（僅非協作） |
| 連結模型數量可取得（1 個） | [實測] | E7 | 已證實（數量） |
| 連結內元件可讀取 | [待第二次探針] | — | 未測 |
| IsModified 可讀 | [實測] | E8：True、True | 已證實（可讀） |
| 執行前後文件未修改 | [待第二次探針] | 第一次因文件已修改而無法判定 | 未證實（需先存檔） |
| 探針原始碼未含寫入類呼叫（靜態） | [自動測試] | `tools/reader_rules.py` 與測試 | 靜態證據（非實機執行證據） |
| 單一 API 失敗不中止 | [自動測試] + [實測] | 28 次 TypeError 後仍完成 731 步 | 已證實 |
| 類型參數 LookupParameter | [待第二次探針] | 樣本類型上皆找不到 | 樣本不足 |
| 非空值的 BuiltInParameter（服務類型、備註） | [待第二次探針] | 樣本為空 | 未測 |
| 唯讀共用參數 | [待第二次探針] | — | 未測 |
