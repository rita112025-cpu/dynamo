# M3 驗收表

日期：2026-11-09。每一列都對應到檔案或測試；「狀態」誠實標示未完成項目。

| 驗收項目 | 證據（檔案 / 測試） | 狀態 |
|---|---|---|
| **字典載入：必填欄位、GUID、型別正確** | `tests/test_dictionary.py`（`ValidationTest`、`SharedParameterTest`）；GUID 與來源檔逐一比對 | 通過（pytest 3.12、Python 3.9 皆通過） |
| 字典：拒絕未知品類、空必填、重複項、未知欄位、JSON 重複鍵 | `tests/test_dictionary.py` | 通過 |
| **完整度檢查：PASS／FAIL／UNVERIFIED 判定一致** | `tests/test_completeness.py`（`ClassifyTest`、`IdentificationTest`、`RackTest`）；`examples/sample_completeness_findings.csv` | 通過 |
| 完整度：每個被檢查元件、每個檢查恰好一筆（由輸出器強制） | `tests/test_completeness.py::test_every_examined_element_has_exactly_one_finding_per_check`；`tests/test_scope.py` | 通過 |
| 完整度：機櫃例外規則（不要求備註 = SCADA） | `tests/test_completeness.py::RackTest::test_rack_is_exempt_from_comments_rule` | 通過 |
| 完整度：品類不存在 → examined = 0 + note | `tests/test_completeness.py` | 通過 |
| **Snapshot：欄位、型別、缺值規則固定** | `tests/test_snapshot.py`（缺欄位、型別、`null`／`""`／`read_error` 規則）；`docs/snapshot_format.md` | 通過 |
| Snapshot：版本號，拒絕不符版本與缺欄位 | `tests/test_snapshot.py::DocumentTest::test_version_must_match_exactly`（含 `1.0`、`True`） | 通過 |
| 門檻：status／source／source_status 必填，2500 mm 記錄完整 | `tests/test_thresholds.py` | 通過 |
| 門檻判定：>= 通過（2500 等於 PASS）、<= 邊界 | `tests/test_thresholds.py::FloorClearanceJudgementTest` | 通過 |
| **規則測試：正常、異常、邊界** | 上列各測試檔（含邊界：2500、1 mm、50 mm；空白、大小寫、保留他值、讀取失敗） | 通過 |
| **Python 3.9 與 3.12 測試通過** | pytest 3.12；Dynamo 內建 Python 3.9.12 的 unittest（見 commit 訊息） | 通過 |
| **既有 Dynamo 腳本與 .dyn 雜湊不變** | 基準：`scratchpad/baseline_outside_toolkit.sha256`（toolkit 以外 12 個檔案）；完成後比對 | 見 commit 說明 |
| 報告與 reason 標示「暫定判定值」 | `Threshold.label`；M4 使用（本版尚無橋架判定） | 部分（標示機制已備，M4 才會產生橋架判定） |
| **建置腳本（新 .dyn）獨立驗證、不覆寫既有 .dyn** | 未實作 | **未完成**（M3 後段） |

## 未驗證（保留）

- 套件能否在 Dynamo Python 節點中 import（未在 Revit 內執行）。
- `ElementId.Value` ／ `IntegerValue` 的版本說明為憑記憶，未查 Autodesk 文件。
- 未用 Excel 實際開啟 CSV。
- 2500 mm 條款的位置與措辭「待核對原文」；50 mm 與 1 mm 為提案值。
- 快照契約未經 Revit 實測。
- 多模型彙總報告尚未設計。
- 「無此參數」與「唯讀」在快照中不區分。

## 待使用者確認

見 `docs/parameter_dictionary.md` 的「待使用者確認」清單（淨距三個名稱、必填 7 個是否為推定、族群編號一致性、唯讀與無參數的區分、機櫃品類推定、正規式規則）。
