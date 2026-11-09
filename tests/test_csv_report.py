import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from core import TOOL_VERSION
from core.csv_report import COLUMNS, safe_text, write_findings_csv
from core.findings import Finding, Status

TAIPEI = timezone(timedelta(hours=8))
RUN_TIME = datetime(2026, 11, 9, 10, 30, 0, tzinfo=TAIPEI)


class CsvReportTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "report.csv")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def read_rows(self):
        with open(self.path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.reader(fh))

    def write(self, findings, **kw):
        kw.setdefault("model_file", r"D:\models\TEST-ESC-A.rvt")
        kw.setdefault("run_time", RUN_TIME)
        return write_findings_csv(self.path, findings, **kw)

    def test_header_and_rows(self):
        n = self.write([
            Finding("服務類型必填", Status.PASS, 101),
            Finding("服務類型必填", Status.FAIL, 102, "服務類型為空"),
            Finding("工作集", Status.UNVERIFIED, None, "工作集未開啟"),
        ])
        self.assertEqual(n, 3)
        rows = self.read_rows()
        self.assertEqual(tuple(rows[0]), COLUMNS)
        self.assertEqual(rows[1], [TOOL_VERSION, "2026-11-09T10:30:00+08:00", "TEST-ESC-A.rvt",
                                   "101", "服務類型必填", "PASS", ""])
        self.assertEqual(rows[2][3:], ["102", "服務類型必填", "FAIL", "服務類型為空"])
        self.assertEqual(rows[3][3:], ["", "工作集", "UNVERIFIED", "工作集未開啟"])

    def test_file_starts_with_bom_for_excel(self):
        self.write([Finding("c", Status.PASS, 1)])
        with open(self.path, "rb") as fh:
            self.assertTrue(fh.read().startswith(b"\xef\xbb\xbf"))

    def test_empty_findings_writes_header_only(self):
        self.assertEqual(self.write([]), 0)
        self.assertEqual(self.read_rows(), [list(COLUMNS)])

    def test_special_characters_round_trip(self):
        reason = 'a, "b"\nc'
        self.write([Finding("c", Status.FAIL, 1, reason)])
        self.assertEqual(self.read_rows()[1][6], reason)

    def test_formula_text_is_neutralised(self):
        self.write([Finding("=check", Status.FAIL, -1, "=HYPERLINK(\"x\")")])
        row = self.read_rows()[1]
        self.assertEqual(row[3], "-1")  # element ids are numbers, not text: untouched
        self.assertEqual(row[4], "'=check")
        self.assertEqual(row[6], "'=HYPERLINK(\"x\")")

    def test_safe_text(self):
        for raw in ("=1", "+1", "-1", "@a", "\tx", "\rx"):
            with self.subTest(raw=raw):
                self.assertEqual(safe_text(raw), "'" + raw)
        self.assertEqual(safe_text("SCADA"), "SCADA")
        self.assertEqual(safe_text(""), "")

    def test_default_run_time_is_timezone_aware(self):
        self.write([Finding("c", Status.PASS, 1)], run_time=None)
        stamp = self.read_rows()[1][1]
        self.assertIsNotNone(datetime.fromisoformat(stamp).tzinfo)

    def test_naive_run_time_rejected_and_no_file(self):
        with self.assertRaises(ValueError):
            self.write([Finding("c", Status.PASS, 1)], run_time=datetime(2026, 11, 9))
        self.assertEqual(os.listdir(self.dir), [])

    def test_empty_model_file_rejected(self):
        with self.assertRaises(ValueError):
            self.write([Finding("c", Status.PASS, 1)], model_file=" ")

    def test_bad_item_keeps_existing_report(self):
        self.write([Finding("c", Status.PASS, 1)])
        with open(self.path, "rb") as fh:
            before = fh.read()
        with self.assertRaises(TypeError):
            self.write([Finding("c", Status.PASS, 2), "not a finding"])
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(os.listdir(self.dir), ["report.csv"])

    def test_write_error_leaves_no_temp_file(self):
        bad_path = os.path.join(self.dir, "missing_dir", "report.csv")
        with self.assertRaises(OSError):
            write_findings_csv(bad_path, [], "m.rvt", RUN_TIME)
        self.assertEqual(os.listdir(self.dir), [])


if __name__ == "__main__":
    unittest.main()
