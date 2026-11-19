"""Release download links depend on actual uploaded, published attachments."""

import json
import unittest
from unittest.mock import patch

from tbook import releases


class ReleaseAssetsTest(unittest.TestCase):
    def test_newest_uploaded_asset_wins_and_drafts_do_not_count(self):
        def asset(tag, name, state="uploaded"):
            return dict(state=state, name=name, size=42,
                        browser_download_url=f"https://github.com/owner/books/releases/download/{tag}/{name}")

        def release(date, *assets, draft=False):
            return dict(draft=draft, published_at=date, assets=assets)

        old = asset("v1", "book.pdf")
        new = asset("v2", "book.pdf")
        response = [[release("2026-01-01", old)],
                    [release("2026-01-03", asset("v3", "book.pdf"), asset("v3", "draft.pdf"), draft=True),
                     release("2026-01-02", new, asset("v2", "incomplete.pdf", "starter"),
                             asset("v2", "book.epub"))]]
        self.addCleanup(releases.pdf_assets.cache_clear)
        with patch.object(releases.subprocess, "check_output", return_value=json.dumps(response)) as run:
            self.assertEqual(releases.pdf_assets("owner/books"),
                             {"book.pdf": releases.PdfAsset(new["browser_download_url"], 42)})
            self.assertIn("--paginate", run.call_args.args[0])
