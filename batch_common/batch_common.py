# Shared helpers for the batch Dynamo scripts (批次*/Batch*.py).
#
# This is NOT an importable module. Dynamo .dyn files embed their whole script,
# so the block below is copied into each script between the markers
#     # >>> shared: batch_common ...
#     # <<< shared: batch_common
# by `python batch_common/sync_shared.py`, which also refreshes the code
# embedded in the matching .dyn. Edit the block here, never in the scripts.
#
# The host script must define, before the marker block:
#   imports: os, re, shutil, `from Autodesk.Revit.DB import *`
#   app        Revit Application (doc.Application)
#   NS         unique .NET namespace string (re-runs in one session must not clash)
#   fail_msgs  list that collects error texts from SuppressWarnings
#
# Per-script helpers (open_target, save, UseDestinationTypes) differ in
# behaviour and stay in each script.
# --- block ---
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


def remove_temp_local(local):
    if not local:
        return
    try:
        if os.path.exists(local):
            os.remove(local)
        shutil.rmtree(os.path.splitext(local)[0] + '_backup', ignore_errors=True)
    except Exception:
        pass
