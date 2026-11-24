# -*- coding: utf-8 -*-
__title__ = u"盤點視圖\n電纜架"
__doc__ = u"唯讀：盤點目前作用中視圖可見的電纜架與配件，依類型與尺寸統計數量與長度。"

from pyrevit import revit, script, forms
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter,
                               FilteredElementCollector)

import check_logic

output = script.get_output()
doc = revit.doc
FEET_TO_MM = 304.8


def type_name(element):
    try:
        type_el = doc.GetElement(element.GetTypeId())
        param = type_el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        return (param.AsString() if param else None) or u"(未命名)"
    except Exception:
        return u"(未知)"


def mm(element, bip):
    param = element.get_Parameter(bip)
    if param is None or not param.HasValue:
        return None
    return int(round(param.AsDouble() * FEET_TO_MM))


def size_text(element):
    width = mm(element, BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
    height = mm(element, BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)
    if width is None or height is None:
        return u"-"
    return u"%dx%d" % (width, height)


def length_m(element):
    param = element.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
    if param is None or not param.HasValue:
        return None
    return param.AsDouble() * FEET_TO_MM / 1000.0


def collect(view, category, kind):
    items = []
    collector = FilteredElementCollector(doc, view.Id).OfCategory(category).WhereElementIsNotElementType()
    for element in collector:
        items.append({"kind": kind, "type": type_name(element), "size": size_text(element),
                      "length_m": length_m(element) if kind == "tray" else None})
    return items


def main():
    view = doc.ActiveView
    try:
        items = (collect(view, BuiltInCategory.OST_CableTray, "tray")
                 + collect(view, BuiltInCategory.OST_CableTrayFitting, "fitting"))
    except Exception as err:
        forms.alert(u"目前視圖無法盤點（明細表、圖紙等非圖形視圖不支援）：%s" % err, exitscript=True)

    if not items:
        forms.alert(u"視圖「%s」沒有電纜架或配件。" % view.Name, exitscript=True)

    rows = check_logic.tally_trays(items)
    kind_label = {"tray": u"電纜架", "fitting": u"配件"}
    total_len = sum(r["length_m"] for r in rows)
    output.print_md(u"# 視圖電纜架盤點\n視圖：%s\n\n電纜架 %d 段、配件 %d 個；電纜架總長 %.2f m。"
                    % (view.Name, len([i for i in items if i["kind"] == "tray"]),
                       len([i for i in items if i["kind"] == "fitting"]), total_len))
    table = [[kind_label[r["kind"]], r["type"], r["size"], r["count"],
              r["length_m"] if r["kind"] == "tray" else u"-"] for r in rows]
    output.print_table(table_data=table, columns=[u"類別", u"類型", u"尺寸(寬x高 mm)", u"數量", u"長度(m)"])


main()
