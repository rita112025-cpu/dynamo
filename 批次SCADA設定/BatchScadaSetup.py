# One-pass SCADA setup for every .rvt file of a folder:
#   1. copy view templates (and the filters they use) from the CURRENT document
#   2. fill the SCADA identification parameters
#        Conduit / cable tray (and fittings): Service Type (服務類型)
#        Electrical equipment / fixtures / wires: Comments (備註)
# Each target file is opened once, changed, and saved / synchronized once.
# (Merged from BatchCopyViewTemplates.py and BatchFillScadaParams.py.)
#
# IN[0]: folder path (string) or list of .rvt paths
# IN[1]: view template names to copy from the current document (default ["SCADA"])
# IN[2]: text to write into the parameters (default "SCADA")
# IN[3]: True  = write and save / synchronize each file
#        False = dry run: each file is opened, planned changes are listed, NOTHING is saved
#
# The current document is the template source and is never a target.
#
# Template rules:
#   - missing template      -> added
#   - same name exists      -> replaced by the copy (views and view types that used the old one
#                              are switched to the new one)
#   - filters with an existing name keep the DESTINATION version
#   - templates are not applied to views; apply "SCADA" to the 3D view yourself
#
# Parameter rules (never destructive):
#   - empty value                      -> set to the text
#   - same text but other case/spaces  -> corrected to the text (filters use "equals")
#   - already the text                 -> left alone
#   - any other non-empty value        -> KEPT, counted and listed in the report
#   - missing / read-only parameter    -> counted, not changed
#
# If a file fails in either step nothing is saved for that file.
# To cover more categories (for example communication devices), add a line to RULES.
import clr, os, re, uuid, shutil

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System import String
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

src_in = IN[0]
names = IN[1] if len(IN) > 1 and IN[1] else ["SCADA"]
if isinstance(names, str):
    names = [names]
names = [str(n) for n in names]
VALUE = str(IN[2]).strip() if len(IN) > 2 and IN[2] else "SCADA"
RUN = bool(IN[3]) if len(IN) > 3 else False

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


# ---- pure helpers (no Revit API) ----
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


# ---- Revit helpers ----
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


NS = "BatchScada_" + uuid.uuid4().hex  # unique namespace so re-runs don't clash
fail_msgs = []


class UseDestinationTypes(IDuplicateTypeNamesHandler):
    __namespace__ = NS

    def OnDuplicateTypeNamesFound(self, args):
        return DuplicateTypeAction.UseDestinationTypes


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
                                 'BatchScada_%s_%s' % (uuid.uuid4().hex[:8], os.path.basename(path)))
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


def commit_with_handling(t):
    fho = t.GetFailureHandlingOptions()
    fho.SetFailuresPreprocessor(SuppressWarnings())
    fho.SetClearAfterRollback(True)
    status = t.Commit(fho)
    if status != TransactionStatus.Committed:
        raise Exception("rolled back: " + "; ".join(fail_msgs))


# ---- step 1: view templates ----
def copy_templates(tdoc, templates, write):
    """Copy (or only plan) the templates. Returns report lines."""
    log = []
    existing = dict((v.Name, v) for v in FilteredElementCollector(tdoc).OfClass(View) if v.IsTemplate)
    if not write:
        for src in templates:
            log.append("    template %s: %s" % (
                "將取代" if src.Name in existing else "將新增", src.Name))
        return log

    views = [v for v in FilteredElementCollector(tdoc).OfClass(View) if not v.IsTemplate]
    vfts = list(FilteredElementCollector(tdoc).OfClass(ViewFamilyType))
    opts = CopyPasteOptions()
    opts.SetDuplicateTypeNamesHandler(UseDestinationTypes())
    del fail_msgs[:]

    t = Transaction(tdoc, "Batch copy view templates")
    t.Start()
    try:
        for src in templates:
            old = existing.get(src.Name)
            if old is not None:
                # Rename the old template first so the copy never clashes with it
                old.Name = "%s_old_%s" % (src.Name, uuid.uuid4().hex[:8])

            new_ids = ElementTransformUtils.CopyElements(
                doc, List[ElementId]([src.Id]), tdoc, Transform.Identity, opts)
            new_v = None
            for i in new_ids:
                e = tdoc.GetElement(i)
                if isinstance(e, View) and e.IsTemplate:
                    new_v = e
                    break
            if new_v is None or (old is not None and new_v.Id == old.Id):
                raise Exception("copy failed: " + src.Name)

            if old is None:
                log.append("    template added: " + src.Name)
            else:
                for v in views:
                    if v.ViewTemplateId == old.Id:
                        v.ViewTemplateId = new_v.Id
                for f in vfts:
                    if f.DefaultTemplateId == old.Id:
                        f.DefaultTemplateId = new_v.Id
                tdoc.Delete(old.Id)
                log.append("    template replaced: " + src.Name)
            if new_v.Name != src.Name:
                new_v.Name = src.Name

        commit_with_handling(t)
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return log


# ---- step 2: parameters ----
def get_param(el, bip_name, pnames):
    bip = getattr(BuiltInParameter, bip_name, None)
    p = el.get_Parameter(bip) if bip is not None else None
    if p is None:
        for n in pnames:
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


def fill_params(tdoc, write):
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
            commit_with_handling(t)
    except Exception:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return lines, changed


def save(tdoc):
    if tdoc.IsWorkshared:
        swc = SynchronizeWithCentralOptions()
        swc.SetRelinquishOptions(RelinquishOptions(True))
        swc.Comment = "Batch SCADA setup (view templates + parameters)"
        tdoc.SynchronizeWithCentral(TransactWithCentralOptions(), swc)
    else:
        tdoc.Save()


# ---- main ----
templates = [v for v in FilteredElementCollector(doc).OfClass(View)
             if v.IsTemplate and v.Name in names]
found = [v.Name for v in templates]
report = ["Mode: %s | value: %s" % ("WRITE" if RUN else "DRY RUN (nothing is saved)", VALUE),
          "Source templates (%d): %s" % (len(templates), ", ".join(found))]
report += ["[NOT FOUND in source] " + n for n in names if n not in found]

# The current document is the source and never a target; documents already open or loaded
# as links cannot be reopened
src_paths = doc_paths(doc)
open_paths = set()
for d in app.Documents:
    open_paths |= doc_paths(d)
open_paths -= src_paths

targets = [p for p in to_list(src_in) if norm(p) not in src_paths]
if not targets:
    report.append("[NO TARGET FILES] check IN[0] folder path")

if not templates:
    report.append("[STOP] no source template found in the current document - open the file that has it")
else:
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
            tpl_lines = copy_templates(tdoc, templates, RUN)
            param_lines, _ = fill_params(tdoc, RUN)
            if RUN:
                save(tdoc)
            report.append("%s %s (workshared=%s)" % ("[OK]" if RUN else "[DRY RUN]", p, info.IsWorkshared))
            report += tpl_lines
            report += param_lines
        except Exception as ex:
            report.append("[ERROR - nothing saved for this file] %s: %s" % (p, ex))
        finally:
            if tdoc is not None:
                tdoc.Close(False)
            remove_temp_local(local)

OUT = report
