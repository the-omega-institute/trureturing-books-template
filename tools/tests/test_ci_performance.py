"""CI cache provenance, shard coverage and strict film selection."""
from __future__ import annotations

import argparse
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

from test_film import Sandbox, needs_example


def ci_module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "ci" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trusted_cache = ci_module("trusted_cache")
films = ci_module("films")


class TrustedCacheTest(unittest.TestCase):
    def setUp(self):
        self.run = dict(id=17, workflow_id=3, head_repository={"full_name": "owner/books"},
                        head_branch="main", event="push", status="completed", conclusion="success")
        self.artifact = dict(id=42, name="tbook-build-store", expired=False)
        self.calls = []

    def api(self, endpoint):
        self.calls.append(endpoint)
        if endpoint.endswith("/pages.yml"):
            return dict(id=3, path=".github/workflows/pages.yml")
        if "/runs?" in endpoint:
            return {"workflow_runs": [self.run]}
        if "/runs/17/artifacts?" in endpoint:
            return {"artifacts": [self.artifact]}
        self.fail(f"unexpected API endpoint {endpoint}")

    def test_default_branch_success_is_selected_by_id(self):
        self.assertEqual(trusted_cache.find("owner/books", "main", self.api), (17, 42))
        self.assertIn("branch=main&status=success", self.calls[1])
        self.run["event"] = "workflow_dispatch"
        self.assertEqual(trusted_cache.find("owner/books", "main", self.api), (17, 42))

    def test_pr_fork_other_workflow_branch_and_failed_runs_cannot_supply_cache(self):
        for changes in ({"event": "pull_request"}, {"event": "pull_request_target"},
                        {"event": "workflow_run"}, {"head_branch": "feature"},
                        {"head_repository": {"full_name": "fork/books"}},
                        {"workflow_id": 4}, {"conclusion": "failure"}, {"status": "in_progress"}):
            original = copy.deepcopy(self.run)
            self.run.update(changes)
            self.calls.clear()
            with self.subTest(changes=changes):
                self.assertIsNone(trusted_cache.find("owner/books", "main", self.api))
                self.assertEqual(len(self.calls), 2, "untrusted run's artifacts must never be read")
            self.run = original

    def test_expired_or_differently_named_artifact_is_a_miss(self):
        self.artifact["expired"] = True
        self.assertIsNone(trusted_cache.find("owner/books", "main", self.api))
        self.artifact.update(expired=False, name="books-html")
        self.assertIsNone(trusted_cache.find("owner/books", "main", self.api))

    def test_older_success_is_used_when_newest_has_no_artifact(self):
        def api(endpoint):
            if "/runs?" in endpoint:
                return {"workflow_runs": [dict(self.run, id=18), self.run]}
            if "/runs/18/artifacts?" in endpoint:
                return {"artifacts": []}
            return self.api(endpoint)
        self.assertEqual(trusted_cache.find("owner/books", "main", api), (17, 42))


class FilmShardsTest(unittest.TestCase):
    def test_every_film_of_every_book_runs_once_even_with_empty_shards(self):
        for size in (0, 1, 3, 8, 19):
            items = [("book-b" if i % 2 else "book-a", f"{i:03}-film") for i in range(size)]
            for count in (1, 4, 8):
                selected = [films.selection(reversed(items), (i, count)) for i in range(1, count + 1)]
                self.assertEqual(sorted(x for part in selected for x in part), sorted(items))
                self.assertLessEqual(max(map(len, selected)) - min(map(len, selected)), 1)

    def test_bad_shards_fail_before_rendering(self):
        for value in ("0/4", "5/4", "1/0", "1", "a/4", "1/2/3"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                films.shard(value)


@needs_example
class FilmBuildTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(self)

    def test_shards_and_the_site_share_the_existing_cache(self):
        def render(item, dest):
            dest.mkdir(parents=True)
            for name in item.videos().values():
                (dest / name).write_bytes(b"video")
        with mock.patch.object(films.film, "toolchain_missing", return_value=[]), \
                mock.patch.object(films.film, "render_videos", side_effect=render) as rendering:
            self.assertEqual(films.build_one(self.sb.site, self.sb.film()), "built")
            status = films.film.build_videos(self.sb.site, self.sb.book, mode="require")
            self.assertEqual(status, {self.sb.film().id: "cached"})
            self.assertEqual(rendering.call_count, 1)

    def test_uncached_film_requires_a_working_toolchain(self):
        with mock.patch.object(films.film, "toolchain_missing", return_value=["missing ffmpeg"]), \
                mock.patch.object(films.film, "render_videos") as rendering:
            with self.assertRaisesRegex(films.film.FilmError, "missing ffmpeg"):
                films.build_one(self.sb.site, self.sb.film())
            rendering.assert_not_called()


planner = ci_module("plan")


class AffectedPlanTest(unittest.TestCase):
    """Exercise real Git trees, not path-filter strings or only workflow spelling."""
    def setUp(self):
        import tempfile
        import shutil
        import subprocess
        self.root = Path(tempfile.mkdtemp(prefix="tbook-ci-plan-"))
        self.addCleanup(shutil.rmtree, self.root)
        self.subprocess = subprocess
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.write("site.toml", '[site]\nlanguages=["zh","en"]\n[books]\nhide=[]\n')
        for slug in ("one", "two"):
            prefix = f"books/{slug}/"
            self.write(prefix + "book.toml", '[book]\ntitle="test"\n[outputs]\npdf=["screen"]\n')
            for lang in ("zh", "en"):
                self.write(prefix + f"{lang}/SUMMARY.md", "# Summary\n")
                self.write(prefix + f"{lang}/chapter.md", '::: {.viz src="a" preset="p" height="500"}\n')
            for ident in ("a", "b"):
                self.write(prefix + f"viz/tests/{ident}.test.mjs", f'import "../{ident}/model.js";\n')
                self.write(prefix + f"viz/{ident}/model.js", "export const n = 1;\n")
                self.write(prefix + f"slides/{ident}/slides.md", "# Slide\n")
            self.write(prefix + "viz/tests/dependencies.json", __import__('json').dumps({
                "schema": planner.DEPENDENCIES, "suites": {
                    "a.test.mjs": [prefix + "zh/*.md", "trureturing.lock.json"],
                    "b.test.mjs": [prefix + "en/*.md", "docs/data.json"]}}))
            self.write(prefix + "films/001-film/film.json", '{"solid":true,"scripts":["viz/a/model.js"]}')
        self.write("trureturing.lock.json", "{}")
        self.write("docs/PUBLISHING.md", "说明\n")
        self.write("tools/test.py", "pass\n")
        self.base = self.commit()

    def git(self, *args):
        return self.subprocess.check_output(["git", "-C", str(self.root), *args], stderr=self.subprocess.PIPE).decode().strip()

    def write(self, path, text):
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def impact(self, base=None):
        head = planner.Tree(self.root, "HEAD")
        old = planner.Tree(self.root, base or self.base)
        paths = planner.changed_paths(self.root, old.sha, head.sha)
        return planner.impact(head, old, paths, template=True)

    def make_plan(self, event="push", *, baseline=True, **kwargs):
        def get(*args):
            return {"sha": self.base, "source_run": 17, "artifact_id": 42} if baseline else None
        return planner.plan(self.root, event=event, payload={}, repo="owner/books", branch="main",
                            ref="refs/heads/main", get_baseline=get, **kwargs)

    def test_documentary_change_only_manifest_no_consumers(self):
        self.write("docs/PUBLISHING.md", "新说明\n")
        self.write("skills/local-example/SKILL.md", "规则\n")
        self.commit()
        result = self.impact()
        self.assertEqual([k for k, v in result["checks"].items() if v], ["manifest"])
        for key in ("suites", "films", "slides", "exports", "books"):
            self.assertEqual(result[key], [], key)
        self.assertFalse(result["site"])

    def test_exact_model_and_film_reverse_dependency(self):
        self.write("books/one/viz/a/model.js", "export const n = 2;\n")
        self.commit()
        result = self.impact()
        self.assertEqual(result["suites"], ["books/one/viz/tests/a.test.mjs"])
        self.assertEqual(result["films"], ["one/001-film"])
        self.assertEqual(result["slides"], [])
        self.assertEqual({x["book"] for x in result["exports"]}, {"one"})
        self.assertEqual({x["variant"] for x in result["exports"] if x["target"] == "pdf"}, {"screen"})

    def test_chapter_presets_lock_summary_and_registered_nonlocal_reads(self):
        for path in ("books/one/zh/chapter.md", "books/one/zh/SUMMARY.md", "trureturing.lock.json", "docs/data.json"):
            with self.subTest(path=path):
                tree = planner.Tree(self.root, "HEAD")
                result = planner.impact(tree, tree, [path])
                expected = "books/one/viz/tests/b.test.mjs" if path == "docs/data.json" else "books/one/viz/tests/a.test.mjs"
                self.assertIn(expected, result["suites"])
                self.assertTrue(result["checks"]["structure"])
                if path == "trureturing.lock.json":
                    self.assertEqual(len(result["suites"]), 4)
                    self.assertEqual(result["films"], ["one/001-film", "two/001-film"])

    def test_undeclared_suite_widens_book_not_other_books(self):
        (self.root / "books/one/viz/tests/dependencies.json").unlink()
        self.base = self.commit()
        self.write("books/one/viz/a/model.js", "export const n = 9;\n")
        self.commit()
        self.assertEqual(self.impact()["suites"], [f"books/one/viz/tests/{x}.test.mjs" for x in ("a", "b")])

    def test_shared_solid_core_and_vendor_include_viz_and_film(self):
        tree = planner.Tree(self.root, "HEAD")
        for path in ("theme/viz/solid-core.js", "theme/viz/vendor/three.js", "package-lock.json", "tools/test.py", "new-unknown"):
            result = planner.impact(tree, tree, [path])
            self.assertEqual(len(result["suites"]), 4, path)
            self.assertEqual(result["films"], ["one/001-film", "two/001-film"], path)
            self.assertTrue(result["checks"]["unit"], path)
            self.assertTrue(result["reasons"])

    def test_deleted_renamed_hidden_and_empty_inventory(self):
        import shutil
        self.git("mv", "books/one/viz/a/model.js", "books/one/viz/b/old-model.js")
        self.commit()
        self.assertIn("one/001-film", self.impact()["films"], "old script endpoint still selects its film")
        shutil.rmtree(self.root / "books/one")
        self.commit()
        result = self.impact()
        self.assertTrue(result["site"])
        self.assertNotIn("one/001-film", result["films"])
        self.assertNotIn("one", result["books"])
        self.write("site.toml", '[books]\nhide=["*"]\n')
        self.commit()
        result = self.impact()
        self.assertEqual(result["suites"], [])
        self.assertEqual(result["exports"], [])
        self.assertTrue(result["site"], "hiding all books must still rebuild and remove published books")

    def test_dynamic_shards_are_exact_disjoint_and_nonempty(self):
        for size in (0, 1, 3, 8, 61):
            for maximum in (4, 8):
                items = [f"item-{x:03}" for x in range(size)]
                parts = planner.shards(items, maximum)
                self.assertEqual(len(parts), min(size, maximum))
                self.assertTrue(all(part["items"] for part in parts))
                self.assertEqual(sorted(x for p in parts for x in p["items"]), sorted(items))

    def test_export_groups_share_setup_without_expanding_execution_set(self):
        tree = planner.Tree(self.root, "HEAD")
        exact = planner.impact(tree, tree, [], full=True)["exports"]
        groups = planner.export_matrix(exact)
        flattened = [(book, group["target"], group["variant"]) for group in groups for book in group["books"]]
        expected = [(item["book"], item["target"], item["variant"]) for item in exact]
        self.assertEqual(sorted(flattened), sorted(expected))
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(len(groups), 3, "two books share the html, pdf-screen and epub installations")
        self.assertEqual(planner.export_matrix([]), [])
        # Run the actual workflow shell with a recording CLI; bad/empty JSON must not build all books.
        import json
        from test_verification import workflow_jobs, run_bash
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        script = next(step["run"] for step in workflow_jobs(workflow)["build"] if step.get("name") == "Build")
        self.write("tbook", "#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\nPath('calls.json').write_text(json.dumps(sys.argv[1:]))\n")
        (self.root / "tbook").chmod(0o755)
        env = {"RUNNER_TEMP": str(self.root), "BOOKS_JSON": '["one","two"]', "TARGET": "pdf", "VARIANT": "screen"}
        run = run_bash(script, self.root, env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads((self.root / "calls.json").read_text()),
                         ["build", "pdf", "--book", "one", "--book", "two", "--variant", "screen"])
        for bad in ("[]", "invalid"):
            (self.root / "calls.json").unlink(missing_ok=True)
            run = run_bash(script, self.root, {**env, "BOOKS_JSON": bad})
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((self.root / "calls.json").exists())

    def test_missing_coverage_explicit_full_and_definition_runtime_invalidation(self):
        self.write("docs/PUBLISHING.md", "new\n")
        self.commit()
        self.assertTrue(self.make_plan(baseline=False)["tasks"]["viz"])
        self.assertTrue(self.make_plan(mode="full")["tasks"]["viz"])
        self.assertTrue(self.make_plan(base=self.base, baseline=False)["tasks"]["viz"])
        tree = planner.Tree(self.root, "HEAD")
        signature = planner.signature(tree, "runtime-one")
        self.assertNotEqual(signature, planner.signature(tree, "runtime-two"))
        self.write("tools/test.py", "changed\n")
        self.commit()
        self.assertNotEqual(signature, planner.signature(planner.Tree(self.root, "HEAD"), "runtime-one"))

    def test_failed_or_cancelled_push_then_docs_does_not_lose_change(self):
        self.write("books/one/viz/a/model.js", "export const n = 3;\n")
        failed = self.commit()
        self.write("docs/PUBLISHING.md", "new\n")
        self.commit()
        result = self.make_plan()
        self.assertNotEqual(result["coverage"]["normal"]["inherited"]["sha"], failed)
        self.assertEqual(result["selections"]["normal"]["suites"], ["books/one/viz/tests/a.test.mjs"])
        self.assertEqual(result["deferred_films"], ["one/001-film"])
        self.assertFalse(result["tasks"]["films"], "main film deduplication remains")

    def test_slow_profile_repeats_only_changed_input_and_call_schedule_is_normal(self):
        self.write("docs/PUBLISHING.md", "new\n")
        self.commit()
        result = self.make_plan(event="schedule")
        self.assertEqual(result["profiles"], ["slow"])
        self.assertFalse(any(result["tasks"].values()))
        self.assertEqual(result["slow"], [])
        called = self.make_plan(event="schedule", own=False)
        self.assertEqual(called["profiles"], ["normal", "films"])
        self.assertFalse(called["publish"])
        first = self.make_plan(event="schedule", baseline=False)
        self.assertTrue(first["tasks"]["viz-slow"])
        self.assertFalse(first["tasks"]["build"])

    def test_aggregate_rejects_failure_cancel_unexpected_skip_and_missing_plan(self):
        result = self.make_plan(baseline=False)
        results = {k: {"result": "success"} for k in ["plan", *planner.JOBS]}
        planner.verify_results(result, results)
        for outcome in ("failure", "cancelled", "skipped"):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                planner.verify_results(result, {**results, "viz": {"result": outcome}})
        with self.assertRaises(ValueError):
            planner.verify_results(result, {**results, "plan": {"result": "failure"}})
        # Only intentionally excluded jobs may be skipped.
        result["tasks"]["viz"] = False
        planner.verify_results(result, {**results, "viz": {"result": "skipped"}})

    def test_pages_uses_own_deployment_profile_and_aggregate(self):
        self.write("docs/PUBLISHING.md", "new\n")
        self.commit()
        result = self.make_plan(workflow="pages")
        self.assertFalse(result["site"])
        self.assertEqual(result["profiles"], ["pages"])
        planner.verify_results(result, {"plan": {"result": "success"}, "probe": {"result": "success"},
                                       "build": {"result": "skipped"}, "deploy": {"result": "skipped"}}, pages=True)
        self.assertTrue(self.make_plan(workflow="pages", baseline=False)["site"])
        result["site"] = True
        with self.assertRaises(ValueError):
            planner.verify_results(result, {"plan": {"result": "success"}, "probe": {"result": "success"},
                                           "build": {"result": "success"}, "deploy": {"result": "skipped"}}, pages=True)

    def test_pr_uses_cumulative_diff_and_tested_merge_parents(self):
        self.git("checkout", "-qb", "feature")
        self.write("books/one/viz/a/model.js", "export const n = 4;\n")
        self.commit()
        self.write("docs/PUBLISHING.md", "new\n")
        head = self.commit()
        self.git("checkout", "-qb", "base-tip", self.base)
        self.write("books/two/viz/b/model.js", "export const n = 8;\n")
        base_tip = self.commit()
        self.git("merge", "--no-ff", "-qm", "merge fixture", "feature")
        payload = {"pull_request": {"base": {"sha": base_tip}, "head": {"sha": head}}}
        def baseline(*args):
            return {"sha": self.base}
        result = planner.plan(self.root, event="pull_request", payload=payload, repo="owner/books", branch="main",
                              ref="refs/pull/1/merge", get_baseline=baseline)
        self.assertEqual(result["selections"]["normal"]["suites"], ["books/one/viz/tests/a.test.mjs", "books/two/viz/tests/b.test.mjs"])
        self.assertFalse(result["publish"])
        payload["pull_request"]["base"]["sha"] = self.base
        advanced = planner.plan(self.root, event="pull_request", payload=payload, repo="owner/books", branch="main",
                                ref="refs/pull/1/merge", get_baseline=baseline)
        self.assertEqual(advanced["selections"], result["selections"])
        self.assertTrue(any("tested base advanced" in x for x in advanced["reasons"]))
        self.git("checkout", "--detach", head)
        with self.assertRaisesRegex(ValueError, "merge"):
            planner.plan(self.root, event="pull_request", payload=payload, repo="owner/books", branch="main",
                         ref="refs/pull/1/merge", get_baseline=baseline)

    def test_corrupt_dependency_contract_is_error_not_empty_plan(self):
        self.write("books/one/viz/tests/dependencies.json", '{"schema":"bad"}')
        self.commit()
        with self.assertRaises(ValueError):
            self.make_plan()

    def test_missing_git_history_or_api_falls_back_visibly(self):
        def missing(*args):
            return {"sha": "f" * 40}
        result = planner.plan(self.root, event="push", payload={}, repo="owner/books", branch="main",
                              ref="refs/heads/main", get_baseline=missing)
        self.assertTrue(result["tasks"]["viz"])
        self.assertTrue(any("incomplete Git" in x for x in result["reasons"]))
        def unavailable(*args):
            raise OSError("API unavailable")
        result = planner.plan(self.root, event="push", payload={}, repo="owner/books", branch="main",
                              ref="refs/heads/main", get_baseline=unavailable)
        self.assertTrue(any("baseline unavailable" in x for x in result["reasons"]))
        self.assertTrue(result["tasks"]["build"])

    def test_example_fixtures_select_unit_even_when_hidden(self):
        self.write("books/example-demo/book.toml", '[book]\ntitle="fixture"\n')
        self.write("site.toml", '[books]\nhide=["example-*"]\n')
        self.commit()
        tree = planner.Tree(self.root, "HEAD")
        result = planner.impact(tree, tree, ["books/example-demo/book.toml"], template=True)
        self.assertTrue(result["checks"]["unit"])
        self.assertTrue(result["checks"]["compat"])
        self.assertEqual(result["suites"], [])


    def test_manual_branch_coverage_stays_scoped_and_calls_use_default_coverage(self):
        seen = []
        def baseline(*args):
            seen.append(args[2])
            return None
        for own in (True, False):
            result = planner.plan(self.root, event="workflow_dispatch", payload={}, repo="owner/books", branch="main",
                                  ref="refs/heads/feature", own=own, get_baseline=baseline)
            self.assertEqual(seen[-1], "feature" if own else "main")
            self.assertEqual(result["publish"], own)
            self.assertTrue(result["tasks"]["viz"], "first run of a profile requires full coverage")



class FilmResponsibilityCoverageTest(unittest.TestCase):
    """Independent CI/Pages histories, real provenance validation and the actual Check CLI."""
    setUp = AffectedPlanTest.setUp
    git = AffectedPlanTest.git
    write = AffectedPlanTest.write
    commit = AffectedPlanTest.commit

    def baseline(self, *args):
        return planner.trusted_baseline(*args, get=self.api, download=self.download)

    def api(self, endpoint):
        for workflow, ident in (("ci", 1), ("pages", 2)):
            if endpoint.endswith(f"/{workflow}.yml"):
                return dict(id=ident, path=f".github/workflows/{workflow}.yml")
            if f"/{workflow}.yml/runs?" in endpoint:
                return {"workflow_runs": list(reversed(self.runs[workflow]))}
        for runs in self.runs.values():
            for run in runs:
                if f"/runs/{run['id']}/artifacts?" in endpoint:
                    return {"artifacts": self.artifacts[run["id"]]}
        if "/deployments?" in endpoint:
            return [{"id": ident, "sha": sha} for ident, sha in self.deployments.items()]
        if "/statuses?" in endpoint:
            return [{"state": "success"}]
        self.fail(endpoint)

    def download(self, ident, profile):
        record = self.records[ident]
        self.assertEqual(record["profile"], profile)
        return record

    def select(self, event="push", workflow="ci", **kwargs):
        import os
        with mock.patch.dict(os.environ, GITHUB_RUN_ID=str(self.next_run), GITHUB_RUN_ATTEMPT="1"):
            return planner.plan(self.root, event=event, payload=kwargs.pop("payload", {}), repo="owner/books",
                                branch="main", ref=kwargs.pop("ref", "refs/heads/main"), workflow=workflow,
                                get_baseline=self.baseline, **kwargs)

    def finish(self, result, workflow="ci", outcome="success", enabled=True, missing_film_proof=False):
        import json
        import os
        import shutil
        import sys
        # Run --verify rather than manufacturing records that merely resemble successful coverage.
        shutil.rmtree(self.root / "coverage", ignore_errors=True)
        if workflow == "ci":
            results = {"plan": {"result": "success"}, **{
                job: {"result": "success" if selected else "skipped"} for job, selected in result["tasks"].items()}}
        else:
            results = {"plan": {"result": "success"}, "probe": {"result": "success"},
                       "build": {"result": outcome if result["site"] else "skipped"},
                       "deploy": {"result": "success" if result["site"] and enabled else "skipped"}}
        script = Path(__file__).parents[1] / "ci/plan.py"
        verified = self.subprocess.run([sys.executable, str(script), "--workflow", workflow, "--verify"],
                                      cwd=self.root, env=dict(os.environ, PLAN_JSON=json.dumps(result),
                                      RESULTS_JSON=json.dumps(results), PAGES_ENABLED=str(enabled).lower()),
                                      capture_output=True, text=True)
        self.assertEqual(verified.returncode == 0, outcome == "success", verified.stderr)
        ident = self.next_run
        self.next_run += 1
        self.runs[workflow].append(dict(id=ident, workflow_id=1 if workflow == "ci" else 2,
            head_sha=result["sha"], head_repository={"full_name": "owner/books"}, head_branch="main",
            event=result["event"], status="completed", conclusion=outcome, run_attempt=1))
        self.artifacts[ident] = []
        if verified.returncode:
            self.assertFalse((self.root / "coverage").exists())
            return
        for path in (self.root / "coverage").glob("*.json"):
            profile = path.stem
            if (profile == "films" and missing_film_proof) or (profile == "pages" and not enabled):
                continue
            artifact_id = ident * 10 + len(self.artifacts[ident])
            self.records[artifact_id] = json.loads(path.read_text())
            self.artifacts[ident].append(dict(id=artifact_id, name=f"tbook-coverage-{profile}", expired=False))
        if workflow == "pages" and enabled:
            self.deployments[ident] = result["sha"]

    def bootstrap(self):
        (self.root / ".git/info/exclude").write_text("coverage/\n")
        self.git("checkout", "--detach", self.base)
        self.runs, self.artifacts, self.records, self.deployments = {"ci": [], "pages": []}, {}, {}, {}
        self.next_run = 10
        self.finish(self.select(workflow="pages"), "pages")
        self.finish(self.select())
        self.write("books/one/viz/a/model.js", "export const n = 7;\n")
        changed = self.commit()
        initial = self.select()
        self.assertEqual(initial["deferred_films"], ["one/001-film"])
        self.assertEqual(initial["films"], [])
        self.assertNotIn("films", initial["coverage"], "deferral is never successful film responsibility coverage")
        self.finish(initial)
        return changed

    def docs(self, name="new"):
        self.write("docs/PUBLISHING.md", name + "\n")
        return self.commit()

    def docs_pr(self):
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qB", "feature")
        head = self.docs("PR")
        self.git("checkout", "--detach", base)
        self.git("merge", "--no-ff", "-qm", "merge fixture", head)
        return self.select("pull_request", payload={"pull_request": {"base": {"sha": base}, "head": {"sha": head}}},
                           ref="refs/pull/1/merge")

    def assert_films(self, result, expected, *, deferred=False):
        self.assertEqual(result["selections"]["normal"]["films"], expected)
        self.assertEqual(result["deferred_films"], expected if deferred else [])
        items = [item for part in result["films"] for item in part["items"]]
        self.assertEqual(sorted(items), [] if deferred else expected)
        self.assertEqual(len(items), len(set(items)))
        self.assertTrue(all(part["items"] for part in result["films"]))
        self.assertEqual(result["tasks"]["films"], bool(expected) and not deferred)
        self.assertFalse(any(value for job, value in result["tasks"].items() if job != "films"),
                         "successful normal coverage still discharges unaffected consumers")

    def test_pages_failure_cancellation_and_missing_proof_survive_normal_success_and_docs(self):
        for state in ("failure", "cancelled", "missing-run", "missing-film-proof"):
            with self.subTest(state=state):
                changed = self.bootstrap()
                if state != "missing-run":
                    self.finish(self.select(workflow="pages"), "pages",
                                outcome=state if state in ("failure", "cancelled") else "success",
                                missing_film_proof=state == "missing-film-proof")
                self.docs()
                pushed = self.select()
                self.assertEqual(pushed["coverage"]["normal"]["inherited"]["sha"], changed)
                self.assert_films(pushed, ["one/001-film"], deferred=True)
                self.finish(pushed)  # A second normal success must not erase the obligation either.
                self.assert_films(self.select("workflow_dispatch"), ["one/001-film"])
                self.assert_films(self.docs_pr(), ["one/001-film"])

    def test_actual_pages_or_manual_film_success_allows_unchanged_consumers_to_skip(self):
        for producer in ("pages", "pages-disabled", "manual"):
            with self.subTest(producer=producer):
                self.bootstrap()
                if producer == "manual":
                    completed = self.select("workflow_dispatch")
                    self.assertTrue(completed["tasks"]["films"])
                    self.finish(completed)
                else:
                    completed = self.select(workflow="pages")
                    self.finish(completed, "pages", enabled=producer != "pages-disabled")
                self.docs()
                pushed = self.select()
                self.assert_films(pushed, [], deferred=True)
                self.finish(pushed)
                unchanged = self.select("workflow_dispatch")
                self.assert_films(unchanged, [])
                self.finish(unchanged)  # Successful inheritance can advance actual film coverage too.
                if producer == "pages":
                    no_op = self.select(workflow="pages")
                    self.assertFalse(no_op["site"])
                    self.assertNotIn("films", no_op["coverage"])
                    self.finish(no_op, "pages")
                self.assert_films(self.docs_pr(), [])

    def test_missing_all_film_evidence_widens_only_film_responsibility(self):
        self.bootstrap()
        self.docs()
        self.finish(self.select())
        for artifacts in self.artifacts.values():
            artifacts[:] = [a for a in artifacts if a["name"] != "tbook-coverage-films"]
        result = self.select("workflow_dispatch")
        self.assert_films(result, ["one/001-film", "two/001-film"])
        self.assertTrue(any("films: full fallback" in reason for reason in result["reasons"]))

    def test_failed_or_cancelled_producer_cannot_supply_even_an_uploaded_film_record(self):
        for outcome in ("failure", "cancelled"):
            with self.subTest(outcome=outcome):
                self.bootstrap()
                self.finish(self.select(workflow="pages"), "pages")
                self.runs["pages"][-1]["conclusion"] = outcome
                self.docs()
                self.finish(self.select())
                self.assert_films(self.select("workflow_dispatch"), ["one/001-film"])

    def test_tag_dedup_and_read_only_entries_preserve_film_responsibility(self):
        self.bootstrap()
        tagged = self.select(ref="refs/tags/v1.0.0", own=False)
        self.assertEqual(tagged["deferred_films"], ["one/001-film"])
        self.assertFalse(tagged["tasks"]["films"])
        self.assertNotIn("films", tagged["coverage"])
        self.assertFalse(tagged["publish"])
        called = self.select("workflow_dispatch", own=False)
        self.assertEqual(called["selections"]["normal"]["films"], ["one/001-film"])
        self.assertTrue(called["tasks"]["films"])
        self.assertFalse(called["publish"])
        self.assertFalse(self.docs_pr()["publish"])


class CoverageProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.run = dict(id=17, head_sha="a" * 40, workflow_id=3, head_repository={"full_name": "owner/books"},
                        head_branch="main", event="push", status="completed", conclusion="success")
        self.record = dict(schema=planner.SCHEMA, profile="normal", sha=self.run["head_sha"], signature="sig",
                           run_id="17", run_attempt="1", ref="refs/heads/main", selector_version=planner.VERSION, repository="owner/books")
        self.downloads = []

    def get(self, endpoint):
        if endpoint.endswith("ci.yml"):
            return dict(id=3, path=".github/workflows/ci.yml")
        if "/runs?" in endpoint:
            return {"workflow_runs": [self.run]}
        if "/artifacts?" in endpoint:
            return {"artifacts": [dict(id=42, name="tbook-coverage-normal", expired=False)]}
        self.fail(endpoint)

    def download(self, ident, profile):
        self.downloads.append(ident)
        return self.record

    def find(self):
        with mock.patch.object(planner, "ancestor", return_value=True):
            return planner.trusted_baseline(Path('.'), "owner/books", "main", "ci", "normal", "sig", "HEAD",
                                            get=self.get, download=self.download)

    def test_only_completed_successful_default_branch_own_producers_can_advance(self):
        self.assertEqual(self.find()["artifact_id"], 42)
        for changes in ({"event": "pull_request"}, {"head_branch": "feature"}, {"workflow_id": 7},
                        {"head_repository": {"full_name": "fork/books"}}, {"conclusion": "failure"},
                        {"conclusion": "cancelled"}, {"status": "in_progress"}):
            original = self.run.copy()
            self.run.update(changes)
            self.downloads.clear()
            self.assertIsNone(self.find(), changes)
            self.assertEqual(self.downloads, [])
            self.run = original

    def test_invalid_record_sha_profile_runtime_or_source_is_not_coverage(self):
        for key, value in (("signature", "other"), ("sha", "b" * 40), ("profile", "slow"),
                           ("run_id", "18"), ("run_attempt", "2"), ("ref", "refs/heads/feature"), ("selector_version", 0), ("repository", "fork/books"), ("schema", "old")):
            original = self.record.copy()
            self.record[key] = value
            self.assertIsNone(self.find(), key)
            self.record = original


class ExactRunnerTest(unittest.TestCase):
    setUp = AffectedPlanTest.setUp
    git = AffectedPlanTest.git
    write = AffectedPlanTest.write
    commit = AffectedPlanTest.commit

    def test_actual_node_runner_selects_before_partition_and_rejects_bad_set(self):
        import json
        import os
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("node unavailable")
        script = Path(__file__).parents[1] / "node/viz-test.mjs"
        items = ["books/one/viz/tests/a.test.mjs", "books/two/viz/tests/b.test.mjs"]
        env = dict(os.environ, TBOOK_ROOT=str(self.root), CI_ITEMS=json.dumps(items))
        seen = []
        for i in (1, 2):
            r = self.subprocess.run([node, str(script), "--selection-env", "CI_ITEMS", "--shard", f"{i}/2", "--list"],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            seen += r.stdout.splitlines()
        self.assertEqual(sorted(seen), items)
        for bad in ([items[0], items[0]], ["books/missing/viz/tests/a.test.mjs"]):
            r = self.subprocess.run([node, str(script), "--selection-env", "CI_ITEMS", "--list"],
                                    env={**env, "CI_ITEMS": json.dumps(bad)}, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
        r = self.subprocess.run([node, str(script), "--selection-env", "CI_ITEMS", "--list"],
                                env={**env, "CI_ITEMS": "[]"}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")

    def test_actual_film_runner_exact_set_and_missing_selection(self):
        import os
        import sys
        script = Path(__file__).parents[1] / "ci/films.py"
        env = dict(os.environ, TBOOK_ROOT=str(self.root), CI_ITEMS='["one/001-film"]')
        r = self.subprocess.run([sys.executable, str(script), "--selection-env", "CI_ITEMS", "--list"],
                                env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "one/001-film")
        for value in ('["missing/film"]', '["one/001-film","one/001-film"]'):
            r = self.subprocess.run([sys.executable, str(script), "--selection-env", "CI_ITEMS", "--list"],
                                    env={**env, "CI_ITEMS": value}, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)


class DeploymentCoverageTest(unittest.TestCase):
    def test_only_active_success_is_valid_and_missing_deployment_forces_fallback(self):
        def get(endpoint):
            if "/statuses?" in endpoint:
                return [{"state": self.state}]
            return [{"id": 3, "sha": "deployed-sha"}]
        for state in ("success", "inactive", "failure", "pending"):
            self.state = state
            self.assertEqual(planner.deployed("owner/books", "deployed-sha", get), state == "success")
        self.assertFalse(planner.deployed("owner/books", "missing-sha", get))


class SelectedSlidesTest(unittest.TestCase):
    def test_partial_deck_build_never_populates_complete_book_cache(self):
        from types import SimpleNamespace
        runner = ci_module("run")
        book = SimpleNamespace(slug="book", slides_dir=Path("nonexistent/slides"))
        unit = object()
        with mock.patch.object(runner.config, "load_site", return_value=SimpleNamespace(repo="owner/books")), \
                mock.patch.object(runner.config, "load_books", return_value=[book]), \
                mock.patch.object(runner.slides, "deck_names", return_value=["a", "b"]), \
                mock.patch.object(runner.slides, "base_path", return_value="/books/"), \
                mock.patch.object(runner.slides, "_node", return_value="node"), \
                mock.patch.object(runner.buildcache, "slides_unit", return_value=unit), \
                mock.patch.object(runner.buildcache, "run", return_value="missing") as cache, \
                mock.patch.object(runner, "run") as execute, \
                mock.patch.object(runner.slides, "build") as whole:
            runner.selected_slides(["book/a"])
            cache.assert_called_once_with(unit, None, repo="owner/books")
            command = execute.call_args.args[0]
            self.assertEqual(command[command.index("--deck") + 1:], ["a"])
            whole.assert_not_called()
            execute.reset_mock()
            cache.reset_mock()
            runner.selected_slides(["book/a", "book/b"])
            whole.assert_called_once()
            cache.assert_not_called()
            execute.assert_not_called()
            with self.assertRaises(ValueError):
                runner.selected_slides(["book/missing"])
