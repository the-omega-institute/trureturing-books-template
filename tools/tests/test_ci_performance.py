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
