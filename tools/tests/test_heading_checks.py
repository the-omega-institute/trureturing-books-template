"""Heading/navigation regressions in small, disposable bilingual books."""

import unittest

from test_core import CoreRepo, messages
from tbook import check, model


class HeadingChecks(unittest.TestCase):
    def inspect(self, text, title="Title"):
        with CoreRepo() as repo:
            book = repo.book(langs=("en",), summaries={"en": f"# Summary\n\n- [{title}](ch01.md)\n"},
                             files={"en": {"ch01.md": text}})
            edition = model.load_book_models(book)["en"]
            issues = []
            check.check_headings(edition, issues)
            return issues

    def test_navigation_title_drift_is_reported(self):
        issues = self.inspect("# Old title\n\n## Detail\n")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "warning")
        self.assertIn("differs from SUMMARY.md", issues[0].message)

    def test_explicit_ids_escapes_and_math_are_title_content(self):
        title = r"C\*-algebras and $\beta$"
        self.assertEqual(self.inspect(f"# {title} {{#stable}}\n", title), [])

    def test_setext_and_inline_comments_do_not_create_title_drift(self):
        self.assertEqual(self.inspect("Title <!-- editorial note -->\n===\n\nDetail\n---\n"), [])

    def test_code_comments_and_multiline_math_are_not_headings(self):
        text = "# Title\n\n```md\n# Example\n#### Example\n```\n\n<!--\n# Hidden\n-->\n\n$$\n# Formula\n$$\n\n## Detail\n"
        self.assertEqual(self.inspect(text), [])

    def test_missing_and_repeated_page_titles_are_reported(self):
        for text, count in (("Text only\n", 0), ("# Title\n\n# Another\n", 2)):
            with self.subTest(count=count):
                self.assertIn(f"{count} level-1 headings", messages(self.inspect(text))[0])

    def test_level_jumps_are_reported_but_returning_to_a_parent_is_valid(self):
        issues = self.inspect("# Title\n\n### Skipped\n\n## Parent\n\n### Child\n\n## Next\n")
        self.assertEqual(len(issues), 1)
        self.assertIn("level 1 to 3", issues[0].message)

    def test_numbering_and_language_are_editorial_choices(self):
        for title in ("第一章 标题", "Chapter 1: Title", "30.1 A child", "A plain title"):
            with self.subTest(title=title):
                self.assertEqual(self.inspect(f"# {title}\n\n## Detail\n", title), [])

    def test_translations_must_keep_the_same_heading_depth_and_order(self):
        with CoreRepo() as repo:
            book = repo.book(summaries={lang: "# Summary\n\n- [Title](ch01.md)\n" for lang in ("zh", "en")},
                             files={"zh": {"ch01.md": "# Title\n\n## 一\n\n### 二\n"},
                                    "en": {"ch01.md": "# Title\n\n## One\n\n## Two\n"}})
            editions = model.load_book_models(book)
            issues = []
            check.check_heading_parity(book, editions, issues)
            self.assertEqual(len(issues), 1)
            self.assertIn("heading levels differ from the zh edition", issues[0].message)


if __name__ == "__main__":
    unittest.main()
