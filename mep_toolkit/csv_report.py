"""Write findings (and per-check scope) to CSV files that open correctly in Excel
(UTF-8 with BOM)."""
import csv
import os
import uuid
from collections import Counter
from datetime import datetime
from typing import Iterable, List, Optional, Sequence

from mep_toolkit import TOOL_VERSION
from mep_toolkit.findings import CheckScope, Finding, Status

COLUMNS = ("tool_version", "run_time", "model_file", "element_id", "check", "result", "reason")
SCOPE_COLUMNS = ("tool_version", "run_time", "model_file", "check", "examined",
                 "pass", "fail", "unverified", "note")

# Excel runs a cell that starts with one of these as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str) -> str:
    """Prefix text that Excel would treat as a formula with an apostrophe.

    Excel then shows the apostrophe. Strip a leading apostrophe when reading a
    report back (see README).
    """
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _prepare(model_file: str, run_time: Optional[datetime]):
    """Validate the shared arguments; return (model name for the CSV, ISO time stamp).

    `model_file` must be the SOURCE path the caller asked to open. Do not read it
    back from the opened document: a document opened detached (for example with
    DetachAndPreserveWorksets) has an empty `doc.PathName`.
    """
    if not isinstance(model_file, str) or not model_file.strip():
        raise ValueError("model_file must be a non-empty string")
    if run_time is None:
        run_time = datetime.now().astimezone()
    if run_time.tzinfo is None:
        raise ValueError("run_time must be timezone-aware")
    # Split on both separators: the path may be a Windows path read on any OS.
    name = model_file.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return name, run_time.isoformat(timespec="seconds")


def _write_rows(path: str, header: Sequence[str], rows: List[List[str]]) -> None:
    """Write to a temporary name first and rename, so a failed run never leaves a
    half-written file or overwrites an existing report."""
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
        try:
            os.replace(tmp, path)
        except PermissionError as ex:
            raise PermissionError(
                ex.errno,
                "cannot replace the report - is it open in Excel? Close it and run again. "
                "The previous report is unchanged",
                path,
            ) from ex
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _check_complete(check: str, examined: int, results: List[Finding]) -> None:
    """Raise ValueError unless `results` cover exactly `examined` units, once each."""
    if not results:
        if examined != 0:
            raise ValueError(
                "check %r says it examined %d but sent no results; send one Finding per "
                "examined element" % (check, examined)
            )
        return
    model_level = [f for f in results if f.element_id is None]
    if model_level and len(model_level) != len(results):
        raise ValueError("check %r mixes element-level and model-level results" % check)
    if model_level:
        if len(results) != 1 or examined != 1:
            raise ValueError(
                "model-level check %r needs exactly 1 result and examined = 1 "
                "(got %d results, examined %d)" % (check, len(results), examined)
            )
        return
    ids = [f.element_id for f in results]
    if len(set(ids)) != len(ids):
        dup = sorted(i for i, n in Counter(ids).items() if n > 1)[:5]
        raise ValueError(
            "check %r has more than one result for element(s) %s; "
            "use one Finding per element per check" % (check, dup)
        )
    if len(ids) != examined:
        raise ValueError(
            "check %r: examined count %d does not match result count %d; every examined "
            "element needs exactly one Finding" % (check, examined, len(ids))
        )


def write_findings_csv(
    path: str,
    findings: Iterable[Finding],
    model_file: str,
    run_time: Optional[datetime] = None,
    tool_version: str = TOOL_VERSION,
) -> int:
    """Write one row per finding and return the row count."""
    items = list(findings)
    for f in items:
        if not isinstance(f, Finding):
            raise TypeError("expected Finding, got %r" % (f,))
    name, stamp = _prepare(model_file, run_time)
    rows = [
        [
            safe_text(tool_version),
            stamp,
            safe_text(name),
            "" if f.element_id is None else str(f.element_id),
            safe_text(f.check),
            f.status.value,
            safe_text(f.reason),
        ]
        for f in items
    ]
    _write_rows(path, COLUMNS, rows)
    return len(rows)


def write_scope_csv(
    path: str,
    scopes: Iterable[CheckScope],
    findings: Iterable[Finding],
    model_file: str,
    run_time: Optional[datetime] = None,
    tool_version: str = TOOL_VERSION,
) -> int:
    """Write one row per check for ONE model and return the row count.

    Every examined element needs exactly one Finding, so pass + fail + unverified
    always equals `examined`. "No result" is never counted as PASS.

    Refuses (nothing is written) when the scope and the findings disagree:
    - a finding whose check has no scope, or two scopes for the same check,
    - an element-level check whose number of results differs from `examined`
      (missing results, or the same element twice),
    - a model-level check (element_id None) that does not have exactly one
      result and `examined == 1`,
    - a check that mixes element-level and model-level results,
    - `examined > 0` with no results at all.
    """
    scope_list = list(scopes)
    finding_list = list(findings)
    for s in scope_list:
        if not isinstance(s, CheckScope):
            raise TypeError("expected CheckScope, got %r" % (s,))
    for f in finding_list:
        if not isinstance(f, Finding):
            raise TypeError("expected Finding, got %r" % (f,))

    by_check = {}
    for s in scope_list:
        if s.check in by_check:
            raise ValueError("duplicate scope for check %r" % s.check)
        by_check[s.check] = s

    grouped = {c: [] for c in by_check}
    counts = {c: Counter() for c in by_check}
    for f in finding_list:
        if f.check not in by_check:
            raise ValueError("finding for check %r has no scope" % f.check)
        grouped[f.check].append(f)
        counts[f.check][f.status] += 1

    for c, s in by_check.items():
        _check_complete(c, s.examined, grouped[c])

    name, stamp = _prepare(model_file, run_time)
    rows = [
        [
            safe_text(tool_version),
            stamp,
            safe_text(name),
            safe_text(s.check),
            str(s.examined),
            str(counts[s.check][Status.PASS]),
            str(counts[s.check][Status.FAIL]),
            str(counts[s.check][Status.UNVERIFIED]),
            safe_text(s.note),
        ]
        for s in scope_list
    ]
    _write_rows(path, SCOPE_COLUMNS, rows)
    return len(rows)
