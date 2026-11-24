// Navisworks 2025 外掛：把 Clash Detective 全部測試的結果匯出成 CSV，供 clash_tracker.py 使用。
// 參考 lejla-adsk/Navisworks-2025-Clash-Data-Exporter 的流程（DocumentClash.TestsData → ClashTest →
// ClashResultGroup/ClashResult），但改為：UTF-8 BOM、RFC4180 引號跳脫、欄位名同 clash_tracker.ClashRow。
// 注意：此檔需在已安裝 Navisworks 2025 的機器上編譯 (.NET Framework 4.8)，本 repo 環境未編譯驗證。
// 參考 DLL（Navisworks 安裝目錄）：Autodesk.Navisworks.Api.dll、Autodesk.Navisworks.Clash.dll、
//   Autodesk.Navisworks.ComApi.dll(不需要)。
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;
using Autodesk.Navisworks.Api;
using Autodesk.Navisworks.Api.Clash;
using Autodesk.Navisworks.Api.Plugins;

namespace ClashTrackerExport
{
    [Plugin("ClashTrackerExport.Run", "SCDX", DisplayName = "匯出碰撞 CSV")]
    [AddInPlugin(AddInLocation.AddIn)]
    public class ExportCommand : AddInPlugin
    {
        private static readonly string[] Header =
        {
            "guid", "test", "name", "status", "distance", "grid", "x", "y", "z",
            "item_a", "item_b", "file_a", "file_b", "path_a", "path_b",
            "assigned_to", "approved_by", "approved_time", "created", "description"
        };

        public override int Execute(params string[] parameters)
        {
            Document doc = Autodesk.Navisworks.Api.Application.ActiveDocument;
            if (doc == null || doc.IsClear)
            {
                MessageBox.Show("請先開啟模型。");
                return 1;
            }

            using (var dlg = new SaveFileDialog
            {
                Filter = "CSV (*.csv)|*.csv",
                FileName = DateTime.Now.ToString("yyyyMMdd") + "-Clash_Data.csv"
            })
            {
                if (dlg.ShowDialog() != DialogResult.OK) return 0;
                try
                {
                    int n = Export(doc, dlg.FileName);
                    MessageBox.Show("已匯出 " + n + " 筆碰撞。");
                    return 0;
                }
                catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException)
                {
                    MessageBox.Show("寫檔失敗：" + ex.Message);
                    return 2;
                }
            }
        }

        private static int Export(Document doc, string path)
        {
            int count = 0;
            using (var sw = new StreamWriter(path, false, new UTF8Encoding(true)))
            {
                sw.WriteLine(string.Join(",", Header));
                foreach (SavedItem t in doc.GetClash().TestsData.Tests)
                {
                    var test = t as ClashTest;
                    if (test == null) continue;
                    foreach (ClashResult r in Results(test))
                    {
                        sw.WriteLine(string.Join(",", Row(test, r).Select(Csv)));
                        count++;
                    }
                }
            }
            return count;
        }

        // 結果可能被分組 (ClashResultGroup)，需展開一層。
        private static IEnumerable<ClashResult> Results(ClashTest test)
        {
            foreach (SavedItem child in test.Children)
            {
                var group = child as ClashResultGroup;
                if (group != null)
                {
                    foreach (SavedItem sub in group.Children)
                    {
                        var gr = sub as ClashResult;
                        if (gr != null) yield return gr;
                    }
                }
                else
                {
                    var r = child as ClashResult;
                    if (r != null) yield return r;
                }
            }
        }

        private static string[] Row(ClashTest test, ClashResult r)
        {
            // 已解決的碰撞 Item1/Item2 可能為 null，退回測試的選集第一個物件（與參考專案相同做法）。
            ModelItem a = r.Item1 ?? test.SelectionA.Selection.GetSelectedItems().FirstOrDefault();
            ModelItem b = r.Item2 ?? test.SelectionB.Selection.GetSelectedItems().FirstOrDefault();
            return new[]
            {
                r.Guid.ToString(), test.DisplayName, r.DisplayName, r.Status.ToString(),
                r.Distance.ToString("R"), r.GridIntersection?.ToString() ?? "",
                r.Center.X.ToString("R"), r.Center.Y.ToString("R"), r.Center.Z.ToString("R"),
                a?.DisplayName ?? "", b?.DisplayName ?? "",
                FileOf(a), FileOf(b), PathOf(a), PathOf(b),
                r.AssignedTo ?? "", r.ApprovedBy ?? "",
                r.ApprovedTime?.ToString("yyyy-MM-dd HH:mm:ss") ?? "",
                r.CreatedTime?.ToString("yyyy-MM-dd HH:mm:ss") ?? "",
                r.Description ?? ""
            };
        }

        private static string FileOf(ModelItem item)
        {
            if (item == null) return "";
            // 往上找到有來源檔名的祖先 (模型根節點)
            foreach (ModelItem anc in item.AncestorsAndSelf)
            {
                string src = anc.Model?.SourceFileName;
                if (!string.IsNullOrEmpty(src)) return Path.GetFileName(src);
            }
            return "";
        }

        private static string PathOf(ModelItem item)
        {
            if (item == null) return "";
            return string.Join(" > ", item.AncestorsAndSelf.Reverse().Select(i => i.DisplayName));
        }

        private static string Csv(string v)
        {
            if (v == null) return "";
            return v.IndexOfAny(new[] { ',', '"', '\r', '\n' }) >= 0
                ? "\"" + v.Replace("\"", "\"\"") + "\""
                : v;
        }
    }
}
