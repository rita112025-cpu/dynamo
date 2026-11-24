# -*- coding: utf-8 -*-
"""Pure-Python logic for the ribbon check buttons (no Revit API imports).

Written to run on both IronPython 2.7 and CPython 3 (no f-strings, no type
hints) so the same file works whichever pyRevit engine runs the buttons.
"""
import io
import json
import os
from collections import OrderedDict

_PARAMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scada_params.json")


def load_scada_params():
    """Return the dictionary of SCADA shared parameters: {name, guid} list."""
    with io.open(_PARAMS_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


# Rack families in real models are not always named SCADA_機櫃_* (e.g. SB11_RTU機櫃_600x1000x2100),
# so match any family whose name contains 機櫃 and let the parameter check report what is missing.
RACK_KEYWORD = u"機櫃"


def is_scada_rack(family_name, keyword=RACK_KEYWORD):
    return bool(family_name) and keyword in family_name


def summarize_racks(racks, param_names):
    """racks: list of {"id", "family", "values": {name: str or None}}.

    A value of None means the parameter does not exist on the element; an empty
    string means it exists but is blank. Returns (rows, totals) where rows has
    one entry per rack with its missing / empty parameter names.
    """
    rows = []
    totals = {"racks": len(racks), "complete": 0, "missing": 0, "empty": 0}
    for rack in racks:
        missing = [n for n in param_names if rack["values"].get(n) is None]
        empty = [n for n in param_names
                 if rack["values"].get(n) is not None and not rack["values"][n].strip()]
        if not missing and not empty:
            totals["complete"] += 1
        totals["missing"] += len(missing)
        totals["empty"] += len(empty)
        rows.append({"id": rack["id"], "family": rack["family"],
                     "missing": missing, "empty": empty})
    return rows, totals


def tally_trays(items):
    """items: list of {"kind": "tray"|"fitting", "type": str, "size": str,
    "length_m": float or None}. Returns ordered rows grouped by (kind, type, size)
    with count and total length (fittings have no length)."""
    groups = OrderedDict()
    for item in items:
        key = (item["kind"], item["type"], item["size"])
        group = groups.setdefault(key, {"count": 0, "length_m": 0.0})
        group["count"] += 1
        if item.get("length_m"):
            group["length_m"] += item["length_m"]
    rows = []
    for key in sorted(groups):
        kind, type_name, size = key
        rows.append({"kind": kind, "type": type_name, "size": size,
                     "count": groups[key]["count"],
                     "length_m": round(groups[key]["length_m"], 2)})
    return rows
