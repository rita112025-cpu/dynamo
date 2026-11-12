"""Work root, run directories, run_id / run_nonce, backups and work copies.

Rules: r2-final sections 1.1 and 3. The official target folder is only read:
backups are copied from it, and work copies are copied from the backups.
"""
import datetime
import fnmatch
import ntpath
import os
import re
import secrets
import shutil
import stat
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from . import atomic

APP_FOLDER = "BIMBatchCommandCenter"
RUN_SUBDIRS = ("jobs", "backup", "work", "staging", "results", "evidence")
SYNC_ENV_VARS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
SYNC_SEGMENTS = ("onedrive", "dropbox", "google drive", "my drive", "iclouddrive", "box")
_RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
_DRIVE_TYPES = {0: "unknown", 1: "no_root_dir", 2: "removable", 3: "fixed", 4: "remote", 5: "cdrom", 6: "ramdisk"}


class ConfigError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__("%s: %s" % (code, message))


class BackupError(OSError):
    pass


class WorkCopyError(OSError):
    pass


# ---- time, run_id, nonce ----
def now_iso(now: Optional[datetime.datetime] = None) -> str:
    """ISO 8601 with a +HH:MM offset (never 'Z': Python 3.9 fromisoformat rejects it)."""
    value = (now or datetime.datetime.now()).astimezone().replace(microsecond=0)
    return value.isoformat()


def new_run_id(now: Optional[datetime.datetime] = None) -> str:
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return "%s-%s" % (stamp, secrets.token_hex(4))


def new_run_nonce() -> str:
    """128-bit nonce from the `secrets` module (r2-final S1)."""
    return secrets.token_hex(16)


def is_run_id(value: str) -> bool:
    return bool(_RUN_ID.match(value or ""))


# ---- work root (D5) ----
def windows_drive_type(path: str) -> Optional[str]:
    """Drive type through GetDriveTypeW on Windows; None elsewhere (not checked)."""
    if os.name != "nt":
        return None
    import ctypes  # Windows only
    root = ntpath.splitdrive(path)[0] + "\\"
    return _DRIVE_TYPES.get(ctypes.windll.kernel32.GetDriveTypeW(root), "unknown")


def _within(child: str, parent: str, flavor) -> bool:
    child_n = flavor.normcase(flavor.normpath(child))
    parent_n = flavor.normcase(flavor.normpath(parent))
    return child_n == parent_n or child_n.startswith(parent_n.rstrip(flavor.sep) + flavor.sep)


def check_runs_root(path: str, environ: Optional[Mapping[str, str]] = None,
                    drive_type: Optional[Callable[[str], Optional[str]]] = None,
                    target_roots: Iterable[str] = (), flavor: Optional[str] = None) -> str:
    """Raise ConfigError when `path` is not an acceptable local, non-synchronised work root.

    `flavor` is "nt" or "posix" (default: this platform). Tests pass "nt" so the
    Windows rules are checked in the Linux container.
    """
    environ = os.environ if environ is None else environ
    flavor = flavor or ("nt" if os.name == "nt" else "posix")
    mod = ntpath if flavor == "nt" else os.path
    drive_type = windows_drive_type if drive_type is None else drive_type
    text = str(path)
    if flavor == "nt":
        if text.replace("/", "\\").startswith("\\\\"):
            raise ConfigError("ROOT_UNC", "network (UNC) paths are not allowed: %s" % text)
        if not re.match(r"^[A-Za-z]:[\\/]", text):
            raise ConfigError("ROOT_NOT_ABSOLUTE", "use an absolute X:\\ path: %s" % text)
    else:
        if text.startswith("//"):
            raise ConfigError("ROOT_UNC", "network paths are not allowed: %s" % text)
        if not os.path.isabs(text):
            raise ConfigError("ROOT_NOT_ABSOLUTE", "use an absolute path: %s" % text)
    if drive_type(text) == "remote":
        raise ConfigError("ROOT_REMOTE_DRIVE", "network drives are not allowed: %s" % text)
    # Check the path as written and, when the rules match this platform, also the
    # real path after resolving symbolic links / junctions (os.path.realpath).
    native = (flavor == "nt") == (os.name == "nt")
    real = os.path.realpath(text) if native else None
    candidates = [text] + ([real] if real and real != text else [])
    targets = list(target_roots)
    real_targets = [os.path.realpath(t) for t in targets] if native else []
    for candidate in candidates:
        for var in SYNC_ENV_VARS:
            sync_root = environ.get(var)
            if not sync_root:
                continue
            roots = [sync_root] + ([os.path.realpath(sync_root)] if native else [])
            if any(_within(candidate, r, mod) for r in roots):
                raise ConfigError("ROOT_SYNC_FOLDER", "inside %%%s%% (%s)" % (var, sync_root))
        for part in re.split(r"[\\/]+", candidate):
            lower = part.lower()
            if lower in SYNC_SEGMENTS or lower.startswith("onedrive - "):
                raise ConfigError("ROOT_SYNC_FOLDER", "path segment '%s' looks like a sync folder" % part)
        for target in targets + real_targets:
            if _within(candidate, target, mod) or _within(target, candidate, mod):
                raise ConfigError("ROOT_INSIDE_TARGET", "work root and target folder overlap: %s" % target)
    return text


def resolve_runs_root(custom: Optional[str] = None, environ: Optional[Mapping[str, str]] = None,
                      drive_type: Optional[Callable[[str], Optional[str]]] = None,
                      target_roots: Iterable[str] = (), flavor: Optional[str] = None) -> str:
    environ = os.environ if environ is None else environ
    flavor = flavor or ("nt" if os.name == "nt" else "posix")
    if custom is None:
        base = environ.get("LOCALAPPDATA")
        if not base:
            raise ConfigError("LOCALAPPDATA_MISSING",
                              "LOCALAPPDATA is not set; pass a local work root explicitly")
        custom = (ntpath if flavor == "nt" else os.path).join(base, APP_FOLDER)
    return check_runs_root(custom, environ, drive_type, target_roots, flavor)


# ---- run directory ----
def create_run_dir(runs_root: str, mkdir: Callable[[str], None] = os.mkdir,
                   now: Optional[datetime.datetime] = None, attempts: int = 20) -> Dict[str, str]:
    """Create <runs_root>/runs/<run_id> exclusively; an existing folder is never reused."""
    runs = os.path.join(runs_root, "runs")
    os.makedirs(runs, exist_ok=True)
    for _ in range(attempts):
        run_id = new_run_id(now)
        run_dir = os.path.join(runs, run_id)
        try:
            mkdir(run_dir)
        except FileExistsError:
            continue
        for sub in RUN_SUBDIRS:
            os.mkdir(os.path.join(run_dir, sub))
        return {"run_id": run_id, "run_dir": run_dir}
    raise OSError("could not create a unique run directory under %s" % runs)


# ---- targets, backup, work copy ----
def list_target_files(root: str, pattern: Optional[str] = None) -> List[str]:
    """Regular files directly in `root` (not recursive), sorted; pattern is case-insensitive."""
    names = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        if pattern and not fnmatch.fnmatch(name.lower(), pattern.lower()):
            continue
        names.append(full)
    return names


def backup_files(src_root: str, files: Iterable[str], backup_dir: str,
                 copy: Callable[[str, str], object] = shutil.copy2) -> List[Dict]:
    """Copy each file to backup_dir, verify SHA-256, mark read-only. Raises BackupError."""
    entries = []
    for path in files:
        rel = os.path.relpath(path, src_root)
        dest = os.path.join(backup_dir, rel)
        try:
            original_sha = atomic.sha256_file(path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            copy(path, dest)
            backup_sha = atomic.sha256_file(dest)
        except Exception as exc:
            raise BackupError("backup of %s failed: %s" % (path, exc))
        if backup_sha != original_sha:
            raise BackupError("backup of %s does not match the original (SHA-256 differs)" % path)
        os.chmod(dest, stat.S_IREAD)
        entries.append({"rel": rel, "original_path": path, "backup_path": dest,
                        "sha256": original_sha, "size": os.path.getsize(dest)})
    return entries


def create_work_copy(backups: Iterable[Dict], work_dir: str,
                     copy: Callable[[str, str], object] = shutil.copy2) -> List[str]:
    """Copy from the backups (never from the official folder). Partial copies are kept."""
    copies = []
    for entry in backups:
        dest = os.path.join(work_dir, entry["rel"])
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            copy(entry["backup_path"], dest)
            os.chmod(dest, stat.S_IREAD | stat.S_IWRITE)
        except Exception as exc:
            raise WorkCopyError("work copy of %s failed: %s" % (entry["backup_path"], exc))
        copies.append(dest)
    return copies
