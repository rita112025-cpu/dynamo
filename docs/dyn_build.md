# 完整度檢查 Dynamo 節點（建置說明與驗收清單）

狀態：**清單 1–4、6 已通過（2026-11-09 上午，使用者在 Revit 2025.5 + Dynamo 3.3.2.11986 中於空白專案「專案1」執行；產物 `out/完整度檢查_20261109-104100.dyn`，SHA-256 `b6143d78084f041f6cc34c811fe72cf451215f1ac17f904a1c18aff4bb82e4a5`，使用者未存檔，事後雜湊仍相同）。清單 5 未做。**

注意：這次只驗證了「快照 JSON → 完整度檢查 → CSV」的路徑，輸入是**假快照**。**不得寫成「Revit 模型檢查已驗證」。**

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

## AST 檢查：護欄，不是安全沙箱

`tools/dyn_checks.py` 以 AST 檢查程式結構，分兩級：

- **基本規則**（節點程式與模組）：禁止 Revit API 匯入與名稱（`clr`、`RevitAPI`、`Transaction`、`Document` 等）、
  禁止寫入或持久化文件的呼叫（`Save`、`SaveAs`、`SynchronizeWithCentral`、`Delete`、`Commit` 等）。
- **嚴格規則**（僅 `mep_toolkit` 模組原始碼）：另禁止 `__import__`、`importlib`、`builtins`、`eval`、`exec`、內建 `compile`；
  `getattr`／`setattr`／`delattr`／`hasattr` 只允許名稱為**非禁止的字串常數**，名稱為變數或禁止名稱時一律違規。

注意：`re.compile(...)` 是正規表示式建構子，不是內建 `compile()`，**不視為違規**（`mep_toolkit` 的 `dictionary.py`、`completeness.py` 使用它）。
若要改為禁止，需改寫這兩處，請使用者決定。

**這些檢查是防意外的護欄，不是安全沙箱。** 靜態檢查無法防止刻意的繞過；它的目的是攔住無心的 Revit 呼叫、
動態取用屬性與動態執行程式碼。真正的隔離不由此檔提供。

## 輸入（兩個字串節點，建置時留空）

**未設為 Dynamo 輸入（`IsSetAsInput` 為 false，且頂層 `Inputs` 為空）。** 原因：本專案中所有既有 Dynamo 3.3 存檔都沒有「已設為輸入」的節點，
無法確認實際格式，因此不憑猜測寫入。日後若要讓 Dynamo Player 以輸入欄位顯示，需以實際存檔格式為準再處理。
目前使用方式：在 Dynamo 中直接填寫兩個字串節點，或在建置前修改 `.dyn` 內的 `InputValue`（不建議，會影響可重現性）。

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

## 手動驗收清單與結果（Revit 2025.5 + Dynamo 3.3.2.11986，2026-11-09 上午）

使用者於空白專案「專案1」執行。

- [x] 1. 開啟 `out/完整度檢查_20261109-104100.dyn`，載入無錯誤（截圖）。Dynamo 日誌僅有既有的 AlsoKnownAs InvalidOperationException 啟動雜訊（前日日誌亦有），與此檔無關。
- [x] 2. Python 節點引擎為 CPython3（節點標示 CPython3）。實際 Dynamo 版本 3.3.2.11986，與 .dyn 記錄一致。
- [x] 3. 兩個字串節點留空時執行：警告「Exception : NOT RUN: fill in IN[0] with the full path of the snapshot JSON.」，回溯行號 116 / 72 與範本一致，Result 為 null，未產生任何檔案。
- [x] 4. 以**假快照**（`examples/sample_snapshot.json`，v2，15 個元件）填入 IN[0]，IN[1] 指向一個已存在的測試資料夾，執行通過：
  - [x] 4a. Watch 顯示工具版本、核心 SHA-256 `3b96f7c5…8fc5`、字典 SHA-256 `586d810c…24b1`、self-check OK、15 個元件、17 筆結果、未涵蓋品類。
  - [x] 4b. 產生兩份 CSV（結果 17 列、範圍 10 列）。審核方以核心、同一輸入與同一執行時間重算，兩份 CSV 逐位元組相同。
  - [ ] 4c. 再執行一次：第一次的 CSV 未被改動。（本次紀錄未包含此項；自動測試 `test_second_run_never_overwrites_the_first_output` 已涵蓋。）
- [ ] 5. 竄改測試（可選）：**未做**。Dynamo 內未執行；已在 Python 3.9.12 自動測試與審核方獨立測試中驗證自檢拒絕。
- [x] 6. 節點未動 Revit 文件（設計上不碰文件；使用者在空白專案執行）。

## 未驗證（請勿當成已驗證）

以下項目**尚未驗證**，照實記錄：

- 讀取 Revit 模型的 reader 尚未實作；快照契約未經真實 Revit 資料驗證。本次只用假快照。
- `IsReadOnly` 判定方式未實測。
- 用 Excel 開啟 CSV 未驗證。
- 清單 5 竄改測試未在 Dynamo 內做（僅 Python 3.9.12 自動測試與審核方獨立測試驗證）。
- Dynamo Player 未設為輸入（見上文「輸入」）。
- 適用族群（`OST_ElectricalEquipment` 且名稱含 `SCADA_機櫃`）為推定，未在 Revit 內確認。
- 三個淨距參數（前方／後方淨距、淨距依據）仍待確認、不檢查。
- 2500 mm 條款原文待核對；50 mm 與 1 mm 為提案值。
- 共用參數檔版次（審核方所述 10/28 版，本次只核對檔案雜湊）。
- 規範值（50 mm、1 mm、2500 mm）不在本節點的判定範圍（M4 才使用）。

已證實（2026-11-09 Dynamo 實機）：Dynamo 3.3.2 載入此 .dyn；CPython3 節點中嵌入模組註冊並執行，輸出與核心一致。

## 第二輪（EngineName、嚴格 AST 規則、輸入格式）的結果

- 節點欄位：移除 `EngineName`，Python 節點鍵集合與參考存檔相同（測試 `test_python_node_keys_match_the_reference_dynamo_file`）。
- 嚴格 AST 規則套用於 `mep_toolkit` 模組原始碼，目前所有模組通過（無違規）。節點範本的 `exec(compile(...))` 註冊邏輯只套用基本規則。
- 輸入節點：未設為輸入（見上文），測試 `test_input_nodes_are_not_set_as_inputs_because_no_reference_exists`。
- 產物：`out/完整度檢查_20261109-104100.dyn`，sha256 `b6143d78084f041f6cc34c811fe72cf451215f1ac17f904a1c18aff4bb82e4a5`。
  兩次獨立建置位元組相同（已驗證）。核心 SHA-256 `3b96f7c5175cddfafd3e7bb7ef235b6946e9b1e2294481fd62c05b50262a8fc5`，字典 SHA-256 `586d810cd34e85834f66ccf56428c022a1325951cafe649f932b4a33ee5e24b1`（與前一版相同，因為模組與字典未變，只有 .dyn 外殼少了 EngineName）。
- 舊產物 `完整度檢查_20261109-103501.dyn` 含 EngineName，已自 `out/` 移除（它是建置工具產生的，不是使用者資料）。
