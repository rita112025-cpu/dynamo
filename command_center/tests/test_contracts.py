"""CT-01 .. CT-10: task contract format, semantics and the MVP plan check."""
import os
import unittest

from bbcc import contracts
from tests.helpers import SandboxTest, contract_dict


class ContractTest(SandboxTest):
    def load(self, data):
        return contracts.load_contract(self.box.write_contract(data, "c.task.json"))

    def assertRejected(self, data, needle):
        with self.assertRaises(contracts.ContractError) as ctx:
            self.load(data)
        self.assertIn(needle, str(ctx.exception))

    def test_ct01_valid_contract_loads(self):
        loaded = self.load(contract_dict("t1"))
        self.assertEqual(loaded.task_id, "t1")
        self.assertEqual(loaded.task_version, "1.0.0")
        self.assertRegex(loaded.sha256, r"^[0-9a-f]{64}$")

    def test_ct02_missing_task_version(self):
        data = contract_dict()
        del data["task_version"]
        self.assertRejected(data, "task_version")

    def test_ct03_bad_task_version_format(self):
        data = contract_dict()
        data["task_version"] = "1.0"
        self.assertRejected(data, "task_version")

    def test_ct04_bad_task_id_pattern(self):
        for bad in ("Batch-SCADA", "batch_scada"):
            with self.subTest(task_id=bad):
                data = contract_dict()
                data["task_id"] = bad
                self.assertRejected(data, "task_id")

    def test_ct05_entry_path_escape_or_drive(self):
        for bad in ("../tools/x.dyn", "C:\\tools\\x.dyn", "tools\\..\\..\\x.dyn"):
            with self.subTest(path=bad):
                data = contract_dict()
                data["entry"]["path"] = bad
                self.assertRejected(data, "entry.path")

    def test_ct06_modifies_models_requires_backup(self):
        data = contract_dict()
        data["requires_backup"] = False
        self.assertRejected(data, "requires_backup")

    def test_ct07_write_switch_default_true(self):
        data = contract_dict()
        data["inputs"][1]["default"] = True
        self.assertRejected(data, "write_switch")

    def test_ct08_unknown_field(self):
        data = contract_dict()
        data["surprise"] = 1
        self.assertRejected(data, "surprise")

    def test_ct09_required_task_not_selected(self):
        registry = self.box.registry("t1", ("t2", ["t1"], []))
        with self.assertRaises(contracts.PlanError) as ctx:
            self.box.run(registry, ["t2"])
        self.assertEqual(ctx.exception.code, "dependency_not_selected")
        self.assertFalse(os.path.exists(os.path.join(self.box.runs_root, "runs")))

    def test_ct10_conflicting_tasks_selected(self):
        registry = self.box.registry(("t1", [], ["t2"]), "t2")
        with self.assertRaises(contracts.PlanError) as ctx:
            self.box.run(registry, ["t1", "t2"])
        self.assertEqual(ctx.exception.code, "CONFLICT")
        self.assertFalse(os.path.exists(os.path.join(self.box.runs_root, "runs")))


if __name__ == "__main__":
    unittest.main()
