"""Build a portable Dynamo .dyn that runs the completeness check (no Revit API).

    python tools/make_dyn.py                 # writes out/完整度檢查_<timestamp>.dyn
    python tools/make_dyn.py -o <folder>     # any folder EXCEPT the existing Dynamo tool folders

What goes into the .dyn:
  - the mep_toolkit modules, as source text, registered as real modules when the node runs;
  - the parameter dictionary JSON, as text;
  - the build hashes of both, which the node re-checks before it does anything;
  - two empty string inputs (snapshot path, output folder). No path is ever stored.

Determinism: node ids come from uuid5 of the content hashes, so two builds from the same source
give byte-identical .dyn content. Only the FILE NAME carries the build time.
Overwriting: a .dyn with the same name is never replaced; the build refuses.
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

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
PACKAGE = os.path.join(ROOT, "mep_toolkit")
DICTIONARY = os.path.join(ROOT, "config", "parameter_dictionary.json")
TEMPLATE = os.path.join(TOOLS, "node_template.txt")
DEFAULT_OUT = os.path.join(ROOT, "out")

sys.path.insert(0, ROOT)
sys.path.insert(0, TOOLS)
from mep_toolkit import TOOL_VERSION  # noqa: E402
from mep_toolkit.dictionary import validate_dictionary  # noqa: E402
from dyn_checks import assert_no_forbidden  # noqa: E402

# Load order: every module comes after the modules it imports.
MODULE_ORDER = (
    "mep_toolkit",
    "mep_toolkit.findings",
    "mep_toolkit.shared_params",
    "mep_toolkit.thresholds",
    "mep_toolkit.csv_report",
    "mep_toolkit.dictionary",
    "mep_toolkit.snapshot",
    "mep_toolkit.completeness",
)

DYN_NAME = "完整度檢查"
DYNAMO_VERSION = "3.3.2.11986"  # the version recorded in the existing Dynamo files of this project
NAMESPACE = uuid.UUID("6f1d2c3e-9a7b-4e21-8c55-0d4b7a9e1f20")  # fixed: ids are reproducible
# Existing Dynamo tool folders next to this toolkit; the build never writes into them.
PROTECTED_FOLDERS = ("批次填參數", "批次複製視圖樣板", "批次參數工具", "批次工作集", "Excel參數同步")
# A drive-letter path in plain source text, or in JSON-escaped text (doubled backslash).
_DRIVE_RAW = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?=[A-Za-z0-9_一-鿿])")
_DRIVE_JSON = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\\\[A-Za-z0-9_一-鿿]")


class BuildError(RuntimeError):
    """The .dyn cannot be built or written safely."""


def load_modules() -> List[Tuple[str, str]]:
    """(dotted name, source text) in MODULE_ORDER. The order must cover every .py file."""
    on_disk = set()
    for fname in os.listdir(PACKAGE):
        if fname.endswith(".py"):
            on_disk.add("mep_toolkit" if fname == "__init__.py" else "mep_toolkit." + fname[:-3])
    if on_disk != set(MODULE_ORDER):
        raise BuildError("MODULE_ORDER does not match mep_toolkit/*.py: missing %s, extra %s"
                         % (sorted(on_disk - set(MODULE_ORDER)), sorted(set(MODULE_ORDER) - on_disk)))
    out = []
    for name in MODULE_ORDER:
        path = os.path.join(PACKAGE, "__init__.py" if name == "mep_toolkit"
                            else name.split(".", 1)[1] + ".py")
        with open(path, encoding="utf-8") as fh:
            out.append((name, fh.read()))
    return out


def core_digest(modules: List[Tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for name, source in modules:
        h.update(name.encode("utf-8") + b"\0" + source.encode("utf-8") + b"\0")
    return h.hexdigest()


def load_dictionary_text() -> str:
    with open(DICTIONARY, encoding="utf-8") as fh:
        text = fh.read()
    validate_dictionary(json.loads(text))  # the embedded dictionary must be valid
    return text


def render_program(modules: List[Tuple[str, str]], dictionary_text: str) -> Tuple[str, str, str]:
    """Return (program text, core hash, dictionary hash)."""
    core = core_digest(modules)
    dict_hash = hashlib.sha256(dictionary_text.encode("utf-8")).hexdigest()
    with open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()
    replacements = [
        ('"__TOOL_VERSION__"', repr(TOOL_VERSION)),
        ('"__CORE_SHA256__"', repr(core)),
        ('"__DICTIONARY_SHA256__"', repr(dict_hash)),
        ("__MODULE_SOURCES__", repr([(n, s) for n, s in modules])),
        ("__DICTIONARY_JSON__", repr(dictionary_text)),
    ]
    program = template
    for placeholder, value in replacements:
        if program.count(placeholder) != 1:
            raise BuildError("template placeholder %s must appear exactly once" % placeholder)
        program = program.replace(placeholder, value)
    ast.parse(program)  # the rendered program must be valid Python
    return program, core, dict_hash


def _gid(key: str) -> str:
    return uuid.uuid5(NAMESPACE, key).hex


def _port(key: str, name: str, desc: str) -> Dict:
    return {"Id": _gid(key), "Name": name, "Description": desc, "UsingDefaultValue": False,
            "Level": 2, "UseLevels": False, "KeepListStructure": False}


def build_dyn_dict(program: str, core: str, dict_hash: str) -> Dict:
    seed = core + ":" + dict_hash
    inputs = [("snapshot", "快照 JSON 完整路徑（必填）"), ("output", "輸出資料夾完整路徑（必填，須已存在）")]
    nodes: List[Dict] = []
    views: List[Dict] = []
    connectors: List[Dict] = []
    py_inputs = [_port(seed + ":py:in%d" % i, "IN[%d]" % i, "Input #%d" % i) for i in range(len(inputs))]
    for i, (key, label) in enumerate(inputs):
        node_id = _gid(seed + ":input:" + key)
        out_port = _port(seed + ":input:" + key + ":out", "", "String")
        node = {"ConcreteType": "CoreNodeModels.Input.StringInput, CoreNodeModels",
                "NodeType": "StringInputNode", "InputValue": "", "Id": node_id,
                "Inputs": [], "Outputs": [out_port], "Replication": "Disabled",
                "Description": "Creates a string. Leave empty only if the node should not run."}
        nodes.append(node)
        views.append({"Id": node_id, "Name": label, "IsSetAsInput": False, "IsSetAsOutput": False,
                      "Excluded": False, "ShowGeometry": True, "X": 0.0, "Y": 120.0 * i})
        connectors.append({"Start": out_port["Id"], "End": py_inputs[i]["Id"],
                           "Id": _gid(seed + ":connector:" + key), "IsHidden": "False"})
    py_id = _gid(seed + ":python")
    py = {"ConcreteType": "PythonNodeModels.PythonNode, PythonNodeModels",
          "Code": program, "Engine": "CPython3", "EngineName": "CPython3",
          "VariableInputPorts": True, "Id": py_id, "NodeType": "PythonScriptNode",
          "Inputs": py_inputs, "Outputs": [_port(seed + ":python:out", "OUT", "Result")],
          "Replication": "Disabled", "Description": "Completeness check of SCADA parameters (embedded)."}
    nodes.append(py)
    views.append({"Id": py_id, "Name": "Completeness check", "IsSetAsInput": False,
                  "IsSetAsOutput": False, "Excluded": False, "ShowGeometry": True, "X": 520.0, "Y": 120.0})
    watch_id = _gid(seed + ":watch")
    watch = {"ConcreteType": "CoreNodeModels.Watch, CoreNodeModels", "WatchWidth": 400.0,
             "WatchHeight": 300.0, "Id": watch_id, "NodeType": "ExtensionNode",
             "Inputs": [_port(seed + ":watch:in", "", "Node to show")],
             "Outputs": [_port(seed + ":watch:out", "", "Node output")],
             "Replication": "Disabled", "Description": "Shows the result lines"}
    nodes.append(watch)
    views.append({"Id": watch_id, "Name": "Result", "IsSetAsInput": False, "IsSetAsOutput": False,
                  "Excluded": False, "ShowGeometry": True, "X": 900.0, "Y": 120.0})
    connectors.append({"Start": py["Outputs"][0]["Id"], "End": watch["Inputs"][0]["Id"],
                       "Id": _gid(seed + ":connector:watch"), "IsHidden": "False"})
    return {
        "Uuid": str(uuid.uuid5(NAMESPACE, seed + ":workspace")),
        "IsCustomNode": False, "Description": "SCADA parameter completeness check (no Revit API)",
        "Name": DYN_NAME, "ElementResolver": {"ResolutionMap": {}}, "Inputs": [], "Outputs": [],
        "Nodes": nodes, "Connectors": connectors, "Dependencies": [],
        "NodeLibraryDependencies": [], "Bindings": [],
        "View": {
            "Dynamo": {"ScaleFactor": 1.0, "HasRunWithoutCrash": False, "IsVisibleInDynamoLibrary": True,
                       "Version": DYNAMO_VERSION, "RunType": "Manual", "RunPeriod": "1000"},
            "Camera": {"Name": "_Background Preview", "EyeX": -17.0, "EyeY": 24.0, "EyeZ": 50.0,
                       "LookX": 12.0, "LookY": -13.0, "LookZ": -58.0, "UpX": 0.0, "UpY": 1.0, "UpZ": 0.0},
            "ConnectorPins": [], "NodeViews": views, "Annotations": [], "X": 0.0, "Y": 0.0, "Zoom": 1.0,
        },
    }


def _protected_hit(out_dir: str) -> Optional[str]:
    target = os.path.normcase(os.path.realpath(out_dir))
    parent = os.path.dirname(ROOT)
    for folder in PROTECTED_FOLDERS:
        guarded = os.path.normcase(os.path.realpath(os.path.join(parent, folder)))
        if target == guarded or target.startswith(guarded + os.sep):
            return folder
    return None


def build_text(modules=None, dictionary_text=None) -> Tuple[str, str, str, str]:
    """Return (dyn text, program, core hash, dictionary hash). Pure: writes nothing."""
    modules = load_modules() if modules is None else modules
    dictionary_text = load_dictionary_text() if dictionary_text is None else dictionary_text
    for name, source in modules:
        assert_no_forbidden(source, name)
    program, core, dict_hash = render_program(modules, dictionary_text)
    assert_no_forbidden(program, "node program")
    dyn = build_dyn_dict(program, core, dict_hash)
    text = json.dumps(dyn, ensure_ascii=False, indent=2) + "\n"
    root_escaped = os.path.realpath(ROOT).replace("\\", "\\\\")
    if (_DRIVE_JSON.search(text) or _DRIVE_RAW.search(program) or os.path.realpath(ROOT) in text
            or root_escaped in text):
        raise BuildError("the .dyn would contain a drive-letter or build-machine path; not written")
    return text, program, core, dict_hash


def write_dyn(out_dir: str, stamp: Optional[str] = None) -> str:
    """Write the .dyn into out_dir as 完整度檢查_<stamp>.dyn. Refuses an existing file."""
    if not os.path.isabs(out_dir):
        raise BuildError("output folder must be an absolute path")
    hit = _protected_hit(out_dir)
    if hit:
        raise BuildError("refusing to write into the existing tool folder %r" % hit)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") if stamp is None else stamp
    path = os.path.join(out_dir, "%s_%s.dyn" % (DYN_NAME, stamp))
    text, _, _, _ = build_text()
    try:
        fh = open(path, "x", encoding="utf-8", newline="\n")  # 'x': never overwrite
    except FileExistsError as ex:
        raise BuildError("refusing to overwrite an existing file: " + path) from ex
    with fh:
        fh.write(text)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=DEFAULT_OUT, help="output folder (default: out/ in the toolkit)")
    args = ap.parse_args(argv)
    try:
        path = write_dyn(os.path.abspath(args.out))
    except BuildError as ex:
        print("BUILD FAILED: %s" % ex, file=sys.stderr)
        return 1
    _, _, core, dict_hash = build_text()
    print(path)
    print("core SHA-256       " + core)
    print("dictionary SHA-256 " + dict_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
