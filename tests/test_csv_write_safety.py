import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from mep_toolkit.csv_report import write_findings_csv, write_scope_csv
from mep_toolkit.findings import CheckScope, Finding, Status

RUN_TIME = datetime(2026, 11, 9, 10, 30, 0, tzinfo=timezone(timedelta(hours=8)))


class ReplaceFailureTest(unittest.TestCase):
    """The target report is locked, for example open in Excel on Windows."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "report.csv")
        write_findings_csv(self.path, [Finding("old", Status.PASS, 1)], "m.rvt", RUN_TIME)
        with open(self.path, "rb") as fh:
            self.before = fh.read()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def assert_untouched(self):
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), self.before)
        self.assertEqual(os.listdir(self.dir), ["report.csv"])

    def test_findings_csv_gives_clear_message_and_keeps_old_report(self):
        with mock.patch("os.replace", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError) as cm:
                write_findings_csv(self.path, [Finding("new", Status.PASS, 2)], "m.rvt", RUN_TIME)
        self.assertIn("Excel", str(cm.exception))
        self.assertEqual(cm.exception.filename, self.path)
        self.assertEqual(cm.exception.errno, 13)
        self.assert_untouched()

    def test_scope_csv_gives_clear_message_and_keeps_old_report(self):
        with mock.patch("os.replace", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError) as cm:
                write_scope_csv(self.path, [CheckScope("new", 1)],
                                [Finding("new", Status.PASS, 1)], "m.rvt", RUN_TIME)
        self.assertIn("Excel", str(cm.exception))
        self.assertEqual(cm.exception.filename, self.path)
        self.assert_untouched()

    @unittest.skipUnless(os.name == "nt", "Windows locks open files; other systems do not")
    def test_real_locked_file_on_windows(self):
        with open(self.path, "rb"):  # same sharing mode as a file another program holds open
            try:
                write_findings_csv(self.path, [Finding("new", Status.PASS, 2)], "m.rvt", RUN_TIME)
            except PermissionError as ex:
                self.assertIn("Excel", str(ex))
                self.assertEqual(ex.filename, self.path)
            else:
                self.skipTest("this Windows build allowed replacing an open file")
        self.assert_untouched()


class ModelFileTest(unittest.TestCase):
    """model_file is the SOURCE path passed in by the caller; never read from a document."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "r.csv")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def name_written(self, model_file):
        write_findings_csv(self.path, [Finding("c", Status.PASS, 1)], model_file, RUN_TIME)
        with open(self.path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.reader(fh))[1][2]

    def test_source_path_variants_give_file_name(self):
        for model_file in (r"D:\models\A-ESC-1.rvt", "D:/models/A-ESC-1.rvt",
                           r"\\server\share\A-ESC-1.rvt", "A-ESC-1.rvt"):
            with self.subTest(model_file=model_file):
                self.assertEqual(self.name_written(model_file), "A-ESC-1.rvt")

    def test_empty_path_rejected(self):
        # A detached document has doc.PathName == "". Passing that on must fail loudly.
        for bad in ("", "   ", None):
            with self.subTest(model_file=bad):
                with self.assertRaises(ValueError):
                    write_findings_csv(self.path, [], bad, RUN_TIME)
                with self.assertRaises(ValueError):
                    write_scope_csv(self.path, [], [], bad, RUN_TIME)
        self.assertEqual(os.listdir(self.dir), [])


if __name__ == "__main__":
    unittest.main()
