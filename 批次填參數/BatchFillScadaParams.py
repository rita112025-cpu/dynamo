# Batch fill the SCADA identification parameters in every .rvt file of a folder.
#   Conduit / cable tray (and fittings): Service Type (服務類型)
#   Electrical equipment / fixtures / wires: Comments (備註)
# so that the "SCADA" and "SCADA_電氣設備" view filters pick them up.
#
# IN[0]: folder path (string) or list of .rvt paths
# IN[1]: text to write (default "SCADA")
# IN[2]: True  = write the values and save / synchronize each file
#        False = dry run: each file is opened, counted and closed WITHOUT saving
#
# Rules (never destructive):
#   - empty value                      -> set to the text
#   - same text but other case/spaces  -> corrected to the text (filters use "equals")
#   - already the text                 -> left alone
#   - any other non-empty value        -> KEPT, counted and listed in the report
#   - missing / read-only parameter    -> counted, not changed
#
# To cover more categories (for example communication devices), add a line to RULES.
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
VALUE = str(IN[1]).strip() if len(IN) > 1 and IN[1] else "SCADA"
RUN = bool(IN[2]) if len(IN) > 2 else False

# (parameter label, BuiltInParameter name, display-name fallbacks)
SERVICE_TYPE = ("服務類型", "RBS_CTC_SERVICE_TYPE", ("服務類型", "Service Type"))
COMMENTS = ("備註", "ALL_MODEL_INSTANCE_COMMENTS", ("備註", "Comments"))

# (report label, BuiltInCategory name, parameter)
RULES = [
    ("電管 Conduit", "OST_Conduit", SERVICE_TYPE),
    ("電管配件 Conduit Fitting", "OST_ConduitFitting", SERVICE_TYPE),
    ("電纜架 Cable Tray", "OST_CableTray", SERVICE_TYPE),
    ("電纜架配件 Cable Tray Fitting", "OST_CableTrayFitting", SERVICE_TYPE),
    ("電氣設備 Electrical Equipment", "OST_ElectricalEquipment", COMMENTS),
    ("電氣裝置 Electrical Fixtures", "OST_ElectricalFixtures", COMMENTS),
    ("電線 Wire", "OST_Wire", COMMENTS),
]


# Safety: only files whose name contains this text are processed ("" = no check).
# A folder may hold other disciplines' models; stamping their elements SCADA would be wrong.
FILE_NAME_MUST_CONTAIN = "-ESC-"


def decide(current, value):
    """What to do with a text parameter whose current value is `current`."""
    cur = (current or "").strip()
    if cur == "":
        return "set"
    if current == value:
        return "same"
    if cur.upper() == value.upper():
        return "fix"
    return "keep"


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


NS = "BatchFill_" + uuid.uuid4().hex  # unique namespace so re-runs don't clash
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


def open_target(path, info):
    """Return (document, temp local path or None). All worksets are opened so that
    no element is silently missed."""
    mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
    opts = OpenOptions()
    local = None
    if info.IsWorkshared:
        opts.DetachFromCentralOption = DetachFromCentralOption.DoNotDetach
        opts.SetOpenWorksetsConfiguration(
            WorksetConfiguration(WorksetConfigurationOption.OpenAllWorksets))
        if info.IsCentral:
            local = os.path.join(os.environ.get('TEMP'),
                                 'BatchFill_%s_%s' % (uuid.uuid4().hex[:8], os.path.basename(path)))
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


def get_param(el, bip_name, names):
    bip = getattr(BuiltInParameter, bip_name, None)
    p = el.get_Parameter(bip) if bip is not None else None
    if p is None:
        for n in names:
            p = el.LookupParameter(n)
            if p is not None:
                break
    return p


def fill_category(tdoc, label, cat_name, prm, write):
    """Fill (or just count) one category. Returns (report line, changed count)."""
    counts = {"set": 0, "fix": 0, "same": 0, "keep": 0, "noparam": 0, "failed": 0}
    kept = []
    bic = getattr(BuiltInCategory, cat_name, None)
    if bic is None:
        return "    %s: category not found in this Revit version" % label, 0
    for el in FilteredElementCollector(tdoc).OfCategory(bic).WhereElementIsNotElementType():
        p = get_param(el, prm[1], prm[2])
        if p is None or p.IsReadOnly or p.StorageType != StorageType.String:
            counts["noparam"] += 1
            continue
        current = p.AsString()
        action = decide(current, VALUE)
        if action == "keep":
            counts["keep"] += 1
            if len(kept) < 3 and current not in kept:
                kept.append(current)
            continue
        if action == "same":
            counts["same"] += 1
            continue
        if write:
            try:
                p.Set.Overloads[String](VALUE)
            except Exception:
                counts["failed"] += 1  # for example owned by another user
                continue
        counts[action] += 1
    verb = "已填" if write else "將填"
    line = ("    %s [%s]: %s %d, 修正大小寫/空格 %d, 原本就是 %s %d, 保留他值 %d, 無此參數或唯讀 %d, 失敗 %d"
            % (label, prm[0], verb, counts["set"], counts["fix"], VALUE, counts["same"],
               counts["keep"], counts["noparam"], counts["failed"]))
    if kept:
        line += "\n      保留的他值範例: " + " | ".join(kept)
    return line, counts["set"] + counts["fix"]


def process(tdoc, write):
    lines = []
    changed = 0
    t = None
    if write:
        del fail_msgs[:]
        t = Transaction(tdoc, "Batch fill SCADA parameters")
        t.Start()
    try:
        for label, cat_name, prm in RULES:
            line, n = fill_category(tdoc, label, cat_name, prm, write)
            lines.append(line)
            changed += n
        if write:
            fho = t.GetFailureHandlingOptions()
            fho.SetFailuresPreprocessor(SuppressWarnings())
            fho.SetClearAfterRollback(True)
            status = t.Commit(fho)
            if status != TransactionStatus.Committed:
                raise Exception("rolled back: " + "; ".join(fail_msgs))
    except Exception:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return lines, changed


def save(tdoc):
    if tdoc.IsWorkshared:
        swc = SynchronizeWithCentralOptions()
        swc.SetRelinquishOptions(RelinquishOptions(True))
        swc.Comment = "Batch fill SCADA parameters"
        tdoc.SynchronizeWithCentral(TransactWithCentralOptions(), swc)
    else:
        tdoc.Save()


report = ["Mode: %s | value: %s" % ("WRITE" if RUN else "DRY RUN (nothing is saved)", VALUE)]

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
        tdoc, local = open_target(p, info)
        lines, changed = process(tdoc, RUN)
        if RUN and changed > 0:
            save(tdoc)
        tag = "[OK]" if RUN else "[DRY RUN]"
        if RUN and changed == 0:
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
    with open(os.path.join(os.environ.get('TEMP'), 'BatchFill_last_report.txt'), 'w', encoding='utf-8') as fh:
        fh.write("\n".join(report))
except Exception:
    pass

OUT = report
