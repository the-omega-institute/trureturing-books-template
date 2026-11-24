"""Pages queue selection and the rolling-hour boundary, independent of runner time."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from ci import pages_rate, pages_schedule, trusted_cache
from tbook import lean, releases


class PagesScheduleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.git("init", "-qb", "main")
        self.live = self.commit("site.toml", "# online")
        self.first = self.commit("site.toml", "# first push")
        self.head = self.commit("README.md", "Docs only in the last push")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def commit(self, path, content):
        (self.root / path).write_text(content)
        self.git("add", path)
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", path)
        return self.git("rev-parse", "HEAD")

    def due(self, sha, event="push", schedule="", manifest=None):
        with patch.object(pages_schedule, "live_commit", return_value=self.live):
            return pages_schedule.due(self.root, "owner/books", sha, event, schedule,
                                      get=lambda _: {"html_url": "https://books.example.org"},
                                      read_live=lambda _: manifest or {})

    def test_queued_tip_includes_changes_in_replaced_pushes(self):
        self.assertTrue(self.due(self.head))
        reverted = self.commit("site.toml", "# online")
        self.assertFalse(self.due(reverted))
        self.assertFalse(self.due(self.live))
        self.assertTrue(self.due(self.live, "workflow_dispatch"))
        self.live = self.head
        self.assertFalse(self.due(self.first, "workflow_dispatch"))
        self.live = None
        self.assertTrue(self.due(reverted))

    def test_scheduled_refresh_compares_live_pdf_and_branch(self):
        self.live = self.head
        spec = lean.BranchLock("owner/lean", "dev")
        manifest = {"trureturing": dict(repo=spec.repo, branch=spec.branch, commit="a" * 40),
                    "release_pdf_digest": releases.pdf_digest({})}
        with (patch.object(pages_schedule.config, "load_site", return_value=Mock(
                  pdf_release_only=True, epub_release_only=False, film_release_only=False)),
              patch.object(lean.Lock, "read_spec", return_value=spec),
              patch.object(pages_schedule.pin, "branch_head", return_value="b" * 40),
              patch.object(releases, "pdf_assets", return_value={})):
            self.assertTrue(self.due(self.head, "schedule", "17 5 * * *", manifest))
            manifest["trureturing"]["commit"] = "b" * 40
            self.assertFalse(self.due(self.head, "schedule", "17 5 * * *", manifest))
            manifest["release_pdf_digest"] = "previous"
            self.assertTrue(self.due(self.head, "schedule", "34 * * * *", manifest))

    def test_hourly_refresh_detects_a_new_epub_attachment(self):
        self.live = self.head
        opts = Mock(pdf_release_only=False, epub_release_only=True, film_release_only=False)
        manifest = {"release_epub_digest": releases.asset_digest({})}
        with (patch.object(pages_schedule.config, "load_site", return_value=opts),
              patch.object(releases, "epub_assets", return_value={}) as fetch):
            self.assertFalse(self.due(self.head, "schedule", "34 * * * *", manifest))
            fetch.return_value = {"book-1.0.0-en.epub": releases.ReleaseAsset("https://example.org/book.epub", 42)}
            self.assertTrue(self.due(self.head, "schedule", "34 * * * *", manifest))

    def test_legacy_registration_and_new_publication_cache_producers(self):
        first = dict(event="push", display_title=trusted_cache.PAGES_PUSH_TITLE + self.head)
        self.assertFalse(trusted_cache.pages_producer(first))
        self.assertTrue(trusted_cache.pages_producer(dict(first, run_attempt=2)))
        for event in ("schedule", "workflow_run"):
            self.assertFalse(trusted_cache.pages_producer(dict(event=event, display_title=trusted_cache.PAGES_SCHEDULER_TITLE)))
        for event in ("push", "schedule", "workflow_dispatch"):
            self.assertTrue(trusted_cache.pages_producer(dict(event=event, display_title="Pages · " + self.head)))


class PagesRateTests(unittest.TestCase):
    def test_ten_immediate_starts_then_wait_once_even_across_the_hour(self):
        now = datetime(2026, 11, 24, 9, 56, tzinfo=timezone.utc)
        starts, receipts, waits = [], [], []

        def get(endpoint):
            self.assertIn("environment=tbook-pages-build&task=pages-build&per_page=10", endpoint)
            return receipts[-10:][::-1]

        def post(endpoint, body):
            if endpoint.endswith("/statuses"):
                return {}
            self.assertFalse(body["production_environment"])
            starts.append(now)
            receipts.append(dict(payload=body["payload"], created_at=now.isoformat()))
            return {"id": len(receipts)}

        def sleep(seconds):
            nonlocal now
            waits.append(seconds)
            now += timedelta(seconds=seconds)

        for attempt in range(24):
            for _ in range(2):  # the same attempt may resume at build or deployment
                pages_rate.reserve("a/b", "abc", str(attempt), get=get, post=post, now=now, sleep=sleep)
            now += timedelta(minutes=1)
        self.assertEqual(len(starts), 24)
        self.assertEqual(len(waits), 2)
        self.assertEqual(starts[9] - starts[0], timedelta(minutes=9))
        for start in starts:
            self.assertLessEqual(sum(start - timedelta(hours=1) < t <= start for t in starts), 10)

    def test_expired_slot_at_exact_boundary_and_unavailable_history(self):
        now = datetime.now(timezone.utc)
        recent = [{"payload": {}, "created_at": (now - timedelta(hours=1)).isoformat()}] * 10
        post = Mock(return_value={"id": 1})
        sleep = Mock()
        pages_rate.reserve("a/b", "abc", "retry", get=lambda _: recent, post=post, now=now, sleep=sleep)
        sleep.assert_not_called()
        post.reset_mock()
        with self.assertRaises(OSError):
            pages_rate.reserve("a/b", "abc", "retry", get=Mock(side_effect=OSError), post=post)
        post.assert_not_called()
