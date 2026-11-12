"""Result contract: validation, state machine, output-path guard and the judge.

Judge order follows r2-final section 2 (J3-J10). J2 (user stop) and J11
(controller error) are decided by the controller around this module.
Process exit codes are never used to decide success.
"""
import datetime
import ntpath
import os
import re
from typing import Dict, List, Optional

from . import atomic, contracts, schema_check, workspace

FINAL_STATES = frozenset(["success", "failed", "skipped", "interrupted"])
TRANSITIONS = {
    None: frozenset(["pending"]),
    "pending": frozenset(["skipped", "running"]),
    "running": frozenset(["success", "failed", "interrupted"]),
}
INTERRUPT_CODES = frozenset(["INTERRUPTED_BY_USER", "RESULT_MISSING", "RUNNER_CRASH"])
HALTING_FAILURE_CLASSES = frozenset(["verification", "controller_error"])
IDENTITY_FIELDS = ("task_id", "task_version", "run_id", "run_nonce", "input_fingerprint", "mode")
_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{6})?[+-][0-9]{2}:[0-9]{2}$")
_SCHEMA = None


class InvalidTransition(ValueError):
    pass


class PathEscape(ValueError):
    pass


def check_transition(old: Optional[str], new: str) -> None:
    if new not in TRANSITIONS.get(old, frozenset()):
        raise InvalidTransition("%s -> %s is not allowed" % (old, new))


def result_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = contracts.load_schema("result.schema.json")
    return _SCHEMA


def parse_time(value: str) -> datetime.datetime:
    if not isinstance(value, str) or not _TIME.match(value):
        raise ValueError("time %r must be ISO 8601 with a +HH:MM offset (no 'Z')" % (value,))
    return datetime.datetime.fromisoformat(value)


def consistency_problems(doc: Dict) -> List[str]:
    problems = []
    status = doc["status"]
    times = {}
    for key in ("started_at", "finished_at"):
        if doc[key] is None:
            continue
        try:
            times[key] = parse_time(doc[key])
        except ValueError as exc:
            problems.append("%s: %s" % (key, exc))
    if len(times) == 2 and times["finished_at"] < times["started_at"]:
        problems.append("finished_at is earlier than started_at")
    if doc["items_modified"] > doc["items_processed"]:
        problems.append("items_modified exceeds items_processed")
    if doc["mode"] == "dry_run" and doc["items_modified"] > 0:
        problems.append("a dry run cannot modify items")
    if doc["written_by"] == "task":
        for key in ("run_nonce", "input_fingerprint"):
            if doc[key] is None:
                problems.append("%s is required in a task-written result" % key)
    codes = set(e["code"] for e in doc["errors"])
    if status == "success":
        if doc["errors"]:
            problems.append("success must not carry errors")
        if doc["started_at"] is None:
            problems.append("success needs started_at")
        if any(i["status"] == "failed" for i in doc.get("items", [])):
            problems.append("success cannot contain failed items")
    if status == "failed":
        if not doc["errors"]:
            problems.append("failed needs at least one error")
        if doc["failure_class"] is None:
            problems.append("failed needs failure_class")
    elif doc["failure_class"] is not None:
        problems.append("failure_class is only allowed when status is failed")
    if status == "skipped":
        if doc["skip_reason"] is None:
            problems.append("skipped needs skip_reason")
        if doc["started_at"] is not None:
            problems.append("skipped must have started_at null")
        if doc["items_processed"] or doc["items_modified"]:
            problems.append("skipped must not process items")
    elif doc["skip_reason"] is not None:
        problems.append("skip_reason is only allowed when status is skipped")
    if status == "interrupted":
        if doc["started_at"] is None:
            problems.append("interrupted needs started_at")
        if not codes & INTERRUPT_CODES:
            problems.append("interrupted needs one of %s" % sorted(INTERRUPT_CODES))
    return problems


def validate_result(doc) -> List[str]:
    errors = schema_check.validate(doc, result_schema())
    if errors:
        return errors
    return consistency_problems(doc)


def read_result(path: str) -> Dict:
    """Read and validate; raises ValueError with all problems."""
    doc = atomic.read_json_strict(path)
    problems = validate_result(doc)
    if problems:
        raise ValueError("; ".join(problems))
    return doc


def write_result(path: str, doc: Dict, **kwargs) -> None:
    problems = validate_result(doc)
    if problems:
        raise ValueError("refusing to write an invalid result: %s" % "; ".join(problems))
    atomic.atomic_write_json(path, doc, **kwargs)


# ---- output path guard (r2-final section 4) ----
def resolve_output_path(rel: str, allowed_root: str) -> str:
    """Return the absolute path of `rel` inside allowed_root, or raise PathEscape."""
    if not isinstance(rel, str) or not rel.strip():
        raise PathEscape("empty path")
    if ntpath.splitdrive(rel)[0] or rel[0] in "\\/" or ntpath.isabs(rel):
        raise PathEscape("absolute, drive or UNC path: %s" % rel)
    if ":" in rel:
        raise PathEscape("':' (alternate data stream) is not allowed: %s" % rel)
    parts = ntpath.normpath(rel.replace("/", "\\")).split("\\")
    if any(p == ".." for p in parts) or parts in ([""], ["."]):
        raise PathEscape("path leaves the run folder: %s" % rel)
    candidate = os.path.join(allowed_root, *parts)
    real_root = os.path.realpath(allowed_root)
    real = os.path.realpath(candidate)
    if os.path.commonpath([real, real_root]) != real_root:
        raise PathEscape("path resolves outside the run folder: %s" % rel)
    return candidate


# ---- results written by the controller ----
def issue(code: str, message: str, path: Optional[str] = None) -> Dict:
    return {"code": code, "message": message, "path": path}


def controller_result(base: Dict, status: str, started_at: Optional[str] = None,
                      errors: Optional[List[Dict]] = None, warnings: Optional[List[Dict]] = None,
                      skip_reason: Optional[str] = None, failure_class: Optional[str] = None,
                      halted: bool = False, input_files: Optional[List[Dict]] = None,
                      process: Optional[Dict] = None, evidence: Optional[List[str]] = None) -> Dict:
    doc = {
        "result_version": "1.0",
        "task_id": base["task_id"],
        "task_version": base["task_version"],
        "run_id": base["run_id"],
        "run_nonce": base.get("run_nonce"),
        "input_fingerprint": base.get("input_fingerprint"),
        "mode": base["mode"],
        "status": status,
        "written_by": "controller",
        "started_at": started_at,
        "finished_at": workspace.now_iso(),
        "input_files": input_files or [],
        "output_files": [],
        "items_processed": 0,
        "items_modified": 0,
        "errors": errors or [],
        "warnings": warnings or [],
        "skip_reason": skip_reason,
        "failure_class": failure_class,
        "verified_by_controller": False,
        "halted_run": halted,
    }
    if process is not None:
        doc["process"] = process
    if evidence:
        doc["evidence"] = evidence
    return doc


class Judgement(object):
    def __init__(self, status: str, failure_class: Optional[str] = None,
                 errors: Optional[List[Dict]] = None, doc: Optional[Dict] = None):
        self.status = status
        self.failure_class = failure_class
        self.errors = errors or []
        self.doc = doc

    @property
    def halts(self) -> bool:
        return self.status == "interrupted" or self.failure_class in HALTING_FAILURE_CLASSES

    @property
    def codes(self) -> List[str]:
        return [e["code"] for e in self.errors]


def _verification(code: str, message: str, doc: Optional[Dict] = None) -> Judgement:
    return Judgement("failed", "verification", [issue(code, message)], doc)


def judge(job: Dict, runner_crashed: bool = False,
          now: Optional[datetime.datetime] = None) -> Judgement:
    """Classify the Runner's result file for `job` (J3-J10)."""
    path = job["result_path"]
    if not os.path.exists(path):
        errors = [issue("RESULT_MISSING", "the runner ended without writing %s" % os.path.basename(path))]
        if runner_crashed:
            errors.append(issue("RUNNER_CRASH", "the runner raised an exception; see evidence"))
        return Judgement("interrupted", None, errors)
    try:
        doc = atomic.read_json_strict(path)
    except (OSError, ValueError) as exc:
        return _verification("RESULT_INVALID", "result file is damaged or not JSON: %s" % exc)
    problems = validate_result(doc)
    if problems:
        return _verification("RESULT_INVALID", "; ".join(problems[:10]))
    if doc["written_by"] != "task":
        return _verification("RESULT_INVALID", "result was not written by the task", doc)
    if doc["status"] not in ("success", "failed"):
        return _verification("RESULT_INVALID",
                             "a runner may only report success or failed, not %s" % doc["status"], doc)
    for key in IDENTITY_FIELDS:
        if doc[key] != job[key]:
            return _verification("RESULT_STALE", "%s does not match this run's job" % key, doc)
    now_dt = (now or datetime.datetime.now()).astimezone()
    issued = parse_time(job["issued_at"])
    if parse_time(doc["started_at"]) < issued or parse_time(doc["finished_at"]) > now_dt:
        return _verification("RESULT_TIME", "started_at/finished_at outside the job's time window", doc)
    staging = job["staging_dir"]
    resolved = []
    for out in doc["output_files"]:
        try:
            resolved.append((out, resolve_output_path(out["path"], staging)))
        except PathEscape as exc:
            return _verification("RESULT_PATH_ESCAPE", str(exc), doc)
    for out, full in resolved:
        if not os.path.isfile(full):
            return _verification("OUTPUT_HASH_MISMATCH", "output %s does not exist" % out["path"], doc)
        if os.path.getsize(full) != out["size"] or atomic.sha256_file(full) != out["sha256"]:
            return _verification("OUTPUT_HASH_MISMATCH", "output %s size or SHA-256 differs" % out["path"], doc)
    if doc["status"] == "failed":
        return Judgement("failed", "task_reported", list(doc["errors"]), doc)
    return Judgement("success", None, [], doc)


def backfill_interrupted(run_dir: str) -> List[str]:
    """After a manual stale-lock release: mark planned tasks without a result as interrupted."""
    written = []
    try:
        plan = atomic.read_json_strict(os.path.join(run_dir, "plan.json"))
    except (OSError, ValueError):
        return written
    for task in plan.get("tasks", []):
        path = os.path.join(run_dir, "results", "%s.result.json" % task["task_id"])
        if os.path.exists(path):
            continue
        base = {"task_id": task["task_id"], "task_version": task["task_version"],
                "run_id": plan["run_id"], "mode": plan["mode"]}
        doc = controller_result(base, "interrupted", started_at=plan["created_at"], errors=[
            issue("RESULT_MISSING", "run did not finish; lock released manually")])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_result(path, doc)
        written.append(path)
    return written
