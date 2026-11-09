"""Write findings to a CSV file that opens correctly in Excel (UTF-8 with BOM)."""
import csv
import os
import uuid
from datetime import datetime
from typing import Iterable, Optional

from core import TOOL_VERSION
from core.findings import Finding

COLUMNS = ("tool_version", "run_time", "model_file", "element_id", "check", "result", "reason")

# Excel runs a cell that starts with one of these as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str) -> str:
    """Prefix text that Excel would treat as a formula with an apostrophe."""
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def write_findings_csv(
    path: str,
    findings: Iterable[Finding],
    model_file: str,
    run_time: Optional[datetime] = None,
    tool_version: str = TOOL_VERSION,
) -> int:
    """Write one row per finding and return the row count.

    The file is written to a temporary name first and then renamed, so a failed
    run never leaves a half-written or overwritten report behind.
    """
    rows = list(findings)
    for f in rows:
        if not isinstance(f, Finding):
            raise TypeError("expected Finding, got %r" % (f,))
    if not isinstance(model_file, str) or not model_file.strip():
        raise ValueError("model_file must be a non-empty string")
    if run_time is None:
        run_time = datetime.now().astimezone()
    if run_time.tzinfo is None:
        raise ValueError("run_time must be timezone-aware")

    stamp = run_time.isoformat(timespec="seconds")
    model_name = os.path.basename(model_file)
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(COLUMNS)
            for f in rows:
                writer.writerow([
                    safe_text(tool_version),
                    stamp,
                    safe_text(model_name),
                    "" if f.element_id is None else str(f.element_id),
                    safe_text(f.check),
                    f.status.value,
                    safe_text(f.reason),
                ])
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return len(rows)
