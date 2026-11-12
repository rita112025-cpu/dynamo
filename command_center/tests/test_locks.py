"""LK-01..07: target-folder locks and the manual stale-lock release."""
import os
import threading
import unittest
from unittest import mock

from bbcc import atomic, locks
from tests.helpers import HOST, SandboxTest

OLD_RUN = "20261111-000000-abcdef12"


class LockBase(SandboxTest):
    """Shared helpers only; contains no tests (so subclasses do not re-run each other)."""

    def path(self):
        return locks.lock_path(self.box.runs_root, self.box.models)

    def plant(self, data=None, raw=None):
        path = self.path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = raw if raw is not None else atomic.json_bytes(data)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path, payload

    def lock_info(self, **changes):
        info = {"lock_version": "1", "run_id": OLD_RUN, "pid": 4242, "host": HOST,
                "started_at": "2026-11-11T00:00:00+08:00", "run_dir": os.path.join(self.box.root, "old_run"),
                "target_root": self.box.models, "controller_version": "0.1.0"}
        info.update(changes)
        return info

    def acquire(self, alive=True):
        return locks.acquire(self.box.runs_root, self.box.models, "20261111-120000-00000001",
                             self.box.root, host=HOST, pid_alive=lambda pid: alive)

    def assertBusy(self, kind, alive):
        path = self.path()
        before = locks.read_lock_bytes(path)
        with self.assertRaises(locks.LockBusy) as ctx:
            self.acquire(alive)
        self.assertEqual(ctx.exception.kind, kind)
        self.assertEqual(locks.read_lock_bytes(path), before)



class LockTest(LockBase):
    def test_lk01_acquire_free_lock(self):
        handle = self.acquire()
        info = atomic.read_json_strict(handle.path)
        for key in ("run_id", "pid", "host", "started_at", "run_dir", "target_root"):
            self.assertIn(key, info)
        self.assertEqual(info["run_id"], "20261111-120000-00000001")

    def test_lk02_two_threads_one_winner(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(n):
            barrier.wait()
            try:
                locks.acquire(self.box.runs_root, self.box.models, "20261111-120000-0000000%d" % n,
                              self.box.root, host=HOST, pid_alive=lambda pid: True)
                outcomes.append("won")
            except locks.LockBusy:
                outcomes.append("busy")

        threads = [threading.Thread(target=worker, args=(n,)) for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcomes), ["busy", "won"])

    def test_lk03_unreadable_lock_is_conflict(self):
        self.plant(raw=b"{not json")
        self.assertBusy(locks.LOCK_CONFLICT, alive=False)

    def test_lk04_other_host_is_conflict(self):
        self.plant(self.lock_info(host="other-pc"))
        self.assertBusy(locks.LOCK_CONFLICT, alive=False)

    def test_lk05_same_host_live_pid_is_conflict(self):
        self.plant(self.lock_info())
        self.assertBusy(locks.LOCK_CONFLICT, alive=True)

    def test_lk06_same_host_dead_pid_is_stale(self):
        self.plant(self.lock_info())
        self.assertBusy(locks.LOCK_STALE, alive=False)

    def test_lk07_manual_release_checks_run_id(self):
        old_run = os.path.join(self.box.root, "old_run")
        os.makedirs(os.path.join(old_run, "results"))
        atomic.atomic_write_json(os.path.join(old_run, "plan.json"), {
            "plan_version": "1", "run_id": OLD_RUN, "created_at": "2026-11-11T00:00:00+08:00",
            "mode": "dry_run", "tasks": [{"task_id": "a1", "task_version": "1.0.0"}]})
        path, payload = self.plant(self.lock_info())
        with self.assertRaises(locks.LockReleaseRefused):
            locks.release_stale_lock(self.box.runs_root, path, "20261111-000000-ffffffff", "checked",
                                     host=HOST, pid_alive=lambda pid: False)
        self.assertEqual(locks.read_lock_bytes(path), payload)
        dest = locks.release_stale_lock(self.box.runs_root, path, OLD_RUN, "PC crashed; checked by hand",
                                        host=HOST, pid_alive=lambda pid: False)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.isfile(dest))
        self.assertEqual(os.path.dirname(dest), os.path.join(self.box.runs_root, "locks", "released"))
        record = atomic.read_json_strict(dest[:-len(".lock")] + ".release.json")
        self.assertEqual(record["reason"], "PC crashed; checked by hand")
        backfilled = atomic.read_json_strict(os.path.join(old_run, "results", "a1.result.json"))
        self.assertEqual(backfilled["status"], "interrupted")
        self.assertEqual(backfilled["errors"][0]["code"], "RESULT_MISSING")



class LockReleaseRaceTest(LockBase):
    """LR-01..02: a lock written by someone else during release is never moved or changed."""

    def racing_reader(self, lock_file, intruder):
        real = atomic.read_json_strict
        fired = []

        def read(path):
            data = real(path)
            if not fired and str(path).startswith(lock_file):
                fired.append(path)
                with open(lock_file, "wb") as handle:
                    handle.write(intruder)
            return data
        return read, fired

    def test_lr01_release_own_race_keeps_new_lock(self):
        handle = self.acquire()
        intruder = atomic.json_bytes(self.lock_info(run_id="20261111-130000-0000000a"))
        reader, fired = self.racing_reader(handle.path, intruder)
        with mock.patch.object(atomic, "read_json_strict", side_effect=reader):
            locks.release_own(handle)
        self.assertTrue(fired)
        self.assertEqual(locks.read_lock_bytes(handle.path), intruder)
        released = atomic.read_json_strict(os.path.join(self.box.root, "lock.released"))
        self.assertEqual(released["run_id"], handle.run_id)

    def test_lr02_stale_release_race_keeps_new_lock(self):
        path, payload = self.plant(self.lock_info())
        intruder = atomic.json_bytes(self.lock_info(run_id="20261111-130000-0000000b", pid=5151))
        reader, fired = self.racing_reader(path, intruder)
        with mock.patch.object(atomic, "read_json_strict", side_effect=reader):
            dest = locks.release_stale_lock(self.box.runs_root, path, OLD_RUN, "checked by hand",
                                            host=HOST, pid_alive=lambda pid: False, backfill=False)
        self.assertTrue(fired)
        self.assertEqual(locks.read_lock_bytes(path), intruder)
        self.assertEqual(locks.read_lock_bytes(dest), payload)


if __name__ == "__main__":
    unittest.main()
