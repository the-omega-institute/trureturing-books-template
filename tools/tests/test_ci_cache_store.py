"""CI transfers verified whole entries, keeps input-key misses, and never publishes PR stores."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

from tbook import buildcache
from test_buildcache import Scratch, tree, write
from test_ci_performance import ci_module
from test_verification import GITHUB_DIR, action_steps, gha_if, workflow_jobs

cache_store = ci_module("cache_store")


class CacheStoreTest(unittest.TestCase):
    def unit(self, root, value="one"):
        return buildcache.Unit("pdf", "demo/zh/screen", buildcache.Inputs().text("chapter", value),
                               [root / "build/book.pdf", root / "build/figures"])

    def store(self, root, value="one", content="first"):
        unit = self.unit(root, value)
        write(unit.outputs[0], content)
        write(unit.outputs[1] / "drawing.svg", content + " drawing")
        buildcache.store(unit)
        return unit

    def test_only_added_verified_entries_are_exported(self):
        with Scratch() as s:
            before = self.store(s.root)
            baseline = s.root / "before.json"
            self.assertEqual(cache_store.snapshot(buildcache.store_root(), baseline), 1)
            added = self.store(s.root, "two")
            out = s.root / "shard"
            self.assertEqual(cache_store.export(buildcache.store_root(), baseline, out), 1)
            self.assertFalse((out / before.entry_dir().relative_to(buildcache.store_root())).exists())
            exported = out / added.entry_dir().relative_to(buildcache.store_root())
            self.assertEqual(buildcache.verify(exported), "")
            # A repaired entry counts as added when the restored bytes were already damaged.
            (before.entry_dir() / "files/0").write_text("corrupt", encoding="utf-8")
            cache_store.snapshot(buildcache.store_root(), baseline)
            self.store(s.root)
            self.assertEqual(cache_store.export(buildcache.store_root(), baseline, out), 1)

    def test_same_input_key_is_never_merged_file_by_file(self):
        with Scratch() as s:
            unit = self.store(s.root, content="first")
            first, second = s.root / "first", s.root / "second"
            shutil.copytree(buildcache.store_root(), first)
            shutil.rmtree(buildcache.store_root())
            self.store(s.root, content="different encoding")
            shutil.copytree(buildcache.store_root(), second)
            shutil.rmtree(buildcache.store_root())
            self.assertEqual(cache_store.merge(buildcache.store_root(), [first, second]), 1)
            self.assertEqual(tree(unit.entry_dir()), tree(first / unit.entry_dir().relative_to(buildcache.store_root())))
            self.assertTrue(buildcache.restore_local(unit))
            self.assertEqual(unit.outputs[0].read_text(), "first")
            self.assertEqual((unit.outputs[1] / "drawing.svg").read_text(), "first drawing")
            # A later shard for the same key cannot replace the validated encoding already present.
            cache_store.merge(buildcache.store_root(), [second])
            self.assertEqual(buildcache.verify(unit.entry_dir()), "")
            self.assertTrue(buildcache.restore_local(unit))
            self.assertEqual(unit.outputs[0].read_text(), "first")

    def test_selected_film_cache_hits_survive_an_older_complete_aggregate_baseline(self):
        with Scratch() as s:
            def film_unit(value):
                return buildcache.Unit("films", "demo/explanation", buildcache.Inputs().text("film", value),
                                       [s.root / "build/film.mp4"])
            current = film_unit("current")
            for index in range(buildcache.KEEP):
                old = film_unit(f"old-{index}")
                write(old.outputs[0], "old video")
                buildcache.store(old)
                meta = json.loads((old.entry_dir() / "entry.json").read_text())
                (old.entry_dir() / "entry.json").write_text(json.dumps(dict(meta, created=100 + index)))
            stale = s.root / "complete-store"
            shutil.copytree(buildcache.store_root(), stale)
            shutil.rmtree(buildcache.store_root())
            write(current.outputs[0], "current video")
            buildcache.store(current)
            meta = json.loads((current.entry_dir() / "entry.json").read_text())
            (current.entry_dir() / "entry.json").write_text(json.dumps(dict(meta, created=1)))
            self.store(s.root)  # unrelated unchanged PDF must remain out of the shard
            baseline, shard = s.root / "before.json", s.root / "film-shard"
            cache_store.snapshot(buildcache.store_root(), baseline)
            self.assertTrue(buildcache.restore_local(current))
            self.assertEqual(cache_store.export(buildcache.store_root(), baseline, shard), 0)
            self.assertEqual(cache_store.export(buildcache.store_root(), baseline, shard,
                                               include_units={("films", current.name)}), 1)
            self.assertFalse((shard / "pdf").exists())
            cache_store.merge(stale, [shard], prefer_imported=True)
            entry = stale / current.entry_dir().relative_to(buildcache.store_root())
            self.assertEqual(buildcache.verify(entry), "")
            self.assertEqual((entry / "files/0").read_text(), "current video")

    def test_corruption_wrong_identity_and_links_are_not_imported(self):
        with Scratch() as s:
            unit = self.store(s.root)
            shard = s.root / "shard"
            shutil.copytree(buildcache.store_root(), shard)
            entry = shard / unit.entry_dir().relative_to(buildcache.store_root())
            shutil.rmtree(buildcache.store_root())
            stored_pdf = entry / "files/0"
            original = stored_pdf.read_bytes()
            stored_pdf.write_bytes(b"damaged")
            self.assertEqual(cache_store.merge(buildcache.store_root(), [shard]), 0)
            stored_pdf.write_bytes(original)
            meta = json.loads((entry / "entry.json").read_text())
            (entry / "entry.json").write_text(json.dumps(dict(meta, unit="other/zh/screen")))
            self.assertEqual(cache_store.merge(buildcache.store_root(), [shard]), 0)
            (entry / "entry.json").write_text(json.dumps(meta))
            external = write(s.root / "external.pdf", original)
            stored_pdf.unlink()
            stored_pdf.symlink_to(external)
            self.assertEqual(cache_store.merge(buildcache.store_root(), [shard]), 0)
            self.assertEqual(external.read_bytes(), original)
            self.assertFalse(buildcache.restore_local(unit))

    def test_merge_preserves_only_recent_valid_keys_without_tools_or_fonts(self):
        with Scratch() as s:
            units = []
            with mock.patch.object(buildcache, "_keep_newest"):
                for index in range(buildcache.KEEP + 2):
                    unit = self.store(s.root, str(index))
                    entry = unit.entry_dir()
                    meta = json.loads((entry / "entry.json").read_text())
                    meta["created"] = index
                    (entry / "entry.json").write_text(json.dumps(meta))
                    units.append(unit)
            shard = s.root / "shard"
            shutil.copytree(buildcache.store_root(), shard)
            shutil.rmtree(buildcache.store_root())
            external = s.root / "external"
            write(external / "keep.txt", "outside")
            buildcache.store_root().mkdir(parents=True)
            (buildcache.store_root() / "linked").symlink_to(external, target_is_directory=True)
            write(buildcache.store_root() / "junk.txt", "unverified")
            with mock.patch.object(buildcache, "units", side_effect=AssertionError("no toolchain key calculation")):
                self.assertEqual(cache_store.merge(buildcache.store_root(), [shard]), buildcache.KEEP)
            self.assertEqual(len(buildcache.stored()), buildcache.KEEP)
            self.assertFalse((buildcache.store_root() / "linked").exists())
            self.assertFalse((buildcache.store_root() / "junk.txt").exists())
            self.assertEqual((external / "keep.txt").read_text(), "outside")
            self.assertTrue(buildcache.restore_local(units[-1]))
            self.assertEqual(buildcache.run(self.unit(s.root, "new input"), None), "missing")

    def test_root_links_and_overlapping_transfers_are_refused(self):
        with Scratch() as s:
            unit = self.store(s.root)
            baseline = s.root / "before.json"
            cache_store.snapshot(buildcache.store_root(), baseline)
            for out in (buildcache.store_root(), buildcache.store_root().parent,
                        buildcache.store_root() / "nested"):
                with self.subTest(out=out), self.assertRaises(ValueError):
                    cache_store.export(buildcache.store_root(), baseline, out)
            linked = s.root / "linked"
            linked.symlink_to(buildcache.store_root(), target_is_directory=True)
            with self.assertRaises(ValueError):
                cache_store.merge(linked, [])
            self.assertEqual(buildcache.verify(unit.entry_dir()), "")


class CacheTransferWorkflowTest(unittest.TestCase):
    def test_film_actions_cache_hit_skips_the_complete_store_but_miss_can_migrate(self):
        steps = action_steps("build-cache")
        films = next(s for s in steps if s.get("id") == "film-restore")
        legacy = next(s for s in steps if s.get("id") == "restore")
        for scope in ("all", "images", "films"):
            for matched in ("", "film-cache-v1-123"):
                context = {"inputs.mode": "restore", "inputs.scope": scope,
                           "steps.film-restore.outputs.cache-matched-key": matched}
                self.assertEqual(gha_if(films["if"], event="push", ref="refs/heads/main", context=context),
                                 scope == "films")
                self.assertEqual(gha_if(legacy["if"], event="push", ref="refs/heads/main", context=context),
                                 scope != "films" or not matched)
                for step in (films, legacy):
                    self.assertFalse(gha_if(step["if"], event="pull_request", ref="refs/pull/1/merge", context=context))

    def test_film_shards_restore_only_videos_and_publish_after_trusted_success(self):
        for workflow in ("ci.yml", "pages.yml"):
            jobs = workflow_jobs(GITHUB_DIR / "workflows" / workflow)
            restore = next(s for s in jobs["films"] if s.get("uses") == "./.github/actions/build-cache")
            self.assertEqual(restore["with"]["scope"], "films")
            export = next(s for s in jobs["films"] if "cache_store.py export" in s.get("run", ""))
            env_name = "CI_ITEMS" if workflow == "ci.yml" else "FILMS_JSON"
            self.assertIn(f"--include-films-env {env_name}", export["run"])
            self.assertEqual(export["env"][env_name], "${{ toJSON(matrix.items) }}")
            producer = jobs["check" if workflow == "ci.yml" else "build"]
            merge = next(s for s in producer if "cache_store.py merge" in s.get("run", ""))
            self.assertIn("--prefer-imported", merge["run"])
            publish = next(s for s in producer if s.get("with", {}).get("name") == "tbook-film-store")
            save = next(s for s in producer if s.get("with", {}).get("key", "").startswith("film-cache-v1-"))
            self.assertEqual(save["with"]["path"], ".cache/artifacts/films")
            self.assertEqual(publish["with"]["path"], ".cache/artifacts/films")
            context = {"steps.verified.outcome": "success", "needs.plan.outputs.films": "true",
                       "steps.cache-merge.outputs.entries": "1"}
            for step in (save, publish):
                self.assertTrue(gha_if(step["if"], event="push", ref="refs/heads/main", context=context))
                self.assertFalse(gha_if(step["if"], event="pull_request", ref="refs/pull/1/merge", context=context))
                self.assertNotIn("always()", step["if"])
                if workflow == "ci.yml":
                    self.assertFalse(gha_if(step["if"], event="push", ref="refs/heads/main",
                                            context={**context, "needs.plan.outputs.films": "false"}))
                    self.assertFalse(gha_if(step["if"], event="push", ref="refs/heads/main",
                                            context={**context, "steps.verified.outcome": "failure"}))

    def test_only_default_branch_jobs_upload_shards_and_the_aggregate_publishes_after_verification(self):
        jobs = workflow_jobs(GITHUB_DIR / "workflows/ci.yml")
        for job in ("build", "media", "films"):
            steps = jobs[job]
            snapshot = next(s for s in steps if "cache_store.py snapshot" in s.get("run", ""))
            export = next(s for s in steps if "cache_store.py export" in s.get("run", ""))
            upload = next(s for s in steps if s.get("with", {}).get("name", "").startswith("tbook-build-shard-"))
            self.assertIn("${{ github.run_attempt }}", upload["with"]["name"])
            self.assertLess(steps.index(snapshot), steps.index(export))
            self.assertLess(steps.index(export), steps.index(upload))
            for step in (snapshot, export, upload):
                step_context = {"steps.cache-shard.outputs.entries": "1"}
                for event in ("push", "workflow_dispatch", "schedule"):
                    self.assertTrue(gha_if(step["if"], event=event, ref="refs/heads/main", context=step_context))
                for event, ref in (("pull_request", "refs/pull/1/merge"),
                                   ("pull_request_target", "refs/heads/main"),
                                   ("push", "refs/heads/feature"), ("push", "refs/tags/v1")):
                    self.assertFalse(gha_if(step["if"], event=event, ref=ref, context=step_context))
        steps = jobs["check"]
        verify = next(i for i, s in enumerate(steps) if "--verify --needs-file" in s.get("run", ""))
        merge = next(i for i, s in enumerate(steps) if "cache_store.py merge" in s.get("run", ""))
        publish = next(i for i, s in enumerate(steps) if s.get("with", {}).get("name") == "tbook-build-store")
        self.assertLess(verify, merge)
        self.assertLess(merge, publish)
        self.assertNotIn("always()", steps[merge]["if"])
        self.assertNotIn("continue-on-error", steps[verify], "failed plan verification must stop publication")
        download = next(s for s in steps if s.get("with", {}).get("pattern", "").startswith("tbook-build-shard-"))
        self.assertNotEqual(download["with"].get("merge-multiple"), "true")
        self.assertIn("${{ github.run_attempt }}", download["with"]["pattern"])
        save = next(s for s in steps if s.get("uses") == "./.github/actions/build-cache" and s["with"]["mode"] == "save")
        self.assertEqual(save["with"]["prune"], "false")
        context = {f"needs.plan.outputs.{key}": "true" for key in ("build", "media", "films")}
        context["steps.verified.outcome"] = "success"
        self.assertTrue(gha_if(steps[merge]["if"], event="push", ref="refs/heads/main", context=context))
        for outcome in ("failure", "cancelled", "skipped", ""):
            self.assertFalse(gha_if(steps[merge]["if"], event="push", ref="refs/heads/main",
                                    context={**context, "steps.verified.outcome": outcome}))
        for event, ref in (("pull_request", "refs/pull/1/merge"), ("pull_request_target", "refs/heads/main"),
                           ("push", "refs/heads/feature"), ("workflow_dispatch", "refs/heads/feature"),
                           ("push", "refs/tags/v1")):
            self.assertFalse(gha_if(steps[merge]["if"], event=event, ref=ref, context=context))


if __name__ == "__main__":
    unittest.main()
