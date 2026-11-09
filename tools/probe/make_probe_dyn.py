"""Build the read-only Revit API probe as a Dynamo .dyn (out/, never overwritten, deterministic).

    python tools/probe/make_probe_dyn.py              # writes out/reader_probe_<timestamp>.dyn
    python tools/probe/make_probe_dyn.py -o <folder>  # not an existing Dynamo tool folder

The .dyn has one CPython3 node (the probe source, unchanged), two empty string inputs and one Watch.
The probe source is checked by tools/reader_rules.py before anything is written.
Node ids are uuid5 of the source hash, so two builds give byte-identical content; only the file name
carries the build time. Nothing here touches the existing completeness-check build (tools/make_dyn.py).
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
from typing import Dict, List, Optional

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(PROBE_DIR)
ROOT = os.path.dirname(TOOLS)
SOURCE = os.path.join(PROBE_DIR, "reader_api_probe.py")
DEFAULT_OUT = os.path.join(ROOT, "out")

sys.path.insert(0, TOOLS)
sys.path.insert(0, ROOT)
import make_dyn  # noqa: E402  (reuse the protected-folder rule; make_dyn itself is not changed)
from reader_rules import reader_forbidden_uses  # noqa: E402

DYN_NAME = "reader_probe"
DYNAMO_VERSION = "3.3.2.11986"  # same version recorded in the project's existing Dynamo files
NAMESPACE = uuid.UUID("0b7e5c1a-3d2f-4a9e-9c61-7f2d8e4b1a05")  # fixed, separate from make_dyn
_DRIVE_JSON = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\\\[A-Za-z0-9_一-鿿]")
_DRIVE_RAW = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?=[A-Za-z0-9_一-鿿])")
INPUTS = (("model", "IN[0] 已另存測試模型完整路徑（必填）"),
          ("folder", "IN[1] 已存在的輸出資料夾完整路徑（必填）"))


class ProbeBuildError(RuntimeError):
    """The probe .dyn cannot be built or written safely."""


def load_source() -> str:
    with open(SOURCE, encoding="utf-8") as fh:
        source = fh.read()
    ast.parse(source)
    findings = reader_forbidden_uses(source)
    if findings:
        raise ProbeBuildError("probe source breaks the reader rules: " + "; ".join(
            "line %d: %s" % item for item in findings))
    return source


def _gid(key: str) -> str:
    return uuid.uuid5(NAMESPACE, key).hex


def _port(key: str, name: str, desc: str) -> Dict:
    return {"Id": _gid(key), "Name": name, "Description": desc, "UsingDefaultValue": False,
            "Level": 2, "UseLevels": False, "KeepListStructure": False}


def build_dyn_dict(source: str) -> Dict:
    seed = hashlib.sha256(source.encode("utf-8")).hexdigest()
    nodes: List[Dict] = []
    views: List[Dict] = []
    connectors: List[Dict] = []
    py_inputs = [_port(seed + ":py:in%d" % i, "IN[%d]" % i, "Input #%d" % i) for i in range(len(INPUTS))]
    for i, (key, label) in enumerate(INPUTS):
        node_id = _gid(seed + ":input:" + key)
        out_port = _port(seed + ":input:" + key + ":out", "", "String")
        nodes.append({"ConcreteType": "CoreNodeModels.Input.StringInput, CoreNodeModels",
                      "NodeType": "StringInputNode", "InputValue": "", "Id": node_id,
                      "Inputs": [], "Outputs": [out_port], "Replication": "Disabled",
                      "Description": "Creates a string. Fill in the full path."})
        views.append({"Id": node_id, "Name": label, "IsSetAsInput": False, "IsSetAsOutput": False,
                      "Excluded": False, "ShowGeometry": True, "X": 0.0, "Y": 120.0 * i})
        connectors.append({"Start": out_port["Id"], "End": py_inputs[i]["Id"],
                           "Id": _gid(seed + ":connector:" + key), "IsHidden": "False"})
    py_id = _gid(seed + ":python")
    py_out = _port(seed + ":python:out", "OUT", "Result")
    py = {"ConcreteType": "PythonNodeModels.PythonNode, PythonNodeModels",
          "Code": source, "Engine": "CPython3",
          "VariableInputPorts": True, "Id": py_id, "NodeType": "PythonScriptNode",
          "Inputs": py_inputs, "Outputs": [py_out],
          "Replication": "Disabled", "Description": "Read-only Revit API probe (Revit 2025)."}
    nodes.append(py)
    views.append({"Id": py_id, "Name": "Reader API probe", "IsSetAsInput": False,
                  "IsSetAsOutput": False, "Excluded": False, "ShowGeometry": True, "X": 520.0, "Y": 120.0})
    watch_id = _gid(seed + ":watch")
    watch = {"ConcreteType": "CoreNodeModels.Watch, CoreNodeModels", "WatchWidth": 500.0,
             "WatchHeight": 400.0, "Id": watch_id, "NodeType": "ExtensionNode",
             "Inputs": [_port(seed + ":watch:in", "", "Node to show")],
             "Outputs": [_port(seed + ":watch:out", "", "Node output")],
             "Replication": "Disabled", "Description": "Shows the probe summary"}
    nodes.append(watch)
    views.append({"Id": watch_id, "Name": "Probe summary", "IsSetAsInput": False, "IsSetAsOutput": False,
                  "Excluded": False, "ShowGeometry": True, "X": 900.0, "Y": 120.0})
    connectors.append({"Start": py_out["Id"], "End": watch["Inputs"][0]["Id"],
                       "Id": _gid(seed + ":connector:watch"), "IsHidden": "False"})
    return {
        "Uuid": str(uuid.uuid5(NAMESPACE, seed + ":workspace")),
        "IsCustomNode": False, "Description": "Read-only Revit API probe (test model only)",
        "Name": "reader_probe", "ElementResolver": {"ResolutionMap": {}}, "Inputs": [], "Outputs": [],
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


def build_text(source: Optional[str] = None) -> str:
    source = load_source() if source is None else source
    text = json.dumps(build_dyn_dict(source), ensure_ascii=False, indent=2) + "\n"
    root_escaped = os.path.realpath(ROOT).replace("\\", "\\\\")
    if (_DRIVE_JSON.search(text) or _DRIVE_RAW.search(source) or os.path.realpath(ROOT) in text
            or root_escaped in text):
        raise ProbeBuildError("the probe .dyn would contain a drive-letter or build-machine path")
    return text


def write_probe_dyn(out_dir: str, stamp: Optional[str] = None) -> str:
    if not os.path.isabs(out_dir):
        raise ProbeBuildError("output folder must be an absolute path")
    hit = make_dyn._protected_hit(out_dir)
    if hit:
        raise ProbeBuildError("refusing to write into the existing tool folder %r" % hit)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") if stamp is None else stamp
    path = os.path.join(out_dir, "%s_%s.dyn" % (DYN_NAME, stamp))
    text = build_text()
    try:
        fh = open(path, "x", encoding="utf-8", newline="\n")
    except FileExistsError as ex:
        raise ProbeBuildError("refusing to overwrite an existing file: " + path) from ex
    with fh:
        fh.write(text)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        path = write_probe_dyn(os.path.abspath(args.out))
    except ProbeBuildError as ex:
        print("BUILD FAILED: %s" % ex, file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
