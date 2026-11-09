"""Element snapshot: the contract between a (future) Revit reader and the pure-Python checks.

See docs/snapshot_format.md. This module only validates data; it never touches Revit.
"""
import json
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
_ELEMENT_KEYS = ("element_id", "category", "family_name", "parameters", "read_error")


class SnapshotError(ValueError):
    """The snapshot does not follow the contract."""


def validate_elements(elements: Any) -> List[Dict[str, Any]]:
    """Return a validated copy of the element list or raise SnapshotError.

    Element: {element_id: int, category: str, family_name: str|None,
              parameters: {name: str|None}, read_error: str|None (optional)}
    `None` for a parameter value means "no such parameter, or it is read-only".
    A non-empty `read_error` means the element could not be read at all.
    """
    if not isinstance(elements, list):
        raise SnapshotError("elements must be a list")
    out: List[Dict[str, Any]] = []
    seen = set()
    for n, e in enumerate(elements):
        where = "element #%d" % n
        if not isinstance(e, dict):
            raise SnapshotError("%s must be an object" % where)
        extra = sorted(set(e) - set(_ELEMENT_KEYS))
        if extra:
            raise SnapshotError("%s has unknown key(s): %s" % (where, ", ".join(extra)))
        eid = e.get("element_id")
        if isinstance(eid, bool) or not isinstance(eid, int):
            raise SnapshotError("%s: element_id must be an int, got %r" % (where, eid))
        where = "element %d" % eid
        if eid in seen:
            raise SnapshotError("%s: duplicate element_id" % where)
        seen.add(eid)
        category = e.get("category")
        if not isinstance(category, str) or not category.strip():
            raise SnapshotError("%s: category must be a non-empty string" % where)
        family = e.get("family_name")
        if family is not None and not isinstance(family, str):
            raise SnapshotError("%s: family_name must be a string or null" % where)
        params = e.get("parameters")
        if not isinstance(params, dict):
            raise SnapshotError("%s: parameters must be an object" % where)
        for name, value in params.items():
            if not isinstance(name, str) or not name:
                raise SnapshotError("%s: parameter names must be non-empty strings" % where)
            if value is not None and not isinstance(value, str):
                raise SnapshotError("%s: parameter %r must be a string or null, got %r" % (where, name, value))
        err = e.get("read_error")
        if err is not None and (not isinstance(err, str) or not err.strip()):
            raise SnapshotError("%s: read_error must be a non-empty string or null" % where)
        out.append({
            "element_id": eid,
            "category": category,
            "family_name": family,
            "parameters": dict(params),
            "read_error": err,
        })
    return out


def parse_snapshot(data: Any) -> Tuple[str, List[Dict[str, Any]]]:
    """Validate a whole snapshot document; return (source_file, elements)."""
    if not isinstance(data, dict):
        raise SnapshotError("snapshot must be an object")
    extra = sorted(set(data) - {"schema_version", "source_file", "elements"})
    if extra:
        raise SnapshotError("snapshot has unknown key(s): %s" % ", ".join(extra))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError("schema_version must be %d" % SCHEMA_VERSION)
    source = data.get("source_file")
    if not isinstance(source, str) or not source.strip():
        raise SnapshotError(
            "source_file must be the SOURCE path asked to open (never doc.PathName of a "
            "detached document, which is empty)"
        )
    return source, validate_elements(data.get("elements"))


def load_snapshot(path: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Read a snapshot JSON file (UTF-8) and validate it."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except ValueError as ex:
        raise SnapshotError("%s is not valid JSON: %s" % (path, ex)) from ex
    return parse_snapshot(data)
