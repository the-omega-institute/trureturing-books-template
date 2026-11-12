"""ci.yml's slow-frame run of the visualization browser suites (viz-slow): weekly and by hand, never on a PR.

The job conditions are evaluated with the expression subset of test_verification.gha_if; a workflow cannot be
triggered from here, so these tests read what the workflow says, not what GitHub did with it."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_verification import gha_if

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
OWN = "the-omega-institute/books/.github/workflows/ci.yml@refs/heads/main"
CALLER = "the-omega-institute/books/.github/workflows/release.yml@refs/heads/main"


def job(name: str) -> str:
    """The text of one job of ci.yml (its lines up to the next job)."""
    text = CI.read_text(encoding="utf-8")
    m = re.search(rf"^  {re.escape(name)}:\n((?:(?:    .*)?\n)*)", text, re.M)
    assert m, f"ci.yml has no job {name}"
    return m.group(1)


def job_if(name: str) -> str:
    """A job's ``if:``, a folded ``>-`` value joined into one line ('' when absent)."""
    m = re.search(r"^    if:\s*(>-)?\s*(.*)$((?:\n      .*)*)", job(name), re.M)
    return " ".join([m.group(2), *m.group(3).split()]).strip() if m else ""


def runs(name: str, event: str, *, ref: str = OWN, slow=None) -> bool:
    cond = job_if(name)
    return True if not cond else gha_if(cond, event=event, ref="refs/heads/main",
                                        context={"github.workflow_ref": ref, "inputs.slow_frames": slow})


class VizSlow(unittest.TestCase):
    def test_runs_weekly_and_by_hand_only(self):
        self.assertTrue(runs("viz-slow", "schedule"))
        self.assertTrue(runs("viz-slow", "workflow_dispatch", slow=True))
        for event, kw in (("pull_request", {}), ("push", {}), ("workflow_dispatch", {"slow": False}),
                          ("schedule", {"ref": CALLER}), ("workflow_dispatch", {"ref": CALLER}),
                          ("push", {"ref": CALLER})):
            with self.subTest(event=event, **kw):
                self.assertFalse(runs("viz-slow", event, **kw))

    def test_weekly_run_does_nothing_else(self):
        self.assertFalse(runs("check", "schedule"))
        for event in ("pull_request", "push", "workflow_dispatch"):
            self.assertTrue(runs("check", event, slow=True), event)
        self.assertTrue(runs("check", "schedule", ref=CALLER), "a caller's schedule runs the checks")
        for name in ("build", "viz", "media", "films"):
            self.assertRegex(job(name), r"(?m)^    needs: check$", f"{name} is skipped with check")

    def test_scheduled_once_a_week(self):
        text = CI.read_text(encoding="utf-8")
        crons = re.findall(r"^\s+- cron:\s*'([^']+)'", text, re.M)
        self.assertEqual(len(crons), 1, crons)
        minute, hour, dom, month, dow = crons[0].split()
        self.assertTrue(minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow.isdigit(), crons)
        self.assertIn("slow_frames:", text)
        self.assertRegex(text, r"(?m)^  group: .*github\.event_name == 'schedule'",
                         "a push to main must not cancel the weekly run")

    def test_same_shards_as_viz_with_slow_frames(self):
        shards = lambda j: re.search(r"shard: \[([\d, ]+)\]", job(j)).group(1)  # noqa: E731
        self.assertEqual(shards("viz-slow"), shards("viz"))
        n = len(shards("viz").split(","))
        self.assertIn(f"node tools/node/viz-test.mjs --slow --shard ${{{{ matrix.shard }}}}/{n}", job("viz-slow"))
        self.assertIn(f"node tools/node/viz-test.mjs --shard ${{{{ matrix.shard }}}}/{n}", job("viz"))
        self.assertNotIn("--slow", job("viz"))


if __name__ == "__main__":
    unittest.main()
