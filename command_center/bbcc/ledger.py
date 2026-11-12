"""Run ledger and duplicate-run rules (r2-final 3.2-3.3, section 6).

Records: <runs_root>/ledger/<input_fingerprint>/<run_id>.json, one file
per task run, written once and never overwritten or deleted.

Approval records (section 6) are only *defined and validated* here. M1-B never
writes an approval record and never writes to an official folder.
"""
import os
import re
from typing import Dict, List, Optional

from . import atomic, results

PROMOTION_STATES = ("none", "pending_approval", "promoted", "rejected")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Decision(object):
    def __init__(self, allowed: bool, skip_reason: Optional[str] = None, message: str = ""):
        self.allowed = allowed
        self.skip_reason = skip_reason
        self.message = message

    def __repr__(self):
        return "Decision(%r, %r, %r)" % (self.allowed, self.skip_reason, self.message)


def ledger_dir(runs_root: str, fingerprint: str) -> str:
    return os.path.join(runs_root, "ledger", fingerprint)


def write_record(runs_root: str, record: Dict) -> str:
    for key in ("run_id", "task_id", "task_version", "input_fingerprint", "mode", "status"):
        if not record.get(key):
            raise ValueError("ledger record needs %s" % key)
    if record.get("promotion", "none") not in PROMOTION_STATES:
        raise ValueError("unknown promotion state %r" % record.get("promotion"))
    folder = ledger_dir(runs_root, record["input_fingerprint"])
    os.makedirs(folder, exist_ok=True)
    # The fingerprint already contains task_id, so <run_id>.json is unique per folder.
    path = os.path.join(folder, "%s.json" % record["run_id"])
    data = dict(record)
    data.setdefault("ledger_version", "1")
    data.setdefault("promotion", "none")
    data.setdefault("promoted_at", None)
    data.setdefault("promoted_by", None)
    data.setdefault("rerun_reason", None)
    atomic.write_new_json(path, data)
    return path


def list_records(runs_root: str, fingerprint: str) -> List[Dict]:
    folder = ledger_dir(runs_root, fingerprint)
    if not os.path.isdir(folder):
        return []
    records = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json"):
            records.append(atomic.read_json_strict(os.path.join(folder, name)))
    return records


def is_confirmed(runs_root: str, record: Dict) -> bool:
    """A record counts as evidence only if the run's own result file agrees with it:
    valid result, same run_id / fingerprint / mode / status, verified by the controller."""
    path = os.path.join(runs_root, "runs", record["run_id"], "results", "%s.result.json" % record["task_id"])
    try:
        doc = results.read_result(path)
    except (OSError, ValueError):
        return False
    return (doc["run_id"] == record["run_id"] and doc["input_fingerprint"] == record["input_fingerprint"]
            and doc["mode"] == record["mode"] and doc["status"] == record["status"]
            and doc["verified_by_controller"] is True)


def check_duplicate(runs_root: str, fingerprint: str, mode: str,
                    allow_rerun: bool = False, rerun_reason: Optional[str] = None) -> Decision:
    """Apply the table in r2-final 3.3.

    Records that *allow* something (a dry_run success enabling a write) must be
    confirmed by their result file. Records that *block* (pending or promoted
    write results) block even when unconfirmed, to stay on the safe side.
    """
    if mode == "dry_run":
        return Decision(True)
    records = list_records(runs_root, fingerprint)
    if not any(r["mode"] == "dry_run" and r["status"] == "success" and is_confirmed(runs_root, r)
               for r in records):
        return Decision(False, "preflight_failed",
                        "no dry_run success with the same input fingerprint; run a dry run first")
    writes = [r for r in records if r["mode"] == "write" and r["status"] == "success"]
    pending = [r for r in writes if r.get("promotion") == "pending_approval"]
    if pending:
        return Decision(False, "duplicate_run",
                        "results awaiting approval already exist (run_id=%s)" % pending[-1]["run_id"])
    promoted = [r for r in writes if r.get("promotion") == "promoted"]
    if promoted:
        if allow_rerun and rerun_reason and rerun_reason.strip():
            return Decision(True, None, "rerun allowed: %s" % rerun_reason.strip())
        return Decision(False, "duplicate_run",
                        "already promoted (run_id=%s); pass allow_rerun with a reason to run again"
                        % promoted[-1]["run_id"])
    return Decision(True)


# ---- approval record format (definition only, not written in M1-B) ----
APPROVAL_REQUIRED = ("approval_version", "run_id", "task_id", "task_version", "input_fingerprint",
                     "decision", "approver_name", "approver_account", "approver_host", "approved_at", "files")
APPROVAL_FILE_REQUIRED = ("original_path", "original_sha256_at_backup", "original_sha256_at_approval",
                          "delivered_path", "delivered_sha256", "backup_path")


def approval_problems(record: Dict) -> List[str]:
    """Validate an approval record dict against r2-final section 6."""
    problems = ["missing %s" % k for k in APPROVAL_REQUIRED if k not in record]
    if problems:
        return problems
    if record["decision"] not in ("approved", "rejected"):
        problems.append("decision must be approved or rejected")
    if not str(record["approver_name"]).strip():
        problems.append("approver_name is empty")
    if record["decision"] == "rejected" and not str(record.get("reason", "")).strip():
        problems.append("reason is required for a rejection")
    for index, item in enumerate(record["files"]):
        missing = [k for k in APPROVAL_FILE_REQUIRED if k not in item]
        if missing:
            problems.append("files[%d] missing %s" % (index, ", ".join(missing)))
            continue
        for key in ("original_sha256_at_backup", "original_sha256_at_approval", "delivered_sha256"):
            if not _HEX64.match(str(item[key])):
                problems.append("files[%d].%s is not a SHA-256" % (index, key))
        if record["decision"] == "approved" and \
                item["original_sha256_at_backup"] != item["original_sha256_at_approval"]:
            problems.append("files[%d]: official file changed since backup; cannot approve" % index)
    return problems
