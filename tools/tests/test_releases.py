"""Release download links depend on actual uploaded, published attachments."""

import json
import unittest
from unittest.mock import patch

from tbook import releases


class ReleaseAssetsTest(unittest.TestCase):
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
                             asset(preview_tag, "preview.pdf"), prerelease=True),
                     release(main_preview_tag, "2026-01-06", asset(main_preview_tag, "book.pdf"),
                             asset(main_preview_tag, "main-preview.pdf"), prerelease=True),
                     release(beta_tag, "2026-01-04", beta, prerelease=True)]]
        self.addCleanup(releases.pdf_assets.cache_clear)
        with patch.object(releases.subprocess, "check_output", return_value=json.dumps(response)) as run:
            self.assertEqual(releases.pdf_assets("owner/books"),
                             {"book.pdf": releases.PdfAsset(new["browser_download_url"], 42),
                              "beta.pdf": releases.PdfAsset(beta["browser_download_url"], 42)})
            self.assertIn("--paginate", run.call_args.args[0])
