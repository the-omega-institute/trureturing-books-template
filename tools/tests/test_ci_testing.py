"""Affected tests must follow old/new dependencies without launching unrelated browsers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from ci import testing
import test_ci_performance as fixtures

planner = fixtures.planner


@unittest.skipUnless(shutil.which("node"), "node not available")
class LocalVizRunnerTests(unittest.TestCase):
    setUp = fixtures.AffectedPlanTest.setUp
    git = fixtures.AffectedPlanTest.git
    write = fixtures.AffectedPlanTest.write
    commit = fixtures.AffectedPlanTest.commit

    def run_viz(self, *args, **env):
        return subprocess.run(["node", str(Path(__file__).parents[1] / "node/viz-test.mjs"), *args],
                              cwd=self.root, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "TBOOK_ROOT": str(self.root), "TBOOK_PYTHON": sys.executable, **env})

    def listed(self, *args):
        run = self.run_viz(*args, "--list")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout.strip().splitlines()

    def test_default_limits_committed_changes_and_book_arguments_filter_them(self):
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.write("books/one/viz/a/model.js", "export const n=2;\n")
        self.commit()
        owner = "books/one/viz/tests/a.test.mjs"
        self.assertEqual(self.listed(), [owner])
        self.assertEqual(self.listed("one"), [owner])
        self.assertEqual(self.listed("two"), [])
        self.assertEqual(self.listed("--base", "HEAD"), [])
        self.assertEqual(self.listed("--shard", "2/2"), [])

    def test_staged_unstaged_and_untracked_inputs_match_the_shared_selector(self):
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.write("books/one/viz/a/model.js", "export const n=2;\n")
        self.git("add", "books/one/viz/a/model.js")
        self.write("books/one/viz/b/model.js", "export const n=2;\n")
        self.write("books/two/viz/a/new.js", "export const n=2;\n")
        expected = [f"books/{book}/viz/tests/{ident}.test.mjs" for book, ident in
                    (("one", "a"), ("one", "b"), ("two", "a"))]
        self.assertEqual(self.listed(), expected)
        old, current, changed = testing.working_changes(self.root, "origin/main")
        self.assertEqual(self.listed(), planner.impact(current, old, changed)["suites"])

    def test_shared_module_selects_only_its_actual_readers(self):
        self.write("theme/viz/shared.js", "export const n=1;\n")
        self.write("books/two/viz/tests/a.test.mjs", 'import "../../../../theme/viz/shared.js";\n')
        self.git("update-ref", "refs/remotes/origin/main", self.commit())
        self.write("theme/viz/shared.js", "export const n=2;\n")
        self.assertEqual(self.listed(), ["books/two/viz/tests/a.test.mjs"])

    def test_clean_and_documentary_changes_exit_without_starting_suites(self):
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        for edited in (False, True):
            if edited:
                self.write("docs/PUBLISHING.md", "新说明\n")
            run = self.run_viz("--slow")
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("no affected visualization suites", run.stdout)
            self.assertNotIn("=== books/", run.stdout)

    def test_default_executes_only_the_affected_child_with_slow_frames_and_report(self):
        for book in ("one", "two"):
            for ident in ("a", "b"):
                self.write(f"books/{book}/viz/tests/{ident}.test.mjs", "throw new Error('unrelated suite ran');\n")
        owner = "books/one/viz/tests/a.test.mjs"
        self.write(owner, 'console.log("frames="+process.env.VIZ_SLOW_FRAMES);\n')
        self.git("update-ref", "refs/remotes/origin/main", self.commit())
        self.write("books/one/viz/a/model.js", "export const n=2;\n")
        report = self.root / ".git/result.json"
        run = self.run_viz("--slow", "--report", str(report))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("frames=1000", run.stdout)
        self.assertIn("1/1 suites passed", run.stdout)
        data = json.loads(report.read_text())
        self.assertEqual([row["unit"] for row in data["results"]], [owner])
        self.assertEqual(data["frames"], 1000)

    def test_missing_base_fails_without_full_fallback_and_full_needs_no_git_history(self):
        run = self.run_viz("--list")
        self.assertEqual(run.returncode, 2)
        self.assertIn("--base <ref>", run.stderr)
        self.assertNotIn("=== books/", run.stdout)
        self.assertEqual(self.listed("--full", "one"),
                         [f"books/one/viz/tests/{ident}.test.mjs" for ident in ("a", "b")])
        shutil.rmtree(self.root / ".git")
        self.assertEqual(len(self.listed("--full")), 4)

    def test_explicit_ci_selection_bypasses_git_but_rejects_ambiguous_modes(self):
        owner = "books/two/viz/tests/b.test.mjs"
        run = self.run_viz("--selection-env", "CI_ITEMS", "--list", CI_ITEMS=json.dumps([owner]))
        self.assertEqual((run.returncode, run.stdout.strip()), (0, owner), run.stderr)
        for args in (("--full",), ("--base", "HEAD")):
            run = self.run_viz("--selection-env", "CI_ITEMS", *args, "--list", CI_ITEMS="[]")
            self.assertEqual(run.returncode, 2)
        self.assertEqual(self.run_viz("--base").returncode, 2)


class SelectionTests(unittest.TestCase):
    setUp = fixtures.AffectedPlanTest.setUp
    git = fixtures.AffectedPlanTest.git
    write = fixtures.AffectedPlanTest.write
    commit = fixtures.AffectedPlanTest.commit

    def views(self):
        return planner.Tree(self.root, self.commit()), planner.Tree(self.root, self.base)

    def test_python_dependency_selects_its_test_and_preserves_removed_imports(self):
        self.write("tools/tbook/model.py", "n=1\n")
        self.write("tools/tests/test_model.py", "import unittest\nfrom tbook import model\n"
                   "class ModelTest(unittest.TestCase):\n def test_model(self): pass\n")
        self.base = self.commit()
        self.write("tools/tests/test_model.py", "import unittest\n"
                   "class ModelTest(unittest.TestCase):\n def test_model(self): pass\n")
        head, old = self.views()
        selected = testing.select(head, old, ["tools/tbook/model.py"])
        self.assertEqual(selected["unit_tests"], ["test_model.ModelTest"])
        self.assertEqual(selected["browser_tests"], [])

    def test_ci_tool_edit_does_not_run_epub_or_visualization_browsers(self):
        self.write("tools/tests/test_export_layout.py", "import unittest\n"
                   "class EpubLayoutTest(unittest.TestCase):\n def test_layout(self): pass\n")
        self.write("tools/ci/plan.py", "pass\n")
        head, old = self.views()
        selected = planner.impact(head, old, ["tools/ci/plan.py"])
        self.assertEqual(selected["browser_tests"], [])
        self.assertEqual(selected["suites"], [])
        selected = testing.select(head, old, ["theme/epub/style.css"])
        self.assertEqual(selected["browser_tests"], ["test_export_layout.EpubLayoutTest"])

    def test_toolchain_image_workflow_edit_has_no_unrelated_browser_consumers(self):
        head, old = self.views()
        selected = planner.impact(head, old, [".github/workflows/toolchain-image.yml"])
        self.assertEqual(selected["browser_tests"], [])
        self.assertEqual(selected["suites"], [])
        self.assertEqual(selected["films"], [])
        self.assertEqual(selected["exports"], [])

    def test_local_runner_regressions_follow_the_node_entrypoint(self):
        self.write("tools/tests/test_ci_testing.py", "import unittest\n"
                   "class LocalVizRunnerTests(unittest.TestCase):\n def test_runner(self): pass\n")
        head, old = self.views()
        selected = testing.select(head, old, ["tools/node/viz-test.mjs"])
        self.assertIn("test_ci_testing.LocalVizRunnerTests", selected["unit_tests"])

    def test_site_browser_regression_is_separate_from_unrelated_python_imports(self):
        self.write("tools/tests/test_site.py", "import unittest\nfrom tbook import cli\n"
                   "class BrowserLayoutTest(unittest.TestCase):\n def test_layout(self): pass\n")
        self.write("tools/tbook/cli.py", "pass\n")
        head, old = self.views()
        selected = testing.select(head, old, ["tools/tbook/cli.py"])
        self.assertNotIn("test_site.BrowserLayoutTest", selected["unit_tests"])
        self.assertEqual(selected["browser_tests"], [])
        selected = testing.select(head, old, ["theme/mdbook/tr-book.css"])
        self.assertEqual(selected["browser_tests"], ["test_site.BrowserLayoutTest"])

    def test_starter_browser_regressions_follow_the_template_and_scaffolder(self):
        self.write("tools/tests/test_viz.py", "import unittest\n"
                   "class RailGate(unittest.TestCase):\n def test_starter(self): pass\n")
        head, old = self.views()
        for path in ("templates/viz/main.js", "templates/viz/index.html", "tools/tbook/viz.py"):
            with self.subTest(path=path):
                selected = testing.select(head, old, [path])
                self.assertNotIn("test_viz.RailGate", selected["unit_tests"])
                self.assertEqual(selected["browser_tests"], ["test_viz.RailGate"])

    def test_citation_dependencies_follow_both_endpoints_and_ignore_fenced_examples(self):
        deps = {"schema": planner.DEPENDENCIES, "suites": {
            "a.test.mjs": ["@citations"], "b.test.mjs": ["@citations"]}}
        path = "books/one/zh/chapter.md"
        self.write("books/one/viz/tests/dependencies.json", json.dumps(deps))
        self.base = self.commit()
        self.write(path, '::: {.viz src="b" height="600"}\n:::\n\n```markdown\n::: {.viz src="a"}\n```\n')
        head, old = self.views()
        selected = planner.impact(head, old, [path])
        self.assertEqual(selected["suites"], [f"books/one/viz/tests/{x}.test.mjs" for x in ("a", "b")])
        selected = planner.impact(head, head, [path])
        self.assertEqual(selected["suites"], ["books/one/viz/tests/b.test.mjs"])

    def test_new_summary_does_not_replay_unchanged_readers_but_keeps_changed_inputs(self):
        dep = "books/one/viz/tests/dependencies.json"
        (self.root / dep).unlink()
        self.base = self.commit()
        self.write(dep, json.dumps({"schema": planner.DEPENDENCIES, "suites": {
            "a.test.mjs": ["@citations"], "b.test.mjs": ["@citations"]}}))
        head, old = self.views()
        self.assertEqual(planner.impact(head, old, ["tools/ci/plan.py"])["suites"], [])
        self.write("books/one/viz/a/model.js", "export const n=3;\n")
        head, old = self.views()
        self.assertEqual(planner.impact(head, old, ["books/one/viz/a/model.js"])["suites"],
                         ["books/one/viz/tests/a.test.mjs"])

    def test_refined_chapter_summary_applies_to_unchanged_old_reader(self):
        dep = "books/one/viz/tests/dependencies.json"
        path = "books/one/zh/other.md"
        self.write(dep, json.dumps({"schema": planner.DEPENDENCIES, "suites": {
            "a.test.mjs": ["books/one/zh/*.md"], "b.test.mjs": ["books/one/zh/*.md"]}}))
        self.write(path, '# Other\n::: {.viz src="b"}\n:::\n')
        self.base = self.commit()
        self.write(dep, json.dumps({"schema": planner.DEPENDENCIES, "suites": {
            "a.test.mjs": ["@citations"], "b.test.mjs": ["@citations"]}}))
        self.write(path, '# Changed other\n::: {.viz src="b"}\n:::\n')
        head, old = self.views()
        self.assertEqual(planner.impact(head, old, [path])["suites"], ["books/one/viz/tests/b.test.mjs"])
        # An edited reader cannot use the corrected summary to discard its old reads.
        self.write("books/one/viz/a/model.js", "export const n=3;\n")
        head, old = self.views()
        self.assertEqual(planner.impact(head, old, [path])["suites"],
                         [f"books/one/viz/tests/{x}.test.mjs" for x in ("a", "b")])

    def test_generated_book_data_only_selects_actual_film_readers(self):
        path = "books/one/data/statistics.json"
        self.write(path, '{}\n')
        head, old = self.views()
        self.assertEqual(planner.impact(head, old, [path])["films"], [])
        self.write("books/one/films/001-film/scenes.js", "const load = url => import(url);\n")
        head, old = self.views()
        self.assertEqual(planner.impact(head, old, [path])["films"], ["one/001-film"])

    def test_local_list_includes_staged_unstaged_and_untracked_inputs_without_running(self):
        self.write("tools/test.py", "n=2\n")
        self.git("add", "tools/test.py")
        self.write("docs/PUBLISHING.md", "changed\n")
        self.write("tools/tests/test_new.py", "import unittest\n"
                   "class NewTest(unittest.TestCase):\n def test_new(self): pass\n")
        old, head, changed = testing.working_changes(self.root, self.base)
        self.assertEqual(changed, ["docs/PUBLISHING.md", "tools/test.py", "tools/tests/test_new.py"])
        selected = testing.select(head, old, changed)
        self.assertIn("test_new.NewTest", selected["unit_tests"])
        self.assertIn("test_template.ExampleTest", selected["unit_tests"])
        self.assertEqual(selected["browser_tests"], [])

    def test_required_browser_skip_is_a_failure(self):
        with mock.patch("unittest.defaultTestLoader.loadTestsFromNames", return_value=unittest.TestSuite()), \
             mock.patch("unittest.TextTestRunner.run", return_value=mock.Mock(skipped=[("test", "missing")],
                                                                            wasSuccessful=lambda: True)):
            with self.assertRaises(SystemExit):
                testing.run_tests(["test_export_layout.EpubLayoutTest"], required=True)

    def test_missing_artifact_uses_a_successful_tree_and_preserves_pending_source_changes(self):
        self.write("books/one/viz/a/model.js", "export const n=2;\n")
        self.commit()
        self.write("docs/PUBLISHING.md", "new\n")
        self.commit()
        revision = mock.Mock(return_value=self.base)
        result = planner.plan(self.root, event="push", payload={}, repo="owner/books", branch="main",
                              ref="refs/heads/main", get_baseline=lambda *a: None, get_revision=revision)
        self.assertEqual(result["selections"]["normal"]["suites"], ["books/one/viz/tests/a.test.mjs"])
        self.assertIsNone(result["coverage"]["normal"]["inherited"])
        self.assertEqual(result["coverage"]["normal"]["comparison"], self.base)
        self.assertEqual([call.args[3] for call in revision.call_args_list], ["ci", "pages"])

    def test_no_comparison_history_fails_instead_of_selecting_all_browsers(self):
        self.git("checkout", "-q", self.base + "^")
        with self.assertRaisesRegex(ValueError, "cannot determine changed scope"):
            planner.plan(self.root, event="push", payload={}, repo="owner/books", branch="main",
                         ref="refs/heads/main", get_baseline=lambda *a: None)

    def test_revision_lookup_rejects_foreign_and_failed_producers_without_artifacts(self):
        valid = dict(id=17, workflow_id=3, head_repository={"full_name": "owner/books"}, head_branch="main",
                     event="push", status="completed", conclusion="success", head_sha=self.base)
        def api(endpoint):
            if endpoint.endswith("/ci.yml"):
                return dict(id=3, path=".github/workflows/ci.yml")
            return {"workflow_runs": [dict(valid, id=18, conclusion="failure"),
                                     dict(valid, id=19, head_repository={"full_name": "fork/books"}), valid]}
        with mock.patch.object(planner, "api", side_effect=api):
            self.assertEqual(planner.trusted_revision(self.root, "owner/books", "main", "ci", "HEAD"), self.base)
