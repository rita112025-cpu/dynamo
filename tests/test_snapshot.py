import os
import shutil
import tempfile
import unittest

from mep_toolkit.snapshot import SCHEMA_VERSION, SnapshotError, load_snapshot, parse_snapshot, validate_elements

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1_FIXTURE = os.path.join(ROOT, "examples", "legacy", "sample_snapshot_v1.json")


def el(**kw):
    base = {"element_id": 1, "category": "OST_Conduit", "family_name": "F",
            "parameters": {"服務類型": "SCADA"}, "read_only_parameters": []}
    base.update(kw)
    return base


class ElementsTest(unittest.TestCase):
    def test_version_is_two(self):
        self.assertEqual(SCHEMA_VERSION, 2)

    def test_valid_and_normalised(self):
        out = validate_elements([el()])
        self.assertIsNone(out[0]["read_error"])
        self.assertEqual(out[0]["parameters"], {"服務類型": "SCADA"})
        self.assertEqual(out[0]["read_only_parameters"], [])

    def test_returns_copy(self):
        src = [el()]
        out = validate_elements(src)
        out[0]["parameters"]["x"] = "y"
        self.assertNotIn("x", src[0]["parameters"])

    def test_null_family_name_allowed(self):
        self.assertIsNone(validate_elements([el(family_name=None)])[0]["family_name"])

    def test_absent_parameter_is_simply_not_a_key(self):
        out = validate_elements([el(parameters={})])
        self.assertNotIn("服務類型", out[0]["parameters"])

    def test_blank_is_empty_string(self):
        self.assertEqual(validate_elements([el(parameters={"a": ""})])[0]["parameters"], {"a": ""})

    def test_null_value_rejected_in_v2(self):
        with self.assertRaisesRegex(SnapshotError, "version 2 has no null values"):
            validate_elements([el(parameters={"a": None})])

    def test_read_only_must_name_present_parameters(self):
        with self.assertRaisesRegex(SnapshotError, "not in parameters"):
            validate_elements([el(read_only_parameters=["服務類型", "不存在"])])
        out = validate_elements([el(read_only_parameters=["服務類型"])])
        self.assertEqual(out[0]["read_only_parameters"], ["服務類型"])

    def test_read_only_no_duplicates(self):
        with self.assertRaisesRegex(SnapshotError, "duplicate"):
            validate_elements([el(read_only_parameters=["服務類型", "服務類型"])])

    def test_read_only_list_type(self):
        for bad in ("服務類型", None, [""], [1]):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(SnapshotError, "read_only_parameters must be a list"):
                    validate_elements([el(read_only_parameters=bad)])

    def test_read_error_requires_empty_parameters_and_read_only(self):
        with self.assertRaisesRegex(SnapshotError, "empty parameters"):
            validate_elements([el(read_error="boom")])
        with self.assertRaisesRegex(SnapshotError, "empty parameters"):
            validate_elements([el(read_error="boom", read_only_parameters=[])])
        out = validate_elements([el(parameters={}, read_only_parameters=[], read_error="boom")])
        self.assertEqual(out[0]["read_error"], "boom")

    def test_read_error_null_or_omitted_is_ok(self):
        self.assertIsNone(validate_elements([el(read_error=None)])[0]["read_error"])

    def test_missing_required_keys_rejected(self):
        for key in ("element_id", "category", "family_name", "parameters", "read_only_parameters"):
            with self.subTest(missing=key):
                e = el()
                del e[key]
                with self.assertRaisesRegex(SnapshotError, "missing key"):
                    validate_elements([e])

    def test_v1_style_element_fields_are_unknown_in_v2(self):
        with self.assertRaisesRegex(SnapshotError, "unknown key"):
            validate_elements([el(legacy_flag=True)])

    def test_bad_elements(self):
        cases = [
            ("not a list", "must be a list"),
            ([1], "must be an object"),
            ([el(element_id="1")], "element_id must be an int"),
            ([el(element_id=True)], "element_id must be an int"),
            ([el(element_id=1.0)], "element_id must be an int"),
            ([el(), el()], "duplicate element_id"),
            ([el(category="")], "category"),
            ([el(family_name=5)], "family_name"),
            ([el(parameters=[])], "parameters must be an object"),
            ([el(parameters={"a": 5})], "must be a string"),
            ([el(parameters={"a": True})], "must be a string"),
            ([el(parameters={"": "x"})], "parameter names"),
            ([el(read_error="  ")], "read_error must be a non-empty string"),
            ([el(read_error=3)], "read_error must be a non-empty string"),
            ([el(extra=1)], "unknown key"),
        ]
        for value, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(SnapshotError, pattern):
                    validate_elements(value)


class DocumentTest(unittest.TestCase):
    good = {"schema_version": SCHEMA_VERSION, "source_file": "a.rvt", "elements": []}

    def test_parse(self):
        src, els = parse_snapshot({"schema_version": 2, "source_file": r"D:\fake\a.rvt", "elements": [el()]})
        self.assertEqual(src, r"D:\fake\a.rvt")
        self.assertEqual(len(els), 1)

    def test_v2_sample_loads(self):
        src, els = load_snapshot(os.path.join(ROOT, "examples", "sample_snapshot.json"))
        self.assertTrue(src.startswith("D:\\fake\\"))
        self.assertEqual(len(els), 15)

    def test_real_v1_file_is_rejected_and_says_version_2(self):
        with self.assertRaisesRegex(SnapshotError, "needs version 2"):
            load_snapshot(V1_FIXTURE)

    def test_v1_document_rejected_even_with_v2_style_elements(self):
        doc = dict(self.good, schema_version=1, elements=[el()])
        with self.assertRaisesRegex(SnapshotError, "needs version 2"):
            parse_snapshot(doc)

    def test_version_must_be_exactly_two(self):
        for v in (0, 3, "2", 2.0, True, None):
            with self.subTest(version=v):
                with self.assertRaisesRegex(SnapshotError, "schema_version"):
                    parse_snapshot(dict(self.good, schema_version=v))

    def test_missing_document_keys_rejected(self):
        for key in ("schema_version", "source_file", "elements"):
            with self.subTest(missing=key):
                doc = dict(self.good)
                del doc[key]
                with self.assertRaisesRegex(SnapshotError, "missing key"):
                    parse_snapshot(doc)

    def test_bad_source_file(self):
        for v in ("", "   ", None, 5):
            with self.subTest(source=v):
                with self.assertRaisesRegex(SnapshotError, "source_file"):
                    parse_snapshot(dict(self.good, source_file=v))

    def test_unknown_document_key(self):
        with self.assertRaisesRegex(SnapshotError, "unknown key"):
            parse_snapshot(dict(self.good, extra=1))

    def test_not_an_object(self):
        with self.assertRaises(SnapshotError):
            parse_snapshot([])

    def test_invalid_json_file(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "s.json")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{")
            with self.assertRaisesRegex(SnapshotError, "not valid JSON"):
                load_snapshot(p)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
