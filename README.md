# Revit MEP 唯讀檢查工具箱（M0 骨架）

目前只有純 Python core，不連接 Revit、不讀寫 RVT。

- `core/findings.py`：`Finding` 與 `Status`（PASS / FAIL / UNVERIFIED）。FAIL 與 UNVERIFIED 必須有原因。
- `core/csv_report.py`：輸出 CSV（UTF-8 BOM，Excel 可直接開；以 `'` 中和公式開頭的文字；先寫暫存檔再改名）。
- `scripts/make_sample_csv.py`：以假資料產生 `examples/sample_findings.csv`。
- `docs/M0_analysis.md`：Dynamo 部署方式比較、共用函式比對。

CSV 欄位：`tool_version, run_time, model_file, element_id, check, result, reason`。
`element_id` 空白表示針對整個模型的結果；`model_file` 只寫檔名。

## 相容性

core 必須相容 Python 3.9（Dynamo 3.3 CPython3），只用標準函式庫。

## 測試

```
python -m pytest
```

以 Dynamo 內建的 Python 3.9 執行同一組測試（不需 pytest）：

```
"%LOCALAPPDATA%\python-3.9.12-embed-amd64\python.exe" -B -m unittest discover -s tests -t .
```
