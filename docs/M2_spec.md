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
