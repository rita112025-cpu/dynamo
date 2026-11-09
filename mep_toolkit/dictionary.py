"""Parameter dictionary: which parameters each category must carry, the legal values,
and the SCADA shared parameters (name, GUID, data type) read from the source file.

The dictionary is a JSON file (see config/parameter_dictionary.json). `validate_dictionary`
rejects anything ambiguous so a typo can never silently disable a check.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from mep_toolkit.shared_params import SharedFileError, SharedFile, parse_shared_bytes

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

GUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_DATA_TYPES = ("TEXT",)  # the only type in the source file (SCADA_SoW_V6)
# Basis of the rack rules. They are inferred from existing code, NOT confirmed by the owner.
BASIS_STATUS = "依既有程式推定，非業主確認"


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
class SharedParameter:
    name: str
    guid: str  # lower-case
    data_type: str


@dataclass(frozen=True)
class SharedBlock:
    source: str
    source_sha256: str
    group: str
    applies_to_category: str
    applies_to_family_contains: str
    parameters: Tuple[SharedParameter, ...]


@dataclass(frozen=True)
class Dictionary:
    categories: Tuple[CategoryRule, ...]
    rack: RackRule
    shared: SharedBlock


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


def _parse_shared(raw: Any) -> SharedBlock:
    obj = _only_keys(raw, ("source", "source_sha256", "group", "applies_to", "parameters"), "shared_parameters")
    source = _text(obj.get("source"), "shared_parameters source")
    sha = obj.get("source_sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        raise DictionaryError("shared_parameters source_sha256 must be 64 lower-case hex characters")
    group = _text(obj.get("group"), "shared_parameters group")
    applies = _only_keys(obj.get("applies_to"), ("category", "family_name_contains"), "shared_parameters applies_to")
    category = _text(applies.get("category"), "shared applies_to category")
    family = _text(applies.get("family_name_contains"), "shared applies_to family_name_contains")
    items = obj.get("parameters")
    if not isinstance(items, list) or not items:
        raise DictionaryError("shared_parameters parameters must be a non-empty list")
    params: List[SharedParameter] = []
    for item in items:
        po = _only_keys(item, ("name", "guid", "data_type"), "shared parameter")
        name = _text(po.get("name"), "shared parameter name")
        guid = po.get("guid")
        if not isinstance(guid, str) or not GUID_RE.match(guid):
            raise DictionaryError("shared parameter %s: GUID %r is not a valid GUID" % (name, guid))
        data_type = po.get("data_type")
        if data_type not in ALLOWED_DATA_TYPES:
            raise DictionaryError("shared parameter %s: data_type %r not in %s"
                                  % (name, data_type, ", ".join(ALLOWED_DATA_TYPES)))
        params.append(SharedParameter(name, guid.lower(), data_type))
    names = [p.name for p in params]
    guids = [p.guid for p in params]
    if len(set(names)) != len(names):
        raise DictionaryError("shared_parameters has duplicate names")
    if len(set(guids)) != len(guids):
        raise DictionaryError("shared_parameters has duplicate GUIDs")
    return SharedBlock(source, sha, group, category, family, tuple(params))


def validate_dictionary(data: Any) -> Dictionary:
    """Return a Dictionary or raise DictionaryError."""
    top = _only_keys(data, ("schema_version", "sources", "shared_parameters", "categories", "rack"), "dictionary")
    version = top.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise DictionaryError("schema_version must be 1")
    if "shared_parameters" not in top:
        raise DictionaryError("dictionary is missing shared_parameters")
    shared = _parse_shared(top["shared_parameters"])
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
         "required_parameters", "non_empty_parameters", "pending_confirmation", "basis"),
        "rack",
    )
    basis = _only_keys(rack_raw.get("basis"), ("status", "non_empty_source", "exists_source"), "rack basis")
    if basis.get("status") != BASIS_STATUS:
        raise DictionaryError("rack basis status must be %r (the rack rules are not owner-confirmed)" % BASIS_STATUS)
    _text(basis.get("non_empty_source"), "rack basis non_empty_source")
    _text(basis.get("exists_source"), "rack basis exists_source")
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

    # Cross-checks: the rack's required parameters ARE the shared parameters, nothing more or less.
    rack_set = set(required)
    shared_set = {p.name for p in shared.parameters}
    if rack_set != shared_set:
        raise DictionaryError(
            "rack required_parameters and shared_parameters differ: only in rack %s; only in shared %s"
            % (sorted(rack_set - shared_set), sorted(shared_set - rack_set)))
    if shared.applies_to_category != category or shared.applies_to_family_contains != contains:
        raise DictionaryError("shared_parameters applies_to does not match the rack definition")
    overlap = [p for p, _ in pending if p in shared_set]
    if overlap:
        raise DictionaryError("pending parameters must not be shared parameters: %s" % overlap)

    return Dictionary(
        tuple(categories),
        RackRule(category, contains, prefix, code, required, non_empty, tuple(pending)),
        shared,
    )


def load_dictionary(path: str) -> Dictionary:
    """Read and validate a dictionary file (UTF-8)."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh, object_pairs_hook=_reject_duplicate_keys)
    except DictionaryError:
        raise
    except ValueError as ex:
        raise DictionaryError("%s is not valid JSON: %s" % (path, ex)) from ex
    return validate_dictionary(data)


def verify_against_shared_file(dictionary: Dictionary, path: str) -> None:
    """Check the dictionary against a Revit shared parameter file, in both directions.

    Raises DictionaryError listing every difference: source hash, group, a name missing on
    either side, a GUID that differs (name -> GUID and GUID -> name), a data type that differs.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        file = parse_shared_bytes(raw)
    except SharedFileError as ex:
        raise DictionaryError("shared parameter file %s: %s" % (path, ex)) from ex
    problems = []
    if file.sha256 != dictionary.shared.source_sha256:
        problems.append("source file changed: sha256 %s, dictionary expects %s"
                        % (file.sha256, dictionary.shared.source_sha256))
    if dictionary.shared.group not in file.groups:
        problems.append("group %r not in the file (file has %s)" % (dictionary.shared.group, list(file.groups)))
    file_names = [p.name for p in file.params]
    if len(set(file_names)) != len(file_names):
        problems.append("the file has duplicate parameter names")
    by_file = {p.name: p for p in file.params}
    by_dict = {p.name: p for p in dictionary.shared.parameters}
    # dictionary -> file
    for name in sorted(by_dict):
        if name not in by_file:
            problems.append("dictionary has %s but the file does not" % name)
            continue
        fp, dp = by_file[name], by_dict[name]
        if fp.guid.lower() != dp.guid:
            problems.append("GUID differs for %s: file %s, dictionary %s" % (name, fp.guid, dp.guid))
        if fp.data_type != dp.data_type:
            problems.append("data type differs for %s: file %s, dictionary %s" % (name, fp.data_type, dp.data_type))
    # file -> dictionary
    for name in sorted(by_file):
        if name not in by_dict:
            problems.append("file has %s but the dictionary does not" % name)
    dict_guid_to_name = {p.guid: p.name for p in dictionary.shared.parameters}
    for fp in file.params:
        guid = fp.guid.lower()
        if guid in dict_guid_to_name and dict_guid_to_name[guid] != fp.name:
            problems.append("GUID %s is %s in the file but %s in the dictionary"
                            % (fp.guid, fp.name, dict_guid_to_name[guid]))
    if problems:
        raise DictionaryError("shared parameter file does not match the dictionary:" + chr(10)
                              + "  - " + (chr(10) + "  - ").join(problems))
