# M0 分析：Dynamo 部署方式與共用函式比對

日期：2026-11-09。範圍：只讀既有腳本，未修改任何 `.dyn`、`.py`、RVT。

## 1. 環境事實（本機實測）

| 項目 | 結果 | 依據 |
|---|---|---|
| Dynamo CPython3 執行環境 | Python 3.9.12 | `%LOCALAPPDATA%\python-3.9.12-embed-amd64\python.exe` 輸出版本 |
| `.dyn` 內嵌程式碼與同名 `.py` | 完全相同（BatchFillScadaParams、BatchCopyViewTemplates） | 解析 `.dyn` JSON 的 `Code` 欄位逐字比對 |
| `.dyn` 是否從外部 import | 否，無 `sys.path` | grep |

推論（未在 Revit 內驗證）：Revit 2025 的 Dynamo 3.3 CPython3 引擎即使用上述 3.9.12。core 因此必須相容 Python 3.9（不用 `X | Y` 型別寫法、`match` 等）。

## 2. 兩種部署方式比較（本階段不決定）

| | A. 內嵌（現況） | B. 外部 import |
|---|---|---|
| 做法 | Python 節點直接存整份程式碼 | 節點內 `sys.path.append(<core 路徑>)` 後 `import core` |
| 可攜性 | `.dyn` 單檔可交給同事，Dynamo Player 直接用 | 每台電腦都要有 core，路徑一致（G: 磁碟代號、網路磁碟） |
| core 路徑來源 | 不需要 | Python 節點沒有 `__file__`，拿不到 `.dyn` 所在位置；只能寫死路徑或用輸入節點傳入 |
| 修改 core 後生效 | 立即（程式在節點內） | CPython3 引擎在同一 Revit 工作階段會保留已 import 的模組，改了 core 需重開 Revit 或 `importlib.reload`（**未實測**） |
| .NET 介面子類別（`IFailuresPreprocessor` 等） | 現有做法：每次執行用 uuid 產生新 `__namespace__` 避免重複註冊 | 放進被 import 的模組時，reload 會重新定義類別，仍需 uuid namespace；建議這類類別留在節點內（**未實測**） |
| 重複程式 | 已確認 4 支腳本各一份（見第 3 節），且已開始分歧 | 單一來源 |
| 單元測試 | 只能測抽出來的副本，無法保證與節點內容一致 | 測的就是執行的程式 |
| 版本追蹤 | `.dyn` 是 JSON，程式碼為單行跳脫字串，diff 難讀 | `.py` 正常 diff |
| 安全 | 程式碼跟著 `.dyn` 走 | 任何人改了 core 路徑上的檔案，所有 `.dyn` 執行時都會跑到 |

第三種可行做法（C，混合）：core 以 `.py` 維護並測試，用建置腳本把 core 內容寫進 `.dyn` 的 Python 節點。兼顧可攜與單一來源，但需要一支會改 `.dyn` 的工具，且要防止有人直接在 Dynamo 裡改節點造成兩邊不一致。

本階段 toolkit 的 core 為純 Python（不依賴 Revit API），A、B、C 三種方式都能使用。

## 3. 七個共用函式比對

比對方式：以 AST 比較函式本體（忽略 docstring 與格式），基準為 `批次填參數/BatchFillScadaParams.py`（Fill）。
另三支：`批次複製視圖樣板/BatchCopyViewTemplates.py`（VT）、`批次參數工具/BatchParamTools.py`（Param）、`批次工作集/BatchWorksets.py`（WS）。`Excel參數同步/ExcelRevitSync.py` 不含這些函式（只處理目前文件）。

註：Param、WS、ExcelRevitSync 是 2026-11-09 09:40 前後新增的檔案，不在原本的盤點內。

| 函式 | Fill | VT | Param | WS | 結論 |
|---|---|---|---|---|---|
| `norm` | L68 | L26 相同 | L127 相同 | L76 相同 | 可直接共用 |
| `to_list` | L72 | L30 相同 | L131 相同 | L80 相同 | 可直接共用 |
| `doc_paths` | L86 | L44 相同 | L145 相同 | L94 相同 | 可直接共用 |
| `version_ok` | L123 | L88 相同 | L182 相同 | L131 相同 | 相同，但依賴全域 `app`，共用時需改成參數 |
| `open_target` | L128 | L93 **不同** | L187 **不同** | L136 **不同** | 3 種變體，見下 |
| `remove_temp_local` | L147 | L111 相同 | L210 相同 | L158 相同 | 可直接共用 |
| `save` | L234 | L178 **不同** | L221 **不同** | L169 **不同** | 只差 Comment；WS 少了非協作檔的 `else` 分支（WS 在 L345 已先排除非協作檔，實際無影響） |
| `SuppressWarnings`（附帶） | L106 | L71 相同 | L165 相同 | L114 相同 | 本體相同，依賴全域 `fail_msgs` 與各自的 namespace |

### `open_target` 的 3 種變體

| 變體 | 腳本 | 工作集 | 協作檔 dry run | 協作檔寫入 | 暫存檔前綴 |
|---|---|---|---|---|---|
| V1 | Fill | OpenAll | DoNotDetach，中央檔會建立暫存本機檔 | 同左 | `BatchFill_` |
| V2 | VT | **CloseAll** | 不開檔 | DoNotDetach + 暫存本機檔 | `BatchVT_` |
| V3 | Param、WS | OpenAll | **DetachAndPreserveWorksets**，不建本機檔 | DoNotDetach + 暫存本機檔 | `BatchParam_`、`BatchWorkset_` |

V3 是後來的版本：dry run 時分離開啟，不會建立本機檔，也不可能同步回中央檔。V1 的 dry run 仍會呼叫 `CreateNewLocal`。

## 4. 抽取方案（提案，尚未實作）

1. **唯讀工具箱只需要 5 個**：`norm`、`to_list`、`doc_paths`、`version_ok(app, info)`、唯讀版 `open_target`。`save` 與 `SuppressWarnings` 只有寫入才用得到，先不抽。
2. 唯讀版 `open_target` 採 V3 的 dry-run 分支：協作檔一律 `DetachAndPreserveWorksets` + `OpenAllWorksets`，不建立本機檔；`remove_temp_local` 因此也用不到。
3. 這些函式都依賴 Revit API，不能放進目前的純 Python core；建議另開 `revit_io` 模組，與 `core` 分開，`core` 維持可在 Revit 外測試。
4. `to_list` 與 `norm` 是純 Python，可放進 core 並加單元測試（備份檔 `.0001.rvt` 排除規則）。
5. 既有 4 支腳本**不回頭改**。若日後要統一，另立項目，並以改寫前後 dry-run 報告逐字相同為驗收條件。
6. 若要統一 `open_target`，需先決定 V1 的 dry run 是否改成 V3 行為；這會改變既有腳本的行為（不再建立本機檔），需使用者同意。
