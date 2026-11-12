"""CR-01..10 controller verdicts and SF-01..13 safety failures (FakeRunner only)."""
import os
import shutil
import unittest
from unittest import mock

from bbcc import atomic, controller, ledger, locks, results
from tests.helpers import HOST, SandboxTest, override, snapshot

OTHER_RUN = "20261111-000000-abcdef12"


def statuses(summary):
    return dict((t, (d["status"], d["failure_class"], d["skip_reason"])) for t, d in summary.results.items())


def codes(summary, task_id):
    return [e["code"] for e in summary.results[task_id]["errors"]]


class ControllerTest(SandboxTest):
    def two(self, behaviour, mode="dry_run"):
        registry = self.box.registry("t1", "t2")
        return self.box.run(registry, ["t1", "t2"], mode=mode,
                            runner=controller.FakeRunner({"t1": behaviour}))

    def assertHalted(self, summary):
        self.assertTrue(summary.halted)
        self.assertEqual(summary.results["t2"]["status"], "skipped")
        self.assertEqual(summary.results["t2"]["skip_reason"], "run_halted")

    def test_cr01_valid_success(self):
        registry = self.box.registry("t1")
        summary = self.box.run(registry, ["t1"])
        doc = self.box.result(summary, "t1")
        self.assertEqual(doc["status"], "success")
        self.assertTrue(doc["verified_by_controller"])
        self.assertEqual(doc["written_by"], "task")

    def test_cr02_task_failure_skips_dependants_only(self):
        def fail(job, stop_event):
            controller.write_task_result(job, status="failed")
        registry = self.box.registry("t1", ("t2", ["t1"], []), "t3")
        summary = self.box.run(registry, ["t1", "t2", "t3"], runner=controller.FakeRunner({"t1": fail}))
        self.assertEqual(statuses(summary), {
            "t1": ("failed", "task_reported", None),
            "t2": ("skipped", None, "dependency_failed"),
            "t3": ("success", None, None)})
        self.assertFalse(summary.halted)

    def test_cr03_missing_result_interrupts_and_halts(self):
        summary = self.two(lambda job, stop_event: None)
        self.assertEqual(summary.results["t1"]["status"], "interrupted")
        self.assertIn("RESULT_MISSING", codes(summary, "t1"))
        self.assertHalted(summary)

    def test_cr04_damaged_result_is_verification_failure(self):
        def damaged(job, stop_event):
            with open(job["result_path"], "wb") as handle:
                handle.write(b'{"status": "succ')
        summary = self.two(damaged)
        self.assertEqual(statuses(summary)["t1"], ("failed", "verification", None))
        self.assertIn("RESULT_INVALID", codes(summary, "t1"))
        self.assertTrue(os.path.isfile(os.path.join(summary.run_dir, "results", "t1.result.rejected.json")))
        self.assertHalted(summary)

    def test_cr05_mode_mismatch_is_stale(self):
        summary = self.two(override(mode="write", items_modified=0))
        self.assertIn("RESULT_STALE", codes(summary, "t1"))
        self.assertHalted(summary)

    def test_cr06_started_before_issue(self):
        summary = self.two(override(started_at="2000-01-01T00:00:00+00:00"))
        self.assertIn("RESULT_TIME", codes(summary, "t1"))
        self.assertHalted(summary)

    def test_cr07_runner_may_not_report_skipped(self):
        summary = self.two(override(status="skipped", skip_reason="not_applicable", started_at=None,
                                    items_processed=0, items_modified=0))
        self.assertEqual(statuses(summary)["t1"], ("failed", "verification", None))
        self.assertIn("RESULT_INVALID", codes(summary, "t1"))
        self.assertHalted(summary)

    def test_cr08_user_stop_while_running(self):
        def stop(job, stop_event):
            controller.write_task_result(job)
            stop_event.set()
        summary = self.two(stop)
        self.assertEqual(summary.results["t1"]["status"], "interrupted")
        self.assertIn("INTERRUPTED_BY_USER", codes(summary, "t1"))
        self.assertHalted(summary)

    def test_cr09_exit_code_zero_is_not_success(self):
        summary = self.two(lambda job, stop_event: controller.RunnerOutcome(exit_code=0, pid=1234))
        doc = summary.results["t1"]
        self.assertEqual(doc["status"], "interrupted")
        self.assertEqual(doc["process"]["exit_code"], 0)
        self.assertHalted(summary)

    def test_cr10_controller_error_halts(self):
        with mock.patch.object(results, "judge", side_effect=RuntimeError("injected fault")):
            summary = self.two(controller.succeed)
        self.assertEqual(statuses(summary)["t1"], ("failed", "controller_error", None))
        trace = os.path.join(summary.run_dir, "evidence", "t1", "controller_error.txt")
        with open(trace, "rb") as handle:
            self.assertIn(b"injected fault", handle.read())
        self.assertHalted(summary)


class SafetyFailureTest(SandboxTest):
    def setUp(self):
        super(SafetyFailureTest, self).setUp()
        self.before = snapshot(self.box.models)

    def assertOriginalUntouched(self):
        self.assertEqual(snapshot(self.box.models), self.before)

    def copy_failing(self, where, nth=1, corrupt=False):
        seen = []

        def copy(src, dst):
            if (os.sep + where + os.sep) in dst:
                seen.append(dst)
                if len(seen) == nth:
                    if corrupt:
                        shutil.copy2(src, dst)
                        os.chmod(dst, 0o644)
                        with open(dst, "ab") as handle:
                            handle.write(b"corrupted")
                        return dst
                    raise OSError("injected copy failure")
            return shutil.copy2(src, dst)
        return copy

    def run_one(self, mode="dry_run", runner=None, **opts):
        self.runner = runner or controller.FakeRunner()
        registry = self.box.registry("t1")
        return self.box.run(registry, ["t1"], mode=mode, runner=self.runner, options=self.box.options(**opts))

    def assertNotStarted(self, summary, reason):
        self.assertEqual(summary.results["t1"]["skip_reason"], reason)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(os.listdir(os.path.join(summary.run_dir, "jobs")), [])
        self.assertOriginalUntouched()

    def write_approved_run(self, behaviour=None):
        registry = self.box.registry("t1")
        self.box.run(registry, ["t1"], mode="dry_run")
        runner = controller.FakeRunner({"t1": behaviour} if behaviour else None)
        return self.box.run(registry, ["t1"], mode="write", runner=runner)

    def two(self, behaviour):
        registry = self.box.registry("t1", "t2")
        return self.box.run(registry, ["t1", "t2"], runner=controller.FakeRunner({"t1": behaviour}))

    def assertHaltedStale(self, summary, code):
        self.assertEqual(summary.results["t1"]["status"], "failed")
        self.assertIn(code, codes(summary, "t1"))
        self.assertTrue(summary.halted)
        self.assertEqual(summary.results["t2"]["skip_reason"], "run_halted")

    def test_sf01_backup_copy_raises(self):
        summary = self.run_one(copy=self.copy_failing("backup"))
        self.assertNotStarted(summary, "backup_failed")

    def test_sf02_backup_hash_mismatch(self):
        summary = self.run_one(copy=self.copy_failing("backup", corrupt=True))
        self.assertNotStarted(summary, "backup_failed")

    def test_sf03_workcopy_fails(self):
        summary = self.run_one(copy=self.copy_failing("work"))
        self.assertNotStarted(summary, "workcopy_failed")

    def test_sf04_workcopy_fails_midway_keeps_partial(self):
        summary = self.run_one(copy=self.copy_failing("work", nth=2))
        self.assertNotStarted(summary, "workcopy_failed")
        kept = os.listdir(os.path.join(summary.run_dir, "work", "t1"))
        self.assertEqual(kept, ["S-ESC-01.rvt"])

    def test_sf05_original_changed_blocks_promotion(self):
        def edit_official(job, stop_event):
            with open(os.path.join(self.box.models, "S-ESC-01.rvt"), "ab") as handle:
                handle.write(b" edited by someone else")
            return controller.succeed(job, stop_event)
        summary = self.write_approved_run(edit_official)
        self.assertEqual(summary.status("t1"), "success")
        report = controller.check_promotion(summary.run_dir)["t1"]
        self.assertFalse(report["promotable"])
        self.assertIn("ORIGINAL_CHANGED:S-ESC-01.rvt", report["reasons"])

    def test_sf06_stale_run_id(self):
        self.assertHaltedStale(self.two(override(run_id="20200101-000000-deadbeef")), "RESULT_STALE")

    def test_sf07_wrong_nonce(self):
        fake_nonce = "f" * 32
        summary = self.two(override(run_nonce=fake_nonce))
        self.assertHaltedStale(summary, "RESULT_STALE")
        job = atomic.read_json_strict(os.path.join(summary.run_dir, "jobs", "t1.job.json"))
        with open(os.path.join(summary.run_dir, "results", "t1.result.json"), "rb") as handle:
            text = handle.read().decode("utf-8")
        self.assertNotIn(job["run_nonce"], " ".join(e["message"] for e in summary.results["t1"]["errors"]))
        self.assertNotIn(fake_nonce, text)

    def test_sf08_output_hash_mismatch(self):
        def bad_hash(job, stop_event):
            controller.write_task_result(job, outputs=[("report.txt", b"ok")], overrides={
                "output_files": [{"path": "report.txt", "sha256": "0" * 64, "size": 2}]})
        self.assertHaltedStale(self.two(bad_hash), "OUTPUT_HASH_MISMATCH")

    def test_sf09_output_changed_before_promotion(self):
        summary = self.write_approved_run()
        self.assertTrue(controller.check_promotion(summary.run_dir)["t1"]["promotable"])
        with open(os.path.join(summary.run_dir, "staging", "t1", "report.txt"), "ab") as handle:
            handle.write(b" tampered")
        report = controller.check_promotion(summary.run_dir)["t1"]
        self.assertFalse(report["promotable"])
        self.assertIn("OUTPUT_CHANGED:report.txt", report["reasons"])

    def test_sf10_runner_crash_keeps_evidence(self):
        def crash(job, stop_event):
            with open(os.path.join(job["staging_dir"], "partial.rvt"), "wb") as handle:
                handle.write(b"half")
            raise RuntimeError("runner died")
        summary = self.run_one(runner=controller.FakeRunner({"t1": crash}))
        self.assertEqual(summary.results["t1"]["status"], "interrupted")
        self.assertEqual(sorted(codes(summary, "t1")), ["RESULT_MISSING", "RUNNER_CRASH"])
        run = summary.run_dir
        self.assertEqual(sorted(os.listdir(os.path.join(run, "work", "t1"))), ["S-ESC-01.rvt", "S-ESC-02.rvt"])
        self.assertTrue(os.path.isfile(os.path.join(run, "staging", "t1", "partial.rvt")))
        self.assertTrue(os.path.isfile(os.path.join(run, "jobs", "t1.job.json")))
        self.assertTrue(os.path.isfile(os.path.join(run, "evidence", "t1", "runner_exception.txt")))
        self.assertOriginalUntouched()

    def plant_lock(self):
        other_run = os.path.join(self.box.root, "other_run")
        os.makedirs(other_run)
        with open(os.path.join(other_run, "run_state.json"), "wb") as handle:
            handle.write(b'{"run_id": "%s", "tasks": {"x1": "running"}}' % OTHER_RUN.encode("ascii"))
        path = locks.lock_path(self.box.runs_root, self.box.models)
        os.makedirs(os.path.dirname(path))
        payload = atomic.json_bytes({"lock_version": "1", "run_id": OTHER_RUN, "pid": 4242, "host": HOST,
                                     "started_at": "2026-11-11T00:00:00+08:00", "run_dir": other_run,
                                     "target_root": self.box.models, "controller_version": "0.1.0"})
        with open(path, "wb") as handle:
            handle.write(payload)
        return path, payload, other_run, snapshot(other_run)

    def test_sf11_active_lock_untouched(self):
        path, payload, other_run, other_before = self.plant_lock()
        summary = self.run_one(pid_alive=lambda pid: True)
        self.assertNotStarted(summary, "lock_conflict")
        self.assertEqual(locks.read_lock_bytes(path), payload)
        self.assertEqual(snapshot(other_run), other_before)

    def test_sf12_stale_lock_needs_manual(self):
        path, payload, _, _ = self.plant_lock()
        summary = self.run_one(pid_alive=lambda pid: False)
        self.assertNotStarted(summary, "lock_stale_suspected")
        self.assertEqual(locks.read_lock_bytes(path), payload)
        self.assertIn("confirm manually", summary.results["t1"]["warnings"][0]["message"])

    def test_sf13_lock_rewritten_by_other_not_released(self):
        lock_file = locks.lock_path(self.box.runs_root, self.box.models)
        intruder = {}

        def rewrite_lock(job, stop_event):
            info = atomic.read_json_strict(lock_file)
            info["run_id"] = OTHER_RUN
            intruder["bytes"] = atomic.json_bytes(info)
            with open(lock_file, "wb") as handle:
                handle.write(intruder["bytes"])
            return controller.succeed(job, stop_event)
        summary = self.run_one(runner=controller.FakeRunner({"t1": rewrite_lock}))
        self.assertTrue(summary.lock_errors)
        self.assertIn(OTHER_RUN, summary.lock_errors[0])
        self.assertEqual(locks.read_lock_bytes(lock_file), intruder["bytes"])
        self.assertFalse(os.path.exists(os.path.join(summary.run_dir, "lock.released")))



class ControllerErrorTest(SandboxTest):
    """CE-01..03: a failure while recording a result is a controller error and halts the batch."""

    def setUp(self):
        super(ControllerErrorTest, self).setUp()
        self.registry = self.box.registry("t1", "t2")

    def failing_state_writes(self, should_fail):
        real = atomic.atomic_write_json

        def write(path, obj, **kwargs):
            if str(path).endswith("run_state.json") and should_fail(obj):
                raise OSError("injected run_state failure")
            return real(path, obj, **kwargs)
        return write

    def test_ce01_ledger_failure_halts_batch(self):
        self.box.run(self.registry, ["t1", "t2"], mode="dry_run")
        with mock.patch.object(ledger, "write_record", side_effect=OSError("injected ledger failure")):
            summary = self.box.run(self.registry, ["t1", "t2"], mode="write")
        self.assertEqual(statuses(summary)["t1"], ("failed", "controller_error", None))
        self.assertTrue(summary.halted)
        self.assertEqual(summary.results["t2"]["skip_reason"], "run_halted")
        on_disk = self.box.result(summary, "t1")
        self.assertEqual((on_disk["status"], on_disk["failure_class"]), ("failed", "controller_error"))
        rejected = atomic.read_json_strict(os.path.join(summary.run_dir, "results", "t1.result.rejected.json"))
        self.assertEqual(rejected["status"], "success")
        self.assertFalse(controller.check_promotion(summary.run_dir)["t1"]["promotable"])

    def test_ce02_state_failure_halts_and_ledger_record_is_not_trusted(self):
        fired = []

        def once(obj):
            if obj["tasks"].get("t1") == "success" and not fired:
                fired.append(1)
                return True
            return False
        with mock.patch.object(atomic, "atomic_write_json", side_effect=self.failing_state_writes(once)):
            summary = self.box.run(self.registry, ["t1", "t2"], mode="dry_run")
        self.assertEqual(statuses(summary)["t1"], ("failed", "controller_error", None))
        self.assertTrue(summary.halted)
        self.assertEqual(summary.results["t2"]["skip_reason"], "run_halted")
        later = self.box.run(self.registry, ["t1"], mode="write")
        self.assertEqual(later.results["t1"]["skip_reason"], "preflight_failed")

    def test_ce03_unrecordable_error_still_halts(self):
        final = lambda obj: obj["tasks"].get("t1") in ("success", "failed")
        with mock.patch.object(atomic, "atomic_write_json", side_effect=self.failing_state_writes(final)):
            summary = self.box.run(self.registry, ["t1", "t2"], mode="dry_run")
        self.assertTrue(summary.halted)
        self.assertNotIn("t1", summary.results)
        self.assertEqual(summary.not_run, ["t2"])
        self.assertTrue(any("CONTROLLER_ERROR_UNRECORDED" in e for e in summary.errors))
        report = controller.check_promotion(summary.run_dir)["t1"]
        self.assertFalse(report["promotable"])
        self.assertIn("STATE_NOT_SUCCESS", report["reasons"])


class PromotionEvidenceTest(SandboxTest):
    """PR-01..05: missing or unverifiable evidence makes results not promotable."""

    def setUp(self):
        super(PromotionEvidenceTest, self).setUp()
        registry = self.box.registry("t1")
        self.box.run(registry, ["t1"], mode="dry_run")
        self.summary = self.box.run(registry, ["t1"], mode="write")
        self.run_dir = self.summary.run_dir
        self.assertTrue(controller.check_promotion(self.run_dir)["t1"]["promotable"])

    def reasons(self):
        report = controller.check_promotion(self.run_dir)["t1"]
        self.assertFalse(report["promotable"])
        return report["reasons"]

    def test_pr01_manifest_missing(self):
        os.remove(os.path.join(self.run_dir, "backup", "t1.manifest.json"))
        self.assertIn("MANIFEST_MISSING", self.reasons())

    def test_pr02_backup_file_changed_or_missing(self):
        manifest = atomic.read_json_strict(os.path.join(self.run_dir, "backup", "t1.manifest.json"))
        changed, missing = manifest[0], manifest[1]
        os.chmod(changed["backup_path"], 0o644)
        with open(changed["backup_path"], "ab") as handle:
            handle.write(b"x")
        os.remove(missing["backup_path"])
        found = self.reasons()
        self.assertIn("BACKUP_CHANGED:%s" % changed["rel"], found)
        self.assertIn("BACKUP_MISSING:%s" % missing["rel"], found)

    def test_pr03_result_not_verified_by_controller(self):
        path = os.path.join(self.run_dir, "results", "t1.result.json")
        doc = atomic.read_json_strict(path)
        doc["verified_by_controller"] = False
        results.write_result(path, doc)
        self.assertIn("NOT_VERIFIED", self.reasons())

    def test_pr04_result_file_damaged(self):
        with open(os.path.join(self.run_dir, "results", "t1.result.json"), "wb") as handle:
            handle.write(b'{"status": "success"')
        self.assertIn("RESULT_INVALID", self.reasons())

    def test_pr05_job_identity_mismatch(self):
        path = os.path.join(self.run_dir, "jobs", "t1.job.json")
        job = atomic.read_json_strict(path)
        job["run_nonce"] = "e" * 32
        atomic.atomic_write_json(path, job)
        self.assertIn("RESULT_STALE", self.reasons())


if __name__ == "__main__":
    unittest.main()
