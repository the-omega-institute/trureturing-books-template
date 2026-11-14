"""Slow profile event semantics and dynamic CI wiring (execution selection lives in the planner)."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from test_ci_performance import planner

CI = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"


class VizSlow(unittest.TestCase):
    def test_schedule_only_slow_and_callers_control_their_profile(self):
        self.assertEqual(planner.event_profiles("schedule", True), ["slow"])
        self.assertEqual(planner.event_profiles("schedule", False), ["normal", "films"])
        self.assertEqual(planner.event_profiles("workflow_dispatch", True, True), ["normal", "films", "slow"])
        for event in ("pull_request", "push", "workflow_call"):
            self.assertEqual(planner.event_profiles(event, True), ["normal", "films"])
        self.assertEqual(planner.event_profiles("workflow_call", False, True), ["normal", "films", "slow"])

    def test_weekly_and_manual_entries_use_the_same_plan_before_setup(self):
        text = CI.read_text()
        crons = re.findall(r"^\s+- cron:\s*'([^']+)'", text, re.M)
        self.assertEqual(crons, ['29 3 * * 3'])
        self.assertIn("slow_frames:", text)
        self.assertRegex(text, r"(?m)^  group: .*github\.event_name == 'schedule'")
        self.assertIn("matrix: ${{ fromJSON(needs.plan.outputs.slow_matrix) }}", text)
        self.assertIn("matrix: ${{ fromJSON(needs.plan.outputs.viz_matrix) }}", text)
        self.assertIn("node tools/node/viz-test.mjs --slow --selection-env CI_ITEMS", text)
        self.assertIn("node tools/node/viz-test.mjs --selection-env CI_ITEMS", text)
        self.assertNotIn("shard: [1", text)

    def test_dynamic_profiles_have_the_same_disjoint_partition_rule(self):
        for size in (0, 1, 7, 61):
            items = [str(i) for i in range(size)]
            self.assertEqual(planner.shards(items, 8), planner.shards(reversed(items), 8))
            self.assertEqual(sum(len(p["items"]) for p in planner.shards(items, 8)), size)


if __name__ == "__main__":
    unittest.main()
