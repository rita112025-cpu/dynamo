"""Task contract loading, semantic checks and the MVP plan check.

MVP planning (r2-final 6.2): tasks run in the order the caller gives. A task's
`requires` entries must be selected and placed earlier; `conflicts_with` pairs
must not be selected together. Topological sorting, `after` and any_of are M1-C.
"""
import ntpath
import os
import re
from typing import Dict, List, Sequence

from . import atomic, schema_check

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")
_DRIVE = re.compile(r"^[A-Za-z]:")


class ContractError(ValueError):
    def __init__(self, source: str, problems: List[str]):
        self.source = source
        self.problems = list(problems)
        super().__init__("%s: %s" % (source, "; ".join(self.problems)))


class PlanError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__("%s: %s" % (code, message))


def load_schema(name: str) -> dict:
    schema = atomic.read_json_strict(os.path.join(SCHEMA_DIR, name))
    unknown = schema_check.unsupported_keywords(schema)
    if unknown:
        raise ValueError("schema %s uses keywords the validator does not support: %s" % (name, unknown))
    return schema


class TaskContract(object):
    """A validated task contract. `data` is the parsed JSON; `sha256` hashes the file bytes."""

    def __init__(self, data: dict, source: str, sha256: str):
        self.data = data
        self.source = source
        self.sha256 = sha256

    task_id = property(lambda self: self.data["task_id"])
    task_version = property(lambda self: self.data["task_version"])
    inputs = property(lambda self: self.data["inputs"])
    entry_path = property(lambda self: self.data["entry"]["path"])
    requires = property(lambda self: self.data["dependencies"]["requires"])
    conflicts_with = property(lambda self: self.data["dependencies"]["conflicts_with"])
    modifies_models = property(lambda self: self.data["execution_mode"]["modifies_models"])
    requires_backup = property(lambda self: self.data["requires_backup"])


def _bad_relative_path(path: str) -> bool:
    if not path or _DRIVE.match(path) or path[0] in "\\/" or ":" in path:
        return True
    return any(part == ".." for part in re.split(r"[\\/]", path))


def semantic_problems(data: dict) -> List[str]:
    problems = []
    entry = data["entry"]
    for key in ("path", "source"):
        if key in entry and _bad_relative_path(entry[key]):
            problems.append("entry.%s must be a repository-relative path without '..' or a drive" % key)
    inputs = data["inputs"]
    names = [i["name"] for i in inputs]
    if len(set(names)) != len(names):
        problems.append("inputs: duplicate name")
    indexes = [i["dyn_index"] for i in inputs if "dyn_index" in i]
    if len(set(indexes)) != len(indexes):
        problems.append("inputs: duplicate dyn_index")
    if entry["type"] == "dyn" and any("dyn_index" not in i for i in inputs):
        problems.append("inputs: every input of a dyn entry needs dyn_index")
    for item in inputs:
        if item["type"] == "enum" and not item.get("choices"):
            problems.append("inputs.%s: enum needs choices" % item["name"])
    switches = [i for i in inputs if i["role"] == "write_switch"]
    if len(switches) > 1:
        problems.append("inputs: more than one write_switch")
    for switch in switches:
        if switch["type"] != "bool" or switch.get("default", False) is not False:
            problems.append("inputs.%s: write_switch must be bool with default false" % switch["name"])
    mode = data["execution_mode"]
    if mode["modifies_models"]:
        if not data["requires_backup"]:
            problems.append("requires_backup must be true when execution_mode.modifies_models is true")
        if not mode["write_requires_approval"]:
            problems.append("write_requires_approval must be true when modifies_models is true")
        if not switches:
            problems.append("a task that modifies models needs one write_switch input")
    deps = data["dependencies"]
    for key in ("requires", "after", "conflicts_with"):
        if data["task_id"] in deps[key]:
            problems.append("dependencies.%s refers to the task itself" % key)
    real = data["verification"]["real_run"]
    if real["status"] in ("documented", "verified") and not real["evidence"]:
        problems.append("verification.real_run.evidence is required when status is %s" % real["status"])
    return problems


def validate_contract_data(data, source: str = "<contract>") -> None:
    errors = schema_check.validate(data, load_schema("task_contract.schema.json"))
    if errors:
        raise ContractError(source, errors)
    problems = semantic_problems(data)
    if problems:
        raise ContractError(source, problems)


def load_contract(path: str) -> TaskContract:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        data = atomic.read_json_strict(path)
    except (OSError, ValueError) as exc:
        raise ContractError(path, ["cannot read contract: %s" % exc])
    validate_contract_data(data, path)
    return TaskContract(data, path, atomic.sha256_bytes(raw))


def make_plan(contracts: Dict[str, TaskContract], selected: Sequence[str]) -> List[str]:
    """Validate the selection and return the run order (caller order, duplicates removed)."""
    order = []
    for task_id in selected:
        if task_id not in contracts:
            raise PlanError("UNKNOWN_TASK", "task '%s' is not registered" % task_id)
        if task_id not in order:
            order.append(task_id)
    chosen = set(order)
    for task_id in order:
        for other in contracts[task_id].conflicts_with:
            if other in chosen:
                raise PlanError("CONFLICT", "'%s' and '%s' cannot run in the same batch" % (task_id, other))
    for position, task_id in enumerate(order):
        for dep in contracts[task_id].requires:
            if dep not in chosen:
                raise PlanError("dependency_not_selected",
                                "'%s' requires '%s', which is not selected" % (task_id, dep))
            if order.index(dep) > position:
                raise PlanError("dependency_order", "'%s' must run after '%s'" % (task_id, dep))
    return order


def normalize_windows_path(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))
