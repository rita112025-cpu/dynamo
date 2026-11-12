"""input_fingerprint (r2-final 1.3).

sha256(canonical_json({fp_version, task_id, task_version, contract_sha256,
entry_sha256, params, input_files})). `mode`, run_id, times and work-copy paths
are deliberately excluded. Relative paths are normalised with ntpath so the
result is the same on Windows and in the Linux test container.
"""
import ntpath
import os
from typing import Dict, Iterable, List, Sequence, Tuple

from . import atomic

FP_VERSION = "1"


def normalize_rel_path(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path.replace("/", "\\")))


def describe_files(root: str, paths: Iterable[str]) -> List[Tuple[str, int, str]]:
    """(normalised path relative to root, size, sha256) for each file, sorted by path."""
    rows = []
    for path in paths:
        rel = os.path.relpath(path, root)
        rows.append((normalize_rel_path(rel), os.path.getsize(path), atomic.sha256_file(path)))
    return sorted(rows)


def input_fingerprint(task_id: str, task_version: str, contract_sha256: str, entry_sha256: str,
                      params: Dict, input_files: Sequence[Sequence]) -> str:
    files = sorted([normalize_rel_path(str(p)), int(size), str(digest)] for p, size, digest in input_files)
    payload = {
        "fp_version": FP_VERSION,
        "task_id": task_id,
        "task_version": task_version,
        "contract_sha256": contract_sha256,
        "entry_sha256": entry_sha256,
        "params": params,
        "input_files": files,
    }
    return atomic.sha256_bytes(atomic.canonical_json(payload))
