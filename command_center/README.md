# BIM Batch Command Center — 控制器核心（M1-B MVP，修正版 r1）

依 `M1A_r2_final_規格_BIM_Batch_Command_Center.md` 實作的純 Python 控制器核心。

**這一版只用模擬 Runner（`FakeRunner`）。** 不連接 Revit、Dynamo、AutoCAD，不讀寫任何正式模型，不寫回正式資料夾。

## 證明的事

1. 讀取並驗證任務契約（`schemas/task_contract.schema.json` + 語意規則）。
2. 建立唯一執行紀錄：`run_id`、`run_nonce`（`secrets`）、執行目錄、job 檔、執行紀錄帳。
3. 呼叫 Runner（目前只有 `FakeRunner`）。
4. 驗證結果檔，區分 `success`、`failed`、`skipped`、`interrupted`。

另含：備份與工作副本（工作副本只從備份複製）、鎖檔與人工解除（先認領再核對）、輸出路徑逃逸防護、Windows 原子替換重試、排他建立（`write_new_json`）、工作根目錄檢查（含實際路徑）、檔案型輸入納入指紋、唯讀且嚴格的寫回檢查 `check_promotion()`。

修正版 r1 內容見交付包 `delivery/CHANGES_R1.md`。

## 不做的事

- 沒有真實任務契約（`tasks/`）；測試只用臨時產生的測試契約。
- 沒有 CLI、GUI、Revit／Dynamo／AutoCAD Runner、心跳。
- 不寫回正式資料夾、不寫核准紀錄（`bbcc/ledger.py` 只定義並驗證核准紀錄格式）。
- 沒有拓撲排序、`after`、`any_of`；依呼叫者給的順序執行，只檢查 `requires`（須已選且在前）與 `conflicts_with`。
- 不修改儲存庫中任何既有檔案。

## 結構

```
command_center/
  README.md
  schemas/task_contract.schema.json   任務契約
  schemas/result.schema.json          結果檔
  bbcc/__init__.py                    版本
  bbcc/schema_check.py                最小 JSON Schema 驗證器（不需 jsonschema）
  bbcc/atomic.py                      原子寫入（含 Windows 重試）、SHA-256、canonical JSON
  bbcc/contracts.py                   契約載入、語意檢查、requires／conflicts
  bbcc/fingerprint.py                 input_fingerprint
  bbcc/ledger.py                      執行紀錄帳、重複執行規則、核准紀錄格式
  bbcc/locks.py                       鎖檔、疑似過期判定、人工解除
  bbcc/workspace.py                   工作根目錄、run_id、run_nonce、備份、工作副本
  bbcc/results.py                     結果驗證、狀態機、路徑逃逸、判定
  bbcc/controller.py                  Runner 介面、FakeRunner、execute、check_promotion
  tests/                              107 項測試（unittest）
```

## 判定規則摘要

| 情況 | 結果 | 是否停止整批 |
|---|---|---|
| 前置條件不成立（備份、工作副本、鎖、相依、重複執行、路徑） | `skipped` | 否；相依者也略過 |
| 使用者停止、Runner 未產生結果檔（含當機） | `interrupted` | 是 |
| 結果檔損毀、格式錯、`run_id`／`run_nonce`／指紋等不符、時間不合理、輸出路徑逃逸、輸出雜湊不符 | `failed`（`verification`） | 是 |
| 控制器自身錯誤 | `failed`（`controller_error`） | 是 |
| 任務自報失敗 | `failed`（`task_reported`） | 否；只略過相依者 |
| 任務自報成功且全部驗證通過 | `success` | — |

程序結束碼只記錄，不作為成功依據。

## 工作根目錄

預設 `%LOCALAPPDATA%\BIMBatchCommandCenter\`（`workspace.resolve_runs_root()`）。自訂路徑必須是本機絕對路徑，拒絕 UNC、網路磁碟、同步資料夾（OneDrive、Dropbox、Google Drive、My Drive、iCloudDrive、Box），以及與目標資料夾重疊的位置。

```
<runs_root>\runs\<run_id>\   plan.json run_state.json run_summary.json jobs\ backup\ work\ staging\ results\ evidence\
<runs_root>\ledger\<input_fingerprint>\<run_id>.json
<runs_root>\locks\<lock_key>.lock    locks\released\
```

## 測試

需求：Python 3.9 以上，只用標準函式庫，不需安裝套件。所有測試只在 `tempfile.TemporaryDirectory()` 內建立檔案。

在 `command_center` 資料夾執行：

```
python -B -m unittest discover -s tests -t . -v
```

Windows 以 Dynamo 內建 Python 3.9.12 執行（路徑依本機安裝而定）：

```
"%LOCALAPPDATA%\python-3.9.12-embed-amd64\python.exe" -B -m unittest discover -s tests -t . -v
```

註：embeddable Python 預設可能不把目前資料夾加入 `sys.path`；若出現 `No module named 'bbcc'`，這是環境設定問題。sessionB 回報已在 Windows 11 的 Dynamo CPython 3.9.12（embed）與 3.12.10 執行過 M1-B 初版的 87 項（86 通過、1 略過）；修正版尚未在 Windows 重跑。

## 程式範例（模擬 Runner）

```python
from bbcc import contracts, controller
registry = {"t1": contracts.load_contract(r"D:\path\t1.task.json")}
summary = controller.execute(registry, ["t1"], {"t1": {"target_folder": r"D:\copy_of_models"}},
                             "dry_run", r"C:\Users\me\AppData\Local\BIMBatchCommandCenter",
                             repo_root=r"D:\repo", runner=controller.FakeRunner())
print(summary.status("t1"))
```

`FakeRunner` 不會讀寫模型內容，只在 staging 寫一個 `report.txt` 並回報成功。

## 已知限制

- 修正版只在 Linux 容器以 Python 3.11／3.12／3.13 執行過；Python 3.9.12 與 Windows 的修正版尚未重跑（只做了 3.9 語法檢查）。
- PE-04（檔案符號連結）在沒有建立符號連結權限的 Windows 帳號（WinError 1314）會略過；PE-07 改用 junction 補上，junction 部分未在 Windows 實測。
- Windows 專屬行為以注入方式測試：`GetDriveTypeW`、`os.replace` 遇到被占用檔案的錯誤碼、junction、PID 判斷（`OpenProcess`）。實際 Windows 行為未驗證。
- 同步資料夾判斷是依名稱的啟發式，無法辨識所有同步軟體。
- 備份檔會設為唯讀；清理執行目錄需由使用者處理，控制器不自動刪除。
- 大型 RVT 的完整 SHA-256 與複製耗時未實測。
