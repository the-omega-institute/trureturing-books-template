"""Large CI data travels through runner script files, including the complete needs fanout."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import test_ci_performance as fixtures
from test_verification import GITHUB_DIR, run_bash, workflow_jobs

planner = fixtures.planner
runner = fixtures.ci_module("run")
TOOLS = Path(__file__).resolve().parents[1]


class PlanOutputBudgetTest(unittest.TestCase):
    setUp = fixtures.AffectedPlanTest.setUp
    git = fixtures.AffectedPlanTest.git
    write = fixtures.AffectedPlanTest.write
    commit = fixtures.AffectedPlanTest.commit
    make_plan = fixtures.AffectedPlanTest.make_plan

    def test_browser_shard_cannot_run_duplicate_empty_or_unplanned_classes(self):
        selected = ['test_viz.KeysGate', 'test_viz.RailGate']
        self.assertEqual(runner.browser_selection(selected, selected[:1]), selected[:1])
        for items in ([], [selected[0], selected[0]], ['test_other.Unknown'], {}, [3]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                runner.browser_selection(selected, items)

    def test_plain_film_name_is_selected_without_metadata_identifiers(self):
        self.write("books/one/films/explanation/film.json", json.dumps({"title": "Explanation"}))
        tree = planner.Tree(self.root, self.commit())
        selected = planner.impact(tree, tree, ["books/one/films/explanation/scenes.js"])
        self.assertEqual(selected["films"], ["one/explanation"])

    def outputs(self, plan):
        output, summary = self.root / "output.txt", self.root / "summary.md"
        for path in (output, summary):
            path.write_text("", encoding="utf-8")
        original = copy.deepcopy(plan)
        with mock.patch.dict(os.environ, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary)):
            planner.write_outputs(plan)
        text = output.read_text(encoding="utf-8")
        fields = {k: json.loads(v) for k, v in (line.split("=", 1) for line in text.splitlines())}
        self.assertEqual(fields["plan"], original)
        self.assertEqual(plan, original)
        for field, key in (("build", "exports"), ("viz", "viz"), ("slow", "slow"), ("film", "films"), ('browser', 'browser')):
            self.assertEqual(fields[field + "_matrix"], {"include": plan[key]})
        for key in ("site", "publish"):
            self.assertEqual(fields[key], plan[key])
        for key, value in plan["tasks"].items():
            self.assertEqual(fields[key.replace("-", "_")], value)
        return text, summary.read_text(encoding="utf-8")

    def suites(self, count, patterns):
        names = ["a", "b", *(f"chapter-{i:03}" for i in range(count - 2))]
        for name in names[2:]:
            self.write(f"books/one/viz/tests/{name}.test.mjs", "// suite\n")
        self.write("books/one/viz/tests/dependencies.json", json.dumps({
            "schema": planner.DEPENDENCIES, "suites": {name + ".test.mjs": patterns for name in names}}))
        return sorted(f"books/one/viz/tests/{name}.test.mjs" for name in names)

    def test_single_path_keeps_suite_and_film_trigger_spelling(self):
        path = "books/one/viz/a/model.js"
        self.write(path, "export const n = 2;\n")
        self.commit()
        plan = self.make_plan(event="workflow_dispatch")
        for selected in plan["selections"].values():
            self.assertIn(f"{path} -> suite books/one/viz/tests/a.test.mjs", selected["reasons"])
            self.assertIn(f"{path} -> film one/001-film", selected["reasons"])

    def test_many_chapters_keep_exact_work_and_fit_job_output_limits(self):
        suites = self.suites(80, ["books/one/zh/*.md"])
        paths = [f"books/one/zh/章节-{i:03}.md" for i in range(60)]
        for path in paths:
            self.write(path, "# Chapter\n")
        self.base = self.commit()
        for path in paths:
            self.write(path, "# Revised chapter\n")
        self.commit()
        plan = self.make_plan(event="workflow_dispatch", slow=True)
        self.assertEqual(plan["reasons"], [])
        for profile, selected in plan["selections"].items():
            self.assertEqual(selected["suites"], suites)
            self.assertEqual(selected["books"], ["one"])
            self.assertEqual(selected["films"], [])
            self.assertEqual(selected["slides"], [])
            self.assertEqual(selected["exports"], [
                dict(name="one-" + name, book="one", target=target, variant=variant)
                for name, target, variant in (("html", "html", ""), ("pdf-screen", "pdf", "screen"), ("epub", "epub", ""))])
            self.assertEqual(selected["checks"], dict(unit=False, theme=False, structure=True, viz_static=True,
                                                     slides_static=True, compat=False, manifest=False, browser=False))
            self.assertTrue(selected["site"])
            self.assertEqual(selected["reasons"], sorted(f"{paths[0]} (+59 more) -> suite {suite}" for suite in suites))
            self.assertEqual(plan["coverage"][profile]["paths"], paths)
        for profile, matrix in (("normal", plan["viz"]), ("slow", plan["slow"])):
            self.assertEqual(sorted(plan["execution"][profile]), suites)
            self.assertEqual(sorted(plan["workloads"][profile]), suites)
            self.assertEqual(sorted(item for shard in matrix for item in shard["items"]), suites)
        self.assertEqual(plan["tasks"], dict(validate=True, browser=False, stills=False, build=True, viz=True, **{"viz-slow": True}, media=False, films=False))
        output, summary = self.outputs(plan)
        self.assertIn(paths[0], output)
        self.assertNotIn("\\u7ae0", output)
        self.assertLess(len(output.encode("utf-8")), 200_000)
        self.assertLess(len(output.encode("utf-16-le")), 400_000)
        self.assertLess(len(summary.encode("utf-8")), 900_000)

    def test_five_hundred_paths_coalesce_film_and_resource_diagnostics(self):
        suites = self.suites(200, ["books/one/zh/*.md", "books/one/assets/**"])
        resources = [f"books/one/assets/input-{i:03}.js" for i in range(250)]
        self.write("books/one/films/001-film/film.json", json.dumps({
            "scripts": [p.removeprefix("books/one/") for p in resources]}))
        tree = planner.Tree(self.root, self.commit())
        paths = resources + [f"books/one/zh/chapter-{i:03}.md" for i in range(250)]
        selected = planner.impact(tree, tree, [*reversed(paths), paths[0]])
        self.assertEqual(selected["suites"], suites)
        self.assertEqual(selected["films"], ["one/001-film"])
        reasons = selected["reasons"]
        self.assertEqual(len(reasons), 202)
        self.assertIn(f"{resources[0]} (+249 more) -> film one/001-film", reasons)
        self.assertIn("book metadata/resource or unknown local dependency: " + resources[0] + " (+249 more)", reasons)
        self.assertLess(len(json.dumps(reasons, ensure_ascii=False).encode("utf-8")), 40_000)

    def test_large_summary_compacts_or_omits_display_without_changing_outputs(self):
        plan = self.make_plan(event="workflow_dispatch", baseline=False)
        for paths, compact in ((["章节"] * 50_000, True), (["章" * 100] * 3000, False)):
            with self.subTest(compact=compact):
                plan["coverage"]["normal"]["paths"] = paths
                self.assertGreater(len(json.dumps(plan, ensure_ascii=False, indent=2).encode("utf-8")), 512 * 1024)
                _, summary = self.outputs(plan)
                self.assertLess(len(summary.encode("utf-8")), 900_000)
                if compact:
                    self.assertEqual(json.loads(summary.split("```json\n")[1].split("\n```")[0]), plan)
                else:
                    self.assertIn("see ci-plan.json", summary)


class LargePlanTransportTest(unittest.TestCase):
    git = fixtures.AffectedPlanTest.git
    write = fixtures.AffectedPlanTest.write
    commit = fixtures.AffectedPlanTest.commit
    make_plan = fixtures.AffectedPlanTest.make_plan

    def setUp(self):
        fixtures.AffectedPlanTest.setUp(self)
        for name in ("ci", "tbook"):
            (self.root / "tools" / name).symlink_to(TOOLS / name, target_is_directory=True)
        self.temp = self.root / "runner-temp"
        self.temp.mkdir()

    def large_plan(self, **kwargs):
        result = self.make_plan(event="workflow_dispatch", baseline=False, **kwargs)
        # Generic provenance, independent of any downstream book or failed run.
        result["coverage"][next(iter(result["coverage"]))]["paths"] = [
            f"books/one/assets/{i:05}-generic-publication-input.svg" for i in range(5000)]
        result["reasons"].append("\nTBOOK_PLAN_JSON\nTBOOK_NEEDS_JSON\n$(touch injected)\n`touch injected`\n'\"\\")
        self.assertGreater(len(json.dumps(result, separators=(",", ":")).encode()), 188430)
        return result

    def needs(self, plan, *, pages=False, enabled=True):
        output = self.temp / "outputs"
        output.unlink(missing_ok=True)
        with mock.patch.dict(os.environ, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=""):
            planner.write_outputs(plan)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(json.loads(outputs["plan"]), plan)
        for field, key in (("build", "exports"), ("viz", "viz"), ("slow", "slow"), ("film", "films")):
            self.assertEqual(json.loads(outputs[field + "_matrix"]), {"include": plan[key]})
        selected = ({"probe": True, "films": bool(plan.get('films')), "build": plan["site"], "deploy": plan["site"] and enabled}
                    if pages else plan["tasks"])
        return {"plan": {"result": "success", "outputs": outputs}, **{
            job: {"result": "success" if chosen else "skipped",
                  "outputs": {"metadata": "generic fanout " * 20000}}
            for job, chosen in selected.items()}}

    def reports(self, plan):
        shutil.rmtree(self.root / "viz-reports", ignore_errors=True)
        fixtures.write_browser_reports(self.write, plan)

    def step(self, workflow, job, marker):
        return next(s for s in workflow_jobs(GITHUB_DIR / "workflows" / workflow)[job]
                    if marker in s.get("run", ""))

    def execute(self, step, data, *, enabled=True):
        script = step["run"]
        for expr, value in (("toJSON(fromJSON(needs.plan.outputs.plan))", json.loads(data["plan"]["outputs"]["plan"])),
                            ("toJSON(needs)", data)):
            script = script.replace("${{ " + expr + " }}", json.dumps(value, ensure_ascii=True, indent=2))
        self.assertNotIn("${{", script)
        completed = run_bash(script, self.root, dict(RUNNER_TEMP=str(self.temp),
            TBOOK_ROOT=str(self.root), PAGES_ENABLED=str(enabled).lower()))
        self.assertFalse((self.root / "injected").exists(), "JSON must remain inert shell data")
        return completed

    def test_selected_consumers_read_the_entire_large_plan_and_keep_exact_selection(self):
        plan = self.large_plan(slow=True)
        needs = self.needs(plan)
        books = plan["selections"]["normal"]["books"]
        commands = {
            "structure": [str(runner.paths.ROOT / "tbook"), "check", *[v for b in books for v in ("--book", b)]],
            "viz-static": ["node", "tools/node/viz-validate.mjs", *books],
            "slides-static": ["node", "tools/node/slides-check.mjs", *[v for b in books for v in ("--book", b)]]}
        for job, kinds in (("validate", commands), ("media", ["slides"])):
            with self.subTest(job=job):
                step = self.step("ci.yml", job, "TBOOK_PLAN_JSON")
                completed = self.execute(step, needs)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                path = self.temp / "ci-plan.json"
                self.assertEqual(json.loads(path.read_text()), plan)
                for kind in kinds:
                    consumer = self.step("ci.yml", job, f"tools/ci/run.py {kind}")
                    with mock.patch.dict(os.environ, RUNNER_TEMP=str(self.temp)):
                        argv = shlex.split(os.path.expandvars(consumer["run"]))[1:]
                    with mock.patch.object(sys, "argv", argv), \
                            mock.patch.object(runner, "run") as command, \
                            mock.patch.object(runner, "selected_slides") as slides:
                        runner.main()
                        if kind == "slides":
                            slides.assert_called_once_with(plan["slides"])
                            command.assert_not_called()
                        else:
                            command.assert_called_once_with(commands[kind])
                            slides.assert_not_called()

    def test_ci_own_and_reusable_aggregate_preserve_large_needs_and_all_profiles(self):
        step = self.step("ci.yml", "check", "--verify")
        for own in (True, False):
            with self.subTest(own=own):
                plan = self.large_plan(own=own, slow=True)
                self.assertEqual(plan["entry"], "own" if own else "call")
                self.reports(plan)
                needs = self.needs(plan)
                self.assertGreater(len(json.dumps(needs).encode()), 1048576)
                completed = self.execute(step, needs)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads((self.temp / "ci-needs.json").read_text()), needs)
                for profile, original in plan["coverage"].items():
                    record = json.loads((self.root / f"coverage/{profile}.json").read_text())
                    for key in set(original) - {"timings"}:
                        self.assertEqual(record[key], original[key], key)
                    if profile in ("normal", "slow"):
                        self.assertEqual(set(record["timings"]), set(plan["execution"][profile]))

    def test_partial_rerun_uses_original_plan_and_checks_each_shard(self):
        jobs = workflow_jobs(GITHUB_DIR / "workflows/ci.yml")
        prefix = "tbook-viz-${{ needs.plan.outputs.plan_attempt }}-"
        for job, profile in (("viz", "normal"), ("viz-slow", "slow")):
            upload = next(s["with"] for s in jobs[job] if "actions/upload-artifact@" in s.get("uses", ""))
            self.assertEqual(upload["name"], prefix + profile + "-${{ matrix.batch }}")
            self.assertEqual(upload["overwrite"], "true")
        download = next(s["with"] for s in jobs["check"] if s["with"].get("path") == "viz-reports")
        self.assertEqual(download["pattern"], prefix + "*")
        plan = self.large_plan(slow=True)
        for record in plan["coverage"].values():
            record["run_attempt"] = "1"
        self.reports(plan)
        needs = self.needs(plan)
        step = self.step("ci.yml", "check", "--verify")
        files = sorted((self.root / "viz-reports").glob("*/normal.json"))
        self.assertGreaterEqual(len(files), 2)
        first = json.loads(files[0].read_text())
        retry = json.loads(files[1].read_text())
        retry["run_attempt"] = "2"
        files[1].write_text(json.dumps(retry))
        with mock.patch.dict(os.environ, GITHUB_RUN_ATTEMPT="3"):
            check = self.execute(step, needs)
            self.assertEqual(check.returncode, 0, check.stderr)
            record = json.loads((self.root / "coverage/normal.json").read_text())
            self.assertEqual((record["plan_attempt"], record["run_attempt"]), ("1", "3"))
            for report in (first, retry):
                for row in report["results"]:
                    self.assertEqual(record["timings"][row["unit"]]["run_attempt"], report["run_attempt"])
            for invalid in (dict(retry, run_attempt="4"), dict(retry, run_id="another"),
                            dict(retry, results=first["results"])):
                files[1].write_text(json.dumps(invalid))
                self.assert_rejected(step, needs)
            files[1].unlink()
            self.assert_rejected(step, needs)

    def test_pages_large_needs_preserves_assembly_deployment_and_film_responsibility(self):
        plan = self.large_plan(workflow="pages")
        step = self.step("pages.yml", "coverage", "--verify")
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                needs = self.needs(plan, pages=True, enabled=enabled)
                completed = self.execute(step, needs, enabled=enabled)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                record = json.loads((self.root / "coverage/pages.json").read_text())
                self.assertEqual(record["deployed"], enabled)
                self.assertEqual(record["deployment_sha"], plan["sha"])
                self.assertEqual(record["paths"], plan["coverage"]["pages"]["paths"])
                self.assertTrue((self.root / "coverage/films.json").exists())
                if enabled:
                    needs["deploy"]["result"] = "failure"
                    self.assert_rejected(step, needs)

    def assert_rejected(self, step, needs):
        shutil.rmtree(self.root / "coverage", ignore_errors=True)
        completed = self.execute(step, needs)
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "coverage").exists())

    def test_missing_malformed_failed_and_mismatched_data_never_publish_coverage(self):
        plan = self.large_plan(slow=True)
        needs = self.needs(plan)
        step = self.step("ci.yml", "check", "--verify")
        self.reports(plan)
        completed = self.execute(step, needs)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        # Every selected job, including plan, must still succeed.
        for job in needs:
            if job != 'plan' and not plan['tasks'][job]:
                continue
            for status in ("failure", "cancelled", "skipped", None):
                bad = copy.deepcopy(needs)
                if status is None:
                    bad[job].pop("result")
                else:
                    bad[job]["result"] = status
                self.assert_rejected(step, bad)
        for outputs in ({}, {"plan": ""}, {"plan": "{}"}):
            bad = copy.deepcopy(needs)
            bad["plan"]["outputs"] = outputs
            # execute renders both expressions, including the plan; use only needs here.
            script = step["run"].replace("${{ toJSON(needs) }}", json.dumps(bad))
            shutil.rmtree(self.root / "coverage", ignore_errors=True)
            completed = run_bash(script, self.root, {"RUNNER_TEMP": str(self.temp)})
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((self.root / "coverage").exists())
        shutil.rmtree(self.root / "viz-reports")
        self.assert_rejected(step, needs)  # No browser reports despite successful job statuses.
        for field, wrong in (("sha", "other-tree"), ("run_attempt", "other-attempt"),
                             ("runtime", {"ImageOS": "other-image"})):
            self.reports(plan)
            path = next((self.root / "viz-reports").glob("*/slow.json"))
            report = json.loads(path.read_text()); report[field] = wrong
            path.write_text(json.dumps(report))
            self.assert_rejected(step, needs)
        for script, args in (("plan.py", ["--verify", "--needs-file"]),
                             ("run.py", ["structure", "--plan-file"])):
            for body in (None, "not json"):
                path = self.temp / "missing-or-malformed.json"
                path.unlink(missing_ok=True)
                if body is not None:
                    path.write_text(body)
                completed = subprocess.run([sys.executable, str(TOOLS / "ci" / script), *args, str(path)],
                    cwd=self.root, capture_output=True, text=True)
                self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
