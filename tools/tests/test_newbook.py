"""Tests of book scaffolding (``new-book``, ``new-chapter``), edition languages and their i18n tables.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_newbook.py'

Every test runs in a throwaway books repository (``Repo``): the ``tbook.paths`` attributes read at
call time point into it, the i18n tables and the book template are this repository's
``theme/i18n`` and ``templates/book`` (read-only). Nothing depends on ``books/example-monograph``.
Regression tests for review findings name the finding in their docstrings.
"""

from __future__ import annotations

import io
import os
import tempfile
import textwrap
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tbook import build, cli, config, newbook, paths

REAL_I18N = paths.THEME / "i18n"

SITE = """\
[site]
repo = "acme/books"
languages = ["zh", "en"]

[site.title]
zh = "书库"
en = "Books"
"""

EN_I18N = (REAL_I18N / "en.toml").read_text(encoding="utf-8")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` with its bytes: compare two snapshots to prove nothing was written."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Repo:
    """A throwaway books repository; ``tbook.paths`` points into it while active."""

    def __init__(self, site: str = SITE):
        self._tmp = tempfile.TemporaryDirectory(prefix="tbook-newbook-")
        self.root = Path(self._tmp.name)
        write(self.root / "site.toml", site)

    def __enter__(self) -> "Repo":
        self.stack = ExitStack()
        r = self.root
        for name, value in dict(ROOT=r, BOOKS=r / "books", BUILD=r / "build", SITE_OUT=r / "_site", CACHE=r / ".cache",
                                SITE_TOML=r / "site.toml", TEMPLATE_TOML=r / "template.toml",
                                LOCK_FILE=r / "trureturing.lock.json", I18N_LOCAL=r / "i18n",
                                I18N_THEME=REAL_I18N).items():
            self.stack.enter_context(mock.patch.object(paths, name, value))
        self.stack.enter_context(mock.patch.dict(os.environ))
        for key in ("TBOOK_REPO", "TBOOK_BASE_URL", "GITHUB_REPOSITORY", "TBOOK_ROOT"):
            os.environ.pop(key, None)
        config.load_site.cache_clear()
        config.i18n.cache_clear()
        self.stack.callback(config.i18n.cache_clear)
        self.stack.callback(config.load_site.cache_clear)
        return self

    def __exit__(self, *exc) -> None:
        self.stack.close()
        self._tmp.cleanup()

    def book(self, slug: str = "demo", langs: tuple[str, ...] = ("zh", "en"), dirs: tuple[str, ...] | None = None,
             summaries: dict[str, str] | None = None) -> config.Book:
        """A book whose editions are ``langs``; only the directories in ``dirs`` (default: all) exist."""
        bdir = self.root / "books" / slug
        titles = "\n".join(f'{lang} = "T-{lang}"' for lang in langs)
        write(bdir / "book.toml", f'[book]\neditions = [{", ".join(repr(x) for x in langs)}]\n\n[book.title]\n{titles}\n'
              .replace("'", '"'))
        for lang in langs if dirs is None else dirs:
            write(bdir / lang / "SUMMARY.md", (summaries or {}).get(lang, "# Summary\n\n- [One](ch01.md)\n"))
            write(bdir / lang / "ch01.md", "# One\n")
        return config.load_book(slug)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- new-chapter


class NewChapterTests(unittest.TestCase):
    def test_creates_the_chapter_in_every_edition(self):
        with Repo() as repo:
            repo.book(langs=("zh", "en", "ja"))
            created = newbook.new_chapter("demo", "ch02-more", {"zh": "第二章", "en": "Chapter 2", "ja": "第二章"})
            self.assertEqual([p.relative_to(repo.root / "books" / "demo").as_posix() for p in created],
                             ["zh/ch02-more.md", "en/ch02-more.md", "ja/ch02-more.md"])
            self.assertTrue((repo.root / "books/demo/en/SUMMARY.md").read_text(encoding="utf-8")
                            .endswith("- [Chapter 2](ch02-more.md)\n"))

    def test_missing_title_writes_nothing_and_the_retry_works(self):
        """Finding 30: a missing title for a later edition used to leave the earlier editions edited,
        and the retry was refused ("… already exists")."""
        with Repo() as repo:
            repo.book(langs=("zh", "en", "ja"))
            before = snapshot(repo.root / "books")
            with self.assertRaisesRegex(config.ConfigError, "missing a title for the 'ja' edition"):
                newbook.new_chapter("demo", "ch05-extra", {"zh": "第五章", "en": "Chapter 5"})
            self.assertEqual(snapshot(repo.root / "books"), before, "nothing is written when validation fails")
            created = newbook.new_chapter("demo", "ch05-extra", {"zh": "第五章", "en": "Chapter 5", "ja": "第五章"})
            self.assertEqual(len(created), 3)

    def test_missing_edition_directory_is_a_config_error(self):
        """Finding 30: an edition listed in book.toml without its directory crashed with
        FileNotFoundError after the other editions had been edited."""
        with Repo() as repo:
            repo.book(langs=("en", "zh", "ja"), dirs=("en", "zh"))
            before = snapshot(repo.root / "books")
            code, _out, err = repo.run_cli("new-chapter", "demo", "ch03-more",
                                           "--title", "en=Three", "--title", "zh=三", "--title", "ja=三")
            self.assertEqual(code, 2)
            self.assertIn("books/demo/ja/SUMMARY.md not found", err)
            self.assertIn("copying books/demo/en/ to books/demo/ja/", err)
            self.assertNotIn("Traceback", err)
            self.assertEqual(snapshot(repo.root / "books"), before)

    def test_later_edition_problems_write_nothing(self):
        """Finding 30: every edition is validated before the first write."""
        cases = {
            "existing file": (None, "books/demo/en/ch02-x.md already exists"),
            "already listed": ("# Summary\n\n- [One](ch01.md)\n- [Two](ch02-x.md)\n",
                               "books/demo/en/SUMMARY.md already lists ch02-x.md"),
            "bad summary": ("# Summary\n\nsome stray text\n", r"books/demo/en/SUMMARY.md:3: unrecognised SUMMARY line"),
        }
        for label, (en_summary, message) in cases.items():
            with self.subTest(label), Repo() as repo:
                repo.book(summaries={"en": en_summary} if en_summary else None)
                if en_summary is None:
                    write(repo.root / "books/demo/en/ch02-x.md", "# Two\n")
                before = snapshot(repo.root / "books")
                with self.assertRaisesRegex(config.ConfigError, message):
                    newbook.new_chapter("demo", "ch02-x", {"zh": "二", "en": "Two"})
                self.assertEqual(snapshot(repo.root / "books"), before)


# --------------------------------------------------------------------------- new-book


class NewBookTests(unittest.TestCase):
    def test_default_date_uses_utc(self):
        with Repo(), mock.patch.object(newbook.datetime, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
            newbook.new_book("my-book", {"zh": "书", "en": "Book"})
            clock.now.assert_called_once_with(timezone.utc)
            self.assertEqual(config.load_book("my-book").date, "2026-12-31")

    def test_new_book_loads(self):
        with Repo() as repo:
            path = newbook.new_book("my-book", {"zh": "书", "en": "Book", "ja": "本"}, langs=["zh", " en", "ja "])
            book = config.load_book("my-book")
            self.assertEqual(path, repo.root / "books" / "my-book")
            self.assertEqual(book.languages, ["zh", "en", "ja"], "codes are trimmed: --langs 'zh, en' works")
            self.assertEqual(config.pick(book.title, "ja"), "本")
            for lang in book.languages:
                self.assertTrue((path / lang / "SUMMARY.md").is_file())

    def test_duplicate_and_invalid_languages_are_rejected_before_writing(self):
        """Finding 46: --langs zh,zh crashed with FileExistsError and left books/<slug> half made;
        --langs en,en_US created a book that broke ./tbook check for the whole repository."""
        cases = {
            "duplicate": (["zh", "zh"], {"zh": "重"}, "--langs lists 'zh' twice"),
            "invalid": (["en", "en_US"], {"en": "X", "en_US": "Y"}, "invalid edition language 'en_US'"),
            "empty": (["zh", ""], {"zh": "X"}, "invalid edition language ''"),
        }
        for label, (langs, titles, message) in cases.items():
            with self.subTest(label), Repo() as repo:
                with self.assertRaisesRegex(config.ConfigError, message):
                    newbook.new_book("bad-book", titles, langs=langs)
                self.assertFalse((repo.root / "books" / "bad-book").exists(), "nothing is created")
                self.assertEqual(config.book_slugs(), [])

    def test_cli_reports_duplicates_without_a_traceback(self):
        """Finding 46: the CLI exits 2 with a message, and a rerun is not blocked by leftovers."""
        with Repo() as repo:
            code, _out, err = repo.run_cli("new-book", "dup-book", "--title", "zh=重", "--langs", "zh,zh")
            self.assertEqual(code, 2)
            self.assertIn("tbook: --langs lists 'zh' twice", err)
            code, out, _err = repo.run_cli("new-book", "dup-book", "--title", "zh=重", "--langs", "zh")
            self.assertEqual(code, 0)
            self.assertIn("created books/dup-book", out)

    def test_a_failed_write_leaves_no_half_made_book(self):
        """Finding 46: whatever fails while writing, books/<slug> is removed again."""
        with Repo() as repo:
            real = newbook.shutil.copytree
            calls = []

            def flaky(src, dst, *args, **kwargs):
                calls.append(dst)
                if len(calls) == 2:
                    raise OSError("disk full")
                return real(src, dst, *args, **kwargs)

            with mock.patch.object(newbook.shutil, "copytree", flaky), self.assertRaises(OSError):
                newbook.new_book("my-book", {"zh": "书", "en": "Book"})
            self.assertFalse((repo.root / "books" / "my-book").exists())

    def test_load_book_and_site_reject_duplicate_languages(self):
        """Finding 46: the readers reject a language listed twice too."""
        with Repo() as repo:
            write(repo.root / "books/dup/book.toml", '[book]\ntitle = "x"\neditions = ["zh", "en", "zh"]\n')
            with self.assertRaisesRegex(config.ConfigError, r"books/dup/book.toml: book.editions lists 'zh' twice"):
                config.load_book("dup")
            write(repo.root / "site.toml", '[site]\nlanguages = ["en", "zh", "en"]\n')
            config.load_site.cache_clear()
            with self.assertRaisesRegex(config.ConfigError, "site.toml: languages lists 'en' twice"):
                config.load_site()


# --------------------------------------------------------------------------- i18n of a new language


class I18nTests(unittest.TestCase):
    def test_built_in_languages_have_no_problems(self):
        with Repo():
            self.assertEqual(config.i18n_problems(["zh", "en"]), [])
            self.assertEqual(config.bcp47("zh"), "zh-CN")
            self.assertEqual(config.s("en", "meta.short"), "EN")

    def test_table_without_meta_does_not_claim_to_be_english(self):
        """Finding 45: i18n/ja.toml without [meta] made the ja edition lang="en" and "EN"."""
        with Repo() as repo:
            local = write(repo.root / "i18n" / "ja.toml", '[env]\ntheorem = "定理"\n')
            self.assertEqual(config.s("ja", "env.theorem"), "定理")
            self.assertEqual(config.s("ja", "env.lemma"), "Lemma", "untranslated strings still fall back to English")
            self.assertEqual((config.s("ja", "meta.name"), config.bcp47("ja"), config.s("ja", "meta.short")),
                             ("ja", "ja", "JA"), "labelled by its code, never as English")
            self.assertEqual(config.i18n("fr")["meta"], {"name": "fr", "bcp47": "fr", "short": "FR"},
                             "a language with no table at all is not English either")
            problems = config.i18n_problems(["zh", "en", "ja"])
            self.assertEqual(len(problems), 1, problems)
            path, message = problems[0]
            self.assertEqual(path, local)
            self.assertIn("[meta] must set name, bcp47, short for the 'ja' edition", message)
            self.assertIn('bcp47 = "ja", short = "JA"', message)

    def test_partial_meta_is_merged_and_reported(self):
        with Repo() as repo:
            write(repo.root / "i18n" / "ja.toml", '[meta]\nname = "日本語"\nbcp47 = "ja"\n')
            self.assertEqual((config.s("ja", "meta.name"), config.bcp47("ja"), config.s("ja", "meta.short")),
                             ("日本語", "ja", "JA"))
            [(path, message)] = config.i18n_problems(["zh", "en", "ja"])
            self.assertIn("[meta] must set short for the 'ja' edition", message)

    def test_copied_english_meta_is_reported_on_the_copy(self):
        """Finding 45: a table copied from en.toml without changing [meta] duplicates English's tag and label."""
        with Repo() as repo:
            local = write(repo.root / "i18n" / "ja.toml", EN_I18N)
            problems = config.i18n_problems(["zh", "en", "ja"])
            self.assertEqual([p for p, _ in problems], [local, local], "blamed on ja, not on the built-in en")
            self.assertIn("meta.bcp47 = 'en' for 'ja' is also the bcp47 of 'en'", problems[0][1])
            self.assertIn("meta.short = 'EN' for 'ja' is also the short of 'en'", problems[1][1])
            self.assertEqual(config.i18n_problems(["zh", "ja"]), [], "only languages in use are compared")

    def test_complete_meta_has_no_problems(self):
        with Repo() as repo:
            write(repo.root / "i18n" / "ja.toml", '[meta]\nname = "日本語"\nbcp47 = "ja"\nshort = "JA"\n')
            self.assertEqual(config.i18n_problems(["zh", "en", "ja", "fr"]), [],
                             "fr has no table at all: has_i18n reports that, not i18n_problems")

    def test_malformed_table_is_a_config_error(self):
        with Repo() as repo:
            write(repo.root / "i18n" / "ja.toml", "[meta\n")
            with self.assertRaisesRegex(config.ConfigError, r"i18n/ja.toml: "):
                config.i18n("ja")


# --------------------------------------------------------------------------- build --lang


class BuildLangTests(unittest.TestCase):
    def test_unknown_lang_fails_before_building(self):
        """Finding 47: build --lang <code> silently did nothing (exit 0) when no selected book had it."""
        with Repo() as repo:
            books = [repo.book("alpha"), repo.book("beta", langs=("zh", "en", "ja"))]
            with mock.patch.object(build.lean.Lock, "load", side_effect=AssertionError("nothing may run")):
                with self.assertRaisesRegex(config.ConfigError,
                                            r"no 'fr' edition in the selected books: alpha \(zh, en\); beta \(zh, en, ja\)"):
                    build.build(["html", "pdf"], books, ["fr"])
                with self.assertRaisesRegex(config.ConfigError, r"no 'ja' edition in the selected books: alpha \(zh, en\)$"):
                    build.build(["html"], books[:1], ["ja"])
                with self.assertRaisesRegex(config.ConfigError, "no 'fr' or 'de' edition"):
                    build.build(["html"], books, ["zh", "fr", "de"])
            self.assertEqual(build.build([], books, ["ja"]).failures, [], "a language of one selected book is fine")

    def test_cli_exit_code(self):
        """Finding 47: the CLI exits 2 with a message instead of 0 with no output."""
        with Repo() as repo:
            repo.book("alpha")
            code, out, err = repo.run_cli("build", "html", "pdf", "--lang", "fr")
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertIn("tbook: no 'fr' edition in the selected books: alpha (zh, en)", err)


if __name__ == "__main__":
    unittest.main()
