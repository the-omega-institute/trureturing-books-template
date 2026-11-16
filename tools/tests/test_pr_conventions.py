"""PR metadata checks cover forks, automation and adoption of existing PRs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from ci import pr_conventions as policy


class PullRequestConventionsTests(unittest.TestCase):
    def test_workflow_reads_current_target_even_when_the_pr_predates_adoption(self):
        path = Path(__file__).resolve().parents[2] / ".github/workflows/pr-conventions.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertIn("pull_request", workflow["on"])
        self.assertNotIn("pull_request_target", workflow["on"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        steps = workflow["jobs"]["conventions"]["steps"]
        checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
        # An existing PR's base SHA can precede the checker. Follow the current
        # target branch, while keeping the untrusted head out of the checkout.
        self.assertEqual(checkout["with"]["ref"], "${{ github.event.pull_request.base.ref }}")
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        self.assertEqual(checkout["with"]["sparse-checkout"], "tools/ci/pr_conventions.py")
        self.assertEqual([step["run"] for step in steps if "run" in step], ["python3 tools/ci/pr_conventions.py"])

    def pr(self, title="fix(ch19): 修正证明范围", branch="fix/ch19-proof-scope", created="2026-11-17T00:00:00Z"):
        return {"title": title, "head": {"ref": branch}, "created_at": created}

    def test_regular_fork_and_automation_metadata(self):
        for title, branch in (
            ("docs: Clarify the source", "docs/123-source-location"),
            ("feat(export)!: 调整目录", "feat/export-layout"),
            ("chore(template): upstream 1.2.1 → 1.3.0 [conflicts]", "template-update/1.3.0"),
            ("chore(template): layer beta", "template-update/academic/v1.3.0-beta.1"),
            ("chore(trureturing): pin abcdef123456 [review statements]", "trureturing-bump/abcdef123456"),
        ):
            with self.subTest(branch=branch):
                pr = self.pr(title, branch)
                pr["head"]["repo"] = {"fork": True}
                self.assertEqual(policy.validate(pr), [])

    def test_invalid_titles_and_branch_names(self):
        for title in ("Fix an error", "Fix: error", "fix: ", " fix: error", "fix: error ",
                      "fix: one\ntwo", "fix(Scope): error", "fix: " + "x" * 96):
            with self.subTest(title=title):
                self.assertTrue(policy.validate(self.pr(title=title)))
        for branch in ("main", "quick-fix", "fix/Some-topic", "fix/a--b", "fix/a/b", "fix/-a",
                       "template-update/anything", "template-update/layer/no-version", "trureturing-bump/abc"):
            with self.subTest(branch=branch):
                self.assertTrue(policy.validate(self.pr(branch=branch)))

    def test_existing_prs_are_exempt_only_before_the_configured_utc_cutoff(self):
        pr = self.pr("Historical title", "old-branch", "2026-11-16T15:59:59Z")
        self.assertEqual(policy.validate(pr, "2026-11-16T16:00:00Z"), [])
        self.assertEqual(len(policy.validate(pr)), 2)
        pr["created_at"] = "2026-11-16T16:00:00Z"
        self.assertEqual(len(policy.validate(pr, "2026-11-16T16:00:00Z")), 2)
        for cutoff in ("invalid", "2026-11-16T16:00:00", "2026-11-16T16:00:00+08:00"):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                policy.validate(pr, cutoff)

    def test_cli_rejects_missing_payload_and_keeps_untrusted_titles_out_of_annotations(self):
        script = Path(policy.__file__)
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            for payload, expected in (({"pull_request": self.pr()}, 0), ({}, 1),
                                      ({"pull_request": self.pr("$(touch injected)\n::warning::untrusted")}, 1)):
                event.write_text(json.dumps(payload), encoding="utf-8")
                run = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                                     env={**os.environ, "GITHUB_EVENT_PATH": str(event), "PR_CONVENTIONS_SINCE": ""})
                self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
                self.assertNotIn("::warning::untrusted", run.stdout)
