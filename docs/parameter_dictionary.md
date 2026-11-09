# 參數字典與完整度檢查

設定檔：`config/parameter_dictionary.json`；載入與驗證：`mep_toolkit/dictionary.py`。
規格來源：`docs/M2_spec.md` 第 3 項。

## 現行雙軌

| 品類 | 必填參數 | 合法值 |
|---|---|---|
| `OST_Conduit`、`OST_ConduitFitting`、`OST_CableTray`、`OST_CableTrayFitting` | 服務類型 | `SCADA` |
| `OST_ElectricalEquipment`、`OST_ElectricalFixtures`、`OST_Wire` | 備註 | `SCADA` |

對照 `BatchFillScadaParams.py` 的 `RULES`，品類與參數相同。

## 值的判定（沿用 `decide()` 語意）

| 現值 | 結果 | reason |
|---|---|---|
| 無此參數或唯讀（`null`） | FAIL | 無此參數或為唯讀 |
| 空白 | FAIL | 為空（缺漏） |
| 與合法值只差大小寫或頭尾空格 | FAIL | 可修正，附現值 |
| 其他值 | FAIL | 保留他值，附現值 |
| 合法值 | PASS | |
| 元件讀取失敗 | UNVERIFIED | 附例外文字 |

注意：批次填參數工具遇到「其他值」會**保留不改**；本檢查把它列為 FAIL，並寫出現值。

## 機櫃（族群名稱含 `SCADA_機櫃`，品類 `OST_ElectricalEquipment`）

機櫃**不**適用「備註 = SCADA」（備註是「站點 房間 機櫃類型」），改為兩個檢查：

1. `機櫃_SCADA共用參數齊全`：16 個 `SCADA_*` 共用參數都必須存在；其中 7 個（編號、站點、房間、機櫃類型、寬、深、高）值不可為空。
2. `機櫃_族群名稱規則`：名稱須為 `SCADA_機櫃_` + 編號；編號不可為空、頭尾不可有空格、不可含 `\ / : * ? " < > |`、不可以 `.` 結尾（與 `scada_racks.py` 的 `family_name` 相同）；
   且與 `SCADA_編號` 的值一致。

同一元件有多個問題時合併成一筆 FAIL。

## 參數名稱的來源（已核對）

16 個名稱取自 `D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\NWC\SCADA_SoW_V6_SharedParameters.txt`
（UTF-16，sha256 `5d8ced89fe445bf10b5e4e17bb47acca81bc0ff13544954328e57ecb58bc9711`），
並對照 `scada_racks.py`（`PARAM_PREFIX = "SCADA_"`，`PLACEMENT_PARAM = "SCADA_定位來源"`）與 CSV 欄位。
測試 `test_rack_parameters_match_source_file` 固定這 16 個名稱，字典若偏離會失敗。

## 待使用者確認

1. **`SCADA_前方淨距mm`、`SCADA_後方淨距mm`、`SCADA_淨距依據`**：`scada_racks.py` 會由 CSV 欄位「前方淨距mm」「後方淨距mm」「淨距依據」加前綴建立，
   但共用參數檔（2025-10-28 版）**沒有**這三個名稱（檔案可能已過時）。目前列為 `pending_confirmation`，**不檢查**。
2. **哪些共用參數的值不可為空**：目前的 7 個（編號、站點、房間、機櫃類型、寬、深、高）是依 `validate_racks.py` 的必填欄位與 `scada_racks.py` 的族群命名規則**推定**，
   不是使用者明確指定。其餘 9 個只要求「參數存在」。
3. **族群名稱的編號是否必須等於 `SCADA_編號`**：`scada_racks.py` 建立時兩者來自同一欄位；專案中重新命名後是否仍須一致，未確認。目前檢查，可在字典把 `code_parameter` 設為 `null` 關閉。
4. **「無此參數」與「唯讀」目前不區分（都是 FAIL）**：快照契約以 `null` 表示兩者；若要分開，需在快照加欄位。
5. **機櫃是否只在 `OST_ElectricalEquipment`**：依 `scada_racks.py` 使用「電氣設備」族群樣板推定，未在 Revit 內確認。
6. 沒有任何值比對規則使用正規式；`BatchParamTools` 的 `設備編號~正規式` 規則尚未納入字典。
