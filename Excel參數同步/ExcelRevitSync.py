# Excel <-> Revit parameter sync for the CURRENT document.
# The .xlsx file is read / written with the Python standard library, so Excel does not
# have to be installed (and must be CLOSED while this script writes the file).
#
# IN[0]: mode  "export" | "import"
# IN[1]: path of the .xlsx file
# IN[2]: category names (BuiltInCategory, e.g. "OST_Conduit"); empty list = the SCADA categories
#        (export only)
# IN[3]: export: parameter names to export; empty list = every writable text / number /
#        yes-no instance parameter found on the elements
#        import: when not empty, only these columns are written back
# IN[4]: True = write to the model (import only); False = dry run, nothing is changed
#
# Sheet layout (row 1 = header):
#   grey columns   UniqueId / ElementId / 類別 / 族群 / 類型 / 樓層  -> identify the row, never written
#   other columns  header = parameter name, written back on import
#
# Import rules (never destructive):
#   - rows are matched by UniqueId (ElementId only when the UniqueId cell is empty)
#   - an EMPTY cell is skipped: a blank never clears a value in the model
#   - same value                      -> left alone
#   - read-only / missing parameter   -> counted, not changed
#   - Yes/No parameters accept 是/否, yes/no, true/false, 1/0
#   - length / number parameters use the project display units (the same text export writes)
import clr, os, re, zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System import String, Int32, Int64

doc = DocumentManager.Instance.CurrentDBDocument

MODE = str(IN[0]).strip().lower() if len(IN) > 0 and IN[0] else ""
XLSX_PATH = str(IN[1]).strip() if len(IN) > 1 and IN[1] else ""
CATEGORIES = [str(c).strip() for c in IN[2]] if len(IN) > 2 and IN[2] else []
PARAM_NAMES = [str(n).strip() for n in IN[3]] if len(IN) > 3 and IN[3] else []
RUN = bool(IN[4]) if len(IN) > 4 else False

DEFAULT_CATEGORIES = [
    "OST_Conduit", "OST_ConduitFitting", "OST_CableTray", "OST_CableTrayFitting",
    "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_Wire",
]
FIXED = ["UniqueId", "ElementId", "類別", "族群", "類型", "樓層"]
SAMPLE_PER_CATEGORY = 300  # elements inspected per category when the parameter list is built
YES = ("是", "yes", "y", "true", "t", "1")
NO = ("否", "no", "n", "false", "f", "0")
SHEET_NAME = "Revit參數"


# ---- xlsx reader / writer (standard library only) ----
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_XML_BAD = re.compile(u"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '</Types>')
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>')
_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>')
# cellXfs: 0 normal | 1 bold + yellow (editable header) | 2 bold + grey (fixed header) | 3 grey (fixed cell)
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="4"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFD9D9D9"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFill="1"/>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')


def col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(ref):
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def text_width(s):
    return sum(2 if ord(ch) > 255 else 1 for ch in s)


def write_xlsx(path, rows, n_fixed):
    """rows[0] is the header; the first n_fixed columns are shown grey (never imported)."""
    ncols = max(len(r) for r in rows)
    last = col_letter(ncols - 1)
    widths = [8] * ncols
    for r in rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], min(60, text_width(v) + 2))
    xml_rows = []
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, v in enumerate(row):
            if ri == 1:
                style = 2 if ci < n_fixed else 1
            else:
                style = 3 if ci < n_fixed else 0
            if v == "" and style == 0:
                continue
            attr = ' s="%d"' % style if style else ""
            cells.append('<c r="%s%d" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>'
                         % (col_letter(ci), ri, attr, escape(_XML_BAD.sub("", v))))
        xml_rows.append('<row r="%d">%s</row>' % (ri, "".join(cells)))
    cols = "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, w)
                   for i, w in enumerate(widths))
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:%s%d"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<cols>%s</cols><sheetData>%s</sheetData>'
        '<autoFilter ref="A1:%s%d"/></worksheet>'
        % (last, len(rows), cols, "".join(xml_rows), last, len(rows)))
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>'
        '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
        "'%s'!$A$1:$%s$%d</definedName></definedNames></workbook>"
        % (SHEET_NAME, SHEET_NAME, last, len(rows)))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def _rich_text(node):
    """Text of a shared string <si> or an inline <is>, without phonetic runs."""
    out = []
    for ch in node:
        if ch.tag == _MAIN + "t":
            out.append(ch.text or "")
        elif ch.tag == _MAIN + "r":
            out.extend(t.text or "" for t in ch.findall(_MAIN + "t"))
    return "".join(out)


def _fmt_num(v):
    try:
        f = float(v)
        if f == int(f) and abs(f) < 1e15:
            return str(int(f))
        return "%.12g" % f
    except (ValueError, OverflowError):
        return v


def read_xlsx(path):
    """First worksheet of an .xlsx file as a list of rows (lists of str)."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [_rich_text(si) for si in root.findall(_MAIN + "si")]
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid = wb.find(_MAIN + "sheets")[0].get(_REL + "id")
        target = [r.get("Target") for r in rels if r.get("Id") == rid][0]
        target = target[1:] if target.startswith("/") else "xl/" + target
        sheet = ET.fromstring(z.read(target))
    rows = []
    for row in sheet.find(_MAIN + "sheetData"):
        cells = {}
        for c in row:
            idx = col_index(c.get("r") or "")
            t = c.get("t")
            v = c.find(_MAIN + "v")
            if t == "inlineStr":
                val = _rich_text(c.find(_MAIN + "is")) if c.find(_MAIN + "is") is not None else ""
            elif v is None or v.text is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)]
            elif t in ("str", "b"):
                val = v.text
            elif t == "e":
                val = ""
            else:
                val = _fmt_num(v.text)
            cells[idx] = val
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows
# ---- end xlsx ----


# ---- value helpers ----
def num_prefix(s):
    m = re.match(r"^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
    if not m:
        return None, s
    return float(m.group(0)), s[m.end():]


def same_number_text(a, b):
    """True when two display strings mean the same value ('1,200 mm' == '1200mm')."""
    na = re.sub(r"[\s,]", "", a or "")
    nb = re.sub(r"[\s,]", "", b or "")
    if na == nb:
        return True
    fa, ta = num_prefix(na)
    fb, tb = num_prefix(nb)
    return fa is not None and fb is not None and ta == tb and abs(fa - fb) < 1e-9


def parse_yes_no(text):
    low = text.strip().lower()
    if low in YES:
        return 1
    if low in NO:
        return 0
    return None
# ---- end value helpers ----


def eid(el):
    i = el.Id
    try:
        return int(i.Value)
    except AttributeError:
        return int(i.IntegerValue)


def make_id(n):
    try:
        return ElementId(Int64(n))
    except Exception:
        return ElementId(n)


def is_yesno(p):
    try:
        return p.Definition.GetDataType().Equals(SpecTypeId.Boolean.YesNo)
    except Exception:
        return False


def param_text(p):
    """Text written to the sheet, or None for parameter types that are not supported."""
    st = p.StorageType
    if st == StorageType.String:
        return p.AsString() or ""
    if st == StorageType.Integer:
        if not p.HasValue:
            return ""
        if is_yesno(p):
            return "是" if p.AsInteger() else "否"
        return str(p.AsInteger())
    if st == StorageType.Double:
        return (p.AsValueString() or "") if p.HasValue else ""
    return None


def evaluate(p, text):
    """-> (action, new value); action is 'same', 'set', 'bad' or 'unsupported'."""
    st = p.StorageType
    if st == StorageType.String:
        return ("same" if (p.AsString() or "") == text else "set"), text
    if st == StorageType.Integer:
        if is_yesno(p):
            v = parse_yes_no(text)
            if v is None:
                return "bad", None
        else:
            try:
                f = float(text)
            except ValueError:
                return "bad", None
            if f != int(f):
                return "bad", None
            v = int(f)
        cur = p.AsInteger() if p.HasValue else None
        return ("same" if cur == v else "set"), v
    if st == StorageType.Double:
        cur = p.AsValueString() if p.HasValue else ""
        return ("same" if same_number_text(cur, text) else "set"), text
    return "unsupported", None


def apply_value(p, new):
    st = p.StorageType
    if st == StorageType.String:
        p.Set.Overloads[String](new)
        return True
    if st == StorageType.Integer:
        p.Set.Overloads[Int32](new)
        return True
    return bool(p.SetValueString(new))


def resolve_categories(names):
    found, bad = [], []
    for n in names:
        bic = getattr(BuiltInCategory, n, None) or getattr(BuiltInCategory, "OST_" + n, None)
        if bic is None:
            bad.append(n)
        else:
            found.append(bic)
    return found, bad


def collect_elements(bics):
    els = []
    for bic in bics:
        els.extend(FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType())
    return els


def level_name(el):
    try:
        lid = el.LevelId
        if lid is None or lid == ElementId.InvalidElementId:
            p = el.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM)
            lid = p.AsElementId() if p is not None else None
        if lid is not None and lid != ElementId.InvalidElementId:
            lv = doc.GetElement(lid)
            return lv.Name if lv is not None else ""
    except Exception:
        pass
    return ""


def type_info(el):
    t = doc.GetElement(el.GetTypeId())
    if t is None:
        return "", ""
    try:
        fam = t.FamilyName
    except Exception:
        fam = ""
    return fam, t.Name


def writable_parameter_names(elements):
    names, seen, per_cat = [], set(FIXED), {}
    for el in elements:
        cat = el.Category.Name if el.Category is not None else ""
        per_cat[cat] = per_cat.get(cat, 0) + 1
        if per_cat[cat] > SAMPLE_PER_CATEGORY:
            continue
        for p in el.Parameters:
            if p.IsReadOnly or p.Definition is None:
                continue
            if p.StorageType not in (StorageType.String, StorageType.Integer, StorageType.Double):
                continue
            n = p.Definition.Name
            if n and n not in seen:
                seen.add(n)
                names.append(n)
    return names


def run_export():
    report = []
    names = CATEGORIES or DEFAULT_CATEGORIES
    bics, bad = resolve_categories(names)
    report += ["[UNKNOWN category] " + n for n in bad]
    elements = collect_elements(bics)
    if not elements:
        return report + ["[NO ELEMENTS] check the category list"]
    pnames = PARAM_NAMES or writable_parameter_names(elements)
    rows = [FIXED + pnames]
    infos = []
    for el in elements:
        fam, typ = type_info(el)
        infos.append((el.Category.Name if el.Category is not None else "", fam, typ, eid(el), el))
    infos.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    for cat, fam, typ, i, el in infos:
        row = [el.UniqueId, str(i), cat, fam, typ, level_name(el)]
        for n in pnames:
            p = el.LookupParameter(n)
            text = param_text(p) if p is not None else None
            row.append(text or "")
        rows.append(row)
    write_xlsx(XLSX_PATH, rows, len(FIXED))
    report.append("[EXPORT OK] %d elements, %d parameter columns -> %s" % (len(elements), len(pnames), XLSX_PATH))
    report.append("Parameters: " + ", ".join(pnames))
    return report


def run_import():
    report = []
    rows = read_xlsx(XLSX_PATH)
    if not rows:
        return ["[EMPTY sheet] " + XLSX_PATH]
    header = [h.strip() for h in rows[0]]
    col_uid = header.index("UniqueId") if "UniqueId" in header else -1
    col_id = header.index("ElementId") if "ElementId" in header else -1
    if col_uid < 0 and col_id < 0:
        return ["[ERROR] header needs a UniqueId or ElementId column"]
    pcols = [(i, h) for i, h in enumerate(header)
             if h and h not in FIXED and (not PARAM_NAMES or h in PARAM_NAMES)]
    counts = {"rows": 0, "notfound": 0, "blank": 0, "same": 0, "set": 0, "bad": 0,
              "noparam": 0, "readonly": 0, "unsupported": 0, "failed": 0}
    plan, samples = [], []

    def cell(row, i):
        return row[i].strip() if 0 <= i < len(row) else ""

    for row in rows[1:]:
        uid, eid_text = cell(row, col_uid), cell(row, col_id)
        if not uid and not eid_text:
            continue
        counts["rows"] += 1
        el = None
        try:
            el = doc.GetElement(uid) if uid else doc.GetElement(make_id(int(float(eid_text))))
        except Exception:
            el = None
        if el is None:
            counts["notfound"] += 1
            continue
        for i, name in pcols:
            text = cell(row, i)
            if text == "":
                counts["blank"] += 1
                continue
            p = el.LookupParameter(name)
            if p is None:
                counts["noparam"] += 1
                continue
            if p.IsReadOnly:
                counts["readonly"] += 1
                continue
            action, new = evaluate(p, text)
            if action in ("same", "bad", "unsupported"):
                counts[action] += 1
                continue
            plan.append((el, p, new))
            if len(samples) < 40:
                samples.append("    [%d] %s: '%s' -> '%s'" % (eid(el), name, param_text(p), text))

    if RUN and plan:
        TransactionManager.Instance.EnsureInTransaction(doc)
        for el, p, new in plan:
            try:
                if apply_value(p, new):
                    counts["set"] += 1
                else:
                    counts["bad"] += 1
            except Exception:
                counts["failed"] += 1
        TransactionManager.Instance.TransactionTaskDone()
    else:
        counts["set"] = len(plan)

    verb = "已寫入" if RUN else "將寫入"
    report.append("[%s] %s" % ("IMPORT OK" if RUN else "DRY RUN (nothing is changed)", XLSX_PATH))
    report.append("  資料列 %d, 找不到元件 %d" % (counts["rows"], counts["notfound"]))
    report.append("  %s %d, 相同 %d, 空白略過 %d, 值無法解析 %d, 無此參數 %d, 唯讀 %d, 不支援型別 %d, 失敗 %d"
                  % (verb, counts["set"], counts["same"], counts["blank"], counts["bad"],
                     counts["noparam"], counts["readonly"], counts["unsupported"], counts["failed"]))
    if samples:
        report.append("  變更範例 (最多 40 筆):")
        report += samples
    return report


if not XLSX_PATH:
    report = ["[ERROR] IN[1] needs the .xlsx path"]
elif MODE == "export":
    try:
        report = run_export()
    except Exception as ex:
        report = ["[ERROR export] %s (is the file open in Excel?)" % ex]
elif MODE == "import":
    if not os.path.isfile(XLSX_PATH):
        report = ["[ERROR] file not found: " + XLSX_PATH]
    else:
        try:
            report = run_import()
        except Exception as ex:
            report = ["[ERROR import] %s" % ex]
else:
    report = ['[ERROR] IN[0] must be "export" or "import"']

try:
    with open(os.path.join(os.environ.get('TEMP'), 'ExcelSync_last_report.txt'), 'w', encoding='utf-8') as fh:
        fh.write("\n".join(report))
except Exception:
    pass

OUT = report
