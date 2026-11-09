# Batch parameter tools for every .rvt file of a folder (check / compose / space).
#
# IN[0]: folder path (string) or list of .rvt paths
# IN[1]: category names (BuiltInCategory, e.g. "OST_Conduit"); empty list = the SCADA categories
# IN[2]: mode  "check" | "compose" | "space"
# IN[3]: spec (list of text, depends on the mode, see below)
# IN[4]: True  = write and save / synchronize each file (compose / space only)
#        False = dry run: files are opened, planned changes are listed, nothing is saved
#
# mode "check"   (always read-only) spec = parameter rules, one text per rule
#     "備註"                       the parameter must not be empty
#     "設備編號~^[A-Z]+-[0-9]{3}$"  must not be empty AND must match the regular expression
# mode "compose" spec = [target parameter, template, optional "overwrite"]
#     ["設備編號", "{樓層}-{備註}-{#:3}"]
#     {參數名} = value of that parameter, also {類別} {族群} {類型} {樓層}
#     {#:3}    = serial number, 3 digits; it restarts from 1 for every different text around it
#     Existing codes are never changed: empty targets are filled and numbering continues after
#     the highest existing number. "overwrite" renumbers everything. An element whose {參數名}
#     source is empty is skipped. Serial order: level, then X, then Y.
# mode "space"   spec = ["目標參數=來源", ...] with source  Room.Number | Room.Name | Level
#     ["房間編號=Room.Number", "房間名稱=Room.Name", "樓層=Level"]
#     Rooms are searched in this model first, then in loaded Revit links. Empty targets are
#     filled and different values are updated (the values are derived data).
#
# Only text parameters are written. Needs a text instance parameter on the elements.
import clr, os, re, uuid, shutil

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System import String

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

src_in = IN[0]
CAT_NAMES = [str(c).strip() for c in IN[1]] if len(IN) > 1 and IN[1] else []
MODE = str(IN[2]).strip().lower() if len(IN) > 2 and IN[2] else ""
SPEC = [str(s).strip() for s in IN[3]] if len(IN) > 3 and IN[3] else []
RUN = bool(IN[4]) if len(IN) > 4 else False

DEFAULT_CATEGORIES = [
    "OST_Conduit", "OST_ConduitFitting", "OST_CableTray", "OST_CableTrayFitting",
    "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_Wire",
]
# Safety: only files whose name contains this text are processed ("" = no check).
FILE_NAME_MUST_CONTAIN = "-ESC-"
SAMPLE_IDS = 8


# ---- pure helpers (no Revit API) ----
TOKEN_RE = re.compile(r"\{([^{}]+)\}")
SERIAL_RE = re.compile(r"^#(?::(\d+))?$")


def parse_template(tpl):
    """-> (left parts, right parts, serial width or None). Parts are ("lit", text) / ("tok", name).
    Without a serial token everything is in the left parts."""
    left, right, width, seen = [], [], None, False
    cur = left
    for i, piece in enumerate(TOKEN_RE.split(tpl)):
        if i % 2 == 0:
            if piece:
                cur.append(("lit", piece))
            continue
        m = SERIAL_RE.match(piece.strip())
        if m:
            if seen:
                raise ValueError("only one {#} serial token is allowed")
            seen = True
            width = int(m.group(1) or 1)
            cur = right
        else:
            cur.append(("tok", piece.strip()))
    return left, right, width


def fill_parts(parts, getter):
    """Join the parts; None when a {token} has no value."""
    out = []
    for kind, v in parts:
        if kind == "lit":
            out.append(v)
        else:
            s = getter(v)
            if not s:
                return None
            out.append(s)
    return "".join(out)


def assign_serials(items, width, overwrite):
    """items: list of (index, sort key, left text, right text, current value).
    Returns {index: new value} for the items that must get a (new) serial number."""
    result, groups = {}, {}
    for it in items:
        groups.setdefault((it[2], it[3]), []).append(it)
    for (left, right), grp in groups.items():
        pat = re.compile("^" + re.escape(left) + r"(\d+)" + re.escape(right) + "$")
        highest, todo = 0, []
        for idx, key, _l, _r, cur in grp:
            cur = (cur or "").strip()
            if overwrite or cur == "":
                todo.append((key, idx))
                continue
            m = pat.match(cur)
            if m:
                highest = max(highest, int(m.group(1)))
        for n, (key, idx) in enumerate(sorted(todo), highest + 1):
            result[idx] = left + str(n).zfill(width) + right
    return result


def parse_check_spec(text):
    name, _, rx = text.partition("~")
    return name.strip(), (re.compile(rx.strip()) if rx.strip() else None)


def parse_space_spec(text):
    target, _, source = text.partition("=")
    return target.strip(), source.strip()
# ---- end pure helpers ----


def norm(p):
    return os.path.normcase(os.path.abspath(p))


def to_list(x):
    if x is None:
        return []
    if isinstance(x, str):
        if not x.strip():
            return []
        if os.path.isdir(x):
            return [os.path.join(x, f) for f in sorted(os.listdir(x))
                    if f.lower().endswith('.rvt')
                    and not re.search(r'\.\d{4}\.rvt$', f, re.I)]  # skip backups
        return [x]
    return [str(p) for p in x if p]


def doc_paths(d):
    """File path of a document plus its central model path (if workshared)."""
    paths = set()
    if d.PathName:
        paths.add(norm(d.PathName))
    if d.IsWorkshared:
        try:
            central = ModelPathUtils.ConvertModelPathToUserVisiblePath(
                d.GetWorksharingCentralModelPath())
            if central:
                paths.add(norm(central))
        except Exception:
            pass
    return paths


NS = "BatchParam_" + uuid.uuid4().hex  # unique namespace so re-runs don't clash
fail_msgs = []


class SuppressWarnings(IFailuresPreprocessor):
    """Delete warnings silently; roll back on errors instead of showing a dialog."""
    __namespace__ = NS

    def PreprocessFailures(self, accessor):
        has_error = False
        for f in accessor.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                accessor.DeleteWarning(f)
            else:
                has_error = True
                fail_msgs.append(f.GetDescriptionText())
        if has_error:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def version_ok(info):
    fmt = getattr(info, 'Format', None) or info.SavedInVersion
    return str(app.VersionNumber) in str(fmt)


def open_target(path, info, write):
    """Return (document, temp local path or None). All worksets are opened so that no element
    is silently missed. Read-only runs of a workshared file are opened detached: no local file
    is created and the central model is never touched."""
    mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
    opts = OpenOptions()
    local = None
    if info.IsWorkshared:
        opts.SetOpenWorksetsConfiguration(
            WorksetConfiguration(WorksetConfigurationOption.OpenAllWorksets))
        if not write:
            opts.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
        else:
            opts.DetachFromCentralOption = DetachFromCentralOption.DoNotDetach
            if info.IsCentral:
                local = os.path.join(os.environ.get('TEMP'),
                                     'BatchParam_%s_%s' % (uuid.uuid4().hex[:8], os.path.basename(path)))
                local_mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(local)
                WorksharingUtils.CreateNewLocal(mp, local_mp)
                mp = local_mp
    return app.OpenDocumentFile(mp, opts), local


def remove_temp_local(local):
    if not local:
        return
    try:
        if os.path.exists(local):
            os.remove(local)
        shutil.rmtree(os.path.splitext(local)[0] + '_backup', ignore_errors=True)
    except Exception:
        pass


def save(tdoc):
    if tdoc.IsWorkshared:
        swc = SynchronizeWithCentralOptions()
        swc.SetRelinquishOptions(RelinquishOptions(True))
        swc.Comment = "Batch parameter tools: " + MODE
        tdoc.SynchronizeWithCentral(TransactWithCentralOptions(), swc)
    else:
        tdoc.Save()


def eid(el):
    i = el.Id
    try:
        return int(i.Value)
    except AttributeError:
        return int(i.IntegerValue)


def param_value(p):
    """Display text of a parameter ("" when missing or without value)."""
    if p is None or not p.HasValue:
        return ""
    if p.StorageType == StorageType.String:
        return (p.AsString() or "").strip()
    return (p.AsValueString() or "").strip()


def lookup_text(el, tdoc, name):
    """Value of a parameter on the element, else on its type."""
    v = param_value(el.LookupParameter(name))
    if v:
        return v
    t = tdoc.GetElement(el.GetTypeId())
    return param_value(t.LookupParameter(name)) if t is not None else ""


def level_of(tdoc, el):
    try:
        lid = el.LevelId
        if lid is None or lid == ElementId.InvalidElementId:
            p = el.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM)
            lid = p.AsElementId() if p is not None else None
        if lid is not None and lid != ElementId.InvalidElementId:
            return tdoc.GetElement(lid)
    except Exception:
        pass
    return None


def location_point(el):
    loc = el.Location
    if loc is None:
        return None
    pt = getattr(loc, "Point", None)
    if pt is not None:
        return pt
    crv = getattr(loc, "Curve", None)
    if crv is not None:
        return crv.Evaluate(0.5, True)
    return None


def sort_key(tdoc, el):
    lv = level_of(tdoc, el)
    pt = location_point(el)
    elev = lv.Elevation if lv is not None else 0.0
    x, y = (pt.X, pt.Y) if pt is not None else (0.0, 0.0)
    return (round(elev, 3), round(x, 2), round(y, 2), eid(el))


def cat_label(tdoc, bic, name):
    try:
        return Category.GetCategory(tdoc, bic).Name
    except Exception:
        return name


def collect_groups(tdoc):
    groups = []
    for name in CAT_NAMES or DEFAULT_CATEGORIES:
        bic = getattr(BuiltInCategory, name, None) or getattr(BuiltInCategory, "OST_" + name, None)
        if bic is None:
            continue
        els = list(FilteredElementCollector(tdoc).OfCategory(bic).WhereElementIsNotElementType())
        groups.append((cat_label(tdoc, bic, name), els))
    return groups


def ids_text(ids):
    shown = ",".join(str(i) for i in ids[:SAMPLE_IDS])
    return shown + (",..." if len(ids) > SAMPLE_IDS else "")


# ---- mode: check ----
def run_check(tdoc, rules):
    lines = []
    for label, els in collect_groups(tdoc):
        if not els:
            continue
        lines.append("    %s (n=%d)" % (label, len(els)))
        for name, rx in rules:
            empty, bad, missing = [], [], 0
            for el in els:
                p = el.LookupParameter(name)
                if p is None:
                    missing += 1
                    continue
                v = param_value(p)
                if v == "":
                    empty.append(eid(el))
                elif rx is not None and not rx.search(v):
                    bad.append(eid(el))
            if not (empty or bad or missing):
                lines.append("      %s: OK" % name)
                continue
            parts = []
            if missing:
                parts.append("無此參數 %d" % missing)
            if empty:
                parts.append("空值 %d (ids: %s)" % (len(empty), ids_text(empty)))
            if bad:
                parts.append("格式不符 %d (ids: %s)" % (len(bad), ids_text(bad)))
            lines.append("      %s: %s" % (name, " | ".join(parts)))
    return lines


# ---- mode: compose ----
def plan_compose(tdoc, target, tpl, overwrite):
    left_parts, right_parts, width = parse_template(tpl)
    lines, plan = [], []
    for label, els in collect_groups(tdoc):
        if not els:
            continue
        c = {"set": 0, "same": 0, "keep": 0, "nosrc": 0, "noparam": 0}
        items, targets = [], {}
        for el in els:
            p = el.LookupParameter(target)
            if p is None or p.IsReadOnly or p.StorageType != StorageType.String:
                c["noparam"] += 1
                continue

            def getter(name, el=el):
                low = name.lower()
                if low in ("類別", "category"):
                    return el.Category.Name if el.Category is not None else ""
                if low in ("族群", "family"):
                    t = tdoc.GetElement(el.GetTypeId())
                    return getattr(t, "FamilyName", "") if t is not None else ""
                if low in ("類型", "type"):
                    t = tdoc.GetElement(el.GetTypeId())
                    return t.Name if t is not None else ""
                if low in ("樓層", "level"):
                    lv = level_of(tdoc, el)
                    return lv.Name if lv is not None else ""
                return lookup_text(el, tdoc, name)

            left = fill_parts(left_parts, getter)
            right = fill_parts(right_parts, getter)
            if left is None or right is None:
                c["nosrc"] += 1
                continue
            cur = (p.AsString() or "").strip()
            if width is None:
                if cur == left:
                    c["same"] += 1
                elif cur == "" or overwrite:
                    plan.append((el, p, left))
                    c["set"] += 1
                else:
                    c["keep"] += 1
                continue
            idx = len(items)
            items.append((idx, sort_key(tdoc, el), left, right, cur))
            targets[idx] = (el, p, cur)
        if width is not None:
            new_values = assign_serials(items, width, overwrite)
            for idx, new in new_values.items():
                el, p, cur = targets[idx]
                if cur == new:
                    c["same"] += 1
                else:
                    plan.append((el, p, new))
                    c["set"] += 1
            c["keep"] += len(items) - len(new_values)
        lines.append("    %s [%s]: 填入 %d, 已是目標值 %d, 保留既有值 %d, 來源參數為空略過 %d, 無此參數或唯讀 %d"
                     % (label, target, c["set"], c["same"], c["keep"], c["nosrc"], c["noparam"]))
    return lines, plan


# ---- mode: space ----
def room_finder(tdoc):
    links = []
    for li in FilteredElementCollector(tdoc).OfClass(RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is not None:
            links.append((ld, li.GetTotalTransform().Inverse))

    def find(el):
        try:
            r = el.Room
            if r is not None:
                return r
        except Exception:
            pass
        pt = location_point(el)
        if pt is None:
            return None
        probes = [pt]
        lv = level_of(tdoc, el)
        if lv is not None:
            probes.append(XYZ(pt.X, pt.Y, lv.Elevation + 1.0))
        for q in probes:
            try:
                r = tdoc.GetRoomAtPoint(q)
                if r is not None:
                    return r
            except Exception:
                pass
            for ld, inv in links:
                try:
                    r = ld.GetRoomAtPoint(inv.OfPoint(q))
                    if r is not None:
                        return r
                except Exception:
                    pass
        return None
    return find


def room_text(room, bip):
    p = room.get_Parameter(bip)
    return (p.AsString() or "").strip() if p is not None else ""


def plan_space(tdoc, pairs):
    find_room = room_finder(tdoc)
    sources = {"room.number": BuiltInParameter.ROOM_NUMBER, "room.name": BuiltInParameter.ROOM_NAME}
    lines, plan = [], []
    for label, els in collect_groups(tdoc):
        if not els:
            continue
        c = {"set": 0, "update": 0, "same": 0, "noroom": 0, "noparam": 0}
        for el in els:
            room = None
            room_done = False
            for target, source in pairs:
                p = el.LookupParameter(target)
                if p is None or p.IsReadOnly or p.StorageType != StorageType.String:
                    c["noparam"] += 1
                    continue
                src = source.lower()
                if src == "level":
                    lv = level_of(tdoc, el)
                    val = lv.Name if lv is not None else ""
                else:
                    if not room_done:
                        room, room_done = find_room(el), True
                    val = room_text(room, sources[src]) if room is not None else ""
                    if not val:
                        c["noroom"] += 1
                        continue
                if not val:
                    continue
                cur = (p.AsString() or "").strip()
                if cur == val:
                    c["same"] += 1
                else:
                    plan.append((el, p, val))
                    c["update" if cur else "set"] += 1
        lines.append("    %s: 填入 %d, 更新 %d, 已相同 %d, 找不到房間 %d, 無此參數或唯讀 %d"
                     % (label, c["set"], c["update"], c["same"], c["noroom"], c["noparam"]))
    return lines, plan


def apply_plan(tdoc, plan):
    """Write the planned values in one transaction. Returns the number of failed writes."""
    del fail_msgs[:]
    t = Transaction(tdoc, "Batch parameter tools: " + MODE)
    t.Start()
    failed = 0
    try:
        for el, p, new in plan:
            try:
                p.Set.Overloads[String](new)
            except Exception:
                failed += 1  # for example owned by another user
        fho = t.GetFailureHandlingOptions()
        fho.SetFailuresPreprocessor(SuppressWarnings())
        fho.SetClearAfterRollback(True)
        status = t.Commit(fho)
        if status != TransactionStatus.Committed:
            raise Exception("rolled back: " + "; ".join(fail_msgs))
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return failed


def process(tdoc, write):
    """Returns (report lines, number of values written)."""
    if MODE == "check":
        return run_check(tdoc, CHECK_RULES), 0
    if MODE == "compose":
        lines, plan = plan_compose(tdoc, SPEC[0], SPEC[1], OVERWRITE)
    else:
        lines, plan = plan_space(tdoc, SPACE_PAIRS)
    if write and plan:
        failed = apply_plan(tdoc, plan)
        lines.append("    已寫入 %d, 失敗 %d" % (len(plan) - failed, failed))
        return lines, len(plan) - failed
    return lines, 0


# ---- validate the spec before any file is opened ----
report = []
CHECK_RULES, SPACE_PAIRS, OVERWRITE = [], [], False
try:
    if MODE == "check":
        CHECK_RULES = [parse_check_spec(s) for s in SPEC]
        if not CHECK_RULES:
            raise ValueError('mode "check" needs at least one parameter rule in IN[3]')
    elif MODE == "compose":
        if len(SPEC) < 2:
            raise ValueError('mode "compose" needs [target parameter, template] in IN[3]')
        parse_template(SPEC[1])
        OVERWRITE = len(SPEC) > 2 and SPEC[2].lower() == "overwrite"
    elif MODE == "space":
        SPACE_PAIRS = [parse_space_spec(s) for s in SPEC]
        for target, source in SPACE_PAIRS:
            if not target or source.lower() not in ("room.number", "room.name", "level"):
                raise ValueError('bad space rule "%s=%s" (source: Room.Number | Room.Name | Level)' % (target, source))
        if not SPACE_PAIRS:
            raise ValueError('mode "space" needs rules like "房間編號=Room.Number" in IN[3]')
    else:
        raise ValueError('IN[2] must be "check", "compose" or "space"')
except Exception as ex:
    report.append("[ERROR spec] %s" % ex)
    MODE = ""

WRITE = RUN and MODE in ("compose", "space")
if MODE:
    report.append("Mode: %s | %s | spec: %s" % (
        MODE, "WRITE" if WRITE else ("READ ONLY" if MODE == "check" else "DRY RUN (nothing is saved)"),
        " ; ".join(SPEC)))

if MODE:
    # The current document is never a target; documents already open or loaded as links cannot be reopened
    src_paths = doc_paths(doc)
    open_paths = set()
    for d in app.Documents:
        open_paths |= doc_paths(d)
    open_paths -= src_paths

    targets = [p for p in to_list(src_in) if norm(p) not in src_paths]
    if not targets:
        report.append("[NO TARGET FILES] check IN[0] folder path")

    # Close Dynamo's own transaction before opening other documents
    TransactionManager.Instance.ForceCloseTransaction()
    for p in targets:
        if norm(p) in open_paths:
            report.append("[SKIP already open or loaded as link - unload it first] " + p)
            continue
        if FILE_NAME_MUST_CONTAIN and FILE_NAME_MUST_CONTAIN.upper() not in os.path.basename(p).upper():
            report.append("[SKIP file name has no '%s' - not a SCADA file] %s" % (FILE_NAME_MUST_CONTAIN, p))
            continue
        try:
            info = BasicFileInfo.Extract(p)
        except Exception as ex:
            report.append("[ERROR read] %s: %s" % (p, ex))
            continue
        if not version_ok(info):
            report.append("[SKIP version mismatch] " + p)
            continue
        tdoc, local = None, None
        try:
            tdoc, local = open_target(p, info, WRITE)
            lines, written = process(tdoc, WRITE)
            if WRITE and written > 0:
                save(tdoc)
            tag = "[CHECK]" if MODE == "check" else ("[OK]" if WRITE else "[DRY RUN]")
            if WRITE and written == 0:
                tag = "[OK nothing to change]"
            report.append("%s %s (workshared=%s)" % (tag, p, info.IsWorkshared))
            report += lines
        except Exception as ex:
            report.append("[ERROR] %s: %s" % (p, ex))
        finally:
            if tdoc is not None:
                tdoc.Close(False)
            remove_temp_local(local)

# The Watch node truncates long lines, so keep the full report in a text file as well
try:
    with open(os.path.join(os.environ.get('TEMP'), 'BatchParamTools_last_report.txt'), 'w', encoding='utf-8') as fh:
        fh.write("\n".join(report))
except Exception:
    pass

OUT = report
