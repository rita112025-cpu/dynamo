"""Test helpers. Everything is created inside a TemporaryDirectory; no real model is read.

The "models" are small byte files named *.rvt. They are not Revit files.
"""
import copy
import json
import os
import tempfile
import unittest

from bbcc import atomic, contracts, controller

MODEL_FILES = {"S-ESC-01.rvt": b"fake model one", "S-ESC-02.rvt": b"fake model two"}
HOST = "test-host"


def contract_dict(task_id="t1", requires=(), conflicts=()):
    return {
        "contract_version": "1.0",
        "task_id": task_id,
        "task_version": "1.0.0",
        "name": "Test task %s" % task_id,
        "application": {"host": "python", "version": "3.9"},
        "entry": {"type": "dyn", "path": "tools/%s.dyn" % task_id},
        "inputs": [
            {"name": "target_folder", "type": "dir", "role": "target_models", "required": True,
             "dyn_index": 0, "file_pattern": "*.rvt"},
            {"name": "write", "type": "bool", "role": "write_switch", "required": True,
             "default": False, "dyn_index": 1},
        ],
        "outputs": [{"name": "report", "kind": "report", "location": "staging", "overwrite_policy": "staging_only"}],
        "dependencies": {"requires": list(requires), "after": [], "conflicts_with": list(conflicts)},
        "execution_mode": {
            "scope": "folder", "batch": True, "supports_dry_run": True, "default_mode": "dry_run",
            "modifies_models": True, "write_requires_approval": True, "filename_guard": None,
            "dry_run_side_effects": [], "auto_run": False,
        },
        "requires_backup": True,
        "verification": {"unit_tests": [], "real_run": {"status": "unverified", "evidence": []},
                         "result_contract": "v1"},
    }


def snapshot(folder):
    """{name: (sha256, mtime_ns)} for every file in folder (recursive)."""
    state = {}
    for base, _, names in os.walk(folder):
        for name in names:
            full = os.path.join(base, name)
            state[os.path.relpath(full, folder)] = (atomic.sha256_file(full), os.stat(full).st_mtime_ns)
    return state


class Sandbox(object):
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="bbcc_test_")
        self.root = self._tmp.name
        self.repo = os.path.join(self.root, "repo")
        self.runs_root = os.path.join(self.root, "runs_root")
        self.models = os.path.join(self.root, "models")
        for folder in (self.repo, self.models, os.path.join(self.repo, "contracts")):
            os.makedirs(folder)
        for name, data in MODEL_FILES.items():
            with open(os.path.join(self.models, name), "wb") as handle:
                handle.write(data)

    def cleanup(self):
        self._tmp.cleanup()

    def write_contract(self, data, name=None):
        path = os.path.join(self.repo, "contracts", name or "%s.task.json" % data["task_id"])
        with open(path, "wb") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        entry = os.path.join(self.repo, *data["entry"]["path"].split("/"))
        if not os.path.exists(entry) and ".." not in data["entry"]["path"]:
            os.makedirs(os.path.dirname(entry), exist_ok=True)
            with open(entry, "wb") as handle:
                handle.write(b'{"fake": "%s"}' % data["task_id"].encode("ascii"))
        return path

    def registry(self, *specs):
        """specs: task_id or (task_id, requires, conflicts)."""
        reg = {}
        for spec in specs:
            if isinstance(spec, str):
                spec = (spec, (), ())
            data = contract_dict(*spec)
            reg[data["task_id"]] = contracts.load_contract(self.write_contract(data))
        return reg

    def register(self, data):
        """Load a custom contract dict and return a one-entry registry."""
        return {data["task_id"]: contracts.load_contract(self.write_contract(data))}

    def options(self, **kwargs):
        kwargs.setdefault("environ", {})
        kwargs.setdefault("host", HOST)
        return controller.Options(**kwargs)

    def run(self, registry, selected, mode="dry_run", runner=None, options=None, extra_inputs=None, **kwargs):
        inputs = dict((t, {"target_folder": self.models}) for t in registry)
        for task_id, values in (extra_inputs or {}).items():
            inputs[task_id].update(values)
        return controller.execute(registry, selected, inputs, mode, self.runs_root, self.repo,
                                  runner or controller.FakeRunner(), options=options or self.options(),
                                  **kwargs)

    def result(self, summary, task_id):
        return atomic.read_json_strict(os.path.join(summary.run_dir, "results", "%s.result.json" % task_id))


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)


def valid_result(**changes):
    doc = {
        "result_version": "1.0", "task_id": "t1", "task_version": "1.0.0",
        "run_id": "20261111-093000-abcdef12", "run_nonce": "a" * 32, "input_fingerprint": "b" * 64,
        "mode": "write", "status": "success", "written_by": "task",
        "started_at": "2026-11-11T09:30:00+08:00", "finished_at": "2026-11-11T09:31:00+08:00",
        "input_files": [{"path": "s-esc-01.rvt", "sha256": "c" * 64, "size": 3}],
        "output_files": [{"path": "report.txt", "sha256": "d" * 64, "size": 2}],
        "items_processed": 2, "items_modified": 1, "errors": [], "warnings": [],
        "skip_reason": None, "failure_class": None, "verified_by_controller": False, "halted_run": False,
    }
    doc = copy.deepcopy(doc)
    doc.update(changes)
    return doc


def override(**fields):
    """Fake runner behaviour: normal outputs, then replace result fields."""
    def behaviour(job, stop_event):
        controller.write_task_result(job, outputs=[("report.txt", b"ok")], overrides=fields)
        return controller.RunnerOutcome(exit_code=0)
    return behaviour

