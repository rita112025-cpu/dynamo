# 參數字典與完整度檢查

設定檔：`config/parameter_dictionary.json`；載入與驗證：`mep_toolkit/dictionary.py`；
共用參數檔讀取：`mep_toolkit/shared_params.py`。規格來源：`docs/M2_spec.md` 第 3、9 節。

設定檔**不含**任何絕對路徑；來源檔的完整路徑只記在本文件（見下方「來源路徑」）。

## 來源路徑（本文件記錄，設定檔不含）

| 來源 | 完整路徑 | 用途 |
|---|---|---|
| 共用參數檔 | `D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\NWC\SCADA_SoW_V6_SharedParameters.txt`（UTF-16） | 16 個參數的名稱、GUID、型別，sha256 `5d8ced89fe445bf10b5e4e17bb47acca81bc0ff13544954328e57ecb58bc9711` |
| 機櫃族群定義 | `D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\scada_racks.py` | 族群名稱規則、共用參數寫入清單（推定依據） |
| 機櫃欄位檢查 | `D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\validate_racks.py` | 必填欄位（推定依據） |
| 批次填參數 | `G:\Dynamo\批次填參數\BatchFillScadaParams.py` | 現行雙軌（服務類型／備註）的來源 |

## 共用參數：名稱、GUID、型別（已從來源檔讀出）

16 個參數全部由共用參數檔讀出，型別皆為 `TEXT`。字典載入時驗證（`validate_dictionary`）：

| 驗證 | 失敗結果 |
|---|---|
| GUID 格式 8-4-4-4-12 十六進位 | 拒絕載入 |
| GUID 不重複（大小寫不計） | 拒絕 |
| 型別只接受 `TEXT` | 拒絕 |
| 名稱不重複 | 拒絕 |
| 共用參數集合 = 機櫃必填參數集合 | 拒絕（列出只在一邊的名稱） |
| 適用族群（類別 `OST_ElectricalEquipment`、名稱含 `SCADA_機櫃`）與機櫃定義一致 | 拒絕 |
| 來源 sha256 為 64 位小寫十六進位 | 拒絕 |
| 待確認參數不得同時是共用參數 | 拒絕 |

GUID 一律以小寫儲存。

### 字典 ↔ 共用參數檔：雙向驗證（`verify_against_shared_file`）

`tests/test_shared_consistency.py` 以**假資料的 UTF-16 共用參數檔**（在暫存資料夾產生，不讀 D:）驗證：

- 每個名稱對應正確 GUID，每個 GUID 對應正確名稱（反向也檢查）；型別一致。
- 負向案例（每一種都必須被偵測到）：字典多出參數、字典少了參數、檔案多出參數、GUID 在字典被改、GUID 在檔案被改、
  兩個名稱的 GUID 互換、型別不同、檔案在字典建立後內容變動（sha256 不符）、群組名稱不符、無 BOM 的檔案、沒有任何 PARAM 行的檔案。
- 測試 `test_shipped_values_reproduce_the_source_bytes`：把設定檔中的名稱、GUID、型別依來源格式編碼，得到的位元組其 sha256
  **恰好等於** 設定檔記錄的來源 sha256。也就是說，字典的值與來源檔逐位元一致。

實際的 D: 檔案**不由測試讀取**。日後要對實際檔案做核對，需人工執行 `verify_against_shared_file(load_dictionary(...), 實際路徑)`。

## 現行雙軌

| 品類 | 必填參數 | 合法值 | 來源 |
|---|---|---|---|
| `OST_Conduit`、`OST_ConduitFitting`、`OST_CableTray`、`OST_CableTrayFitting` | 服務類型 | `SCADA` | 批次填參數 `RULES` |
| `OST_ElectricalEquipment`、`OST_ElectricalFixtures`、`OST_Wire` | 備註 | `SCADA` | 批次填參數 `RULES` |

## 值的判定（沿用 `decide()` 語意，v2 三種狀態）

| 狀態／現值 | 結果 | reason |
|---|---|---|
| 模型沒有此參數（MISSING_PARAMETER） | FAIL | 模型沒有此參數 |
| 唯讀且值正確 | PASS | — |
| 唯讀且值錯或為空 | FAIL | 註明「唯讀，批次工具無法修正」，並附現值 |
| 一般參數，空白 | FAIL | 為空（缺漏） |
| 一般參數，與合法值只差大小寫或頭尾空格 | FAIL | 可修正，附現值 |
| 一般參數，其他值 | FAIL | 保留他值，附現值 |
| 讀取失敗（UNREADABLE） | UNVERIFIED | 附例外文字 |

注意：批次填參數工具遇到「其他值」會**保留不改**；本檢查把它列為 FAIL，並寫出現值。

## 機櫃（族群名稱含 `SCADA_機櫃`，品類 `OST_ElectricalEquipment`）

機櫃**不**適用「備註 = SCADA」（備註是「站點 房間 機櫃類型」），改為兩個檢查：

1. `機櫃_SCADA共用參數齊全`：16 個共用參數都必須存在（缺少者 FAIL，reason 寫 MISSING_PARAMETER）；其中 7 個值不可為空。
2. `機櫃_族群名稱規則`：名稱須為 `SCADA_機櫃_` + 編號；編號不可為空、頭尾不可有空格、不可含 `\ / : * ? " < > |`、不可以 `.` 結尾（與 `scada_racks.py` 的 `family_name` 相同）；且與 `SCADA_編號` 的值一致。

同一元件有多個問題時合併成一筆 FAIL。

## 規則來源：既有程式推定，**非業主確認**（R5）

設定檔 `rack.basis.status` 固定為「依既有程式推定，非業主確認」（驗證器只接受此字串，不可改寫成業主確認）。

| 規則 | 參數 | 來源（推定） | 狀態 |
|---|---|---|---|
| **值不可為空**（7 個） | SCADA_編號、SCADA_站點、SCADA_房間、SCADA_機櫃類型、SCADA_寬mm、SCADA_深mm、SCADA_高mm | `validate_racks.py` 的 `REQUIRED_COLUMNS`，以及 `scada_racks.py` 的欄位定義 | 依既有程式推定，非業主確認 |
| **只要求存在**（其餘 9 個） | SCADA_期別、SCADA_建物、SCADA_尺寸、SCADA_附錄D項次、SCADA_UPS電源110V、SCADA_附錄F項次、SCADA_來源文件、SCADA_備註、SCADA_定位來源 | `scada_racks.py` 寫入的 SCADA_* 共用參數清單 | 依既有程式推定，非業主確認 |
| **族群名稱規則** | 名稱前綴 `SCADA_機櫃_`、編號規則 | `scada_racks.py` 的 `family_name` | 依既有程式推定，非業主確認 |
| **適用族群** | `OST_ElectricalEquipment` 且名稱含 `SCADA_機櫃` | `scada_racks.py` 使用「電氣設備」族群樣板 | **推定**，未在 Revit 內確認 |

以上規則**不得被當成業主正式規定**。報告或文件引用時須註明其推定性質。

## 待使用者確認

| # | 事項 | 目前處置 |
|---|---|---|
| 1 | `SCADA_前方淨距mm`、`SCADA_後方淨距mm`、`SCADA_淨距依據` | 列為待確認，**不檢查**。共用參數檔沒有這三個名稱，`scada_racks.py` 卻會由 CSV 欄位加前綴建立。**不得自行補造 GUID**。待確認：是否有新版共用參數檔，以及 `scada_racks.py` 是否已正式使用這三項 |
| 2 | 共用參數的 GUID 與型別 | 已從共用參數檔（sha256 `5d8ced89…c9711` 這一版）讀出並核對。**版次未確認**（審核方所述為 10/28 版，本次只以檔案雜湊核對，未核對版次） |
| 3 | 適用族群 `OST_ElectricalEquipment` 與名稱含 `SCADA_機櫃` | 推定，未在 Revit 確認 |
| 4 | 7 個「值不可為空」與 9 個「只要求存在」 | 依既有程式推定，**非業主確認**（見上表） |
| 5 | 族群名稱的編號是否必須等於 `SCADA_編號` | 目前檢查。可在字典把 `code_parameter` 設為 `null` 關閉；命名規則是否定案待確認 |
| 6 | 無此參數與唯讀 | **已定案**：分開判定（MISSING_PARAMETER 為 FAIL；唯讀依值判斷），見 `snapshot_format.md` |
| 7 | 機櫃品類 | 依 `scada_racks.py` 使用電氣設備樣板推定，待 Revit 實際盤點 |
| 8 | BatchParamTools 的「設備編號~正規式」規則 | 納入下一版字典，沿用既有規則，不另創格式 |
