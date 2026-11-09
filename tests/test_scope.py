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


def element_results(check, ids, status=Status.PASS, reason=""):
    return [Finding(check, status, i, reason) for i in ids]


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

    def assert_rejected(self, scopes, findings, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self.write(scopes, findings)
        self.assertEqual(os.listdir(self.dir), [])

    def test_counts_per_check_sum_to_examined(self):
        n = self.write(
            [CheckScope("a", 4), CheckScope("b", 1)],
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
        self.assertEqual(rows[2], base + ["b", "1", "1", "0", "0", ""])
        for row in rows[1:]:
            self.assertEqual(int(row[5]) + int(row[6]) + int(row[7]), int(row[4]))

    def test_all_examined_elements_have_a_result_passes(self):
        ids = range(2000, 2014)
        findings = (element_results("c", [2000], Status.FAIL, "x")
                    + element_results("c", list(ids)[1:]))
        self.write([CheckScope("c", 14)], findings)
        self.assertEqual(self.rows()[1][3:8], ["c", "14", "13", "1", "0"])

    def test_examined_14_but_only_1_result_rejected_and_no_file(self):
        self.assert_rejected(
            [CheckScope("c", 14)],
            [Finding("c", Status.FAIL, 1, "x")],
            "examined 14 elements but has 1 results",
        )

    def test_more_results_than_examined_rejected(self):
        self.assert_rejected(
            [CheckScope("a", 1)], element_results("a", [1, 2]),
            "examined 1 elements but has 2 results",
        )

    def test_same_element_twice_rejected(self):
        self.assert_rejected(
            [CheckScope("a", 2)],
            [Finding("a", Status.FAIL, 7, "x"), Finding("a", Status.FAIL, 7, "y")],
            "more than one result for element",
        )

    def test_examined_without_any_result_rejected(self):
        self.assert_rejected([CheckScope("a", 12)], [], "sent no results")

    def test_nothing_checked_is_distinguishable_from_all_passed(self):
        self.write(
            [CheckScope("clean", 12), CheckScope("empty", 0, "模型沒有電纜架")],
            element_results("clean", range(12)),
        )
        rows = self.rows()
        self.assertEqual(rows[1][3:], ["clean", "12", "12", "0", "0", ""])
        self.assertEqual(rows[2][3:], ["empty", "0", "0", "0", "0", "模型沒有電纜架"])

    def test_zero_examined_with_a_result_rejected(self):
        self.assert_rejected(
            [CheckScope("a", 0, "none")], [Finding("a", Status.PASS, 1)],
            "examined 0 elements but has 1 results",
        )

    def test_model_level_check_one_result(self):
        self.write([CheckScope("a", 1)], [Finding("a", Status.UNVERIFIED, None, "z")])
        self.assertEqual(self.rows()[1][3:8], ["a", "1", "0", "0", "1"])

    def test_model_level_check_needs_examined_one_and_one_result(self):
        self.assert_rejected(
            [CheckScope("a", 2)], [Finding("a", Status.FAIL, None, "z")], "model-level check"
        )
        self.assert_rejected(
            [CheckScope("a", 1)],
            [Finding("a", Status.FAIL, None, "z"), Finding("a", Status.FAIL, None, "w")],
            "model-level check",
        )

    def test_mixed_levels_rejected(self):
        self.assert_rejected(
            [CheckScope("a", 2)],
            [Finding("a", Status.PASS, 1), Finding("a", Status.FAIL, None, "z")],
            "mixes element-level and model-level",
        )

    def test_finding_without_scope_rejected_and_no_file(self):
        self.assert_rejected([CheckScope("a", 1)], [Finding("other", Status.PASS, 1)], "no scope")

    def test_duplicate_scope_rejected(self):
        self.assert_rejected([CheckScope("a", 1), CheckScope("a", 2)], [], "duplicate")

    def test_wrong_types_rejected(self):
        with self.assertRaises(TypeError):
            self.write(["a"], [])
        with self.assertRaises(TypeError):
            self.write([CheckScope("a", 1)], ["x"])

    def test_note_formula_neutralised(self):
        self.write([CheckScope("a", 1, "=1+1")], [Finding("a", Status.PASS, 1)])
        self.assertEqual(self.rows()[1][8], "'=1+1")


if __name__ == "__main__":
    unittest.main()
