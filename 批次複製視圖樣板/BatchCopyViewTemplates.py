# Batch copy view templates (and the filters they use) from the CURRENT document
# to every .rvt file in a folder.
# IN[0]: folder path (string) or list of .rvt paths
# IN[1]: view template names to copy; empty list = all templates in this file
# IN[2]: True = run; False = dry run (no file is opened or changed)
import clr, os, re, uuid, shutil

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

src_in = IN[0]
names = IN[1] if len(IN) > 1 and IN[1] else []
RUN = bool(IN[2]) if len(IN) > 2 else False
if isinstance(names, str):
    names = [names]
names = [str(n) for n in names]


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


NS = "BatchVT_" + uuid.uuid4().hex  # unique namespace so re-runs don't clash
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
    """Return (document, temp local path or None)."""
    mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
    opts = OpenOptions()
    local = None
    if info.IsWorkshared:
        opts.DetachFromCentralOption = DetachFromCentralOption.DoNotDetach
        opts.SetOpenWorksetsConfiguration(
            WorksetConfiguration(WorksetConfigurationOption.CloseAllWorksets))
        if info.IsCentral:
            local = os.path.join(os.environ.get('TEMP'),
                                 'BatchVT_%s_%s' % (uuid.uuid4().hex[:8], os.path.basename(path)))
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


def copy_templates(tdoc, templates):
    log = []
    existing = dict((v.Name, v) for v in FilteredElementCollector(tdoc).OfClass(View) if v.IsTemplate)
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
                log.append("    added: " + src.Name)
            else:
                for v in views:
                    if v.ViewTemplateId == old.Id:
                        v.ViewTemplateId = new_v.Id
                for f in vfts:
                    if f.DefaultTemplateId == old.Id:
                        f.DefaultTemplateId = new_v.Id
                tdoc.Delete(old.Id)
                log.append("    overwritten: " + src.Name)
            if new_v.Name != src.Name:
                new_v.Name = src.Name

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
    return log


def save(tdoc):
    if tdoc.IsWorkshared:
        swc = SynchronizeWithCentralOptions()
        swc.SetRelinquishOptions(RelinquishOptions(True))
        swc.Comment = "Batch copy view templates"
        tdoc.SynchronizeWithCentral(TransactWithCentralOptions(), swc)
    else:
        tdoc.Save()


templates = [v for v in FilteredElementCollector(doc).OfClass(View)
             if v.IsTemplate and (not names or v.Name in names)]
report = ["Source templates (%d): %s" % (len(templates), ", ".join(v.Name for v in templates))]
found = [v.Name for v in templates]
report += ["[NOT FOUND in source] " + n for n in names if n not in found]

# The source file itself (and its central model) is never a target
src_paths = doc_paths(doc)
# Documents already open in this Revit session (including loaded links) cannot be opened again
open_paths = set()
for d in app.Documents:
    open_paths |= doc_paths(d)
open_paths -= src_paths

targets = [p for p in to_list(src_in) if norm(p) not in src_paths]
if not targets:
    report.append("[NO TARGET FILES] check IN[0] folder path")

if templates:
    if RUN:
        # Close Dynamo's own transaction before opening other documents
        TransactionManager.Instance.ForceCloseTransaction()
    for p in targets:
        if norm(p) in open_paths:
            report.append("[SKIP already open or loaded as link - unload it first] " + p)
            continue
        try:
            info = BasicFileInfo.Extract(p)
        except Exception as ex:
            report.append("[ERROR read] %s: %s" % (p, ex))
            continue
        if not version_ok(info):
            report.append("[SKIP version mismatch] " + p)
            continue
        if not RUN:
            report.append("[DRY RUN] %s (workshared=%s)" % (p, info.IsWorkshared))
            continue
        tdoc, local = None, None
        try:
            tdoc, local = open_target(p, info)
            log = copy_templates(tdoc, templates)
            save(tdoc)
            report.append("[OK] " + p)
            report += log
        except Exception as ex:
            report.append("[ERROR] %s: %s" % (p, ex))
        finally:
            if tdoc is not None:
                tdoc.Close(False)
            remove_temp_local(local)

OUT = report
