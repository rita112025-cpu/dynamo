"""AST rules for Revit READ-ONLY code (the reader probe and, later, the reader).

Unlike tools/dyn_checks.py (which forbids every Revit import), this module ALLOWS a short, explicit
list of read-only Revit names and forbids everything that writes, saves, syncs, opens or closes a
document, or shows UI. The existing base/strict rules are NOT changed by this module.

Like dyn_checks, this is a guard against accidents, not a security sandbox (see docs/dyn_build.md).
"""
import ast
from typing import List, Tuple

# ---- imports -------------------------------------------------------------------------------
# Autodesk.Revit.DB names a read-only reader may import.
ALLOWED_DB_NAMES = (
    "FilteredElementCollector", "FilteredWorksetCollector", "BuiltInCategory", "BuiltInParameter",
    "StorageType", "ElementId", "ModelPathUtils", "RevitLinkInstance",
)
# System names a reader may import (string, integer and GUID types only).
ALLOWED_SYSTEM_NAMES = ("String", "Int32", "Int64", "Guid")
# RevitServices: only the document accessor (no transaction manager).
ALLOWED_REVITSERVICES_NAMES = ("DocumentManager",)
# clr.AddReference may only name these assemblies, given as string constants.
ALLOWED_ASSEMBLIES = ("RevitAPI", "RevitServices")

# Import roots that are never allowed, whatever the name.
FORBIDDEN_IMPORT_ROOTS = ("Autodesk.Revit.UI", "System.IO", "RevitServices.Transactions",
                          "importlib", "builtins")

# ---- names and attributes ------------------------------------------------------------------
FORBIDDEN_NAMES = (
    "Transaction", "TransactionManager", "SubTransaction", "TransactionGroup", "UIDocument",
    "UIApplication", "TransactionStatus", "FailureHandlingOptions", "IFailuresPreprocessor",
)
FORBIDDEN_ATTRIBUTES = (
    "Set", "SetValueString", "Overloads", "Create", "Delete", "Save", "SaveAs", "SaveAsLibrary",
    "SynchronizeWithCentral", "Commit", "RollBack", "Start", "Regenerate", "Close",
    "OpenDocumentFile", "CreateNewLocal", "ForceCloseTransaction", "Reload", "ReloadFrom",
    "Activate", "ShowDialog", "Show",
)
STRICT_BUILTINS = ("__import__", "eval", "exec", "compile", "importlib", "builtins")
# os functions that delete or remove files or folders. os.replace stays allowed (report writes).
OS_DELETE_FUNCTIONS = ("remove", "unlink", "rmdir", "removedirs")
DYNAMIC_ACCESS = ("getattr", "setattr", "delattr", "hasattr")
# getattr may read enum members from these two classes only (read-only by nature).
GETATTR_ENUM_CLASSES = ("BuiltInCategory", "BuiltInParameter")

Finding = Tuple[int, str]


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _check_import_from(node: ast.ImportFrom) -> List[Finding]:
    found: List[Finding] = []
    module = node.module or ""
    if node.level:
        return [(node.lineno, "relative import not allowed")]
    for root in FORBIDDEN_IMPORT_ROOTS:
        if module == root or module.startswith(root + "."):
            return [(node.lineno, "forbidden import from %s" % module)]
    allowed = None
    if module == "Autodesk.Revit.DB":
        allowed = ALLOWED_DB_NAMES
    elif module == "System":
        allowed = ALLOWED_SYSTEM_NAMES
    elif module == "RevitServices.Persistence":
        allowed = ALLOWED_REVITSERVICES_NAMES
    elif module == "datetime":
        allowed = ("datetime",)  # standard library, no Revit access
    else:
        return [(node.lineno, "import from %s is not on the reader allowlist" % module)]
    for alias in node.names:
        if alias.name not in allowed:
            found.append((node.lineno, "import %s from %s is not allowed" % (alias.name, module)))
    return found


def _check_import(node: ast.Import) -> List[Finding]:
    found: List[Finding] = []
    for alias in node.names:
        root = alias.name.split(".")[0]
        if alias.name in FORBIDDEN_IMPORT_ROOTS or root in ("clr", "importlib", "builtins") and root != "clr":
            found.append((node.lineno, "import " + alias.name))
        elif alias.name == "clr":
            continue  # only the clr.AddReference call is allowed (checked on the call)
        elif alias.name in ("os", "json", "hashlib", "datetime", "traceback", "types", "sys"):
            continue  # standard library, no Revit access
        else:
            found.append((node.lineno, "import " + alias.name + " is not on the reader allowlist"))
    return found


def reader_forbidden_uses(source: str) -> List[Finding]:
    """Return (line, description) for every disallowed construct in Revit read-only code."""
    tree = ast.parse(source)
    found: List[Finding] = []
    # Calls judged by their own rule; their function names must not also be flagged as bare names.
    judged_funcs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name in DYNAMIC_ACCESS:
                judged_funcs.add(id(node.func))
                if name in ("setattr", "delattr"):
                    found.append((node.lineno, "%s is not allowed" % name))
                    continue
                first = node.args[0] if node.args else None
                second = node.args[1] if len(node.args) > 1 else None
                if name == "getattr" and isinstance(first, ast.Name) and first.id in GETATTR_ENUM_CLASSES:
                    continue
                if isinstance(second, ast.Constant) and isinstance(second.value, str):
                    if second.value in FORBIDDEN_ATTRIBUTES or second.value in FORBIDDEN_NAMES:
                        found.append((node.lineno, "%s of forbidden name %r" % (name, second.value)))
                else:
                    found.append((node.lineno, "%s with a name that is not a plain string constant" % name))
    # The only use of the name clr is clr.AddReference(...).
    clr_ok = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "clr":
            if node.attr == "AddReference":
                clr_ok.add(id(node.value))
            else:
                found.append((node.lineno, "clr.%s is not allowed (only clr.AddReference)" % node.attr))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.extend(_check_import_from(node))
        elif isinstance(node, ast.Import):
            found.extend(_check_import(node))
        elif isinstance(node, ast.Call) and _dotted(node.func) == "clr.AddReference":
            arg = node.args[0] if node.args else None
            if not (isinstance(arg, ast.Constant) and arg.value in ALLOWED_ASSEMBLIES):
                found.append((node.lineno, "clr.AddReference may only name RevitAPI or RevitServices"))
        elif isinstance(node, ast.Name):
            if node.id == "clr":
                if id(node) not in clr_ok:
                    found.append((node.lineno, "clr may only be used as clr.AddReference"))
            elif node.id in FORBIDDEN_NAMES or node.id in FORBIDDEN_ATTRIBUTES:
                found.append((node.lineno, "name " + node.id))
            elif node.id in STRICT_BUILTINS:
                found.append((node.lineno, "builtin " + node.id))
            elif node.id in DYNAMIC_ACCESS and id(node) not in judged_funcs:
                found.append((node.lineno, "dynamic access builtin %s used as a value" % node.id))
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in OS_DELETE_FUNCTIONS:
                found.append((node.lineno, "os." + node.attr + " deletes files (not allowed)"))
            elif node.attr in FORBIDDEN_ATTRIBUTES:
                found.append((node.lineno, "call or access ." + node.attr))
            elif node.attr in FORBIDDEN_NAMES:
                found.append((node.lineno, "attribute " + node.attr))
            elif node.attr in STRICT_BUILTINS:
                found.append((node.lineno, "attribute ." + node.attr))
    return sorted(set(found))


def assert_reader_clean(source: str, label: str) -> None:
    found = reader_forbidden_uses(source)
    if found:
        details = "; ".join("line %d: %s" % item for item in found)
        raise ValueError("%s breaks the reader rules (%s)" % (label, details))
