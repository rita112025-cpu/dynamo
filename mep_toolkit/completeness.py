"""Parameter completeness check on element snapshots (pure Python, read-only).

Produces Findings and CheckScopes that satisfy the "exactly one Finding per examined
element per check" rule, so they can go straight into write_scope_csv.
"""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from mep_toolkit import TOOL_VERSION
from mep_toolkit.csv_report import write_findings_csv, write_scope_csv
from mep_toolkit.dictionary import Dictionary, ParamRule
from mep_toolkit.findings import CheckScope, Finding, Status
from mep_toolkit.snapshot import validate_elements

IDENT_CHECK_PREFIX = "SCADA識別_"
RACK_PARAMS_CHECK = "機櫃_SCADA共用參數齊全"
RACK_NAME_CHECK = "機櫃_族群名稱規則"

# Same character set scada_racks.family_name refuses in a family file name.
_FAMILY_NAME_BAD = re.compile(r'[\\/:*?"<>|]')

# classify() results
MISSING, OK, FIXABLE, OTHER = "missing", "ok", "fixable", "other"


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
    # These elements are NOT examined and have no Finding.
    ignored_categories: Dict[str, int]


def _rule_issue(rule: ParamRule, params: Dict[str, Optional[str]]) -> Optional[str]:
    if rule.parameter not in params or params[rule.parameter] is None:
        return "「%s」無此參數或為唯讀" % rule.parameter
    current = params[rule.parameter]
    kind = classify(current, rule.allowed)
    allowed = " / ".join(rule.allowed)
    if kind == OK:
        return None
    if kind == MISSING:
        return "「%s」為空（缺漏），應為 %s" % (rule.parameter, allowed)
    if kind == FIXABLE:
        return "「%s」大小寫或空格不同（可修正）：現值 %r，應為 %s" % (rule.parameter, current, allowed)
    return "「%s」為其他值（保留他值）：現值 %r，應為 %s" % (rule.parameter, current, allowed)


def _result(check: str, element: Dict[str, Any], issues: List[str]) -> Finding:
    if issues:
        return Finding(check, Status.FAIL, element["element_id"], "；".join(issues))
    return Finding(check, Status.PASS, element["element_id"])


def _unreadable(check: str, element: Dict[str, Any]) -> Finding:
    return Finding(check, Status.UNVERIFIED, element["element_id"],
                   "讀取元件失敗，未檢查：%s" % element["read_error"])


def _is_rack(element: Dict[str, Any], dictionary: Dictionary) -> bool:
    rack = dictionary.rack
    family = element["family_name"]
    return (element["category"] == rack.category and isinstance(family, str)
            and rack.family_name_contains in family)


def _rack_params_issues(element: Dict[str, Any], dictionary: Dictionary) -> List[str]:
    rack = dictionary.rack
    params = element["parameters"]
    absent = [p for p in rack.required_parameters if params.get(p) is None]
    issues = []
    if absent:
        issues.append("缺少共用參數（無此參數或唯讀）：" + "、".join(absent))
    empty = [p for p in rack.non_empty_parameters if params.get(p) is not None and not params[p].strip()]
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
    elif rack.code_parameter:
        value = element["parameters"].get(rack.code_parameter)
        if value is not None and value.strip() and value != code:
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
            issues = [i for i in (_rule_issue(r, e["parameters"]) for r in cat.required) if i]
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
    return CompletenessResult(findings, scopes, dict(sorted(ignored.items())))


def write_completeness_reports(
    result: CompletenessResult,
    findings_path: str,
    scope_path: str,
    model_file: str,
    run_time: Optional[datetime] = None,
    tool_version: str = TOOL_VERSION,
) -> None:
    """Write both CSVs through the standard writers (which enforce completeness).

    `model_file` is the SOURCE path asked to open, as in the CSV writers.
    """
    # Scope first: it validates completeness before anything is written.
    write_scope_csv(scope_path, result.scopes, result.findings, model_file, run_time, tool_version)
    write_findings_csv(findings_path, result.findings, model_file, run_time, tool_version)
