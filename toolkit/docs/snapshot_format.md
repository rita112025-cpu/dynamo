# 元件快照格式（Snapshot）— 契約 v2

日後 `revit_io` reader 的**輸出契約**，也是 `mep_toolkit.completeness` 的輸入。
本版只有純 Python 驗證（`mep_toolkit/snapshot.py`），**尚無 Revit 端實作，契約未經 Revit 實測**。
範例：`examples/sample_snapshot.json`（v2，路徑與名稱全為假資料）。
舊格式：`examples/legacy/sample_snapshot_v1.json`（v1，真實寫出過的格式，**會被拒絕**，供測試使用）。

## 三層分離

| 層 | 負責 | 位置 |
|---|---|---|
| Revit API | 讀取元件、輸出快照（reader） | 日後 `revit_io`（未實作） |
| 業務規則 | 判定 PASS／FAIL／UNVERIFIED | `mep_toolkit/completeness.py`、`thresholds.py` |
| 報告輸出 | 寫 CSV（先完整驗證，再原子寫入） | `mep_toolkit/csv_report.py` |

業務規則只接受通過 `snapshot.py` 驗證的資料，因此 reader 只要輸出符合本契約的 JSON 即可。

## 版本

`schema_version` 必須是整數 `2`。

- `1`、`true`、`2.0`、字串 `"2"` 一律拒絕（Python 中 `True == 1`、`2.0 == 2`，驗證器明確排除）。
- **v1 文件被拒絕，訊息會指出需要 version 2。** v1 用 `null` 同時表示「無此參數」與「唯讀」，兩者無法分辨，因此不做降級解讀。
- 版本不符時整份快照拒絕載入。

## 文件結構

```json
{
  "schema_version": 2,
  "source_file": "D:\\fake\\FAKE-ESC-TEST-STATION.rvt",
  "elements": [
    {"element_id": 2001001, "category": "OST_Conduit", "family_name": "FAKE 電管",
     "parameters": {"服務類型": "SCADA"}, "read_only_parameters": []}
  ]
}
```

| 欄位 | 必填 | 型別 | 規則 |
|---|---|---|---|
| `schema_version` | 是 | 整數 | 必須為 `2` |
| `source_file` | 是 | 字串 | **來源路徑**（使用者要求開啟的路徑）。不可取自分離開啟的文件的 `doc.PathName`（為空字串）。空白會被拒絕 |
| `elements` | 是 | 陣列 | 元件清單 |

不允許未知欄位；缺欄位一律拒絕。

## 元件

| 欄位 | 必填 | 型別 | 規則 |
|---|---|---|---|
| `element_id` | 是 | 整數（非布林） | ElementId 的整數值；快照內不可重複 |
| `category` | 是 | 非空字串 | BuiltInCategory 名稱，如 `OST_Conduit`。不在字典內的品類不檢查，但會以範圍檔的「未涵蓋品類」列出並計數 |
| `family_name` | 是 | 字串或 `null` | 沒有族群時為 `null`。機櫃以此判斷（含 `SCADA_機櫃`） |
| `parameters` | 是 | 物件 | 參數名 → **字串**。見下方「三種狀態」 |
| `read_only_parameters` | 是 | 陣列 | 參數名清單。每個名稱必須是 `parameters` 的鍵，且不可重複 |
| `read_error` | 否 | `null`、省略，或非空字串 | 非空表示**這個元件讀取失敗**（附例外文字）。此時 `parameters` 與 `read_only_parameters` 必須是空的 |

## 三種狀態（v2 的核心）

| 狀態 | 快照中的表示 | 判定 |
|---|---|---|
| **MISSING_PARAMETER**：模型沒有此參數 | 該名稱**不在** `parameters` 中 | **FAIL**，reason 寫「模型沒有此參數（MISSING_PARAMETER）」 |
| **READ_ONLY**：參數存在但不可寫 | 在 `parameters` 中，且名稱列在 `read_only_parameters` | 依**值**判斷：值正確 → **PASS**；值錯或為空 → **FAIL**，reason 註明「唯讀，批次工具無法修正」 |
| **UNREADABLE**：元件讀取失敗 | `read_error` 為非空字串，`parameters` 為 `{}` | **UNVERIFIED**，reason 附例外文字 |
| 一般參數，值為空白 | `""` | FAIL（缺漏） |
| 一般參數，有值 | 字串 | 依比對規則（可修正／保留他值／通過） |

**v2 不接受 `null`。** 任何參數值為 `null` 都會被拒絕，並提示改用上述兩種表示法。
這是為了不讓「無此參數」與「唯讀」再次被混成同一種值。

## Reader 的責任（日後實作，現為約定）

- `parameters` 的鍵使用字典中的參數名稱（如 `服務類型`、`備註`、`SCADA_編號`）。
  語系備援（`服務類型` / `Service Type`、`備註` / `Comments`，以及 BuiltInParameter）由 reader 處理，
  做法參照 `BatchFillScadaParams.get_param`。
- 讀到的參數值一律轉成字串（本契約只比對文字）。
- 參數不存在 → 不放進 `parameters`。參數存在但 `IsReadOnly` → 把名稱放進 `read_only_parameters`。
- 讀取某元件發生例外：`parameters` 與 `read_only_parameters` 填空，`read_error` 填例外文字；**不可略過該元件**，也不可當成「沒有參數」。
- 把所有要檢查的品類元件都放進來（含開啟全部工作集後的元件）。漏放的元件不會有任何結果，因此只有在範圍檔可以看出差異。

## 輸出

`check_completeness(elements, dictionary)` 回傳 Finding、CheckScope 與被忽略的品類計數；
`write_completeness_reports` 先完整驗證兩份報告，再以 `write_reports_atomic` 原子寫入（見 `README.md`）。
「每個被檢查元件、每個檢查恰好一筆」由輸出器強制。
