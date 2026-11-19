"""Regression cases for selecting a Pages update from verified Git history."""
from datetime import datetime, timedelta, timezone
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ci import pages_schedule, trusted_cache


class PagesScheduleTests(unittest.TestCase):
    repo = "owner/books"
    now = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.git("init", "-qb", "main")
        self.shas = []
        for name in ("live", "eligible", "newer", "head"):
            (self.root / "site.toml").write_text(f'# {name}\n')
            self.git("add", "site.toml")
            self.git("-c", "user.name=Test", "-c", "user.email=test@example.org",
                     "commit", "--allow-empty", "-qm", name)
            self.shas.append(self.git("rev-parse", "HEAD"))
        self.live, self.eligible, self.newer, self.head = self.shas
        self.deployments = [dict(id=1, sha=self.live, created_at=self.ago(30))]
        self.statuses = {1: [dict(state="success", created_at=self.ago(20))]}
        self.ci = [self.run_record(self.eligible), self.run_record(self.newer)]
        self.registrations = {sha: [self.run_record(sha)] for sha in self.shas}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def ago(self, minutes):
        return (self.now - timedelta(minutes=minutes)).isoformat()

    def run_record(self, sha, **changes):
        return dict(head_branch="main", event="push", head_repository={"full_name": self.repo},
                    head_sha=sha, status="completed", conclusion="success", run_attempt=1,
                    display_title=trusted_cache.PAGES_PUSH_TITLE + sha) | changes

    def api(self, endpoint):
        path, query = urlsplit(endpoint).path, parse_qs(urlsplit(endpoint).query)
        if path.endswith("/deployments"):
            return self.deployments
        if path.endswith("/statuses"):
            return self.statuses[int(path.split("/")[-2])]
        if path.endswith("/ci.yml/runs"):
            return {"workflow_runs": self.ci}
        if path.endswith("/pages.yml/runs"):
            return {"workflow_runs": self.registrations.get(query["head_sha"][0], [])}
        if path.endswith("/pages"):
            return {"html_url": "https://books.example.org/"}
        self.fail(f"Unexpected endpoint: {endpoint}")

    def choose(self):
        candidate = pages_schedule.select(self.root, self.repo, "main", self.head, self.now, self.api)
        return candidate["head_sha"] if candidate else None

    def test_newest_verified_main_commit_is_selected_once_due(self):
        self.ci.extend([
            self.run_record(self.head, conclusion="failure"),
            self.run_record(self.head, event="pull_request"),
            self.run_record(self.head, head_repository={"full_name": "fork/books"}),
            self.run_record(self.head, status="in_progress"),
        ])
        self.assertEqual(self.choose(), self.newer)

    def test_compares_net_publication_inputs_with_live_site(self):
        self.git("checkout", "-q", self.live, "--", "site.toml")
        (self.root / "README.md").write_text("Engineering notes")
        self.git("add", "README.md")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "revert site and document")
        self.head = self.git("rev-parse", "HEAD")
        self.ci.append(self.run_record(self.head))
        self.registrations[self.head] = [self.run_record(self.head)]
        self.assertIsNone(self.choose())
        self.deployments.clear()
        self.assertEqual(self.choose(), self.head, "the first site still needs a deployment")

    def test_cooldown_uses_success_time_and_counts_failed_deployments(self):
        self.statuses[1][0]["created_at"] = self.ago(19)
        self.assertIsNone(self.choose())
        self.statuses[1][0]["created_at"] = self.ago(20)
        self.deployments.insert(0, dict(id=2, sha=self.newer, created_at=self.ago(3)))
        self.statuses[2] = [dict(state="failure", created_at=self.ago(2))]
        self.assertIsNone(self.choose())
        self.deployments[0]["created_at"] = self.ago(20)
        self.assertEqual(self.choose(), self.newer)

    def test_skips_published_or_divergent_versions_and_legacy_runs(self):
        self.registrations[self.newer][0]["display_title"] = "Prior Pages workflow"
        self.assertEqual(self.choose(), self.eligible)
        self.deployments[0]["sha"] = self.newer
        self.assertIsNone(self.choose())
        self.deployments[0]["sha"] = "0" * 40
        self.assertIsNone(self.choose())

    def test_registration_and_scheduler_are_not_build_cache_producers(self):
        first = self.run_record(self.eligible)
        self.assertFalse(trusted_cache.pages_producer(first))
        self.assertTrue(trusted_cache.pages_producer(dict(first, run_attempt=2)))
        for event in ("schedule", "workflow_run"):
            self.assertFalse(trusted_cache.pages_producer(dict(
                first, event=event, display_title=trusted_cache.PAGES_SCHEDULER_TITLE)))
        self.assertTrue(trusted_cache.pages_producer(dict(
            first, event="schedule", display_title=trusted_cache.PAGES_REFRESH_TITLE)))

    def test_refresh_requires_the_live_book_commit_and_its_successful_push_ci(self):
        self.assertFalse(pages_schedule.refresh_due(self.repo, "main", self.head, self.now, self.api))
        self.assertFalse(pages_schedule.refresh_due(self.repo, "main", self.live, self.now, self.api))
        self.ci.append(self.run_record(self.live))
        self.assertTrue(pages_schedule.refresh_due(self.repo, "main", self.live, self.now, self.api))
        self.statuses[1][0]["created_at"] = self.ago(19)
        self.assertFalse(pages_schedule.refresh_due(self.repo, "main", self.live, self.now, self.api))

    def test_refresh_pins_the_branch_head_only_when_the_live_snapshot_differs(self):
        site = SimpleNamespace(raw={"trureturing": {"pages_follow_branch": True}},
                               trureturing_repo="owner/trureturing", trureturing_branch="dev")
        target = "a" * 40
        live_manifest = dict(repo=site.trureturing_repo, branch="dev", commit=target)

        def prepare():
            return pages_schedule.prepare_snapshot(site, self.repo, "main", self.live,
                                                   refresh=True, get=self.api, read_live=lambda _: live_manifest)

        with (patch.object(pages_schedule, "refresh_due", return_value=True),
              patch.object(pages_schedule.lean, "ls_remote", return_value=target) as resolve,
              patch.object(pages_schedule.pin, "pin") as pin):
            self.assertEqual(prepare(), "")
            pin.assert_not_called()
            live_manifest["commit"] = "b" * 40
            pin.return_value = SimpleNamespace(written=True, markdown=lambda: "pin report")
            self.assertEqual(prepare(), target)
            resolve.assert_called_with("owner/trureturing", "refs/heads/dev")
            pin.assert_called_once_with(target)
            pin.return_value.written = False
            with self.assertRaisesRegex(ValueError, "cannot publish"):
                prepare()
