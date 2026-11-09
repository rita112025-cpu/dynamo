"""Validate workbook dimensions, information preservation, and isolated Dynamo output."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

import openpyxl

import excel_rack_families as excel


class ExcelFamilyTest(unittest.TestCase):
    def test_source_workbook_has_nine_cabinets_with_requested_sizes_and_information(self):
        rows = excel.read_equipment(excel.DEFAULT_WORKBOOK)
        self.assertEqual(len(rows), 9)
        self.assertEqual([(r["寬mm"], r["深mm"], r["高mm"]) for r in rows[:2]],
                         [("800", "1000", "2000")] * 2)
        self.assertEqual([(r["寬mm"], r["深mm"], r["高mm"]) for r in rows[2:]],
                         [("600", "800", "2100")] * 7)
        self.assertIn("42U", rows[0]["機櫃規格"])
        self.assertIn("汐東雲平台", rows[1]["安裝位置"])
        self.assertIn("MOXA", rows[2]["BIM設計與應用說明"])
        self.assertEqual(rows[-1]["來源列"], "10")

    def write_workbook(self, path, quantity=1, dimensions="600W x 800D x 2100H mm", duplicate=False):
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(excel.HEADERS)
        data = [1, " Test location ", "RTU", dimensions, quantity, " Test information "]
        sheet.append(data)
        if duplicate:
            sheet.append(data)
        book.save(path)
        book.close()

    def test_quantity_is_expanded_without_losing_source_information(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.xlsx"
            self.write_workbook(path, quantity=2)
            rows = excel.read_equipment(path)
        self.assertEqual([r["編號"] for r in rows], ["XLSX-001-01", "XLSX-001-02"])
        self.assertTrue(all(r["配置數量"] == "2" for r in rows))
        self.assertEqual(rows[0]["BIM設計與應用說明"], "Test information")

    def test_bad_quantity_dimensions_and_duplicate_items_stop_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.xlsx"
            for changes in ({"quantity": 0}, {"quantity": 1.5}, {"quantity": True},
                            {"dimensions": "600 x 800 x 2100"},
                            {"dimensions": "0W x 800D x 2100H mm"}, {"duplicate": True}):
                with self.subTest(changes=changes):
                    self.write_workbook(path, **changes)
                    with self.assertRaises(ValueError):
                        excel.prepare(path, Path(directory) / "out")
                    self.assertFalse((Path(directory) / "out").exists())

    def test_generated_graph_is_self_contained_and_has_no_project_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rows = excel.prepare(excel.DEFAULT_WORKBOOK, output)
            graph = json.loads((output / "SCADA_Racks_Excel.dyn").read_text(encoding="utf-8"))
            source = (output / "excel_rack_runtime.py").read_text(encoding="utf-8")
            with (output / "SCADA_Racks_Excel.csv").open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream)), rows)
            script = next(node for node in graph["Nodes"] if "Code" in node)
            self.assertEqual(script["Code"], source)
            self.assertEqual(len(script["Inputs"]), 2)
            self.assertEqual(len(graph["Connectors"]), 3)
            self.assertEqual(len(graph["Nodes"]), 4)
            self.assertNotIn("delete_previous_racks", source)
            self.assertNotIn("NewProjectDocument", source)
            self.assertIn("SCADA_Excel_SharedParameters.txt", source)
            compile(source, "runtime", "exec")
            ports = {p["Id"] for n in graph["Nodes"] for kind in ("Inputs", "Outputs") for p in n[kind]}
            for link in graph["Connectors"]:
                self.assertIn(link["Start"], ports)
                self.assertIn(link["End"], ports)


if __name__ == "__main__":
    unittest.main()
