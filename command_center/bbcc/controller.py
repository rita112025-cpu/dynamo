"""Controller: Runner interface, FakeRunner, execute() and read-only check_promotion().

M1-B scope: only FakeRunner exists. No Revit, Dynamo or AutoCAD runner, no
write-back to official folders, no approval records. Tasks always work on a
copy taken from the verified backup of the official target folder.
"""
import os
import re
import shutil
import threading
import traceback
from typing import Callable, Dict, List, Optional, Sequence

from . import CONTROLLER_VERSION, atomic, contracts, fingerprint, ledger, locks, results, workspace
from .results import issue

FILE_ROLES = ("target_models", "source_model", "data_file")
FILE_TYPES = ("file", "file_list")


class RunnerOutcome(object):
    """What a runner reports about its process. Recorded only; never decides success."""

    def __init__(self, exit_code: Optional[int] = None, pid: Optional[int] = None):
        self.exit_code = exit_code
        self.pid = pid


class Runner(object):
    def run(self, job: Dict, stop_event: threading.Event) -> Optional[RunnerOutcome]:
        raise NotImplementedError


def write_task_result(job: Dict, status: str = "success", outputs: Sequence = (),
                      items_processed: int = 1, items_modified: Optional[int] = None,
                      errors: Optional[List[Dict]] = None, overrides: Optional[Dict] = None) -> Dict:
    """Helper for fake runners: write outputs into staging and a task-written result.

    `overrides` replaces fields after the document is built (used by tests to
    simulate stale or tampered results). No validation is applied here.
    """
    refs = []
    for rel, data in outputs:
        full = os.path.join(job["staging_dir"], *re.split(r"[\\/]", rel))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(data)
        refs.append({"path": rel, "sha256": atomic.sha256_bytes(data), "size": len(data)})
    if items_modified is None:
        items_modified = 0 if job["mode"] == "dry_run" else items_processed
    if errors is None:
        errors = [] if status == "success" else [issue("TASK_ERROR", "the task reported an error")]
    doc = {
        "result_version": "1.0",
        "task_id": job["task_id"],
        "task_version": job["task_version"],
        "run_id": job["run_id"],
        "run_nonce": job["run_nonce"],
        "input_fingerprint": job["input_fingerprint"],
        "mode": job["mode"],
        "status": status,
        "written_by": "task",
        "started_at": job["issued_at"],
        "finished_at": workspace.now_iso(),
        "input_files": job["input_files"],
        "output_files": refs,
        "items_processed": items_processed,
        "items_modified": items_modified,
        "errors": errors,
        "warnings": [],
        "skip_reason": None,
        "failure_class": None if status == "success" else "task_reported",
        "verified_by_controller": False,
        "halted_run": False,
    }
    doc.update(overrides or {})
    atomic.atomic_write_json(job["result_path"], doc)
    return doc


def succeed(job, stop_event):
    write_task_result(job, outputs=[("report.txt", b"ok")])
    return RunnerOutcome(exit_code=0)


class FakeRunner(Runner):
    """Test runner. `behaviors` maps task_id -> callable(job, stop_event)."""

    def __init__(self, behaviors: Optional[Dict[str, Callable]] = None):
        self.behaviors = behaviors or {}
        self.calls = []

    def run(self, job, stop_event):
        self.calls.append(job["task_id"])
        return self.behaviors.get(job["task_id"], succeed)(job, stop_event)


class Options(object):
    """Injection points; defaults are the real implementations."""

    def __init__(self, copy=shutil.copy2, pid_alive=locks.default_pid_alive, host=None,
                 mkdir=os.mkdir, environ=None, drive_type=None, flavor=None):
        self.copy = copy
        self.pid_alive = pid_alive
        self.host = host
        self.mkdir = mkdir
        self.environ = environ
        self.drive_type = drive_type
        self.flavor = flavor


class RunSummary(object):
    def __init__(self, run_id: str, run_dir: str):
        self.run_id = run_id
        self.run_dir = run_dir
        self.results = {}
        self.halted = False
        self.lock_errors = []
        self.errors = []      # controller problems that could not be recorded as a task result
        self.not_run = []     # tasks never processed because recording a controller error failed

    def status(self, task_id: str) -> str:
        return self.results[task_id]["status"]


class _Skip(Exception):
    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(message)


def _target_input(contract):
    for item in contract.inputs:
        if item["role"] == "target_models" and item["type"] == "dir":
            return item
    return None


def _write_text(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic.atomic_write_bytes(path, text.encode("utf-8"))
    return path


def _move_runner_result(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    rejected = path[:-len(".json")] + ".rejected.json"
    os.replace(path, rejected)
    return rejected


class _Run(object):
    def __init__(self, registry, order, inputs, mode, runs_root, repo_root, runner, stop_event,
                 allow_rerun, opts, created):
        self.registry = registry
        self.order = order
        self.inputs = inputs
        self.mode = mode
        self.runs_root = runs_root
        self.repo_root = repo_root
        self.runner = runner
        self.stop_event = stop_event
        self.allow_rerun = allow_rerun
        self.opts = opts
        self.run_id = created["run_id"]
        self.run_dir = created["run_dir"]
        self.summary = RunSummary(self.run_id, self.run_dir)
        self.state = {}
        self.locks = {}

    # ---- bookkeeping ----
    def path(self, *parts):
        return os.path.join(self.run_dir, *parts)

    def set_state(self, task_id, new):
        """The in-memory state changes only after run_state.json was written."""
        results.check_transition(self.state.get(task_id), new)
        updated = dict(self.state)
        updated[task_id] = new
        atomic.atomic_write_json(self.path("run_state.json"), {"run_id": self.run_id, "tasks": updated})
        self.state = updated

    def finish(self, task_id, doc, fp=None, rerun_reason=None):
        """Commit a final result: result file -> ledger record -> run state.

        The task becomes final only after all three steps succeeded. If any step
        raises, the task is still pending/running, so controller_error() can record
        a controller_error failure and halt the batch.
        """
        results.write_result(self.path("results", "%s.result.json" % task_id), doc)
        if fp:
            promotion = "pending_approval" if (doc["mode"] == "write" and doc["status"] == "success") else "none"
            ledger.write_record(self.runs_root, {
                "run_id": self.run_id, "task_id": task_id, "task_version": doc["task_version"],
                "input_fingerprint": fp, "mode": doc["mode"], "status": doc["status"],
                "recorded_at": workspace.now_iso(), "promotion": promotion, "rerun_reason": rerun_reason})
        self.set_state(task_id, doc["status"])
        self.summary.results[task_id] = doc
        if doc["halted_run"]:
            self.summary.halted = True

    def base(self, contract, nonce=None, fp=None):
        return {"task_id": contract.task_id, "task_version": contract.task_version, "run_id": self.run_id,
                "mode": self.mode, "run_nonce": nonce, "input_fingerprint": fp}

    # ---- preflight ----
    def preflight(self, contract):
        given = dict(self.inputs.get(contract.task_id, {}))
        values = {}
        for item in contract.inputs:
            if item["role"] == "write_switch":
                values[item["name"]] = (self.mode == "write")
            elif item["name"] in given:
                values[item["name"]] = given[item["name"]]
            elif "default" in item:
                values[item["name"]] = item["default"]
            elif item["required"]:
                raise _Skip("preflight_failed", "required input '%s' is missing" % item["name"])
        entry = os.path.join(self.repo_root, *re.split(r"[\\/]", contract.entry_path))
        if not os.path.isfile(entry):
            raise _Skip("preflight_failed", "entry file not found: %s" % contract.entry_path)
        entry_sha = atomic.sha256_file(entry)
        target = _target_input(contract)
        root, files = None, []
        if target is not None:
            root = values.get(target["name"])
            if not root or not os.path.isdir(root):
                raise _Skip("preflight_failed", "target folder not found: %s" % root)
            files = workspace.list_target_files(root, target.get("file_pattern"))
            if not files:
                raise _Skip("preflight_failed", "NO_TARGETS: no matching files in %s" % root)
        external = self.external_files(contract, values, target)
        file_inputs = set(i["name"] for i in contract.inputs
                          if i["role"] in FILE_ROLES or i["type"] in FILE_TYPES or i["role"] == "write_switch")
        params = dict((k, v) for k, v in values.items() if k not in file_inputs)
        described = fingerprint.describe_files(root, files) if root else []
        rows = list(described) + [(e["path"], e["size"], e["sha256"]) for e in external]
        fp = fingerprint.input_fingerprint(contract.task_id, contract.task_version, contract.sha256,
                                           entry_sha, params, rows)
        return {"values": values, "root": root, "files": files, "described": described,
                "external": external, "fp": fp, "target": target}

    @staticmethod
    def external_files(contract, values, target):
        """Every file-type input other than the target folder must exist; each is hashed
        and becomes part of the fingerprint (source models, data files, file lists)."""
        rows = []
        for item in contract.inputs:
            if item is target or item["role"] == "write_switch":
                continue
            if item["role"] not in FILE_ROLES and item["type"] not in FILE_TYPES:
                continue
            if item["name"] not in values or values[item["name"]] is None:
                continue
            value = values[item["name"]]
            if item["type"] == "file_list":
                if not isinstance(value, list):
                    raise _Skip("preflight_failed", "input '%s' must be a list of files" % item["name"])
                paths = value
            elif item["type"] == "file":
                paths = [value]
            else:
                raise _Skip("preflight_failed", "input '%s': only file inputs are supported for role %s"
                            % (item["name"], item["role"]))
            for index, path in enumerate(paths):
                if not isinstance(path, str) or not os.path.isfile(path):
                    raise _Skip("preflight_failed", "input file not found: %s (%s)" % (path, item["name"]))
                rows.append({"path": "input\\%s\\%d\\%s" % (item["name"], index, os.path.basename(path)),
                             "size": os.path.getsize(path), "sha256": atomic.sha256_file(path),
                             "role": item["role"], "source": os.path.abspath(path)})
        return rows

    def guard(self, contract, pre):
        task_id = contract.task_id
        reason = self.allow_rerun.get(task_id)
        decision = ledger.check_duplicate(self.runs_root, pre["fp"], self.mode,
                                          allow_rerun=reason is not None, rerun_reason=reason)
        if not decision.allowed:
            raise _Skip(decision.skip_reason, decision.message)
        if pre["root"] is None:
            return [], None
        key = locks.lock_key(pre["root"])
        if key not in self.locks:
            try:
                self.locks[key] = locks.acquire(self.runs_root, pre["root"], self.run_id, self.run_dir,
                                                host=self.opts.host, pid_alive=self.opts.pid_alive)
            except locks.LockBusy as busy:
                raise _Skip(busy.kind, busy.detail)
        try:
            backups = workspace.backup_files(pre["root"], pre["files"], self.path("backup", task_id),
                                             copy=self.opts.copy)
        except workspace.BackupError as exc:
            raise _Skip("backup_failed", str(exc))
        atomic.atomic_write_json(self.path("backup", "%s.manifest.json" % task_id), backups)
        work = self.path("work", task_id)
        os.makedirs(work, exist_ok=True)
        try:
            workspace.create_work_copy(backups, work, copy=self.opts.copy)
        except workspace.WorkCopyError as exc:
            raise _Skip("workcopy_failed", str(exc))
        return backups, work

    # ---- one task ----
    def run_task(self, contract):
        task_id = contract.task_id
        if self.summary.halted or self.stop_event.is_set():
            raise _Skip("run_halted", "the batch was stopped before this task started")
        for dep in contract.requires:
            dep_status = self.summary.results[dep]["status"]
            if dep_status != "success":
                reason = "dependency_skipped" if dep_status == "skipped" else "dependency_failed"
                raise _Skip(reason, "required task '%s' ended with %s" % (dep, dep_status))
        pre = self.preflight(contract)
        try:
            _, work = self.guard(contract, pre)
        except _Skip as skip:
            skip.fp = pre["fp"]
            raise
        self.set_state(task_id, "running")
        values = dict(pre["values"])
        if work is not None:
            values[pre["target"]["name"]] = work
        staging = self.path("staging", task_id)
        os.makedirs(staging, exist_ok=True)
        job = {
            "job_version": "1.0", "task_id": task_id, "task_version": contract.task_version,
            "run_id": self.run_id, "run_nonce": workspace.new_run_nonce(),
            "input_fingerprint": pre["fp"], "mode": self.mode, "inputs": values,
            "input_files": [{"path": p, "size": s, "sha256": h, "role": "target_model"}
                            for p, s, h in pre["described"]] +
                           [{"path": e["path"], "size": e["size"], "sha256": e["sha256"], "role": e["role"]}
                            for e in pre["external"]],
            "result_path": self.path("results", "%s.result.json" % task_id),
            "staging_dir": staging, "issued_at": workspace.now_iso(),
        }
        atomic.atomic_write_json(self.path("jobs", "%s.job.json" % task_id), job)
        crashed, outcome, evidence = False, None, []
        try:
            outcome = self.runner.run(job, self.stop_event)
        except Exception:
            crashed = True
            evidence.append(_write_text(self.path("evidence", task_id, "runner_exception.txt"),
                                        traceback.format_exc()))
        process = None
        if isinstance(outcome, RunnerOutcome):
            process = {"pid": outcome.pid, "exit_code": outcome.exit_code, "exit_seen_at": workspace.now_iso()}
        if self.stop_event.is_set():
            verdict = results.Judgement("interrupted", None, [
                issue("INTERRUPTED_BY_USER", "the batch was stopped while this task was running")])
        else:
            verdict = results.judge(job, runner_crashed=crashed)
        base = self.base(contract, job["run_nonce"], pre["fp"])
        reason = self.allow_rerun.get(task_id)
        if verdict.status == "success" or verdict.failure_class == "task_reported":
            doc = dict(verdict.doc)
            doc["verified_by_controller"] = True
            doc["halted_run"] = False
            if process is not None:
                doc["process"] = process
            if evidence:
                doc["evidence"] = evidence
            self.finish(task_id, doc, pre["fp"], reason)
            return
        rejected = _move_runner_result(job["result_path"])
        if rejected:
            evidence.append(rejected)
        doc = results.controller_result(base, verdict.status, started_at=job["issued_at"],
                                        errors=verdict.errors, failure_class=verdict.failure_class,
                                        halted=verdict.halts, input_files=job["input_files"],
                                        process=process, evidence=evidence)
        self.finish(task_id, doc, pre["fp"], reason)

    def skip(self, contract, skip):
        doc = results.controller_result(self.base(contract, None, getattr(skip, "fp", None)), "skipped",
                                        warnings=[issue(skip.reason.upper(), skip.message)],
                                        skip_reason=skip.reason)
        self.finish(contract.task_id, doc, getattr(skip, "fp", None))

    def controller_error(self, contract):
        """Record a controller_error failure. The batch is halted before anything else,
        so even if recording fails below, no further task can start."""
        task_id = contract.task_id
        self.summary.halted = True
        trace = traceback.format_exc()
        evidence = []
        try:
            evidence.append(_write_text(self.path("evidence", task_id, "controller_error.txt"), trace))
        except Exception as exc:
            self.summary.errors.append("%s: could not save controller error trace: %s" % (task_id, exc))
        if self.state.get(task_id) not in ("pending", "running"):
            # finish() makes a task final only as its last step, so this means the error
            # happened after the task was completely recorded; keep it and report.
            self.summary.errors.append("%s: controller error after the task was recorded as %s"
                                       % (task_id, self.state.get(task_id)))
            return
        if self.state.get(task_id) == "pending":
            self.set_state(task_id, "running")
        rejected = _move_runner_result(self.path("results", "%s.result.json" % task_id))
        if rejected:
            evidence.append(rejected)
        doc = results.controller_result(self.base(contract), "failed", started_at=workspace.now_iso(),
                                        errors=[issue("CONTROLLER_ERROR", "internal controller error; see evidence")],
                                        failure_class="controller_error", halted=True, evidence=evidence)
        self.finish(task_id, doc)

    def execute(self):
        atomic.atomic_write_json(self.path("plan.json"), {
            "plan_version": "1", "run_id": self.run_id, "created_at": workspace.now_iso(), "mode": self.mode,
            "controller_version": CONTROLLER_VERSION,
            "tasks": [{"task_id": t, "task_version": self.registry[t].task_version} for t in self.order]})
        for task_id in self.order:
            self.set_state(task_id, "pending")
        try:
            for task_id in self.order:
                contract = self.registry[task_id]
                try:
                    try:
                        self.run_task(contract)
                    except _Skip as skip:
                        self.skip(contract, skip)
                except Exception:
                    try:
                        self.controller_error(contract)
                    except Exception as exc:
                        self.summary.halted = True
                        self.summary.errors.append("%s: CONTROLLER_ERROR_UNRECORDED: %s: %s"
                                                   % (task_id, type(exc).__name__, exc))
                        position = self.order.index(task_id)
                        self.summary.not_run = list(self.order[position + 1:])
                        break
        finally:
            for handle in self.locks.values():
                try:
                    locks.release_own(handle)
                except (locks.LockReleaseRefused, OSError) as exc:
                    self.summary.lock_errors.append(str(exc))
            try:
                atomic.atomic_write_json(self.path("run_summary.json"), {
                    "run_id": self.run_id, "mode": self.mode, "halted": self.summary.halted,
                    "lock_errors": self.summary.lock_errors, "errors": self.summary.errors,
                    "not_run": self.summary.not_run,
                    "tasks": dict((t, {"status": d["status"], "failure_class": d["failure_class"],
                                       "skip_reason": d["skip_reason"],
                                       "codes": [e["code"] for e in d["errors"]]})
                                  for t, d in self.summary.results.items())})
            except Exception as exc:
                self.summary.errors.append("run_summary.json could not be written: %s" % exc)
        return self.summary


def execute(registry: Dict[str, contracts.TaskContract], selected: Sequence[str], inputs: Dict[str, Dict],
            mode: str, runs_root: str, repo_root: str, runner: Runner,
            stop_event: Optional[threading.Event] = None, allow_rerun: Optional[Dict[str, str]] = None,
            options: Optional[Options] = None) -> RunSummary:
    """Run the selected tasks. Raises PlanError / ConfigError before any run folder is created."""
    if mode not in ("dry_run", "write"):
        raise ValueError("mode must be dry_run or write")
    opts = options or Options()
    order = contracts.make_plan(registry, selected)
    targets = []
    for task_id in order:
        item = _target_input(registry[task_id])
        if item is not None and inputs.get(task_id, {}).get(item["name"]):
            targets.append(inputs[task_id][item["name"]])
    workspace.check_runs_root(runs_root, opts.environ, opts.drive_type, targets, opts.flavor)
    created = workspace.create_run_dir(runs_root, mkdir=opts.mkdir)
    run = _Run(registry, order, inputs, mode, runs_root, repo_root, runner,
               stop_event or threading.Event(), dict(allow_rerun or {}), opts, created)
    return run.execute()


MANIFEST_KEYS = ("rel", "original_path", "backup_path", "sha256", "size")


def _manifest_problems(run_dir: str, task_id: str, job: Optional[Dict]) -> List[str]:
    targets = [f for f in (job or {}).get("input_files", []) if f.get("role") == "target_model"]
    path = os.path.join(run_dir, "backup", "%s.manifest.json" % task_id)
    if not targets and not os.path.exists(path):
        return []
    if not os.path.exists(path):
        return ["MANIFEST_MISSING"]
    try:
        manifest = atomic.read_json_strict(path)
        if not isinstance(manifest, list) or not all(
                isinstance(e, dict) and all(k in e for k in MANIFEST_KEYS) and
                re.match(r"^[0-9a-f]{64}$", str(e["sha256"])) for e in manifest):
            raise ValueError("unexpected structure")
    except (OSError, ValueError):
        return ["MANIFEST_INVALID"]
    reasons = []
    expected = dict((t["path"], t["sha256"]) for t in targets)
    listed = dict((fingerprint.normalize_rel_path(e["rel"]), e["sha256"]) for e in manifest)
    if expected != listed:
        reasons.append("MANIFEST_MISMATCH")
    for entry in manifest:
        backup, original = entry["backup_path"], entry["original_path"]
        if not os.path.isfile(backup):
            reasons.append("BACKUP_MISSING:%s" % entry["rel"])
        elif atomic.sha256_file(backup) != entry["sha256"]:
            reasons.append("BACKUP_CHANGED:%s" % entry["rel"])
        if not os.path.isfile(original):
            reasons.append("ORIGINAL_MISSING:%s" % entry["rel"])
        elif atomic.sha256_file(original) != entry["sha256"]:
            reasons.append("ORIGINAL_CHANGED:%s" % entry["rel"])
    return reasons


def _promotion_problems(run_dir: str, run_id: str, task_id: str, state: Optional[str]) -> List[str]:
    reasons = []
    if state != "success":
        reasons.append("STATE_NOT_SUCCESS")
    try:
        doc = results.read_result(os.path.join(run_dir, "results", "%s.result.json" % task_id))
    except (OSError, ValueError):
        return reasons + ["RESULT_INVALID"]
    if doc["status"] != "success":
        reasons.append("NOT_SUCCESS")
    if doc["mode"] != "write":
        reasons.append("DRY_RUN")
    if doc["written_by"] != "task" or doc["verified_by_controller"] is not True:
        reasons.append("NOT_VERIFIED")
    job = None
    try:
        job = atomic.read_json_strict(os.path.join(run_dir, "jobs", "%s.job.json" % task_id))
    except (OSError, ValueError):
        reasons.append("JOB_MISSING")
    if doc["run_id"] != run_id or doc["task_id"] != task_id or (
            job is not None and any(doc[k] != job.get(k) for k in results.IDENTITY_FIELDS)):
        reasons.append("RESULT_STALE")
    staging = os.path.join(run_dir, "staging", task_id)
    for out in doc["output_files"]:
        try:
            full = results.resolve_output_path(out["path"], staging)
        except results.PathEscape:
            reasons.append("OUTPUT_PATH_ESCAPE:%s" % out["path"])
            continue
        if not os.path.isfile(full) or atomic.sha256_file(full) != out["sha256"]:
            reasons.append("OUTPUT_CHANGED:%s" % out["path"])
    if job is not None:
        reasons += _manifest_problems(run_dir, task_id, job)
    return reasons


def check_promotion(run_dir: str) -> Dict[str, Dict]:
    """Read-only: report whether each planned task's results could be written back.

    Any missing or unverifiable evidence makes a task not promotable: run state,
    result file (schema + consistency), controller verification, job identity,
    staged output hashes, backup manifest, backup files and official files.
    Nothing is written.
    """
    run_id = os.path.basename(os.path.normpath(run_dir))
    try:
        plan = atomic.read_json_strict(os.path.join(run_dir, "plan.json"))
        task_ids = [t["task_id"] for t in plan["tasks"]]
    except (OSError, ValueError, KeyError, TypeError):
        return {"*": {"promotable": False, "reasons": ["PLAN_MISSING"]}}
    try:
        state = atomic.read_json_strict(os.path.join(run_dir, "run_state.json")).get("tasks", {})
    except (OSError, ValueError, AttributeError):
        state = {}
    report = {}
    for task_id in task_ids:
        reasons = _promotion_problems(run_dir, run_id, task_id, state.get(task_id))
        report[task_id] = {"promotable": not reasons, "reasons": reasons}
    return report
