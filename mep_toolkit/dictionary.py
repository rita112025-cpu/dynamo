"""Parameter dictionary: which parameters each category must carry, and the legal values.

The dictionary is a JSON file (see config/parameter_dictionary.json). `validate_dictionary`
rejects anything ambiguous so a typo can never silently disable a check.
"""
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Categories the toolkit knows how to check (BuiltInCategory names).
KNOWN_CATEGORIES = (
    "OST_Conduit",
    "OST_ConduitFitting",
    "OST_CableTray",
    "OST_CableTrayFitting",
    "OST_ElectricalEquipment",
    "OST_ElectricalFixtures",
    "OST_Wire",
)


class DictionaryError(ValueError):
    """The parameter dictionary is malformed."""


@dataclass(frozen=True)
class ParamRule:
    parameter: str
    allowed: Tuple[str, ...]


@dataclass(frozen=True)
class CategoryRule:
    key: str
    label: str
    required: Tuple[ParamRule, ...]


@dataclass(frozen=True)
class RackRule:
    category: str
    family_name_contains: str
    family_name_prefix: str
    code_parameter: Optional[str]
    required_parameters: Tuple[str, ...]
    non_empty_parameters: Tuple[str, ...]
    pending_confirmation: Tuple[Tuple[str, str], ...]  # (parameter, reason); NOT checked


@dataclass(frozen=True)
class Dictionary:
    categories: Tuple[CategoryRule, ...]
    rack: RackRule


def _reject_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise DictionaryError("duplicate key %r in dictionary file" % key)
        seen[key] = value
    return seen


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DictionaryError("%s must be a non-empty string" % what)
    if value != value.strip():
        raise DictionaryError("%s has leading or trailing spaces: %r" % (what, value))
    return value


def _text_list(value: Any, what: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise DictionaryError("%s must be a non-empty list" % what)
    items = [_text(v, "%s item" % what) for v in value]
    if len(set(items)) != len(items):
        raise DictionaryError("%s has duplicate entries" % what)
    return tuple(items)


def _only_keys(obj: Any, allowed: Tuple[str, ...], what: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise DictionaryError("%s must be an object" % what)
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise DictionaryError("%s has unknown key(s): %s" % (what, ", ".join(extra)))
    return obj


def validate_dictionary(data: Any) -> Dictionary:
    """Return a Dictionary or raise DictionaryError."""
    top = _only_keys(data, ("schema_version", "sources", "categories", "rack"), "dictionary")
    if top.get("schema_version") != 1:
        raise DictionaryError("schema_version must be 1")
    cats_raw = top.get("categories")
    if not isinstance(cats_raw, dict) or not cats_raw:
        raise DictionaryError("categories must be a non-empty object")

    categories: List[CategoryRule] = []
    for key, raw in cats_raw.items():
        if key not in KNOWN_CATEGORIES:
            raise DictionaryError("unknown category %r (known: %s)" % (key, ", ".join(KNOWN_CATEGORIES)))
        obj = _only_keys(raw, ("label", "required"), "category %s" % key)
        label = _text(obj.get("label"), "category %s label" % key)
        req_raw = obj.get("required")
        if not isinstance(req_raw, list) or not req_raw:
            raise DictionaryError("category %s: required list must not be empty" % key)
        rules: List[ParamRule] = []
        for r in req_raw:
            ro = _only_keys(r, ("parameter", "allowed"), "category %s required item" % key)
            name = _text(ro.get("parameter"), "category %s parameter" % key)
            allowed = _text_list(ro.get("allowed"), "category %s parameter %s allowed" % (key, name))
            rules.append(ParamRule(name, allowed))
        names = [r.parameter for r in rules]
        if len(set(names)) != len(names):
            raise DictionaryError("category %s: duplicate required parameter" % key)
        categories.append(CategoryRule(key, label, tuple(rules)))

    rack_raw = _only_keys(
        top.get("rack"),
        ("category", "family_name_contains", "family_name_prefix", "code_parameter",
         "required_parameters", "non_empty_parameters", "pending_confirmation"),
        "rack",
    )
    category = _text(rack_raw.get("category"), "rack category")
    if category not in cats_raw:
        raise DictionaryError("rack category %r is not a configured category" % category)
    contains = _text(rack_raw.get("family_name_contains"), "rack family_name_contains")
    prefix = _text(rack_raw.get("family_name_prefix"), "rack family_name_prefix")
    if not prefix.startswith(contains):
        raise DictionaryError("rack family_name_prefix must start with family_name_contains")
    required = _text_list(rack_raw.get("required_parameters"), "rack required_parameters")
    non_empty_raw = rack_raw.get("non_empty_parameters")
    non_empty = _text_list(non_empty_raw, "rack non_empty_parameters") if non_empty_raw else ()
    missing = [p for p in non_empty if p not in required]
    if missing:
        raise DictionaryError("rack non_empty_parameters not in required_parameters: %s" % missing)
    code = rack_raw.get("code_parameter")
    if code is not None:
        code = _text(code, "rack code_parameter")
        if code not in required:
            raise DictionaryError("rack code_parameter %r must be in required_parameters" % code)
    pending: List[Tuple[str, str]] = []
    for item in rack_raw.get("pending_confirmation") or []:
        po = _only_keys(item, ("parameter", "reason"), "rack pending_confirmation item")
        name = _text(po.get("parameter"), "pending parameter")
        if name in required:
            raise DictionaryError("pending parameter %r is also required" % name)
        pending.append((name, _text(po.get("reason"), "pending reason for %s" % name)))
    if len({p for p, _ in pending}) != len(pending):
        raise DictionaryError("rack pending_confirmation has duplicate parameters")

    return Dictionary(
        tuple(categories),
        RackRule(category, contains, prefix, code, required, non_empty, tuple(pending)),
    )


def load_dictionary(path: str) -> Dictionary:
    """Read and validate a dictionary file (UTF-8)."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh, object_pairs_hook=_reject_duplicate_keys)
    except ValueError as ex:  # includes JSONDecodeError and DictionaryError
        if isinstance(ex, DictionaryError):
            raise
        raise DictionaryError("%s is not valid JSON: %s" % (path, ex)) from ex
    return validate_dictionary(data)
