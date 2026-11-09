"""Element snapshot, contract version 2: the contract between a (future) Revit reader and the
pure-Python checks. See docs/snapshot_format.md. This module only validates data; it never
touches Revit.

Version 2 separates three states that version 1 merged into `null`:
  - MISSING_PARAMETER : the parameter is not in `parameters` (the model has no such parameter)
  - READ_ONLY         : the parameter is in `parameters` AND its name is in `read_only_parameters`
  - UNREADABLE        : `read_error` is set (the element could not be read; `parameters` must be {})
"""
import json
from typing import Any, Dict, List, Tuple

SCHEMA_VERSION = 2
_ELEMENT_REQUIRED = ("element_id", "category", "family_name", "parameters", "read_only_parameters")
_ELEMENT_KEYS = _ELEMENT_REQUIRED + ("read_error",)
_DOCUMENT_KEYS = ("schema_version", "source_file", "elements")


class SnapshotError(ValueError):
    """The snapshot does not follow the contract."""


def _is_int(value: Any) -> bool:
    # bool is a subclass of int, and 1.0 == 1: reject both explicitly.
    return isinstance(value, int) and not isinstance(value, bool)


def validate_elements(elements: Any) -> List[Dict[str, Any]]:
    """Return a validated copy of the element list or raise SnapshotError.

    Element (all required keys must be present; `read_error` may be omitted):
      element_id           int, unique in the snapshot
      category             non-empty string (BuiltInCategory name)
      family_name          string, or null when the element has no family
      parameters           object: name -> string. A parameter that is absent from the model
                           is simply NOT a key. Blank is "". `null` is not allowed in v2.
      read_only_parameters list of names; each must be a key of `parameters`, no duplicates
      read_error           omitted/null, or a non-empty string = the element could not be read.
                           Then `parameters` and `read_only_parameters` must be empty.
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
        missing = [k for k in _ELEMENT_REQUIRED if k not in e]
        if missing:
            raise SnapshotError("%s is missing key(s): %s" % (where, ", ".join(missing)))
        eid = e["element_id"]
        if not _is_int(eid):
            raise SnapshotError("%s: element_id must be an int, got %r" % (where, eid))
        where = "element %d" % eid
        if eid in seen:
            raise SnapshotError("%s: duplicate element_id" % where)
        seen.add(eid)
        category = e["category"]
        if not isinstance(category, str) or not category.strip():
            raise SnapshotError("%s: category must be a non-empty string" % where)
        family = e["family_name"]
        if family is not None and not isinstance(family, str):
            raise SnapshotError("%s: family_name must be a string or null" % where)
        params = e["parameters"]
        if not isinstance(params, dict):
            raise SnapshotError("%s: parameters must be an object" % where)
        for name, value in params.items():
            if not isinstance(name, str) or not name:
                raise SnapshotError("%s: parameter names must be non-empty strings" % where)
            if value is None:
                raise SnapshotError(
                    "%s: parameter %r is null; version 2 has no null values. Leave an absent "
                    "parameter out of `parameters`, and list a read-only one in read_only_parameters"
                    % (where, name))
            if not isinstance(value, str):
                raise SnapshotError("%s: parameter %r must be a string, got %r" % (where, name, value))
        ro = e["read_only_parameters"]
        if not isinstance(ro, list) or not all(isinstance(x, str) and x for x in ro):
            raise SnapshotError("%s: read_only_parameters must be a list of non-empty strings" % where)
        if len(set(ro)) != len(ro):
            raise SnapshotError("%s: read_only_parameters has duplicate names" % where)
        not_present = [x for x in ro if x not in params]
        if not_present:
            raise SnapshotError("%s: read_only_parameters not in parameters: %s" % (where, ", ".join(not_present)))
        err = e.get("read_error")
        if err is not None:
            if not isinstance(err, str) or not err.strip():
                raise SnapshotError("%s: read_error must be a non-empty string or null" % where)
            if params or ro:
                raise SnapshotError("%s: a read_error element must have empty parameters and "
                                    "read_only_parameters" % where)
        out.append({
            "element_id": eid,
            "category": category,
            "family_name": family,
            "parameters": dict(params),
            "read_only_parameters": list(ro),
            "read_error": err,
        })
    return out


def parse_snapshot(data: Any) -> Tuple[str, List[Dict[str, Any]]]:
    """Validate a whole snapshot document; return (source_file, elements)."""
    if not isinstance(data, dict):
        raise SnapshotError("snapshot must be an object")
    version = data.get("schema_version")
    if _is_int(version) and version == 1:
        raise SnapshotError(
            "schema_version 1 is not accepted: this toolkit needs version 2. Version 1 wrote null "
            "for both 'parameter absent' and 'read-only', which cannot be told apart. Re-export "
            "the snapshot as version 2 (with read_only_parameters).")
    extra = sorted(set(data) - set(_DOCUMENT_KEYS))
    if extra:
        raise SnapshotError("snapshot has unknown key(s): %s" % ", ".join(extra))
    missing = [k for k in _DOCUMENT_KEYS if k not in data]
    if missing:
        raise SnapshotError("snapshot is missing key(s): %s" % ", ".join(missing))
    if not _is_int(version) or version != SCHEMA_VERSION:
        raise SnapshotError("schema_version must be %d, got %r" % (SCHEMA_VERSION, version))
    source = data["source_file"]
    if not isinstance(source, str) or not source.strip():
        raise SnapshotError(
            "source_file must be the SOURCE path asked to open (never doc.PathName of a "
            "detached document, which is empty)"
        )
    return source, validate_elements(data["elements"])


def load_snapshot(path: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Read a snapshot JSON file (UTF-8) and validate it."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except ValueError as ex:
        raise SnapshotError("%s is not valid JSON: %s" % (path, ex)) from ex
    return parse_snapshot(data)
