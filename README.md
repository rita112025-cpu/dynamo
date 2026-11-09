# Revit MEP 唯讀檢查工具箱（M3）

目前只有純 Python 套件 `mep_toolkit`，不連接 Revit、不讀寫 RVT。

- `mep_toolkit/findings.py`：`Finding` 與 `Status`（PASS / FAIL / UNVERIFIED），以及 `CheckScope`（檢查範圍）。FAIL 與 UNVERIFIED 必須有原因。
- `mep_toolkit/csv_report.py`：輸出兩種 CSV（UTF-8 BOM，Excel 可直接開；先寫暫存檔再改名）。
- `scripts/make_sample_csv.py`：以假資料產生 `examples/` 下的兩個範例。
- `mep_toolkit/dictionary.py`、`config/parameter_dictionary.json`：參數字典（載入與驗證）。見 `docs/parameter_dictionary.md`（含「待使用者確認」清單）。
- `mep_toolkit/snapshot.py`：元件快照驗證（日後 `revit_io` reader 的輸出契約）。見 `docs/snapshot_format.md`。
- `mep_toolkit/completeness.py`：對快照做參數完整度檢查，輸出 Finding／CheckScope，經標準 CSV 輸出器寫出。
- `scripts/make_sample_completeness.py`：以假快照產生 `examples/sample_completeness_*.csv`。
- `config/thresholds.json`、`mep_toolkit/thresholds.py`：暫定門檻（50 mm、1 mm、2500 mm），每個都帶 `status`／`source`／`source_status`。所有報告一律標示「暫定判定值」，不得寫成符合業主規範。
- `docs/M3_acceptance.md`：M3 驗收表（含未完成項目：建置腳本）。
- `docs/M2_spec.md`：使用者選定的 M2 規格。
- `docs/unverified_policy.md`：UNVERIFIED 何時可以出現。
- `docs/M0_analysis.md`：Dynamo 部署方式比較、共用函式比對、`revit_io` 規劃。

## 兩個 CSV

**結果檔**（`write_findings_csv`）：`tool_version, run_time, model_file, element_id, check, result, reason`

- `element_id` 空白表示針對整個模型的結果。
- `model_file` 只寫檔名（**同名但不同資料夾的檔案無法區分**），**必須由呼叫端傳入來源路徑**（使用者要求開啟的那個路徑）。不可從開啟後的文件讀取：用 `DetachAndPreserveWorksets` 分離開啟的文件，`doc.PathName` 是空字串；空路徑會被拒絕。

**範圍檔**（`write_scope_csv`，每個模型一份）：`tool_version, run_time, model_file, check, examined, pass, fail, unverified, note`

- 每個檢查項目一列，`examined` 是實際檢查的元件數。**每個被檢查的元件，對該檢查恰好一筆結果**，所以 `pass + fail + unverified = examined`；「沒有結果」不會被當成通過。
- 「沒有問題」（examined > 0，fail = 0）和「沒有檢查」（examined = 0，且必須有 `note` 說明原因）因此可以區分。
- 模型層級的檢查（`element_id` 空白）：`examined = 1`，恰好一筆結果。
- 輸出器在以下情況拒絕寫入、不留檔：結果的檢查項目沒有對應範圍；同一檢查項目有兩筆範圍；元件層級檢查的結果筆數不等於 `examined`（漏送或同一元件送兩筆）；模型層級與元件層級混在同一檢查；`examined > 0` 卻沒有任何結果。
- **完整性只在走 `write_scope_csv` 時成立**；`write_findings_csv` 不驗證完整性。
- 同一元件有多個原因時合併成一筆 Finding。
- 大模型每元件每檢查一列（含 PASS），結果檔會很大；目前採此設計，是否接受由使用者決定。
- 計數口徑（例如「設備編號重複」：每個涉及的元件各一筆 FAIL）見 [docs/unverified_policy.md](docs/unverified_policy.md)。

## 讀回 CSV 的注意事項

- 以 `= + - @` 開頭的文字會被加上 `'`，避免 Excel 當成公式執行。Excel 會把這個撇號顯示出來；用程式讀回時，請去掉文字欄位開頭的 `'`。
- 目標 CSV 正被 Excel 開著時，寫入會失敗並拋出 `PermissionError`（`filename` 屬性為目標路徑，訊息說明請關閉 Excel）；舊報告維持不變，不會留下暫存檔。

## 尚未驗證

- 套件能否在 Dynamo 的 Python 節點中 import。
- `ElementId.Value` / `IntegerValue` 的版本說明憑記憶寫成，未查 Autodesk 文件。
- 未用 Excel 實際開啟過這些 CSV。
- 多模型彙總報告尚未設計（範圍檔目前每個模型一份）。

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
