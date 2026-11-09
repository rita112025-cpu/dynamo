"""AST checks for embedded Python: nothing may call or import Revit, and nothing may write to a model.

Checks look at the parsed program, not at raw text, so comments, docstrings and string constants
that merely mention a word are NOT violations. Only real imports, names and attribute accesses are.
"""
import ast
from typing import List, Tuple

# Imports whose module (or top-level package) is forbidden in the embedded program.
FORBIDDEN_IMPORT_ROOTS = ("clr", "RevitAPI", "RevitServices", "Autodesk", "System")

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

Finding = Tuple[int, str]


def forbidden_uses(source: str) -> List[Finding]:
    """Return (line, description) for every forbidden import, name or attribute."""
    tree = ast.parse(source)
    found: List[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    found.append((node.lineno, "import " + alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                found.append((node.lineno, "from %s import ..." % node.module))
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                found.append((node.lineno, "name " + node.id))
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES:
                found.append((node.lineno, "call or access ." + node.attr))
            elif node.attr in FORBIDDEN_NAMES:
                found.append((node.lineno, "attribute " + node.attr))
    return sorted(found)


def assert_no_forbidden(source: str, label: str) -> None:
    found = forbidden_uses(source)
    if found:
        details = "; ".join("line %d: %s" % item for item in found)
        raise ValueError("%s uses forbidden Revit/model-writing code (%s)" % (label, details))
