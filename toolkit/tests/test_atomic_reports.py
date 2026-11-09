"""R2 acceptance: the scope file and the findings file are written as one unit.

Each test checks the bytes of both final files, and that no temporary or backup file is left.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from mep_toolkit.csv_report import COLUMNS, SCOPE_COLUMNS, write_reports_atomic

REAL_REPLACE = os.replace


def scope_row(tag):
    return ["0.1.0", "2026-11-09T10:30:00+08:00", "m.rvt", "chk", "1", tag, "0", "0", ""]


def finding_row(tag):
    return ["0.1.0", "2026-11-09T10:30:00+08:00", "m.rvt", "1", "chk", "PASS", tag]


def fail_once(target, errno=13):
    """os.replace that fails the FIRST time it is asked to put something at `target`."""
    state = {"failed": False}

    def fake(src, dst):
        if not state["failed"] and os.path.normcase(dst) == os.path.normcase(target):
            state["failed"] = True
            raise PermissionError(errno, "locked by another program")
        return REAL_REPLACE(src, dst)

    return fake


def fail_always(target):
    def fake(src, dst):
        if os.path.normcase(dst) == os.path.normcase(target):
            raise PermissionError(13, "locked by another program")
        return REAL_REPLACE(src, dst)

    return fake


class AtomicReportsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.scope = os.path.join(self.dir, "scope.csv")
        self.findings = os.path.join(self.dir, "findings.csv")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def outputs(self, tag):
        return [(self.scope, SCOPE_COLUMNS, [scope_row(tag)]),
                (self.findings, COLUMNS, [finding_row(tag)])]

    def read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def seed_old(self):
        write_reports_atomic(self.outputs("OLD"))
        return self.read(self.scope), self.read(self.findings)

    def assert_no_residue(self):
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(
            n for n in os.listdir(self.dir) if n in ("scope.csv", "findings.csv")))

    def test_both_new_when_no_files_exist(self):
        write_reports_atomic(self.outputs("NEW"))
        self.assertIn(b"NEW", self.read(self.scope))
        self.assertIn(b"NEW", self.read(self.findings))
        self.assertEqual(sorted(os.listdir(self.dir)), ["findings.csv", "scope.csv"])

    def test_both_replaced_when_both_succeed(self):
        old_scope, old_findings = self.seed_old()
        write_reports_atomic(self.outputs("NEW"))
        self.assertNotEqual(self.read(self.scope), old_scope)
        self.assertNotEqual(self.read(self.findings), old_findings)
        self.assertIn(b"NEW", self.read(self.scope))
        self.assertIn(b"NEW", self.read(self.findings))
        self.assertEqual(sorted(os.listdir(self.dir)), ["findings.csv", "scope.csv"])

    def test_second_replacement_fails_both_old_bytes_restored(self):
        old_scope, old_findings = self.seed_old()
        with mock.patch("os.replace", side_effect=fail_once(self.findings)):
            with self.assertRaises(PermissionError) as cm:
                write_reports_atomic(self.outputs("NEW"))
        self.assertEqual(cm.exception.filename, self.findings)
        self.assertIn("Excel", str(cm.exception))
        self.assertEqual(self.read(self.scope), old_scope)
        self.assertEqual(self.read(self.findings), old_findings)
        self.assertEqual(sorted(os.listdir(self.dir)), ["findings.csv", "scope.csv"])

    def test_second_replacement_fails_with_no_old_files_leaves_nothing(self):
        with mock.patch("os.replace", side_effect=fail_once(self.findings)):
            with self.assertRaises(PermissionError):
                write_reports_atomic(self.outputs("NEW"))
        self.assertEqual(os.listdir(self.dir), [])

    def test_first_replacement_fails_both_old_bytes_unchanged(self):
        old_scope, old_findings = self.seed_old()
        with mock.patch("os.replace", side_effect=fail_once(self.scope)):
            with self.assertRaises(PermissionError) as cm:
                write_reports_atomic(self.outputs("NEW"))
        self.assertEqual(cm.exception.filename, self.scope)
        self.assertEqual(self.read(self.scope), old_scope)
        self.assertEqual(self.read(self.findings), old_findings)
        self.assertEqual(sorted(os.listdir(self.dir)), ["findings.csv", "scope.csv"])

    def test_rollback_that_cannot_restore_says_which_file(self):
        old_scope, _ = self.seed_old()
        with mock.patch("os.replace", side_effect=fail_always(self.findings)):
            with self.assertRaises(RuntimeError) as cm:
                write_reports_atomic(self.outputs("NEW"))
        message = str(cm.exception)
        self.assertIn("rollback incomplete", message)
        self.assertIn(self.findings, message)
        # The scope file was rolled back fine; only the findings file needs a hand check.
        self.assertEqual(self.read(self.scope), old_scope)

    def test_duplicate_target_rejected_before_any_write(self):
        with self.assertRaisesRegex(ValueError, "appears more than once"):
            write_reports_atomic([(self.scope, SCOPE_COLUMNS, []), (self.scope, COLUMNS, [])])
        self.assertEqual(os.listdir(self.dir), [])

    @unittest.skipUnless(os.name == "nt", "Windows keeps an open file locked against rename/replace")
    def test_real_locked_findings_file_keeps_both_old(self):
        old_scope, old_findings = self.seed_old()
        with open(self.findings, "rb"):  # another program holds the file open
            with self.assertRaises(PermissionError) as cm:
                write_reports_atomic(self.outputs("NEW"))
        self.assertEqual(cm.exception.filename, self.findings)
        self.assertEqual(self.read(self.scope), old_scope)
        self.assertEqual(self.read(self.findings), old_findings)
        self.assertEqual(sorted(os.listdir(self.dir)), ["findings.csv", "scope.csv"])


if __name__ == "__main__":
    unittest.main()
