# 碰撞追蹤（Navisworks Clash → 站別／系統／處理狀態）

把 Navisworks Clash Detective 的碰撞結果整理成送審用追蹤表。流程參考
[lejla-adsk/Navisworks-2025-Clash-Data-Exporter](https://github.com/lejla-adsk/Navisworks-2025-Clash-Data-Exporter)
（走訪 `DocumentClash.TestsData` → `ClashTest` → `ClashResultGroup`/`ClashResult`），
沒有複製其原始碼（該 repo 未見授權條款），並修正其弱點：`^` 分隔無跳脫、寫死樹深度、
每列相同的網格範圍。

## 流程

```
Navisworks ──(A) Clash Detective > 報告 > XML ──┐
           └─(B) NavisworksPlugin 匯出 CSV ─────┤
                                                ▼
                       clash_tracker.py  +  clash_config.json
                                                ▼
                 碰撞追蹤表.xlsx（明細／摘要） + 同名 .csv（Power BI）
```

**不需要編譯外掛即可使用**：路徑 A 用 Navisworks 內建 XML 報告。外掛（路徑 B）可多帶
指派人、核可者、物件路徑等欄位。

## 使用

```powershell
python clash_tracker.py SB12_碰撞.xml SB14_碰撞.xml -o 碰撞追蹤表.xlsx
python -m pytest tests -q
```

- 只需 Python 3 與 `openpyxl`。
- 同一輸出檔重跑時，**人工欄位（負責人／送審狀態／備註）依碰撞 ID（GUID）自動帶回**；`--no-carry` 可關閉。
- 輸出明細欄位：站別、系統A/B、系統組合、Navisworks 狀態、處理狀態、距離、網格位置、XYZ、物件、檔案、指派、核可、建立時間。
- 「摘要」頁：站別 × 系統組合 × 處理狀態 計數與未結案數。

## 分類規則（`clash_config.json`）

| 項目 | 判斷依據 |
|---|---|
| 站別 | 測試名稱／檔名／路徑中的站代號（預設 regex `S[A-Z]\d{1,2}`，如 SB12、SB14），其次汐止／東湖 |
| 系統 | 先看模型檔名（EL/ME/PL/ST/AR/SIG…），再看路徑與物件名；SCADA 關鍵字優先 |
| 處理狀態 | new→待處理、active→處理中、reviewed→已審閱、approved→已核可、resolved→已解決；待處理＋處理中算未結案 |

規則依序比對、第一個命中者生效。**預設規則是依檔名慣例推測的範例，請用實際檔名調整**，
比對不到會標「未分類」，方便檢查。

## 外掛（選用，未編譯驗證）

[`NavisworksPlugin/ClashCsvExport.cs`](NavisworksPlugin/ClashCsvExport.cs)：.NET Framework 4.8，
引用 Navisworks 2025 安裝目錄的 `Autodesk.Navisworks.Api.dll`、`Autodesk.Navisworks.Clash.dll`，
編譯後放進 `Plugins\ClashTrackerExport\`。此環境沒有 Navisworks SDK，所以**只做了 Python 端測試**；
外掛的 API 成員名稱（如 `GridIntersection`、`ApprovedTime`、`Model.SourceFileName`）請在第一次編譯時對照 2025 SDK 確認。

## 限制

- XML 格式依 Navisworks 標準報告結構解析，未用真實專案 XML 驗證，第一次請拿一份實檔跑跑看並回報欄位缺漏。
- 不寫回 Navisworks（狀態以 Navisworks 為準，追蹤表只讀）。
