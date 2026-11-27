# -*- coding: utf-8 -*-
"""Copy the shared block from batch_common.py into the batch scripts and their .dyn.

    python batch_common/sync_shared.py          # write changes
    python batch_common/sync_shared.py --check  # exit 1 if anything is out of sync

For each target script the text between the BEGIN and END markers is replaced
by the block in batch_common.py, then the Python node code embedded in the
matching .dyn is set to the full script text. Only the JSON string of that node
is replaced, so the rest of the .dyn stays byte-for-byte the same.
"""
import io
import json
import os
import sys
from typing import List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "batch_common", "batch_common.py")
BLOCK_SEPARATOR = "# --- block ---\n"
BEGIN = "# >>> shared: batch_common (edit batch_common/batch_common.py, then run batch_common/sync_shared.py)\n"
END = "# <<< shared: batch_common\n"
TARGETS = (
    "批次SCADA設定/BatchScadaSetup.py",
    "批次參數工具/BatchParamTools.py",
    "批次填參數/BatchFillScadaParams.py",
    "批次工作集/BatchWorksets.py",
    "批次複製視圖樣板/BatchCopyViewTemplates.py",
)


class SyncError(Exception):
    pass


def read_text(path: str) -> str:
    """Read UTF-8 text with line endings normalised to LF."""
    with io.open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def write_text(path: str, text: str) -> None:
    """Write LF text, keeping the file's existing CRLF line endings if it has them."""
    newline = "\n"
    if os.path.exists(path):
        with io.open(path, "rb") as f:
            if b"\r\n" in f.read():
                newline = "\r\n"
    with io.open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def load_block(source_text: str) -> str:
    if source_text.count(BLOCK_SEPARATOR) != 1:
        raise SyncError("batch_common.py must contain exactly one %r line" % BLOCK_SEPARATOR.strip())
    block = source_text.split(BLOCK_SEPARATOR, 1)[1]
    return block.rstrip("\n") + "\n"


def apply_block(script_text: str, block: str) -> str:
    """Return script_text with the marker region replaced by block."""
    if script_text.count(BEGIN) != 1 or script_text.count(END) != 1:
        raise SyncError("script must contain exactly one BEGIN and one END marker line")
    head, rest = script_text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return head + BEGIN + block + END + tail


def python_node_code(dyn_text: str) -> str:
    nodes = [n for n in json.loads(dyn_text).get("Nodes", [])
             if str(n.get("ConcreteType", "")).startswith("PythonNodeModels") and "Code" in n]
    if len(nodes) != 1:
        raise SyncError("expected exactly one Python node in the .dyn, found %d" % len(nodes))
    return nodes[0]["Code"]


def replace_dyn_code(dyn_text: str, new_code: str) -> str:
    """Replace the embedded Python node code, leaving all other bytes unchanged."""
    old_code = python_node_code(dyn_text)
    for ascii_only in (True, False):
        old_json = json.dumps(old_code, ensure_ascii=ascii_only)
        if dyn_text.count(old_json) == 1:
            result = dyn_text.replace(old_json, json.dumps(new_code, ensure_ascii=ascii_only))
            if python_node_code(result) != new_code:
                raise SyncError("embedded code did not round-trip")
            return result
    raise SyncError("could not locate the embedded code string exactly once")


def sync_one(py_path: str, block: str, write: bool) -> List[str]:
    """Return the paths that are (or were) out of sync."""
    changed = []
    script = read_text(py_path)
    new_script = apply_block(script, block)
    if new_script != script:
        changed.append(py_path)
        if write:
            write_text(py_path, new_script)

    dyn_path = os.path.splitext(py_path)[0] + ".dyn"
    dyn_text = read_text(dyn_path)
    if python_node_code(dyn_text) != new_script:
        changed.append(dyn_path)
        if write:
            write_text(dyn_path, replace_dyn_code(dyn_text, new_script))
    return changed


def run(write: bool, root: str = ROOT, targets: Tuple[str, ...] = TARGETS,
        source: Optional[str] = None) -> List[str]:
    block = load_block(read_text(source or SOURCE))
    changed = []
    for rel in targets:
        changed += sync_one(os.path.join(root, rel), block, write)
    return changed


def main(argv: List[str]) -> int:
    check = "--check" in argv
    try:
        changed = run(write=not check)
    except (OSError, ValueError, SyncError) as ex:
        print("ERROR: %s" % ex, file=sys.stderr)
        return 2
    for path in changed:
        print(("OUT OF SYNC: " if check else "updated: ") + os.path.relpath(path, ROOT))
    if check and changed:
        return 1
    if not changed:
        print("all in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
