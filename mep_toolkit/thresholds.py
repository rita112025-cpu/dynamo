"""Provisional thresholds (distances, heights) loaded from config/thresholds.json.

Every threshold carries status and source. A threshold whose status is 'provisional' is
reported as 暫定判定值 and must never be described as a compliance result.
"""
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

SCHEMA_VERSION = 1
STATUSES = ("provisional", "confirmed")
SOURCE_STATUSES = ("待核對原文", "已核對原文", "提案值，無原文依據")
KINDS = ("gap", "tolerance", "height")
COMPARISONS = ("<=", ">=")
HEIGHT_BASIS_ONLY = "bottom"  # this version: bottom face only; center/top are not allowed to mix in
PROVISIONAL_LABEL = "暫定判定值"

_REQUIRED = ("kind", "value", "unit", "comparison", "applies_to", "status", "source", "source_status")
_OPTIONAL = ("height_basis", "note")


class ThresholdError(ValueError):
    """The threshold file is malformed."""


@dataclass(frozen=True)
class Threshold:
    id: str
    kind: str
    value: float
    unit: str
    comparison: str
    applies_to: str
    status: str
    source: str
    source_status: str
    height_basis: Optional[str] = None
    note: str = ""

    @property
    def label(self) -> str:
        """Text that every report and reason must show next to the value."""
        return PROVISIONAL_LABEL if self.status == "provisional" else "已確認判定值"

    def satisfies(self, measured: float) -> bool:
        """True when `measured` meets the threshold's comparison (>= passes, <= passes)."""
        if not isinstance(measured, (int, float)) or isinstance(measured, bool) or not math.isfinite(measured):
            raise ValueError("measured value must be a finite number, got %r" % (measured,))
        return measured <= self.value if self.comparison == "<=" else measured >= self.value


def _only(obj: Any, allowed: Tuple[str, ...], what: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ThresholdError("%s must be an object" % what)
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise ThresholdError("%s has unknown key(s): %s" % (what, ", ".join(extra)))
    return obj


def _nonempty(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThresholdError("%s must be a non-empty string" % what)
    return value


def validate_thresholds(data: Any) -> Dict[str, Threshold]:
    top = _only(data, ("schema_version", "_note", "thresholds"), "thresholds file")
    version = top.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise ThresholdError("schema_version must be %d" % SCHEMA_VERSION)
    raw_all = top.get("thresholds")
    if not isinstance(raw_all, dict) or not raw_all:
        raise ThresholdError("thresholds must be a non-empty object")
    out: Dict[str, Threshold] = {}
    for tid, raw in raw_all.items():
        where = "threshold %s" % tid
        allowed = _REQUIRED + _OPTIONAL
        obj = _only(raw, allowed, where)
        missing = [k for k in _REQUIRED if k not in obj]
        if missing:
            raise ThresholdError("%s is missing: %s" % (where, ", ".join(missing)))
        kind = obj["kind"]
        if kind not in KINDS:
            raise ThresholdError("%s: kind %r not in %s" % (where, kind, ", ".join(KINDS)))
        value = obj["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ThresholdError("%s: value must be a positive finite number" % where)
        if obj["unit"] != "mm":
            raise ThresholdError("%s: unit must be 'mm'" % where)
        comparison = obj["comparison"]
        if comparison not in COMPARISONS:
            raise ThresholdError("%s: comparison %r not in %s" % (where, comparison, ", ".join(COMPARISONS)))
        status = obj["status"]
        if status not in STATUSES:
            raise ThresholdError("%s: status %r not in %s" % (where, status, ", ".join(STATUSES)))
        source_status = obj["source_status"]
        if source_status not in SOURCE_STATUSES:
            raise ThresholdError("%s: source_status %r not in %s" % (where, source_status, ", ".join(SOURCE_STATUSES)))
        if status == "confirmed" and source_status != "已核對原文":
            raise ThresholdError("%s: a confirmed threshold needs source_status 已核對原文" % where)
        height_basis = obj.get("height_basis")
        if kind == "height":
            if height_basis != HEIGHT_BASIS_ONLY:
                raise ThresholdError("%s: height threshold needs height_basis %r (this version uses the bottom face only)"
                                     % (where, HEIGHT_BASIS_ONLY))
            if comparison != ">=":
                raise ThresholdError("%s: height threshold must use '>=' (>= passes)" % where)
        elif height_basis is not None:
            raise ThresholdError("%s: height_basis is only for kind 'height'" % where)
        out[tid] = Threshold(
            id=tid,
            kind=kind,
            value=float(value),
            unit="mm",
            comparison=comparison,
            applies_to=_nonempty(obj["applies_to"], "%s applies_to" % where),
            status=status,
            source=_nonempty(obj["source"], "%s source" % where),
            source_status=source_status,
            height_basis=height_basis,
            note=obj.get("note", "") or "",
        )
    return out


def load_thresholds(path: str) -> Dict[str, Threshold]:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except ValueError as ex:
        raise ThresholdError("%s is not valid JSON: %s" % (path, ex)) from ex
    return validate_thresholds(data)
