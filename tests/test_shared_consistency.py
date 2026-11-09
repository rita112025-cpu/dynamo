"""R1 acceptance A: dictionary <-> shared parameter file, two-way, using FAKE UTF-16 fixtures.

No test here reads the real D: drive. The fixture file is generated in a temp folder.
"""
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from mep_toolkit.dictionary import DictionaryError, load_dictionary, validate_dictionary, verify_against_shared_file
from mep_toolkit.shared_params import SharedFileError, parse_shared_bytes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "parameter_dictionary.json")

HEADER = [
    "# This is a Revit shared parameter file.",
    "# Do not edit manually.",
    "*META\tVERSION\tMINVERSION",
    "META\t2\t1",
    "*GROUP\tID\tNAME",
    "GROUP\t1\t{group}",
    "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE",
]


def encode_file(group, params):
    """params: list of (guid, name, datatype). Returns UTF-16 bytes (with BOM), CRLF line ends."""
    lines = [h.format(group=group) for h in HEADER]
    for guid, name, dtype in params:
        lines.append("PARAM\t%s\t%s\t%s\t\t1\t1\t\t1\t0" % (guid, name, dtype))
    return ("\r\n".join(lines) + "\r\n").encode("utf-16")


def shipped_shared():
    with open(CONFIG, encoding="utf-8") as fh:
        data = json.load(fh)
    shared = data["shared_parameters"]
    return shared["group"], [(p["guid"], p["name"], p["data_type"]) for p in shared["parameters"]]


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def build(self, file_params, dict_params=None, file_group=None, dict_group=None, file_raw=None):
        """Write a fake shared file and a dictionary that claims the same hash.

        file_params: what the FILE contains. dict_params: what the DICTIONARY contains
        (defaults to file_params). The dictionary's source hash is the hash of the file
        it was built from, so only deliberate differences are reported.
        """
        base_group, base_params = shipped_shared()
        dict_params = file_params if dict_params is None else dict_params
        group = base_group if file_group is None else file_group
        raw = file_raw if file_raw is not None else encode_file(group, file_params)
        path = os.path.join(self.dir, "fake_shared.txt")
        with open(path, "wb") as fh:
            fh.write(raw)
        data = json.loads(open(CONFIG, encoding="utf-8").read())
        data["shared_parameters"]["source_sha256"] = hashlib.sha256(raw).hexdigest()
        data["shared_parameters"]["group"] = base_group if dict_group is None else dict_group
        data["shared_parameters"]["parameters"] = [
            {"name": n, "guid": g, "data_type": t} for g, n, t in dict_params]
        return validate_dictionary(data), path, raw


class PositiveTest(Case):
    def test_matching_fixture_passes_both_directions(self):
        dictionary, path, _ = self.build(shipped_shared()[1])
        verify_against_shared_file(dictionary, path)  # no exception

    def test_every_name_maps_to_its_guid_and_type(self):
        group, params = shipped_shared()
        dictionary, path, _ = self.build(params)
        file = parse_shared_bytes(open(path, "rb").read())
        by_name = {p.name: p for p in file.params}
        for guid, name, dtype in params:
            with self.subTest(name=name):
                self.assertEqual(by_name[name].guid.lower(), guid)
                self.assertEqual(by_name[name].data_type, dtype)

    def test_every_guid_maps_back_to_its_name(self):
        group, params = shipped_shared()
        dictionary, path, _ = self.build(params)
        file = parse_shared_bytes(open(path, "rb").read())
        name_by_guid = {p.guid.lower(): p.name for p in file.params}
        for guid, name, _ in params:
            with self.subTest(guid=guid):
                self.assertEqual(name_by_guid[guid], name)

    def test_shipped_values_reproduce_the_source_bytes(self):
        # Encoding the shipped GUIDs/names/types in the source layout gives exactly the bytes
        # whose hash the dictionary records. So the dictionary values are byte-true to the source.
        group, params = shipped_shared()
        raw = encode_file(group, params)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), load_dictionary(CONFIG).shared.source_sha256)
        path = os.path.join(self.dir, "reproduced.txt")
        with open(path, "wb") as fh:
            fh.write(raw)
        verify_against_shared_file(load_dictionary(CONFIG), path)


class NegativeTest(Case):
    """Each deliberate difference must be detected."""

    def setUp(self):
        super().setUp()
        self.group, self.params = shipped_shared()

    def expect(self, pattern, **kw):
        dictionary, path, _ = self.build(**kw)
        with self.assertRaisesRegex(DictionaryError, pattern):
            verify_against_shared_file(dictionary, path)

    def test_dictionary_has_extra_parameter_that_file_lacks(self):
        # Dictionary has the 16 names; the file is missing SCADA_備註 (dictionary-side extra).
        file_params = [p for p in self.params if p[1] != "SCADA_備註"]
        self.expect("dictionary has SCADA_備註 but the file does not", file_params=file_params,
                    dict_params=self.params)

    def test_dictionary_lacks_parameter_that_file_has(self):
        # File has an extra parameter the dictionary does not know.
        file_params = self.params + [("11111111-2222-4333-8444-555555555555", "SCADA_多出的", "TEXT")]
        self.expect("file has SCADA_多出的 but the dictionary does not", file_params=file_params,
                    dict_params=self.params)

    def test_guid_changed_in_dictionary(self):
        dict_params = list(self.params)
        guid, name, dtype = dict_params[0]
        dict_params[0] = ("00000000-0000-4000-8000-000000000000", name, dtype)
        self.expect("GUID differs for SCADA_編號", file_params=self.params, dict_params=dict_params)

    def test_guid_changed_in_file(self):
        file_params = list(self.params)
        guid, name, dtype = file_params[3]
        file_params[3] = ("00000000-0000-4000-8000-000000000001", name, dtype)
        self.expect("GUID differs for", file_params=file_params, dict_params=self.params)

    def test_names_swapped_between_two_guids(self):
        file_params = list(self.params)
        (g0, n0, t0), (g1, n1, t1) = file_params[0], file_params[1]
        file_params[0], file_params[1] = (g1, n0, t0), (g0, n1, t1)  # same names, GUIDs crossed
        self.expect("GUID differs for|is SCADA_", file_params=file_params, dict_params=self.params)

    def test_data_type_differs(self):
        file_params = list(self.params)
        guid, name, _ = file_params[5]
        file_params[5] = (guid, name, "NUMBER")
        self.expect("data type differs for SCADA_機櫃類型", file_params=file_params, dict_params=self.params)

    def test_file_changed_after_dictionary_was_built(self):
        dictionary, path, raw = self.build(self.params)
        changed = raw.replace("SCADA_編號".encode("utf-16-le"), "SCADA_编号".encode("utf-16-le"))
        with open(path, "wb") as fh:
            fh.write(changed)
        with self.assertRaisesRegex(DictionaryError, "source file changed"):
            verify_against_shared_file(dictionary, path)

    def test_group_name_differs(self):
        self.expect("group 'SCADA_SoW_V6' not in the file", file_params=self.params, file_group="OTHER_GROUP")

    def test_file_without_utf16_bom_is_rejected(self):
        dictionary, path, _ = self.build(self.params)
        with open(path, "wb") as fh:
            fh.write(encode_file(self.group, self.params)[2:])  # strip the BOM
        with self.assertRaisesRegex(DictionaryError, "UTF-16"):
            verify_against_shared_file(dictionary, path)

    def test_file_with_no_params_is_rejected(self):
        dictionary, path, _ = self.build(self.params)
        with open(path, "wb") as fh:
            fh.write(encode_file(self.group, []))
        with self.assertRaises(DictionaryError):
            verify_against_shared_file(dictionary, path)


class ParserTest(unittest.TestCase):
    def test_bad_guid_in_file_is_not_silently_accepted(self):
        # Parser keeps the text; the dictionary comparison then fails.
        raw = encode_file("G", [("not-a-guid", "SCADA_編號", "TEXT")])
        self.assertEqual(parse_shared_bytes(raw).params[0].guid, "not-a-guid")

    def test_short_param_line_rejected(self):
        raw = ("\r\n".join(["GROUP\t1\tG", "PARAM\tonly-guid"]) + "\r\n").encode("utf-16")
        with self.assertRaisesRegex(SharedFileError, "PARAM needs"):
            parse_shared_bytes(raw)

    def test_sha256_is_of_raw_bytes(self):
        raw = encode_file("G", [("81bdc77b-c362-4012-aa80-6edd256f9b09", "SCADA_編號", "TEXT")])
        self.assertEqual(parse_shared_bytes(raw).sha256, hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
