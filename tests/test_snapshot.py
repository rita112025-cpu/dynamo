import json
import os
import shutil
import tempfile
import unittest

from mep_toolkit.snapshot import SCHEMA_VERSION, SnapshotError, load_snapshot, parse_snapshot, validate_elements

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def el(**kw):
    base = {"element_id": 1, "category": "OST_Conduit", "family_name": "F", "parameters": {"服務類型": "SCADA"}}
    base.update(kw)
    return base


class ElementsTest(unittest.TestCase):
    def test_valid_and_normalised(self):
        out = validate_elements([el()])
        self.assertIsNone(out[0]["read_error"])
        self.assertEqual(out[0]["parameters"], {"服務類型": "SCADA"})

    def test_returns_copy(self):
        src = [el()]
        out = validate_elements(src)
        out[0]["parameters"]["x"] = "y"
        self.assertNotIn("x", src[0]["parameters"])

    def test_null_family_name_allowed(self):
        self.assertIsNone(validate_elements([el(family_name=None)])[0]["family_name"])

    def test_null_parameter_value_means_absent_or_read_only(self):
        self.assertEqual(validate_elements([el(parameters={"a": None})])[0]["parameters"], {"a": None})

    def test_empty_string_is_present_but_blank(self):
        self.assertEqual(validate_elements([el(parameters={"a": ""})])[0]["parameters"], {"a": ""})

    def test_read_error_requires_empty_parameters(self):
        with self.assertRaisesRegex(SnapshotError, "parameters \\{\\}"):
            validate_elements([el(read_error="boom")])
        out = validate_elements([el(parameters={}, read_error="boom")])
        self.assertEqual(out[0]["read_error"], "boom")

    def test_read_error_null_or_omitted_is_ok(self):
        self.assertIsNone(validate_elements([el(read_error=None)])[0]["read_error"])
        self.assertIsNone(validate_elements([el()])[0]["read_error"])

    def test_missing_required_keys_rejected(self):
        for key in ("element_id", "category", "family_name", "parameters"):
            with self.subTest(missing=key):
                e = el()
                del e[key]
                with self.assertRaisesRegex(SnapshotError, "missing key"):
                    validate_elements([e])

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
            ([el(parameters={"a": 5})], "must be a string or null"),
            ([el(parameters={"a": True})], "must be a string or null"),
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
        src, els = parse_snapshot({"schema_version": 1, "source_file": r"D:\fake\a.rvt", "elements": [el()]})
        self.assertEqual(src, r"D:\fake\a.rvt")
        self.assertEqual(len(els), 1)

    def test_version_must_match_exactly(self):
        for v in (0, 2, "1", 1.0, True, None):
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

    def test_shipped_sample_loads(self):
        src, els = load_snapshot(os.path.join(ROOT, "examples", "sample_snapshot.json"))
        self.assertTrue(src.startswith("D:\\fake\\"))
        self.assertGreater(len(els), 5)

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
