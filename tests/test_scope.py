import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from mep_toolkit import TOOL_VERSION
from mep_toolkit.csv_report import SCOPE_COLUMNS, write_scope_csv
from mep_toolkit.findings import CheckScope, Finding, Status

RUN_TIME = datetime(2026, 11, 9, 10, 30, 0, tzinfo=timezone(timedelta(hours=8)))
MODEL = r"D:\models\FAKE-ESC-A.rvt"


class CheckScopeTest(unittest.TestCase):
    def test_valid(self):
        s = CheckScope("c", 5)
        self.assertEqual((s.check, s.examined, s.note), ("c", 5, ""))

    def test_zero_examined_needs_note(self):
        with self.assertRaises(ValueError):
            CheckScope("c", 0)
        with self.assertRaises(ValueError):
            CheckScope("c", 0, "  ")
        self.assertEqual(CheckScope("c", 0, "模型沒有電纜架").examined, 0)

    def test_bad_values(self):
        for check, examined in (("", 1), (" ", 1), (None, 1), ("c", -1), ("c", 1.0), ("c", True), ("c", "1")):
            with self.subTest(check=check, examined=examined):
                with self.assertRaises(ValueError):
                    CheckScope(check, examined)

    def test_note_must_be_string(self):
        with self.assertRaises(ValueError):
            CheckScope("c", 1, None)


class ScopeCsvTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "scope.csv")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, scopes, findings):
        return write_scope_csv(self.path, scopes, findings, MODEL, RUN_TIME)

    def rows(self):
        with open(self.path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.reader(fh))

    def test_counts_per_check(self):
        n = self.write(
            [CheckScope("a", 4), CheckScope("b", 2)],
            [
                Finding("a", Status.PASS, 1),
                Finding("a", Status.PASS, 2),
                Finding("a", Status.FAIL, 3, "x"),
                Finding("a", Status.UNVERIFIED, 4, "y"),
                Finding("b", Status.PASS, 1),
            ],
        )
        self.assertEqual(n, 2)
        rows = self.rows()
        self.assertEqual(tuple(rows[0]), SCOPE_COLUMNS)
        base = [TOOL_VERSION, "2026-11-09T10:30:00+08:00", "FAKE-ESC-A.rvt"]
        self.assertEqual(rows[1], base + ["a", "4", "2", "1", "1", ""])
        self.assertEqual(rows[2], base + ["b", "2", "1", "0", "0", ""])

    def test_nothing_wrong_and_nothing_checked_are_distinguishable(self):
        self.write(
            [CheckScope("clean", 12), CheckScope("empty", 0, "模型沒有電纜架")],
            [],
        )
        rows = self.rows()
        self.assertEqual(rows[1][3:], ["clean", "12", "0", "0", "0", ""])
        self.assertEqual(rows[2][3:], ["empty", "0", "0", "0", "0", "模型沒有電纜架"])

    def test_finding_without_scope_rejected_and_no_file(self):
        with self.assertRaisesRegex(ValueError, "no scope"):
            self.write([CheckScope("a", 1)], [Finding("other", Status.PASS, 1)])
        self.assertEqual(os.listdir(self.dir), [])

    def test_duplicate_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.write([CheckScope("a", 1), CheckScope("a", 2)], [])
        self.assertEqual(os.listdir(self.dir), [])

    def test_more_elements_than_examined_rejected(self):
        with self.assertRaisesRegex(ValueError, "examined only 1"):
            self.write(
                [CheckScope("a", 1)],
                [Finding("a", Status.PASS, 1), Finding("a", Status.PASS, 2)],
            )
        self.assertEqual(os.listdir(self.dir), [])

    def test_several_findings_on_one_element_count_once_as_examined(self):
        self.write(
            [CheckScope("a", 1)],
            [Finding("a", Status.FAIL, 7, "x"), Finding("a", Status.FAIL, 7, "y")],
        )
        self.assertEqual(self.rows()[1][3:8], ["a", "1", "0", "2", "0"])

    def test_model_level_finding_does_not_need_an_element(self):
        self.write([CheckScope("a", 1)], [Finding("a", Status.UNVERIFIED, None, "z")])
        self.assertEqual(self.rows()[1][3:8], ["a", "1", "0", "0", "1"])

    def test_wrong_types_rejected(self):
        with self.assertRaises(TypeError):
            self.write(["a"], [])
        with self.assertRaises(TypeError):
            self.write([CheckScope("a", 1)], ["x"])

    def test_note_formula_neutralised(self):
        self.write([CheckScope("a", 1, "=1+1")], [])
        self.assertEqual(self.rows()[1][8], "'=1+1")


if __name__ == "__main__":
    unittest.main()
