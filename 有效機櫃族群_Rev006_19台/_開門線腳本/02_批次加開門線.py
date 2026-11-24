# Dynamo for Revit 2025 - Python Script node (CPython3)
# Stage 2: add door-swing model lines to every main cabinet family in DIR.
#
# Door layout (per user's CAD sketch):
#   - one single-leaf door on EACH short face (front Y=min, back Y=max)
#   - door width = cabinet width (X extent of the main extrusion)
#   - both doors are right-hand (HAND): seen from in front of each door, the
#     hinge is on the viewer's right -> front hinge at +X, back hinge at -X
#   - door swings outward 90 deg
#   - drawn as MODEL lines (visible in plan, 3D and elevations):
#     open leaf line (perpendicular to face) + 90 deg arc
# Lines go on subcategory DOOR_SUBCAT so they can be toggled in V/G.
# Re-running is safe: existing curves on DOOR_SUBCAT are deleted first.
# Backup files (*.0001.rfa etc.) are skipped. Files already open in Revit are skipped.
# Each file is copied to BACKUP_DIR before it is opened/saved (Revit .000N backups
# are NOT relied on: these families keep only one).
# OUT = list of per-file results.

import clr
import os
import re
import shutil
import traceback
from datetime import datetime

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import (
    FilteredElementCollector, CurveElement, Extrusion, Line, Arc, XYZ, Plane,
    SketchPlane, Transaction, GraphicsStyleType, ModelPathUtils, OpenOptions,
)
from RevitServices.Persistence import DocumentManager

DIR = r"D:\族群_汐東縣\SCADA_主題導覽\12 SoW_V6_規範追溯\有效機櫃族群_Rev006_19台"
DOOR_SUBCAT = "開門線"
HAND = 1  # +1 = right-hand doors (hinge on viewer's right), -1 = left-hand
ONLY = []  # file names to process; empty = every main .rfa in DIR
BACKUP_RE = re.compile(r"\.\d{4}\.rfa$", re.IGNORECASE)
BACKUP_DIR = os.path.join(DIR, "_備份_" + datetime.now().strftime("%Y%m%d_%H%M%S"))

app = DocumentManager.Instance.CurrentUIApplication.Application


def target_files():
    return sorted(
        os.path.join(DIR, f) for f in os.listdir(DIR)
        if f.lower().endswith(".rfa") and not BACKUP_RE.search(f)
        and (not ONLY or f in ONLY)
    )


def is_open(path):
    for d in app.Documents:
        if d.PathName and os.path.normcase(d.PathName) == os.path.normcase(path):
            return True
    return False


def cabinet_extents(doc):
    exts = list(FilteredElementCollector(doc).OfClass(Extrusion))
    if not exts:
        raise ValueError("no extrusion found")
    bbs = [e.get_BoundingBox(None) for e in exts if e.IsSolid]
    bbs = [b for b in bbs if b is not None]
    min_x = min(b.Min.X for b in bbs)
    max_x = max(b.Max.X for b in bbs)
    min_y = min(b.Min.Y for b in bbs)
    max_y = max(b.Max.Y for b in bbs)
    return min_x, max_x, min_y, max_y


def door_subcategory(doc):
    parent = doc.OwnerFamily.FamilyCategory
    if parent.SubCategories.Contains(DOOR_SUBCAT):
        return parent.SubCategories.get_Item(DOOR_SUBCAT)
    return doc.Settings.Categories.NewSubcategory(parent, DOOR_SUBCAT)


def door_curves(min_x, max_x, face_y, outward):
    """Leaf opens outward (outward = -1 front face, +1 back face).
    Viewer outside the face looks in -outward direction; their right is X = -outward * HAND."""
    width = max_x - min_x
    hinge_sign = -outward * HAND
    hx, fx = (max_x, min_x) if hinge_sign > 0 else (min_x, max_x)
    hinge = XYZ(hx, face_y, 0)
    closed_tip = XYZ(fx, face_y, 0)
    open_tip = XYZ(hx, face_y + outward * width, 0)
    # point at 45 deg between closed and open positions
    v1 = closed_tip.Subtract(hinge).Normalize()
    v2 = open_tip.Subtract(hinge).Normalize()
    mid = hinge.Add(v1.Add(v2).Normalize().Multiply(width))
    return [Line.CreateBound(hinge, open_tip), Arc.Create(closed_tip, open_tip, mid)]


def process(path):
    if is_open(path):
        return "SKIP (open in Revit, close it and re-run)"
    os.makedirs(BACKUP_DIR, exist_ok=True)
    shutil.copy2(path, os.path.join(BACKUP_DIR, os.path.basename(path)))
    doc = app.OpenDocumentFile(ModelPathUtils.ConvertUserVisiblePathToModelPath(path), OpenOptions())
    try:
        min_x, max_x, min_y, max_y = cabinet_extents(doc)
        t = Transaction(doc, "Add door swing lines")
        t.Start()
        try:
            sub = door_subcategory(doc)
            style = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
            old = [c.Id for c in FilteredElementCollector(doc).OfClass(CurveElement)
                   if c.LineStyle is not None and c.LineStyle.Id == style.Id]
            for eid in old:
                doc.Delete(eid)
            sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))
            curves = door_curves(min_x, max_x, min_y, -1) + door_curves(min_x, max_x, max_y, 1)
            for c in curves:
                sc = doc.FamilyCreate.NewModelCurve(c, sp)
                sc.LineStyle = style
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        doc.Save()
        w = round((max_x - min_x) * 304.8)
        d = round((max_y - min_y) * 304.8)
        return "OK {}x{} (removed {} old, added {})".format(w, d, len(old), len(curves))
    finally:
        doc.Close(False)


results = []
for p in target_files():
    name = os.path.basename(p)
    try:
        results.append("{}: {}".format(name, process(p)))
    except Exception:
        results.append("{}: ERROR {}".format(name, traceback.format_exc().splitlines()[-1]))

OUT = results
