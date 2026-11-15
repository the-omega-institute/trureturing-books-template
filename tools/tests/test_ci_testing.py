"""Affected tests must follow old/new dependencies without launching unrelated browsers."""
import json
import unittest
from unittest import mock

from ci import testing
import test_ci_performance as fixtures

planner = fixtures.planner


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
