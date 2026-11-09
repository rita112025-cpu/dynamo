"""Build the dialog compatibility test as a Dynamo .dyn (out/, deterministic, never overwritten).

    python tools/dialog_test/make_dialog_test_dyn.py              # writes out/dialog_compat_test_<timestamp>.dyn
    python tools/dialog_test/make_dialog_test_dyn.py -o <folder>  # never an existing Dynamo tool folder

The .dyn has one CPython3 node (dialog_compat_test.py, unchanged), one string input (mode, left blank),
and one Watch. Node ids are uuid5 of the source hash, so two builds give byte-identical content.
Only the file name carries the build time.

The node source is checked here with the rules below (own rules; tools/reader_rules.py is not used).
These rules guard against accidents. They are not a sandbox.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

DIALOG_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(DIALOG_DIR)
ROOT = os.path.dirname(TOOLS)
SOURCE = os.path.join(DIALOG_DIR, "dialog_compat_test.py")
DEFAULT_OUT = os.path.join(ROOT, "out")
NAMESPACE = uuid.UUID("3c1f9a7e-5b2d-4e08-9a64-2d7b1c0e8f41")  # fixed: ids are reproducible
DYNAMO_VERSION = "3.3.2.11986"  # the version recorded in the project's existing Dynamo files
PROTECTED_FOLDERS = ("批次填參數", "批次複製視圖樣板", "批次參數工具", "批次工作集", "Excel參數同步")
REFERENCE_PYTHON_NODE_KEYS = frozenset({
    "Code", "ConcreteType", "Description", "Engine", "Id", "Inputs",
    "NodeType", "Outputs", "Replication", "VariableInputPorts",
})
_DRIVE_JSON = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\\\[A-Za-z0-9_一-鿿]")
_DRIVE_RAW = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?=[A-Za-z0-9_一-鿿])")

ALLOWED_IMPORTS = {"clr", "ctypes", "os", "sys", "System", "System.Windows.Forms",
                   "System.Threading", "System.Diagnostics"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "DocumentManager",
                   "TransactionManager", "Transaction", "SubTransaction", "TransactionGroup",
                   "Document", "UIDocument", "FilteredElementCollector", "RevitServices",
                   "shutil", "tempfile", "importlib", "builtins"}
OS_WRITE_FUNCTIONS = {"makedirs", "mkdir", "remove", "unlink", "rmdir", "removedirs", "rename",
                      "renames", "replace", "symlink", "link", "chmod", "utime", "truncate"}
FORBIDDEN_ATTRIBUTES = {"Save", "SaveAs", "SynchronizeWithCentral", "Delete", "Create",
                        "SetValueString", "Commit", "RollBack", "OpenDocumentFile"}


class DialogBuildError(RuntimeError):
    """The dialog test .dyn cannot be built or written safely."""


def node_rule_findings(source: str) -> List[Tuple[int, str]]:
    tree = ast.parse(source)
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    found.append((node.lineno, "import " + alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "") not in ALLOWED_IMPORTS:
                found.append((node.lineno, "from %s import ..." % node.module))
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                found.append((node.lineno, "name " + node.id))
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in OS_WRITE_FUNCTIONS:
                found.append((node.lineno, "os." + node.attr + " changes the file system"))
            elif node.attr in FORBIDDEN_ATTRIBUTES:
                found.append((node.lineno, "call or access ." + node.attr))
    return sorted(set(found))


def load_source() -> str:
    with open(SOURCE, encoding="utf-8") as fh:
        source = fh.read()
    ast.parse(source)
    findings = node_rule_findings(source)
    if findings:
        raise DialogBuildError("node source breaks the dialog test rules: " + "; ".join(
            "line %d: %s" % item for item in findings))
    return source


def _gid(key: str) -> str:
    return uuid.uuid5(NAMESPACE, key).hex


def _port(key: str, name: str, desc: str) -> Dict:
    return {"Id": _gid(key), "Name": name, "Description": desc, "UsingDefaultValue": False,
            "Level": 2, "UseLevels": False, "KeepListStructure": False}


def build_dyn_dict(source: str) -> Dict:
    seed = hashlib.sha256(source.encode("utf-8")).hexdigest()
    input_key, input_label = "mode", "IN[0] 模式：留空 / no-owner / owner"
    py_in = _port(seed + ":py:in0", "IN[0]", "Input #0")
    input_node_id = _gid(seed + ":input:mode")
    input_out = _port(seed + ":input:mode:out", "", "String")
    input_node = {"ConcreteType": "CoreNodeModels.Input.StringInput, CoreNodeModels",
                  "NodeType": "StringInputNode", "InputValue": "", "Id": input_node_id,
                  "Inputs": [], "Outputs": [input_out], "Replication": "Disabled",
                  "Description": "Creates a string. Leave blank, or no-owner / owner."}
    py_id = _gid(seed + ":python")
    py_out = _port(seed + ":python:out", "OUT", "Result")
    py = {"ConcreteType": "PythonNodeModels.PythonNode, PythonNodeModels",
          "Code": source, "Engine": "CPython3", "VariableInputPorts": True,
          "Id": py_id, "NodeType": "PythonScriptNode", "Inputs": [py_in], "Outputs": [py_out],
          "Replication": "Disabled", "Description": "Dialog compatibility test (no Revit, no file writes)."}
    watch_id = _gid(seed + ":watch")
    watch_in = _port(seed + ":watch:in", "", "Node to show")
    watch = {"ConcreteType": "CoreNodeModels.Watch, CoreNodeModels", "WatchWidth": 600.0,
             "WatchHeight": 500.0, "Id": watch_id, "NodeType": "ExtensionNode",
             "Inputs": [watch_in], "Outputs": [_port(seed + ":watch:out", "", "Node output")],
             "Replication": "Disabled", "Description": "Shows the dialog test lines"}
    connectors = [
        {"Start": input_out["Id"], "End": py_in["Id"], "Id": _gid(seed + ":connector:in"), "IsHidden": "False"},
        {"Start": py_out["Id"], "End": watch_in["Id"], "Id": _gid(seed + ":connector:watch"), "IsHidden": "False"},
    ]
    views = [
        {"Id": input_node_id, "Name": input_label, "IsSetAsInput": False, "IsSetAsOutput": False,
         "Excluded": False, "ShowGeometry": True, "X": 0.0, "Y": 0.0},
        {"Id": py_id, "Name": "Dialog compatibility test", "IsSetAsInput": False, "IsSetAsOutput": False,
         "Excluded": False, "ShowGeometry": True, "X": 520.0, "Y": 0.0},
        {"Id": watch_id, "Name": "Result", "IsSetAsInput": False, "IsSetAsOutput": False,
         "Excluded": False, "ShowGeometry": True, "X": 900.0, "Y": 0.0},
    ]
    return {
        "Uuid": str(uuid.uuid5(NAMESPACE, seed + ":workspace")),
        "IsCustomNode": False, "Description": "Dialog compatibility test (test only)",
        "Name": "dialog_compat_test", "ElementResolver": {"ResolutionMap": {}}, "Inputs": [], "Outputs": [],
        "Nodes": [input_node, py, watch], "Connectors": connectors, "Dependencies": [],
        "NodeLibraryDependencies": [], "Bindings": [],
        "View": {
            "Dynamo": {"ScaleFactor": 1.0, "HasRunWithoutCrash": False, "IsVisibleInDynamoLibrary": True,
                       "Version": DYNAMO_VERSION, "RunType": "Manual", "RunPeriod": "1000"},
            "Camera": {"Name": "_Background Preview", "EyeX": -17.0, "EyeY": 24.0, "EyeZ": 50.0,
                       "LookX": 12.0, "LookY": -13.0, "LookZ": -58.0, "UpX": 0.0, "UpY": 1.0, "UpZ": 0.0},
            "ConnectorPins": [], "NodeViews": views, "Annotations": [], "X": 0.0, "Y": 0.0, "Zoom": 1.0,
        },
    }


def build_text(source: Optional[str] = None) -> str:
    source = load_source() if source is None else source
    text = json.dumps(build_dyn_dict(source), ensure_ascii=False, indent=2) + "\n"
    root_escaped = os.path.realpath(ROOT).replace("\\", "\\\\")
    if (_DRIVE_JSON.search(text) or _DRIVE_RAW.search(source) or os.path.realpath(ROOT) in text
            or root_escaped in text):
        raise DialogBuildError("the dialog test .dyn would contain a drive-letter or build-machine path")
    return text


def _protected_hit(out_dir: str) -> Optional[str]:
    target = os.path.normcase(os.path.realpath(out_dir))
    parent = os.path.dirname(ROOT)
    for folder in PROTECTED_FOLDERS:
        guarded = os.path.normcase(os.path.realpath(os.path.join(parent, folder)))
        if target == guarded or target.startswith(guarded + os.sep):
            return folder
    return None


def write_dialog_dyn(out_dir: str, stamp: Optional[str] = None) -> str:
    if not os.path.isabs(out_dir):
        raise DialogBuildError("output folder must be an absolute path")
    hit = _protected_hit(out_dir)
    if hit:
        raise DialogBuildError("refusing to write into the existing tool folder %r" % hit)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") if stamp is None else stamp
    path = os.path.join(out_dir, "dialog_compat_test_%s.dyn" % stamp)
    text = build_text()
    try:
        fh = open(path, "x", encoding="utf-8", newline="\n")
    except FileExistsError as ex:
        raise DialogBuildError("refusing to overwrite an existing file: " + path) from ex
    with fh:
        fh.write(text)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        path = write_dialog_dyn(os.path.abspath(args.out))
    except DialogBuildError as ex:
        print("BUILD FAILED: %s" % ex, file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
