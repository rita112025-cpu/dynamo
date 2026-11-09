import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from mep_toolkit.completeness import (FIXABLE, MISSING, OK, OTHER, RACK_NAME_CHECK, RACK_PARAMS_CHECK,
                                      check_completeness, classify, write_completeness_reports)
from mep_toolkit.dictionary import load_dictionary
from mep_toolkit.findings import Status
from mep_toolkit.snapshot import SnapshotError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT = load_dictionary(os.path.join(ROOT, "config", "parameter_dictionary.json"))
RUN_TIME = datetime(2026, 11, 9, 10, 30, 0, tzinfo=timezone(timedelta(hours=8)))
SOURCE = r"D:\fake\FAKE-ESC-TEST.rvt"


def conduit(eid, value, read_only=False, read_error=None):
    """value None = the parameter is absent from the model."""
    params = {} if value is None else {"服務類型": value}
    ro = ["服務類型"] if (read_only and value is not None) else []
    if read_error:
        params, ro = {}, []
    el = {"element_id": eid, "category": "OST_Conduit", "family_name": "F",
          "parameters": params, "read_only_parameters": ro}
    if read_error:
        el["read_error"] = read_error
    return el


def rack_params(**over):
    p = {n: "x" for n in DICT.rack.required_parameters}
    p["SCADA_編號"] = "R01"
    for k, v in over.items():
        if v is None:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def rack(eid, name="SCADA_機櫃_R01", params=None, read_only=(), read_error=None):
    params = rack_params() if params is None else params
    el = {"element_id": eid, "category": "OST_ElectricalEquipment", "family_name": name,
          "parameters": params, "read_only_parameters": list(read_only)}
    if read_error:
        el["parameters"], el["read_only_parameters"] = {}, []
        el["read_error"] = read_error
    return el


def by_check(result, check):
    return [f for f in result.findings if f.check == check]


def scope(result, check):
    return next(s for s in result.scopes if s.check == check)


class ClassifyTest(unittest.TestCase):
    def test_cases(self):
        allowed = ("SCADA",)
        cases = [
            (None, MISSING), ("", MISSING), ("   ", MISSING),
            ("SCADA", OK),
            ("scada", FIXABLE), ("Scada", FIXABLE), ("SCADA ", FIXABLE), (" SCADA", FIXABLE), (" scada ", FIXABLE),
            ("SCADA 2", OTHER), ("S CADA", OTHER), ("Power", OTHER), ("待確認", OTHER),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(classify(value, allowed), expected)


class IdentificationTest(unittest.TestCase):
    def one(self, el):
        r = check_completeness([el], DICT)
        return by_check(r, "SCADA識別_OST_Conduit")[0]

    def test_pass(self):
        f = self.one(conduit(1, "SCADA"))
        self.assertEqual((f.status, f.element_id, f.reason), (Status.PASS, 1, ""))

    def test_blank_present_is_missing_value_fail(self):
        for v in ("", "  "):
            f = self.one(conduit(1, v))
            self.assertEqual(f.status, Status.FAIL)
            self.assertIn("為空（缺漏）", f.reason)

    def test_case_or_space_is_fixable_fail_with_current_value(self):
        f = self.one(conduit(1, "scada "))
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("可修正", f.reason)
        self.assertIn("'scada '", f.reason)

    def test_other_value_is_kept_and_reported_with_current_value(self):
        f = self.one(conduit(1, "Power"))
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("保留他值", f.reason)
        self.assertIn("'Power'", f.reason)

    def test_missing_parameter_is_fail_with_its_own_reason(self):
        f = self.one(conduit(1, None))
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("模型沒有此參數（MISSING_PARAMETER）", f.reason)

    def test_read_only_correct_value_passes(self):
        self.assertEqual(self.one(conduit(1, "SCADA", read_only=True)).status, Status.PASS)

    def test_read_only_wrong_value_fails_and_says_it_cannot_be_fixed(self):
        for value in ("scada", "Power", ""):
            with self.subTest(value=value):
                f = self.one(conduit(1, value, read_only=True))
                self.assertEqual(f.status, Status.FAIL)
                self.assertIn("唯讀，批次工具無法修正", f.reason)
                self.assertIn("現值 %r" % value, f.reason)

    def test_read_error_is_unverified_with_exception_text(self):
        f = self.one(conduit(1, None, read_error="InvalidObjectException: boom"))
        self.assertEqual(f.status, Status.UNVERIFIED)
        self.assertIn("UNREADABLE", f.reason)
        self.assertIn("InvalidObjectException: boom", f.reason)

    def test_comments_track_for_equipment(self):
        els = [
            {"element_id": 1, "category": "OST_ElectricalEquipment", "family_name": "配電箱",
             "parameters": {"備註": "SCADA"}, "read_only_parameters": []},
            {"element_id": 2, "category": "OST_Wire", "family_name": "W",
             "parameters": {"備註": "x"}, "read_only_parameters": []},
        ]
        r = check_completeness(els, DICT)
        self.assertEqual(by_check(r, "SCADA識別_OST_ElectricalEquipment")[0].status, Status.PASS)
        self.assertEqual(by_check(r, "SCADA識別_OST_Wire")[0].status, Status.FAIL)

    def test_category_with_no_elements_has_examined_zero_and_note(self):
        r = check_completeness([conduit(1, "SCADA")], DICT)
        s = scope(r, "SCADA識別_OST_Wire")
        self.assertEqual(s.examined, 0)
        self.assertIn("OST_Wire", s.note)

    def test_empty_snapshot_examines_nothing_with_notes(self):
        r = check_completeness([], DICT)
        self.assertEqual(r.findings, [])
        self.assertTrue(all(s.examined == 0 and s.note for s in r.scopes))
        self.assertEqual(len(r.scopes), len(DICT.categories) + 2)


class UncoveredCategoryTest(unittest.TestCase):
    """R3: elements of categories the dictionary does not cover must show in the scope file."""

    def test_uncovered_category_has_scope_row_with_count(self):
        els = [conduit(1, "SCADA"),
               {"element_id": 2, "category": "OST_Walls", "family_name": None,
                "parameters": {}, "read_only_parameters": []},
               {"element_id": 3, "category": "OST_Walls", "family_name": None,
                "parameters": {}, "read_only_parameters": []}]
        r = check_completeness(els, DICT)
        self.assertEqual(r.ignored_categories, {"OST_Walls": 2})
        s = scope(r, "未涵蓋品類_OST_Walls")
        self.assertEqual(s.examined, 0)
        self.assertIn("未涵蓋品類 OST_Walls：2 個元件未檢查", s.note)
        self.assertEqual({f.element_id for f in r.findings}, {1})

    def test_uncovered_category_appears_in_written_scope_csv(self):
        d = tempfile.mkdtemp()
        try:
            els = [{"element_id": 7, "category": "OST_Walls", "family_name": None,
                    "parameters": {}, "read_only_parameters": []}]
            r = check_completeness(els, DICT)
            sp, fp = os.path.join(d, "s.csv"), os.path.join(d, "f.csv")
            write_completeness_reports(r, fp, sp, SOURCE, RUN_TIME)
            with open(sp, encoding="utf-8-sig", newline="") as fh:
                row = next(x for x in csv.DictReader(fh) if x["check"] == "未涵蓋品類_OST_Walls")
            self.assertEqual(row["examined"], "0")
            self.assertIn("1 個元件未檢查", row["note"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class RackTest(unittest.TestCase):
    def test_rack_is_exempt_from_comments_rule(self):
        els = [rack(1, params=rack_params(**{"SCADA_備註": "站 房 型"})),
               {"element_id": 2, "category": "OST_ElectricalEquipment", "family_name": "配電箱",
                "parameters": {"備註": "SCADA"}, "read_only_parameters": []}]
        r = check_completeness(els, DICT)
        self.assertEqual([f.element_id for f in by_check(r, "SCADA識別_OST_ElectricalEquipment")], [2])
        self.assertEqual(scope(r, "SCADA識別_OST_ElectricalEquipment").examined, 1)
        self.assertEqual(scope(r, RACK_PARAMS_CHECK).examined, 1)

    def test_complete_rack_passes_both_checks(self):
        r = check_completeness([rack(1)], DICT)
        self.assertEqual(by_check(r, RACK_PARAMS_CHECK)[0].status, Status.PASS)
        self.assertEqual(by_check(r, RACK_NAME_CHECK)[0].status, Status.PASS)

    def test_optional_rack_values_may_be_blank(self):
        p = rack_params(**{"SCADA_附錄D項次": "", "SCADA_備註": ""})
        self.assertEqual(by_check(check_completeness([rack(1, params=p)], DICT), RACK_PARAMS_CHECK)[0].status,
                         Status.PASS)

    def test_absent_rack_parameter_is_missing_parameter_fail(self):
        p = rack_params(**{"SCADA_備註": None})
        f = by_check(check_completeness([rack(1, params=p)], DICT), RACK_PARAMS_CHECK)[0]
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("模型沒有共用參數（MISSING_PARAMETER）：SCADA_備註", f.reason)

    def test_blank_required_value_fail(self):
        p = rack_params(**{"SCADA_站點": "  "})
        f = by_check(check_completeness([rack(1, params=p)], DICT), RACK_PARAMS_CHECK)[0]
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("必填值為空：SCADA_站點", f.reason)

    def test_read_only_blank_required_value_says_it_cannot_be_fixed(self):
        p = rack_params(**{"SCADA_站點": ""})
        f = by_check(check_completeness([rack(1, params=p, read_only=["SCADA_站點"])], DICT),
                     RACK_PARAMS_CHECK)[0]
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("SCADA_站點（唯讀，批次工具無法修正）", f.reason)

    def test_read_only_complete_rack_passes(self):
        f = by_check(check_completeness([rack(1, read_only=["SCADA_寬mm"])], DICT), RACK_PARAMS_CHECK)[0]
        self.assertEqual(f.status, Status.PASS)

    def test_family_name_must_start_with_prefix(self):
        r = check_completeness([rack(1, name="X_SCADA_機櫃_R01")], DICT)
        f = by_check(r, RACK_NAME_CHECK)[0]
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("開頭", f.reason)

    def test_family_name_code_rules(self):
        for name in ("SCADA_機櫃_", "SCADA_機櫃_ R01", "SCADA_機櫃_R01 ", "SCADA_機櫃_R:01", "SCADA_機櫃_R01."):
            with self.subTest(name=name):
                r = check_completeness([rack(1, name=name)], DICT)
                self.assertEqual(by_check(r, RACK_NAME_CHECK)[0].status, Status.FAIL)

    def test_family_name_code_must_match_code_parameter(self):
        f = by_check(check_completeness([rack(1, name="SCADA_機櫃_R02")], DICT), RACK_NAME_CHECK)[0]
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("不一致", f.reason)

    def test_code_mismatch_skipped_when_code_parameter_absent_or_blank(self):
        for p in (rack_params(**{"SCADA_編號": None}), rack_params(**{"SCADA_編號": ""})):
            with self.subTest(params=p.get("SCADA_編號")):
                r = check_completeness([rack(1, params=p)], DICT)
                self.assertEqual(by_check(r, RACK_NAME_CHECK)[0].status, Status.PASS)

    def test_rack_read_failure_unverified_on_both_checks(self):
        r = check_completeness([rack(1, read_error="boom")], DICT)
        self.assertEqual(by_check(r, RACK_PARAMS_CHECK)[0].status, Status.UNVERIFIED)
        self.assertEqual(by_check(r, RACK_NAME_CHECK)[0].status, Status.UNVERIFIED)

    def test_no_racks_gives_examined_zero_with_note(self):
        r = check_completeness([conduit(1, "SCADA")], DICT)
        for check in (RACK_PARAMS_CHECK, RACK_NAME_CHECK):
            self.assertEqual(scope(r, check).examined, 0)
            self.assertIn("SCADA_機櫃", scope(r, check).note)

    def test_rack_marker_only_matches_configured_category(self):
        el = {"element_id": 1, "category": "OST_Conduit", "family_name": "SCADA_機櫃_R01",
              "parameters": {"服務類型": "SCADA"}, "read_only_parameters": []}
        r = check_completeness([el], DICT)
        self.assertEqual(scope(r, RACK_PARAMS_CHECK).examined, 0)
        self.assertEqual(scope(r, "SCADA識別_OST_Conduit").examined, 1)


class InputAndOutputTest(unittest.TestCase):
    def test_invalid_snapshot_rejected(self):
        with self.assertRaises(SnapshotError):
            check_completeness([conduit(1, "SCADA"), conduit(1, "SCADA")], DICT)

    def test_v1_style_null_value_rejected(self):
        el = conduit(1, "SCADA")
        el["parameters"] = {"服務類型": None}
        with self.assertRaisesRegex(SnapshotError, "null"):
            check_completeness([el], DICT)

    def test_deterministic(self):
        els = [conduit(2, ""), conduit(1, "SCADA"), rack(3)]
        a = check_completeness(els, DICT)
        b = check_completeness(els, DICT)
        self.assertEqual(a, b)
        self.assertEqual([f.element_id for f in by_check(a, "SCADA識別_OST_Conduit")], [2, 1])

    def test_every_examined_element_has_exactly_one_finding_per_check(self):
        els = [conduit(1, "SCADA"), conduit(2, None), conduit(3, "x", read_error="e"),
               rack(4), rack(5, name="bad SCADA_機櫃_")]
        r = check_completeness(els, DICT)
        for s in r.scopes:
            fs = by_check(r, s.check)
            self.assertEqual(len(fs), s.examined, s.check)
            self.assertEqual(len({f.element_id for f in fs}), len(fs), s.check)

    def test_reports_go_through_standard_writers(self):
        d = tempfile.mkdtemp()
        try:
            els = [conduit(1, "SCADA"), conduit(2, ""), conduit(3, "x", read_error="e"), rack(4)]
            r = check_completeness(els, DICT)
            fp, sp = os.path.join(d, "f.csv"), os.path.join(d, "s.csv")
            write_completeness_reports(r, fp, sp, SOURCE, RUN_TIME)
            with open(sp, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), len(DICT.categories) + 2)
            for row in rows:
                self.assertEqual(int(row["pass"]) + int(row["fail"]) + int(row["unverified"]), int(row["examined"]))
                self.assertEqual(row["model_file"], "FAKE-ESC-TEST.rvt")
            conduit_row = next(x for x in rows if x["check"] == "SCADA識別_OST_Conduit")
            self.assertEqual((conduit_row["examined"], conduit_row["pass"], conduit_row["fail"],
                              conduit_row["unverified"]), ("3", "1", "1", "1"))
            with open(fp, encoding="utf-8-sig", newline="") as fh:
                self.assertEqual(len(list(csv.DictReader(fh))), len(r.findings))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_empty_source_path_rejected_and_nothing_written(self):
        d = tempfile.mkdtemp()
        try:
            r = check_completeness([conduit(1, "SCADA")], DICT)
            with self.assertRaises(ValueError):
                write_completeness_reports(r, os.path.join(d, "f.csv"), os.path.join(d, "s.csv"), "", RUN_TIME)
            self.assertEqual(os.listdir(d), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
