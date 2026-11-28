"""Release download links depend on actual uploaded, published attachments."""

import os
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tbook import releases


class ReleaseAssetsTest(unittest.TestCase):
    def test_catalog_is_reused_across_runs_and_only_falls_back_for_rate_limits(self):
        pages = [[{"tag_name": "v1"}]]
        with (TemporaryDirectory() as directory,
              patch.dict(os.environ, {"TBOOK_RELEASE_CACHE": directory}),
              patch.object(releases.time, "time", return_value=1000),
              patch.object(releases, "read_json", return_value=pages) as fetch):
            self.assertEqual(releases._release_pages("owner/books"), pages)
            self.assertEqual(releases._release_pages("owner/books"), pages)
            self.assertEqual(fetch.call_count, 1)
            failure = subprocess.CalledProcessError(1, ["gh"], stderr="API rate limit exceeded")
            with patch.object(releases.time, "time", return_value=1500):
                fetch.side_effect = failure
                self.assertEqual(releases._release_pages("owner/books"), pages)
                with self.assertRaises(subprocess.CalledProcessError):
                    releases._release_pages("owner/other-books")
                fetch.side_effect = subprocess.CalledProcessError(1, ["gh"], stderr="Forbidden")
                with self.assertRaises(subprocess.CalledProcessError):
                    releases._release_pages("owner/books")
            with patch.object(releases.time, "time", return_value=100000):
                fetch.side_effect = failure
                with self.assertRaises(subprocess.CalledProcessError):
                    releases._release_pages("owner/books")

    def test_newest_uploaded_asset_wins_and_drafts_and_daily_previews_do_not_count(self):
        def asset(tag, name, state="uploaded"):
            return dict(state=state, name=name, size=42,
                        browser_download_url=f"https://github.com/owner/books/releases/download/{tag}/{name}")

        def release(tag, date, *assets, draft=False, prerelease=False):
            return dict(tag_name=tag, draft=draft, prerelease=prerelease, published_at=date, assets=assets)

        old = asset("v1", "book.pdf")
        new = asset("v2", "book.pdf")
        preview_tag = f"preview-dev-{'a' * 40}"
        main_preview_tag = f"preview-{'b' * 40}"
        beta_tag = "book-v3.0.0-beta.1"
        beta = asset(beta_tag, "beta.pdf")
        response = [[release("v1", "2026-01-01", old)],
                    [release("v3", "2026-01-03", asset("v3", "book.pdf"), asset("v3", "draft.pdf"), draft=True),
                     release("v2", "2026-01-02", new, asset("v2", "incomplete.pdf", "starter"),
                             asset("v2", "book.epub")),
                     release(preview_tag, "2026-01-05", asset(preview_tag, "book.pdf"),
                             asset(preview_tag, "preview.pdf"), asset(preview_tag, "film.mp4"), prerelease=True),
                     release(main_preview_tag, "2026-01-06", asset(main_preview_tag, "book.pdf"),
                             asset(main_preview_tag, "main-preview.pdf"),
                             asset(main_preview_tag, "book.epub"), prerelease=True),
                     release(beta_tag, "2026-01-04", beta, prerelease=True)]]
        releases._published.cache_clear()
        self.addCleanup(releases._published.cache_clear)
        self.addCleanup(releases.film_assets.cache_clear)
        self.addCleanup(releases.pdf_assets.cache_clear)
        self.addCleanup(releases.epub_assets.cache_clear)
        with patch.object(releases, "read_json", return_value=response) as run:
            self.assertEqual(releases.pdf_assets("owner/books"),
                             {"book.pdf": releases.PdfAsset(new["browser_download_url"], 42),
                              "beta.pdf": releases.PdfAsset(beta["browser_download_url"], 42)})
            self.assertEqual(releases.epub_assets("owner/books"),
                             {"book.epub": releases.ReleaseAsset(asset("v2", "book.epub")["browser_download_url"], 42)})
            self.assertIn("film.mp4", releases.film_assets("owner/books"))
            run.assert_called_once_with("repos/owner/books/releases?per_page=100", paginate=True, timeout=90)
