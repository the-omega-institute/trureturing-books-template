"""Book page limits use whole changed Git blobs, before any CI coverage reuse."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ci import plan
from tbook import config, page_lines


class PageLinesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tbook-page-lines-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.write("site.toml", '[site]\nlanguages=["zh", "en"]\n')
        for slug in ("one", "two"):
            self.book(slug, 3)
            for lang in ("zh", "en"):
                self.write(f"books/{slug}/{lang}/SUMMARY.md", "# Summary\n")
                self.write(f"books/{slug}/{lang}/chapter.md", "# Chapter\n\nText\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def book(self, slug, limit):
        value = f"max_page_lines={limit}\n" if limit is not None else ""
        self.write(f"books/{slug}/book.toml", '[book]\ntitle="Test"\neditions=["zh", "en"]\n' + value)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def failures(self):
        tree = plan.Tree(self.root, self.commit())
        return page_lines.check_tree(tree, plan.changed_paths(self.root, self.base, tree.sha))

    def ci_plan(self, payload=None, event="push", **kwargs):
        return plan.plan(self.root, event=event, payload=payload or {"before": self.base},
                         repo="owner/books", branch="main", ref="refs/heads/main",
                         get_baseline=kwargs.pop("get_baseline", lambda *a: {"sha": self.base}), **kwargs)

    def test_boundaries_count_blank_code_and_unterminated_final_line(self):
        for text, expected in (("", 0), ("a", 1), ("a\n", 1), ("a\n\n", 2),
                               ("a\r\n\r\nb", 3), ("```\na\n```", 3), ("a\u2028b", 1)):
            with self.subTest(text=text):
                self.assertEqual(page_lines.line_count(text), expected)
        name = "books/one/zh/chapter.md"
        self.write(name, "# Chapter\n\nLast")
        self.assertEqual(self.failures(), [])
        self.write(name, "# Chapter\n\nLast\nExtra")
        self.assertEqual(self.failures(), [(name, 4, 3)])

    def test_config_rejects_invalid_values_and_loads_omitted_or_positive(self):
        for value in ("0", "-1", "true", "false", '"1000"', "1.5"):
            with self.subTest(value=value):
                self.book("one", value)
                with self.assertRaisesRegex(config.ConfigError, "max_page_lines.*positive integer"):
                    config.load_book(self.root / "books/one")
                tree = plan.Tree(self.root, self.commit())
                with self.assertRaises(config.ConfigError):
                    page_lines.check_tree(tree, [])
                with self.assertRaises(config.ConfigError):
                    self.ci_plan()
        self.book("one", None)
        self.assertIsNone(config.load_book(self.root / "books/one").max_page_lines)
        self.book("one", 1000)
        self.assertEqual(config.load_book(self.root / "books/one").max_page_lines, 1000)

    def test_only_changed_pages_are_checked_and_one_book_config_rechecks_all_its_editions(self):
        first = "books/one/en/old.md"
        second = "books/two/zh/old.md"
        for name in (first, second):
            self.write(name, "line\n" * 4)
        self.base = self.commit()
        self.write("docs/NOTE.md", "documentation\n" * 100)
        self.assertEqual(self.failures(), [])
        self.book("one", 2)
        found = self.failures()
        self.assertIn((first, 4, 2), found)
        self.assertTrue(all(p.startswith("books/one/") for p, _, _ in found))
        self.assertNotIn(second, [p for p, _, _ in found])

    def test_new_and_renamed_nested_orphan_pages_are_checked_deleted_pages_are_ignored(self):
        old = "books/one/zh/old.md"
        new = "books/one/zh/nested/new.md"
        self.write(old, "line\n" * 4)
        self.base = self.commit()
        self.git("rm", old)
        self.write(new, "line\n" * 4)
        self.write("books/one/slides/deck/slides.md", "slide\n" * 9)
        self.write("README.md", "root\n" * 9)
        self.assertEqual(self.failures(), [(new, 4, 3)])
        self.git("rm", new)
        self.assertEqual(self.failures(), [])

    def test_site_config_rechecks_newly_visible_books_and_hidden_books_are_ignored(self):
        name = "books/two/zh/old.md"
        self.write(name, "line\n" * 4)
        self.write("site.toml", '[site]\nlanguages=["zh", "en"]\n[books]\nhide=["two"]\n')
        self.base = self.commit()
        self.write(name, "line\n" * 5)
        self.assertEqual(self.failures(), [])
        self.write("site.toml", '[site]\nlanguages=["zh", "en"]\n[books]\nhide=[]\n')
        self.assertEqual(self.failures(), [(name, 5, 3)])

    def test_unconfigured_books_preserve_compatibility_and_summary_is_a_page(self):
        self.book("one", None)
        self.write("books/one/zh/chapter.md", "line\n" * 100)
        self.write("books/two/en/SUMMARY.md", "line\n" * 4)
        self.assertEqual(self.failures(), [("books/two/en/SUMMARY.md", 4, 3)])

    def test_ci_blocks_before_looking_up_reusable_coverage(self):
        name = "books/one/zh/chapter.md"
        self.write(name, "# Chapter\n\nText\nExtra\n")
        self.commit()
        lookup = mock.Mock(side_effect=AssertionError("coverage lookup ran before page enforcement"))
        with self.assertRaisesRegex(ValueError, r"books/one/zh/chapter.md:4: 4 lines.*= 3"):
            self.ci_plan(get_baseline=lookup)
        lookup.assert_not_called()

    def test_push_checks_event_interval_and_initial_branch_push_checks_all(self):
        name = "books/one/zh/chapter.md"
        self.write(name, "line\n" * 4)
        later = self.commit()
        self.write("docs/NOTE.md", "documentation\n")
        self.commit()
        # An unchanged historical violation does not contaminate this push interval.
        self.ci_plan({"before": later})
        with self.assertRaisesRegex(ValueError, "Markdown page line limit exceeded"):
            self.ci_plan({"before": self.base})
        with self.assertRaisesRegex(ValueError, "Markdown page line limit exceeded"):
            self.ci_plan({"before": "0" * 40})

    def test_pr_checks_actual_merge_first_parent(self):
        original = self.base
        self.git("checkout", "-qb", "topic")
        self.write("books/one/zh/chapter.md", "line\n" * 4)
        topic = self.commit()
        self.git("checkout", "-q", "-")
        # This target-only violation must not be attributed to the PR.
        self.write("books/two/zh/target-only.md", "line\n" * 4)
        target = self.commit()
        self.git("merge", "--no-ff", "-qm", "tested merge", "topic")
        payload = {"pull_request": {"base": {"sha": original}, "head": {"sha": topic}}}
        with self.assertRaises(ValueError) as caught:
            self.ci_plan(payload, event="pull_request")
        self.assertIn("books/one/zh/chapter.md", str(caught.exception))
        self.assertNotIn("target-only", str(caught.exception))
        self.assertEqual(self.git("rev-parse", "HEAD^"), target)

    def test_local_full_book_audit_is_offline_even_with_branch_following_lock(self):
        self.write("books/one/en/unlisted.md", "line\n" * 4)
        self.write("trureturing.lock.json", json.dumps({"schema": "trureturing-books.lock.v1",
                   "repo": "https://invalid.example/no-network", "branch": "dev"}))
        book = config.load_book(self.root / "books/one")
        self.assertEqual(page_lines.check_book(book), [(self.root / "books/one/en/unlisted.md", 4, 3)])
        source = Path(__file__).resolve().parents[1]
        run = subprocess.run([sys.executable, "-m", "tbook", "check", "--page-lines-only", "--book", "one"],
                             cwd=self.root, capture_output=True, text=True, timeout=20,
                             env={**os.environ, "PYTHONPATH": str(source), "TBOOK_ROOT": str(self.root)})
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("unlisted.md:4", run.stdout)
        self.assertIn("4 lines exceed book.max_page_lines = 3", run.stdout)


if __name__ == "__main__":
    unittest.main()
