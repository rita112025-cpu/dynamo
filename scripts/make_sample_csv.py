"""Write examples/sample_findings.csv and examples/sample_scope.csv from FAKE data
(no Revit, no RVT).

Usage (from the toolkit folder): python scripts/make_sample_csv.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mep_toolkit.csv_report import write_findings_csv, write_scope_csv  # noqa: E402
from mep_toolkit.findings import CheckScope, Finding, Status  # noqa: E402

# Fixed time so the sample files are reproducible.
RUN_TIME = datetime(2026, 11, 9, 10, 30, 0, tzinfo=timezone(timedelta(hours=8)))
# SOURCE path the caller asked to open (never read back from a detached document).
MODEL_FILE = r"D:\fake\FAKE-ESC-TEST-STATION.rvt"  # test data, not a real model

FINDINGS = [
    Finding("SCADA_服務類型必填", Status.PASS, 1001001),
    Finding("SCADA_服務類型必填", Status.FAIL, 1001002, "服務類型為空"),
    Finding("SCADA_服務類型必填", Status.FAIL, 1001003, "服務類型為 'SCADA ' (含空格)"),
    Finding("CableTray_Connector連接", Status.FAIL, 1002001, "2 個 connector 中 1 個未連接"),
    Finding("CableTray_高程範圍", Status.UNVERIFIED, 1002002, "高程規則未經業主確認"),
    # Only possible when checking an already open document (see docs/unverified_policy.md).
    Finding("工作集載入", Status.UNVERIFIED, None, "有 1 個工作集未開啟，其元件未檢查"),
    Finding("設備編號重複", Status.FAIL, 1003001, "編號 =A01 與元件 1003002 重複"),
]

SCOPES = [
    CheckScope("SCADA_服務類型必填", 3),
    CheckScope("CableTray_Connector連接", 14),
    CheckScope("CableTray_高程範圍", 14),
    CheckScope("工作集載入", 1, "以整個模型為單位"),
    CheckScope("設備編號重複", 20),
    CheckScope("Conduit_Connector連接", 0, "模型沒有電管，未檢查"),
]


def main() -> int:
    out_dir = os.path.join(ROOT, "examples")
    os.makedirs(out_dir, exist_ok=True)
    f_path = os.path.join(out_dir, "sample_findings.csv")
    s_path = os.path.join(out_dir, "sample_scope.csv")
    print("wrote %d rows to %s" % (write_findings_csv(f_path, FINDINGS, MODEL_FILE, RUN_TIME), f_path))
    print("wrote %d rows to %s" % (write_scope_csv(s_path, SCOPES, FINDINGS, MODEL_FILE, RUN_TIME), s_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
