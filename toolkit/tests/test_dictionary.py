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


# Fixed regression baseline, deliberately hard-coded (16 GUIDs, file order).
# Purpose: if the dictionary AND the source file are changed together, this constant still
# catches it. It is NOT the main check. Main verification is dynamic: parse the shared
# parameter file and compare both directions (tests/test_shared_consistency.py,
# dictionary.verify_against_shared_file), which also detects source-file changes.
# Origin: SCADA_SoW_V6_SharedParameters.txt (UTF-16, sha256 5d8ced89...c9711).
SOURCE_GUIDS = (
    "81bdc77b-c362-4012-aa80-6edd256f9b09", "b1b763ae-f6db-44bf-b7a5-ad35ea29ad9c",
    "f1f6fdc5-7006-44e2-a7d0-60ae0647f0d0", "8a59691b-8411-4799-a4b5-693cf1661e67",
    "53413beb-fd65-4b80-8753-db471cb8319c", "3e00233a-044f-4b21-bca3-fa1ce26ba6e5",
    "e0f8b8a1-3ba8-49e3-9b11-e40b4b710d06", "b9f4ce69-08e6-4908-b23b-56a384832f43",
    "896f98f9-1b6f-4a9f-9a85-3cfa29758348", "a6d1af90-4cc8-48c0-a233-f204e0abad5b",
    "42b9f865-f078-4b52-93b3-852e19aeafa6", "b662bf65-c745-4d14-beaf-4dcc180dc298",
    "aa933f19-c018-4d63-887b-d388eef2ec0a", "a26cb5cc-1c1d-400b-b011-5c77e3a44b4b",
    "4cb549c0-2004-4250-8d34-8c10252c4a4f", "82607d24-24b2-4a1f-94fe-109bfff58ad1",
)


class SharedParameterTest(unittest.TestCase):
    def test_shipped_names_and_guids_match_source_file(self):
        params = load_dictionary(CONFIG).shared.parameters
        self.assertEqual([(p.name, p.guid) for p in params], list(zip(SHARED_PARAMETER_NAMES, SOURCE_GUIDS)))

    def test_shipped_types_and_source_hash(self):
        shared = load_dictionary(CONFIG).shared
        self.assertEqual({p.data_type for p in shared.parameters}, {"TEXT"})
        self.assertEqual(shared.source_sha256, "5d8ced89fe445bf10b5e4e17bb47acca81bc0ff13544954328e57ecb58bc9711")
        self.assertEqual(shared.applies_to_category, "OST_ElectricalEquipment")
        self.assertEqual(shared.applies_to_family_contains, "SCADA_機櫃")

    def test_guid_normalised_to_lower_case(self):
        d = valid()
        d["shared_parameters"]["parameters"][0]["guid"] = SOURCE_GUIDS[0].upper()
        self.assertEqual(validate_dictionary(d).shared.parameters[0].guid, SOURCE_GUIDS[0])

    def _reject(self, mutate, pattern):
        d = valid()
        mutate(d)
        with self.assertRaisesRegex(DictionaryError, pattern):
            validate_dictionary(d)

    def test_bad_guid_formats(self):
        for bad in ("81bdc77bc3624012aa806edd256f9b09", "81bdc77b-c362-4012-aa80-6edd256f9b0", "zzbdc77b-c362-4012-aa80-6edd256f9b09", "", None):
            with self.subTest(guid=bad):
                self._reject(lambda d: d["shared_parameters"]["parameters"][0].update(guid=bad), "not a valid GUID")

    def test_duplicate_guid(self):
        def m(d):
            d["shared_parameters"]["parameters"][1]["guid"] = SOURCE_GUIDS[0].upper()
        self._reject(m, "duplicate GUIDs")

    def test_duplicate_name(self):
        def m(d):
            d["shared_parameters"]["parameters"][1]["name"] = d["shared_parameters"]["parameters"][0]["name"]
        self._reject(m, "duplicate names")

    def test_data_type_must_be_text(self):
        for bad in ("Integer", "text", None):
            with self.subTest(data_type=bad):
                self._reject(lambda d: d["shared_parameters"]["parameters"][0].update(data_type=bad),
                             "not in TEXT")

    def test_missing_shared_block(self):
        self._reject(lambda d: d.pop("shared_parameters"), "missing shared_parameters")

    def test_shared_names_must_equal_rack_required(self):
        self._reject(lambda d: d["shared_parameters"]["parameters"].pop(),
                     r"differ: only in rack .*only in shared \[\]")
        def extra(d):
            d["shared_parameters"]["parameters"].append(
                {"name": "SCADA_多出的", "guid": SOURCE_GUIDS[0].replace("8", "7", 1), "data_type": "TEXT"})
        self._reject(extra, "differ")

    def test_shared_applies_to_must_match_rack(self):
        self._reject(lambda d: d["shared_parameters"]["applies_to"].update(family_name_contains="X"),
                     "applies_to does not match")

    def test_source_hash_format(self):
        self._reject(lambda d: d["shared_parameters"].update(source_sha256="ABC"), "source_sha256")

    def test_shared_block_unknown_key(self):
        self._reject(lambda d: d["shared_parameters"].update(extra=1), "unknown key")

    def test_pending_names_are_not_shared(self):
        def m(d):
            d["rack"]["pending_confirmation"][0]["parameter"] = "SCADA_定位來源"
        self._reject(m, "also required")


class BasisTest(unittest.TestCase):
    """R5: the rack rules are marked as inferred from existing code, not owner-confirmed."""

    def _reject(self, mutate, pattern):
        d = valid()
        mutate(d)
        with self.assertRaisesRegex(DictionaryError, pattern):
            validate_dictionary(d)

    def test_shipped_basis_says_inferred_not_confirmed(self):
        basis = load_dictionary(CONFIG)  # loads only if the basis block is valid
        with open(CONFIG, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["rack"]["basis"]["status"], "依既有程式推定，非業主確認")

    def test_basis_block_required(self):
        self._reject(lambda d: d["rack"].pop("basis"), "missing|basis")

    def test_basis_status_cannot_claim_owner_confirmation(self):
        for bad in ("業主確認", "已確認", "依既有程式推定", ""):
            with self.subTest(status=bad):
                self._reject(lambda d, s=bad: d["rack"]["basis"].update(status=s), "not owner-confirmed")

    def test_basis_sources_required(self):
        self._reject(lambda d: d["rack"]["basis"].update(non_empty_source=""), "non-empty")
        self._reject(lambda d: d["rack"]["basis"].update(exists_source=""), "non-empty")

    def test_basis_unknown_key(self):
        self._reject(lambda d: d["rack"]["basis"].update(owner="x"), "unknown key")


if __name__ == "__main__":
    unittest.main()
