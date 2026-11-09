"""AST checks for embedded Python.

Two levels:
  base    - the node program and the modules: no Revit API, no Revit model writes.
  strict  - the mep_toolkit module sources only: additionally no dynamic code or dynamic
            attribute access (eval, exec, compile, __import__, importlib, and getattr/setattr/
            delattr/hasattr with a name that is not a plain string constant, or is a forbidden name).

Checks look at the parsed program, not raw text, so comments, docstrings and string constants
that merely mention a word are NOT violations.

These checks are a guard against accidents. They are NOT a security sandbox: a determined author
can still find ways around a static check. See docs/dyn_build.md.
"""
import ast
from typing import List, Tuple

# Imports whose module (or top-level package) is forbidden in the embedded program.
FORBIDDEN_IMPORT_ROOTS = ("clr", "RevitAPI", "RevitServices", "Autodesk", "System")
STRICT_IMPORT_ROOTS = ("importlib", "builtins")

# Names that refer to Revit API objects (as a variable, a class or an attribute).
FORBIDDEN_NAMES = (
    "Transaction", "TransactionManager", "SubTransaction", "TransactionGroup",
    "DocumentManager", "Document", "UIDocument", "RevitServices", "FilteredElementCollector",
    "ElementTransformUtils", "WorksharingUtils", "ModelPathUtils", "SynchronizeWithCentralOptions",
)

# Method or property names that modify or persist a Revit document or transaction.
FORBIDDEN_ATTRIBUTES = (
    "Save", "SaveAs", "SaveAsLibrary", "SynchronizeWithCentral", "Delete", "Commit", "RollBack",
    "OpenDocumentFile", "Regenerate", "CreateNewLocal", "ForceCloseTransaction", "Close",
)

# Strict only: builtins that run or build code dynamically (bare names, i.e. the builtins).
STRICT_BUILTIN_NAMES = ("__import__", "importlib", "eval", "exec", "compile", "builtins")

# Strict only: attribute-access builtins; allowed only with a plain, non-forbidden string constant.
DYNAMIC_ACCESS = ("getattr", "setattr", "delattr", "hasattr")

Finding = Tuple[int, str]


def _call_name(node: ast.Call):
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _name_argument(node: ast.Call):
    if len(node.args) >= 2:
        return node.args[1]
    for kw in node.keywords:
        if kw.arg == "name":
            return kw.value
    return None


def forbidden_uses(source: str, strict: bool = False) -> List[Finding]:
    """Return (line, description) for every forbidden import, name, attribute or dynamic access."""
    tree = ast.parse(source)
    found: List[Finding] = []
    import_roots = FORBIDDEN_IMPORT_ROOTS + (STRICT_IMPORT_ROOTS if strict else ())
    # Function names of getattr-style calls are judged by their call, not as bare values.
    dynamic_funcs = set()
    if strict:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in DYNAMIC_ACCESS:
                dynamic_funcs.add(id(node.func))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in import_roots:
                    found.append((node.lineno, "import " + alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.split(".")[0] in import_roots:
                found.append((node.lineno, "from %s import ..." % node.module))
        elif isinstance(node, ast.Call) and strict and _call_name(node) in DYNAMIC_ACCESS:
            name_arg = _name_argument(node)
            label = _call_name(node)
            if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
                found.append((node.lineno, "%s with a name that is not a plain string constant" % label))
            elif name_arg.value in FORBIDDEN_ATTRIBUTES or name_arg.value in FORBIDDEN_NAMES:
                found.append((node.lineno, "%s of forbidden name %r" % (label, name_arg.value)))
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                found.append((node.lineno, "name " + node.id))
            elif strict and node.id in STRICT_BUILTIN_NAMES:
                found.append((node.lineno, "builtin " + node.id))
            elif strict and node.id in DYNAMIC_ACCESS and id(node) not in dynamic_funcs:
                # Bare use outside a call (e.g. passed around): cannot be checked statically.
                found.append((node.lineno, "dynamic access builtin " + node.id + " used as a value"))
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES:
                found.append((node.lineno, "call or access ." + node.attr))
            elif node.attr in FORBIDDEN_NAMES:
                found.append((node.lineno, "attribute " + node.attr))
            elif strict and node.attr in ("__import__", "eval", "exec", "builtins", "importlib"):
                found.append((node.lineno, "attribute ." + node.attr))
    return sorted(set(found))


def assert_no_forbidden(source: str, label: str, strict: bool = False) -> None:
    found = forbidden_uses(source, strict=strict)
    if found:
        details = "; ".join("line %d: %s" % item for item in found)
        raise ValueError("%s uses forbidden code (%s)" % (label, details))
