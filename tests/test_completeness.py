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


def conduit(eid, value, **kw):
    base = {"element_id": eid, "category": "OST_Conduit", "family_name": "F", "parameters": {"服務類型": value}}
    base.update(kw)
    return base


def rack_params(**over):
    p = {n: "x" for n in DICT.rack.required_parameters}
    p["SCADA_編號"] = "R01"
    p.update(over)
    return p


def rack(eid, name="SCADA_機櫃_R01", params=None, **kw):
    base = {"element_id": eid, "category": "OST_ElectricalEquipment", "family_name": name,
            "parameters": rack_params() if params is None else params}
    base.update(kw)
    return base


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

    def test_multiple_allowed_values(self):
        self.assertEqual(classify("b", ("A", "B")), FIXABLE)
        self.assertEqual(classify("A", ("A", "B")), OK)


class IdentificationTest(unittest.TestCase):
    def run_one(self, value, **kw):
        r = check_completeness([conduit(1, value, **kw)], DICT)
        return by_check(r, "SCADA識別_OST_Conduit")[0]

    def test_pass(self):
        f = self.run_one("SCADA")
        self.assertEqual((f.status, f.element_id, f.reason), (Status.PASS, 1, ""))

    def test_blank_is_missing_fail(self):
        for v in ("", "  "):
            f = self.run_one(v)
            self.assertEqual(f.status, Status.FAIL)
            self.assertIn("缺漏", f.reason)

    def test_case_or_space_is_fixable_fail_with_current_value(self):
        f = self.run_one("scada ")
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("可修正", f.reason)
        self.assertIn("'scada '", f.reason)

    def test_other_value_is_kept_and_reported_with_current_value(self):
        f = self.run_one("Power")
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("保留他值", f.reason)
        self.assertIn("'Power'", f.reason)

    def test_no_such_parameter_or_read_only(self):
        for value in (None,):
            f = self.run_one(value)
            self.assertEqual(f.status, Status.FAIL)
            self.assertIn("無此參數或為唯讀", f.reason)
        r = check_completeness([conduit(1, "x", parameters={})], DICT)
        self.assertIn("無此參數或為唯讀", by_check(r, "SCADA識別_OST_Conduit")[0].reason)

    def test_read_failure_is_unverified_with_exception_text(self):
        f = self.run_one("SCADA", read_error="InvalidObjectException: boom")
        self.assertEqual(f.status, Status.UNVERIFIED)
        self.assertIn("InvalidObjectException: boom", f.reason)

    def test_comments_track_for_equipment(self):
        els = [
            {"element_id": 1, "category": "OST_ElectricalEquipment", "family_name": "配電箱", "parameters": {"備註": "SCADA"}},
            {"element_id": 2, "category": "OST_Wire", "family_name": "W", "parameters": {"備註": "x"}},
        ]
        r = check_completeness(els, DICT)
        self.assertEqual(by_check(r, "SCADA識別_OST_ElectricalEquipment")[0].status, Status.PASS)
        self.assertEqual(by_check(r, "SCADA識別_OST_Wire")[0].status, Status.FAIL)

    def test_category_with_no_elements_has_examined_zero_and_note(self):
        r = check_completeness([conduit(1, "SCADA")], DICT)
        s = scope(r, "SCADA識別_OST_Wire")
        self.assertEqual(s.examined, 0)
        self.assertIn("OST_Wire", s.note)
        self.assertEqual(by_check(r, "SCADA識別_OST_Wire"), [])

    def test_empty_snapshot_examines_nothing_with_notes(self):
        r = check_completeness([], DICT)
        self.assertEqual(r.findings, [])
        self.assertTrue(all(s.examined == 0 and s.note for s in r.scopes))
        self.assertEqual(len(r.scopes), len(DICT.categories) + 2)

    def test_unknown_category_ignored_and_counted(self):
        els = [conduit(1, "SCADA"),
               {"element_id": 2, "category": "OST_Walls", "family_name": None, "parameters": {}},
               {"element_id": 3, "category": "OST_Walls", "family_name": None, "parameters": {}}]
        r = check_completeness(els, DICT)
        self.assertEqual(r.ignored_categories, {"OST_Walls": 2})
        self.assertEqual({f.element_id for f in r.findings}, {1})


class RackTest(unittest.TestCase):
    def test_rack_is_exempt_from_comments_rule(self):
        els = [rack(1, params=rack_params(**{"SCADA_備註": "站 房 型"})),
               {"element_id": 2, "category": "OST_ElectricalEquipment", "family_name": "配電箱", "parameters": {"備註": "SCADA"}}]
        r = check_completeness(els, DICT)
        ident = by_check(r, "SCADA識別_OST_ElectricalEquipment")
        self.assertEqual([f.element_id for f in ident], [2])
        self.assertEqual(scope(r, "SCADA識別_OST_ElectricalEquipment").examined, 1)
        self.assertEqual(scope(r, RACK_PARAMS_CHECK).examined, 1)
        self.assertEqual(scope(r, RACK_NAME_CHECK).examined, 1)

    def test_complete_rack_passes_both_checks(self):
        r = check_completeness([rack(1)], DICT)
        self.assertEqual(by_check(r, RACK_PARAMS_CHECK)[0].status, Status.PASS)
        self.assertEqual(by_check(r, RACK_NAME_CHECK)[0].status, Status.PASS)

    def test_rack_non_empty_optional_values_may_be_blank(self):
        p = rack_params(**{"SCADA_附錄D項次": "", "SCADA_備註": ""})
        r = check_completeness([rack(1, params=p)], DICT)
        self.assertEqual(by_check(r, RACK_PARAMS_CHECK)[0].status, Status.PASS)

    def test_missing_and_empty_are_merged_into_one_finding(self):
        p = rack_params(**{"SCADA_站點": ""})
        del p["SCADA_備註"]
        p["SCADA_建物"] = None  # read-only counts as missing
        r = check_completeness([rack(1, params=p)], DICT)
        fs = by_check(r, RACK_PARAMS_CHECK)
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].status, Status.FAIL)
        for name in ("SCADA_備註", "SCADA_建物", "SCADA_站點"):
            self.assertIn(name, fs[0].reason)

    def test_pending_parameters_are_not_required(self):
        # Rack without the unconfirmed clearance parameters still passes.
        r = check_completeness([rack(1)], DICT)
        self.assertEqual(by_check(r, RACK_PARAMS_CHECK)[0].status, Status.PASS)

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
        r = check_completeness([rack(1, name="SCADA_機櫃_R02")], DICT)
        f = by_check(r, RACK_NAME_CHECK)[0]
        self.assertEqual(f.status, Status.FAIL)
        self.assertIn("不一致", f.reason)

    def test_code_mismatch_skipped_when_code_parameter_unavailable(self):
        p = rack_params()
        p["SCADA_編號"] = None
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
        el = {"element_id": 1, "category": "OST_Conduit", "family_name": "SCADA_機櫃_R01", "parameters": {"服務類型": "SCADA"}}
        r = check_completeness([el], DICT)
        self.assertEqual(scope(r, RACK_PARAMS_CHECK).examined, 0)
        self.assertEqual(scope(r, "SCADA識別_OST_Conduit").examined, 1)

    def test_family_name_none_is_not_a_rack(self):
        el = rack(1)
        el["family_name"] = None
        r = check_completeness([el], DICT)
        self.assertEqual(scope(r, RACK_PARAMS_CHECK).examined, 0)


class InputAndOutputTest(unittest.TestCase):
    def test_invalid_snapshot_rejected(self):
        with self.assertRaises(SnapshotError):
            check_completeness([conduit(1, "SCADA"), conduit(1, "SCADA")], DICT)

    def test_deterministic(self):
        els = [conduit(2, ""), conduit(1, "SCADA"), rack(3)]
        a = check_completeness(els, DICT)
        b = check_completeness(els, DICT)
        self.assertEqual(a, b)
        self.assertEqual([f.element_id for f in by_check(a, "SCADA識別_OST_Conduit")], [2, 1])  # snapshot order

    def test_every_examined_element_has_exactly_one_finding_per_check(self):
        els = [conduit(1, "SCADA"), conduit(2, None), conduit(3, "x", read_error="e"), rack(4), rack(5, name="bad SCADA_機櫃_")]
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
            self.assertEqual((conduit_row["examined"], conduit_row["pass"], conduit_row["fail"], conduit_row["unverified"]),
                             ("3", "1", "1", "1"))
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
