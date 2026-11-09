# M2 規格（使用者已選定，由審核方轉達）

日期：2026-11-09。本文件只記錄決定，不含實作。M3 實作其中第 3 項的純 Python 核心；
第 2 項建置腳本留到 M3 後段；第 4 項為 M4。

> 規範值未驗證，不得視為合規；零問題不代表合規。
> 附錄C 的數值取自審核方轉達的 業主需求書(四) 附錄C 第三章，**本專案尚未自行對照原文核實**。

## 1. 結果檔

維持「每個被檢查元件、每個檢查各一列（含 PASS）」。沒有結果就不是通過。

報告大小風險已知：5 萬元件 × 5 個檢查 ≈ 25 萬列。此為已接受的取捨；
若日後要縮小，需另行決定，且不可讓「沒有列」被解讀為通過。

## 2. 部署方式 C

- toolkit 的 `.py` 是**唯一來源**。
- 建置腳本把 `mep_toolkit` 核心原始碼寫進**新產生的** `.dyn` 的 Python 節點（單檔可攜，Dynamo Player 可用）。
- 參考做法：`D:\github\scada-cabinet-toolkit\tools\make_dyn.py`（以 `# <core-import>` ／ `# </core-import>` 標記區塊替換；本機已確認該檔存在）。
- **不改既有 5 支 `.dyn`／`.py`。**
- 產生的 `.dyn`，輸入值一律留空。
- 建置必須防止「`.dyn` 內程式與 `.py` 不一致」：建置時寫入來源雜湊，並有測試比對。
- 時程：M3 後段；M3 本輪不產生任何 `.dyn`。

## 3. 參數字典

依品類對應，保留現行雙軌；以 JSON 設定檔（`config/`）表示，每個品類列出必填參數與合法值。

| 品類 | 必填參數 | 合法值 |
|---|---|---|
| 電管、電管配件、電纜架、電纜架配件（`OST_Conduit`、`OST_ConduitFitting`、`OST_CableTray`、`OST_CableTrayFitting`） | 服務類型 | `SCADA` |
| 電氣設備、電氣裝置、電線（`OST_ElectricalEquipment`、`OST_ElectricalFixtures`、`OST_Wire`） | 備註 | `SCADA` |
| 機櫃（族群名稱含 `SCADA_機櫃`） | **不**要求備註 = SCADA（備註是「站點 房間 機櫃類型」）；改要求 `SCADA_*` 共用參數齊全與族群名稱規則 | 見字典 |

- 值比對沿用 `BatchFillScadaParams.decide()` 語意：
  空白 = 缺漏；大小寫／空格不同 = 可修正的 FAIL；其他值 = 保留他值（列為 FAIL，並寫出現值）。
- `SCADA_*` 共用參數的名稱必須來自來源檔，不憑記憶：
  `D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\NWC\SCADA_SoW_V6_SharedParameters.txt`（UTF-16）
  與 `scada_racks.py` 的欄位定義。無法確定者列入「待使用者確認」（見 `docs/parameter_dictionary.md`）。

## 4. Cable Tray 檢查 MVP（M4，規範值未驗證）

依據：業主需求書(四) 附錄C 第三章。reason 與文件須註明「規範值未驗證」。

**連接**
- connector 未連接，且附近（缺口 ≤ 50 mm，**提案值**，放 config 可調）有另一橋架／配件端點 → FAIL「疑似斷開」。
- 兩端皆未連接的孤立段 → FAIL。
- 已連接但端點相距 > 1 mm → FAIL。
- 其餘 → PASS。
- 連接器讀取失敗 → UNVERIFIED，reason 寫例外原因。

**離地高度**
- 水平橋架底面距關聯樓層 ≥ 2500 mm（附錄C「宜高出地面 ≥ 2.5 m」，門檻放 config）→ PASS，否則 FAIL。
- reason 註明「樓層標高不一定等於完成面」。
- 非水平（斜向／垂直）橋架本版不判定：UNVERIFIED，並寫原因。

**本版不做**
- 跨專業淨距（水管 400/300、設備 500、線架 600、通信線架 300 等）：
  範圍檔以 `examined = 0` + note「需連結其他專業模型，未涵蓋」呈現。
- 斜率與彎曲半徑。

## 5. 邊界（維持）

- 不改既有 5 支 Dynamo 腳本與 `.dyn`。
- 不實作 `revit_io`；M3 不連 Revit，不做 Revit 內實測。
- 不推送。

---

## 7. 暫定值與依據（審閱意見，審核方認可）

每個門檻在 `config/thresholds.json` 帶 `status`、`source`、`source_status` 欄位，並可由設定檔調整。
門檻的讀取與驗證：`mep_toolkit/thresholds.py`。

| 門檻 | 值 | `status` | `source_status` | 說明 |
|---|---|---|---|---|
| `cable_tray_gap_max` | 50 mm | provisional | 提案值，無原文依據 | 缺口 ≤ 50 mm 視為疑似斷開的判定距離 |
| `cable_tray_endpoint_tolerance` | 1 mm | provisional | 提案值，無原文依據 | 已連接端點相距 ≤ 1 mm 才算通過 |
| `cable_tray_floor_clearance` | 2500 mm | provisional | **待核對原文** | 見第 8 節 |

**規則：** 所有門檻在報告與 `reason` 中一律標示「暫定判定值」（`Threshold.label`）。
任何文件或報告**不得**把結果寫成「符合業主規範」。`status` 為 `confirmed` 時，`source_status` 必須是「已核對原文」（驗證器強制）。

## 8. 離地高度 2500 mm 的記錄（M4 使用，本版只列為設定）

| 項目 | 內容 |
|---|---|
| 原文條款 | 業主需求書(四) 附錄C 第三章（**條款編號與頁碼：待核對原文**） |
| 原文措辭 | 審核方轉達為「宜高出地面 ≥ 2.5 m」；**措辭與強制程度：待核對原文**（「宜」不等於「應」） |
| 適用對象 | **水平橋架（電纜架水平段）**。垂直與斜向本版**不判定**（UNVERIFIED，註明原因） |
| 高度基準 | **橋架底面**（三擇一：底部／中心線／頂部，本版定為底部，不得混用；驗證器只接受 `bottom`） |
| 單位 | mm |
| 判定方式 | 底面距關聯樓層的高度 **≥ 2500 → PASS**；< 2500 → FAIL。等於 2500 為 PASS |
| 標高說明 | 樓層標高不一定等於完成面；reason 須註明 |
| 狀態 | `provisional`，`source_status` = 待核對原文 |

## 9. SCADA 共用參數（已從來源檔核對）

- 來源：`D:\SCADA_主題導覽\01_BIM model\SCADA_機櫃_Dynamo\NWC\SCADA_SoW_V6_SharedParameters.txt`（UTF-16），sha256 `5d8ced89fe445bf10b5e4e17bb47acca81bc0ff13544954328e57ecb58bc9711`。
- 16 個參數的**名稱、GUID、資料型別**全部由檔案讀出，未自行命名或憑記憶填寫。型別皆為 `TEXT`。
- 適用族群：`OST_ElectricalEquipment` 且族群名稱含 `SCADA_機櫃`（`scada_racks.py`）。
- 字典載入時驗證：GUID 格式（8-4-4-4-12 十六進位）、GUID 不重複、型別只接受 `TEXT`、名稱不重複、
  共用參數集合**必須等於**機櫃必填參數集合、來源 sha256 格式、適用族群與機櫃定義一致。
- 讀不到或無法確定的名稱列入「待使用者確認」，**不得自創替代名稱**（目前清單見 `docs/parameter_dictionary.md`）。

## 10. Snapshot 契約與三層分離

- Revit API（日後 `revit_io`，只負責讀取並輸出快照）、業務規則（`completeness.py`、`thresholds.py`）、報告輸出（`csv_report.py`）三者分離。
- 快照契約為 **v2**：固定欄位、型別、三種狀態（MISSING_PARAMETER／READ_ONLY／UNREADABLE）與版本號；載入時拒絕 v1 與不符版本、缺欄位與未知欄位。文件見 `docs/snapshot_format.md`。
- 業務規則只接受通過驗證的快照，因此 `revit_io` 只要輸出符合契約的資料，就能交給純 Python 核心。

## 11. 後續順序（審核方確認）

1. **M3 純 Python 核心 + Snapshot 契約**（本階段，已完成核心與驗證，見 `docs/M3_acceptance.md`）
2. M3 後段：新 `.dyn` 建置腳本（獨立驗證，**不覆寫既有 `.dyn`**）
3. M4：Cable Tray 檢查（連接、離地高度；門檻依第 7、8 節）
4. M5：Revit 2025 實機驗收
5. M6：測試複本批次執行與正式驗收

M3 期間不新增其他 Dynamo 功能。
