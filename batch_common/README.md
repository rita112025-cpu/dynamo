# batch_common：批次腳本共用區塊

5 支批次 Dynamo 腳本共用 6 個輔助函式：`norm`、`to_list`、`doc_paths`、`SuppressWarnings`、`version_ok`、`remove_temp_local`。這些函式只維護一份，放在 [batch_common.py](batch_common.py)。

套用的腳本：`批次SCADA設定`、`批次參數工具`、`批次填參數`、`批次工作集`、`批次複製視圖樣板`。

## 為什麼不用 import

`.dyn` 會把整支腳本內嵌在 Python 節點裡，單檔就能複製給別人使用。改成執行時 import，`.dyn` 就得找得到模組路徑，可攜性會壞掉。所以改用**建置時同步**：共用區塊寫進各腳本的標記區段，再同步更新 `.dyn` 內嵌的程式碼。

```
# >>> shared: batch_common (...)
...共用區塊...
# <<< shared: batch_common
```

## 修改共用函式

1. 只改 `batch_common/batch_common.py` 中 `# --- block ---` 以下的內容，不要直接改腳本裡的標記區段。
2. 執行同步：

   ```powershell
   python batch_common/sync_shared.py
   ```

   這會更新 5 支 `.py`，以及對應 `.dyn` 中 Python 節點的 `Code`。`.dyn` 的其他內容逐位元組保持不變。
3. 檢查是否同步（沒同步時回傳 1）：

   ```powershell
   python batch_common/sync_shared.py --check
   ```

4. 依每支工具的說明，在 Revit 實機重新驗證受影響的工具。

## 不放進共用區塊的部分

`open_target`、`save` 和 `UseDestinationTypes` 各腳本的行為不同，所以留在各自的腳本裡。不同之處包括：開啟全部或關閉全部工作集、試跑時是否分離中央模型、同步註解，以及暫存檔前綴。

共用區塊需要主腳本先定義 `app`、`NS`、`fail_msgs`，並匯入 `os`、`re`、`shutil` 和 `Autodesk.Revit.DB`。標記區段必須放在 `NS` 與 `fail_msgs` 之後。

## 測試

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"; python -m pytest -q batch_common/tests
```

`test_repository_scripts_and_dyn_are_in_sync` 會確認倉庫內的腳本與 `.dyn` 都和共用區塊一致。
