"""Target-folder locks (r2-final section 4 of r2, unchanged in r2-final).

* A lock is created with O_CREAT | O_EXCL; an existing lock is never deleted,
  overwritten or edited automatically.
* An existing lock is classified as `lock_conflict` (unreadable, other host,
  process still present) or `lock_stale_suspected` (same host, process gone).
  Both stop the task; a stale lock needs a person to call release_stale_lock.
* A released lock is moved (renamed), never deleted.
* Releasing first *claims* the lock by renaming it to a unique name, then checks
  the claimed copy. A lock written by someone else after the claim is a new file
  at the original path and is never touched. A claim that turns out not to be
  ours is put back with os.link, which fails instead of overwriting a new lock.
"""
import ntpath
import os
import secrets
import socket
from typing import Callable, Dict, Optional

from . import CONTROLLER_VERSION, atomic, workspace

LOCK_CONFLICT = "lock_conflict"
LOCK_STALE = "lock_stale_suspected"


class LockBusy(Exception):
    def __init__(self, kind: str, path: str, detail: str, info: Optional[Dict] = None):
        self.kind = kind
        self.path = path
        self.detail = detail
        self.info = info
        super().__init__("%s: %s (%s)" % (kind, detail, path))


class LockReleaseRefused(Exception):
    pass


def default_pid_alive(pid: int) -> bool:
    """True when a process with this PID exists. A live PID may belong to another
    program (PIDs are reused), so callers only use True to be conservative."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes  # Windows only; not exercised in the Linux test container
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return kernel32.GetLastError() == 5  # access denied: the process exists
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_key(target_root: str) -> str:
    normalised = ntpath.normcase(ntpath.normpath(os.path.abspath(target_root).replace("/", "\\")))
    return atomic.sha256_bytes(normalised.encode("utf-8"))


def lock_path(runs_root: str, target_root: str) -> str:
    return os.path.join(runs_root, "locks", "%s.lock" % lock_key(target_root))


class LockHandle(object):
    def __init__(self, path: str, run_id: str, run_dir: str):
        self.path = path
        self.run_id = run_id
        self.run_dir = run_dir


def acquire(runs_root: str, target_root: str, run_id: str, run_dir: str,
            pid: Optional[int] = None, host: Optional[str] = None,
            pid_alive: Callable[[int], bool] = default_pid_alive) -> LockHandle:
    path = lock_path(runs_root, target_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    info = {
        "lock_version": "1",
        "run_id": run_id,
        "pid": os.getpid() if pid is None else pid,
        "host": socket.gethostname() if host is None else host,
        "started_at": workspace.now_iso(),
        "run_dir": os.path.abspath(run_dir),
        "target_root": os.path.abspath(target_root),
        "controller_version": CONTROLLER_VERSION,
    }
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        kind, detail, existing = assess(path, host=info["host"], pid_alive=pid_alive)
        raise LockBusy(kind, path, detail, existing)
    try:
        os.write(fd, atomic.json_bytes(info))
        os.fsync(fd)
    finally:
        os.close(fd)
    return LockHandle(path, run_id, run_dir)


def _run_finished(run_dir: str) -> bool:
    try:
        state = atomic.read_json_strict(os.path.join(run_dir, "run_state.json"))
    except (OSError, ValueError):
        return False
    return bool(state.get("tasks")) and all(
        s in ("success", "failed", "skipped", "interrupted") for s in state["tasks"].values())


def assess(path: str, host: Optional[str] = None,
           pid_alive: Callable[[int], bool] = default_pid_alive):
    """Classify an existing lock. Reads only; returns (kind, detail, info or None)."""
    host = socket.gethostname() if host is None else host
    try:
        info = atomic.read_json_strict(path)
        if not isinstance(info, dict) or not info.get("run_id") or "pid" not in info:
            raise ValueError("missing run_id or pid")
    except (OSError, ValueError) as exc:
        return LOCK_CONFLICT, "lock file is unreadable (%s); confirm manually" % exc, None
    if info.get("host") != host:
        return LOCK_CONFLICT, "held by another computer (%s); confirm manually" % info.get("host"), info
    if pid_alive(int(info["pid"])):
        return LOCK_CONFLICT, "held by running process %s (run_id=%s)" % (info["pid"], info["run_id"]), info
    if _run_finished(info.get("run_dir", "")):
        detail = "process gone; previous run finished but did not release the lock; confirm manually"
    else:
        detail = "process gone and the run did not finish; confirm manually"
    return LOCK_STALE, "%s (run_id=%s)" % (detail, info["run_id"]), info


def _claim(path: str) -> str:
    claim = "%s.%s.claim" % (path, secrets.token_hex(4))
    os.rename(path, claim)  # atomic; after this no other process can change our copy
    return claim


def _restore(claim: str, path: str) -> bool:
    """Put a claimed lock back without overwriting a lock created meanwhile."""
    try:
        os.link(claim, path)
    except FileExistsError:
        return False  # a new lock exists; keep the claim file as evidence
    except (OSError, NotImplementedError, AttributeError):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        try:
            os.write(fd, read_lock_bytes(claim))
            os.fsync(fd)
        finally:
            os.close(fd)
    os.remove(claim)
    return True


def _refuse(claim: str, path: str, message: str):
    if _restore(claim, path):
        raise LockReleaseRefused(message + "; lock left in place")
    raise LockReleaseRefused(message + "; a new lock appeared meanwhile, claimed copy kept at %s" % claim)


def release_own(handle: LockHandle) -> None:
    """Move our lock to <run_dir>/lock.released only if it still carries our run_id."""
    try:
        claim = _claim(handle.path)
    except OSError as exc:
        raise LockReleaseRefused("cannot claim lock %s: %s" % (handle.path, exc))
    try:
        info = atomic.read_json_strict(claim)
    except (OSError, ValueError) as exc:
        _refuse(claim, handle.path, "cannot read lock %s: %s" % (handle.path, exc))
    if not isinstance(info, dict) or info.get("run_id") != handle.run_id:
        _refuse(claim, handle.path, "lock %s now belongs to run_id=%s"
                % (handle.path, info.get("run_id") if isinstance(info, dict) else None))
    os.replace(claim, os.path.join(handle.run_dir, "lock.released"))


def release_stale_lock(runs_root: str, path: str, expected_run_id: str, reason: str,
                       host: Optional[str] = None,
                       pid_alive: Callable[[int], bool] = default_pid_alive,
                       backfill: bool = True) -> str:
    """Manual release of a lock classified as stale. Returns the new location."""
    if not str(reason).strip():
        raise LockReleaseRefused("a reason is required")
    try:
        claim = _claim(path)
    except OSError as exc:
        raise LockReleaseRefused("cannot claim lock %s: %s" % (path, exc))
    kind, detail, info = assess(claim, host=host, pid_alive=pid_alive)
    if info is None or info.get("run_id") != expected_run_id:
        _refuse(claim, path, "lock run_id does not match expected_run_id")
    if kind != LOCK_STALE:
        _refuse(claim, path, "lock is not stale (%s)" % detail)
    released_dir = os.path.join(runs_root, "locks", "released")
    os.makedirs(released_dir, exist_ok=True)
    base = os.path.basename(path)[:-len(".lock")]
    dest = os.path.join(released_dir, "%s.%s.released.lock" % (base, expected_run_id))
    os.replace(claim, dest)
    record = {
        "released_at": workspace.now_iso(),
        "reason": reason,
        "released_by_host": socket.gethostname() if host is None else host,
        "released_by_pid": os.getpid(),
        "lock": info,
        "assessment": detail,
    }
    atomic.write_new_json(dest[:-len(".lock")] + ".release.json", record)
    if backfill and info.get("run_dir") and os.path.isdir(info["run_dir"]):
        from . import results  # local import: results does not depend on locks
        results.backfill_interrupted(info["run_dir"])
    return dest


def read_lock_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()

