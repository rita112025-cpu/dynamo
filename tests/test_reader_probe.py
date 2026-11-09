"""Acceptance for the read-only Revit API probe.

Automatic: reader AST rules (positive and negative cases), probe constants equal the dictionary,
deterministic .dyn build, the completeness-check .dyn is unchanged, and a run of the probe under
Dynamo's embedded Python 3.9.12 with FAKE Revit modules (refusals, report written, no forbidden call).
The real Revit run is a manual step documented in docs/reader_probe.md.
"""
import ast
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "probe"))
sys.path.insert(0, ROOT)

import make_dyn  # noqa: E402
import make_probe_dyn  # noqa: E402
from reader_rules import reader_forbidden_uses  # noqa: E402

PROBE = os.path.join(ROOT, "tools", "probe", "reader_api_probe.py")
CONFIG = os.path.join(ROOT, "config", "parameter_dictionary.json")
PY39 = os.path.join(os.environ.get("LOCALAPPDATA", ""), "python-3.9.12-embed-amd64", "python.exe")
HAVE_PY39 = os.path.isfile(PY39)
COMPLETENESS_DYN_SHA256 = "b6143d78084f041f6cc34c811fe72cf451215f1ac17f904a1c18aff4bb82e4a5"


class ReaderRulesTest(unittest.TestCase):
    def test_write_and_transaction_calls_are_caught(self):
        for snippet in (
            "t = Transaction(doc)\n",
            "tm = TransactionManager.Instance\n",
            "p.Set.Overloads[String](v)\n",
            "p.SetValueString(v)\n",
            "doc.Save()\n",
            "doc.SaveAs(path)\n",
            "doc.SynchronizeWithCentral(a, b)\n",
            "doc.Delete(eid)\n",
            "doc.Create.NewFamilyInstance(a, b, c)\n",
            "doc.Close(False)\n",
            "OpenDocumentFile(path)\n",
            "doc.Application.OpenDocumentFile(path)\n",
            "sub = SubTransaction(doc)\n",
            "t.Commit()\n",
            "t.RollBack()\n",
            "doc.Regenerate()\n",
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(reader_forbidden_uses(snippet), "not caught")

    def test_ui_io_and_imports_are_caught(self):
        for snippet in (
            "from Autodesk.Revit.UI import TaskDialog\n",
            "import System.IO\n",
            "from System.IO import File\n",
            "from RevitServices.Transactions import TransactionManager\n",
            "from Autodesk.Revit.DB import Transaction\n",
            "from Autodesk.Revit.DB import ElementTransformUtils\n",
            "from System import Windows\n",
            "import importlib\n",
            "clr.AddReference('System.Windows.Forms')\n",
            "clr.Foo\n",
            "x = clr\n",
            "import socket\n",
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(reader_forbidden_uses(snippet), "not caught")

    def test_file_deletion_and_dynamic_access_are_caught(self):
        for snippet in (
            "import os\nos.remove('x')\n",
            "import os\nos.rmdir('x')\n",
            "getattr(x, 'Save')()\n",
            "getattr(doc, name)\n",
            "setattr(x, 'a', 1)\n",
            "delattr(x, 'a')\n",
            "eval('1')\n",
            "exec('x')\n",
            "__import__('clr')\n",
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(reader_forbidden_uses(snippet), "not caught")

    def test_allowed_read_only_use_passes(self):
        for snippet in (
            "from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory\n",
            "from System import Guid\n",
            "from RevitServices.Persistence import DocumentManager\n",
            "clr.AddReference('RevitAPI')\n",
            "import os\nos.replace('a', 'b')\n",
            "import json\nimport hashlib\nfrom datetime import datetime\n",
            "v = getattr(BuiltInCategory, key)\n",
            "ok = hasattr(el, 'Symbol')\n",
            "items.remove(3)\n",
        ):
            with self.subTest(snippet=snippet):
                self.assertEqual(reader_forbidden_uses(snippet), [])

    def test_comments_docstrings_and_strings_are_not_flagged(self):
        source = (
            '"""Never call Save, SaveAs, Transaction or clr here."""\n'
            "# Set, SetValueString, Delete, eval and exec are only words in this comment\n"
            'label = "Transaction then SynchronizeWithCentral"\n'
            "text = 'Autodesk.Revit.UI and System.IO are text here'\n"
        )
        self.assertEqual(reader_forbidden_uses(source), [])

    def test_existing_base_and_strict_rules_are_untouched(self):
        # The new module must not change the existing rule sets' verdicts on existing products.
        from dyn_checks import forbidden_uses as base_rules  # noqa: E402
        self.assertTrue(base_rules("import clr\n"))
        self.assertEqual(base_rules('exec(compile("x", "f", "exec"))\n'), [])


class ProbeSourceTest(unittest.TestCase):
    def setUp(self):
        with open(PROBE, encoding="utf-8") as fh:
            self.source = fh.read()

    def test_probe_passes_the_reader_rules(self):
        self.assertEqual(reader_forbidden_uses(self.source), [])

    def test_probe_parses(self):
        ast.parse(self.source)

    def test_shared_parameter_constants_equal_the_dictionary(self):
        with open(CONFIG, encoding="utf-8") as fh:
            config = json.load(fh)
        expected = [(p["name"], p["guid"]) for p in config["shared_parameters"]["parameters"]]
        tree = ast.parse(self.source)
        found = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SHARED_PARAMETERS" for t in node.targets):
                found = ast.literal_eval(node.value)
        self.assertIsNotNone(found)
        self.assertEqual(list(found), expected)

    def test_probe_contains_no_drive_letter_path(self):
        self.assertIsNone(make_probe_dyn._DRIVE_RAW.search(self.source))


class ProbeBuildTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_two_builds_are_byte_identical(self):
        a = make_probe_dyn.write_probe_dyn(os.path.join(self.dir, "a"), stamp="19700101-000000")
        b = make_probe_dyn.write_probe_dyn(os.path.join(self.dir, "b"), stamp="19700101-000000")
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())

    def test_probe_node_carries_the_probe_source_unchanged(self):
        text = make_probe_dyn.build_text()
        data = json.loads(text)
        code = next(n["Code"] for n in data["Nodes"] if n.get("NodeType") == "PythonScriptNode")
        with open(PROBE, encoding="utf-8") as fh:
            self.assertEqual(code, fh.read())

    def test_probe_node_has_no_engine_name_and_two_inputs(self):
        data = json.loads(make_probe_dyn.build_text())
        py = next(n for n in data["Nodes"] if n.get("NodeType") == "PythonScriptNode")
        self.assertNotIn("EngineName", py)
        self.assertEqual(py["Engine"], "CPython3")
        strings = [n for n in data["Nodes"] if n.get("NodeType") == "StringInputNode"]
        self.assertEqual(len(strings), 2)
        self.assertTrue(all(n["InputValue"] == "" for n in strings))

    def test_refuses_existing_dynamo_tool_folders(self):
        parent = os.path.dirname(ROOT)
        with self.assertRaisesRegex(make_probe_dyn.ProbeBuildError, "existing tool folder"):
            make_probe_dyn.write_probe_dyn(os.path.join(parent, "批次填參數"), stamp="19700101-000001")

    def test_refuses_overwrite(self):
        make_probe_dyn.write_probe_dyn(self.dir, stamp="19700101-000002")
        with self.assertRaisesRegex(make_probe_dyn.ProbeBuildError, "refusing to overwrite"):
            make_probe_dyn.write_probe_dyn(self.dir, stamp="19700101-000002")

    def test_relative_folder_refused(self):
        with self.assertRaisesRegex(make_probe_dyn.ProbeBuildError, "absolute"):
            make_probe_dyn.write_probe_dyn("out", stamp="19700101-000003")

    def test_completeness_check_dyn_is_unchanged(self):
        text, _, _, _ = make_dyn.build_text()
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), COMPLETENESS_DYN_SHA256)


FAKE_RUNNER = r'''
import json
import sys
import types

probe_path, model_in, folder_in, doc_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
forbidden_log = []
FORBIDDEN = {"Save", "SaveAs", "SynchronizeWithCentral", "Close", "Delete", "Create", "Set",
             "SetValueString", "OpenDocumentFile", "Commit", "RollBack", "Start", "Regenerate"}


class Meta(type):
    def __getattr__(cls, name):
        return name


def module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class BuiltInCategory(metaclass=Meta):
    pass


class BuiltInParameter(metaclass=Meta):
    pass


class StorageType(metaclass=Meta):
    pass


class ElementId(metaclass=Meta):
    pass


class ModelPathUtils(metaclass=Meta):
    pass


class FilteredElementCollector:
    def __init__(self, doc):
        pass

    def OfCategory(self, b):
        return self

    def OfClass(self, c):
        return self

    def WhereElementIsNotElementType(self):
        return self

    def WhereElementIsElementType(self):
        return self

    def __iter__(self):
        return iter([])


class FilteredWorksetCollector(FilteredElementCollector):
    pass


class RevitLinkInstance:
    pass


class DocumentManager:
    class _Instance:
        CurrentDBDocument = None
    Instance = _Instance()


class FakeApp:
    VersionNumber = "2025"  # VersionName deliberately missing: the probe must record it and go on


class FakeDoc:
    def __init__(self, path):
        self.PathName = path
        self.Title = "fake test model"
        self.IsWorkshared = False
        self.IsModified = False
        self.Application = FakeApp()

    def GetElement(self, _):
        return None

    def GetWorksetTable(self):
        raise RuntimeError("fake: no workset table")

    def __getattr__(self, name):
        if name in FORBIDDEN:
            def refused(*args, **kwargs):
                forbidden_log.append(name)
                raise RuntimeError("forbidden call reached: " + name)
            return refused
        raise AttributeError(name)


class Guid:
    def __init__(self, text):
        self.text = text


class _Clr:
    @staticmethod
    def AddReference(name):
        return None


sys.modules["clr"] = _Clr
module("Autodesk")
module("Autodesk.Revit")
module("Autodesk.Revit.DB", FilteredElementCollector=FilteredElementCollector,
       FilteredWorksetCollector=FilteredWorksetCollector, BuiltInCategory=BuiltInCategory,
       BuiltInParameter=BuiltInParameter, StorageType=StorageType, ElementId=ElementId,
       ModelPathUtils=ModelPathUtils, RevitLinkInstance=RevitLinkInstance)
module("RevitServices")
module("RevitServices.Persistence", DocumentManager=DocumentManager)
module("System", Guid=Guid)
DocumentManager.Instance.CurrentDBDocument = FakeDoc(doc_path)

src = open(probe_path, encoding="utf-8").read()
ns = {"IN": [model_in, folder_in]}
exec(compile(src, "probe.py", "exec"), ns)
print(json.dumps({"OUT": ns["OUT"], "forbidden_calls": forbidden_log}, ensure_ascii=False))
'''


@unittest.skipUnless(HAVE_PY39, "Dynamo embedded Python 3.9.12 not found")
class ProbeRunTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.runner = os.path.join(self.dir, "fake_runner.py")
        with open(self.runner, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(FAKE_RUNNER)
        self.model = os.path.join(self.dir, "TEST-model.rvt")
        self.folder = os.path.join(self.dir, "out")
        os.makedirs(self.folder)
        self.work = os.path.join(self.dir, "work")
        os.makedirs(self.work)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_probe(self, doc_path, model_in=None, folder_in=None):
        args = [PY39, "-I", self.runner, PROBE,
                self.model if model_in is None else model_in,
                self.folder if folder_in is None else folder_in,
                doc_path]
        return subprocess.run(args, cwd=self.work, capture_output=True, text=True, encoding="utf-8")

    def reports(self):
        return sorted(glob.glob(os.path.join(self.folder, "reader_probe_*.json")))

    def test_refuses_unsaved_document(self):
        r = self.run_probe("")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUSED", r.stderr)
        self.assertIn("not saved", r.stderr)
        self.assertEqual(self.reports(), [])

    def test_refuses_a_different_document(self):
        r = self.run_probe(os.path.join(self.dir, "OTHER-model.rvt"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUSED", r.stderr)
        self.assertEqual(self.reports(), [])

    def test_refuses_when_inputs_are_empty(self):
        r = self.run_probe(self.model, model_in="")
        self.assertIn("NOT RUN", r.stderr)
        r = self.run_probe(self.model, folder_in="")
        self.assertIn("NOT RUN", r.stderr)
        self.assertEqual(self.reports(), [])

    def test_runs_on_the_matching_document_and_writes_one_report(self):
        r = self.run_probe(self.model)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["forbidden_calls"], [], "a write-type API was reached")
        self.assertTrue(any("reader API probe" in line for line in out["OUT"]))
        files = self.reports()
        self.assertEqual(len(files), 1)
        with open(files[0], encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(report["environment"]["path_name"], self.model)
        self.assertGreater(report["summary"]["steps"], 0)
        # The missing API is recorded with its exception type; the run was not aborted by it.
        failed = [rec for rec in report["records"] if rec.get("ok") is False]
        self.assertTrue(any(rec["name"] == "Application.VersionName" and "AttributeError" in rec["exception"]
                            for rec in failed), failed[:3])
        self.assertIsNone(report["environment"]["version_name"])
        self.assertEqual(report["environment"]["version_number"], "2025")

    def test_second_run_never_overwrites_the_first_report(self):
        first = self.run_probe(self.model)
        self.assertEqual(first.returncode, 0, first.stderr)
        before = open(self.reports()[0], "rb").read()
        second = self.run_probe(self.model)
        self.assertEqual(open(self.reports()[0], "rb").read(), before)
        self.assertTrue(second.returncode == 0 or "already exists" in second.stderr, second.stderr)


if __name__ == "__main__":
    unittest.main()
