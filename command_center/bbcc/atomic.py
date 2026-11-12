"""Atomic file writes, canonical JSON and SHA-256 helpers.

Write rule (r2-final section 5): write <name>.<8 hex>.tmp in the same folder,
flush + fsync, then os.replace. On Windows os.replace fails while another
process (antivirus, indexer, Excel) holds the target open; those errors are
retried up to 4 times (0.1/0.2/0.4/0.8 s). On final failure the tmp file is
removed and the old target is left untouched.
"""
import hashlib
import json
import os
import secrets
import time
from typing import Any, Callable, Optional

RETRY_WINERRORS = (5, 32, 33)  # access denied, sharing violation, lock violation
RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8)
UTF8_BOM = b"\xef\xbb\xbf"


class AtomicWriteError(OSError):
    """The target could not be replaced. The previous target bytes are unchanged."""

    def __init__(self, path: str, cause: BaseException, attempts: int):
        self.path = path
        self.cause = cause
        self.attempts = attempts
        super().__init__("atomic write to %s failed after %d attempt(s): %s: %s"
                         % (path, attempts, type(cause).__name__, cause))


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    return getattr(exc, "winerror", None) in RETRY_WINERRORS


def _remove_quietly(path: str) -> Optional[str]:
    try:
        os.remove(path)
        return None
    except FileNotFoundError:
        return None
    except OSError as exc:  # reported, never hides the original error
        return "could not remove %s: %s" % (path, exc)


def atomic_write_bytes(path: str, data: bytes,
                       replace: Optional[Callable[[str, str], None]] = None,
                       sleep: Optional[Callable[[float], None]] = None) -> None:
    replace = replace or os.replace
    sleep = sleep or time.sleep
    target = os.path.abspath(path)
    folder = os.path.dirname(target)
    tmp = os.path.join(folder, "%s.%s.tmp" % (os.path.basename(target), secrets.token_hex(4)))
    try:
        with open(tmp, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        _remove_quietly(tmp)
        raise AtomicWriteError(target, exc, 0)
    attempts = 0
    while True:
        attempts += 1
        try:
            replace(tmp, target)
            return
        except OSError as exc:
            if is_retryable(exc) and attempts <= len(RETRY_DELAYS):
                sleep(RETRY_DELAYS[attempts - 1])
                continue
            _remove_quietly(tmp)
            raise AtomicWriteError(target, exc, attempts)


def json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write_json(path: str, obj: Any, **kwargs) -> None:
    atomic_write_bytes(path, json_bytes(obj), **kwargs)


def read_json_strict(path: str) -> Any:
    """Read UTF-8 JSON without BOM. Raises ValueError on BOM or bad JSON."""
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith(UTF8_BOM):
        raise ValueError("%s starts with a UTF-8 BOM; write UTF-8 without BOM" % path)
    return json.loads(raw.decode("utf-8"))


def write_new_json(path: str, obj: Any, link: Optional[Callable[[str, str], None]] = None) -> None:
    """Create a JSON file that must not exist yet; never overwrites, even under a race.

    The complete content is written to a tmp file first and then published with
    os.link(tmp, target), which fails atomically when the target exists. On a file
    system without hard links (for example FAT/exFAT) the fallback is
    os.open(O_CREAT | O_EXCL): still exclusive, but a crash during that write can
    leave a partial file.
    """
    link = link or os.link
    target = os.path.abspath(path)
    tmp = os.path.join(os.path.dirname(target), "%s.%s.tmp" % (os.path.basename(target), secrets.token_hex(4)))
    data = json_bytes(obj)
    try:
        with open(tmp, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            link(tmp, target)
            return
        except FileExistsError:
            raise
        except (OSError, NotImplementedError, AttributeError):
            pass  # no hard links here: use the exclusive-create fallback below
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        _remove_quietly(tmp)
