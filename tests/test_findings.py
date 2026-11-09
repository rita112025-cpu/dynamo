import dataclasses
import unittest

from core.findings import Finding, Status


class FindingTest(unittest.TestCase):
    def test_pass_needs_no_reason(self):
        f = Finding("check", Status.PASS, 123)
        self.assertEqual(f.reason, "")
        self.assertEqual(f.element_id, 123)

    def test_model_level_finding_has_no_element(self):
        self.assertIsNone(Finding("check", Status.FAIL, reason="x").element_id)

    def test_fail_and_unverified_need_reason(self):
        for status in (Status.FAIL, Status.UNVERIFIED):
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    Finding("check", status, 1)
                with self.assertRaises(ValueError):
                    Finding("check", status, 1, "   ")

    def test_status_must_be_enum(self):
        with self.assertRaises(ValueError):
            Finding("check", "PASS", 1)

    def test_check_must_be_non_empty(self):
        for bad in ("", "  ", None):
            with self.subTest(check=bad):
                with self.assertRaises(ValueError):
                    Finding(bad, Status.PASS, 1)

    def test_element_id_must_be_int(self):
        for bad in ("123", 1.0, True):
            with self.subTest(element_id=bad):
                with self.assertRaises(ValueError):
                    Finding("check", Status.PASS, bad)

    def test_negative_element_id_allowed(self):
        # Built-in Revit elements (and InvalidElementId) have negative ids.
        self.assertEqual(Finding("check", Status.PASS, -1).element_id, -1)

    def test_reason_must_be_string(self):
        with self.assertRaises(ValueError):
            Finding("check", Status.FAIL, 1, None)

    def test_frozen(self):
        f = Finding("check", Status.PASS, 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            f.status = Status.FAIL

    def test_status_values(self):
        self.assertEqual([s.value for s in Status], ["PASS", "FAIL", "UNVERIFIED"])


if __name__ == "__main__":
    unittest.main()
