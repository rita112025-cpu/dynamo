# Revit Snapshot Reader：設計文件（只設計，不寫程式）

日期：2026-11-09。狀態：**草案，待審核與使用者決定**。本文件不含任何 Revit API 程式，也不連接 Revit。

## 0. 本文件的依據與標示規則

每個 Revit API 斷言都標示來源，三種之一：

- **[repo]**：既有腳本已在實際使用（可在 `G:\Dynamo` 中查到，已讀取確認）。
- **[憑記憶]**：來自開發者記憶，**未查證 Autodesk 文件，也未在 Revit 2025.5 實測**。
- **[待確認]**：本文件無法確定，需在 Revit 2025.5 + Dynamo 3.3.2 中以小測試確認。

目前的已知事實（repo）：`doc.PathName`、`GetWorksharingCentralModelPath`、`DetachFromCentralOption.DetachAndPreserveWorksets`、`CreateNewLocal`、`LookupParameter`、`get_Parameter(BuiltInParameter)`、`Parameter.IsReadOnly`、`Parameter.StorageType`（String／Integer／Double）、`AsString`、`AsInteger`、`AsValueString`、`HasValue`、`Definition.Name`、`Category.Name`、`Category.GetCategory`、`doc.GetElement(el.GetTypeId())`、`t.FamilyName`（後者在 `try` 中），以及 `el.Id.Value`（先試）後退到 `el.Id.IntegerValue`。

## 1. 執行形態

| 形態 | 做法 | 優點 | 缺點 | 風險 |
|---|---|---|---|---|
| **A. Dynamo 節點讀目前開啟的文件** | 節點透過 `DocumentManager` 取得目前文件，只讀取（參考 `ExcelRevitSync.py`，repo [repo]） | 不開啟其他檔案；與現有驗收的節點形態相同；最少新機制 | 只能讀使用者目前開著的模型；工作集狀態即使用者當下狀態；連結模型需另處理 | 低（只讀，不開 Transaction） |
| B. 批次開檔（分離） | 參考 `BatchParamTools`／`BatchWorksets` 的 V3 做法：`DetachAndPreserveWorksets` 分離開啟，不建本機檔 [repo] | 可一次處理多個 RVT | 開檔耗時高；分離開啟的文件 `PathName` 為空（已知，repo 註解）；需處理已開啟與連結衝突 | 中（開檔可能觸發同步或鎖定；需在複本上測） |
| C. Revit Add-in（External Command） | 以 C# 或新的 Add-in 提供按鈕與介面 | 介面佳、長期可維護 | 需新專案、新安裝流程；目前 `revit/` 已有 Add-in 但未涵蓋此功能 | 高（部署與權限） |

**建議第一版：A。** 理由：只讀、單一文件、與已驗收的節點形態相同，風險最低，且能直接在使用者開著的測試專案驗證。
B 留到第二階段（需先驗證分離開啟的行為與效能）。C 不在本階段範圍。

## 2. 讀取範圍

- **品類**：來自字典的 7 個 `OST_*`（Conduit、ConduitFitting、CableTray、CableTrayFitting、ElectricalEquipment、ElectricalFixtures、Wire）。
  品類名稱不依賴本地化的 `Category.Name`，而是直接以字典的鍵呼叫 `FilteredElementCollector(doc).OfCategory(getattr(BuiltInCategory, key))`
  [repo 做法：`getattr(BuiltInCategory, n)`，見 `ExcelRevitSync.resolve_categories`]。
- **機櫃判定**：機櫃是品類 `OST_ElectricalEquipment` 中族群名稱含 `SCADA_機櫃` 的元件，因此需要該品類的族群名稱（見第 3 節）。
- **只讀取字典所列品類**：其他品類不進快照。**待確認**：是否要讀其他品類並計數，讓 R3「未涵蓋品類」在真實模型中也會出現（目前設計不讀，所以真實模型不會出現未涵蓋品類列；差異需使用者決定）。
- **連結模型：預設不含。** 連結模型的元件不在主文件的收集結果中 [憑記憶]。範圍檔應加一列 model-level `examined=0`，note 寫「未涵蓋連結模型」，讓讀者知道範圍。
  是否涵蓋連結模型、如何涵蓋（開啟連結文件、座標、重複元件）為**待確認**，留待後續階段。
- **工作集未開啟**：元件可能不可見或無法收集 [待確認：在唯讀的目前文件中，未開啟工作集的元件是否會出現在收集結果中]。
  設計：讀取前先檢查工作集表（`WorksetTable`，API 名稱 [待確認]）；若有相關品類所在工作集未開啟，該事實寫入 model-level 結果，
  對應 `工作集載入` 檢查給 UNVERIFIED（沿用 `docs/unverified_policy.md` 的規則），**不得**悄悄略過。
- **元件不可見**（隱藏於視圖、設計選項、階段）：**待確認**。預設設計為「文件全域收集」，不套用視圖過濾；若收集結果不含某些元件，需由測試專案確認。

## 3. 欄位對應

| 快照欄位 | 來源 | 做法 | 狀態 |
|---|---|---|---|
| `element_id` | `el.Id` | 先試 `Id.Value`，`AttributeError` 時退回 `Id.IntegerValue`（與 repo 相同寫法 [repo]）。結果為 `int`。 | `Value`：[憑記憶] 於 Revit 2024 之後加入；`IntegerValue`：[憑記憶] 2024 起過時但仍存在。**兩者在 Revit 2025.5 的實際行為為待確認**（使用者可在 Dynamo 中以 Python 節點測試）。內建元件（負值）需確認。 |
| `category` | 迴圈的字典鍵 | 不讀 `Category.Name`（本地化） | 不需 API 斷言。 |
| `family_name` | 元件的類型 | repo 做法：`doc.GetElement(el.GetTypeId())` 取類型，再 `t.FamilyName`（在 `try` 中，失敗為空字串）[repo]。 無族群的元件（系統族群，如導管）→ `null`。 | `FamilyName` 對系統族群的傳回值為**待確認**。`FamilyInstance` 的 `Symbol.Family.Name` 為 [憑記憶]，未採用，待確認。 |
| `parameters`（內建） | `get_Parameter(BuiltInParameter)`，失敗再以名稱 `LookupParameter` [repo：`BatchFillScadaParams.get_param`] | 服務類型：`RBS_CTC_SERVICE_TYPE`，備援名稱 `服務類型`、`Service Type`；備註：`ALL_MODEL_INSTANCE_COMMENTS`，備援 `備註`、`Comments` [repo]。 | 語系備援名單需在目標語系下確認（待確認）。 |
| `parameters`（共用） | 16 個 `SCADA_*` | 以字典的 GUID 查找（`get_Parameter(Guid)` [憑記憶，待確認]）；失敗才以名稱 `LookupParameter`（repo 有名稱查找 [repo]）。 | GUID 查找 API 為待確認。GUID 較穩定（不受改名影響），名稱查找會受改名與語系影響。**使用哪一種的決定見第 8 節。** |
| 參數「不存在」 | 查找結果為 `null` | 該名稱**不放入** `parameters`（MISSING_PARAMETER） | repo 以 `None` 判斷 [repo] |
| 參數「存在但空白」 | 參數物件存在，值為空 | `""` | repo 以 `AsString() or ""` 處理 [repo] |
| 值轉字串 — String | `AsString()` | `None` → `""` | [repo] |
| 值轉字串 — Integer | `AsInteger()` | 轉為十進位字串。Yes/No 型別：repo 轉為「是／否」[repo]。字典用到的參數都是文字，此分支目前用不到。 | [repo] |
| 值轉字串 — Double | repo 用 `AsValueString()`（顯示字串，**含單位格式**）[repo] | **問題**：顯示字串依使用者單位設定而變，不穩定。建議改用內部單位數值並換算為 mm。 | 換算 API（`UnitUtils`、`UnitTypeId`）為 [憑記憶]，**待確認**。字典目前的 SCADA 參數皆為 TEXT，Double 分支在本階段不會用到；第一版建議標示為「不支援」，該參數不放入 `parameters`，並在 Watch 警告（待使用者決定，見第 8.2 節第 9 項）。 |
| 值轉字串 — ElementId / 其他 | — | 第一版不支援：寫入空字串並在 Watch 警告，或視為不支援參數（不放入） | 待使用者決定（第 8 節）。 |
| `read_only_parameters` | `Parameter.IsReadOnly` [repo] | 存在且 `IsReadOnly` 為真者，名稱列入清單 | 是否所有唯讀參數都可由 `IsReadOnly` 正確判定，**未實測**。 |
| `read_error` | 例外 | 見下方「例外處理邊界」 | — |

### 例外處理邊界

- **單一元件失敗不得中斷整批。** 每個元件的讀取包在獨立的 `try` 中。
- 元件內任何一個參數讀取失敗 → **整個元件** `read_error`，`parameters` 與 `read_only_parameters` 皆為空（符合 v2 契約，不做部分讀取）。理由：部分讀取會讓「讀失敗」被誤判成「缺參數」。
- `read_error` 的文字為 `例外型別名: 例外訊息`，並限制長度（待確認上限）。
- **整批層級的失敗**（取不到文件、收集器建立失敗）→ 整個節點報錯，**不產生快照**，不產生部分 CSV。
- 例外捕捉只針對 `Exception`；`KeyboardInterrupt` 等 `BaseException` 不捕捉，照常中止。

## 4. 文件安全限制

### 4.1 必須保證的事

1. 不開啟任何 `Transaction`／`TransactionGroup`。
2. 不呼叫 `Save`、`SaveAs`、`SynchronizeWithCentral`、`Delete`、`Create`、任何 `Set`、`SetValueString`、`Document.Close`、`OpenDocumentFile`。
3. 不修改任何元件、參數、工作集、視圖。
4. 完成後文件的修改狀態不變（**待確認**：`doc.IsModified` 的可用性；若可用，節點結束前檢查並寫入 Watch）。

### 4.2 如何在程式與測試中保證

現有 AST 護欄（`tools/dyn_checks.py`）的**基本規則**禁止 `Autodesk`、`clr`、`RevitAPI` 等匯入，且禁止 `Transaction`、`Save` 等名稱。
Reader 必須匯入 Revit API，因此**這些規則不能直接套用到 Reader**。需要一套新的「Reader 專用」規則：

- **允許匯入**：`Autodesk.Revit.DB` 中列在白名單的**只讀類別**（例如 `FilteredElementCollector`、`BuiltInCategory`、`BuiltInParameter`、`StorageType`、`ElementId`、`ElementId.Value` 相關存取）。白名單外的 `Autodesk.*` 匯入一律違規。
- **禁止屬性名稱**（黑名單，即使出現在白名單類別上也禁止）：`Set`、`SetValueString`、`Create`、`Delete`、`Save`、`SaveAs`、`SynchronizeWithCentral`、`Commit`、`RollBack`、`Start`、`Regenerate`、`OpenDocumentFile`、`Close`、`CreateNewLocal`、`ForceCloseTransaction`，以及 `Set.Overloads`。
- **動態存取**：沿用嚴格規則（`getattr` 等）。
- **限制**：AST 是靜態檢查，無法判定型別。因此 Reader 的 Revit 部分應盡量**只呼叫白名單中的方法**，並將 Revit 直接呼叫集中在單一檔案 `revit_io.py`，讓審核範圍縮小。
- 這些是**護欄，不是沙箱**：有意繞過仍可能成功。靜態規則的目的是攔住意外的寫入。
- **實機補強**：節點執行前後比較 `doc.IsModified`（[待確認]）與元件數，寫入 Watch；若不一致則報錯。

## 5. source_file

| 來源 | 條件 | 決定 |
|---|---|---|
| 使用者路徑（參數） | 批次開檔（B）時必須 | 批次開檔時一律使用使用者提供的來源路徑，不取 `PathName` |
| `doc.PathName` | 形態 A（目前文件） | 有值則使用，寫入快照 `source_file`（完整路徑）。 |
| `doc.PathName` 為空 | 未另存的文件（例如「專案1」未存檔） | **報錯**，要求使用者先另存，不可用空字串或假路徑。 |

可追溯性：Watch 必須同時顯示 `PathName`、`doc.Title`，以及工作集中心模型路徑（若有，repo 有 `GetWorksharingCentralModelPath` 的用法 [repo]，格式待確認）。
CSV 的 `model_file` 仍只寫檔名（既有行為）；同名不同資料夾的限制已在 README 註明。

## 6. 與核心的邊界

- **流程**：`Revit 讀取（revit_io）` → 純 Python 的 `build_snapshot`（欄位正規化、read_error 規則）→ `snapshot.parse_snapshot` 驗證 → `check_completeness` → `write_completeness_reports`。
  `build_snapshot` 的輸出**必須**通過 `snapshot.validate_elements`，不通過即報錯，不交給核心。
- **程式碼位置**：建議新增獨立套件 `revit_reader/`，不改 `mep_toolkit` 核心：
  - `revit_reader/normalize.py`：純 Python（無 Revit import）。欄位正規化、值轉字串、read_error 組裝。**可用假物件測試**。
  - `revit_reader/revit_io.py`：唯一允許 Revit import 的檔案。只做讀取，回傳純資料（dict list）。
- **嵌入 .dyn**：沿用 `tools/make_dyn.py` 的做法，把 `revit_reader` 原始碼與 `mep_toolkit` 一併嵌入。
  **建議另建一支新的 .dyn**（例如 `完整度檢查_讀取_<時間戳>.dyn`），不修改既有已驗收的 `完整度檢查_*.dyn` 產生方式，避免影響已驗收產物。
- **自檢**：雜湊清單擴充為「mep_toolkit + revit_reader + 字典」，建置時寫入，節點執行時重算。
- **決定性**：建置決定性不變（uuid5、無時間）。**執行時的資料**（Revit 模型內容、執行時間）本來就不決定性；決定性只保證「同一批快照輸入、同一執行時間 → 同一 CSV」，與前一階段相同。

## 7. 測試策略

### 7.1 可自動測試的部分（純 Python，無 Revit）

以**假物件**模擬 Revit 元件、參數、ElementId、類型：

- `Id.Value` 存在與不存在（退回 `IntegerValue`）的兩種情況。
- 參數不存在 → 不放入 `parameters`；存在但空白 → `""`；唯讀 → 列入 `read_only_parameters`。
- String、Integer、Double 的轉換（Double 在本階段以「不支援」處理，需測試其行為）。
- 單一元件丟出例外 → 該元件 `read_error`，其他元件照常；`parameters` 與 `read_only_parameters` 為空。
- 整批層級例外 → 報錯，無快照產生。
- 產生的快照通過 `validate_elements`；產生的快照無效時不進入核心（測試負向情況）。
- `family_name` 為空或不可取 → `null`。

### 7.2 Revit 內手動驗收（使用者執行，不得在正式專案上執行）

**測試專案**（二擇一，須使用者決定）：
- (a) 空白專案，手動建立少量測試元件：2 條導管、1 條電纜架、1 個電氣設備（備註 SCADA）、1 個名稱含 `SCADA_機櫃_TEST01` 的族群（測試用，非正式族群）、1 個備註為空的設備、1 個缺少某參數的元件。
- (b) 正式模型的**複本**（不得直接使用正式模型）。

**共用參數**：為了測試 GUID 查找，測試專案需載入 16 個 SCADA 共用參數（來源：共用參數檔，唯讀使用，不修改該檔）。

**驗收清單（草案，待審核）**：
1. 節點在測試專案執行，Watch 顯示 `PathName`、`Title`、元件數、各品類數量，與手動建立的數量相符。
2. 空白專案（未存檔）→ 報錯要求另存（驗證 source_file 規則）。
3. 缺少備註的設備 → FAIL，reason 含 MISSING_PARAMETER 或空值說明。
4. 唯讀參數（需先確認如何在 Revit 中建立唯讀參數 [待確認]）→ 依值判斷。
5. 執行前後 `doc.IsModified`（[待確認]）不變；使用者以 Revit「復原」清單確認沒有新增的操作紀錄。
6. 兩次執行的 CSV 第一份未被覆寫。
7. 手動比對 CSV 與手動建立的預期結果逐列相符。

**驗收標準**：清單 1–7 全部通過，且 AST 護欄與自動測試仍通過；任一項失敗即不放行。

## 8. 風險、未知與需要使用者決定的事項

### 8.1 風險與未知

- ElementId `Value`／`IntegerValue` 在 2025.5 的行為（[憑記憶]，待確認）。
- `FamilyName` 對系統族群的傳回值（待確認）。
- `IsReadOnly` 的判定是否正確（未實測）。
- `get_Parameter(Guid)` 的 API 存在與用法（[憑記憶]，待確認）。
- Double 單位換算 API（[憑記憶]，待確認）。
- 未開啟工作集的收集行為（待確認）。
- 大型模型的效能（收集與逐元件讀取的時間，未測）。
- 連結模型與 `GetLinkedDocuments` 的行為（待確認）。
- `doc.IsModified` 的可用性（待確認）。
- AST 護欄是靜態規則，有意繞過仍可能成功（文件已註明）。

### 8.2 需要使用者決定

1. **第一版是否只做單檔（形態 A）？** 建議：是。
2. **文件版本**：目前文件版或已儲存的複本？建議：只對複本測試，不對正式模型執行。
3. **是否納入連結模型**？建議：第一版不含，範圍檔明確註記。
4. **工作集未開啟**時：UNVERIFIED（建議）或直接報錯停止？
5. **元件數上限與效能**：是否設上限？大模型是否允許較長執行時間？
6. **輸出檔位置**：仍由使用者輸入資料夾（與現行一致，建議）？
7. **參數查找方式**：GUID 優先（建議，需確認 API）或名稱優先？
8. **真實模型的「未涵蓋品類」**：是否讀取其他品類並計數（讓 R3 在真實模型也出現），或只讀字典品類（建議，較簡單）？
9. **Double／ElementId 參數**：第一版是否不支援（建議），或寫入顯示字串？
10. **新 .dyn 與既有 .dyn**：新建一支（建議，不影響已驗收產物）？
11. **Add-in（形態 C）是否排入後續規劃**？

## 9. 實作分階段計畫

每階段可獨立驗收，且可回退（不使用該階段的 .dyn 即可，核心不受影響）。

| 階段 | 內容 | 驗收 | 回退 |
|---|---|---|---|
| R0 | 本設計文件審核與使用者決定（第 8.2 節） | 審核通過 | — |
| R1 | `revit_reader/normalize.py` 純 Python + 假物件測試；`build_snapshot` 通過 `validate_elements`；Reader 專用 AST 規則與測試 | 自動測試雙環境通過；AST 規則測試通過 | 刪除套件，核心不變 |
| R2 | `revit_io.py` 單檔形態 A 讀取；新 .dyn（只讀）；測試專案手動驗收清單 1–7 | 手動驗收通過；雜湊與決定性測試通過 | 不使用新 .dyn；既有 .dyn 不變 |
| R3 | 工作集未開啟與連結模型的範圍註記（UNVERIFIED／examined=0） | 測試專案含未開啟工作集與連結時的結果符合設計 | 停用該註記（需設計決定） |
| R4 | 形態 B 批次開檔（參考 V3），僅在複本上測試 | 批次結果與單檔逐列一致；不寫入任何來源檔 | 不使用 B 的 .dyn |
| R5 | 評估 Add-in（形態 C） | 另案規劃 | — |

## 10. 不在本文件範圍內

- 任何 Revit API 程式（本文件僅為設計）。
- 連結模型的座標與重複元件處理。
- 2500 mm 條款、50 mm、1 mm 的判定（M4）。
- 推送與既有工具的修改。
