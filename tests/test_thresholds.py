import copy
import json
import os
import shutil
import tempfile
import unittest

from mep_toolkit.thresholds import (PROVISIONAL_LABEL, ThresholdError, load_thresholds, validate_thresholds)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "thresholds.json")


def valid():
    with open(CONFIG, encoding="utf-8") as fh:
        return json.load(fh)


class ShippedThresholdsTest(unittest.TestCase):
    def test_values_and_status(self):
        t = load_thresholds(CONFIG)
        self.assertEqual(t["cable_tray_gap_max"].value, 50)
        self.assertEqual(t["cable_tray_endpoint_tolerance"].value, 1)
        self.assertEqual(t["cable_tray_floor_clearance"].value, 2500)
        for th in t.values():
            self.assertEqual(th.status, "provisional")
            self.assertEqual(th.label, PROVISIONAL_LABEL)
            self.assertEqual(th.unit, "mm")

    def test_floor_clearance_record(self):
        f = load_thresholds(CONFIG)["cable_tray_floor_clearance"]
        self.assertEqual(f.kind, "height")
        self.assertEqual(f.height_basis, "bottom")
        self.assertEqual(f.comparison, ">=")
        self.assertEqual(f.source_status, "待核對原文")
        self.assertIn("附錄C", f.source)
        self.assertIn("樓層標高", f.note)
        self.assertIn("水平段", f.applies_to)

    def test_gap_and_tolerance_are_proposals_without_source(self):
        t = load_thresholds(CONFIG)
        for tid in ("cable_tray_gap_max", "cable_tray_endpoint_tolerance"):
            self.assertEqual(t[tid].source_status, "提案值，無原文依據")


class FloorClearanceJudgementTest(unittest.TestCase):
    def setUp(self):
        self.f = load_thresholds(CONFIG)["cable_tray_floor_clearance"]

    def test_greater_or_equal_passes(self):
        self.assertTrue(self.f.satisfies(2500))       # boundary: equal passes
        self.assertTrue(self.f.satisfies(2500.5))
        self.assertTrue(self.f.satisfies(3000))

    def test_below_fails(self):
        self.assertFalse(self.f.satisfies(2499.9))
        self.assertFalse(self.f.satisfies(0))

    def test_gap_and_tolerance_comparisons(self):
        t = load_thresholds(CONFIG)
        self.assertTrue(t["cable_tray_endpoint_tolerance"].satisfies(1))     # equal is within tolerance
        self.assertFalse(t["cable_tray_endpoint_tolerance"].satisfies(1.001))
        self.assertTrue(t["cable_tray_gap_max"].satisfies(50))
        self.assertFalse(t["cable_tray_gap_max"].satisfies(50.1))

    def test_bad_measurements_rejected(self):
        for bad in (float("nan"), float("inf"), "2500", None, True):
            with self.subTest(measured=bad):
                with self.assertRaises(ValueError):
                    self.f.satisfies(bad)


class ValidationTest(unittest.TestCase):
    def reject(self, mutate, pattern, key="cable_tray_floor_clearance"):
        data = valid()
        mutate(data["thresholds"][key])
        with self.assertRaisesRegex(ThresholdError, pattern):
            validate_thresholds(data)

    def test_wrong_schema_version(self):
        data = valid()
        data["schema_version"] = 2
        with self.assertRaisesRegex(ThresholdError, "schema_version"):
            validate_thresholds(data)

    def test_empty_thresholds(self):
        data = valid()
        data["thresholds"] = {}
        with self.assertRaisesRegex(ThresholdError, "non-empty"):
            validate_thresholds(data)

    def test_missing_required_key(self):
        for key in ("kind", "value", "unit", "comparison", "applies_to", "status", "source", "source_status"):
            with self.subTest(missing=key):
                self.reject(lambda t, k=key: t.pop(k), "is missing")

    def test_unknown_key(self):
        self.reject(lambda t: t.update(extra=1), "unknown key")

    def test_value_must_be_positive_number(self):
        for bad in (0, -1, "2500", True, None, float("inf")):
            with self.subTest(value=bad):
                self.reject(lambda t, v=bad: t.update(value=v), "positive finite number")

    def test_unit_must_be_mm(self):
        self.reject(lambda t: t.update(unit="m"), "unit must be 'mm'")

    def test_comparison_allowed_values(self):
        self.reject(lambda t: t.update(comparison="<"), "comparison")

    def test_status_allowed_values(self):
        self.reject(lambda t: t.update(status="approved"), "status")

    def test_source_status_allowed_values(self):
        self.reject(lambda t: t.update(source_status="頁碼待定"), "source_status")

    def test_confirmed_needs_verified_source(self):
        self.reject(lambda t: t.update(status="confirmed"), "confirmed threshold needs")
        def ok(t):
            t.update(status="confirmed", source_status="已核對原文")
        data = valid()
        ok(data["thresholds"]["cable_tray_floor_clearance"])
        validate_thresholds(data)  # does not raise

    def test_height_basis_only_bottom(self):
        for basis in ("center", "top", "Bottom", "", None):
            with self.subTest(basis=basis):
                self.reject(lambda t, b=basis: t.update(height_basis=b), "height_basis")

    def test_height_threshold_requires_height_basis(self):
        self.reject(lambda t: t.pop("height_basis"), "height_basis")

    def test_height_threshold_must_use_greater_or_equal(self):
        self.reject(lambda t: t.update(comparison="<="), "must use '>='")

    def test_height_basis_only_for_height_kind(self):
        self.reject(lambda t: t.update(kind="gap", height_basis="bottom"), "only for kind 'height'",
                    key="cable_tray_gap_max")

    def test_kind_allowed_values(self):
        self.reject(lambda t: t.update(kind="area"), "kind")

    def test_empty_source_or_applies_to(self):
        self.reject(lambda t: t.update(source="  "), "source must be a non-empty string")
        self.reject(lambda t: t.update(applies_to=""), "applies_to must be a non-empty string")


class FileTest(unittest.TestCase):
    def test_invalid_json(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "t.json")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{")
            with self.assertRaisesRegex(ThresholdError, "not valid JSON"):
                load_thresholds(p)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
