"""Minimal JSON Schema validator (subset) for the two schemas in ../schemas.

Only the keywords listed in SUPPORTED are understood. `unsupported_keywords`
reports any other keyword, so a schema cannot silently rely on a rule this
validator ignores. Patterns are matched with re.search, as JSON Schema does.
"""
import re
from typing import Any, Dict, List

SUPPORTED = frozenset([
    "type", "required", "properties", "additionalProperties", "items", "enum",
    "const", "pattern", "minimum", "minLength", "minItems", "$ref", "$defs",
])
METADATA = frozenset(["$schema", "$id", "title", "description", "$comment"])

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def unsupported_keywords(schema: Any, path: str = "#") -> List[str]:
    """Return 'path: keyword' for every keyword this validator does not implement."""
    found = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key not in SUPPORTED and key not in METADATA:
                found.append("%s: %s" % (path, key))
            if key in ("properties", "$defs") and isinstance(value, dict):
                for name, sub in value.items():
                    found += unsupported_keywords(sub, "%s/%s/%s" % (path, key, name))
            elif key in ("items", "additionalProperties") and isinstance(value, dict):
                found += unsupported_keywords(value, "%s/%s" % (path, key))
    return found


def _resolve(ref: str, root: Dict[str, Any]) -> Dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError("only local $ref is supported: %s" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(instance: Any, schema: Dict[str, Any], root: Dict[str, Any] = None,
             path: str = "$") -> List[str]:
    """Return a list of error strings (empty when valid)."""
    root = schema if root is None else root
    if "$ref" in schema:
        return validate(instance, _resolve(schema["$ref"], root), root, path)
    errors = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](instance) for t in types):
            return ["%s: expected type %s, got %s" % (path, "/".join(types), type(instance).__name__)]
    if "const" in schema and instance != schema["const"]:
        errors.append("%s: must equal %r" % (path, schema["const"]))
    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: %r is not one of %r" % (path, instance, schema["enum"]))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append("%s: shorter than %d" % (path, schema["minLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append("%s: %r does not match %s" % (path, instance, schema["pattern"]))
    if _TYPES["number"](instance) and "minimum" in schema and instance < schema["minimum"]:
        errors.append("%s: below minimum %s" % (path, schema["minimum"]))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append("%s: fewer than %d items" % (path, schema["minItems"]))
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(instance):
                errors += validate(item, schema["items"], root, "%s[%d]" % (path, i))
    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append("%s: missing required field '%s'" % (path, name))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for name, value in instance.items():
            sub_path = "%s.%s" % (path, name)
            if name in props:
                errors += validate(value, props[name], root, sub_path)
            elif extra is False:
                errors.append("%s: unknown field" % sub_path)
            elif isinstance(extra, dict):
                errors += validate(value, extra, root, sub_path)
    return errors
