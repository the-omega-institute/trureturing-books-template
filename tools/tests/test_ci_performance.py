"""CI cache provenance, shard coverage and strict film selection."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
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


def write_browser_reports(write, plan):
    import json
    for profile, matrix in (("normal", "viz"), ("slow", "slow")):
        for shard in plan.get(matrix, []):
            record = plan["coverage"][profile]
            attempt = record["run_attempt"]
            artifact = f"tbook-viz-{attempt}-{profile}-{shard['batch']}"
            write(f"viz-reports/{artifact}/{profile}.json", json.dumps(dict(
                schema="tbook-viz-report-v1", profile=profile, sha=plan["sha"],
                run_id=record["run_id"], run_attempt=attempt, runtime=record["runtime"],
                frames=1000 if profile == "slow" else 0,
                results=[dict(unit=u, seconds=1, exit_code=0, signal=None) for u in shard["items"]])))


class TrustedCacheTest(unittest.TestCase):
    def setUp(self):
        self.run = dict(id=17, workflow_id=3, head_repository={"full_name": "owner/books"},
                        head_branch="main", event="push", status="completed", conclusion="success")
        self.artifact = dict(id=42, name="tbook-build-store", expired=False)
        self.ci_runs = []
        self.calls = []

    def api(self, endpoint):
        self.calls.append(endpoint)
        if endpoint.endswith("/pages.yml"):
            return dict(id=3, path=".github/workflows/pages.yml")
        if endpoint.endswith("/ci.yml"):
            return dict(id=4, path=".github/workflows/ci.yml")
        if "/actions/artifacts?" in endpoint:
            return {"total_count": 1, "artifacts": [dict(self.artifact, workflow_run={"id": 17})]}
        if endpoint.endswith("/runs/17"):
            return self.run
        if "/ci.yml/runs?" in endpoint:
            return {"workflow_runs": self.ci_runs}
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
                        {"head_branch": "feature"},
                        {"head_repository": {"full_name": "fork/books"}},
                        {"workflow_id": 4}, {"conclusion": "failure"}, {"status": "in_progress"}):
            original = copy.deepcopy(self.run)
            self.run.update(changes)
            self.calls.clear()
            with self.subTest(changes=changes):
                self.assertIsNone(trusted_cache.find("owner/books", "main", self.api))
                self.assertFalse(any("/artifacts?" in endpoint for endpoint in self.calls),
                                 "untrusted run's artifacts must never be read")
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

    def test_newest_successful_ci_or_pages_store_is_selected(self):
        self.ci_runs = [dict(self.run, id=20, workflow_id=4, created_at="2026-11-16T02:00:00Z")]
        self.run["created_at"] = "2026-11-16T01:00:00Z"
        def api(endpoint):
            if "/runs/20/artifacts?" in endpoint:
                return {"artifacts": [dict(self.artifact, id=43)]}
            return self.api(endpoint)
        self.assertEqual(trusted_cache.find("owner/books", "main", api), (20, 43))
        self.run["created_at"] = "2026-11-16T03:00:00Z"
        self.assertEqual(trusted_cache.find("owner/books", "main", api), (17, 42))

    def test_late_finishing_pages_and_reruns_supply_the_freshest_store(self):
        self.run.update(created_at='2026-11-16T01:00:00Z', updated_at='2026-11-16T03:00:00Z')
        self.ci_runs = [dict(self.run, id=20, workflow_id=4,
                             created_at='2026-11-16T02:00:00Z', updated_at='2026-11-16T02:30:00Z')]
        def api(endpoint):
            if '/runs/20/artifacts?' in endpoint:
                return {'artifacts': [dict(self.artifact, id=43)]}
            return self.api(endpoint)
        self.assertEqual(trusted_cache.find('owner/books', 'main', api), (17, 42))
        self.ci_runs[0].update(run_attempt=2, updated_at='2026-11-16T04:00:00Z')
        self.assertEqual(trusted_cache.find('owner/books', 'main', api), (20, 43))

    def test_ci_store_has_the_same_source_and_success_requirements(self):
        original = dict(self.run, id=20, workflow_id=4)
        self.run["conclusion"] = "failure"
        for changes in ({"event": "pull_request"}, {"event": "pull_request_target"},
                        {"head_repository": {"full_name": "fork/books"}}, {"head_branch": "feature"},
                        {"workflow_id": 99}, {"conclusion": "failure"}, {"status": "in_progress"}):
            self.ci_runs = [dict(original, **changes)]
            self.calls.clear()
            with self.subTest(changes=changes):
                self.assertIsNone(trusted_cache.find("owner/books", "main", self.api))
                self.assertFalse(any("/artifacts?" in endpoint for endpoint in self.calls))

    def test_missing_ci_workflow_does_not_hide_a_pages_store(self):
        def api(endpoint):
            if endpoint.endswith("/ci.yml"):
                raise OSError("not present")
            return self.api(endpoint)
        self.assertEqual(trusted_cache.find("owner/books", "main", api), (17, 42))

    def test_film_store_is_not_shadowed_by_a_newer_export_only_ci(self):
        self.artifact["name"] = "tbook-film-store"
        self.run["updated_at"] = "2026-11-17T01:00:00Z"
        self.ci_runs = [dict(self.run, id=20, workflow_id=4, updated_at="2026-11-17T02:00:00Z")]
        def api(endpoint):
            if "/runs/20/artifacts?" in endpoint:
                return {"artifacts": [dict(self.artifact, id=43, name="tbook-build-store")]}
            return self.api(endpoint)
        self.assertEqual(trusted_cache.find("owner/books", "main", api,
                                          artifact_name="tbook-film-store"), (17, 42))
        self.run["event"] = "pull_request"
        self.assertIsNone(trusted_cache.find("owner/books", "main", api,
                                            artifact_name="tbook-film-store"))

    def test_film_discovery_survives_twenty_newer_export_runs_and_paginates_artifacts(self):
        self.artifact["name"] = "tbook-film-store"
        self.ci_runs = [dict(self.run, id=i, workflow_id=4) for i in range(18, 39)]
        calls = []
        def api(endpoint):
            calls.append(endpoint)
            if "/actions/artifacts?" in endpoint:
                if endpoint.endswith("page=1"):
                    return {"total_count": 101, "artifacts": [dict(self.artifact, id=i,
                            workflow_run={"id": 20}) for i in range(100, 200)]}
                self.assertTrue(endpoint.endswith("page=2"))
                return {"total_count": 101, "artifacts": [dict(self.artifact, workflow_run={"id": 17})]}
            if endpoint.endswith("/runs/20"):
                return dict(self.run, id=20, event="pull_request")
            return self.api(endpoint)
        self.assertEqual(trusted_cache.find("owner/books", "main", api,
                                          artifact_name="tbook-film-store"), (17, 42))
        self.assertEqual(calls.count("repos/owner/books/actions/runs/20"), 1)
        self.assertFalse(any("/runs?" in call for call in calls), "unrelated run volume cannot hide films")

    def test_named_film_artifacts_keep_all_producer_and_expiry_checks(self):
        self.artifact["name"] = "tbook-film-store"
        for changes in ({"event": "pull_request"}, {"head_branch": "feature"},
                        {"head_repository": {"full_name": "fork/books"}}, {"workflow_id": 99},
                        {"status": "in_progress"}, {"conclusion": "failure"}):
            original = dict(self.run)
            self.run.update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(trusted_cache.find("owner/books", "main", self.api,
                                                    artifact_name="tbook-film-store"))
            self.run = original
        self.artifact["expired"] = True
        self.calls.clear()
        self.assertIsNone(trusted_cache.find("owner/books", "main", self.api,
                                            artifact_name="tbook-film-store"))
        self.assertNotIn("repos/owner/books/actions/runs/17", self.calls)

    def test_image_lookup_stays_scoped_when_only_the_complete_store_exists(self):
        self.assertIsNone(trusted_cache.find("owner/books", "main", self.api,
                                            artifact_name="tbook-image-store"))
        self.assertTrue(any("name=tbook-image-store" in call for call in self.calls))
        self.assertFalse(any("/runs?" in call for call in self.calls))
        self.artifact["name"] = "tbook-image-store"
        self.assertEqual(trusted_cache.find("owner/books", "main", self.api,
                                            artifact_name="tbook-image-store"), (17, 42))
        self.run["event"] = "pull_request"
        self.assertIsNone(trusted_cache.find("owner/books", "main", self.api,
                                            artifact_name="tbook-image-store"))

    def test_image_lookup_stops_after_the_first_verified_inventory(self):
        self.artifact["name"] = "tbook-image-store"

        def api(endpoint):
            if "/actions/artifacts?" in endpoint:
                return {"total_count": 2, "artifacts": [
                    dict(self.artifact, workflow_run={"id": 17}),
                    dict(self.artifact, id=40, workflow_run={"id": 16}),
                ]}
            return self.api(endpoint)

        self.assertEqual(trusted_cache.find("owner/books", "main", api,
                                            artifact_name="tbook-image-store"), (17, 42))
        self.assertNotIn("repos/owner/books/actions/runs/16", self.calls)

    def test_film_restore_falls_back_to_legacy_store_at_the_correct_root(self):
        find = trusted_cache.find
        for dedicated in (True, False):
            with self.subTest(dedicated=dedicated), tempfile.TemporaryDirectory() as tmp:
                self.artifact["name"] = "tbook-film-store" if dedicated else "tbook-build-store"
                output = Path(tmp) / "output"
                with mock.patch.dict(os.environ, GITHUB_REPOSITORY="owner/books", DEFAULT_BRANCH="main",
                                     CACHE_ARTIFACT="tbook-film-store", GITHUB_OUTPUT=str(output)), \
                     mock.patch.object(trusted_cache, "find", side_effect=lambda *a, **kw:
                                       find(*a, get=self.api, **kw)), \
                     mock.patch("builtins.print"):
                    trusted_cache.main()
                self.assertEqual(dict(line.split("=", 1) for line in output.read_text().splitlines()),
                                 {"run-id": "17", "artifact-id": "42",
                                  "artifact-scope": "films" if dedicated else "all"})


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

    def test_source_scope_projection_preserves_the_existing_video_input_key(self):
        # Freeze the pre-extraction key contract, including file/value ordering.
        f = films.film
        item = self.sb.film()
        where = f.paths.rel(item.dir)
        legacy = (f.buildcache.Inputs()
                  .files(item.dir, exclude=(f"/{where}/{f.POSTER}", f"/{where}/README.md", f"/{where}/out/"))
                  .files(f.THEME_FILM, exclude=("/theme/film/site/",))
                  .files(f.paths.GENERATED / "tokens.mjs", f.paths.TOOLS / "tbook" / "film.py")
                  .text("engine", f.engine_data(item)).text("npm", f._npm_packages())
                  .text("kokoro", f.KOKORO_RELEASE).text("node", f.buildcache.node_version()))
        legacy.files(*(p for p in item.scripts if p.is_file()))
        if item.solid:
            legacy.files(f.SOLID_CORE, f.SOLID_VENDOR)
        current = f.video_unit(self.sb.site, item).inputs
        self.assertEqual(current.parts, legacy.parts)
        self.assertEqual(current.key(), legacy.key())


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
        self.git("commit", "--allow-empty", "-qm", "initial")
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
        self.write("tools/tests/test_template.py", "import unittest\nimport test\n"
                   "class ExampleTest(unittest.TestCase):\n    def test_ok(self): pass\n")
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

    def template_release(self):
        # Use the tool's accepted minimal config, without new owner restrictions.
        before = '[template]\nversion="0.12.0"\n[managed]\npaths=["tools/"]\n'
        self.write("template.toml", before)
        self.base = self.commit()
        self.write("template.toml", before.replace('"0.12.0"', '"0.12.1"'))
        self.write("docs/CHANGELOG.md", "## [0.12.1] - 2026-11-14\n\n修复说明。\n")
        self.write("template-manifest.json", '{"version":"0.12.1"}')
        return planner.Tree(self.root, self.commit()), planner.Tree(self.root, self.base)

    def test_template_release_metadata_keeps_tool_checks_and_actual_site_reader_only(self):
        head, old = self.template_release()
        self.assertEqual(planner.changed_paths(self.root, old.sha, head.sha),
                         ["docs/CHANGELOG.md", "template-manifest.json", "template.toml"])
        result = self.impact()
        self.assertEqual([k for k, v in result["checks"].items() if v], ["unit", "compat", "manifest"])
        for key in ("suites", "films", "slides", "exports", "books"):
            self.assertEqual(result[key], [], key)
        # _template_info is a real footer/manifest reader, independent of exports.
        self.assertTrue(result["site"])
        for event in ("push", "workflow_dispatch", "workflow_call", "schedule"):
            with self.subTest(event=event):
                plan = self.make_plan(event=event)
                for selected in plan["selections"].values():
                    for key in ("suites", "films", "slides", "exports", "books"):
                        self.assertEqual(selected[key], [], (event, key))
                self.assertFalse(any(plan["tasks"][k] for k in ("build", "viz", "viz-slow", "media", "films")))
        pages = self.make_plan(workflow="pages")
        self.assertTrue(pages["site"])

    def test_template_version_metadata_retains_declared_readers_in_either_tree(self):
        import json
        dep = "books/one/viz/tests/dependencies.json"
        data = json.loads((self.root / dep).read_text())
        data["suites"]["a.test.mjs"].append("template.toml")
        self.write(dep, json.dumps(data))
        self.write("books/one/viz/tests/a.test.mjs",
                   'import fs from "node:fs"; fs.readFileSync("template.toml", "utf8");\n')
        head, old = self.template_release()
        data["suites"]["a.test.mjs"].remove("template.toml")
        self.write(dep, json.dumps(data))
        self.write("books/one/viz/tests/a.test.mjs", 'export const nonreader = true;\n')
        head = planner.Tree(self.root, self.commit())
        # A supported constructor's declared root source must also remain live.
        engine_sources = planner.film_inputs.engine_sources
        def sources(slug):
            return (*engine_sources(slug), *(["template.toml"] if slug == "two" else []))
        with mock.patch.object(planner.film_inputs, "engine_sources", sources):
            for current, previous in ((head, old), (old, head)):
                result = planner.impact(current, previous, ["template.toml"])
                self.assertEqual(result["suites"], ["books/one/viz/tests/a.test.mjs"])
                self.assertEqual(result["films"], ["two/001-film"])
                self.assertEqual(result["slides"], [])
                self.assertEqual(result["books"], ["one", "two"])

    def test_collaboration_ownership_additions_do_not_select_publication_outputs(self):
        head, old = self.template_release()
        metadata = head.read("template.toml").replace(
            'paths=["tools/"]',
            'paths=["tools/", "CONTRIBUTING.md", ".github/ISSUE_TEMPLATE/", '
            '".github/pull_request_template.md"]\nexclude=[".github/ISSUE_TEMPLATE/local-"]')
        self.write("template.toml", metadata)
        new = planner.Tree(self.root, self.commit())
        for current, previous in ((new, old), (old, new), (new, head), (head, new)):
            with self.subTest(current=current.sha, previous=previous.sha):
                result = planner.impact(current, previous, ["template.toml"], template=True)
                for key in ("suites", "films", "slides", "exports", "books", "browser_tests"):
                    self.assertEqual(result[key], [], key)
                self.assertTrue(result["checks"]["manifest"])

        # Unknown metadata and ownership of publication resources still widen.
        self.write("template.toml", metadata.replace('"CONTRIBUTING.md"', '"assets/"'))
        other = planner.Tree(self.root, self.commit())
        self.assertTrue(planner.impact(other, old, ["template.toml"])["exports"])

    def test_pages_workflow_reuses_book_evidence_but_keeps_assembly_and_explicit_readers(self):
        import json
        path = ".github/workflows/pages.yml"
        self.write(path, "name: Pages\n")
        self.write("tools/tests/test_ci_performance.py", "import unittest\n"
                   "class PipelineTest(unittest.TestCase):\n    def test_ok(self): pass\n")
        old = planner.Tree(self.root, self.commit())
        self.write(path, "name: Updated Pages\n")
        head = planner.Tree(self.root, self.commit())
        for current, previous in ((head, old), (old, head)):
            result = planner.impact(current, previous, [path])
            self.assertTrue(result["site"])
            self.assertIn("test_ci_performance.PipelineTest", result["unit_tests"])
            for key in ("books", "suites", "films", "slides", "exports", "browser_tests"):
                self.assertEqual(result[key], [], key)
        deps = "books/one/viz/tests/dependencies.json"
        data = json.loads((self.root / deps).read_text())
        data["suites"]["a.test.mjs"].append(path)
        self.write(deps, json.dumps(data))
        self.write("books/one/viz/tests/a.test.mjs",
                   f'import fs from "node:fs"; fs.readFileSync("{path}", "utf8");\n')
        reader = planner.Tree(self.root, self.commit())
        for current, previous in ((reader, old), (old, reader)):
            result = planner.impact(current, previous, [path])
            self.assertEqual(result["suites"], ["books/one/viz/tests/a.test.mjs"])
            self.assertEqual(result["books"], ["one"])

    def test_template_metadata_nonversion_invalid_and_absent_inputs_keep_full_fallback(self):
        head, old = self.template_release()
        valid = head.read("template.toml")
        full = planner.impact(head, old, [], full=True, template=True)
        variants = (valid.replace('paths=["tools/"]', 'paths=["theme/"]'),
                    valid + '\n[extra]\nflag=true\n',
                    valid.replace('"0.12.1"', '"invalid"'),
                    valid.replace('"0.12.1"', '12'),
                    valid.replace('paths=["tools/"]', 'paths="tools/"'),
                    '[template\nversion="0.12.1"',
                    valid.replace('version="0.12.1"', ''),
                    valid.replace('[template]', 'template=[]\n[other]'))
        for text in variants:
            self.write("template.toml", text)
            changed = planner.Tree(self.root, self.commit())
            for current, previous in ((changed, old), (old, changed)):
                with self.subTest(text=text, reverse=current is old):
                    result = planner.impact(current, previous, ["template.toml"], template=True)
                    for key in ("checks", "suites", "films", "slides", "exports", "books", "site"):
                        self.assertEqual(result[key], full[key], key)
        # Even Python-equal TOML values of different types are non-version edits.
        for value in ('true', '1'):
            text = valid.replace('"0.12.1"', '"0.12.0"') if value == 'true' else valid
            self.write("template.toml", text + '\n[extra]\nflag=' + value + '\n')
            if value == 'true':
                before = planner.Tree(self.root, self.commit())
            else:
                after = planner.Tree(self.root, self.commit())
        self.assertEqual(planner.impact(after, before, ["template.toml"])["suites"], full["suites"])
        (self.root / "template.toml").unlink()
        absent = planner.Tree(self.root, self.commit())
        for current, previous in ((head, absent), (absent, head), (head, None)):
            result = planner.impact(current, previous, ["template.toml"], template=True)
            self.assertEqual(result["suites"], full["suites"])
            self.assertEqual(result["films"], full["films"])

    def test_template_metadata_does_not_discharge_unknown_shared_reads_or_full_mode(self):
        (self.root / "books/one/viz/tests/dependencies.json").unlink()
        self.write("books/two/films/001-film/scenes.js", 'import(resolveURL());\n')
        head, old = self.template_release()
        result = planner.impact(head, old, ["template.toml", "theme/new-resource.js"])
        self.assertEqual(result["suites"], ["books/one/viz/tests/a.test.mjs", "books/one/viz/tests/b.test.mjs"])
        self.assertEqual(result["films"], ["two/001-film"])
        for options in ({"baseline": False}, {"mode": "full"}):
            plan = self.make_plan(**options)
            self.assertEqual(plan["tasks"]["viz"], options.get("mode") == "full")
            self.assertEqual(plan["tasks"]["build"], options.get("mode") == "full")

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
                    self.assertEqual(len(result["suites"]), 2)
                    self.assertEqual(result["films"], ["one/001-film", "two/001-film"])

    def plain_markdown_change(self):
        import json
        # Complete nonreader summaries distinguish book text from engineering docs.
        # Neither browser suite reads this chapter, so publication must stand alone.
        for slug in ("one", "two"):
            self.write(f"books/{slug}/viz/tests/dependencies.json", json.dumps({
                "schema": planner.DEPENDENCIES, "suites": {"a.test.mjs": [], "b.test.mjs": []}}))
        path = "books/one/zh/prose.md"
        self.write(path, "# Chapter\n\nOriginal text.\n")
        self.base = self.commit()
        self.write(path, "# Chapter\n\nRevised text.\n")
        return path, self.commit()

    def assert_markdown_publication(self, result, path):
        selected = result["selections"]["normal"]
        self.assertEqual(result["coverage"]["normal"]["paths"], [path])
        self.assertTrue(result["tasks"]["validate"])
        self.assertTrue(selected["checks"]["structure"])
        self.assertEqual(selected["books"], ["one"])
        self.assertEqual({(x["target"], x["variant"]) for x in selected["exports"]},
                         {("html", ""), ("pdf", "screen"), ("epub", "")})
        self.assertTrue(result["tasks"]["build"])
        self.assertEqual(selected["suites"], [])
        self.assertFalse(result["tasks"]["viz"])
        # The stable Check cannot pass after validation/exports unexpectedly skip.
        needs = {job: {"result": "success"} for job in ("plan", *result["tasks"])}
        planner.verify_results(result, needs)
        for job in ("validate", "build"):
            with self.subTest(job=job), self.assertRaisesRegex(ValueError, job + ": expected success"):
                planner.verify_results(result, {**needs, job: {"result": "skipped"}})

    def test_only_book_markdown_push_validates_exports_and_selects_pages_without_a_browser_reader(self):
        import json
        path, head = self.plain_markdown_change()
        for baseline in (True, False):
            with self.subTest(baseline=baseline):
                result = self.make_plan(baseline=baseline)
                self.assert_markdown_publication(result, path)
                output = self.root / "github-output"
                output.write_text("")
                with mock.patch.dict(os.environ, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=""):
                    planner.write_outputs(result)
                fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
                self.assertTrue(json.loads(fields["validate"]))
                self.assertTrue(json.loads(fields["build"]))
                pages = self.make_plan(event="push", workflow="pages", baseline=baseline)
                self.assertTrue(pages["site"])
                self.assertEqual(pages["sha"], head)
                self.assertEqual(pages["coverage"]["pages"]["paths"], [path])

    def test_only_book_markdown_pr_validates_the_tested_merge(self):
        path, head = self.plain_markdown_change()
        self.git("branch", "markdown-head", head)
        self.git("checkout", "-qb", "tested-merge", self.base)
        self.git("merge", "--no-ff", "-qm", "merge fixture", "markdown-head")
        payload = {"pull_request": {"base": {"sha": self.base}, "head": {"sha": head}}}
        for baseline in (True, False):
            with self.subTest(baseline=baseline):
                result = planner.plan(self.root, event="pull_request", payload=payload, repo="owner/books",
                                      branch="main", ref="refs/pull/1/merge",
                                      get_baseline=lambda *args: {"sha": self.base} if baseline else None)
                self.assert_markdown_publication(result, path)
                self.assertFalse(result["publish"])

    def test_link_only_reader_keeps_static_evidence_check_without_unrelated_browser_work(self):
        import json
        name = 'books/one/viz/tests/dependencies.json'
        self.write(name, json.dumps({'schema': planner.DEPENDENCIES, 'suites': {
            'a.test.mjs': ['@lean-links'], 'b.test.mjs': ['trureturing.lock.json']}}))
        tree = planner.Tree(self.root, self.commit())
        result = planner.impact(tree, tree, ['trureturing.lock.json'])
        self.assertNotIn('books/one/viz/tests/a.test.mjs', result['suites'])
        self.assertIn('books/one/viz/tests/b.test.mjs', result['suites'])
        self.assertTrue(result['checks']['structure'])
        self.assertTrue(result['checks']['viz_static'])
        self.assertFalse(result['checks']['browser'])

    def test_image_shards_cover_each_live_page_once_across_all_export_variants(self):
        import json
        for slug in ('one', 'two'):
            self.write(f'books/{slug}/viz/visualizations.json', json.dumps({'visualizations': [
                {'id': 'a', 'status': 'live'}, {'id': 'b', 'status': 'draft'}]}))
        tree = planner.Tree(self.root, self.commit())
        exports = [dict(book=slug, target=target) for slug in ('one', 'two')
                   for target in ('html', 'pdf', 'pdf', 'epub')]
        rows = planner.image_shards(tree, exports)
        self.assertEqual(sorted(i for row in rows for i in row['items']), ['one/a', 'two/a'])
        self.assertEqual(planner.image_shards(tree, [dict(book='one', target='html')]), [])

    def test_stills_follow_capture_inputs_and_published_presets(self):
        import json
        prefix = "books/one/"
        self.write(prefix + "viz/visualizations.json", json.dumps({"visualizations": [
            {"id": "a", "status": "live", "capture_lock": "links"}, {"id": "b", "status": "live"}]}))
        self.write(prefix + "zh/SUMMARY.md", "# Summary\n- [Chapter](chapter.md)\n")
        old = planner.Tree(self.root, self.commit())
        self.write(prefix + "zh/chapter.md", "Only prose changed.\n::: {.viz src=\"a\" preset=\"p\"}\n:::\n")
        current = planner.Tree(self.root, self.commit())
        exports = [dict(book="one", target="pdf"), dict(book="one", target="epub")]
        def selected(head, paths):
            return [item for row in planner.image_shards(head, exports, previous=old, paths=paths)
                    for item in row["items"]]
        self.assertEqual(selected(current, [prefix + "zh/chapter.md"]), [])
        self.assertEqual(selected(current, ["trureturing.lock.json"]), ["one/b"])
        self.assertEqual(selected(current, [prefix + "viz/a/model.js"]), ["one/a"])
        self.write(prefix + "zh/chapter.md", '::: {.viz src="a" preset="new"}\n:::\n')
        self.assertEqual(selected(planner.Tree(self.root, self.commit()), [prefix + "zh/chapter.md"]), ["one/a"])

    def test_format_theme_and_test_changes_have_independent_consumers(self):
        self.write("books/one/slides/a/deck.toml", 'kind="academic"\n')
        self.commit()
        tree = planner.Tree(self.root, "HEAD")
        for path, targets, decks in (
            ("theme/mdbook/head.hbs", {"html"}, []),
            ("theme/epub/book.css", {"epub"}, []),
            ("theme/typst/book.typ", {"pdf"}, []),
            ("theme/typst/pandoc-template.typst", {"pdf"}, []),
            ("theme/typst/cover.typ", {"pdf", "epub"}, []),
            ("theme/typst/fonts/custom/font.otf", {"pdf", "epub"}, ["one/a"]),
            ("theme/typst/nested/unused.typ", set(), []),
            ("tools/filters/tr-book.lua", {"pdf", "epub"}, []),
            ("theme/beamer/beamerthemeTBookAcademic.sty", set(), ["one/a"]),
            ("theme/slides/styles/deck.css", set(), ["one/b", "two/a", "two/b"]),
            ("books/one/viz/tests/a.test.mjs", set(), []),
            ("theme/site/site.css", set(), []),
            ("theme/site/site.js", set(), []),
        ):
            with self.subTest(path=path):
                selected = planner.impact(tree, tree, [path])
                self.assertEqual({v["target"] for v in selected["exports"]}, targets)
                self.assertEqual(selected["slides"], decks)
                self.assertEqual(selected["site"], "/tests/" not in path)
                if "/tests/" in path:
                    self.assertIn(path, selected["suites"])
                    self.assertFalse(selected["checks"]["slides_static"])

    def test_publication_keeps_custom_book_test_readers_from_both_trees(self):
        path = "books/one/viz/tests/a.test.mjs"
        clean = planner.Tree(self.root, self.base)
        self.write("books/one/slides/a/slides.md", "[Fixture](../../viz/tests/a.test.mjs)\n")
        slides = planner.Tree(self.root, self.commit())
        self.assertEqual(planner.impact(slides, clean, [path])["slides"], ["one/a"])
        self.assertEqual(planner.impact(slides, clean, [path])["exports"], [])
        self.write("books/one/zh/chapter.md", "[Fixture](../viz/tests/a.test.mjs)\n")
        book = planner.Tree(self.root, self.commit())
        for current, previous in ((book, clean), (clean, book)):
            result = planner.impact(current, previous, [path])
            self.assertEqual({item["book"] for item in result["exports"]}, {"one"})
            self.assertEqual(result["slides"], ["one/a"])
            self.assertTrue(result["site"])

    def test_viz_fixture_data_and_html_only_runtime_consumers(self):
        self.write("books/one/book.toml", "[outputs]\nhtml=true\npdf=false\nepub=false\n")
        self.write("books/one/figures/probe.py", 'value = (root / "viz" / "tests" / filename).read_text()')
        self.write("books/one/viz/tests/data.txt", "figure input")
        tree = planner.Tree(self.root, self.commit())
        runtime = planner.impact(tree, tree, ["theme/viz/kit.js"])
        self.assertTrue(runtime["checks"]["viz_static"])
        self.assertIn("one", runtime["books"])
        self.assertFalse(any(row["book"] == "one" for row in runtime["exports"]))
        for filename in ("data.txt", "a.test.mjs"):
            fixture = planner.impact(tree, tree, ["books/one/viz/tests/" + filename])
            self.assertEqual({row["book"] for row in fixture["exports"]}, {"one"})
            self.assertTrue(fixture["site"])

    def test_release_and_cache_action_changes_select_direct_tests_and_declared_readers(self):
        import json

        paths = (".github/workflows/release.yml", ".github/workflows/template-release.yml",
                 ".github/actions/build-cache/action.yml", ".github/actions/build-cache/helper.mjs")
        expected = {
            "test_ci_cache_store": ("CacheTransferWorkflowTest", "CacheStoreTest"),
            "test_template": ("WorkflowTests", "OtherTemplateTest"),
            "test_verification": ("BuildCacheWorkflowTests", "PullRequestCacheTests", "LockCheckTests"),
            "test_hide": ("ReleasePlanTests", "OtherHideTest"),
            "test_ci_transport": ("OtherPipelineTest",),
            "test_container": ("ContainerTests",),
        }
        for module, classes in expected.items():
            self.write(f"tools/tests/{module}.py", "import unittest\n" + "".join(
                f"class {cls}(unittest.TestCase):\n    def test_ok(self): pass\n" for cls in classes))
        deps = "books/one/viz/tests/dependencies.json"
        data = json.loads((self.root / deps).read_text())
        data["suites"]["a.test.mjs"] += list(paths)
        self.write(deps, json.dumps(data))
        old = planner.Tree(self.root, self.commit())
        direct = {"test_ci_cache_store.CacheTransferWorkflowTest", "test_template.WorkflowTests",
                  "test_verification.BuildCacheWorkflowTests", "test_verification.PullRequestCacheTests"}
        for path in paths:
            with self.subTest(path=path):
                self.write(path, "name: Change\n")
                head = planner.Tree(self.root, self.commit())
                want = direct | ({"test_hide.ReleasePlanTests"} if path.endswith("/release.yml") else set())
                for current, previous in ((head, old), (old, head)):
                    selected = planner.impact(current, previous, [path])
                    self.assertEqual(set(selected["unit_tests"]), want)
                    self.assertEqual(selected["suites"], ["books/one/viz/tests/a.test.mjs"])
                    for key in ("exports", "films", "slides", "browser_tests"):
                        self.assertEqual(selected[key], [], key)
                    self.assertFalse(selected["site"])
                self.assertEqual(planner.signature(head, "runtime"), planner.signature(old, "runtime"))
                old = head
        self.write(".github/actions/setup/action.yml", "name: Changed setup\n")
        self.assertNotEqual(planner.signature(planner.Tree(self.root, self.commit()), "runtime"),
                            planner.signature(old, "runtime"))

    def test_lock_refresh_only_selects_films_using_the_changed_declaration(self):
        import json
        lock = dict(repo="org/proofs", commit="1" * 40, declarations={"cited": {"line": 1}})
        self.write("books/one/films/001-film/film.json", json.dumps({"lean": ["cited"]}))
        self.write("trureturing.lock.json", json.dumps(lock))
        old = planner.Tree(self.root, self.commit())
        def films():
            head = planner.Tree(self.root, self.commit())
            return planner.impact(head, old, ["trureturing.lock.json"])["films"]
        lock["declarations"]["other"] = {"line": 2}
        self.write("trureturing.lock.json", json.dumps(lock))
        self.assertEqual(films(), [])
        lock["declarations"]["cited"]["line"] = 3
        self.write("trureturing.lock.json", json.dumps(lock))
        self.assertEqual(films(), ["one/001-film"])
        lock["commit"] = "2" * 40
        self.write("trureturing.lock.json", json.dumps(lock))
        self.assertEqual(films(), ["one/001-film", "two/001-film"])

    def test_push_scope_ignores_stale_history_before_looking_for_costs(self):
        self.write("books/two/viz/a/model.js", "upstream\n")
        before = self.commit()
        self.write("docs/PUBLISHING.md", "docs only\n")
        self.commit()
        def unrelated(*args):
            self.fail("documentary push requested historical coverage")
        result = planner.plan(self.root, event="push", payload={"before": before}, repo="owner/books",
                              branch="main", ref="refs/heads/main", get_baseline=unrelated, get_revision=unrelated)
        self.assertFalse(any(result["tasks"].values()))
        self.assertEqual(result["coverage"]["normal"]["paths"], ["docs/PUBLISHING.md"])

    def test_selected_tool_browser_classes_run_exactly_once_and_failure_blocks_coverage(self):
        modules = {}
        for name in planner.testing.BROWSER:
            module, cls = name.split('.')
            modules.setdefault(module, []).append(cls)
        for module, classes in modules.items():
            self.write(f'tools/tests/{module}.py', 'import unittest\n' + '\n'.join(
                f'class {cls}(unittest.TestCase):\n    def test_ok(self): pass\n' for cls in classes))
        self.commit()
        result = self.make_plan(mode='full')
        selected = result['selections']['normal']['browser_tests']
        self.assertGreater(len(selected), 8)
        self.assertEqual(len(result['browser']), 8)
        self.assertEqual(sorted(x for row in result['browser'] for x in row['items']), selected)
        self.assertTrue(result['tasks']['browser'])
        needs = {'plan': {'result': 'success'}, **{job: {'result': 'success'} for job in result['tasks']}}
        planner.verify_results(result, needs)
        needs['browser']['result'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'browser: expected success'):
            planner.verify_results(result, needs)

    def test_registry_entry_reader_skips_other_entries_but_whole_registry_reader_still_runs(self):
        import json
        registry = 'books/one/viz/visualizations.json'
        self.write(registry, json.dumps({'visualizations': [{'id': 'a'}, {'id': 'b'}]}))
        self.write('books/one/viz/tests/dependencies.json', json.dumps({'schema': planner.DEPENDENCIES,
                    'suites': {'a.test.mjs': ['@registry-entry'], 'b.test.mjs': [registry]}}))
        old = planner.Tree(self.root, self.commit())
        self.write(registry, json.dumps({'visualizations': [{'id': 'a'}, {'id': 'b', 'title': 'updated'}]}))
        new = planner.Tree(self.root, self.commit())
        selected = planner.impact(new, old, [registry])
        self.assertNotIn('books/one/viz/tests/a.test.mjs', selected['suites'])
        self.assertIn('books/one/viz/tests/b.test.mjs', selected['suites'])
        self.write(registry, json.dumps({'visualizations': [{'id': 'a', 'title': 'updated'}, {'id': 'b'}]}))
        new = planner.Tree(self.root, self.commit())
        self.assertIn('books/one/viz/tests/a.test.mjs', planner.impact(new, old, [registry])['suites'])

    def test_batch_object_reader_preserves_newlines_in_paths_and_large_contents(self):
        name = 'docs/line\nbreak.md'
        content = 'large\n' * 50000
        self.write(name, content)
        tree = planner.Tree(self.root, self.commit())
        self.assertEqual(tree.read(name), content)
        self.assertEqual(tree.read('docs/PUBLISHING.md'), '说明\n')
        self.assertEqual(tree.read(name), content)

    def test_undeclared_suite_widens_book_not_other_books(self):
        (self.root / "books/one/viz/tests/dependencies.json").unlink()
        self.base = self.commit()
        self.write("books/one/viz/a/model.js", "export const n = 9;\n")
        self.commit()
        self.assertEqual(self.impact()["suites"], [f"books/one/viz/tests/{x}.test.mjs" for x in ("a", "b")])

    def test_unknown_shared_inputs_keep_full_fallback(self):
        tree = planner.Tree(self.root, "HEAD")
        for path in ("package-lock.json", "new-unknown"):
            result = planner.impact(tree, tree, [path])
            self.assertEqual(len(result["suites"]), 4, path)
            self.assertEqual(result["films"], ["one/001-film", "two/001-film"], path)
            self.assertTrue(result["checks"]["unit"], path)
            self.assertTrue(result["reasons"])
        result = planner.impact(tree, tree, ["tools/test.py"])
        self.assertEqual(result["suites"], [])
        self.assertEqual(result["films"], [])
        self.assertTrue(result["checks"]["unit"])
        # Missing roles do not override complete summaries of either kind.
        result = planner.impact(tree, tree, ["theme/unrepresented/new.js"])
        self.assertEqual(result["suites"], [])
        self.assertEqual(result["films"], [])

    def shared_readers(self):
        import json
        self.write("theme/viz/solid-core.js", 'import "./vendor/module.js";\n')
        self.write("theme/viz/vendor/module.js", 'import "./core.js";\n')
        self.write("theme/viz/vendor/core.js", "export const n = 1;\n")
        for path in ("theme/viz/hub.js", "theme/viz/hub.css", "theme/i18n/en.toml", "theme/i18n/zh.toml"):
            self.write(path, "")
        for slug in ("one", "two"):
            prefix = f"books/{slug}/"
            # Actual literal lazy import; the other model is a source-known nonreader.
            self.write(prefix + "viz/a/model.js", 'export const load = () => import("../../../../theme/viz/solid-core.js");\n')
            deps = {"a.test.mjs": [], "b.test.mjs": []}
            if slug == "one":
                # A computed browser request is represented by the complete-read contract,
                # not inferred from a JS import or the presence of a schema key.
                self.write(prefix + "viz/b/model.js", 'export const load = (origin) => fetch(origin + "/one/viz/");\n')
                deps["b.test.mjs"] = ["theme/viz/hub.*", "theme/i18n/*.toml", "i18n/*.toml"]
            self.write(prefix + "viz/tests/dependencies.json", json.dumps({"schema": planner.DEPENDENCIES, "suites": deps}))
            self.write(prefix + "viz/shared/classic.js", "window.MODEL = {};\n")
            self.write(prefix + "films/001-film/film.json", '{"solid":true,"scripts":["viz/shared/classic.js"]}')
            self.write(prefix + "films/002-flat/film.json", '{"solid":false}')
        self.base = self.commit()

    def test_optional_shared_readers_and_publication_are_distinct(self):
        self.shared_readers()
        tree = planner.Tree(self.root, "HEAD")
        full = planner.impact(tree, tree, [], full=True)
        for path in ("theme/viz/solid-core.js", "theme/viz/vendor/module.js", "theme/viz/vendor/core.js",
                     "theme/viz/hub.js", "theme/viz/hub.css", "theme/i18n/en.toml", "i18n/zh.toml"):
            with self.subTest(path=path):
                result = planner.impact(tree, tree, [path])
                solid = path.startswith(("theme/viz/solid-core", "theme/viz/vendor/"))
                self.assertEqual(result["suites"], [f"books/{slug}/viz/tests/a.test.mjs" for slug in ("one", "two")]
                                 if solid else ["books/one/viz/tests/b.test.mjs"])
                self.assertEqual(result["films"], ["one/001-film", "two/001-film"] if solid else
                                 full["films"] if "i18n/" in path else [])
                self.assertFalse(result["checks"]["unit"])
                if path.startswith("theme/viz/"):
                    self.assertEqual({item["target"] for item in result["exports"]}, {"pdf", "epub"})
                    self.assertEqual(result["slides"], [])
                else:
                    self.assertEqual(result["exports"], full["exports"])
                    self.assertEqual(result["slides"], full["slides"])
                for key in ("books", "site"):
                    self.assertEqual(result[key], full[key], key)

    def test_shared_unknown_readers_span_books_and_both_summaries(self):
        import json
        self.shared_readers()
        deps_path = "books/two/viz/tests/dependencies.json"
        data = json.loads((self.root / deps_path).read_text())
        del data["suites"]["b.test.mjs"]
        self.write(deps_path, json.dumps(data))
        unknown = self.commit()
        old = planner.Tree(self.root, self.base)
        head = planner.Tree(self.root, unknown)
        expected = ["books/one/viz/tests/b.test.mjs", "books/two/viz/tests/b.test.mjs"]
        self.assertEqual(planner.impact(head, old, ["theme/viz/hub.js"])["suites"], expected)
        # Restoring a complete declaration for an unchanged reader also describes
        # the former tree; removing a live declaration above still widens coverage.
        self.assertEqual(planner.impact(old, head, ["theme/viz/hub.js"])["suites"], expected[:1])
        # An entirely new book/suite cannot inherit an inapplicable old summary.
        self.write("books/new/book.toml", "[book]\n")
        self.write("books/new/viz/tests/new.test.mjs", "")
        self.write("books/new/viz/tests/dependencies.json", json.dumps({"schema": planner.DEPENDENCIES,
                   "suites": {"new.test.mjs": []}}))
        self.commit()
        result = planner.impact(planner.Tree(self.root, "HEAD"), old, ["theme/viz/hub.js"])
        self.assertIn("books/new/viz/tests/new.test.mjs", result["suites"])

    def test_shared_old_reader_deletion_rename_and_unknown_role(self):
        import json
        self.shared_readers()
        old = planner.Tree(self.root, self.base)
        # Remove a reader edge in head; an old positive edge still selects the live suite.
        self.write("books/one/viz/a/model.js", "export const n = 2;\n")
        self.commit()
        head = planner.Tree(self.root, "HEAD")
        self.assertIn("books/one/viz/tests/a.test.mjs", planner.impact(head, old, ["theme/viz/vendor/core.js"])["suites"])
        (self.root / "theme/viz/vendor/core.js").unlink()
        self.commit()
        self.assertEqual(self.impact()["films"], ["one/001-film", "two/001-film"])
        self.git("mv", "theme/viz/vendor/module.js", "theme/viz/vendor/renamed.js")
        self.commit()
        self.assertEqual(self.impact()["suites"], [f"books/{s}/viz/tests/a.test.mjs" for s in ("one", "two")])
        # Import constructors cover new modules without enumerating vendor filenames.
        self.write("theme/viz/solid-core.js", 'import "./vendor/new.js";\n')
        self.write("theme/viz/vendor/new.js", "")
        self.commit()
        self.assertEqual(self.impact()["suites"], [f"books/{s}/viz/tests/a.test.mjs" for s in ("one", "two")])
        tree = planner.Tree(self.root, "HEAD")
        for path in ("theme/viz/vendor/future.js", "theme/unknown.js", "theme/viz/kit.js"):
            self.assertEqual(planner.impact(tree, tree, [path])["suites"], [], path)
        self.assertEqual(planner.impact(tree, tree, ["i18n/fr.toml"])["suites"], ["books/one/viz/tests/b.test.mjs"])
        # Removed consumers are not executable; publication remains responsible for removal.
        (self.root / "books/one/viz/tests/a.test.mjs").unlink()
        data = json.loads((self.root / "books/one/viz/tests/dependencies.json").read_text())
        del data["suites"]["a.test.mjs"]
        self.write("books/one/viz/tests/dependencies.json", json.dumps(data))
        (self.root / "books/one/films/002-flat/film.json").unlink()
        self.commit()
        result = self.impact()
        self.assertNotIn("books/one/viz/tests/a.test.mjs", result["suites"])
        self.assertNotIn("one/002-flat", result["films"])
        self.assertTrue(result["site"])

    def test_shared_local_override_add_delete_and_invalid_inventory(self):
        self.shared_readers()
        self.write("i18n/en.toml", '[film]\nopen="Open"\n')
        created = self.commit()
        expected_films = [f"{slug}/{film}" for slug in ("one", "two") for film in ("001-film", "002-flat")]
        self.assertEqual(self.impact()["films"], expected_films)
        (self.root / "i18n/en.toml").unlink()
        self.commit()
        self.assertEqual(self.impact(created)["films"], expected_films)
        self.write("books/one/viz/tests/dependencies.json", '{"schema":"bad","suites":{}}')
        self.commit()
        with self.assertRaisesRegex(ValueError, "invalid schema"):
            self.impact()

    def test_shared_constructor_inputs_do_not_schedule_proved_browser_nonreaders(self):
        self.shared_readers()
        for p in ("theme/film/engine.js", "theme/film/lib.js", "theme/generated/tokens.mjs",
                  "theme/film/site/films.js", "theme/slides/components/Source.vue"):
            self.write(p, "// source\n")
        self.base = self.commit()
        tree = planner.Tree(self.root, self.base)
        full = planner.impact(tree, tree, [], full=True)
        for p in ("theme/film/engine.js", "theme/film/lib.js", "theme/generated/tokens.mjs",
                  "theme/film/site/films.js", "theme/slides/components/Source.vue", "theme/film/new-stage.js"):
            with self.subTest(path=p):
                result = planner.impact(tree, tree, [p])
                self.assertEqual(result["suites"], [])
                self.assertEqual(result["films"], [] if p.startswith(("theme/film/site/", "theme/slides/")) else full["films"])
                self.assertFalse(result["checks"]["unit"])
                self.assertTrue(result["site"])
                self.assertEqual(result["exports"], [])
                self.assertEqual(result["slides"], full["slides"] if p.startswith("theme/slides/") else [])
                self.assertEqual(result["books"], [] if p.startswith("theme/film/site/") else full["books"])

    def test_declared_shared_imports_and_implicit_object_imports_cover_future_members(self):
        import json
        # No resource role/name registry: one declared module generates its closure.
        self.write("theme/other/runtime.mjs", 'import "./new-part.mjs";\n')
        self.write("theme/other/new-part.mjs", "export const n=1;\n")
        self.write("books/one/viz/a/main.js", 'import "../../../../theme/other/implicit.mjs";\n')
        self.write("theme/other/implicit.mjs", "export const n=1;\n")
        p = "books/two/viz/tests/dependencies.json"
        data = json.loads((self.root / p).read_text())
        data["suites"]["b.test.mjs"].append("theme/other/runtime.mjs")
        self.write(p, json.dumps(data))
        old = planner.Tree(self.root, self.commit())
        self.write("theme/other/runtime.mjs", 'import "./renamed-part.mjs";\n')
        self.git("mv", "theme/other/new-part.mjs", "theme/other/renamed-part.mjs")
        head = planner.Tree(self.root, self.commit())
        for path in ("theme/other/new-part.mjs", "theme/other/renamed-part.mjs"):
            self.assertEqual(planner.impact(head, old, [path])["suites"], ["books/two/viz/tests/b.test.mjs"])
        self.assertEqual(planner.impact(head, old, ["theme/other/implicit.mjs"])["suites"],
                         ["books/one/viz/tests/a.test.mjs"])

    def test_arbitrary_shared_read_summary_positive_old_and_unknown_are_separate(self):
        import json
        self.shared_readers()
        path = "books/one/viz/tests/dependencies.json"
        data = json.loads((self.root / path).read_text())
        data["suites"]["b.test.mjs"].append("theme/film/**")
        self.write(path, json.dumps(data))
        self.write("theme/film/engine.js", "// engine\n")
        old = planner.Tree(self.root, self.commit())
        data["suites"]["b.test.mjs"].remove("theme/film/**")
        self.write(path, json.dumps(data))
        head = planner.Tree(self.root, self.commit())
        expected = ["books/one/viz/tests/b.test.mjs"]
        for current, previous in ((head, old), (old, head)):
            # Correcting a complete declaration also refines the unchanged old reader.
            self.assertEqual(planner.impact(current, previous, ["theme/film/engine.js"])["suites"],
                             [] if current is head else expected)
        del data["suites"]["b.test.mjs"]
        self.write(path, json.dumps(data))
        unknown = planner.Tree(self.root, self.commit())
        for current, previous in ((head, unknown), (unknown, head)):
            self.assertEqual(planner.impact(current, previous, ["theme/film/engine.js"])["suites"],
                             [] if current is head else expected)
        self.write("books/one/viz/b/model.js", "export const n = 2;\n")
        self.write(path, json.dumps({"schema": planner.DEPENDENCIES, "suites": data["suites"] | {"b.test.mjs": []}}))
        edited = planner.Tree(self.root, self.commit())
        for current, previous in ((edited, old), (old, edited)):
            self.assertEqual(planner.impact(current, previous, ["theme/film/engine.js"])["suites"], expected)

    def test_unsupported_inline_module_keeps_only_its_film_uncertain_in_either_tree(self):
        self.shared_readers()
        self.write("theme/viz/kit.js", "// browser-only\n")
        old = planner.Tree(self.root, self.commit())
        for code in ('const load = (url) => import(url);\n', 'import model from "./resource.js";\n'):
            self.write("books/two/films/002-flat/scenes.js", code)
            head = planner.Tree(self.root, self.commit())
            for current, previous in ((head, old), (old, head)):
                selected = planner.impact(current, previous, ["theme/viz/kit.js"])
                self.assertEqual(selected["suites"], [])
                self.assertEqual(selected["films"], ["two/002-flat"])
                # Unknown local reads follow the same consumer scope as unknown suites.
                selected = planner.impact(current, previous, ["books/two/viz/b/main.js"])
                self.assertEqual(selected["films"], ["two/002-flat"])
                selected = planner.impact(current, previous, ["books/one/viz/b/main.js"])
                self.assertEqual(selected["films"], [])

    def test_new_film_summary_is_inapplicable_in_old_tree_and_malformed_meta_is_error(self):
        self.shared_readers()
        self.write("theme/viz/kit.js", "// browser-only\n")
        old = planner.Tree(self.root, self.commit())
        self.write("books/one/films/003-new/film.json", "{}")
        head = planner.Tree(self.root, self.commit())
        self.assertEqual(planner.impact(head, old, ["theme/viz/kit.js"])["films"], ["one/003-new"])
        for text in ('{"solid":"yes"}', '{"scripts":["../outside.js"]}'):
            self.write("books/one/films/003-new/film.json", text)
            with self.assertRaises(ValueError):
                planner.inventory(planner.Tree(self.root, self.commit()))

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

    def test_ci_and_pages_split_film_work_into_up_to_sixteen_jobs(self):
        names = [f"film-{index:02d}" for index in range(15)]
        for name in names:
            self.write(f"books/one/films/{name}/film.json", "{}")
        self.commit()

        added = [f"one/{name}" for name in names]
        cases = (
            (self.make_plan(event="workflow_dispatch"), added),
            (self.make_plan(workflow="pages", mode="full"),
             sorted([*added, "one/001-film", "two/001-film"])),
        )
        for result, expected in cases:
            with self.subTest(profiles=result["profiles"]):
                parts = result["films"]
                self.assertTrue(result["tasks"]["films"])
                self.assertEqual(len(parts), min(len(expected), 16))
                self.assertTrue(all(part["items"] for part in parts))
                self.assertEqual(sorted(item for part in parts for item in part["items"]), expected)

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
        self.write("tools/ci/stills.py", "import sys\nassert sys.argv[1:] == ['--ensure-books', 'one', 'two']\n")
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
        self.assertFalse(self.make_plan(baseline=False)["tasks"]["viz"])
        self.assertTrue(self.make_plan(mode="full")["tasks"]["viz"])
        self.assertFalse(self.make_plan(base=self.base, baseline=False)["tasks"]["viz"])
        tree = planner.Tree(self.root, "HEAD")
        signature = planner.signature(tree, "runtime-one")
        self.assertNotEqual(signature, planner.signature(tree, "runtime-two"))
        self.write("tools/test.py", "changed\n")
        self.commit()
        self.assertEqual(signature, planner.signature(planner.Tree(self.root, "HEAD"), "runtime-one"))

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
        self.assertFalse(first["tasks"]["viz-slow"])
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
        result = self.make_plan(event="workflow_dispatch", workflow="pages")
        self.assertFalse(result["site"])
        self.assertEqual(result["profiles"], ["pages"])
        planner.verify_results(result, {"plan": {"result": "success"}, "probe": {"result": "success"},
                                       "build": {"result": "skipped"}, "deploy": {"result": "skipped"}}, pages=True)
        self.assertTrue(self.make_plan(event="workflow_dispatch", workflow="pages", baseline=False)["site"])
        self.assertTrue(self.make_plan(event="push", workflow="pages")["site"])
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
        self.assertEqual(result["selections"]["normal"]["suites"], ["books/one/viz/tests/a.test.mjs"])
        self.assertEqual(result["coverage"]["normal"]["comparison"], base_tip)
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
        shutil.rmtree(self.root / "viz-reports", ignore_errors=True)
        write_browser_reports(self.write, result)
        if workflow == "ci":
            results = {"plan": {"result": "success"}, **{
                job: {"result": "success" if selected else "skipped"} for job, selected in result["tasks"].items()}}
        else:
            results = {"plan": {"result": "success"}, "probe": {"result": "success"},
                       "films": {"result": "success" if result.get('films') else "skipped"},
                       "build": {"result": outcome if result["site"] else "skipped"},
                       "deploy": {"result": "success" if result["site"] and enabled else "skipped"}}
        results["plan"]["outputs"] = {"plan": json.dumps(result)}
        self.write("ci-needs.json", json.dumps(results))
        script = Path(__file__).parents[1] / "ci/plan.py"
        verified = self.subprocess.run([sys.executable, str(script), "--workflow", workflow, "--verify"],
                                      cwd=self.root, env=dict(os.environ, GITHUB_RUN_ATTEMPT="1", PAGES_ENABLED=str(enabled).lower()),
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
        (self.root / ".git/info/exclude").write_text("coverage/\nviz-reports/\nci-needs.json\n")
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
                self.assert_films(self.docs_pr(), [])

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
                    no_op = self.select("workflow_dispatch", workflow="pages")
                    self.assertFalse(no_op["site"])
                    self.assertNotIn("films", no_op["coverage"])
                    self.finish(no_op, "pages")
                self.assert_films(self.docs_pr(), [])

    def test_missing_film_artifact_keeps_unchanged_films_out_of_the_git_diff(self):
        self.bootstrap()
        self.docs()
        self.finish(self.select())
        for artifacts in self.artifacts.values():
            artifacts[:] = [a for a in artifacts if a["name"] != "tbook-coverage-films"]
        result = self.select("workflow_dispatch")
        self.assert_films(result, [])
        self.assertTrue(any("films: changes only" in reason for reason in result["reasons"]))

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
        tagged = self.select(ref="refs/tags/v1.0.0", own=False, payload={"before": "0" * 40})
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
    def test_book_markdown_is_not_filtered_out_of_pr_or_main_push_events(self):
        import re
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        events = re.search(r"^on:\n(.*?)^permissions:", workflow.read_text(), re.M | re.S).group(1)
        for name in ("pull_request", "push"):
            block = re.search(rf"^  {name}:\n(.*?)(?=^  \w|\Z)", events, re.M | re.S).group(1)
            self.assertNotRegex(block, r"(?m)^    (?:paths|paths-ignore):")
            if name == "push":
                self.assertIn("branches: [main]", block)

    def test_pages_cadence_selects_only_own_successful_ci_or_schedule_events(self):
        import re
        from test_verification import gha_if
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/pages.yml"
        condition = " ".join(re.search(r"    name: Select a verified Pages update\n    if: >-\n(.*?)^    permissions:",
                                       workflow.read_text(), re.M | re.S).group(1).split())
        context = {"github.event.workflow_run.conclusion": "success",
                   "github.event.workflow_run.event": "push",
                   "github.event.workflow_run.head_repository.full_name": "owner/books",
                   "github.event.schedule": "",
                   "github.repository": "owner/books"}
        self.assertTrue(gha_if(condition, event="workflow_run", ref="refs/heads/main", context=context))
        for change in ({"github.event.workflow_run.conclusion": "cancelled"},
                       {"github.event.workflow_run.conclusion": "failure"},
                       {"github.event.workflow_run.event": "pull_request"},
                       {"github.event.workflow_run.head_repository.full_name": "fork/books"}):
            with self.subTest(change=change):
                self.assertFalse(gha_if(condition, event="workflow_run", ref="refs/heads/main",
                                        context={**context, **change}))
        self.assertTrue(gha_if(condition, event="schedule", ref="refs/heads/main",
                               context={name: "" for name in context}))
        self.assertFalse(gha_if(condition, event="schedule", ref="refs/heads/main",
                                context={**context, "github.event.schedule": "17 5 * * *"}))

    def test_only_superseded_pull_requests_cancel_running_ci(self):
        import re
        from test_verification import gha_if
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        condition = re.search(r"^  cancel-in-progress: (.+)$", workflow.read_text(), re.M).group(1)
        for event, ref, ref_type in (("pull_request", "refs/pull/1/merge", "branch"),
                                     ("push", "refs/heads/main", "branch"),
                                     ("push", "refs/tags/v1.5.3", "tag"),
                                     ("workflow_dispatch", "refs/heads/main", "branch"),
                                     ("schedule", "refs/heads/main", "branch")):
            with self.subTest(event=event, ref=ref):
                self.assertEqual(gha_if(condition, event=event, ref=ref,
                                        context={"github.ref_type": ref_type}), event == "pull_request")

    def test_deploy_after_optional_films_skip_requires_successful_assembly(self):
        import re
        from test_verification import gha_if
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/pages.yml"
        block = workflow.read_text().split("\n  deploy:\n", 1)[1].split("\n  coverage:\n", 1)[0]
        condition = re.search(r"^    if: (.+)$", block, re.M).group(1).strip('"')
        for films in ("success", "skipped"):
            for build in ("success", "failure", "cancelled", "skipped"):
                for enabled, site, cancelled in (("true", "true", False), ("false", "true", False),
                                                  ("true", "false", False), ("true", "true", True)):
                    # GitHub implicitly requires successful ancestors unless the condition
                    # contains a status function, even if the direct build need succeeded.
                    implicit_success = (films == "success" and build == "success")
                    explicit_status = bool(re.search(r"\b(?:always|success|failure|cancelled)\(", condition))
                    allowed = (explicit_status or implicit_success) and gha_if(
                        condition, event="workflow_run", ref="refs/heads/main", cancelled=cancelled,
                        context={"needs.build.result": build, "needs.plan.outputs.site": site,
                                 "needs.probe.outputs.enabled": enabled})
                    with self.subTest(films=films, build=build, enabled=enabled, site=site, cancelled=cancelled):
                        self.assertEqual(allowed, build == "success" and enabled == site == "true" and not cancelled)

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
                mock.patch.object(runner.theme, "write"), \
                mock.patch.object(runner.derived, "refresh"), \
                mock.patch.object(runner.build, "_figures") as figures, \
                mock.patch.object(runner.buildcache, "slides_unit", return_value=unit), \
                mock.patch.object(runner.buildcache, "run", return_value="missing") as cache, \
                mock.patch.object(runner.slides, "_build_slidev") as execute, \
                mock.patch.object(runner.slides, "build") as whole:
            runner.selected_slides(["book/a"])
            figures.assert_called_once_with(book)
            cache.assert_called_once_with(unit, None, repo="owner/books")
            self.assertEqual(execute.call_args.kwargs, {"decks": ["a"]})
            whole.assert_not_called()
            execute.reset_mock()
            cache.reset_mock()
            runner.selected_slides(["book/a", "book/b"])
            whole.assert_called_once()
            cache.assert_not_called()
            execute.assert_not_called()
            with self.assertRaises(ValueError):
                runner.selected_slides(["book/missing"])
