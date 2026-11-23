"""Unnumbered trees keep navigation, shared theorem counters and subsequent chapter numbers."""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from test_core import CoreRepo, make_lock
from tbook import config, html, model, newbook, pandoc, summary


TOC = """# Summary

- [One](one.md)
- [Coda $x$](coda.md)
  - [Detail](coda-detail.md)
    - [Deep](coda-deep.md)
- [Two](two.md)

[Appendix](appendix.md)
"""
META = """[book]
title = "Sample"
editions = ["zh", "en"]

[numbering.unnumbered]
"coda.md" = "Coda"

[html]
section-labels = true

[html.fold]
level = 0
"""


def fixture(repo):
    chapters = {"one.md": "One", "coda.md": "Coda $x$", "coda-detail.md": "Detail",
                "coda-deep.md": "Deep", "two.md": "Two", "appendix.md": "Appendix"}
    files = {file: f'# {title} {{#stable-{file[:-3]}}}\n\n::: {{.remark #{file[:-3]}}}\nText.\n:::\n'
             for file, title in chapters.items()}
    return repo.book(toml=META, summaries={lang: TOC for lang in ("zh", "en")},
                     files={lang: files for lang in ("zh", "en")})


class UnnumberedTrees(unittest.TestCase):
    def test_model_excludes_the_tree_and_shares_its_environment_counter(self):
        with CoreRepo() as repo:
            book = fixture(repo)
            editions = model.load_book_models(book)
            for ed in editions.values():
                self.assertEqual(ed.issues, [])
                self.assertEqual([ch.number_label for ch in ed.summary.chapters], ["1", "", "", "", "2", ""])
                self.assertEqual([env.number for env in ed.all_envs()],
                                 ["1.1", "Coda.1", "Coda.2", "Coda.3", "2.1", "A.1"])
                self.assertEqual([ch.depth for ch in ed.summary.chapters], [0, 0, 1, 2, 0, 0])
            newbook.new_chapter(book.slug, "coda-more", {"zh": "More", "en": "More"}, parent="coda")
            ed = model.load_edition(book.primary)
            added = next(ch for ch in ed.summary.chapters if ch.path == "coda-more.md")
            self.assertEqual((added.depth, added.number_label, added.unnumbered_prefix), (1, "", "Coda"))

    def test_bad_config_and_targets_fail_clearly(self):
        for entry in ('unnumbered = []', 'unnumbered = {"../coda.md" = "Coda"}',
                      'unnumbered = {"coda.md" = false}', 'unnumbered = {"coda.md" = "40"}',
                      'unnumbered = {"coda.md" = "Coda", "other.md" = "Coda"}'):
            with self.subTest(entry=entry), CoreRepo() as repo:
                with self.assertRaises(config.ConfigError):
                    repo.book(toml='[book]\ntitle = "Sample"\n[numbering]\n' + entry)
        for target, prefix in (("missing.md", "Coda"), ("coda-detail.md", "Coda"),
                               ("appendix.md", "Coda"), ("coda.md", "A")):
            with self.subTest(target=target, prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(summary.SummaryError):
                    summary.parse_summary(Path(tmp) / "SUMMARY.md", text=TOC, unnumbered={target: prefix})

    def test_pandoc_keeps_nested_titles_anchors_and_custom_environment_numbers(self):
        with CoreRepo() as repo:
            book = fixture(repo)
            ed = model.load_edition(book.primary)
            staged = pandoc.stage(config.load_site(), book, book.primary, ed, make_lock())
            text = staged.book_md.read_text()
            heads = {h.attrs.id: h for h in pandoc.find_headings(text) if h.attrs}
            for file in ("coda", "coda-detail", "coda-deep"):
                self.assertIn("unnumbered", heads[f"stable-{file}"].attrs.classes)
            self.assertEqual([heads[f"stable-{file}"].level for file in ("coda", "coda-detail", "coda-deep")],
                             [1, 2, 3])
            self.assertNotIn("unnumbered", heads["stable-two"].attrs.classes)
            self.assertIn('tr-kicker="DEMO"', pandoc.format_heading(1, "X", heads["stable-coda"].attrs))
            self.assertIn("Coda.3", text)

    @unittest.skipUnless(shutil.which("mdbook") and shutil.which("node"), "needs mdBook and Node")
    def test_real_mdbook_toc_and_search_follow_model_with_section_labels_enabled(self):
        with CoreRepo() as repo:
            book = fixture(repo)
            ed = model.load_edition(book.primary)
            out = repo.root / "html"
            html.build_edition(config.load_site(), book, book.primary, ed, make_lock(), out)
            toc = (out / "toc.html").read_text()
            for file in ("coda", "coda-detail", "coda-deep"):
                link = re.search(r'<a\b[^>]*href="' + file + r'\.html"[^>]*>(.*?)</a>', toc, re.S)
                self.assertIsNotNone(link)
                self.assertNotIn("<strong", link.group(1))
            for child in ("coda-detail", "coda-deep"):
                self.assertRegex(toc, r'<ol class="section"><li class="chapter-item "><span class="chapter-link-wrapper">'
                                      rf'<a href="{child}\.html"')
            self.assertRegex(toc, r'two\.html[^>]*>\s*<strong[^>]*>2\.</strong>')
            self.assertIn('class="katex"', toc)
            self.assertIn("Coda.3", (out / "coda-deep.html").read_text())
            self.assertTrue(list(out.glob("searchindex*.js")))


if __name__ == "__main__":
    unittest.main()
