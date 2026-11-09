# Dialog compatibility test for Dynamo 3.3 (CPython3). TEST ONLY.
# Reads no Revit element, writes no file, creates no folder. It opens two standard dialogs
# (file, then folder) and reports what happened. Generated into a .dyn by make_dialog_test_dyn.py.
#
# IN[0]  mode: blank or 'no-owner' = no owner window; 'owner' = the Revit main window as owner.
#        The owner is applied ONLY on the DIRECT route (dialog shown on Dynamo's own thread).
#        The FALLBACK route (new STA thread) never uses an owner window.
# OUT    lines for the Watch node.
import clr
import ctypes
import os
import sys

clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
import System
from System import Environment
from System.Diagnostics import Process
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import DialogResult, FolderBrowserDialog, NativeWindow, OpenFileDialog

TITLE = u"測試：此測試不會讀取或修改任何檔案"
OUT = []


def say(text):
    OUT.append(text)


def _text(value):
    return "" if value is None else str(value).strip()


def _safe(label, fn):
    try:
        return fn()
    except Exception as ex:
        say("%s: EXCEPTION %s: %s" % (label, type(ex).__name__, str(ex)[:300]))
        return None


MODE = _text(IN[0]).lower() if len(IN) > 0 else ""
if MODE not in ("", "no-owner", "owner"):
    raise Exception("mode must be blank, no-owner or owner (got %r)" % MODE)
OWNER_MODE = MODE == "owner"

# ---- 1. environment facts (measured in this run) --------------------------------------------
say("== environment ==")
say("RuntimeInformation.FrameworkDescription: " + str(_safe(
    "FrameworkDescription", lambda: System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription)))
say("Environment.Version: " + str(_safe("Environment.Version", lambda: Environment.Version)))
say("Environment.Is64BitProcess: " + str(_safe("Is64BitProcess", lambda: Environment.Is64BitProcess)))
say("sys.version: " + str(sys.version).replace("\n", " "))


def _forms_probe():
    dlg = OpenFileDialog()
    try:
        return dlg.GetType().Assembly.Location + " | version " + str(dlg.GetType().Assembly.GetName().Version)
    finally:
        dlg.Dispose()


say("System.Windows.Forms assembly: " + str(_safe("Forms assembly", _forms_probe)))
PROCESS = _safe("Process", lambda: Process.GetCurrentProcess())
if PROCESS is not None:
    say("Process name / PID: " + str(_safe("ProcessName", lambda: PROCESS.ProcessName)) + " / " +
        str(_safe("Id", lambda: PROCESS.Id)))
MAIN_HANDLE = _safe("MainWindowHandle", lambda: PROCESS.MainWindowHandle) if PROCESS is not None else None

# ---- 2. thread facts ------------------------------------------------------------------------
say("== thread ==")
say("apartment state (this thread): " + str(_safe("GetApartmentState", lambda: Thread.CurrentThread.GetApartmentState())))
say("ManagedThreadId: " + str(_safe("ManagedThreadId", lambda: Thread.CurrentThread.ManagedThreadId)))
say("IsBackground: " + str(_safe("IsBackground", lambda: Thread.CurrentThread.IsBackground)))
say("IsThreadPoolThread: " + str(_safe("IsThreadPoolThread", lambda: Thread.CurrentThread.IsThreadPoolThread)))


def _foreground():
    return ctypes.windll.user32.GetForegroundWindow()


try:
    FG_BEFORE = _foreground()
    say("foreground window before dialog 1: " + str(FG_BEFORE) + " | MainWindowHandle: " + str(MAIN_HANDLE))
except Exception as ex:
    FG_BEFORE = None
    say("foreground window: not recorded (ctypes unavailable: %s)" % type(ex).__name__)


# ---- helpers ----------------------------------------------------------------------------
def _make(kind):
    if kind == "file":
        dlg = OpenFileDialog()
        dlg.Title = TITLE
        dlg.Filter = u"Revit 檔案 (*.rvt)|*.rvt"
        dlg.Multiselect = False
        dlg.CheckFileExists = True
        dlg.CheckPathExists = True
        dlg.RestoreDirectory = True
        return dlg
    dlg = FolderBrowserDialog()
    dlg.Description = TITLE
    dlg.UseDescriptionForTitle = True
    dlg.ShowNewFolderButton = False
    return dlg


def _path(dlg, kind):
    return dlg.FileName if kind == "file" else dlg.SelectedPath


def _attempt(kind, owner, box=None):
    """Returns (status, path, exception, returned). status: OK, CANCEL or EXC."""
    try:
        dlg = _make(kind)
        try:
            result = dlg.ShowDialog(owner) if owner is not None else dlg.ShowDialog()
            returned = str(result)
            if box is not None:
                box["apt"] = str(Thread.CurrentThread.GetApartmentState())
            if result == DialogResult.OK:
                return "OK", _path(dlg, kind), None, returned
            return "CANCEL", None, None, returned
        finally:
            dlg.Dispose()
    except Exception as ex:
        if box is not None:
            box["apt"] = str(Thread.CurrentThread.GetApartmentState())
        return "EXC", None, ex, "EXCEPTION"


def _is_sta_error(ex):
    return "ThreadStateException" in type(ex).__name__ or "ThreadStateException" in str(ex)


def _run_sta(kind):
    """FALLBACK route: a new STA thread. Never receives an owner window (cross-thread owner is not used)."""
    box = {}

    def work():
        box["r"] = _attempt(kind, None, box)

    worker = Thread(ThreadStart(work))
    worker.SetApartmentState(ApartmentState.STA)
    worker.Start()
    worker.Join()
    return box.get("r", ("EXC", None, Exception("STA worker returned no result"), "NONE")), box.get("apt")


def _dialog(kind, owner, label):
    """Runs one dialog. Returns (status, path, route, owner_applied). Writes its lines."""
    status, path, ex, returned = _attempt(kind, owner)
    route = "DIRECT"
    applied = owner is not None
    if status == "EXC" and _is_sta_error(ex):
        say("%s: EXCEPTION %s: %s (not STA) -> FALLBACK route, new STA thread, NO owner window" % (
            label, type(ex).__name__, str(ex)[:300]))
        route = "FALLBACK"
        applied = False
        (status, path, ex, returned), apt = _run_sta(kind)
        say("%s: FALLBACK thread apartment state = %s" % (label, apt))
    if status == "EXC":
        say("%s: EXCEPTION %s: %s" % (label, type(ex).__name__, str(ex)[:300]))
    say("%s: route=%s | owner applied=%s | ShowDialog returned=%s | status=%s" % (
        label, route, "yes" if applied else "no", returned, status))
    return status, path, route, applied


def _make_owner():
    if not OWNER_MODE:
        return None
    try:
        window = NativeWindow()
        window.AssignHandle(MAIN_HANDLE)
        say("owner window: NativeWindow assigned to MainWindowHandle (used on DIRECT route only)")
        return window
    except Exception as ex:
        say("owner window: EXCEPTION %s: %s -> continuing with NO owner" % (type(ex).__name__, str(ex)[:300]))
        return None


def _release(window):
    if window is None:
        return
    try:
        window.ReleaseHandle()
        say("owner window: released")
    except Exception as ex:
        say("owner release: EXCEPTION %s: %s" % (type(ex).__name__, str(ex)[:300]))


# ---- 3-7. dialogs and outcome ---------------------------------------------------------------
say("== dialogs (mode: %s) ==" % (MODE or "no-owner"))
OWNER = _make_owner()
try:
    status, path, route, applied = _dialog("file", OWNER, "dialog 1 (file)")
    FG_AFTER_1 = _safe("foreground after dialog 1", _foreground)
    say("foreground window after dialog 1: " + str(FG_AFTER_1) + " | same as before: " + str(FG_AFTER_1 == FG_BEFORE))
    if status == "CANCEL":
        say("CANCELLED: file dialog")
    elif status == "OK":
        ext = os.path.splitext(path)[1].lower()
        if ext != ".rvt":
            say("INVALID FILE: extension %r is not .rvt (path shown only; nothing read)" % ext)
        elif not os.path.isfile(path):
            say("INVALID FILE: not an existing file")
        else:
            say("file selected: " + path + " (extension ok, isfile True)")
            status2, path2, route2, applied2 = _dialog("folder", OWNER, "dialog 2 (folder)")
            if status2 == "CANCEL":
                say("CANCELLED: folder dialog")
            elif status2 == "OK":
                if not os.path.isdir(path2):
                    say("INVALID FOLDER: not an existing folder")
                else:
                    say("folder selected: " + path2 + " (isdir True)")
finally:
    _release(OWNER)

say("node reached the last line of the script: yes")
say("NO FILES WRITTEN; NO REVIT OBJECTS TOUCHED")
