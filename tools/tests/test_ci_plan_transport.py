"""Large selection plans retain every responsibility without process-size limits."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from ci import plan as planner
from ci.plan_io import load_plan


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def in_directory(path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def large_plan():
    return {
        "profiles": ["normal"], "sha": "a"*40, "site": False, "publish": True,
        "tasks": {"validate": True, "build": False, "viz": False,
                  "viz-slow": False, "media": False, "films": False},
        "selections": {"normal": {"checks": {"structure": True}, "books": ["one"],
                                  "reasons": ["changed: "+"x"*1000]*200}},
        "coverage": {"normal": {"inherited": None, "paths": ["x"*1000]*200}},
        "execution": {}, "workloads": {}, "viz": [], "slow": [], "films": [],
        "exports": [], "slides": [],
    }


class PlanTransportTest(unittest.TestCase):
    def test_outputs_keep_conditions_small_without_mutating_the_complete_plan(self):
        plan = large_plan()
        original = deepcopy(plan)
        self.assertGreater(len(json.dumps(plan).encode()), 131072)
        with TemporaryDirectory() as temp:
            target = Path(temp)/"outputs"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(target)}, clear=True):
                planner.write_outputs(plan)
            outputs = dict(line.split("=", 1) for line in target.read_text().splitlines())
        control = json.loads(outputs["plan"])
        self.assertLess(len(outputs["plan"].encode()), 4096)
        self.assertEqual(control["selections"]["normal"]["checks"], {"structure": True})
        self.assertEqual(control["profiles"], ["normal"])
        self.assertEqual(control["coverage"], {"normal": True})
        self.assertEqual(json.loads(outputs["validate"]), True)
        self.assertEqual(plan, original)

    def test_complete_file_is_required_and_preserves_large_details(self):
        plan = large_plan()
        with TemporaryDirectory() as temp, in_directory(temp):
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(FileNotFoundError):
                    load_plan()
                Path("ci-plan.json").write_text(json.dumps(plan))
                self.assertEqual(load_plan(), plan)
            custom = Path(temp)/"custom.json"
            custom.write_text(json.dumps(plan))
            with mock.patch.dict(os.environ, {"PLAN_FILE": str(custom)}, clear=True):
                self.assertEqual(load_plan(), plan)

    def test_final_verifier_uses_the_large_file_and_still_rejects_failed_work(self):
        plan = large_plan()
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"ci-plan.json").write_text(json.dumps(plan))
            env = {k:v for k,v in os.environ.items() if k not in {"PLAN_JSON", "PLAN_FILE"}}
            results = {"plan": {"result": "success"}, "validate": {"result": "failure"}}
            env["RESULTS_JSON"] = json.dumps(results)
            command = [sys.executable, str(ROOT/"tools/ci/plan.py"), "--verify"]
            failed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("validate: expected success, got failure", failed.stderr)
            self.assertFalse((root/"coverage").exists())
            results["validate"]["result"] = "success"
            env["RESULTS_JSON"] = json.dumps(results)
            passed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            record = json.loads((root/"coverage/normal.json").read_text())
            self.assertEqual(record["paths"], plan["coverage"]["normal"]["paths"])

    def test_workflows_transfer_the_same_run_plan_before_each_file_consumer(self):
        for name, consumers in [("ci", ["validate", "media", "check"]), ("pages", ["coverage"])]:
            workflow = (ROOT/".github/workflows"/(name+".yml")).read_text()
            jobs = dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:|\Z)", workflow))
            upload = jobs["plan"].split("- name: Retain the complete selection plan", 1)[1]
            self.assertIn("name: tbook-plan\n", upload)
            self.assertIn("path: ci-plan.json\n", upload)
            self.assertIn("overwrite: true", upload)
            self.assertNotIn("run_attempt", upload, "failed-job retries retain the plan")
            for job in consumers:
                spec = jobs[job]
                self.assertNotIn("PLAN_JSON", spec)
                download = spec.index("- name: Download the complete selection plan")
                step = spec[download:].split("- name: ", 2)[1]
                self.assertIn("uses: actions/download-artifact@v7", step)
                self.assertIn("name: tbook-plan\n", step)
                self.assertNotIn("run-id:", step, "never consume another run's plan")
                execution = [m.start() for m in re.finditer(r"tools/ci/run\.py|--verify", spec)]
                self.assertTrue(execution)
                for i in execution:
                    self.assertLess(download, i)
                self.assertNotIn("toJSON(needs)", spec)


if __name__ == "__main__":
    unittest.main()
