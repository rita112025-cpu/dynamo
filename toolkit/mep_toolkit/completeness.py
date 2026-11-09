"""Parameter completeness check on element snapshots (pure Python, read-only).

Every examined element gets exactly one Finding per check, so the CSV scope rule holds.
Snapshot version 2 separates three states (see mep_toolkit/snapshot.py):
  - MISSING_PARAMETER -> FAIL
  - READ_ONLY         -> judged by its value: correct = PASS, wrong = FAIL (reason says the
                         batch tools cannot fix a read-only value)
  - UNREADABLE        -> UNVERIFIED
"""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from mep_toolkit import TOOL_VERSION
from mep_toolkit.csv_report import (COLUMNS, SCOPE_COLUMNS, build_findings_rows, build_scope_rows,
                                    write_reports_atomic)
from mep_toolkit.dictionary import Dictionary, ParamRule
from mep_toolkit.findings import CheckScope, Finding, Status
from mep_toolkit.snapshot import validate_elements

IDENT_CHECK_PREFIX = "SCADA識別_"
UNCOVERED_CHECK_PREFIX = "未涵蓋品類_"
RACK_PARAMS_CHECK = "機櫃_SCADA共用參數齊全"
RACK_NAME_CHECK = "機櫃_族群名稱規則"
READ_ONLY_TAG = "（唯讀，批次工具無法修正）"

# Same character set scada_racks.family_name refuses in a family file name.
_FAMILY_NAME_BAD = re.compile(r'[\\/:*?"<>|]')

# classify() results
MISSING, OK, FIXABLE, OTHER = "missing", "ok", "fixable", "other"
_DESCRIPTION = {MISSING: "為空（缺漏）", FIXABLE: "大小寫或空格不同", OTHER: "為其他值（保留他值）"}


def classify(current: Optional[str], allowed) -> str:
    """Same meaning as BatchFillScadaParams.decide(), for a list of legal values.

    missing  - empty or blank
    ok       - exactly one of the legal values
    fixable  - differs from a legal value only in case or leading/trailing spaces
    other    - any other value (the batch tools KEEP these; here they are reported)
    """
    cur = (current or "").strip()
    if cur == "":
        return MISSING
    if current in allowed:
        return OK
    upper = cur.upper()
    if any(upper == a.upper() for a in allowed):
        return FIXABLE
    return OTHER


@dataclass(frozen=True)
class CompletenessResult:
    findings: List[Finding]
    scopes: List[CheckScope]
    # category -> element count, for categories the dictionary does not cover.
    # They are NOT examined; the scope file records each one (examined = 0, with a note).
    ignored_categories: Dict[str, int]


def _rule_issue(rule: ParamRule, element: Dict[str, Any]) -> Optional[str]:
    name = rule.parameter
    params = element["parameters"]
    if name not in params:
        return "「%s」模型沒有此參數（MISSING_PARAMETER）" % name
    current = params[name]
    kind = classify(current, rule.allowed)
    if kind == OK:
        return None
    allowed = " / ".join(rule.allowed)
    if name in element["read_only_parameters"]:
        return "「%s」%s，現值 %r，應為 %s%s" % (name, _DESCRIPTION[kind], current, allowed, READ_ONLY_TAG)
    if kind == MISSING:
        return "「%s」為空（缺漏），應為 %s" % (name, allowed)
    if kind == FIXABLE:
        return "「%s」大小寫或空格不同（可修正）：現值 %r，應為 %s" % (name, current, allowed)
    return "「%s」為其他值（保留他值）：現值 %r，應為 %s" % (name, current, allowed)


def _result(check: str, element: Dict[str, Any], issues: List[str]) -> Finding:
    if issues:
        return Finding(check, Status.FAIL, element["element_id"], "；".join(issues))
    return Finding(check, Status.PASS, element["element_id"])


def _unreadable(check: str, element: Dict[str, Any]) -> Finding:
    return Finding(check, Status.UNVERIFIED, element["element_id"],
                   "讀取元件失敗（UNREADABLE），未檢查：%s" % element["read_error"])


def _is_rack(element: Dict[str, Any], dictionary: Dictionary) -> bool:
    rack = dictionary.rack
    family = element["family_name"]
    return (element["category"] == rack.category and isinstance(family, str)
            and rack.family_name_contains in family)


def _rack_params_issues(element: Dict[str, Any], dictionary: Dictionary) -> List[str]:
    rack = dictionary.rack
    params = element["parameters"]
    ro = element["read_only_parameters"]
    absent = [p for p in rack.required_parameters if p not in params]
    issues = []
    if absent:
        issues.append("模型沒有共用參數（MISSING_PARAMETER）：" + "、".join(absent))
    empty = []
    for p in rack.non_empty_parameters:
        if p in params and not params[p].strip():
            empty.append(p + (READ_ONLY_TAG if p in ro else ""))
    if empty:
        issues.append("必填值為空：" + "、".join(empty))
    return issues


def _rack_name_issues(element: Dict[str, Any], dictionary: Dictionary) -> List[str]:
    rack = dictionary.rack
    name = element["family_name"]
    if not name.startswith(rack.family_name_prefix):
        return ["族群名稱 %r 須以 %r 開頭" % (name, rack.family_name_prefix)]
    code = name[len(rack.family_name_prefix):]
    issues = []
    if not code or code != code.strip() or _FAMILY_NAME_BAD.search(code) or code.endswith("."):
        issues.append("族群名稱的編號部分 %r 不合法（不可為空、頭尾不可有空格、不可含 \\ / : * ? \" < > |、不可以 . 結尾）" % code)
    elif rack.code_parameter and rack.code_parameter in element["parameters"]:
        value = element["parameters"][rack.code_parameter]
        if value.strip() and value != code:
            issues.append("族群名稱的編號 %r 與 %s 的值 %r 不一致" % (code, rack.code_parameter, value))
    return issues


def check_completeness(elements: List[Dict[str, Any]], dictionary: Dictionary) -> CompletenessResult:
    """Run every completeness check over one model's snapshot."""
    elems = validate_elements(elements)
    findings: List[Finding] = []
    scopes: List[CheckScope] = []

    racks = [e for e in elems if _is_rack(e, dictionary)]
    rack_ids = {e["element_id"] for e in racks}

    for cat in dictionary.categories:
        check = IDENT_CHECK_PREFIX + cat.key
        group = [e for e in elems if e["category"] == cat.key and e["element_id"] not in rack_ids]
        for e in group:
            if e["read_error"]:
                findings.append(_unreadable(check, e))
                continue
            issues = [i for i in (_rule_issue(r, e) for r in cat.required) if i]
            findings.append(_result(check, e, issues))
        note = "" if group else "模型沒有 %s 元件，未檢查" % cat.key
        scopes.append(CheckScope(check, len(group), note))

    for check, issues_of in ((RACK_PARAMS_CHECK, _rack_params_issues), (RACK_NAME_CHECK, _rack_name_issues)):
        for e in racks:
            if e["read_error"]:
                findings.append(_unreadable(check, e))
            else:
                findings.append(_result(check, e, issues_of(e, dictionary)))
        note = "" if racks else "沒有族群名稱含 %s 的元件，未檢查" % dictionary.rack.family_name_contains
        scopes.append(CheckScope(check, len(racks), note))

    known = {c.key for c in dictionary.categories}
    ignored = Counter(e["category"] for e in elems if e["category"] not in known)
    for category, count in sorted(ignored.items()):
        scopes.append(CheckScope(
            UNCOVERED_CHECK_PREFIX + category, 0,
            "未涵蓋品類 %s：%d 個元件未檢查（品類不在參數字典內）" % (category, count)))
    return CompletenessResult(findings, scopes, dict(sorted(ignored.items())))


def write_completeness_reports(
    result: CompletenessResult,
    findings_path: str,
    scope_path: str,
    model_file: str,
    run_time: Optional[datetime] = None,
    tool_version: str = TOOL_VERSION,
) -> None:
    """Validate both reports completely, then write them as one unit (both new or both old).

    `model_file` is the SOURCE path asked to open, as in the CSV writers.
    """
    if run_time is None:
        run_time = datetime.now().astimezone()  # one time stamp for both files
    scope_rows = build_scope_rows(result.scopes, result.findings, model_file, run_time, tool_version)
    findings_rows = build_findings_rows(result.findings, model_file, run_time, tool_version)
    write_reports_atomic([
        (scope_path, SCOPE_COLUMNS, scope_rows),
        (findings_path, COLUMNS, findings_rows),
    ])
