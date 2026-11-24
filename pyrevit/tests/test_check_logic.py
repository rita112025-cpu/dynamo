# -*- coding: utf-8 -*-
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "DynamoToolbox.extension", "lib"))

import check_logic  # noqa: E402


def test_params_match_toolkit_dictionary():
    path = os.path.join(os.path.dirname(ROOT), "toolkit", "config", "parameter_dictionary.json")
    with open(path, encoding="utf-8") as handle:
        source = json.load(handle)["shared_parameters"]
    copy = check_logic.load_scada_params()
    assert copy["parameters"] == [{"name": p["name"], "guid": p["guid"]} for p in source["parameters"]]
    assert copy["applies_to"] == source["applies_to"]
    assert len(copy["parameters"]) == 16


def test_is_scada_rack():
    assert check_logic.is_scada_rack("SCADA_機櫃_PLC", "SCADA_機櫃")
    assert not check_logic.is_scada_rack("Other", "SCADA_機櫃")
    assert not check_logic.is_scada_rack(None, "SCADA_機櫃")


def test_summarize_racks_distinguishes_missing_and_empty():
    racks = [
        {"id": 1, "family": "f", "values": {"A": "x", "B": "y"}},
        {"id": 2, "family": "f", "values": {"A": "x", "B": "  "}},
        {"id": 3, "family": "f", "values": {"A": "x"}},
    ]
    rows, totals = check_logic.summarize_racks(racks, ["A", "B"])
    assert totals == {"racks": 3, "complete": 1, "missing": 1, "empty": 1}
    assert rows[1]["empty"] == ["B"] and rows[1]["missing"] == []
    assert rows[2]["missing"] == ["B"]


def test_summarize_racks_no_racks():
    rows, totals = check_logic.summarize_racks([], ["A"])
    assert rows == [] and totals["racks"] == 0


def test_tally_trays_groups_and_sums():
    items = [
        {"kind": "tray", "type": "梯型", "size": "300x100", "length_m": 2.0},
        {"kind": "tray", "type": "梯型", "size": "300x100", "length_m": 1.255},
        {"kind": "tray", "type": "梯型", "size": "200x100", "length_m": 3.0},
        {"kind": "fitting", "type": "彎頭", "size": "300x100", "length_m": None},
    ]
    rows = check_logic.tally_trays(items)
    assert len(rows) == 3
    ladder = [r for r in rows if r["size"] == "300x100" and r["kind"] == "tray"][0]
    assert ladder["count"] == 2 and ladder["length_m"] == 3.25
    fitting = [r for r in rows if r["kind"] == "fitting"][0]
    assert fitting["length_m"] == 0.0
