# -*- coding: utf-8 -*-
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sync_shared as s  # noqa: E402

BLOCK = "def shared():\n    return 1\n"
SOURCE = "# header\n" + s.BLOCK_SEPARATOR + BLOCK


def script(region: str) -> str:
    return "NS = 'x'\n\n" + s.BEGIN + region + s.END + "\nOUT = shared()\n"


def dyn(code: str) -> str:
    nodes = [{"ConcreteType": "CoreNodeModels.Watch, CoreNodeModels", "Id": "w"},
             {"ConcreteType": "PythonNodeModels.PythonNode, PythonNodeModels",
              "Code": code, "Engine": "CPython3", "Id": "p"}]
    return json.dumps({"Uuid": "u", "Nodes": nodes, "Name": "測試"}, indent=2, ensure_ascii=False)


def write(path, text, newline="\n"):
    with io.open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def make_tree(tmp_path, region, newline="\n"):
    (tmp_path / "tool").mkdir()
    py = tmp_path / "tool" / "Tool.py"
    text = script(region)
    write(py, text, newline)
    write(tmp_path / "tool" / "Tool.dyn", dyn(text), newline)
    write(tmp_path / "common.py", SOURCE)
    return py


def run(tmp_path, write_changes):
    return s.run(write=write_changes, root=str(tmp_path), targets=("tool/Tool.py",),
                 source=str(tmp_path / "common.py"))


def test_repository_scripts_and_dyn_are_in_sync():
    assert s.run(write=False) == []


def test_load_block_requires_one_separator():
    assert s.load_block(SOURCE) == BLOCK
    with pytest.raises(s.SyncError):
        s.load_block("no separator\n")


def test_apply_block_replaces_only_the_marker_region():
    assert s.apply_block(script("old()\n"), BLOCK) == script(BLOCK)


@pytest.mark.parametrize("text", ["no markers\n", s.BEGIN + "x\n", script("a\n") + script("b\n")])
def test_apply_block_rejects_missing_or_duplicate_markers(text):
    with pytest.raises(s.SyncError):
        s.apply_block(text, BLOCK)


def test_replace_dyn_code_keeps_other_bytes():
    old = dyn("old\n")
    new = s.replace_dyn_code(old, "new\n")
    assert s.python_node_code(new) == "new\n"
    assert new == old.replace('"old\\n"', '"new\\n"')


def test_check_reports_without_writing(tmp_path):
    py = make_tree(tmp_path, "stale()\n")
    before = py.read_bytes()
    changed = run(tmp_path, write_changes=False)
    assert [os.path.basename(p) for p in changed] == ["Tool.py", "Tool.dyn"]
    assert py.read_bytes() == before


def test_sync_updates_script_and_dyn_and_keeps_crlf(tmp_path):
    py = make_tree(tmp_path, "stale()\n", newline="\r\n")
    run(tmp_path, write_changes=True)
    assert s.read_text(str(py)) == script(BLOCK)
    dyn_path = str(tmp_path / "tool" / "Tool.dyn")
    assert s.python_node_code(s.read_text(dyn_path)) == script(BLOCK)
    assert b"\r\n" in py.read_bytes()
    assert run(tmp_path, write_changes=False) == []
