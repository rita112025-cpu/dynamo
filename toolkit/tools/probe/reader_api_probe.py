# Read-only Revit API probe (Revit 2025). Generated into a .dyn by tools/probe/make_probe_dyn.py.
#
# What it does: reads the CURRENT document, records what each Revit API call returns or raises,
# and writes ONE JSON report into IN[1]. It never opens, saves, synchronises, closes or edits anything.
#
# IN[0]  full path of the saved TEST model. Must equal the open document's PathName, otherwise the
#        probe refuses to run (protects against running on a production or unsaved model).
# IN[1]  full path of an EXISTING output folder.
# OUT    summary lines (shown by the Watch node).
#
# Every Revit call is wrapped on its own, so one failing API never stops the probe.
import clr
import json
import os
from datetime import datetime

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import (FilteredElementCollector, FilteredWorksetCollector, BuiltInCategory,
                               BuiltInParameter, RevitLinkInstance)
from RevitServices.Persistence import DocumentManager
from System import Guid

PROBE_VERSION = "0.1.0"
CATEGORY_KEYS = ("OST_Conduit", "OST_ConduitFitting", "OST_CableTray", "OST_CableTrayFitting",
                 "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_Wire")
SAMPLES_PER_CATEGORY = 5
TYPE_SAMPLES_PER_CATEGORY = 3
RACK_SAMPLES = 2
# The 16 SCADA shared parameters (name, GUID), copied from config/parameter_dictionary.json.
# tests/test_reader_probe.py checks that this list still equals the dictionary.
SHARED_PARAMETERS = (
    ("SCADA_編號", "81bdc77b-c362-4012-aa80-6edd256f9b09"),
    ("SCADA_期別", "b1b763ae-f6db-44bf-b7a5-ad35ea29ad9c"),
    ("SCADA_站點", "f1f6fdc5-7006-44e2-a7d0-60ae0647f0d0"),
    ("SCADA_建物", "8a59691b-8411-4799-a4b5-693cf1661e67"),
    ("SCADA_房間", "53413beb-fd65-4b80-8753-db471cb8319c"),
    ("SCADA_機櫃類型", "3e00233a-044f-4b21-bca3-fa1ce26ba6e5"),
    ("SCADA_寬mm", "e0f8b8a1-3ba8-49e3-9b11-e40b4b710d06"),
    ("SCADA_深mm", "b9f4ce69-08e6-4908-b23b-56a384832f43"),
    ("SCADA_高mm", "896f98f9-1b6f-4a9f-9a85-3cfa29758348"),
    ("SCADA_尺寸", "a6d1af90-4cc8-48c0-a233-f204e0abad5b"),
    ("SCADA_附錄D項次", "42b9f865-f078-4b52-93b3-852e19aeafa6"),
    ("SCADA_UPS電源110V", "b662bf65-c745-4d14-beaf-4dcc180dc298"),
    ("SCADA_附錄F項次", "aa933f19-c018-4d63-887b-d388eef2ec0a"),
    ("SCADA_來源文件", "a26cb5cc-1c1d-400b-b011-5c77e3a44b4b"),
    ("SCADA_備註", "4cb549c0-2004-4250-8d34-8c10252c4a4f"),
    ("SCADA_定位來源", "82607d24-24b2-4a1f-94fe-109bfff58ad1"),
)
SERVICE_NAMES = ("服務類型", "Service Type")
COMMENT_NAMES = ("備註", "Comments")

REPORT = []


def _plain(value, depth=0):
    """Make a value JSON-safe. Revit objects become their string form."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth > 2:
        return "<deep>"
    if isinstance(value, (list, tuple)):
        return [_plain(v, depth + 1) for v in list(value)[:50]]
    try:
        return str(value)[:500]
    except Exception:
        return "<unprintable>"


def _exc(ex):
    try:
        message = str(ex)[:500]
    except Exception:
        message = "<unprintable>"
    return type(ex).__name__ + ": " + message


def call(section, name, fn):
    """Run one probe step. Records ok/value or exception type and message. Returns the raw result
    (or None on failure) so later steps can use Revit objects."""
    record = {"section": section, "name": name}
    try:
        out = fn()
        record["ok"] = True
        record["value"] = _plain(out)
    except Exception as ex:
        out = None
        record["ok"] = False
        record["exception"] = _exc(ex)
    REPORT.append(record)
    return out


def describe_param(section, label, p):
    """Record what a parameter object reports. Returns a small summary dict."""
    summary = {"label": label, "found": p is not None}
    if p is None:
        REPORT.append({"section": section, "name": label + " found", "ok": True, "value": False})
        return summary
    REPORT.append({"section": section, "name": label + " found", "ok": True, "value": True})
    summary["Definition.Name"] = call(section, label + " Definition.Name", lambda: p.Definition.Name)
    summary["StorageType"] = call(section, label + " StorageType", lambda: str(p.StorageType))
    summary["IsReadOnly"] = call(section, label + " IsReadOnly", lambda: p.IsReadOnly)
    summary["HasValue"] = call(section, label + " HasValue", lambda: p.HasValue)
    summary["AsString"] = call(section, label + " AsString", lambda: p.AsString())
    summary["AsValueString"] = call(section, label + " AsValueString", lambda: p.AsValueString())
    return summary


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _text(value):
    return "" if value is None else str(value).strip()


def run():
    in_model = _text(IN[0])
    in_folder = _text(IN[1])
    if not in_model:
        raise Exception("NOT RUN: IN[0] must be the full path of the saved TEST model")
    if not in_folder:
        raise Exception("NOT RUN: IN[1] must be the full path of an EXISTING output folder")
    if not os.path.isdir(in_folder):
        raise Exception("output folder does not exist (not created automatically): " + in_folder)
    doc = DocumentManager.Instance.CurrentDBDocument
    current = doc.PathName
    if not current:
        raise Exception("REFUSED: the open document has no file path (not saved). Save it as the test model first.")
    if _norm(current) != _norm(in_model):
        raise Exception("REFUSED: the open document is not IN[0]. Open: " + current + " | IN[0]: " + in_model)

    # ---- 1. environment --------------------------------------------------------------------
    env = {}
    modified_before = call("env", "IsModified before", lambda: doc.IsModified)
    env["path_name"] = call("env", "PathName", lambda: doc.PathName)
    env["title"] = call("env", "Title", lambda: doc.Title)
    env["is_workshared"] = call("env", "IsWorkshared", lambda: doc.IsWorkshared)
    env["version_number"] = call("env", "Application.VersionNumber", lambda: doc.Application.VersionNumber)
    env["version_name"] = call("env", "Application.VersionName", lambda: doc.Application.VersionName)
    env["is_modified_before"] = modified_before

    # ---- 2. categories: counts with and without WhereElementIsNotElementType -----------------
    categories = {}
    for key in CATEGORY_KEYS:
        bic = call("category", key + " BuiltInCategory", lambda k=key: getattr(BuiltInCategory, k))
        counts = {}
        counts["all"] = call("category", key + " count all", lambda b=bic: len(list(FilteredElementCollector(doc).OfCategory(b))))
        counts["instances"] = call("category", key + " count instances",
                                   lambda b=bic: len(list(FilteredElementCollector(doc).OfCategory(b).WhereElementIsNotElementType())))
        counts["types"] = call("category", key + " count types",
                               lambda b=bic: len(list(FilteredElementCollector(doc).OfCategory(b).WhereElementIsElementType())))
        categories[key] = counts
        instances = call("category", key + " list instances",
                         lambda b=bic: list(FilteredElementCollector(doc).OfCategory(b).WhereElementIsNotElementType())) or []
        types = call("category", key + " list types",
                     lambda b=bic: list(FilteredElementCollector(doc).OfCategory(b).WhereElementIsElementType())) or []
        for el in instances[:SAMPLES_PER_CATEGORY]:
            _probe_instance(doc, key, el)
        for t in types[:TYPE_SAMPLES_PER_CATEGORY]:
            _probe_type(doc, key, t)

    # ---- 3. rack samples and the 16 shared parameters: GUID lookup vs name lookup -----------
    racks = _find_racks(doc)
    for index, rack in enumerate(racks):
        _probe_shared(doc, index, rack)

    # ---- 4. worksets -----------------------------------------------------------------------
    workshared = env["is_workshared"]
    if workshared is True:
        call("workset", "GetWorksetTable", lambda: doc.GetWorksetTable())
        worksets = call("workset", "FilteredWorksetCollector list", lambda: list(FilteredWorksetCollector(doc))) or []
        for w in worksets[:50]:
            call("workset", "Workset.Name", lambda x=w: x.Name)
            call("workset", "Workset.IsOpen", lambda x=w: x.IsOpen)
            call("workset", "Workset.Kind", lambda x=w: str(x.Kind))
    else:
        REPORT.append({"section": "workset", "name": "worksets", "ok": True, "value": "N/A (not workshared)"})

    # ---- 5. links --------------------------------------------------------------------------
    links = call("links", "RevitLinkInstance list", lambda: list(FilteredElementCollector(doc).OfClass(RevitLinkInstance)))
    call("links", "link count", lambda: len(links) if links is not None else None)
    for link in (links or [])[:20]:
        call("links", "link name", lambda x=link: x.Name)

    modified_after = call("env", "IsModified after", lambda: doc.IsModified)
    env["is_modified_after"] = modified_after
    return env, categories, racks


def _probe_instance(doc, key, el):
    sec = "sample"
    id_value = call(sec, key + " instance Id.Value", lambda e=el: e.Id.Value)
    label = key + " instance " + str(id_value)
    id_int = call(sec, label + " Id.IntegerValue", lambda e=el: e.Id.IntegerValue)
    call(sec, label + " Id.Value equals IntegerValue", lambda: id_value == id_int)
    call(sec, label + " Category.Name", lambda e=el: e.Category.Name)
    type_id = call(sec, label + " GetTypeId", lambda e=el: e.GetTypeId())
    t = call(sec, label + " GetElement(type)", lambda: doc.GetElement(type_id)) if type_id is not None else None
    call(sec, label + " type FamilyName", lambda: t.FamilyName)
    call(sec, label + " type Name", lambda: t.Name)
    call(sec, label + " hasattr Symbol", lambda e=el: hasattr(e, "Symbol"))
    if hasattr(el, "Symbol"):
        call(sec, label + " Symbol.Family.Name", lambda e=el: e.Symbol.Family.Name)
    _probe_params(label, el, t, key)


def _probe_type(doc, key, t):
    sec = "type"
    label = key + " type " + str(call(sec, key + " type Id.Value", lambda x=t: x.Id.Value))
    call(sec, label + " Category.Name", lambda x=t: x.Category.Name)
    call(sec, label + " FamilyName", lambda x=t: x.FamilyName)
    call(sec, label + " Name", lambda x=t: x.Name)


def _probe_params(label, el, type_el, key):
    sec = "param"
    if key in ("OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_Wire"):
        builtin_name = "ALL_MODEL_INSTANCE_COMMENTS"
        names = COMMENT_NAMES
    else:
        builtin_name = "RBS_CTC_SERVICE_TYPE"
        names = SERVICE_NAMES
    bip = call(sec, label + " BuiltInParameter " + builtin_name,
               lambda: getattr(BuiltInParameter, builtin_name))
    p = call(sec, label + " get_Parameter(BuiltInParameter)", lambda: el.get_Parameter(bip)) if bip is not None else None
    describe_param(sec, label + " builtin", p)
    for n in names:
        q = call(sec, label + " LookupParameter " + n, lambda x=n: el.LookupParameter(x))
        describe_param(sec, label + " lookup " + n, q)
        if type_el is not None:
            tq = call(sec, label + " type LookupParameter " + n, lambda x=n: type_el.LookupParameter(x))
            describe_param(sec, label + " type lookup " + n, tq)
    # Expected read-only candidate [憑記憶]: curve length of a linear element.
    length = call(sec, label + " get_Parameter(CURVE_ELEM_LENGTH)",
                  lambda: el.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH))
    describe_param(sec, label + " CURVE_ELEM_LENGTH (expected read-only)", length)


def _find_racks(doc):
    """Up to RACK_SAMPLES instances whose type family name contains SCADA_機櫃."""
    found = []
    equipment = call("rack", "list equipment instances",
                     lambda: list(FilteredElementCollector(doc)
                                  .OfCategory(BuiltInCategory.OST_ElectricalEquipment)
                                  .WhereElementIsNotElementType())) or []
    for el in equipment:
        if len(found) >= RACK_SAMPLES:
            break
        type_id = call("rack", "rack candidate GetTypeId", lambda e=el: e.GetTypeId())
        t = call("rack", "rack candidate type", lambda: doc.GetElement(type_id)) if type_id is not None else None
        fam = call("rack", "rack candidate FamilyName", lambda: t.FamilyName) if t is not None else None
        if isinstance(fam, str) and "SCADA_機櫃" in fam:
            found.append(el)
    call("rack", "rack instances found", lambda: len(found))
    return found


def _probe_shared(doc, index, el):
    sec = "shared"
    label = "rack " + str(index)
    for name, guid_text in SHARED_PARAMETERS:
        g = call(sec, label + " Guid " + name, lambda s=guid_text: Guid(s))
        by_guid = call(sec, label + " get_Parameter(Guid) " + name, lambda: el.get_Parameter(g)) if g is not None else None
        by_name = call(sec, label + " LookupParameter " + name, lambda n=name: el.LookupParameter(n))
        if by_guid is not None:
            call(sec, label + " GUID of found param " + name, lambda p=by_guid: str(p.GUID))
        describe_param(sec, label + " by GUID " + name, by_guid)
        describe_param(sec, label + " by NAME " + name, by_name)
        same = (by_guid is not None and by_name is not None
                and call(sec, label + " same element " + name, lambda: by_guid.Id == by_name.Id) is True)
        REPORT.append({"section": sec, "name": label + " GUID vs NAME agree " + name, "ok": True, "value": same})


def _write_report(report, folder):
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(folder, "reader_probe_" + stamp + ".json")
    if os.path.exists(path):
        raise Exception("report already exists, not overwritten: " + path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def main():
    env, categories, racks = run()
    ok = sum(1 for r in REPORT if r.get("ok"))
    failed = [r for r in REPORT if r.get("ok") is False]
    report = {
        "probe_version": PROBE_VERSION,
        "run_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"model_path": _text(IN[0]), "output_folder": _text(IN[1])},
        "environment": env,
        "category_counts": categories,
        "rack_instances_found": len(racks),
        "records": REPORT,
        "summary": {"steps": len(REPORT), "ok": ok, "failed": len(failed)},
    }
    path = _write_report(report, _text(IN[1]))
    lines = [
        "reader API probe " + PROBE_VERSION + " (read-only, nothing written to the model)",
        "model: " + str(env.get("path_name")),
        "Revit " + str(env.get("version_number")) + " " + str(env.get("version_name")),
        "IsModified before " + str(env.get("is_modified_before")) + ", after " + str(env.get("is_modified_after")),
        "steps " + str(len(REPORT)) + ", ok " + str(ok) + ", failed " + str(len(failed)),
        "rack instances found: " + str(len(racks)),
        "report: " + path,
    ]
    for key in CATEGORY_KEYS:
        c = categories.get(key) or {}
        lines.append("%s all=%s instances=%s types=%s" % (key, c.get("all"), c.get("instances"), c.get("types")))
    return lines


OUT = main()
