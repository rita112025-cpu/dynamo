# Batch assign elements to worksets in every workshared .rvt file of a folder.
#
# IN[0]: folder path (string) or list of .rvt paths
# IN[1]: rules (list of text); empty list = DEFAULT_RULES below. One rule per text:
#            類別 -> 工作集名稱
#            類別 | 參數名=值 -> 工作集名稱
#        e.g.   "OST_Conduit -> SCADA_管線"
#               "OST_ElectricalEquipment | 備註=SCADA -> SCADA_設備"
#        The optional condition (parameter = value, case-insensitive) limits the rule to the
#        elements that carry that value, so other disciplines' elements in the same file are
#        left alone. Alternative parameter names are separated by "/": "服務類型/Service Type=SCADA".
# IN[2]: True  = write and synchronize each file
#        False = dry run: each file is opened detached (nothing is saved, central is not touched)
#
# Rules (never destructive):
#   - a missing workset is created (new worksets are visible by default)
#   - elements already in the target workset are left alone
#   - elements owned by another user, or whose workset cannot be changed, are counted, not changed
#   - a target workset that another user has checked out is skipped and reported
#   - non-workshared files are skipped (this script never turns worksharing on)
import clr, os, re, uuid, shutil

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System import Int32
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

src_in = IN[0]
RULE_TEXTS = [str(r).strip() for r in IN[1] if str(r).strip()] if len(IN) > 1 and IN[1] else []
RUN = bool(IN[2]) if len(IN) > 2 else False

# Used when IN[1] is empty. Edit the workset names to match your project standard.
DEFAULT_RULES = [
    "OST_Conduit | 服務類型/Service Type=SCADA -> SCADA_管線",
    "OST_ConduitFitting | 服務類型/Service Type=SCADA -> SCADA_管線",
    "OST_CableTray | 服務類型/Service Type=SCADA -> SCADA_管線",
    "OST_CableTrayFitting | 服務類型/Service Type=SCADA -> SCADA_管線",
    "OST_ElectricalEquipment | 備註/Comments=SCADA -> SCADA_設備",
    "OST_ElectricalFixtures | 備註/Comments=SCADA -> SCADA_設備",
    "OST_Wire | 備註/Comments=SCADA -> SCADA_設備",
]
# Safety: only files whose name contains this text are processed ("" = no check).
FILE_NAME_MUST_CONTAIN = "-ESC-"


# ---- pure helpers (no Revit API) ----
def parse_rule(text):
    """-> (category name, (parameter names, value) or None, workset name)."""
    if "->" not in text:
        raise ValueError('missing "->" in rule: ' + text)
    left, ws = text.rsplit("->", 1)
    ws = ws.strip()
    flt = None
    if "|" in left:
        left, cond = left.split("|", 1)
        if "=" not in cond:
            raise ValueError('condition needs "parameter=value": ' + text)
        pname, pval = cond.split("=", 1)
        names = tuple(n.strip() for n in pname.split("/") if n.strip())
        if not names:
            raise ValueError("empty parameter name: " + text)
        flt = (names, pval.strip())
    cat = left.strip()
    if not cat or not ws:
        raise ValueError("empty category or workset name: " + text)
    return cat, flt, ws
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


NS = "BatchWorkset_" + uuid.uuid4().hex  # unique namespace so re-runs don't clash
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
    is silently missed. A dry run is opened detached: no local file, central never touched."""
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
                                     'BatchWorkset_%s_%s' % (uuid.uuid4().hex[:8], os.path.basename(path)))
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
    swc = SynchronizeWithCentralOptions()
    swc.SetRelinquishOptions(RelinquishOptions(True))
    swc.Comment = "Batch assign worksets"
    tdoc.SynchronizeWithCentral(TransactWithCentralOptions(), swc)


def id_int(i):
    try:
        return int(i.Value)
    except AttributeError:
        return int(i.IntegerValue)


def eid(el):
    return id_int(el.Id)


def text_param(el, names):
    for n in names:
        p = el.LookupParameter(n)
        if p is not None:
            if p.StorageType == StorageType.String:
                return (p.AsString() or "").strip()
            return (p.AsValueString() or "").strip()
    return ""


def ensure_editable(tdoc, ws):
    """True when the workset is editable by the current user (tries to check it out)."""
    if ws.IsEditable:
        return True
    try:
        WorksharingUtils.CheckoutWorksets(tdoc, List[WorksetId]([ws.Id]))
    except Exception:
        pass
    return tdoc.GetWorksetTable().GetWorkset(ws.Id).IsEditable


def process(tdoc, write):
    """Returns (report lines, number of elements moved)."""
    if not tdoc.IsWorkshared:
        return ["    [SKIP not workshared]"], 0
    existing = dict((w.Name, w) for w in FilteredWorksetCollector(tdoc).OfKind(WorksetKind.UserWorkset))
    lines = ["    現有工作集: " + (", ".join(sorted(existing)) or "(none)")]

    plan = {}  # workset name -> [elements that must move]
    for cat_name, flt, ws_name in RULES:
        bic = getattr(BuiltInCategory, cat_name, None) or getattr(BuiltInCategory, "OST_" + cat_name, None)
        if bic is None:
            lines.append("    [UNKNOWN category] " + cat_name)
            continue
        target = existing.get(ws_name)
        target_id = target.Id.IntegerValue if target is not None else None
        c = {"move": 0, "already": 0, "filtered": 0, "nows": 0}
        for el in FilteredElementCollector(tdoc).OfCategory(bic).WhereElementIsNotElementType():
            if flt is not None and text_param(el, flt[0]).upper() != flt[1].upper():
                c["filtered"] += 1
                continue
            if el.WorksetId.IntegerValue < 0:
                c["nows"] += 1
                continue
            if target_id is not None and el.WorksetId.IntegerValue == target_id:
                c["already"] += 1
                continue
            plan.setdefault(ws_name, []).append(el)
            c["move"] += 1
        cond = "" if flt is None else " | %s=%s" % ("/".join(flt[0]), flt[1])
        lines.append("    %s%s -> %s: %s %d, 已在目標工作集 %d, 不符條件 %d, 無工作集 %d"
                     % (cat_name, cond, ws_name, "移動" if write else "將移動", c["move"],
                        c["already"], c["filtered"], c["nows"]))
    if not plan:
        return lines, 0

    missing = [n for n in plan if n not in existing]
    if missing:
        lines.append("    %s工作集: %s" % ("建立" if write else "將建立", ", ".join(missing)))
    if not write:
        return lines, 0

    # Check out what we need before the transaction
    blocked = set()
    for name in plan:
        if name in existing and not ensure_editable(tdoc, existing[name]):
            blocked.add(name)
            lines.append("    [SKIP workset checked out by another user] %s (%s)" % (name, existing[name].Owner))
    owned = None
    try:
        ids = List[ElementId]([el.Id for n, els in plan.items() if n not in blocked for el in els])
        owned = set(id_int(i) for i in WorksharingUtils.CheckoutElements(tdoc, ids))
    except Exception:
        owned = None  # fall back: try every element and count the failures

    del fail_msgs[:]
    moved_total = 0
    t = Transaction(tdoc, "Batch assign worksets")
    t.Start()
    try:
        for name, els in plan.items():
            if name in blocked:
                continue
            ws = existing.get(name)
            if ws is None:
                try:
                    ws = Workset.Create(tdoc, name)
                except Exception as ex:
                    lines.append("    [ERROR create workset] %s: %s" % (name, ex))
                    continue
                existing[name] = ws
            moved = locked = other = 0
            for el in els:
                if owned is not None and eid(el) not in owned:
                    other += 1
                    continue
                p = el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
                if p is None or p.IsReadOnly:
                    locked += 1
                    continue
                try:
                    p.Set.Overloads[Int32](ws.Id.IntegerValue)
                    moved += 1
                except Exception:
                    locked += 1
            moved_total += moved
            lines.append("    → %s: 已移動 %d, 他人持有 %d, 無法變更(群組/唯讀) %d" % (name, moved, other, locked))
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
    return lines, moved_total


report = []
RULES = []
try:
    RULES = [parse_rule(t) for t in (RULE_TEXTS or DEFAULT_RULES)]
except ValueError as ex:
    report.append("[ERROR rule] %s" % ex)

if RULES:
    report.append("Mode: %s | %d rules%s" % ("WRITE" if RUN else "DRY RUN (nothing is saved)", len(RULES),
                                             "" if RULE_TEXTS else " (DEFAULT_RULES)"))
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
        if not info.IsWorkshared:
            report.append("[SKIP not workshared] " + p)
            continue
        tdoc, local = None, None
        try:
            tdoc, local = open_target(p, info, RUN)
            lines, moved = process(tdoc, RUN)
            if RUN and moved > 0:
                save(tdoc)
            tag = "[DRY RUN]" if not RUN else ("[OK]" if moved > 0 else "[OK nothing to change]")
            report.append("%s %s" % (tag, p))
            report += lines
        except Exception as ex:
            report.append("[ERROR] %s: %s" % (p, ex))
        finally:
            if tdoc is not None:
                tdoc.Close(False)
            remove_temp_local(local)

# The Watch node truncates long lines, so keep the full report in a text file as well
try:
    with open(os.path.join(os.environ.get('TEMP'), 'BatchWorksets_last_report.txt'), 'w', encoding='utf-8') as fh:
        fh.write("\n".join(report))
except Exception:
    pass

OUT = report
