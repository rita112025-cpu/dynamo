"""Acceptance for the embedded .dyn: determinism, AST checks, refusals, and a real run under the
Dynamo embedded Python 3.9.12 that is compared byte-for-byte with calling the core directly.

The run tests need %LOCALAPPDATA%\\python-3.9.12-embed-amd64\\python.exe; they are skipped if it is absent.
Nothing here touches Revit or the existing Dynamo tool folders.
"""
import ast
import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import make_dyn  # noqa: E402
from dyn_checks import forbidden_uses  # noqa: E402
from mep_toolkit import TOOL_VERSION  # noqa: E402
from mep_toolkit.completeness import check_completeness, write_completeness_reports  # noqa: E402
from mep_toolkit.dictionary import load_dictionary  # noqa: E402
from mep_toolkit.snapshot import load_snapshot  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "sample_snapshot.json")
CONFIG = os.path.join(ROOT, "config", "parameter_dictionary.json")
PY39 = os.path.join(os.environ.get("LOCALAPPDATA", ""), "python-3.9.12-embed-amd64", "python.exe")
HAVE_PY39 = os.path.isfile(PY39)

RUNNER = (
    "import json, sys\n"
    "src = open(sys.argv[1], encoding='utf-8').read()\n"
    "ns = {'IN': [sys.argv[2], sys.argv[3]]}\n"
    "exec(compile(src, 'node.py', 'exec'), ns)\n"
    "print(json.dumps(ns['OUT'], ensure_ascii=False))\n"
)


def node_code(dyn_text):
    data = json.loads(dyn_text)
    return next(n["Code"] for n in data["Nodes"] if n.get("NodeType") == "PythonScriptNode")


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_node(self, code, snapshot, out_dir):
        """Run the node program with Dynamo's embedded Python 3.9.12, in an isolated process
        whose working folder is empty (the toolkit is NOT importable from there)."""
        runner = os.path.join(self.dir, "runner.py")
        node = os.path.join(self.dir, "node.py")
        with open(runner, "w", encoding="utf-8") as fh:
            fh.write(RUNNER)
        with open(node, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(code)
        work = os.path.join(self.dir, "work")
        os.makedirs(work, exist_ok=True)
        return subprocess.run([PY39, "-I", runner, node, snapshot, out_dir], cwd=work,
                              capture_output=True, text=True, encoding="utf-8")


class AstRuleTest(unittest.TestCase):
    def test_real_calls_and_imports_are_caught(self):
        for snippet in (
            "import clr\n",
            "from Autodesk.Revit.DB import *\n",
            "import RevitAPI\n",
            "t = Transaction(doc)\n",
            "d.Save()\n",
            "d.SaveAs(path)\n",
            "d.SynchronizeWithCentral(a, b)\n",
            "e.Delete(eid)\n",
            "col = FilteredElementCollector(doc)\n",
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(forbidden_uses(snippet), "not caught")

    def test_text_that_only_mentions_the_words_is_not_flagged(self):
        source = (
            '"""Never call Save, SaveAs, Transaction or clr from here."""\n'
            "# SynchronizeWithCentral and Delete are described in this comment only\n"
            'label = "Transaction then SynchronizeWithCentral"\n'
            "message = 'Autodesk.Revit.DB is text here'\n"
            "import os\n"
            "os.remove('x')\n"
        )
        self.assertEqual(forbidden_uses(source), [])

    def test_shipped_modules_and_program_are_clean(self):
        for name, source in make_dyn.load_modules():
            with self.subTest(module=name):
                self.assertEqual(forbidden_uses(source), [])
        prog, _, _ = make_dyn.render_program(make_dyn.load_modules(), make_dyn.load_dictionary_text())
        self.assertEqual(forbidden_uses(prog), [])


class BuildTest(Case):
    def test_two_builds_are_byte_identical(self):
        a, b = os.path.join(self.dir, "a"), os.path.join(self.dir, "b")
        pa = make_dyn.write_dyn(a, stamp="20260101-000000")
        pb = make_dyn.write_dyn(b, stamp="20260101-000000")
        with open(pa, "rb") as fa, open(pb, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())

    def test_file_name_carries_stamp_and_content_has_no_build_time(self):
        p = make_dyn.write_dyn(self.dir, stamp="20260101-000001")
        self.assertTrue(os.path.basename(p).startswith("完整度檢查_20260101-000001"))
        text, _, _, _ = make_dyn.build_text()
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)

    def test_refuses_to_overwrite_existing_dyn(self):
        make_dyn.write_dyn(self.dir, stamp="20260101-000002")
        with self.assertRaisesRegex(make_dyn.BuildError, "refusing to overwrite"):
            make_dyn.write_dyn(self.dir, stamp="20260101-000002")

    def test_refuses_existing_dynamo_tool_folders(self):
        parent = os.path.dirname(ROOT)
        for folder in make_dyn.PROTECTED_FOLDERS:
            with self.subTest(folder=folder):
                with self.assertRaisesRegex(make_dyn.BuildError, "existing tool folder"):
                    make_dyn.write_dyn(os.path.join(parent, folder), stamp="20260101-000003")
                with self.assertRaisesRegex(make_dyn.BuildError, "existing tool folder"):
                    make_dyn.write_dyn(os.path.join(parent, folder, "sub"), stamp="20260101-000003")

    def test_relative_output_folder_refused(self):
        with self.assertRaisesRegex(make_dyn.BuildError, "absolute"):
            make_dyn.write_dyn("out", stamp="20260101-000004")

    def test_no_drive_letter_or_build_path_in_the_dyn(self):
        text, _, _, _ = make_dyn.build_text()
        self.assertIsNone(make_dyn._DRIVE_JSON.search(text))
        self.assertNotIn(os.path.realpath(ROOT), text)
        self.assertNotIn(os.path.realpath(ROOT).replace("\\", "\\\\"), text)

    def test_dyn_structure_two_empty_inputs_one_python_node(self):
        text, _, _, _ = make_dyn.build_text()
        data = json.loads(text)
        strings = [n for n in data["Nodes"] if n.get("NodeType") == "StringInputNode"]
        pythons = [n for n in data["Nodes"] if n.get("NodeType") == "PythonScriptNode"]
        self.assertEqual(len(strings), 2)
        self.assertTrue(all(n["InputValue"] == "" for n in strings))
        self.assertEqual(len(pythons), 1)
        self.assertEqual(pythons[0]["Engine"], "CPython3")
        self.assertEqual(len(pythons[0]["Inputs"]), 2)

    def test_ids_are_derived_not_random(self):
        a, _, _, _ = make_dyn.build_text()
        b, _, _, _ = make_dyn.build_text()
        self.assertEqual(a, b)


class EmbeddedContentTest(unittest.TestCase):
    def setUp(self):
        self.text, self.program, self.core, self.dict_hash = make_dyn.build_text()
        self.tree = ast.parse(self.program)

    def literal(self, name):
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
                return ast.literal_eval(node.value)
        raise AssertionError(name + " not found in the node program")

    def test_embedded_modules_equal_the_files_on_disk(self):
        embedded = self.literal("MODULE_SOURCES")
        on_disk = make_dyn.load_modules()
        self.assertEqual([n for n, _ in embedded], [n for n, _ in on_disk])
        for (name, src_e), (_, src_d) in zip(embedded, on_disk):
            self.assertEqual(src_e, src_d, name)

    def test_embedded_dictionary_equals_the_config_file(self):
        with open(CONFIG, encoding="utf-8") as fh:
            self.assertEqual(self.literal("DICTIONARY_JSON"), fh.read())

    def test_embedded_hashes_match_the_content(self):
        import hashlib
        self.assertEqual(self.literal("CORE_SHA256"), make_dyn.core_digest(self.literal("MODULE_SOURCES")))
        self.assertEqual(self.literal("DICTIONARY_SHA256"),
                         hashlib.sha256(self.literal("DICTIONARY_JSON").encode("utf-8")).hexdigest())

    def test_module_load_order_covers_every_file(self):
        self.assertEqual(set(make_dyn.MODULE_ORDER), set(n for n, _ in make_dyn.load_modules()))


# Keys of the Python node in a real Dynamo 3.3 workspace saved in this project
# (source: G:\Dynamo\批次填參數\BatchFillScadaParams.dyn, read only; the path is not used by tests).
# Stored here as a constant so the test does not depend on any real path.
REFERENCE_PYTHON_NODE_KEYS = frozenset({
    "Code", "ConcreteType", "Description", "Engine", "Id", "Inputs",
    "NodeType", "Outputs", "Replication", "VariableInputPorts",
})


class NodeFormatTest(unittest.TestCase):
    def setUp(self):
        self.text, _, _, _ = make_dyn.build_text()
        self.data = json.loads(self.text)

    def test_python_node_keys_match_the_reference_dynamo_file(self):
        py = [n for n in self.data["Nodes"] if n.get("NodeType") == "PythonScriptNode"]
        self.assertEqual(len(py), 1)
        self.assertEqual(frozenset(py[0].keys()), REFERENCE_PYTHON_NODE_KEYS)
        self.assertNotIn("EngineName", py[0])

    def test_input_nodes_are_not_set_as_inputs_because_no_reference_exists(self):
        # No Dynamo 3.3 file in this project sets an input node (IsSetAsInput), so the format
        # is not guessed. Documented in docs/dyn_build.md.
        views = [v for v in self.data["View"]["NodeViews"] if "StringInput" in v.get("Name", "") or
                 v.get("Name") in ("快照 JSON 完整路徑（必填）", "輸出資料夾完整路徑（必填，須已存在）")]
        self.assertEqual(len(views), 2)
        self.assertTrue(all(v["IsSetAsInput"] is False for v in views))
        self.assertEqual(self.data["Inputs"], [])


class StrictRuleTest(unittest.TestCase):
    """Module sources: no dynamic code and no dynamic attribute access."""

    def test_dynamic_calls_are_caught(self):
        for snippet in (
            'getattr(doc, "Save")()\n',
            'getattr(doc, name_variable)\n',
            'getattr(doc)\n',
            'setattr(doc, "SaveAs", 1)\n',
            'hasattr(doc, "SynchronizeWithCentral")\n',
            'builtins.getattr(x, "Save")\n',
            '__import__("clr")\n',
            'import importlib\nimportlib.import_module("clr")\n',
            'import builtins\n',
            'eval("1 + 1")\n',
            'exec("x = 1")\n',
            'code = compile("x", "f", "exec")\n',
            'f = getattr\n',
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(forbidden_uses(snippet, strict=True), "not caught")

    def test_plain_names_and_mentions_are_not_flagged(self):
        for snippet in (
            'getattr(x, "name")\n',
            'hasattr(x, "Name")\n',
            're.compile(r"a+")\n',             # regex constructor, not the builtin compile()
            'label = "eval exec compile getattr"\n',
            '# getattr(x, n); eval(s); __import__("clr")\n',
            '"""exec compile __import__ getattr(x, n)"""\n',
        ):
            with self.subTest(snippet=snippet):
                self.assertEqual(forbidden_uses(snippet, strict=True), [])

    def test_base_rules_do_not_apply_the_strict_builtins(self):
        # The node template uses exec(compile(...)) to register modules; base mode allows it.
        self.assertEqual(forbidden_uses('exec(compile("x", "f", "exec"))\n', strict=False), [])

    def test_shipped_modules_pass_the_strict_rules(self):
        for name, source in make_dyn.load_modules():
            with self.subTest(module=name):
                self.assertEqual(forbidden_uses(source, strict=True), [])


@unittest.skipUnless(HAVE_PY39, "Dynamo embedded Python 3.9.12 not found")
class NodeRunTest(Case):
    def setUp(self):
        super().setUp()
        self.text, self.program, self.core, self.dict_hash = make_dyn.build_text()

    def _files(self, out):
        return (sorted(glob.glob(os.path.join(out, "completeness_scope_*.csv"))),
                sorted(glob.glob(os.path.join(out, "completeness_findings_*.csv"))))

    def test_node_runs_and_reports_hashes_and_paths(self):
        out = os.path.join(self.dir, "out")
        os.makedirs(out)
        r = self.run_node(self.program, SAMPLE, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = json.loads(r.stdout.strip().splitlines()[-1])
        joined = "\n".join(lines)
        self.assertIn("core SHA-256 " + self.core, joined)
        self.assertIn("dictionary SHA-256 " + self.dict_hash, joined)
        self.assertIn("self-check: OK", joined)
        self.assertIn(TOOL_VERSION, joined)
        scope_files, findings_files = self._files(out)
        self.assertEqual(len(scope_files), 1)
        self.assertEqual(len(findings_files), 1)
        self.assertIn(scope_files[0], joined)
        self.assertIn(findings_files[0], joined)

    def test_node_output_is_byte_identical_to_calling_the_core_directly(self):
        out = os.path.join(self.dir, "out")
        os.makedirs(out)
        r = self.run_node(self.program, SAMPLE, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        scope_node, findings_node = self._files(out)
        with open(scope_node[0], encoding="utf-8-sig", newline="") as fh:
            run_time = datetime.fromisoformat(next(csv.DictReader(fh))["run_time"])
        # Same snapshot, same dictionary, same run time -> the core must give the same bytes.
        source, elements = load_snapshot(SAMPLE)
        result = check_completeness(elements, load_dictionary(CONFIG))
        core_dir = os.path.join(self.dir, "core")
        os.makedirs(core_dir)
        core_scope = os.path.join(core_dir, "scope.csv")
        core_findings = os.path.join(core_dir, "findings.csv")
        write_completeness_reports(result, core_findings, core_scope, source, run_time, TOOL_VERSION)
        for node_path, core_path in ((scope_node[0], core_scope), (findings_node[0], core_findings)):
            with open(node_path, "rb") as a, open(core_path, "rb") as b:
                self.assertEqual(a.read(), b.read(), os.path.basename(node_path))

    def test_empty_snapshot_path_says_not_run(self):
        out = os.path.join(self.dir, "out")
        os.makedirs(out)
        r = self.run_node(self.program, "", out)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("NOT RUN", r.stderr)
        self.assertIn("IN[0]", r.stderr)
        self.assertEqual(os.listdir(out), [])

    def test_empty_output_folder_says_not_run(self):
        r = self.run_node(self.program, SAMPLE, "")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("IN[1]", r.stderr)

    def test_missing_output_folder_is_not_created(self):
        missing = os.path.join(self.dir, "no_such_folder")
        r = self.run_node(self.program, SAMPLE, missing)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not exist", r.stderr)
        self.assertFalse(os.path.exists(missing))

    def test_second_run_never_overwrites_the_first_output(self):
        out = os.path.join(self.dir, "out")
        os.makedirs(out)
        first = self.run_node(self.program, SAMPLE, out)
        self.assertEqual(first.returncode, 0, first.stderr)
        scope_before = [open(p, "rb").read() for p in self._files(out)[0]]
        second = self.run_node(self.program, SAMPLE, out)
        for p, before in zip(self._files(out)[0], scope_before):
            with open(p, "rb") as fh:
                self.assertEqual(fh.read(), before)  # first file untouched
        # Either a new file with a later stamp, or a refusal because the name already exists.
        self.assertTrue(second.returncode == 0 or "already exists" in second.stderr, second.stderr)

    def test_tampered_embedded_core_is_refused(self):
        out = os.path.join(self.dir, "out")
        os.makedirs(out)
        tampered = self.program.replace("def check_completeness(", "def check_completeness_x(", 1)
        self.assertNotEqual(tampered, self.program)
        r = self.run_node(tampered, SAMPLE, out)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not match its build hash", r.stderr)
        self.assertEqual(os.listdir(out), [])

    def test_tampered_embedded_dictionary_is_refused(self):
        out = os.path.join(self.dir, "out")
        os.makedirs(out)
        tampered = self.program.replace('"SCADA"', '"SCADA "', 1)
        self.assertNotEqual(tampered, self.program)
        r = self.run_node(tampered, SAMPLE, out)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue("does not match" in r.stderr, r.stderr)


if __name__ == "__main__":
    unittest.main()
