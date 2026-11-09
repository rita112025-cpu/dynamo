# M3 驗收表（第二輪）

日期：2026-11-09。依審核方 R1–R5 與使用者的驗收要求逐項記錄。每一列都對應到測試或檔案；未完成者明確標示。

## 結論

M3 **尚未正式放行**：建置腳本（M3 後段）未做；Revit／Dynamo 實機未驗證；待確認事項仍有數項。
本輪完成的是 R1–R5 與 R2 原子寫入的程式與測試。

## 各項結果

| 項目 | 證據（檔案 / 測試） | 結果 |
|---|---|---|
| **R1 字典 ↔ 共用參數檔（雙向）** | `mep_toolkit/shared_params.py`、`dictionary.verify_against_shared_file`；`tests/test_shared_consistency.py` | 通過。正向：名稱→GUID、GUID→名稱、型別、重現來源位元組（sha256 相符）。負向（每項都被偵測）：字典多出、字典少了、檔案多出、字典 GUID 被改、檔案 GUID 被改、兩 GUID 互換、型別不同、檔案內容變動、群組不符、無 BOM、無 PARAM 行 |
| R1 GUID 格式、唯一、型別、名稱 | `tests/test_dictionary.py::SharedParameterTest` | 通過 |
| **R2 兩份報告原子寫入（備份與還原）** | `mep_toolkit/csv_report.py::write_reports_atomic`；`tests/test_atomic_reports.py` | 通過（見下方「R2 限制」） |
| R2 第二份替換失敗 → 兩份位元組與原本相同、無殘留 | `test_second_replacement_fails_both_old_bytes_restored` | 通過 |
| R2 第一份替換失敗 → 兩份不變 | `test_first_replacement_fails_both_old_bytes_unchanged` | 通過 |
| R2 兩份都成功 → 都是新的、無殘留 | `test_both_replaced_when_both_succeed` | 通過 |
| R2 真實檔案鎖定（Windows，未跳過） | `test_real_locked_findings_file_keeps_both_old` | 通過 |
| R2 回滾也失敗 → 明確指出哪個檔案要人工檢查 | `test_rollback_that_cannot_restore_says_which_file` | 通過 |
| **R3 未涵蓋品類寫入範圍檔** | `tests/test_completeness.py::UncoveredCategoryTest` | 通過：範圍列 examined=0，note 寫「未涵蓋品類 OST_Walls：N 個元件未檢查」，並出現在寫出的 CSV 中 |
| **R4 Snapshot v2：三種狀態** | `mep_toolkit/snapshot.py`；`docs/snapshot_format.md` | 通過（見下表） |
| R4 v1 被拒絕（真實 v1 檔） | `tests/test_snapshot.py::test_real_v1_file_is_rejected_and_says_version_2`（`examples/legacy/sample_snapshot_v1.json`） | 通過，訊息指出需要 version 2 |
| R4 v2 正常載入 | `test_v2_sample_loads` | 通過 |
| R4 缺欄位、null、read_only 不合規 | `tests/test_snapshot.py` | 通過 |
| **R4 缺參數 → FAIL** | `test_missing_parameter_is_fail_with_its_own_reason` | 通過 |
| **R4 唯讀且值正確 → PASS** | `test_read_only_correct_value_passes` | 通過 |
| **R4 唯讀且值錯 → FAIL 並註明唯讀** | `test_read_only_wrong_value_fails_and_says_it_cannot_be_fixed` | 通過 |
| **R4 讀取失敗 → UNVERIFIED** | `test_read_error_is_unverified_with_exception_text` | 通過 |
| **R5 規則來源標示為推定** | 設定檔 `rack.basis.status` 只接受「依既有程式推定，非業主確認」；`docs/parameter_dictionary.md` 表格 | 通過（`tests/test_dictionary.py::BasisTest`） |
| R5 三個淨距參數維持待確認、不檢查、不補造 GUID | 設定檔 `pending_confirmation`；文件 #1 | 通過 |

## R4 三種狀態的判定對照

| 狀態 | 快照表示 | 判定 | reason |
|---|---|---|---|
| MISSING_PARAMETER | 名稱不在 `parameters` | FAIL | 模型沒有此參數（MISSING_PARAMETER） |
| READ_ONLY，值正確 | 在 `parameters`，且列於 `read_only_parameters` | PASS | — |
| READ_ONLY，值錯或空 | 同上 | FAIL | 註明「唯讀，批次工具無法修正」並附現值 |
| UNREADABLE | `read_error` 非空，`parameters` 為空 | UNVERIFIED | 附例外文字 |

## R2 限制（誠實說明）

`write_reports_atomic` 不是跨檔案的交易。它保證：正常錯誤（鎖定、權限、替換失敗）之後，兩份檔案都是舊的或都是新的；
若回滾本身失敗，會拋出 RuntimeError 指出要人工檢查的檔案。**不保證**：程式在兩次替換之間被強制終止（例如斷電）時的狀態；
該情況下可能留下 `.bak` 備份檔，需人工處理。

## 次要項目

- `docs/snapshot_format.md` 的 JSON 範例已以解析器驗證為合法 JSON。
- 設定檔的 `sources` 與 `shared_parameters.source` 已改為檔名；完整路徑移到 `docs/parameter_dictionary.md`。
- 2500 mm 門檻的 `applies_to` 改為「水平橋架（電纜架水平段）」。條款位置與原文措辭仍標「待核對原文」（見 `docs/M2_spec.md` 第 8 節）。

## 驗證

- pytest 3.12：**195 passed, 156 subtests passed**，退出碼 0，`-rs` 無任何 skip。
- Dynamo 內建 Python 3.9.12，`python -W error::ResourceWarning -m unittest discover`：**Ran 195 tests … OK**，退出碼 0。
- toolkit 以外的既有檔案（10 個 `.dyn`／`.py` 加 2 個步驟說明文件，共 12 個）：下表逐檔比對施作前基準。

| 檔案（toolkit 以外） | SHA-256 | 與基準 |
|---|---|---|
| Dynamo批次處理_步驟說明.md | `cc8b14e5df223eb9c8c6c3af457296fead1e59931ef53aeb67fa00913af9c3ba` | MATCH |
| Dynamo批次處理_步驟說明.pdf | `c69d68e2c861204636befdaa078a68180bb4ab9ab56f9d0c2f50a7ac21af10fd` | MATCH |
| Excel參數同步/ExcelRevitSync.dyn | `b74e25dae1cf6f877b8fb7b84bff9cb64a79fc1bfc71651e9c91bbe5921c0451` | MATCH |
| Excel參數同步/ExcelRevitSync.py | `0c4816c87a57b8475b6cb1964a8082a1b73fdc29fef22238c4b7cc50a338e986` | MATCH |
| 批次參數工具/BatchParamTools.dyn | `8ece0c62043d9d79e17d63dd3df36d8be89fa42c3f59d7fee1376ac2ef4e01d4` | MATCH |
| 批次參數工具/BatchParamTools.py | `0be9e56629c69f26a2260da51fc6c8e6686ee1a3f26b64b8c356180926b3cc11` | MATCH |
| 批次填參數/BatchFillScadaParams.dyn | `5cbc3a4c44696b419c669f9c636f8160c848a0ad795607133701d280b686a521` | MATCH |
| 批次填參數/BatchFillScadaParams.py | `394dadcc1d2dc6a1c7a69fdcafbe65032603d48f829757bc66a586064c0267f1` | MATCH |
| 批次工作集/BatchWorksets.dyn | `5681081c5b3bdb4d68fc31d66cb27c1ae17bcdd764ba2c311388f208cf16d865` | MATCH |
| 批次工作集/BatchWorksets.py | `48eeffe7bb39ca1314f774301b413080d1e7ad7bf4511328bd3ca4dbf1f29105` | MATCH |
| 批次複製視圖樣板/BatchCopyViewTemplates.dyn | `9b96754c715cf15b1bba4b7dfbfeb80123156aa4f8473b39a511a1fa89b2e4cb` | MATCH |
| 批次複製視圖樣板/BatchCopyViewTemplates.py | `a4d8ea3bf346bc262a3921df2528fbbabb59128f058e62691a52135b35b1cf04` | MATCH |

## 尚未在 Revit／Dynamo 實際執行的部分

- 套件能否在 Dynamo CPython3 節點中 import。
- `IsReadOnly` 的判定方式（快照契約假設 reader 能正確區分唯讀，未實測）。
- ElementId 版本說明（`Value`／`IntegerValue`）為憑記憶，未查 Autodesk 文件。
- 快照契約在 Revit 中的實際輸出。
- 未用 Excel 實際開啟 CSV。
- 共用參數檔的版次（審核方所述 10/28 版，本次只核對檔案雜湊，未核對版次）。

## 未完成

- 新 `.dyn` 建置腳本（M3 後段）。本輪沒有產生任何 `.dyn`。
- M4 橋架檢查。
- 多模型彙總報告。
- 2500 mm 條款原文核對（待核對原文）；50 mm 與 1 mm 為提案值。

## 未解決的待確認事項

見 `docs/parameter_dictionary.md` 的「待使用者確認」清單（共 8 項）。
