# Revit MEP 唯讀檢查工具箱（M1）

目前只有純 Python 套件 `mep_toolkit`，不連接 Revit、不讀寫 RVT。

- `mep_toolkit/findings.py`：`Finding` 與 `Status`（PASS / FAIL / UNVERIFIED），以及 `CheckScope`（檢查範圍）。FAIL 與 UNVERIFIED 必須有原因。
- `mep_toolkit/csv_report.py`：輸出兩種 CSV（UTF-8 BOM，Excel 可直接開；先寫暫存檔再改名）。
- `scripts/make_sample_csv.py`：以假資料產生 `examples/` 下的兩個範例。
- `docs/unverified_policy.md`：UNVERIFIED 何時可以出現。
- `docs/M0_analysis.md`：Dynamo 部署方式比較、共用函式比對、`revit_io` 規劃。

## 兩個 CSV

**結果檔**（`write_findings_csv`）：`tool_version, run_time, model_file, element_id, check, result, reason`

- `element_id` 空白表示針對整個模型的結果。
- `model_file` 只寫檔名，**必須由呼叫端傳入來源路徑**（使用者要求開啟的那個路徑）。不可從開啟後的文件讀取：用 `DetachAndPreserveWorksets` 分離開啟的文件，`doc.PathName` 是空字串；空路徑會被拒絕。

**範圍檔**（`write_scope_csv`，每個模型一份）：`tool_version, run_time, model_file, check, examined, pass, fail, unverified, note`

- 每個檢查項目一列，`examined` 是實際檢查的元件數。「沒有問題」（examined > 0，fail = 0）和「沒有檢查」（examined = 0，且必須有 `note` 說明原因）因此可以區分。
- 輸出器在以下情況拒絕寫入：結果的檢查項目沒有對應範圍、同一檢查項目有兩筆範圍、某檢查回報的不同元件數超過它宣稱檢查的數量。

## 讀回 CSV 的注意事項

- 以 `= + - @` 開頭的文字會被加上 `'`，避免 Excel 當成公式執行。Excel 會把這個撇號顯示出來；用程式讀回時，請去掉文字欄位開頭的 `'`。
- 目標 CSV 正被 Excel 開著時，寫入會失敗，並顯示明確錯誤；舊報告維持不變，不會留下暫存檔。

## 相容性

`mep_toolkit` 必須相容 Python 3.9（Dynamo 3.3 CPython3），只用標準函式庫。套件名稱刻意不用 `core` 這類通用名稱，避免日後外部 import 時撞名。

## 測試

```
python -m pytest
```

`pytest.ini` 使用 `--disable-plugin-autoload`（避免全域安裝的外掛壞掉時中止整個測試），此選項需要 **pytest 8.4 以上**。

以 Dynamo 內建的 Python 3.9 執行同一組測試（不需 pytest）：

```
"%LOCALAPPDATA%\python-3.9.12-embed-amd64\python.exe" -B -m unittest discover -s tests -t .
```
