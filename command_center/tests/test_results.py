"""RS-01..11 result contract, ST-01..03 state machine, PE-01..05 output path escape,
AW-01..03 atomic replace retries on Windows-style errors."""
import errno
import json
import os
import threading
import unittest
from unittest import mock

from bbcc import atomic, controller, results
from tests.helpers import SandboxTest, override, valid_result


class ResultContractTest(unittest.TestCase):
    def problems(self, **changes):
        return results.validate_result(valid_result(**changes))

    def test_rs01_valid_success(self):
        self.assertEqual(self.problems(), [])

    def test_rs02_success_with_errors(self):
        self.assertTrue(self.problems(errors=[{"code": "BAD_THING", "message": "x"}]))

    def test_rs03_failed_without_failure_class(self):
        self.assertTrue(self.problems(status="failed", errors=[{"code": "BAD_THING", "message": "x"}]))

    def test_rs04_skipped_without_reason(self):
        self.assertTrue(self.problems(status="skipped", started_at=None, items_processed=0,
                                      items_modified=0, written_by="controller"))

    def test_rs05_dry_run_cannot_modify(self):
        self.assertTrue(self.problems(mode="dry_run", items_modified=1))

    def test_rs06_modified_exceeds_processed(self):
        self.assertTrue(self.problems(items_processed=1, items_modified=2))

    def test_rs07_time_needs_offset(self):
        for value in ("2026-11-11T09:30:00Z", "2026-11-11T09:30:00"):
            with self.subTest(value=value):
                found = self.problems(started_at=value)
                self.assertTrue(found)
                self.assertTrue(any("+HH:MM" in p for p in found))

    def test_rs08_output_without_sha256(self):
        self.assertTrue(self.problems(output_files=[{"path": "report.txt", "size": 2}]))


class AtomicWriteTest(SandboxTest):
    def target(self):
        path = os.path.join(self.box.root, "result.json")
        with open(path, "wb") as handle:
            handle.write(b"OLD")
        return path

    def tmp_files(self):
        return [n for n in os.listdir(self.box.root) if n.endswith(".tmp")]

    def test_rs09_non_retryable_replace_error_keeps_old_file(self):
        path = self.target()
        calls = []

        def broken(src, dst):
            calls.append(src)
            raise OSError(errno.EIO, "disk error")

        with self.assertRaises(atomic.AtomicWriteError):
            atomic.atomic_write_json(path, {"a": 1}, replace=broken, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"OLD")
        self.assertEqual(self.tmp_files(), [])

    def test_rs10_write_then_read_roundtrip(self):
        path = os.path.join(self.box.root, "r.json")
        doc = valid_result()
        results.write_result(path, doc)
        self.assertEqual(results.read_result(path), doc)

    def test_rs11_bom_is_rejected(self):
        path = os.path.join(self.box.root, "bom.json")
        with open(path, "wb") as handle:
            handle.write(b"\xef\xbb\xbf" + json.dumps(valid_result()).encode("utf-8"))
        with self.assertRaises(ValueError) as ctx:
            results.read_result(path)
        self.assertIn("BOM", str(ctx.exception))

    def test_aw01_permission_error_retried_then_succeeds(self):
        path = self.target()
        attempts, sleeps = [], []

        def flaky(src, dst):
            attempts.append(src)
            if len(attempts) <= 2:
                raise PermissionError(13, "in use")
            os.replace(src, dst)

        atomic.atomic_write_json(path, {"ok": True}, replace=flaky, sleep=sleeps.append)
        self.assertEqual(atomic.read_json_strict(path), {"ok": True})
        self.assertEqual(sleeps, [0.1, 0.2])
        self.assertEqual(self.tmp_files(), [])

    def test_aw02_permission_error_every_time(self):
        path = self.target()
        attempts, sleeps = [], []

        def locked(src, dst):
            attempts.append(src)
            raise PermissionError(13, "in use")

        with self.assertRaises(atomic.AtomicWriteError) as ctx:
            atomic.atomic_write_json(path, {"ok": True}, replace=locked, sleep=sleeps.append)
        self.assertEqual(len(attempts), 5)
        self.assertEqual(sleeps, [0.1, 0.2, 0.4, 0.8])
        self.assertIn(path, str(ctx.exception))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"OLD")
        self.assertEqual(self.tmp_files(), [])

    def test_aw03_tmp_is_in_target_folder(self):
        path = self.target()
        seen = []

        def record(src, dst):
            seen.append(src)
            os.replace(src, dst)

        atomic.atomic_write_json(path, {"ok": True}, replace=record)
        self.assertEqual(os.path.dirname(seen[0]), os.path.dirname(os.path.abspath(path)))
        self.assertRegex(os.path.basename(seen[0]), r"^result\.json\.[0-9a-f]{8}\.tmp$")


class StateMachineTest(unittest.TestCase):
    def test_st01_legal_transitions(self):
        for old, new in [(None, "pending"), ("pending", "skipped"), ("pending", "running"),
                         ("running", "success"), ("running", "failed"), ("running", "interrupted")]:
            with self.subTest(old=old, new=new):
                results.check_transition(old, new)

    def test_st02_illegal_transitions(self):
        for old, new in [("success", "running"), ("failed", "success"), ("pending", "success"),
                         ("skipped", "running")]:
            with self.subTest(old=old, new=new):
                with self.assertRaises(results.InvalidTransition):
                    results.check_transition(old, new)

    def test_st03_final_states(self):
        self.assertEqual(results.FINAL_STATES, {"success", "failed", "skipped", "interrupted"})


class PathEscapeTest(SandboxTest):
    def run_with_output(self, path, data=b"ok", create=None):
        def behaviour(job, stop_event):
            if create:
                create(job)
            controller.write_task_result(job, outputs=[("report.txt", b"ok")], overrides={
                "output_files": [{"path": path, "sha256": atomic.sha256_bytes(data), "size": len(data)}]})
        registry = self.box.registry("t1", "t2")
        return self.box.run(registry, ["t1", "t2"], runner=controller.FakeRunner({"t1": behaviour}))

    def assertEscape(self, summary):
        doc = summary.results["t1"]
        self.assertEqual((doc["status"], doc["failure_class"]), ("failed", "verification"))
        self.assertEqual(doc["errors"][0]["code"], "RESULT_PATH_ESCAPE")
        self.assertTrue(summary.halted)
        self.assertEqual(summary.results["t2"]["skip_reason"], "run_halted")

    def test_pe01_parent_segments(self):
        self.assertEscape(self.run_with_output("..\\..\\x.rvt"))

    def test_pe02_drive_and_unc(self):
        for path in ("C:\\x.rvt", "\\\\srv\\s\\x.rvt"):
            with self.subTest(path=path):
                self.assertEscape(self.run_with_output(path))

    def test_pe03_alternate_data_stream(self):
        self.assertEscape(self.run_with_output("out.rvt:stream"))

    def test_pe04_symlink_leaving_staging(self):
        outside = os.path.join(self.box.root, "outside.rvt")
        with open(outside, "wb") as handle:
            handle.write(b"ok")
        probe = os.path.join(self.box.root, "probe_link")
        try:
            os.symlink(outside, probe)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symbolic links not available on this platform: %s" % exc)
        os.remove(probe)

        def make_link(job):
            os.symlink(outside, os.path.join(job["staging_dir"], "link.rvt"))

        self.assertEscape(self.run_with_output("link.rvt", create=make_link))

    def test_pe06_dotdot_rule_works_without_realpath(self):
        # With realpath neutralised, only the '..' rule can reject these paths, so this
        # test fails if that rule is removed (the realpath layer cannot mask it).
        root = os.path.join(self.box.root, "allowed")
        os.makedirs(root)
        with mock.patch.object(results.os.path, "realpath", side_effect=lambda p: p):
            for bad in ("..\\x.rvt", "../x.rvt", "sub\\..\\..\\x.rvt"):
                with self.subTest(path=bad):
                    with self.assertRaises(results.PathEscape):
                        results.resolve_output_path(bad, root)
            inside = results.resolve_output_path("sub\\..\\out.rvt", root)
            self.assertEqual(inside, os.path.join(root, "out.rvt"))

    def make_dir_link(self, target, link):
        """Directory symlink; on Windows without symlink privilege (WinError 1314) a
        junction, which needs no administrator rights."""
        try:
            os.symlink(target, link, target_is_directory=True)
            return
        except (OSError, NotImplementedError):
            pass
        if os.name == "nt":
            try:
                import _winapi
                _winapi.CreateJunction(target, link)
                return
            except Exception as exc:
                self.skipTest("cannot create a symlink or junction: %s" % exc)
        self.skipTest("directory links are not available on this platform")

    def test_pe07_directory_link_or_junction_leaving_staging(self):
        outside = os.path.join(self.box.root, "outside_dir")
        os.makedirs(outside)
        with open(os.path.join(outside, "out.rvt"), "wb") as handle:
            handle.write(b"ok")

        def make_link(job):
            self.make_dir_link(outside, os.path.join(job["staging_dir"], "linkdir"))

        self.assertEscape(self.run_with_output("linkdir\\out.rvt", create=make_link))

    def test_pe05_relative_path_inside_staging(self):
        def behaviour(job, stop_event):
            controller.write_task_result(job, outputs=[("sub\\out.rvt", b"data")])
        registry = self.box.registry("t1")
        summary = self.box.run(registry, ["t1"], runner=controller.FakeRunner({"t1": behaviour}))
        self.assertEqual(summary.status("t1"), "success")
        self.assertTrue(os.path.isfile(os.path.join(summary.run_dir, "staging", "t1", "sub", "out.rvt")))



class ExclusiveCreateTest(SandboxTest):
    """AT-01..02: write_new_json never overwrites, even when an existence check is raced."""

    def test_at01_exclusive_even_if_check_is_raced(self):
        path = os.path.join(self.box.root, "record.json")
        with open(path, "wb") as handle:
            handle.write(b"OLD")
        with mock.patch.object(atomic.os.path, "exists", return_value=False):
            with self.assertRaises(FileExistsError):
                atomic.write_new_json(path, {"new": 1})
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"OLD")
        self.assertEqual([n for n in os.listdir(self.box.root) if n.endswith(".tmp")], [])

    def test_at02_concurrent_writers_one_winner(self):
        path = os.path.join(self.box.root, "record.json")
        barrier = threading.Barrier(8)
        outcome = {}

        def writer(n):
            barrier.wait()
            try:
                atomic.write_new_json(path, {"writer": n, "pad": "x" * 20000})
                outcome[n] = "won"
            except FileExistsError:
                outcome[n] = "exists"

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners = [n for n, o in outcome.items() if o == "won"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(atomic.read_json_strict(path), {"writer": winners[0], "pad": "x" * 20000})
        self.assertEqual([n for n in os.listdir(self.box.root) if n.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
