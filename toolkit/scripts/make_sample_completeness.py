"""Run the completeness check on examples/sample_snapshot.json (FAKE data) and write
examples/sample_completeness_findings.csv and examples/sample_completeness_scope.csv.

No Revit, no RVT. Usage (from the toolkit folder): python scripts/make_sample_completeness.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mep_toolkit.completeness import check_completeness, write_completeness_reports  # noqa: E402
from mep_toolkit.dictionary import load_dictionary  # noqa: E402
from mep_toolkit.snapshot import load_snapshot  # noqa: E402

RUN_TIME = datetime(2026, 11, 9, 10, 30, 0, tzinfo=timezone(timedelta(hours=8)))  # fixed: reproducible


def main() -> int:
    dictionary = load_dictionary(os.path.join(ROOT, "config", "parameter_dictionary.json"))
    source, elements = load_snapshot(os.path.join(ROOT, "examples", "sample_snapshot.json"))
    result = check_completeness(elements, dictionary)
    f_path = os.path.join(ROOT, "examples", "sample_completeness_findings.csv")
    s_path = os.path.join(ROOT, "examples", "sample_completeness_scope.csv")
    write_completeness_reports(result, f_path, s_path, source, RUN_TIME)
    print("findings: %d rows -> %s" % (len(result.findings), f_path))
    print("scope: %d rows -> %s" % (len(result.scopes), s_path))
    print("ignored categories (not examined): %s" % result.ignored_categories)
    return 0


if __name__ == "__main__":
    sys.exit(main())
