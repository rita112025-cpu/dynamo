# -*- coding: utf-8 -*-
__title__ = u"讀取\nSCADA參數"
__doc__ = u"唯讀：列出目前模型所有 SCADA 機櫃的 16 個共用參數，標出缺少與空白。"

import System
from pyrevit import revit, script, forms
from Autodesk.Revit.DB import BuiltInCategory, FilteredElementCollector, StorageType

import check_logic

output = script.get_output()
doc = revit.doc


def family_name(element):
    try:
        return doc.GetElement(element.GetTypeId()).FamilyName
    except Exception:
        return u""


def read_value(element, name, guid):
    """None = parameter missing, u"" = present but blank."""
    param = None
    try:
        param = element.get_Parameter(System.Guid(guid))
    except Exception:
        param = None
    if param is None:
        param = element.LookupParameter(name)
    if param is None:
        return None
    if not param.HasValue:
        return u""
    if param.StorageType == StorageType.String:
        return param.AsString() or u""
    return param.AsValueString() or u""


def main():
    spec = check_logic.load_scada_params()
    params = spec["parameters"]
    names = [p["name"] for p in params]
    keyword = spec["applies_to"]["family_name_contains"]

    racks = []
    collector = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_ElectricalEquipment)
                 .WhereElementIsNotElementType())
    for element in collector:
        fam = family_name(element)
        if not check_logic.is_scada_rack(fam, keyword):
            continue
        values = dict((p["name"], read_value(element, p["name"], p["guid"])) for p in params)
        racks.append({"id": element.Id, "family": fam, "values": values})

    if not racks:
        forms.alert(u"目前模型找不到族群名稱含「%s」的電氣設備。" % keyword, exitscript=True)

    rows, totals = check_logic.summarize_racks(racks, names)
    output.print_md(u"# SCADA 機櫃參數檢查\n模型：%s\n\n機櫃 %d 台；完整 %d 台；缺少參數 %d 項；空白 %d 項。"
                    % (doc.Title, totals["racks"], totals["complete"], totals["missing"], totals["empty"]))
    table = []
    for row in rows:
        table.append([output.linkify(row["id"]), row["family"],
                      u"、".join(row["missing"]) or u"-",
                      u"、".join(row["empty"]) or u"-"])
    output.print_table(table_data=table, columns=[u"元件", u"族群", u"缺少參數", u"空白參數"])


main()
