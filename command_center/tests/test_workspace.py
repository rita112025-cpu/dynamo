"""WS-01..05 run folders, backups and work copies; NC-01..02 run_nonce;
RR-01..06 work root checks (Windows rules checked with flavor="nt")."""
import os
import re
import secrets
import shutil
import unittest
from unittest import mock

from bbcc import atomic, workspace
from tests.helpers import SandboxTest, snapshot


class RunFolderTest(SandboxTest):
    def test_ws01_unique_run_ids(self):
        ids = set()
        for _ in range(1000):
            created = workspace.create_run_dir(self.box.runs_root)
            self.assertTrue(workspace.is_run_id(created["run_id"]))
            ids.add(created["run_id"])
        self.assertEqual(len(ids), 1000)

    def test_ws02_existing_run_dir_not_reused(self):
        calls = []

        def mkdir(path):
            calls.append(path)
            if len(calls) == 1:
                os.makedirs(path)
                with open(os.path.join(path, "keep.txt"), "wb") as handle:
                    handle.write(b"someone else's run")
                raise FileExistsError(path)
            os.mkdir(path)

        created = workspace.create_run_dir(self.box.runs_root, mkdir=mkdir)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(created["run_dir"], calls[0])
        with open(os.path.join(calls[0], "keep.txt"), "rb") as handle:
            self.assertEqual(handle.read(), b"someone else's run")
        self.assertFalse(os.path.exists(os.path.join(calls[0], "jobs")))

    def test_ws03_backup_matches_and_original_untouched(self):
        before = snapshot(self.box.models)
        files = workspace.list_target_files(self.box.models, "*.rvt")
        backups = workspace.backup_files(self.box.models, files, os.path.join(self.box.root, "bk"))
        for entry in backups:
            self.assertEqual(atomic.sha256_file(entry["backup_path"]), entry["sha256"])
            self.assertEqual(atomic.sha256_file(entry["original_path"]), entry["sha256"])
        self.assertEqual(snapshot(self.box.models), before)

    def test_ws04_work_copy_comes_from_backup(self):
        copies = []

        def recording_copy(src, dst):
            copies.append((src, dst))
            return shutil.copy2(src, dst)

        registry = self.box.registry("t1")
        summary = self.box.run(registry, ["t1"], options=self.box.options(copy=recording_copy))
        self.assertEqual(summary.status("t1"), "success")
        work_root = os.path.join(summary.run_dir, "work") + os.sep
        backup_root = os.path.join(summary.run_dir, "backup") + os.sep
        to_work = [(s, d) for s, d in copies if d.startswith(work_root)]
        self.assertEqual(len(to_work), 2)
        for src, _ in to_work:
            self.assertTrue(src.startswith(backup_root), src)

    def test_ws05_full_flow_leaves_official_folder_unchanged(self):
        before = snapshot(self.box.models)
        registry = self.box.registry("t1")
        self.box.run(registry, ["t1"], mode="dry_run")
        summary = self.box.run(registry, ["t1"], mode="write")
        self.assertEqual(summary.status("t1"), "success")
        self.assertEqual(snapshot(self.box.models), before)


class NonceTest(SandboxTest):
    def test_nc01_nonce_comes_from_secrets(self):
        real = secrets.token_hex
        fixed = "0123456789abcdef0123456789abcdef"

        def fake(n=None):
            return fixed if n == 16 else real(n)

        with mock.patch.object(workspace.secrets, "token_hex", side_effect=fake) as patched:
            registry = self.box.registry("t1")
            summary = self.box.run(registry, ["t1"])
        self.assertIn(mock.call(16), patched.call_args_list)
        job = atomic.read_json_strict(os.path.join(summary.run_dir, "jobs", "t1.job.json"))
        self.assertEqual(job["run_nonce"], fixed)
        self.assertRegex(job["run_nonce"], r"^[0-9a-f]{32}$")

    def test_nc02_nonces_are_unique(self):
        values = set(workspace.new_run_nonce() for _ in range(1000))
        self.assertEqual(len(values), 1000)
        self.assertTrue(all(re.match(r"^[0-9a-f]{32}$", v) for v in values))


class RunsRootTest(unittest.TestCase):
    ENV = {"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local"}

    def check(self, path, environ=None, drive="fixed"):
        return workspace.resolve_runs_root(path, environ if environ is not None else self.ENV,
                                           drive_type=lambda p: drive, flavor="nt")

    def assertCode(self, code, *args, **kwargs):
        with self.assertRaises(workspace.ConfigError) as ctx:
            self.check(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)

    def test_rr01_default_under_localappdata(self):
        self.assertEqual(self.check(None), "C:\\Users\\u\\AppData\\Local\\BIMBatchCommandCenter")

    def test_rr02_missing_localappdata(self):
        self.assertCode("LOCALAPPDATA_MISSING", None, environ={})

    def test_rr03_unc_rejected(self):
        self.assertCode("ROOT_UNC", "\\\\srv\\share\\bbcc")

    def test_rr04_sync_folders_rejected(self):
        env = dict(self.ENV, OneDrive="C:\\Users\\u\\OneDrive")
        self.assertCode("ROOT_SYNC_FOLDER", "C:\\Users\\u\\OneDrive\\bbcc", environ=env)
        self.assertCode("ROOT_SYNC_FOLDER", "D:\\Dropbox\\runs")

    def test_rr05_network_drive_rejected_local_accepted(self):
        self.assertCode("ROOT_REMOTE_DRIVE", "Z:\\bbcc", drive="remote")
        self.assertEqual(self.check("D:\\bbcc", drive="fixed"), "D:\\bbcc")

    def test_rr06_relative_path_rejected(self):
        self.assertCode("ROOT_NOT_ABSOLUTE", "runs")



class RealPathTest(SandboxTest):
    """RJ-01..02: the work root is also checked after resolving symbolic links."""

    def link_or_skip(self, target, link):
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symbolic links not available on this platform: %s" % exc)

    def test_rj01_link_resolving_into_target_folder(self):
        inner = os.path.join(self.box.models, "inner")
        os.makedirs(inner)
        alias = os.path.join(self.box.root, "alias_root")
        self.link_or_skip(inner, alias)
        with self.assertRaises(workspace.ConfigError) as ctx:
            workspace.check_runs_root(alias, {}, lambda p: None, [self.box.models])
        self.assertEqual(ctx.exception.code, "ROOT_INSIDE_TARGET")

    def test_rj02_link_resolving_into_sync_folder(self):
        real = os.path.join(self.box.root, "Dropbox", "real")
        os.makedirs(real)
        alias = os.path.join(self.box.root, "alias")
        self.link_or_skip(real, alias)
        with self.assertRaises(workspace.ConfigError) as ctx:
            workspace.check_runs_root(os.path.join(alias, "bbcc"), {}, lambda p: None, [])
        self.assertEqual(ctx.exception.code, "ROOT_SYNC_FOLDER")


if __name__ == "__main__":
    unittest.main()
