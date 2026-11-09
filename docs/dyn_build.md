# 完整度檢查 Dynamo 節點（建置說明與驗收清單）

狀態：**程式與自動測試已完成；Dynamo 實機載入與執行尚未驗證，待使用者在 Dynamo 確認。**

## 這是什麼

`tools/make_dyn.py` 產生一支**單檔、可攜**的 Dynamo `.dyn`（CPython3 Python 節點）。
節點讀取一份快照 JSON，執行 `mep_toolkit` 的完整度檢查，寫出**範圍檔**與**結果檔**兩份 CSV。
它不含任何 Revit API，不開啟任何 RVT 模型。

## 建置

```bash
python tools/make_dyn.py            # 寫入 out/完整度檢查_<時間戳>.dyn（out/ 不納入版控）
python tools/make_dyn.py -o <資料夾>  # 指定資料夾（不可是既有的 Dynamo 工具資料夾）
```

- 檔名的時間戳只出現在檔名。**同樣的來源，兩次建置的 .dyn 內容逐位元組相同**（節點 id 由內容雜湊以 uuid5 衍生，不含隨機值）。
- 同名的 .dyn **不會被覆寫**；建置拒絕。
- 拒絕寫入既有的 Dynamo 工具資料夾（`批次填參數`、`批次複製視圖樣板`、`批次參數工具`、`批次工作集`、`Excel參數同步`）。
- 生成的 .dyn 不含任何磁碟機路徑或建置機器路徑（建置時檢查，發現即拒絕寫入）。

## 嵌入內容

| 項目 | 內容 | 如何確認 |
|---|---|---|
| `mep_toolkit` 原始碼 | 8 個模組的原始碼文字，節點執行時註冊為真正的模組（不改寫 import） | 測試 `test_embedded_modules_equal_the_files_on_disk` |
| 參數字典 | `config/parameter_dictionary.json` 的文字 | 測試 `test_embedded_dictionary_equals_the_config_file` |
| 核心雜湊 | 模組原始碼的 SHA-256（建置時寫入） | 節點執行時重算，不符即報錯 |
| 字典雜湊 | 字典文字的 SHA-256（建置時寫入） | 同上 |

節點執行時先**自檢**嵌入內容，與建置時寫入的雜湊相符才繼續；不符就明確報錯並不寫任何檔案。

## 輸入（兩個字串節點，建置時留空）

| 輸入 | 必填 | 規則 |
|---|---|---|
| `IN[0]` 快照 JSON 完整路徑 | 是 | 留空 → 明確報錯「NOT RUN」；檔案不存在 → 報錯 |
| `IN[1]` 輸出資料夾完整路徑 | 是 | 留空 → 明確報錯；資料夾不存在 → 報錯，**不自動建立** |

## 輸出

- Watch 節點顯示（`OUT`）：工具版本、核心 SHA-256、字典 SHA-256、自檢結果、快照來源、元件數、執行時間、兩份檔案的完整路徑、列數、未涵蓋品類。
- 兩份 CSV（UTF-8 BOM）：`completeness_scope_<時間戳>.csv`、`completeness_findings_<時間戳>.csv`。
  - 檔名已存在 → 拒絕覆寫，報錯。
  - 兩份一起寫入（`write_reports_atomic`），失敗時兩份都維持舊狀態（見 `docs/M3_acceptance.md`）。

## 自動驗收（已完成，於 `tests/test_dyn_build.py`）

| 項目 | 證據 |
|---|---|
| AST 禁止詞：真正的呼叫、匯入會被抓到；註解、docstring、字串中的同名字不誤判 | `AstRuleTest` |
| 嵌入模組、字典與檔案一致；雜湊與內容相符 | `EmbeddedContentTest` |
| 兩次建置位元組相同；檔名帶時間戳、內容無建置時間 | `BuildTest` |
| 拒絕覆寫既有 .dyn；拒絕既有 Dynamo 工具資料夾；拒絕相對路徑 | `BuildTest` |
| .dyn 不含磁碟機路徑或建置機器路徑 | `test_no_drive_letter_or_build_path_in_the_dyn` |
| 節點在 Dynamo 內建 Python 3.9.12 實際執行（隔離程序、空工作資料夾，無法 import 專案目錄） | `NodeRunTest` |
| 節點輸出的 CSV 與「核心直接呼叫」（同快照、同字典、同執行時間）**逐位元組相同** | `test_node_output_is_byte_identical_to_calling_the_core_directly` |
| 快照或輸出資料夾留空 → 明確提示；資料夾不存在 → 不建立 | `NodeRunTest` |
| 第二次執行不覆寫第一次的輸出 | `test_second_run_never_overwrites_the_first_output` |
| 竄改嵌入的核心或字典 → 自檢拒絕執行 | `test_tampered_*` |

## 手動驗收清單（待使用者在 Revit 2025 + Dynamo 3.3 中執行）

以下項目**未在本專案內驗證**，請使用者逐項確認並記錄結果：

- [ ] 1. 在 Revit 2025 的 Dynamo 3.3 中開啟 `out/完整度檢查_<時間戳>.dyn`，無載入錯誤。
- [ ] 2. 確認 Python 節點的引擎為 CPython3，且節點可執行（Dynamo 版本號會在 .dyn 中記錄為 3.3.2.11986，請確認實際版本）。
- [ ] 3. 兩個字串節點留空時執行：Watch 或錯誤訊息顯示「NOT RUN」並指出 IN[0]／IN[1]。
- [ ] 4. 以**假快照**（例如 `examples/sample_snapshot.json`，v2）填入 IN[0]，IN[1] 指向一個已存在的測試資料夾，執行：
  - [ ] 4a. Watch 顯示工具版本與兩個 SHA-256，與 `out/` 中建置時的紀錄一致（見 `python tools/make_dyn.py` 的輸出）。
  - [ ] 4b. 產生兩份 CSV，內容與 `examples/sample_completeness_*.csv` 的規則一致（列數：結果 17、範圍 10）。
  - [ ] 4c. 再執行一次：第一次的 CSV 未被改動。
- [ ] 5. 竄改測試（可選）：用文字編輯器改動 .dyn 內的核心原始碼一個字元後執行，應被自檢拒絕。
- [ ] 6. 確認節點未呼叫任何 Revit 文件物件（本節點設計上不會；可由程式碼 AST 測試佐證，但實機行為需使用者確認）。

## 未驗證（請勿當成已驗證）

- Dynamo 3.3 實際載入此 .dyn、CPython3 節點執行（僅以內建 Python 3.9.12 的獨立程序驗證）。
- 套件內嵌模組在 Dynamo 節點中以 `sys.modules` 註冊後的行為（僅於獨立程序驗證）。
- 快照契約的實際來源（Revit reader 尚未實作，快照目前為假資料）。
- 共用參數檔版次（審核方所述 10/28 版，本次只核對檔案雜湊）。
- 規範值（50 mm、1 mm、2500 mm）仍為暫定值，且不在本節點的判定範圍（M4 才使用）。
