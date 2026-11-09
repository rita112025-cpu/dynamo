"""Write findings (and per-check scope) to CSV files that open correctly in Excel
(UTF-8 with BOM).

Writers validate everything before touching the disk. Several reports are written as one
unit by `write_reports_atomic`: either all of them end up new, or all of them end up as they
were before (see that function for the exact steps and their limits).
"""
import csv
import os
import uuid
from collections import Counter
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from mep_toolkit import TOOL_VERSION
from mep_toolkit.findings import CheckScope, Finding, Status

COLUMNS = ("tool_version", "run_time", "model_file", "element_id", "check", "result", "reason")
SCOPE_COLUMNS = ("tool_version", "run_time", "model_file", "check", "examined",
                 "pass", "fail", "unverified", "note")

# Excel runs a cell that starts with one of these as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_LOCKED_HINT = ("cannot replace or move the report - is it open in Excel? Close it and run again. "
                "The reports were left as they were before")


def safe_text(value: str) -> str:
    """Prefix text that Excel would treat as a formula with an apostrophe.

    Excel then shows the apostrophe. Strip a leading apostrophe when reading a
    report back (see README).
    """
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _prepare(model_file: str, run_time: Optional[datetime]) -> Tuple[str, str]:
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


def build_findings_rows(findings: Iterable[Finding], model_file: str,
                        run_time: Optional[datetime] = None,
                        tool_version: str = TOOL_VERSION) -> List[List[str]]:
    """Validate the findings and return the CSV rows (without the header)."""
    items = list(findings)
    for f in items:
        if not isinstance(f, Finding):
            raise TypeError("expected Finding, got %r" % (f,))
    name, stamp = _prepare(model_file, run_time)
    return [
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


def build_scope_rows(scopes: Iterable[CheckScope], findings: Iterable[Finding], model_file: str,
                     run_time: Optional[datetime] = None,
                     tool_version: str = TOOL_VERSION) -> List[List[str]]:
    """Validate scopes against findings and return the CSV rows (without the header).

    Every examined element needs exactly one Finding, so pass + fail + unverified always
    equals `examined`. "No result" is never counted as PASS. Refuses (nothing is written):
    - a finding whose check has no scope, or two scopes for the same check,
    - an element-level check whose number of results differs from `examined`,
    - a model-level check (element_id None) that does not have exactly one result and examined 1,
    - a check that mixes element-level and model-level results,
    - examined > 0 with no results at all.
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
    return [
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


def _replace(src: str, dst: str, report: str) -> None:
    """os.replace with a clear message; `report` names the user's file in the error."""
    try:
        os.replace(src, dst)
    except PermissionError as ex:
        raise PermissionError(ex.errno or 13, _LOCKED_HINT, report) from ex


def _rollback(replaced: List[str], backups: List[Tuple[str, str]], cause: BaseException) -> None:
    """Undo a partial write: drop the new files that were put in place, then restore the backups.

    Raises RuntimeError naming every file that could not be put back, so nothing is silently wrong.
    """
    problems = []
    for path in reversed(replaced):
        try:
            os.remove(path)
        except OSError as ex:
            problems.append("%s: could not remove the new file (%s)" % (path, ex))
    for path, bak in reversed(backups):
        try:
            if os.path.exists(bak):
                os.replace(bak, path)
        except OSError as ex:
            problems.append("%s: could not restore the old file from %s (%s)" % (path, bak, ex))
    if problems:
        raise RuntimeError(
            "report rollback incomplete after: %s. Check these files by hand: %s"
            % (cause, "; ".join(problems))
        ) from cause


def write_reports_atomic(outputs: Sequence[Tuple[str, Sequence[str], List[List[str]]]]) -> None:
    """Write several CSV reports as one unit.

    Steps:
      1. Write every new content to its own temporary file. Final paths are not touched yet.
      2. Move each existing final file aside to a backup name. A locked file fails here.
      3. Put each temporary file in place. If any step fails, undo everything: remove new
         files that were put in place and move the backups back. Afterwards every report is
         either entirely the old one or entirely the new one.
      4. On success delete the backups.

    Limit: if the rollback itself fails, RuntimeError names the file that must be checked by hand.
    """
    targets = [os.path.normcase(os.path.abspath(p)) for p, _, _ in outputs]
    if len(set(targets)) != len(targets):
        raise ValueError("the same report path appears more than once")
    temps: List[Tuple[str, str]] = []
    backups: List[Tuple[str, str]] = []
    replaced: List[str] = []
    try:
        for path, header, rows in outputs:
            tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
            temps.append((path, tmp))
            with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                writer.writerows(rows)
        for path, _, _ in outputs:
            if os.path.exists(path):
                bak = "%s.%s.bak" % (path, uuid.uuid4().hex[:8])
                _replace(path, bak, path)
                backups.append((path, bak))
        for path, tmp in temps:
            _replace(tmp, path, path)
            replaced.append(path)
    except BaseException as ex:
        _rollback(replaced, backups, ex)
        raise
    finally:
        for _, tmp in temps:
            if os.path.exists(tmp):
                os.remove(tmp)
    for _, bak in backups:
        if os.path.exists(bak):
            try:
                os.remove(bak)
            except OSError as ex:
                raise RuntimeError(
                    "reports were written, but the backup %s could not be deleted (%s); "
                    "delete it by hand" % (bak, ex)
                ) from ex


def write_findings_csv(
    path: str,
    findings: Iterable[Finding],
    model_file: str,
    run_time: Optional[datetime] = None,
    tool_version: str = TOOL_VERSION,
) -> int:
    """Write one row per finding and return the row count."""
    rows = build_findings_rows(findings, model_file, run_time, tool_version)
    write_reports_atomic([(path, COLUMNS, rows)])
    return len(rows)


def write_scope_csv(
    path: str,
    scopes: Iterable[CheckScope],
    findings: Iterable[Finding],
    model_file: str,
    run_time: Optional[datetime] = None,
    tool_version: str = TOOL_VERSION,
) -> int:
    """Write one row per check for ONE model and return the row count."""
    rows = build_scope_rows(scopes, findings, model_file, run_time, tool_version)
    write_reports_atomic([(path, SCOPE_COLUMNS, rows)])
    return len(rows)
