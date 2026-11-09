import json
import os
import shutil
import tempfile
import unittest

from mep_toolkit.snapshot import SnapshotError, load_snapshot, parse_snapshot, validate_elements

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def el(**kw):
    base = {"element_id": 1, "category": "OST_Conduit", "family_name": "F", "parameters": {"服務類型": "SCADA"}}
    base.update(kw)
    return base


class ElementsTest(unittest.TestCase):
    def test_valid_and_normalised(self):
        out = validate_elements([el()])
        self.assertEqual(out[0]["read_error"], None)
        self.assertEqual(out[0]["parameters"], {"服務類型": "SCADA"})

    def test_returns_copy(self):
        src = [el()]
        out = validate_elements(src)
        out[0]["parameters"]["x"] = "y"
        self.assertNotIn("x", src[0]["parameters"])

    def test_null_parameter_value_allowed(self):
        self.assertEqual(validate_elements([el(parameters={"a": None})])[0]["parameters"], {"a": None})

    def test_bad_elements(self):
        cases = [
            ("not a list", "must be a list"),
            ([1], "must be an object"),
            ([el(element_id="1")], "element_id must be an int"),
            ([el(element_id=True)], "element_id must be an int"),
            ([el(), el()], "duplicate element_id"),
            ([el(category="")], "category"),
            ([el(family_name=5)], "family_name"),
            ([el(parameters=[])], "parameters must be an object"),
            ([el(parameters={"a": 5})], "must be a string or null"),
            ([el(parameters={"": "x"})], "parameter names"),
            ([el(read_error="  ")], "read_error"),
            ([el(extra=1)], "unknown key"),
        ]
        for value, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(SnapshotError, pattern):
                    validate_elements(value)

    def test_missing_keys(self):
        with self.assertRaises(SnapshotError):
            validate_elements([{"element_id": 1}])


class DocumentTest(unittest.TestCase):
    def test_parse(self):
        src, els = parse_snapshot({"schema_version": 1, "source_file": r"D:\fake\a.rvt", "elements": [el()]})
        self.assertEqual(src, r"D:\fake\a.rvt")
        self.assertEqual(len(els), 1)

    def test_bad_documents(self):
        good = {"schema_version": 1, "source_file": "a.rvt", "elements": []}
        for change, pattern in (
            ({"schema_version": 2}, "schema_version"),
            ({"source_file": ""}, "source_file"),
            ({"source_file": None}, "source_file"),
            ({"elements": None}, "elements"),
            ({"extra": 1}, "unknown key"),
        ):
            with self.subTest(pattern=pattern):
                bad = dict(good, **change)
                with self.assertRaisesRegex(SnapshotError, pattern):
                    parse_snapshot(bad)
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
