"""FP-01..07 input fingerprint, LD-01..05 run ledger and duplicate-run rules."""
import os
import unittest

from bbcc import atomic, fingerprint, ledger, results
from tests.helpers import SandboxTest, contract_dict, valid_result

FILES = [("S-ESC-01.rvt", 3, "a" * 64), ("S-ESC-02.rvt", 4, "b" * 64)]


def fp(**changes):
    args = {"task_id": "t1", "task_version": "1.0.0", "contract_sha256": "c" * 64,
            "entry_sha256": "d" * 64, "params": {"value": "SCADA", "names": ["SCADA"]},
            "input_files": FILES}
    args.update(changes)
    return fingerprint.input_fingerprint(**args)


class FingerprintTest(unittest.TestCase):
    def test_fp01_same_input_same_fingerprint(self):
        self.assertEqual(fp(), fp())
        self.assertRegex(fp(), r"^[0-9a-f]{64}$")

    def test_fp02_param_key_order(self):
        self.assertEqual(fp(params={"a": 1, "b": 2}), fp(params={"b": 2, "a": 1}))

    def test_fp03_input_file_content(self):
        changed = [("S-ESC-01.rvt", 3, "e" * 64), FILES[1]]
        self.assertNotEqual(fp(), fp(input_files=changed))

    def test_fp04_task_version(self):
        self.assertNotEqual(fp(), fp(task_version="1.0.1"))

    def test_fp05_entry_content(self):
        self.assertNotEqual(fp(), fp(entry_sha256="f" * 64))

    def test_fp06_mode_is_not_part_of_fingerprint(self):
        # input_fingerprint has no mode argument; the controller passes the same
        # values for dry_run and write. Verified end to end with a real sandbox run.
        self.assertNotIn("mode", fingerprint.input_fingerprint.__code__.co_varnames)
        from tests.helpers import Sandbox
        box = Sandbox()
        self.addCleanup(box.cleanup)
        registry = box.registry("t1")
        dry = box.run(registry, ["t1"], mode="dry_run")
        write = box.run(registry, ["t1"], mode="write")
        self.assertEqual(box.result(dry, "t1")["input_fingerprint"], box.result(write, "t1")["input_fingerprint"])

    def test_fp07_path_case_and_separator(self):
        variant = [("s-esc-01.RVT", 3, "a" * 64), ("s-esc-02.rvt", 4, "b" * 64)]
        self.assertEqual(fp(), fp(input_files=variant))
        nested_a = [("sub/S-ESC-01.rvt", 3, "a" * 64)]
        nested_b = [("SUB\\s-esc-01.rvt", 3, "a" * 64)]
        self.assertEqual(fp(input_files=nested_a), fp(input_files=nested_b))


class LedgerTest(SandboxTest):
    FP = "9" * 64

    def record(self, run_id, mode, status, promotion="none", confirm=True):
        """Write a ledger record and, unless confirm=False, the matching result file
        that ledger.is_confirmed() requires before a record may enable a write."""
        ledger.write_record(self.box.runs_root, {
            "run_id": run_id, "task_id": "t1", "task_version": "1.0.0", "input_fingerprint": self.FP,
            "mode": mode, "status": status, "recorded_at": "2026-11-11T09:00:00+08:00",
            "promotion": promotion})
        if not confirm:
            return
        changes = {"run_id": run_id, "input_fingerprint": self.FP, "mode": mode, "status": status,
                   "verified_by_controller": True}
        if mode == "dry_run":
            changes["items_modified"] = 0
        if status == "failed":
            changes.update(errors=[{"code": "TASK_ERROR", "message": "x"}], failure_class="task_reported")
        if status == "interrupted":
            changes.update(errors=[{"code": "RESULT_MISSING", "message": "x"}], written_by="controller")
        folder = os.path.join(self.box.runs_root, "runs", run_id, "results")
        os.makedirs(folder)
        results.write_result(os.path.join(folder, "t1.result.json"), valid_result(**changes))

    def test_ld01_write_without_dry_run(self):
        decision = ledger.check_duplicate(self.box.runs_root, self.FP, "write")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.skip_reason, "preflight_failed")

    def test_ld02_dry_run_can_repeat(self):
        self.record("20261111-090000-00000001", "dry_run", "success")
        self.assertTrue(ledger.check_duplicate(self.box.runs_root, self.FP, "dry_run").allowed)

    def test_ld03_pending_approval_blocks_write(self):
        self.record("20261111-090000-00000001", "dry_run", "success")
        self.record("20261111-090100-00000002", "write", "success", "pending_approval")
        decision = ledger.check_duplicate(self.box.runs_root, self.FP, "write")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.skip_reason, "duplicate_run")
        self.assertIn("20261111-090100-00000002", decision.message)

    def test_ld04_promoted_needs_allow_rerun_with_reason(self):
        registry = self.box.registry("t1")
        self.box.run(registry, ["t1"], mode="dry_run")
        first = self.box.run(registry, ["t1"], mode="write")
        fp_value = self.box.result(first, "t1")["input_fingerprint"]
        record_path = os.path.join(self.box.runs_root, "ledger", fp_value, "%s.json" % first.run_id)
        record = atomic.read_json_strict(record_path)
        self.assertEqual(record["promotion"], "pending_approval")
        record["promotion"] = "promoted"  # test-only: simulate a later approved write-back
        atomic.atomic_write_json(record_path, record)
        blocked = self.box.run(registry, ["t1"], mode="write")
        self.assertEqual(blocked.results["t1"]["skip_reason"], "duplicate_run")
        rerun = self.box.run(registry, ["t1"], mode="write", allow_rerun={"t1": "client asked for a re-issue"})
        self.assertEqual(rerun.status("t1"), "success")
        new_record = atomic.read_json_strict(
            os.path.join(self.box.runs_root, "ledger", fp_value, "%s.json" % rerun.run_id))
        self.assertEqual(new_record["rerun_reason"], "client asked for a re-issue")

    def test_ld06_unconfirmed_dry_run_record_does_not_enable_write(self):
        # A ledger record alone is not evidence: its result file must exist, be valid,
        # match run_id / fingerprint / mode / status and be verified by the controller.
        self.record("20261111-090000-00000001", "dry_run", "success", confirm=False)
        decision = ledger.check_duplicate(self.box.runs_root, self.FP, "write")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.skip_reason, "preflight_failed")
        self.record("20261111-090100-00000002", "dry_run", "success", confirm=True)
        self.assertTrue(ledger.check_duplicate(self.box.runs_root, self.FP, "write").allowed)

    def test_ld05_failures_do_not_block(self):
        self.record("20261111-090000-00000001", "dry_run", "success")
        self.record("20261111-090100-00000002", "write", "failed")
        self.record("20261111-090200-00000003", "write", "interrupted")
        self.assertTrue(ledger.check_duplicate(self.box.runs_root, self.FP, "write").allowed)



class ExternalInputTest(SandboxTest):
    """FX-01..03: source_model / data_file / file_list inputs are hashed into the fingerprint."""

    def contract(self, kind="file"):
        data = contract_dict("t1")
        data["inputs"].append({"name": "source_data", "type": kind, "role": "data_file",
                               "required": True, "dyn_index": 2})
        return self.box.register(data)

    def put(self, name, data):
        path = os.path.join(self.box.root, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_fx01_data_file_content_changes_fingerprint(self):
        registry = self.contract()
        data = self.put("params.csv", b"version-A")
        extra = {"t1": {"source_data": data}}
        first = self.box.run(registry, ["t1"], extra_inputs=extra)
        self.assertEqual(first.status("t1"), "success")
        job = atomic.read_json_strict(os.path.join(first.run_dir, "jobs", "t1.job.json"))
        roles = [f["role"] for f in job["input_files"]]
        self.assertIn("data_file", roles)
        self.put("params.csv", b"version-B")
        blocked = self.box.run(registry, ["t1"], mode="write", extra_inputs=extra)
        self.assertEqual(blocked.results["t1"]["skip_reason"], "preflight_failed")
        second = self.box.run(registry, ["t1"], extra_inputs=extra)
        self.assertNotEqual(self.box.result(first, "t1")["input_fingerprint"],
                            self.box.result(second, "t1")["input_fingerprint"])

    def test_fx02_missing_input_file_is_preflight_failure(self):
        from bbcc import controller
        registry = self.contract()
        runner = controller.FakeRunner()
        summary = self.box.run(registry, ["t1"], runner=runner,
                               extra_inputs={"t1": {"source_data": os.path.join(self.box.root, "missing.csv")}})
        self.assertEqual(summary.results["t1"]["skip_reason"], "preflight_failed")
        self.assertIn("input file not found", summary.results["t1"]["warnings"][0]["message"])
        self.assertEqual(runner.calls, [])

    def test_fx03_file_list_member_change(self):
        registry = self.contract("file_list")
        a, b = self.put("a.xlsx", b"sheet A"), self.put("b.xlsx", b"sheet B")
        extra = {"t1": {"source_data": [a, b]}}
        first = self.box.run(registry, ["t1"], extra_inputs=extra)
        self.put("b.xlsx", b"sheet B changed")
        second = self.box.run(registry, ["t1"], extra_inputs=extra)
        self.assertEqual(first.status("t1"), "success")
        self.assertNotEqual(self.box.result(first, "t1")["input_fingerprint"],
                            self.box.result(second, "t1")["input_fingerprint"])


if __name__ == "__main__":
    unittest.main()
