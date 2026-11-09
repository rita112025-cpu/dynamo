# 元件快照格式（Snapshot）— 契約 v1

日後 `revit_io` reader 的**輸出契約**，也是 `mep_toolkit.completeness` 的輸入。
本版只有純 Python 驗證（`mep_toolkit/snapshot.py`），**尚無 Revit 端實作，契約未經 Revit 實測**。
範例：`examples/sample_snapshot.json`（路徑與名稱全為假資料）。

## 三層分離

| 層 | 負責 | 位置 |
|---|---|---|
| Revit API | 讀取元件、輸出快照（reader） | 日後 `revit_io`（未實作） |
| 業務規則 | 判定 PASS／FAIL／UNVERIFIED | `mep_toolkit/completeness.py`、`thresholds.py` |
| 報告輸出 | 寫 CSV | `mep_toolkit/csv_report.py` |

業務規則只接受通過 `snapshot.py` 驗證的資料，因此 reader 只要輸出符合本契約的 JSON 即可。

## 版本

`schema_version` 必須是整數 `1`。`true`、`1.0`、字串 `"1"` 一律拒絕（Python 中 `True == 1`、`1.0 == 1`，驗證器明確排除）。
版本不符時整份快照拒絕載入，不做降級解讀。

## 文件結構

```json
{
  "schema_version": 1,
  "source_file": "D:\fake\FAKE-ESC-TEST-STATION.rvt",
  "elements": [
    {"element_id": 2001001, "category": "OST_Conduit", "family_name": "FAKE 電管",
     "parameters": {"服務類型": "SCADA"}}
  ]
}
```

| 欄位 | 必填 | 型別 | 規則 |
|---|---|---|---|
| `schema_version` | 是 | 整數 | 必須為 `1` |
| `source_file` | 是 | 字串 | **來源路徑**（使用者要求開啟的路徑）。不可取自分離開啟的文件的 `doc.PathName`（為空字串）。空白會被拒絕 |
| `elements` | 是 | 陣列 | 元件清單 |

不允許未知欄位；缺欄位一律拒絕。

## 元件

| 欄位 | 必填 | 型別 | 規則 |
|---|---|---|---|
| `element_id` | 是 | 整數（非布林） | ElementId 的整數值；快照內不可重複 |
| `category` | 是 | 非空字串 | BuiltInCategory 名稱，如 `OST_Conduit`。不在字典內的品類會被忽略並計數（不檢查、無 Finding） |
| `family_name` | 是 | 字串或 `null` | 沒有族群時為 `null`。機櫃以此判斷（含 `SCADA_機櫃`） |
| `parameters` | 是 | 物件 | 參數名 → 值。見下方「缺值規則」 |
| `read_error` | 否 | `null`、省略，或非空字串 | 非空表示**這個元件讀取失敗**（附例外文字） |

## 缺值規則（固定）

| 狀況 | `parameters` 中的表示 | 判定結果 |
|---|---|---|
| 有此參數，值為空白 | `""` | 空白 → FAIL（缺漏） |
| 有此參數，有值 | 字串 | 依比對規則 |
| **無此參數，或為唯讀** | `null` | FAIL（「無此參數或為唯讀」）。兩者目前不區分 |
| **讀取失敗** | `read_error` 為非空字串，且 `parameters` **必須是 `{}`** | UNVERIFIED，附例外文字 |

讀取失敗時 `parameters` 必須為空物件：不信任任何部分讀到的值，避免把「讀失敗」誤判成「缺參數」或「通過」。
違反此規則的快照會被拒絕（例如 `read_error` 同時帶有參數）。

## Reader 的責任（日後實作，現為約定）

- `parameters` 的鍵使用字典中的參數名稱（如 `服務類型`、`備註`、`SCADA_編號`）。
  語系備援（`服務類型` / `Service Type`、`備註` / `Comments`，以及 BuiltInParameter）由 reader 處理，
  做法參照 `BatchFillScadaParams.get_param`。
- 只放字典用得到的參數；數值型參數也轉成字串（本契約只比對文字）。
- 讀取某元件發生例外：`parameters` 填 `{}`、`read_error` 填例外文字；**不可略過該元件**，也不可當成「沒有參數」。
- 把所有要檢查的品類元件都放進來（含開啟全部工作集後的元件）。漏放的元件不會有任何結果，因此只有在範圍檔可以看出差異。

## 輸出

`check_completeness(elements, dictionary)` 回傳 Finding、CheckScope 與被忽略的品類計數；
`write_completeness_reports` 透過既有的 `write_scope_csv`／`write_findings_csv` 輸出，
「每個被檢查元件、每個檢查恰好一筆」由輸出器強制。
