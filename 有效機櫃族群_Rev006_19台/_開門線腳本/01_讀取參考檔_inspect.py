# Dynamo for Revit 2025 - Python Script node (CPython3)
# Stage 1: read-only inspection of the reference family and two target families.
# Opens each .rfa in the background, dumps curves / forms / ref planes / parameters
# to JSON, then closes WITHOUT saving. No input ports needed.
# OUT = path of the JSON report.

import clr
import json
import os
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import (
    FilteredElementCollector, CurveElement, GenericForm, ReferencePlane,
    FamilyInstance, Dimension, Arc, BuiltInParameter, View, ModelPathUtils,
    OpenOptions, StorageType, Element,
)
from RevitServices.Persistence import DocumentManager

FT2MM = 304.8
REF = r"D:\族群_汐東縣\Rita\族群們\SCADA_機櫃_GEN-RJ45-PP-01.rfa"
DIR = r"D:\族群_汐東縣\SCADA_主題導覽\12 SoW_V6_規範追溯\有效機櫃族群_Rev006_19台"
TARGETS = [
    os.path.join(DIR, "SB10_RTU機櫃_600x1000x2100.rfa"),
    os.path.join(DIR, "PDU_獨立機櫃_600x800x2100.rfa"),
]
OUT_PATH = os.path.join(DIR, "_開門線腳本", "inspect_result.json")

app = DocumentManager.Instance.CurrentUIApplication.Application


def safe(fn):
    try:
        return fn()
    except Exception:
        return None


def ename(e):
    # pythonnet cannot read .Name on some Element subclasses; fall back to base getter
    if e is None:
        return None
    try:
        return e.Name
    except Exception:
        return safe(lambda: Element.Name.GetValue(e))


def mm(v):
    return round(v * FT2MM, 2)


def pt(p):
    return [mm(p.X), mm(p.Y), mm(p.Z)]


def curve_info(c):
    d = {"type": c.GetType().Name}
    if c.IsBound:
        d["start"] = pt(c.GetEndPoint(0))
        d["end"] = pt(c.GetEndPoint(1))
    if isinstance(c, Arc):
        d["center"] = pt(c.Center)
        d["radius"] = mm(c.Radius)
        d["normal"] = [round(c.Normal.X, 4), round(c.Normal.Y, 4), round(c.Normal.Z, 4)]
    return d


def visibility(el):
    try:
        v = el.GetVisibility()
    except Exception:
        return None
    keys = ["IsShownInCoarse", "IsShownInMedium", "IsShownInFine",
            "IsShownInFrontBack", "IsShownInLeftRight", "IsShownInTopBottom",
            "IsShownInPlanRCPCut", "IsShownOnlyWhenCut"]
    d = {}
    for k in keys:
        try:
            d[k] = getattr(v, k)
        except Exception:
            pass
    try:
        d["VisibilityType"] = str(v.VisibilityType)
    except Exception:
        pass
    return d


def visible_param(doc, el):
    p = el.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM)
    if p is None:
        return None
    d = {"value": p.AsInteger()}
    try:
        fp = doc.FamilyManager.GetAssociatedFamilyParameter(p)
        if fp is not None:
            d["associated"] = fp.Definition.Name
    except Exception:
        pass
    return d


def view_name(doc, el):
    vid = el.OwnerViewId
    if vid is None or vid.Value < 0:
        return None
    v = doc.GetElement(vid)
    return ename(v)


def bbox(el):
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None
    return {"min": pt(bb.Min), "max": pt(bb.Max)}


def param_value(doc, fp):
    t = doc.FamilyManager.CurrentType
    if t is None:
        return None
    st = fp.StorageType
    try:
        if st == StorageType.Double:
            v = t.AsDouble(fp)
            return None if v is None else round(v * FT2MM, 2)
        if st == StorageType.Integer:
            return t.AsInteger(fp)
        if st == StorageType.String:
            return t.AsString(fp)
        if st == StorageType.ElementId:
            eid = t.AsElementId(fp)
            return None if eid is None else eid.Value
    except Exception:
        return None
    return None


def inspect(path):
    res = {"file": path}
    opts = OpenOptions()
    doc = app.OpenDocumentFile(ModelPathUtils.ConvertUserVisiblePathToModelPath(path), opts)
    try:
        res["category"] = doc.OwnerFamily.FamilyCategory.Name if doc.OwnerFamily.FamilyCategory else None
        fm = doc.FamilyManager
        res["types"] = [t.Name for t in fm.Types]
        res["parameters"] = []
        for fp in fm.Parameters:
            res["parameters"].append({
                "name": fp.Definition.Name,
                "instance": fp.IsInstance,
                "formula": fp.Formula,
                "value": param_value(doc, fp),
            })

        res["views"] = [
            {"name": ename(v), "type": str(v.ViewType)}
            for v in FilteredElementCollector(doc).OfClass(View)
            if not v.IsTemplate
        ]

        res["ref_planes"] = []
        for rp in FilteredElementCollector(doc).OfClass(ReferencePlane):
            res["ref_planes"].append({
                "id": rp.Id.Value, "name": ename(rp),
                "bubble": pt(rp.BubbleEnd), "free": pt(rp.FreeEnd),
                "normal": [round(rp.Normal.X, 4), round(rp.Normal.Y, 4), round(rp.Normal.Z, 4)],
            })

        res["curves"] = []
        for ce in FilteredElementCollector(doc).OfClass(CurveElement):
            try:
                ls = ename(ce.LineStyle)
            except Exception:
                ls = None
            res["curves"].append({
                "id": ce.Id.Value,
                "class": ce.GetType().Name,
                "curve": curve_info(ce.GeometryCurve),
                "line_style": ls,
                "view": view_name(doc, ce),
                "sketch_plane": ename(ce.SketchPlane),
                "visibility": visibility(ce),
                "visible_param": visible_param(doc, ce),
            })

        res["forms"] = []
        for f in FilteredElementCollector(doc).OfClass(GenericForm):
            sub = None
            try:
                sub = f.Subcategory.Name if f.Subcategory is not None else None
            except Exception:
                pass
            res["forms"].append({
                "id": f.Id.Value, "class": f.GetType().Name, "name": ename(f),
                "subcategory": sub, "solid": f.IsSolid, "bbox": bbox(f),
                "visibility": visibility(f), "visible_param": visible_param(doc, f),
            })

        res["nested"] = []
        for fi in FilteredElementCollector(doc).OfClass(FamilyInstance):
            res["nested"].append({
                "id": fi.Id.Value, "family": ename(fi.Symbol.Family),
                "type": ename(fi.Symbol), "bbox": bbox(fi),
                "view": view_name(doc, fi),
                "visible_param": visible_param(doc, fi),
            })

        res["dimensions"] = []
        for d in FilteredElementCollector(doc).OfClass(Dimension):
            lbl = None
            try:
                lbl = d.FamilyLabel.Definition.Name if d.FamilyLabel is not None else None
            except Exception:
                pass
            res["dimensions"].append({
                "id": d.Id.Value, "label": lbl, "view": view_name(doc, d),
                "refs": [r.ElementId.Value for r in d.References],
                "value": mm(d.Value) if d.Value is not None else None,
            })
    finally:
        doc.Close(False)
    return res


report = []
for p in [REF] + TARGETS:
    try:
        report.append(inspect(p))
    except Exception:
        report.append({"file": p, "error": traceback.format_exc()})

with open(OUT_PATH, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)

OUT = OUT_PATH
