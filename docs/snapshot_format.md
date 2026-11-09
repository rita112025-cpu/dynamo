# 元件快照格式（Snapshot）

日後 `revit_io` reader 的**輸出契約**，也是 `mep_toolkit.completeness` 的輸入。
本階段只有純 Python 驗證（`mep_toolkit/snapshot.py`），尚無任何 Revit 端實作，契約**未經 Revit 實測**。
範例：`examples/sample_snapshot.json`（路徑與名稱全為假資料）。

## 檔案結構（UTF-8 JSON，每個模型一份）

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

| 欄位 | 型別 | 意義 |
|---|---|---|
| `schema_version` | int | 目前必須是 `1` |
| `source_file` | 字串 | **來源路徑**：使用者要求開啟的路徑。不可由分離開啟的文件讀 `doc.PathName`（為空字串）。空值會被拒絕。 |
| `elements` | 陣列 | 元件清單 |

### 元件

| 欄位 | 型別 | 意義 |
|---|---|---|
| `element_id` | int | ElementId 的整數值；同一快照內不可重複 |
| `category` | 字串 | BuiltInCategory 名稱，例如 `OST_Conduit`。不在參數字典內的品類會被忽略並計數（不檢查、無 Finding） |
| `family_name` | 字串或 null | 族群名稱；沒有則 null。機櫃以此判斷（含 `SCADA_機櫃`） |
| `parameters` | 物件 | 參數名 → 值。值為字串；**`null` 表示「無此參數，或為唯讀」**（兩者不區分）；空字串表示有此參數但沒有值 |
| `read_error` | 字串或 null（可省略） | 非空表示**這個元件完全讀不到**（例外文字）；此元件所有檢查都標 UNVERIFIED，並寫入該文字 |

不允許未知欄位；型別不符、`element_id` 重複、`source_file` 為空都會拋 `SnapshotError`，不會悄悄略過。

## Reader 的責任（日後實作，現為約定）

- `parameters` 的鍵用**字典裡的參數名稱**（例如 `服務類型`、`備註`、`SCADA_編號`）。
  名稱的語系備援（`服務類型` / `Service Type`、`備註` / `Comments`，以及 BuiltInParameter）由 reader 處理，
  做法參照 `BatchFillScadaParams.get_param`。
- 只放字典用得到的參數；數值型參數也轉成字串（本契約只比對文字）。
- 讀取某元件時發生例外：填 `read_error`，不要略過該元件，也不要把它當成「沒有參數」。
- 把所有要檢查的品類元件都放進來（含開啟全部工作集後的元件）；漏放的元件不會有任何結果。

## 輸出

`check_completeness(elements, dictionary)` 回傳 Finding、CheckScope 與被忽略的品類計數；
`write_completeness_reports` 透過既有的 `write_scope_csv`／`write_findings_csv` 輸出，
因此「每個被檢查元件、每個檢查恰好一筆」由輸出器強制。
