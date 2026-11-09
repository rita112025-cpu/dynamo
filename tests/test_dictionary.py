import copy
import json
import os
import shutil
import tempfile
import unittest

from mep_toolkit.dictionary import (KNOWN_CATEGORIES, DictionaryError, load_dictionary,
                                    validate_dictionary)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "parameter_dictionary.json")

# Names copied from SCADA_SoW_V6_SharedParameters.txt (UTF-16; sha256 5d8ced89...c9711).
# If the shipped dictionary drifts from the source file, this test fails.
SHARED_PARAMETER_NAMES = (
    "SCADA_編號", "SCADA_期別", "SCADA_站點", "SCADA_建物", "SCADA_房間", "SCADA_機櫃類型",
    "SCADA_寬mm", "SCADA_深mm", "SCADA_高mm", "SCADA_尺寸", "SCADA_附錄D項次",
    "SCADA_UPS電源110V", "SCADA_附錄F項次", "SCADA_來源文件", "SCADA_備註", "SCADA_定位來源",
)


def valid():
    with open(CONFIG, encoding="utf-8") as fh:
        return json.load(fh)


class ShippedDictionaryTest(unittest.TestCase):
    def test_loads(self):
        d = load_dictionary(CONFIG)
        self.assertEqual([c.key for c in d.categories], list(KNOWN_CATEGORIES))

    def test_dual_track_mapping(self):
        d = {c.key: c for c in load_dictionary(CONFIG).categories}
        for key in ("OST_Conduit", "OST_ConduitFitting", "OST_CableTray", "OST_CableTrayFitting"):
            self.assertEqual([(r.parameter, r.allowed) for r in d[key].required], [("服務類型", ("SCADA",))])
        for key in ("OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_Wire"):
            self.assertEqual([(r.parameter, r.allowed) for r in d[key].required], [("備註", ("SCADA",))])

    def test_rack_parameters_match_source_file(self):
        rack = load_dictionary(CONFIG).rack
        self.assertEqual(rack.required_parameters, SHARED_PARAMETER_NAMES)
        self.assertEqual(rack.category, "OST_ElectricalEquipment")
        self.assertEqual(rack.family_name_contains, "SCADA_機櫃")

    def test_unconfirmed_names_are_pending_not_required(self):
        rack = load_dictionary(CONFIG).rack
        pending = [p for p, _ in rack.pending_confirmation]
        self.assertEqual(pending, ["SCADA_前方淨距mm", "SCADA_後方淨距mm", "SCADA_淨距依據"])
        self.assertFalse(set(pending) & set(rack.required_parameters))


class ValidationTest(unittest.TestCase):
    def reject(self, mutate, pattern):
        data = valid()
        mutate(data)
        with self.assertRaisesRegex(DictionaryError, pattern):
            validate_dictionary(data)

    def test_unknown_category(self):
        def m(d):
            d["categories"]["OST_Walls"] = copy.deepcopy(d["categories"]["OST_Wire"])
        self.reject(m, "unknown category 'OST_Walls'")

    def test_empty_required_list(self):
        self.reject(lambda d: d["categories"]["OST_Wire"].update(required=[]), "required list must not be empty")

    def test_duplicate_required_parameter(self):
        def m(d):
            r = d["categories"]["OST_Wire"]["required"]
            r.append(copy.deepcopy(r[0]))
        self.reject(m, "duplicate required parameter")

    def test_duplicate_allowed_value(self):
        def m(d):
            d["categories"]["OST_Wire"]["required"][0]["allowed"] = ["SCADA", "SCADA"]
        self.reject(m, "duplicate entries")

    def test_empty_allowed_list(self):
        def m(d):
            d["categories"]["OST_Wire"]["required"][0]["allowed"] = []
        self.reject(m, "non-empty list")

    def test_blank_or_padded_names(self):
        def blank(d):
            d["categories"]["OST_Wire"]["required"][0]["parameter"] = " "
        def padded(d):
            d["categories"]["OST_Wire"]["required"][0]["parameter"] = "備註 "
        self.reject(blank, "non-empty string")
        self.reject(padded, "leading or trailing spaces")

    def test_empty_categories(self):
        self.reject(lambda d: d.update(categories={}), "non-empty object")

    def test_unknown_keys_rejected(self):
        self.reject(lambda d: d.update(extra=1), "unknown key")
        self.reject(lambda d: d["categories"]["OST_Wire"].update(extra=1), "unknown key")

    def test_wrong_schema_version(self):
        self.reject(lambda d: d.update(schema_version=2), "schema_version")

    def test_rack_empty_required(self):
        self.reject(lambda d: d["rack"].update(required_parameters=[]), "non-empty list")

    def test_rack_duplicate_required(self):
        self.reject(lambda d: d["rack"]["required_parameters"].append("SCADA_編號"), "duplicate")

    def test_rack_non_empty_must_be_required(self):
        self.reject(lambda d: d["rack"].update(non_empty_parameters=["SCADA_不存在"]), "not in required_parameters")

    def test_rack_category_must_be_configured(self):
        def m(d):
            del d["categories"]["OST_ElectricalEquipment"]
        self.reject(m, "not a configured category")

    def test_rack_prefix_must_contain_marker(self):
        self.reject(lambda d: d["rack"].update(family_name_prefix="X_"), "must start with")

    def test_rack_code_parameter_must_be_required(self):
        self.reject(lambda d: d["rack"].update(code_parameter="SCADA_其他"), "must be in required_parameters")

    def test_pending_must_not_also_be_required(self):
        def m(d):
            d["rack"]["pending_confirmation"].append({"parameter": "SCADA_編號", "reason": "x"})
        self.reject(m, "also required")

    def test_not_an_object(self):
        with self.assertRaises(DictionaryError):
            validate_dictionary([])


class LoadFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, text):
        path = os.path.join(self.dir, "d.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_invalid_json(self):
        with self.assertRaisesRegex(DictionaryError, "not valid JSON"):
            load_dictionary(self.write("{"))

    def test_duplicate_keys_rejected(self):
        with open(CONFIG, encoding="utf-8") as fh:
            text = fh.read().replace('"OST_Wire": {', '"OST_Wire": {"label": "x", "label": "y", ', 1)
        with self.assertRaisesRegex(DictionaryError, "duplicate key"):
            load_dictionary(self.write(text))

    def test_missing_file(self):
        with self.assertRaises(OSError):
            load_dictionary(os.path.join(self.dir, "nope.json"))


if __name__ == "__main__":
    unittest.main()
