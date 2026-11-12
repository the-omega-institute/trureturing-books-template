"""Unit tests of the tbook core: config, summary, mdscan, lean, model, render, ledger, check, pin, theme.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_core.py'

Every test runs against a throwaway books repository (``CoreRepo``): the ``tbook.paths``
attributes the core reads at call time are patched to point into it, and the cached
``config.load_site`` / ``config.i18n`` are cleared on entry and exit. trureturing is replaced
by ``FakeLedger`` (frozen state dicts in memory), so nothing touches the network. The i18n
tables and design tokens are read from this repository's ``theme/`` (read-only).

Regression tests for the core bugs found during integration are marked in their docstrings.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import textwrap
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest import mock

from tbook import check, config, lean, ledger, mdscan, model, paths, pin, render, summary, theme

REAL_I18N = paths.THEME / "i18n"
REAL_LOCK = paths.LOCK_FILE
REAL_TOKENS = paths.TOKENS
REAL_GENERATED = paths.GENERATED

GID_3V = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"
GID_INT = "D5/S1/Deficit/DeficitInteger.deficit_integer"
GID_DEF = "D5/S1/Deficit/DeficitInteger.deficit"
MOD_3V = "D5/S1/Deficit/DeficitThreeValued"
MOD_INT = "D5/S1/Deficit/DeficitInteger"
COMMIT = "a" * 40
OLD_COMMIT = "b" * 40
TRU = "the-omega-institute/trureturing"


# --------------------------------------------------------------------------- helpers


def trureturing_checkout() -> tuple[Path, str] | None:
    """(checkout, pinned commit) when a local trureturing checkout has this repository's pinned commit."""
    try:
        commit = json.loads(REAL_LOCK.read_text(encoding="utf-8"))["commit"]
    except (OSError, ValueError, KeyError):
        return None
    for cand in (os.environ.get("TRURETURING_DIR"), paths.ROOT.parent / "trureturing"):
        if cand and (Path(cand) / ".git").exists():
            r = subprocess.run(["git", "-C", str(cand), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
            if r.returncode == 0:
                return Path(cand), commit
    return None


TRURETURING = trureturing_checkout()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def name_key(*comps: str | int, private_of: tuple[str, ...] | None = None) -> str:
    """Encode a Lean name like trureturing's ``declaration_name_key`` (lengths in UTF-8 bytes)."""
    key = "n0"
    if private_of is not None:  # _private.<module>.0.<name>
        key = "ns(n0,8:_private)"
        for c in private_of:
            key = f"ns({key},{len(c.encode())}:{c})"
        key = f"nn({key},0)"
    for c in comps:
        key = f"nn({key},{c})" if isinstance(c, int) else f"ns({key},{len(c.encode())}:{c})"
    return key


def states() -> dict[str, dict]:
    return {
        MOD_3V: {"statement_id": "sha256:3v", "declarations": [
            {"declaration_name_key": name_key("D5", "S1", "Deficit", "deficit_three_valued"), "kind": "theorem"},
            {"declaration_name_key": name_key("D5", "S1", "Deficit", "helper",
                                              private_of=("D5", "S1", "Deficit", "DeficitThreeValued")),
             "kind": "theorem"},
        ]},
        MOD_INT: {"statement_id": "sha256:int", "declarations": [
            {"declaration_name_key": name_key("D5", "S1", "Deficit", "deficit"), "kind": "def"},
            {"declaration_name_key": name_key("D5", "S1", "Deficit", "deficit_integer"), "kind": "theorem"},
        ]},
    }


class FakeLedger:
    """Stands in for ``lean.Ledger``: frozen states and Lean sources from dicts."""

    def __init__(self, state_map: dict[str, dict | None] | None = None, sources: dict[str, str] | None = None,
                 unreachable: bool = False, on_branch: bool | None = True, shas: dict[str, str] | None = None):
        self.states = states() if state_map is None else state_map
        self.sources = sources or {}
        self.unreachable = unreachable
        self.calls: list[tuple[str, str]] = []
        self.ancestry = lean.Ancestry(on_branch, {True: "fake: on branch", False: "fake: not on branch",
                                                  None: "fake: cannot tell"}[on_branch])
        self.ancestry_calls: list[tuple[str, str]] = []
        self.recorded: list[tuple[str, str]] = []
        self.shas = shas or {}

    def branch_contains(self, commit: str, branch: str) -> lean.Ancestry:
        self.ancestry_calls.append((commit, branch))
        return self.ancestry

    def record_on_branch(self, commit: str, branch: str, detail: str) -> None:
        self.recorded.append((commit, branch))

    def expand_sha(self, prefix: str) -> str | None:
        return self.shas.get(prefix)

    def state(self, commit: str, module: str) -> dict | None:
        self.calls.append((commit, module))
        if self.unreachable:
            raise lean.LeanError(f"cannot read state of {module} at {commit[:12]}: no trureturing checkout, "
                                 "no cache entry and network disabled")
        st = self.states.get(module)
        return json.loads(json.dumps(st)) if st is not None else None

    def read(self, commit: str, path: str) -> bytes | None:
        text = self.sources.get(path)
        return text.encode() if text is not None else b""


def lock_decls(**overrides) -> dict[str, dict]:
    decls = {
        GID_3V: {"module": MOD_3V, "name": "D5.S1.Deficit.deficit_three_valued", "kind": "theorem",
                 "statement_id": "sha256:3v", "line": 12, "signature": "theorem deficit_three_valued"},
        GID_INT: {"module": MOD_INT, "name": "D5.S1.Deficit.deficit_integer", "kind": "theorem",
                  "statement_id": "sha256:int", "line": 0, "signature": ""},
        GID_DEF: {"module": MOD_INT, "name": "D5.S1.Deficit.deficit", "kind": "def",
                  "statement_id": "sha256:int", "line": 7, "signature": "def deficit"},
    }
    for gid, value in overrides.items():
        if value is None:
            decls.pop(gid, None)
        else:
            decls[gid] = value
    return decls


def make_lock(decls: dict | None = None, repo: str = TRU) -> lean.Lock:
    return lean.Lock(repo=repo, branch="dev", commit=COMMIT, pinned_at="2026-01-01T00:00:00Z",
                     declarations=lock_decls() if decls is None else decls)


SITE = """\
[site]
repo = "acme/books"
languages = ["zh", "en"]

[site.title]
zh = "书库"
en = "Library"

[trureturing]
repo = "the-omega-institute/trureturing"
branch = "dev"

[books]
order = ["second", "demo"]
"""

ZH_SUMMARY = """\
# Summary

[前言](README.md)

- [第一章](ch01.md)
- [第二章](ch02.md)
  - [第二章第一节](part/ch02-1.md)
- [草稿]()

[附录甲](appendix-a.md)
[附录乙](appendix-b.md)
"""

EN_SUMMARY = ZH_SUMMARY.replace("前言", "Preface").replace("第一章", "Chapter 1").replace(
    "第二章第一节", "Section 2.1").replace("第二章", "Chapter 2").replace("草稿", "Draft").replace(
    "附录甲", "Appendix A").replace("附录乙", "Appendix B")


def chapters(lang: str) -> dict[str, str]:
    zh = lang == "zh"
    return {
        "README.md": f"""\
            # {'前言' if zh else 'Preface'}

            ::: {{.remark #rem-intro}}
            {'前言里的注。' if zh else 'A remark in the preface.'}
            :::
            """,
        "ch01.md": f"""\
            # {'第一章' if zh else 'Chapter 1'}

            ::: {{.theorem #thm-a title="{'亏量三值' if zh else 'Three values'}" lean="{GID_3V}"}}
            {'对所有' if zh else 'For all'} $v$.
            :::

            ::: proof
            {'见' if zh else 'See'} [`deficit_three_valued`](lean:{GID_3V}).
            :::

            ::: {{.definition #def-d lean="{GID_DEF}"}}
            {'定义。' if zh else 'Definition.'}
            :::

            ::: {{.conjecture #conj-x}}
            {'猜想。' if zh else 'Conjecture.'}
            :::

            {'见' if zh else 'See'} [@thm-a] {'与' if zh else 'and'} `[@not-a-ref]`.

            ```text
            ::: {{.theorem #in-code}}
            [@in-code] [x](lean:not/a.gid)
            ```

            ![fig](../assets/fig.svg "Figure")
            [ext](https://example.org/x) [here](#thm-a) [next](ch02.md)
            """,
        "ch02.md": f"""\
            # {'第二章' if zh else 'Chapter 2'}

            ::: {{.lemma #lem-b lean="{GID_INT}"}}
            {'引理。' if zh else 'Lemma.'}
            :::

            {'由' if zh else 'By'} [@thm-a] {'与' if zh else 'and'} [@lem-b].
            """,
        "part/ch02-1.md": f"""\
            # {'第一节' if zh else 'Section'}

            ::: {{.corollary #cor-c lean="{GID_INT}"}}
            [@thm-a].
            :::

            ![fig](../../assets/fig.svg)
            """,
        "appendix-a.md": """\
            # A

            ::: {.example #ex-a}
            x
            :::
            """,
        "appendix-b.md": """\
            # B

            ::: {.remark #rem-b}
            y
            :::

            ::: {.problem #prob-p title="Open"}
            z
            :::
            """,
    }


class CoreRepo:
    """A throwaway books repository; ``tbook.paths`` points into it while active."""

    def __init__(self, site: str = SITE):
        self._tmp = tempfile.TemporaryDirectory(prefix="tbook-core-")
        self.root = Path(self._tmp.name)
        write(self.root / "site.toml", site)

    def __enter__(self) -> "CoreRepo":
        self.stack = ExitStack()
        r = self.root
        for name, value in dict(ROOT=r, BOOKS=r / "books", BUILD=r / "build", SITE_OUT=r / "_site", CACHE=r / ".cache",
                                SITE_TOML=r / "site.toml", TEMPLATE_TOML=r / "template.toml",
                                LOCK_FILE=r / "trureturing.lock.json", I18N_LOCAL=r / "i18n",
                                I18N_THEME=REAL_I18N, TOKENS=REAL_TOKENS, GENERATED=REAL_GENERATED).items():
            self.stack.enter_context(mock.patch.object(paths, name, value))
        self.stack.enter_context(mock.patch.dict(os.environ))
        # GITHUB_EVENT_NAME: in a pull request's CI run, tbook would not read the test's .cache (lean.cache_trusted)
        for key in ("TBOOK_REPO", "TBOOK_BASE_URL", "GITHUB_REPOSITORY", "TRURETURING_DIR", "TBOOK_ROOT",
                    "GITHUB_EVENT_NAME"):
            os.environ.pop(key, None)
        config.load_site.cache_clear()
        config.i18n.cache_clear()
        self.stack.callback(config.i18n.cache_clear)
        self.stack.callback(config.load_site.cache_clear)
        return self

    def __exit__(self, *exc) -> None:
        self.stack.close()
        self._tmp.cleanup()

    def book(self, slug: str = "demo", langs: tuple[str, ...] = ("zh", "en"), toml: str = "",
             summaries: dict[str, str] | None = None, files: dict[str, dict[str, str]] | None = None) -> config.Book:
        bdir = self.root / "books" / slug
        write(bdir / "book.toml", toml or f"""\
            [book]
            version = "1.2.3"
            editions = {json.dumps(list(langs))}
            date = "2026-01-02"

            [book.title]
            zh = "示例"
            en = "Sample"
            """)
        for lang in langs:
            write(bdir / lang / "SUMMARY.md", (summaries or {}).get(lang, ZH_SUMMARY if lang == "zh" else EN_SUMMARY))
            for rel, text in ((files or {}).get(lang) or chapters(lang)).items():
                write(bdir / lang / rel, text)
        write(bdir / "assets" / "fig.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
        return config.load_book(slug)


def media_stub(name: str, real=__import__("importlib").import_module):
    """importlib.import_module replacement: neutral tbook.viz/film/slides (other components)."""
    if name in ("tbook.viz", "tbook.film", "tbook.slides"):
        return types.SimpleNamespace(check=lambda book: [], check_ref=lambda book, src: None,
                                     render_embed=lambda env, ctx, inner, doc: f"<MEDIA {env.kind} {env.attrs.get('src')}>")
    return real(name)


def messages(issues, severity: str | None = None) -> list[str]:
    return [i.message for i in issues if severity is None or i.severity == severity]


# --------------------------------------------------------------------------- config


class ConfigTests(unittest.TestCase):
    def test_localized_and_pick(self):
        self.assertEqual(config.localized(None, "x"), {})
        self.assertEqual(config.localized("Hi", "x"), {"*": "Hi"})
        self.assertEqual(config.localized({"zh": "你好", "en": "Hi"}, "x"), {"zh": "你好", "en": "Hi"})
        for bad in (["a"], {"zh": 1}, 3):
            with self.assertRaises(config.ConfigError):
                config.localized(bad, "book.title")
        text = {"en": "Hi", "zh": "你好"}
        self.assertEqual(config.pick(text, "zh"), "你好")
        self.assertEqual(config.pick({"*": "Any", "en": "Hi"}, "fr"), "Any")
        self.assertEqual(config.pick(text, "fr", ["zh", "en"]), "你好")
        self.assertEqual(config.pick(text, "fr"), "Hi", "first value as the last resort")
        self.assertEqual(config.pick({}, "zh"), "")

    def test_i18n_lookup_override_and_fallback(self):
        with CoreRepo() as repo:
            self.assertEqual(config.s("zh", "env.theorem"), "定理")
            self.assertEqual(config.s("en", "env.theorem"), "Theorem")
            self.assertEqual(config.s("zh", "no.such.key"), "")
            write(repo.root / "i18n" / "zh.toml", '[env]\ntheorem = "定理（改）"\n[extra]\nonly_zh = "仅中文"\n')
            write(repo.root / "i18n" / "en.toml", '[extra]\nonly_en = "English only"\n')
            config.i18n.cache_clear()
            self.assertEqual(config.s("zh", "env.theorem"), "定理（改）", "i18n/<lang>.toml overrides")
            self.assertEqual(config.s("zh", "env.lemma"), "引理", "deep merge keeps the other keys")
            self.assertEqual(config.s("zh", "extra.only_en"), "English only", "missing keys fall back to English")
            self.assertEqual(config.s("en", "extra.only_zh"), "")
            self.assertEqual(config.i18n("fr")["env"]["theorem"], "Theorem", "unknown languages use English")
            self.assertFalse(config.has_i18n("fr"))
            write(repo.root / "i18n" / "fr.toml", '[env]\ntheorem = "Théorème"\n')
            config.i18n.cache_clear()
            self.assertTrue(config.has_i18n("fr"))
            self.assertEqual(config.s("fr", "env.theorem"), "Théorème")
            self.assertEqual(config.bcp47("zh"), "zh-CN")

    def test_site(self):
        with CoreRepo():
            site = config.load_site()
            self.assertEqual(site.languages, ["zh", "en"])
            self.assertEqual(site.default_language, "zh")
            self.assertEqual(site.repo, "acme/books")
            self.assertEqual(site.base_url, "https://acme.github.io/books/")
            self.assertEqual(site.book_url("demo", "zh", ""), "https://acme.github.io/books/demo/zh")
            self.assertEqual(site.text(site.title, "en"), "Library")
            self.assertEqual(site.trureturing_repo, TRU)
        with CoreRepo(SITE.replace('repo = "acme/books"\n', "")):
            os.environ["TBOOK_REPO"] = "Org/org.github.io"
            self.assertEqual(config.load_site().base_url, "https://org.github.io/")
        with CoreRepo():
            os.environ["TBOOK_BASE_URL"] = "https://books.example.org"
            self.assertEqual(config.load_site().base_url, "https://books.example.org/")
        with CoreRepo(SITE.replace('languages = ["zh", "en"]', 'languages = ["zh", "EN!"]')):
            with self.assertRaisesRegex(config.ConfigError, "invalid language"):
                config.load_site()
        with CoreRepo() as repo:
            (repo.root / "site.toml").unlink()
            with self.assertRaisesRegex(config.ConfigError, "site.toml not found"):
                config.load_site()
        self.assertEqual(config.pages_base_url(""), "")

    def test_git_remote_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "git@github.com:acme/books.git"], check=True)
            self.assertEqual(config._git_remote_repo(root), "acme/books")
            subprocess.run(["git", "-C", str(root), "remote", "set-url", "origin", "http://127.0.0.1:9/git/acme/b"],
                           check=True)
            self.assertEqual(config._git_remote_repo(root), "acme/b")
            self.assertEqual(config._git_remote_repo(root / "nope"), "")

    # BUG (config._git_remote_repo): repository names containing a dot (user/organisation Pages
    # repositories such as acme/acme.github.io) are not recognised, so local builds get no base URL.
    # Patch: use r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$" (and the same for the /git/ form).
    def test_git_remote_repo_with_dot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                            "https://github.com/acme/acme.github.io.git"], check=True)
            self.assertEqual(config._git_remote_repo(root), "acme/acme.github.io")

    def test_academic_pdf_is_opt_in(self):
        with CoreRepo() as repo:
            repo.book()
            p = repo.root / "books" / "demo" / "book.toml"
            original = p.read_text()
            for value, expected in (("true", ["screen", "print"]),
                                    ('["academic"]', ["academic"])):
                p.write_text(original + "\n[outputs]\npdf = " + value + "\n")
                book = config.load_book("demo")
                self.assertEqual(book.outputs_pdf, expected)
            self.assertEqual(book.artifact("zh", "pdf", "academic"), "demo-1.2.3-zh-academic.pdf")

    def test_load_book(self):
        with CoreRepo() as repo:
            book = repo.book()
            self.assertEqual(book.slug, "demo")
            self.assertEqual(book.version, "1.2.3")
            self.assertEqual(book.languages, ["zh", "en"])
            self.assertEqual([e.lang for e in book.editions], ["zh", "en"])
            self.assertTrue(book.primary.primary)
            self.assertFalse(book.edition("en").primary)
            self.assertEqual(book.edition("en").title, "Sample")
            self.assertEqual(book.edition("zh").key, "demo/zh")
            self.assertEqual(book.edition("zh").summary, repo.root / "books" / "demo" / "zh" / "SUMMARY.md")
            self.assertEqual(book.code, "DEMO")
            self.assertEqual(book.outputs_pdf, ["screen", "print"])
            self.assertTrue(book.outputs_epub and book.outputs_html)
            self.assertEqual(book.artifact("zh", "pdf", "print"), "demo-1.2.3-zh-print.pdf")
            self.assertEqual(book.artifact("en", "pdf"), "demo-1.2.3-en-screen.pdf")
            self.assertEqual(book.artifact("en", "epub"), "demo-1.2.3-en.epub")
            with self.assertRaises(ValueError):
                book.artifact("en", "docx")
            with self.assertRaisesRegex(config.ConfigError, "no 'fr' edition"):
                book.edition("fr")
            self.assertEqual(book.viz_dir, book.dir / "viz")

            write(repo.root / "books" / "second" / "book.toml", """\
                [book]
                title = "Second"
                code = "SEC//ONE"
                [outputs]
                pdf = false
                epub = false
                """)
            second = config.load_book("second")
            self.assertEqual(second.languages, ["zh", "en"], "editions default to the site languages")
            self.assertEqual(second.outputs_pdf, [])
            self.assertEqual(second.title, {"*": "Second"})
            self.assertEqual(second.edition("en").title, "Second")
            self.assertEqual(config.book_slugs(), ["second", "demo"], "site.toml [books].order first")
            self.assertEqual([b.slug for b in config.load_books(["demo"])], ["demo"])
            with self.assertRaisesRegex(config.ConfigError, "unknown book"):
                config.load_books(["nope"])

            bad = repo.root / "books" / "bad"
            for text, msg in (('[book]\nversion="1"\n', "book.title is required"),
                              ('[book]\ntitle="x"\neditions=["zh","E N"]\n', "invalid edition language"),
                              ('[book]\ntitle="x"\n[outputs]\npdf=["a4"]\n', "outputs.pdf entries")):
                write(bad / "book.toml", text)
                with self.assertRaisesRegex(config.ConfigError, msg):
                    config.load_book("bad")
            write(repo.root / "books" / "Bad_Slug" / "book.toml", '[book]\ntitle="x"\n')
            with self.assertRaisesRegex(config.ConfigError, "kebab-case"):
                config.load_book("Bad_Slug")
            with self.assertRaisesRegex(config.ConfigError, "not found"):
                config.load_book("missing")


# --------------------------------------------------------------------------- summary


class SummaryTests(unittest.TestCase):
    def parse(self, text: str) -> summary.Summary:
        with tempfile.TemporaryDirectory() as tmp:
            p = write(Path(tmp) / "SUMMARY.md", text)
            return summary.parse_summary(p)

    def test_sections_numbers_parts_drafts(self):
        s = self.parse("""\
            # Summary

            <!-- a comment
            spanning lines -->
            [Preface](README.md)
            [Intro](intro.md)

            # Part I

            - [One](one.md)
              - [One.One](one/a.md)
                - [Deep](one/a/deep.md)
              - [One.Two](one/b.md)
            - [Two \\[draft\\]]()
            <!-- one-line comment -->

            # Part II

            ---

            - [Three](three.md)

            [Appendix](app-a.md)
            [Glossary](app-b.md)
            """)
        self.assertEqual(s.title, "Summary")
        rows = [(c.title, c.path, c.section, c.number_label, c.depth, c.part, c.top) for c in s.chapters]
        self.assertEqual(rows, [
            ("Preface", "README.md", "prefix", "", 0, "", 0),
            ("Intro", "intro.md", "prefix", "", 0, "", 1),
            ("One", "one.md", "numbered", "1", 0, "Part I", 2),
            ("One.One", "one/a.md", "numbered", "1.1", 1, "Part I", 2),
            ("Deep", "one/a/deep.md", "numbered", "1.1.1", 2, "Part I", 2),
            ("One.Two", "one/b.md", "numbered", "1.2", 1, "Part I", 2),
            ("Two [draft]", None, "numbered", "2", 0, "Part I", 3),
            ("Three", "three.md", "numbered", "3", 0, "Part II", 4),
            ("Appendix", "app-a.md", "suffix", "", 0, "Part II", 5),
            ("Glossary", "app-b.md", "suffix", "", 0, "Part II", 6),
        ])
        self.assertTrue(s.chapters[6].draft)
        self.assertEqual([c.title for c in s.chapters[2].children], ["One.One", "One.Two"])
        self.assertEqual(s.files(), ["README.md", "intro.md", "one.md", "one/a.md", "one/a/deep.md", "one/b.md",
                                     "three.md", "app-a.md", "app-b.md"])
        self.assertEqual(len(s.top_level()), 7)
        prefixes = [summary.chapter_prefix(s, c) for c in s.chapters]
        self.assertEqual(prefixes, ["0", "0", "1", "1", "1", "1", "2", "3", "A", "B"])

    def test_appendix_letters(self):
        self.assertEqual([summary._letters(n) for n in (0, 1, 25, 26, 27, 51, 52, 701, 702)],
                         ["A", "B", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA"])

    def test_errors(self):
        cases = {
            "- plain text item\n": "list items must be links",
            "- [A](a.md)\n\n[S](s.md)\n\n- [B](b.md)\n": "cannot follow suffix",
            "- [A](../a.md)\n": "must stay inside the edition",
            "- [A](/abs.md)\n": "must stay inside the edition",
            "- [A](a.html)\n": "must be a .md file",
            "Just some prose\n": "unrecognised SUMMARY line",
        }
        for text, msg in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(summary.SummaryError) as ctx:
                    self.parse(text)
                self.assertIn(msg, ctx.exception.message)
                self.assertGreater(ctx.exception.line, 0)

    def test_no_title_and_star_bullets(self):
        s = self.parse("* [A](a.md)\n    * [B](b.md)\n")
        self.assertEqual(s.title, "")
        self.assertEqual([c.number_label for c in s.chapters], ["1", "1.1"])


# --------------------------------------------------------------------------- mdscan


class MdscanTests(unittest.TestCase):
    def test_fenced_code_is_opaque(self):
        text = textwrap.dedent("""\
            before [@a]
            ````markdown
            ```
            ::: {.theorem #in-code}
            [@b]
            ```
            ````
            ~~~
            ::: proof
            ~~~~
            after
            """)
        issues: list[mdscan.ScanIssue] = []
        nodes = mdscan.parse_blocks(text, issues)
        self.assertEqual(issues, [])
        self.assertEqual([type(n).__name__ for n in nodes], ["Text", "Code", "Code", "Text"])
        self.assertEqual(len(nodes[1].lines), 6, "a 4-backtick fence is not closed by 3 backticks")
        self.assertEqual(nodes[2].lines[-1], "~~~~", "a longer closing fence closes")
        lines = [line for _, line in mdscan.iter_text_lines(nodes)]
        self.assertEqual(lines, ["before [@a]", "after", ""])
        self.assertEqual(mdscan.render_blocks(nodes), text, "serialising unchanged blocks is lossless")

    def test_nested_divs_and_shorthand(self):
        text = textwrap.dedent("""\
            :::: {.theorem #thm-x lean="D5/S1/A/B.c"}
            Statement.

            ::: proof
            Inner [@thm-x].
            :::
            ::::
            ::: {.note}
            free div
            :::
            :::
            """)
        nodes = mdscan.parse_blocks(text)
        outer = nodes[0]
        self.assertIsInstance(outer, mdscan.Div)
        self.assertEqual((outer.attrs.id, outer.classes, outer.attrs.get("lean")), ("thm-x", ["theorem"], "D5/S1/A/B.c"))
        self.assertEqual((outer.start, outer.end, outer.fence), (1, 7, "::::"))
        inner = [n for n in outer.children if isinstance(n, mdscan.Div)][0]
        self.assertEqual((inner.classes, inner.start, inner.end), (["proof"], 4, 6))
        self.assertEqual([type(n).__name__ for n in mdscan.walk(nodes)][:4], ["Div", "Text", "Div", "Text"])
        self.assertEqual(nodes[-1].lines[0], ":::", "a closing fence with nothing open is plain text")
        self.assertEqual(mdscan.render_blocks(nodes), text)

    def test_unclosed_div_and_bad_attributes(self):
        issues: list[mdscan.ScanIssue] = []
        nodes = mdscan.parse_blocks("::: {.theorem #a}\nnever closed\n", issues)
        self.assertEqual([(i.line, "never closed" in i.message) for i in issues], [(1, True)])
        self.assertEqual(nodes[0].end, 0)
        self.assertEqual(mdscan.render_blocks(nodes), "::: {.theorem #a}\nnever closed\n")
        issues = []
        nodes = mdscan.parse_blocks('::: {.theorem #a #b}\n:::\n::: {.x = }\n:::\n', issues)
        self.assertEqual(len(issues), 2)
        self.assertIn("more than one #id", issues[0].message)
        self.assertIn("cannot parse attributes", issues[1].message)
        self.assertEqual(nodes[0].attrs, mdscan.Attrs())

    def test_parse_attrs(self):
        a = mdscan.parse_attrs(r'''.theorem #thm:a-b_1 title="A \"quoted\" title" note='it\'s' lean=D5/S1/A/B.c data-n=3 .extra''')
        self.assertEqual(a.id, "thm:a-b_1")
        self.assertEqual(a.classes, ["theorem", "extra"])
        self.assertEqual(a.kv, {"title": 'A "quoted" title', "note": "it's", "lean": "D5/S1/A/B.c", "data-n": "3"})
        self.assertEqual(a.get("missing", "d"), "d")
        self.assertEqual(mdscan.parse_attrs("  "), mdscan.Attrs())
        again = mdscan.parse_attrs(a.to_pandoc()[1:-1])
        self.assertEqual((again.id, again.classes, again.kv), (a.id, a.classes, a.kv), "to_pandoc round-trips")
        self.assertEqual(mdscan.escape_attr('a\\b"c\nd'), 'a\\\\b\\"c d')
        with self.assertRaises(mdscan.AttrError):
            mdscan.parse_attrs('title="unterminated')

    def test_code_spans_refs_and_lean_links(self):
        line = r"a `[@x]` b ``c ` [@y] `` [@z] \`[@w]\` `unclosed [@v]"
        spans = mdscan.code_spans(line)
        self.assertEqual([line[a:b] for a, b in spans], ["`[@x]`", "``c ` [@y] ``"])
        refs = [m.group("id") for m in mdscan.find_outside_code(mdscan.REF_RE, line)]
        self.assertEqual(refs, ["z", "w", "v"])
        self.assertEqual([m.group("id") for m in mdscan.REF_RE.finditer("[@a](x) [@b]")], ["b"],
                         "[@a](…) is a link, not a reference")
        line = f"see [`deficit`](lean:{GID_3V}) and `[t](lean:{GID_INT})` and [plain](lean:{GID_DEF})"
        self.assertEqual(mdscan.lean_link_gids(line), [GID_3V, GID_DEF])
        out = mdscan.sub_outside_code(mdscan.REF_RE, lambda m: m.group("id").upper(), "[@a] `[@b]` [@c]")
        self.assertEqual(out, "A `[@b]` C")

    def test_transform_text(self):
        nodes = mdscan.parse_blocks("x\n```\nx\n```\n::: proof\nx\n:::\n")
        mdscan.transform_text(nodes, lambda s: s.replace("x", "y"))
        self.assertEqual(mdscan.render_blocks(nodes), "y\n```\nx\n```\n::: proof\ny\n:::\n")


# --------------------------------------------------------------------------- lean


class LeanTests(unittest.TestCase):
    def test_parse_name_key(self):
        self.assertEqual(lean.parse_name_key("n0"), [])
        self.assertEqual(lean.parse_name_key(name_key("D5", "S1", "Deficit", "deficit_three_valued")),
                         ["D5", "S1", "Deficit", "deficit_three_valued"])
        self.assertEqual(lean.parse_name_key("nn(ns(n0,3:Foo),12)"), ["Foo", 12])
        self.assertEqual(lean.parse_name_key("ns(n0,7:a,b)c(d)"), ["a,b)c(d"], "components may contain delimiters")
        priv = lean.parse_name_key(name_key("helper", private_of=("D5", "S1", "M")))
        self.assertEqual(priv, ["_private", "D5", "S1", "M", 0, "helper"])
        self.assertTrue(lean.is_private(priv))
        self.assertFalse(lean.is_private(["D5", "x"]))
        for bad in ("nx(n0,1:a)", "ns(n0,1:a)extra", "ns(n0;1:a)", "ns(n0,1:ab)"):
            with self.assertRaises(lean.LeanError, msg=bad):
                lean.parse_name_key(bad)

    # BUG (lean.parse_name_key): trureturing writes component lengths in UTF-8 *bytes*
    # (e.g. "ns(ns(n0,9:LinearMap),5:mk₂)", 193 such keys among the first 4000 state files at the
    # pinned commit), but the parser slices *characters*. Any module that contains one such name
    # fails to resolve at all — with LeanError, or even an uncaught IndexError ("ns(n0,4:n₁)").
    # Patch, in the "ns(" branch:
    #     raw = key[start:].encode("utf-8")[:length]
    #     try: comp = raw.decode("utf-8")
    #     except UnicodeDecodeError as exc: raise LeanError(f"bad name key at {start}: split UTF-8 sequence") from exc
    #     i = start + len(comp)
    def test_parse_name_key_counts_utf8_bytes(self):
        self.assertEqual(lean.parse_name_key("ns(ns(ns(n0,9:LinearMap),5:mk₂),10:congr_simp)"),
                         ["LinearMap", "mk₂", "congr_simp"])
        self.assertEqual(lean.parse_name_key("ns(n0,4:n₁)"), ["n₁"])

    def test_resolve_module_with_multibyte_names(self):
        st = {"M": {"statement_id": "s", "declarations": [
            {"declaration_name_key": "ns(ns(n0,1:X),4:n₁)", "kind": "def"},
            {"declaration_name_key": "ns(ns(n0,1:X),6:result)", "kind": "theorem"}]}}
        led = FakeLedger({"D5/S0/Certificates/M": st["M"]})
        self.assertEqual(lean.resolve(led, COMMIT, "D5/S0/Certificates/M.result").name, "X.result")

    # The same bug against trureturing itself (skipped without a local checkout of the pinned commit):
    # this frozen module lists GRType.n₁ … so citing its theorem `result` crashes ./tbook check / pin
    # with an uncaught IndexError.
    @unittest.skipUnless(TRURETURING, "needs a trureturing checkout ($TRURETURING_DIR) with the pinned commit")
    def test_resolve_real_module_with_multibyte_names(self):
        checkout, commit = TRURETURING
        led = lean.Ledger(TRU, offline=True, checkout=checkout)
        res = lean.resolve(led, commit, "D5/S0/Certificates/Combinatorics/GaleRobinsonKernelDimensionRefutation.result")
        self.assertEqual(res.kind, "theorem")

    @unittest.skipUnless(TRURETURING, "needs a trureturing checkout ($TRURETURING_DIR) with the pinned commit")
    def test_resolve_real_pinned_declarations(self):
        checkout, commit = TRURETURING
        led = lean.Ledger(TRU, offline=True, checkout=checkout)
        lock = lean.Lock.load(REAL_LOCK)
        for gid, decl in lock.declarations.items():
            res = lean.resolve(led, commit, gid)
            self.assertEqual((res.name, res.kind, res.statement_id), (decl["name"], decl["kind"], decl["statement_id"]))

    def test_name_to_str(self):
        self.assertEqual(lean.name_to_str(["D5", "S1", "x'", "y!", "z?"]), "D5.S1.x'.y!.z?")
        self.assertEqual(lean.name_to_str(["Foo", 3, "bar"]), "Foo.3.bar")
        self.assertEqual(lean.name_to_str(["Foo", "with space", "1st", "a.b"]), "Foo.«with space».«1st».«a.b»")

    def test_gid(self):
        g = lean.parse_gid(f"  {GID_3V} ")
        self.assertEqual((g.module, g.name), (MOD_3V, "deficit_three_valued"))
        self.assertEqual(g.text, GID_3V)
        self.assertEqual(g.lean_module, "D5.S1.Deficit.DeficitThreeValued")
        self.assertEqual(g.state_path, f"Golden/Frozen/state/{MOD_3V}.lean.json")
        self.assertEqual(g.source_path, f"{MOD_3V}.lean")
        self.assertEqual(g.blueprint_path, f"Blueprint/{MOD_3V}.md")
        g = lean.parse_gid("D10/S2/A.Ns.name'")
        self.assertEqual((g.module, g.name), ("D10/S2/A", "Ns.name'"))
        for bad in ("deficit", "D5/S1.x", "X5/S1/A.b", "D5/S1/A", "D5/S1/A.", "D5/S1/A.b c", "D5/S1/A.1b",
                    "D5/S1/A/.b"):
            with self.assertRaises(lean.LeanError, msg=bad):
                lean.parse_gid(bad)
        self.assertEqual(lean.split_gids(f" {GID_3V}, {GID_INT}\n{GID_DEF} "), [GID_3V, GID_INT, GID_DEF])
        self.assertEqual(lean.split_gids(""), [])

    def test_resolve(self):
        led = FakeLedger()
        r = lean.resolve(led, COMMIT, GID_3V)
        self.assertEqual((r.gid, r.module, r.name, r.kind, r.statement_id),
                         (GID_3V, MOD_3V, "D5.S1.Deficit.deficit_three_valued", "theorem", "sha256:3v"))
        self.assertNotIn("gid", r.to_lock())
        self.assertEqual(lean.resolve(led, COMMIT, f"{MOD_3V}.Deficit.deficit_three_valued").name,
                         "D5.S1.Deficit.deficit_three_valued", "dotted suffixes match")
        self.assertEqual(lean.resolve(led, COMMIT, f"{MOD_3V}.D5.S1.Deficit.deficit_three_valued").kind, "theorem",
                         "full names match")
        with self.assertRaisesRegex(lean.LeanError, "no frozen declaration named 'helper'"):
            lean.resolve(led, COMMIT, f"{MOD_3V}.helper")  # private declarations are not citable
        with self.assertRaisesRegex(lean.LeanError, "no frozen declaration named 'three_valued'"):
            lean.resolve(led, COMMIT, f"{MOD_3V}.three_valued")  # a suffix must start at a dot
        with self.assertRaisesRegex(lean.LeanError, "not frozen"):
            lean.resolve(led, COMMIT, "D5/S1/Deficit/Unfrozen.x")
        amb = FakeLedger({"D5/S1/M": {"statement_id": "s", "declarations": [
            {"declaration_name_key": name_key("A", "lemma1"), "kind": "theorem"},
            {"declaration_name_key": name_key("B", "lemma1"), "kind": "theorem"}]}})
        with self.assertRaisesRegex(lean.LeanError, "ambiguous, matches A.lemma1, B.lemma1"):
            lean.resolve(amb, COMMIT, "D5/S1/M.lemma1")
        self.assertEqual(lean.resolve(amb, COMMIT, "D5/S1/M.B.lemma1").name, "B.lemma1")
        with self.assertRaises(lean.LeanError):
            lean.resolve(led, COMMIT, "not a gid")

    def test_locate(self):
        src = textwrap.dedent("""\
            namespace D5.S1.Deficit

            /-- doc -/
            @[simp] protected theorem deficit_three_valued (v : Nat) :
                v = v := by
              rfl
            """)
        led = FakeLedger(sources={f"{MOD_3V}.lean": src})
        res = lean.resolve(led, COMMIT, GID_3V)
        lean.locate(led, COMMIT, res)
        self.assertEqual(res.line, 4)
        self.assertEqual(res.signature, "@[simp] protected theorem deficit_three_valued (v : Nat) : v = v")
        res2 = lean.resolve(led, COMMIT, GID_INT)
        lean.locate(led, COMMIT, res2)  # no source: best effort, nothing set
        self.assertEqual((res2.line, res2.signature), (0, ""))

    def test_lock_round_trip_and_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "lock.json"
            lock = make_lock()
            lock.save(p)
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(list(data), ["schema", "repo", "branch", "commit", "pinned_at", "declarations"])
            self.assertEqual(list(data["declarations"]), sorted(data["declarations"]))
            again = lean.Lock.load(p)
            self.assertEqual((again.repo, again.branch, again.commit, again.pinned_at, again.declarations),
                             (lock.repo, lock.branch, lock.commit, lock.pinned_at, lock.declarations))
            self.assertIsNone(lean.Lock.load(Path(tmp) / "absent.json"))
            p.write_text(json.dumps(dict(data, schema="v0")), encoding="utf-8")
            with self.assertRaisesRegex(lean.LeanError, "unsupported schema"):
                lean.Lock.load(p)
            p.write_text(json.dumps(dict(data, commit="abc")), encoding="utf-8")
            with self.assertRaisesRegex(lean.LeanError, "40-hex"):
                lean.Lock.load(p)
        res = lock.get(GID_3V)
        self.assertEqual((res.gid, res.line, res.kind), (GID_3V, 12, "theorem"))
        self.assertIsNone(lock.get("D5/S1/X.y"))
        base = f"https://github.com/{TRU}/blob/{COMMIT}"
        self.assertEqual(lock.source_url(GID_3V), f"{base}/{MOD_3V}.lean#L12")
        self.assertEqual(lock.source_url(GID_INT), f"{base}/{MOD_INT}.lean", "no line: no anchor")
        self.assertEqual(lock.source_url("D5/S1/Other.x"), f"{base}/D5/S1/Other.lean")
        self.assertEqual(lock.state_url(GID_3V), f"{base}/Golden/Frozen/state/{MOD_3V}.lean.json")
        self.assertEqual(lock.blueprint_url(GID_3V), f"{base}/Blueprint/{MOD_3V}.md")
        self.assertEqual(lock.tree_url, f"https://github.com/{TRU}/tree/{COMMIT}")
        self.assertEqual(lean.ls_remote(TRU, COMMIT), COMMIT, "a full SHA needs no network")
        self.assertRegex(lean.now_utc(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_ledger_sources(self):
        with CoreRepo() as repo, tempfile.TemporaryDirectory() as gtmp:
            g = Path(gtmp)
            env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                       GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
            write(g / f"Golden/Frozen/state/{MOD_3V}.lean.json", json.dumps(states()[MOD_3V]))
            for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
                subprocess.run(["git", "-C", str(g), *cmd], check=True, env=env, capture_output=True)
            sha = subprocess.run(["git", "-C", str(g), "rev-parse", "HEAD"], capture_output=True, text=True,
                                 env=env).stdout.strip()
            led = lean.Ledger(TRU, offline=True, checkout=g)
            self.assertEqual([type(s).__name__ for s in led.sources], ["GitSource", "CacheSource"])
            self.assertEqual(led.state(sha, MOD_3V)["statement_id"], "sha256:3v")
            self.assertIsNone(led.state(sha, MOD_INT), "absent at the commit: not frozen")
            self.assertEqual(lean.resolve(led, sha, GID_3V).kind, "theorem")
            with self.assertRaisesRegex(lean.LeanError, "network disabled"):
                led.state(COMMIT, MOD_3V)  # the checkout does not have this commit, nor the cache
            cache = lean.CacheSource(repo.root / ".cache" / "trureturing")
            cache.store(COMMIT, f"Golden/Frozen/state/{MOD_3V}.lean.json", json.dumps(states()[MOD_3V]).encode())
            cache.store(COMMIT, f"Golden/Frozen/state/{MOD_INT}.lean.json", b"")
            led2 = lean.Ledger(TRU, offline=True)
            self.assertEqual([type(s).__name__ for s in led2.sources], ["CacheSource"])
            self.assertEqual(led2.state(COMMIT, MOD_3V)["statement_id"], "sha256:3v")
            self.assertIsNone(led2.state(COMMIT, MOD_INT), "a .missing marker means absent")
            os.environ["TRURETURING_DIR"] = str(g)
            self.assertEqual(type(lean.Ledger(TRU, offline=True).sources[0]).__name__, "GitSource")
            self.assertIn("HttpSource", [type(s).__name__ for s in lean.Ledger(TRU).sources])


# --------------------------------------------------------------------------- model


class ModelTests(unittest.TestCase):
    def test_numbering_refs_and_links(self):
        with CoreRepo() as repo:
            book = repo.book()
            m = model.load_edition(book.edition("zh"))
            self.assertEqual(m.issues, [])
            numbers = {e.id or e.kind: e.number for e in m.all_envs()}
            self.assertEqual(numbers, {"rem-intro": "0.1", "thm-a": "1.1", "proof": "", "def-d": "1.2",
                                       "conj-x": "1.3", "lem-b": "2.1", "cor-c": "2.2", "ex-a": "A.1",
                                       "rem-b": "B.1", "prob-p": "B.2"})
            self.assertEqual([e.id for e in m.formal_envs()], ["thm-a", "lem-b", "cor-c"])
            thm = m.envs["thm-a"]
            self.assertEqual((thm.kind, thm.status, thm.title, thm.lean), ("theorem", "lean", "亏量三值", [GID_3V]))
            self.assertEqual(thm.ref_text("zh"), "定理1.1")
            self.assertEqual(thm.ref_text("en"), "Theorem 1.1")
            self.assertEqual(thm.heading("zh"), "定理1.1（亏量三值）")
            self.assertEqual(m.envs["conj-x"].status, "open")
            self.assertEqual(m.envs["def-d"].status, "definition")
            self.assertEqual(m.envs["rem-b"].status, "informal")
            ch01 = m.chapters[1]
            self.assertEqual(ch01.chapter.path, "ch01.md")
            self.assertEqual([r for _, r in ch01.refs], ["thm-a"], "refs in code are ignored")
            self.assertEqual([g for _, g in ch01.lean_links], [GID_3V])
            self.assertEqual(m.chapter_of("cor-c").chapter.path, "part/ch02-1.md")
            self.assertIsNone(m.chapter_of("nope"))
            cited = sorted({g for _, _, g, _ in m.cited_gids()})
            self.assertEqual(cited, sorted([GID_3V, GID_DEF, GID_INT]))
            self.assertEqual(len(m.chapters), 6, "drafts are skipped")
            self.assertEqual(model.load_book_models(book).keys(), {"zh", "en"})

    def test_media_and_kinds(self):
        with CoreRepo() as repo:
            files = {"zh": {"README.md": "::: {.viz src=\"golden\"}\ncap\n:::\n::: {.remark #r .viz}\n:::\n"
                                         "::: {.unknown #u}\n:::\n"}}
            book = repo.book(langs=("zh",), summaries={"zh": "[P](README.md)\n"}, files=files)
            m = model.load_edition(book.primary)
            doc = m.chapters[0]
            self.assertEqual([(e.kind, e.number, e.attrs.get("src")) for e in doc.media], [("viz", "", "golden")])
            self.assertEqual([(e.kind, e.number) for e in doc.envs], [("remark", "0.1")],
                             "the first known class decides the kind; unknown divs are not environments")

    # BUG (model.load_edition): the counter is per top-level chapter, so two prefix chapters both
    # number from 0.1 and two different environments get the same label ("注 0.1"), which makes
    # references ambiguous. All prefix chapters share the prefix "0", so they should share a counter.
    # Patch: before numbering, `top = summary.top_level()[chapter.top]` and
    # `ckey = "prefix" if top.section == "prefix" else chapter.top`; use counters[ckey].
    def test_prefix_chapters_share_numbering(self):
        with CoreRepo() as repo:
            files = {"zh": {"a.md": "::: {.remark #r1}\n:::\n", "b.md": "::: {.remark #r2}\n:::\n"}}
            book = repo.book(langs=("zh",), summaries={"zh": "[A](a.md)\n[B](b.md)\n"}, files=files)
            m = model.load_edition(book.primary)
            self.assertEqual([e.number for e in m.all_envs()], ["0.1", "0.2"])

    def test_issues(self):
        with CoreRepo() as repo:
            files = {"zh": {"a.md": "::: {.theorem #dup}\n:::\n::: {.remark #dup}\n:::\n::: proof\nunclosed\n"}}
            book = repo.book(langs=("zh",), summaries={"zh": "- [A](a.md)\n- [Missing](missing.md)\n"}, files=files)
            m = model.load_edition(book.primary)
            msgs = messages(m.issues)
            self.assertTrue(any("chapter file not found: missing.md" in x for x in msgs), msgs)
            self.assertTrue(any("duplicate id #dup" in x for x in msgs), msgs)
            self.assertTrue(any("never closed" in x for x in msgs), msgs)
            self.assertTrue(all(i.severity == "error" for i in m.issues))
            (book.primary.summary).write_text("- not a link\n", encoding="utf-8")
            m = model.load_edition(book.primary)
            self.assertIsNone(m.summary)
            self.assertIn("list items must be links", messages(m.issues)[0])
            book.primary.summary.unlink()
            self.assertEqual(messages(model.load_edition(book.primary).issues), ["SUMMARY.md is missing"])

    def test_issue_formatting(self):
        with CoreRepo() as repo:
            issue = model.Issue("error", repo.root / "books" / "a.md", 3, "bad 100%\nnext")
            self.assertEqual(issue.format(), "ERROR   books/a.md:3: bad 100%\nnext")
            self.assertEqual(issue.github(), "::error file=books/a.md,line=3::bad 100%25%0Anext")
            self.assertEqual(model.Issue("warning", None, 0, "w").github(), "::warning::w")
            self.assertEqual(model.Issue("warning", None, 0, "w").format(), "WARNING -: w")


# --------------------------------------------------------------------------- render


class RenderTests(unittest.TestCase):
    def ctx(self, repo: CoreRepo, lang: str = "zh", target: str = "mdbook", lock: lean.Lock | None = None):
        book = repo.book()
        ed = book.edition(lang)
        m = model.load_edition(ed)
        return render.RenderContext(site=config.load_site(), book=book, edition=ed, model=m,
                                    lock=lock if lock is not None else make_lock(), target=target,
                                    env_href=render.mdbook_env_href(m) if target == "mdbook" else None)

    def test_current_labels_follow_only_lock_changes(self):
        with CoreRepo() as repo:
            source = (f"[{{commit}}](trureturing:) [{{source}}](lean:{GID_3V}) "
                      f"[{{statement_id}}](lean:{GID_3V})")
            for target in ("mdbook", "pandoc"):
                ctx = self.ctx(repo, target=target)
                doc = ctx.model.chapters[1]
                first = render.transform_line(source, doc, ctx)
                self.assertIn(COMMIT, first)
                self.assertIn(f"{MOD_3V}.lean:12", first)
                ctx.lock.commit = OLD_COMMIT
                ctx.lock.declarations[GID_3V]["line"] = 93
                ctx.lock.declarations[GID_3V]["statement_id"] = "sha256:123456789abcdef"
                second = render.transform_line(source, doc, ctx)
                self.assertNotIn(COMMIT, second)
                self.assertIn(f"{MOD_3V}.lean:93", second)
                self.assertIn("#L93", second)
                self.assertIn("`sha256:12345678`", second)
                self.assertNotIn("{source}", second)
                literal = f"`[{{source}}](lean:{GID_3V})`"
                self.assertEqual(render.transform_line(literal, doc, ctx), literal)

    def test_refs_links_and_assets(self):
        with CoreRepo() as repo:
            ctx = self.ctx(repo)
            m = ctx.model
            with mock.patch("importlib.import_module", side_effect=media_stub):
                ch01 = render.chapter_markdown(m.chapters[1], ctx)
                ch02 = render.chapter_markdown(m.chapters[2], ctx)
                sec = render.chapter_markdown(m.chapters[3], ctx)
            self.assertIn("见 [定理1.1](#thm-a) 与 `[@not-a-ref]`.", ch01, "same chapter: fragment only")
            self.assertIn("由 [定理1.1](ch01.md#thm-a) 与 [引理2.1](#lem-b).", ch02)
            self.assertIn("[定理1.1](../ch01.md#thm-a).", sec, "relative to a nested chapter")
            url = f"https://github.com/{TRU}/blob/{COMMIT}/{MOD_3V}.lean#L12"
            self.assertIn(f"[`deficit_three_valued`]({url})", ch01)
            self.assertIn('![fig](_book/assets/fig.svg "Figure")', ch01)
            self.assertIn("![fig](../_book/assets/fig.svg)", sec)
            self.assertIn("[ext](https://example.org/x) [here](#thm-a) [next](ch02.md)", ch01)
            self.assertIn("[@in-code] [x](lean:not/a.gid)", ch01, "code blocks are untouched")
            self.assertEqual(ctx.book_files, {(repo.root / "books" / "demo" / "assets" / "fig.svg").resolve()})
            self.assertEqual(ctx.issues, [])

    def test_unknown_ref_and_escaping_link(self):
        with CoreRepo() as repo:
            ctx = self.ctx(repo)
            doc = ctx.model.chapters[1]
            out = render.transform_line("[@missing] [x](../../../outside.png)", doc, ctx)
            self.assertEqual(out, "**[@missing?]** [x](../../../outside.png)")
            self.assertEqual(len(ctx.issues), 2)
            self.assertTrue(any("unknown reference [@missing]" in i for i in ctx.issues), ctx.issues)
            self.assertTrue(any("link leaves the book directory: ../../../outside.png" in i for i in ctx.issues))

    def test_mdbook_env_markup(self):
        with CoreRepo() as repo:
            ctx = self.ctx(repo)
            with mock.patch("importlib.import_module", side_effect=media_stub):
                out = render.chapter_markdown(ctx.model.chapters[1], ctx)
            url = f"https://github.com/{TRU}/blob/{COMMIT}/{MOD_3V}.lean#L12"
            self.assertIn('<section class="tr-env tr-theorem tr-status-lean" id="thm-a" data-kind="theorem">', out)
            self.assertIn('<header class="tr-env-head"><span class="tr-env-label">定理1.1</span>'
                          '<span class="tr-env-title">（亏量三值）</span>'
                          f'<a class="tr-badge tr-badge-lean" href="{url}" title="{config.s("zh", "badge.lean_title")}">'
                          'LEAN ✓</a></header>', out)
            self.assertIn(f'<footer class="tr-env-lean"><a class="tr-lean-decl" href="{url}" title="{GID_3V}">'
                          '<code>D5.S1.Deficit.deficit_three_valued</code></a></footer>', out)
            self.assertIn('<section class="tr-env tr-proof tr-status-proof" data-kind="proof">\n'
                          '<header class="tr-env-head"><span class="tr-env-label">证明</span></header>', out)
            self.assertIn('<span class="tr-qed" aria-hidden="true">∎</span>', out)
            self.assertIn('<span class="tr-badge tr-badge-open" title="', out)
            self.assertIn('<section class="tr-env tr-definition tr-status-definition" id="def-d"', out)
            self.assertNotIn("tr-badge-lean\" href=\"https://github.com/the-omega-institute/trureturing/blob/"
                             f"{COMMIT}/{MOD_INT}", out, "definitions get no LEAN badge")

    def test_pandoc_env_attributes(self):
        with CoreRepo() as repo:
            ctx = self.ctx(repo, lang="en", target="pandoc")
            with mock.patch("importlib.import_module", side_effect=media_stub):
                out = render.chapter_markdown(ctx.model.chapters[1], ctx)
            first = next(line for line in out.splitlines() if line.startswith(":::::: {#thm-a"))
            attrs = mdscan.parse_attrs(first[len(":::::: {"):-1])
            self.assertEqual(attrs.id, "thm-a")
            self.assertEqual(attrs.classes, ["tr-env", "theorem"])
            url = f"https://github.com/{TRU}/blob/{COMMIT}/{MOD_3V}.lean#L12"
            self.assertEqual(attrs.kv, {
                "tr-kind": "theorem", "tr-status": "lean", "tr-label": "Theorem", "tr-number": "1.1",
                "tr-ref": "Theorem 1.1", "tr-title": "Three values", "tr-badge": "LEAN ✓",
                "tr-badge-title": config.s("en", "badge.lean_title"), "tr-badge-url": url, "tr-lean": GID_3V,
                "tr-lean-name": "D5.S1.Deficit.deficit_three_valued", "tr-lean-url": url})
            self.assertIn("See [Theorem 1.1](#thm-a)", out, "pandoc targets link by fragment")
            self.assertIn(":::::: {#conj-x .tr-env .conjecture tr-kind=\"conjecture\" tr-status=\"open\"", out)
            closes = [line for line in out.splitlines() if line == "::::::"]
            self.assertEqual(len(closes), 4)

    def test_lean_view_without_lock_and_free_divs_and_media(self):
        with CoreRepo() as repo:
            view = render.lean_view(GID_INT, None)
            self.assertEqual((view["name"], view["url"]), ("D5.S1.Deficit.DeficitInteger.deficit_integer", ""))
            self.assertEqual(render.lean_view("bad gid", None)["name"], "")
            files = {"zh": {"README.md": "::: {.note #n}\nx\n:::\n\n::: {.viz src=\"golden\"}\ncap\n:::\n"},
                     "en": {"README.md": "::: {.note #n}\nx\n:::\n\n::: {.viz src=\"golden\"}\ncap\n:::\n"}}
            book = repo.book(summaries={"zh": "[P](README.md)\n", "en": "[P](README.md)\n"}, files=files)
            m = model.load_edition(book.primary)
            for target, expect in (("mdbook", '<div class="note" id="n">\n\nx\n\n</div>'),
                                   ("pandoc", '::: {#n .note}\nx\n:::')):
                ctx = render.RenderContext(site=config.load_site(), book=book, edition=book.primary, model=m,
                                           lock=None, target=target)
                with mock.patch("importlib.import_module", side_effect=media_stub):
                    out = render.chapter_markdown(m.chapters[0], ctx)
                self.assertIn(expect, out)
                self.assertIn("<MEDIA viz golden>", out)


# --------------------------------------------------------------------------- ledger


class LedgerChapterTests(unittest.TestCase):
    def test_ledger_markdown(self):
        with CoreRepo() as repo:
            book = repo.book()
            m = model.load_edition(book.edition("en"))
            text = ledger.ledger_markdown(m, make_lock())
            self.assertTrue(text.startswith(f"# {config.s('en', 'ledger.title')} {{#{ledger.LEDGER_ID} .unnumbered}}"))
            url = f"https://github.com/{TRU}/blob/{COMMIT}/{MOD_3V}.lean#L12"
            self.assertIn(f"| [Theorem 1.1](#thm-a) | Three values | [`D5.S1.Deficit.deficit_three_valued`]({url}) |", text)
            self.assertIn("[Lemma 2.1](#lem-b)", text)
            self.assertIn("- [Conjecture 1.3](#conj-x)", text)
            self.assertIn("Open", text)
            self.assertIn(f"[`{COMMIT[:12]}`](https://github.com/{TRU}/tree/{COMMIT})", text)
            bare = ledger.ledger_markdown(m, None, href=lambda env: f"x.html#{env.id}")
            self.assertIn("`D5.S1.Deficit.deficit_three_valued`", bare.replace(GID_3V, "D5.S1.Deficit.deficit_three_valued"))
            self.assertIn("(x.html#thm-a)", bare)


# --------------------------------------------------------------------------- check


class CheckTests(unittest.TestCase):
    def test_env_policy(self):
        with CoreRepo() as repo:
            bad = f"""\
                ::: {{.theorem #thm-nolean}}
                :::
                ::: {{.lemma lean="{GID_INT}"}}
                :::
                ::: {{.conjecture #conj-lean lean="{GID_INT}"}}
                :::
                ::: {{.theorem #thm-badgid lean="not-a-gid"}}
                :::
                ::: {{.remark #1bad}}
                :::
                ::: viz
                :::
                ::: {{.definition}}
                :::

                [@missing-ref] [x](lean:bad) `[@in-code-is-fine]`
                """
            book = repo.book(langs=("zh",), summaries={"zh": "- [A](a.md)\n"}, files={"zh": {"a.md": bad}})
            m = model.load_edition(book.primary)
            issues: list[model.Issue] = []
            check.check_env_policy(m, issues)
            msgs = messages(issues, "error")
            expected = ["theorem #thm-nolean cites no Lean declaration", "lemma needs an id",
                        "conjecture #conj-lean: open items must not cite Lean", "not a declaration GID: 'not-a-gid'",
                        "#1bad: ids use letters", 'viz embed needs src="…"', "definition needs an id",
                        "[@missing-ref] refers to no environment", "not a declaration GID: 'bad'"]
            for e in expected:
                self.assertTrue(any(e in x for x in msgs), f"{e!r} not in {msgs}")
            self.assertEqual(len(msgs), len(expected), msgs)

    def test_media_check_ref_is_consulted(self):
        with CoreRepo() as repo:
            book = repo.book(langs=("zh",), summaries={"zh": "- [A](a.md)\n"},
                             files={"zh": {"a.md": '::: {.film src="nope"}\n:::\n'}})
            m = model.load_edition(book.primary)
            fake = types.SimpleNamespace(check_ref=lambda b, src: f"no film {src}")
            with mock.patch.object(check.importlib, "import_module", return_value=fake):
                issues: list[model.Issue] = []
                check.check_env_policy(m, issues)
            self.assertEqual(messages(issues), ["no film nope"])

    def test_orphans(self):
        with CoreRepo() as repo:
            book = repo.book()
            write(book.edition("zh").dir / "notes.md", "orphan")
            m = model.load_edition(book.edition("zh"))
            issues: list[model.Issue] = []
            check.check_orphans(m, issues)
            self.assertEqual([(i.severity, i.path.name) for i in issues], [("warning", "notes.md")])

    def test_parity(self):
        with CoreRepo() as repo:
            book = repo.book()
            models = model.load_book_models(book)
            issues: list[model.Issue] = []
            check.check_parity(book, models, issues)
            self.assertEqual(issues, [], "the fixture editions agree")

            en_ch01 = book.edition("en").dir / "ch01.md"
            text = en_ch01.read_text(encoding="utf-8")
            en_ch01.write_text(text.replace("::: {.conjecture #conj-x}", "::: {.problem #conj-x}"), encoding="utf-8")
            issues = []
            check.check_parity(book, model.load_book_models(book), issues)
            self.assertEqual(messages(issues), ["item 4 differs between editions: zh has conjecture #conj-x, "
                                                "en has problem #conj-x"])
            en_ch01.write_text(text.replace(f'lean="{GID_DEF}"', f'lean="{GID_INT}"'), encoding="utf-8")
            issues = []
            check.check_parity(book, model.load_book_models(book), issues)
            self.assertIn(f"zh has definition #def-d lean={GID_DEF}, en has definition #def-d lean={GID_INT}",
                          messages(issues)[0])
            en_ch01.write_text(text, encoding="utf-8")

            summary_en = book.edition("en").summary
            s = summary_en.read_text(encoding="utf-8")
            summary_en.write_text(s.replace("- [Chapter 2](ch02.md)\n  - [Section 2.1](part/ch02-1.md)\n", ""),
                                  encoding="utf-8")
            issues = []
            check.check_parity(book, model.load_book_models(book), issues)
            self.assertIn("missing ch02.md, part/ch02-1.md", messages(issues)[0])
            summary_en.write_text(s.replace("[Appendix A](appendix-a.md)\n[Appendix B](appendix-b.md)",
                                            "[Appendix B](appendix-b.md)\n[Appendix A](appendix-a.md)"),
                                  encoding="utf-8")
            issues = []
            check.check_parity(book, model.load_book_models(book), issues)
            self.assertIn("same files in a different order", messages(issues)[0])

    def run_lean(self, lock, ledger_obj=None, offline=False):
        with mock.patch.object(lean, "Ledger", lambda repo, **kw: ledger_obj or FakeLedger()):
            book = config.load_book("demo")
            issues: list[model.Issue] = []
            check.check_lean({"demo": model.load_book_models(book)}, lock, config.load_site(), issues, offline=offline)
            return issues

    def test_lean_rules(self):
        with CoreRepo() as repo:
            repo.book()
            self.assertEqual(self.run_lean(make_lock()), [])
            self.assertEqual(messages(self.run_lean(None)), ["trureturing.lock.json is missing; run ./tbook pin"])
            msgs = messages(self.run_lean(make_lock(lock_decls(**{GID_INT: None}))))
            self.assertEqual(msgs, [f"{GID_INT} is not in trureturing.lock.json; run ./tbook pin --refresh"])
            as_def = dict(lock_decls()[GID_INT], kind="def")
            msgs = messages(self.run_lean(make_lock(lock_decls(**{GID_INT: as_def}))))
            self.assertIn(f"{GID_INT} is a Lean def, but theorem-like environments must cite theorems", msgs)
            self.assertTrue(any("lock says kind='def'" in x for x in msgs), msgs)
            msgs = messages(self.run_lean(make_lock(repo="someone/fork")))
            self.assertIn(f"lock pins someone/fork but site.toml uses {TRU}; run ./tbook pin", msgs)
            moved = dict(lock_decls()[GID_3V], statement_id="sha256:old")
            msgs = messages(self.run_lean(make_lock(lock_decls(**{GID_3V: moved}))))
            self.assertEqual(len(msgs), 1)
            self.assertIn("lock says statement_id='sha256:old'", msgs[0])
            self.assertIn("run ./tbook pin --refresh", msgs[0])
            issues = self.run_lean(make_lock(), FakeLedger(unreachable=True), offline=True)
            self.assertEqual({i.severity for i in issues}, {"warning"})
            self.assertTrue(all("not re-verified offline" in m for m in messages(issues)))
            issues = self.run_lean(make_lock(), FakeLedger(unreachable=True), offline=False)
            self.assertEqual({i.severity for i in issues}, {"error"})
            unfrozen = FakeLedger({MOD_3V: states()[MOD_3V], MOD_INT: None})
            msgs = messages(self.run_lean(make_lock(), unfrozen))
            self.assertTrue(msgs and all("is not frozen" in x for x in msgs), msgs)
            extra = lock_decls(**{"D5/S1/Old/Gone.x": {"module": "D5/S1/Old/Gone", "name": "x", "kind": "theorem"}})
            issues = self.run_lean(make_lock(extra))
            self.assertEqual([(i.severity, i.message) for i in issues],
                             [("warning", "D5/S1/Old/Gone.x is locked but no longer cited; ./tbook pin --refresh prunes it")])

    def test_run_end_to_end(self):
        with CoreRepo() as repo:
            book = repo.book()
            make_lock().save()
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()), \
                    mock.patch.object(check.importlib, "import_module", side_effect=media_stub):
                issues = check.run([book], offline=True)
                self.assertEqual([i.format() for i in issues], [])
                paths.LOCK_FILE.write_text("{not json", encoding="utf-8")
                issues = check.run([book], offline=True)
                self.assertTrue(any("unreadable lock" in m for m in messages(issues, "error")))
            make_lock().save()
            write(repo.root / "site.toml", SITE.replace('languages = ["zh", "en"]', 'languages = ["zh", "en", "fr"]'))
            config.load_site.cache_clear()
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()), \
                    mock.patch.object(check.importlib, "import_module", side_effect=media_stub):
                msgs = messages(check.run([book], offline=True))
            self.assertIn("no i18n table for 'fr': add i18n/fr.toml (copy theme/i18n/en.toml)", msgs)

    def test_cli_exit_codes(self):
        from tbook import cli

        with CoreRepo() as repo:
            repo.book()
            make_lock().save()
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()), \
                    mock.patch.object(check.importlib, "import_module", side_effect=media_stub), \
                    redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["check", "--offline"]), 0)
                self.assertIn("check: 1 book(s), 0 error(s), 0 warning(s)", out.getvalue())
                write(repo.root / "books" / "demo" / "zh" / "stray.md", "x")
                self.assertEqual(cli.main(["check", "--offline"]), 0)
                self.assertEqual(cli.main(["check", "--offline", "--strict"]), 1)
                os.environ["GITHUB_ACTIONS"] = "true"
                cli.main(["check", "--offline"])
                self.assertIn("::warning file=books/demo/zh/stray.md::", out.getvalue())


# --------------------------------------------------------------------------- pin


class PinTests(unittest.TestCase):
    SOURCES = {f"{MOD_3V}.lean": "namespace D5.S1.Deficit\n\ntheorem deficit_three_valued (v : Nat) : True := by\n  trivial\n"}

    def setUp(self):
        self.repo = CoreRepo().__enter__()
        self.repo.book()
        old = lean.Lock(repo=TRU, branch="dev", commit=OLD_COMMIT, pinned_at="2025-01-01T00:00:00Z", declarations={
            GID_3V: dict(lock_decls()[GID_3V], statement_id="sha256:old"),
            "D5/S1/Old/Gone.x": {"module": "D5/S1/Old/Gone", "name": "x", "kind": "theorem", "statement_id": "s"},
        })
        old.save()
        self.ledger = FakeLedger(sources=self.SOURCES)
        self.patch = mock.patch.object(lean, "Ledger", lambda r, **kw: self.ledger)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.repo.__exit__(None, None, None)

    def test_pin_new_commit(self):
        report = pin.pin(COMMIT, offline=True)
        self.assertTrue(report.written)
        self.assertEqual((report.commit, report.previous), (COMMIT, OLD_COMMIT))
        self.assertEqual(report.added, [GID_DEF, GID_INT])
        self.assertEqual(report.removed, ["D5/S1/Old/Gone.x"])
        self.assertEqual(report.changed, [(GID_3V, "module statement digest changed")])
        lock = lean.Lock.load()
        self.assertEqual(lock.commit, COMMIT)
        self.assertEqual(sorted(lock.declarations), sorted([GID_3V, GID_INT, GID_DEF]))
        res = lock.get(GID_3V)
        self.assertEqual((res.line, res.signature), (3, "theorem deficit_three_valued (v : Nat) : True"))
        self.assertNotEqual(lock.pinned_at, "2025-01-01T00:00:00Z")
        text = report.markdown()
        self.assertIn(f"trureturing pin: `{OLD_COMMIT[:12]}` → `{COMMIT[:12]}`", text)
        self.assertIn("**Changed — review the book text for these:**", text)
        self.assertIn(f"- `{GID_3V}`: module statement digest changed", text)
        self.assertIn("**Removed:**", text)

    def test_dry_run_and_errors_do_not_write(self):
        before = paths.LOCK_FILE.read_text(encoding="utf-8")
        report = pin.pin(COMMIT, offline=True, dry_run=True)
        self.assertFalse(report.written)
        self.assertEqual(report.added, [GID_DEF, GID_INT])
        self.assertEqual(paths.LOCK_FILE.read_text(encoding="utf-8"), before)
        self.ledger.states = {MOD_3V: states()[MOD_3V], MOD_INT: None}
        report = pin.pin(COMMIT, offline=True)
        self.assertFalse(report.written)
        self.assertEqual(len(report.errors), 2)
        self.assertIn("**Unresolved (lock not written):**", report.markdown())
        self.assertEqual(paths.LOCK_FILE.read_text(encoding="utf-8"), before)

    def test_refresh_and_offline_rules(self):
        report = pin.pin(refresh=True, offline=True)
        lock = lean.Lock.load()
        self.assertEqual((report.commit, lock.commit), (OLD_COMMIT, OLD_COMMIT))
        self.assertEqual(lock.pinned_at, "2025-01-01T00:00:00Z", "refresh keeps the pin time")
        report = pin.pin(refresh=True, offline=True)
        self.assertIn("No declaration changes.", report.markdown())
        with self.assertRaisesRegex(lean.LeanError, "--offline needs a full 40-hex commit"):
            pin.pin("dev", offline=True)
        paths.LOCK_FILE.unlink()
        with self.assertRaisesRegex(lean.LeanError, "nothing to refresh"):
            pin.pin(refresh=True, offline=True)
        self.assertEqual(pin.cited_gids(config.load_books()), sorted([GID_3V, GID_DEF, GID_INT]))


# --------------------------------------------------------------------------- theme


class ThemeTests(unittest.TestCase):
    def test_generators(self):
        tokens = theme.load_tokens()
        css = theme.css(tokens)
        self.assertTrue(css.startswith(f"/* {theme.HEADER} */\n:root {{"))
        for key in tokens["screen"]:
            self.assertIn(f"  --tr-{key}: ", css)
        self.assertIn('.tr-paper, [data-tr-palette="paper"] {', css)
        typ = theme.typst(tokens)
        self.assertIn("#let tr-screen = (", typ)
        self.assertIn("#let tr-fonts = (", typ)
        self.assertTrue(theme.js(tokens).startswith(f"// {theme.HEADER}\nexport const TOKENS = {{"))
        self.assertEqual(theme._typ_color("#00f0ff"), 'rgb("#00f0ff")')
        self.assertEqual(theme._typ_color("rgba(0, 240, 255, 0.35)"), "rgb(0, 240, 255, 35%)")
        self.assertEqual(theme._typ_color("rgb(1,2,3)"), "rgb(1, 2, 3, 100%)")
        with self.assertRaises(ValueError):
            theme._typ_color("hsl(1, 2%, 3%)")
        self.assertEqual(theme._css_font(["Chakra Petch", "Inter", "sans-serif"]),
                         '"Chakra Petch", "Inter", sans-serif')

    def test_stale_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = Path(tmp) / "generated"
            with mock.patch.object(paths, "GENERATED", gen):
                self.assertEqual(len(theme.stale_outputs()), 3)
                self.assertEqual(len(theme.write()), 3)
                self.assertEqual(theme.stale_outputs(), [])
                self.assertEqual(theme.write(), [], "writing is idempotent")
                (gen / "tokens.css").write_text("edited", encoding="utf-8")
                self.assertEqual(theme.stale_outputs(), [gen / "tokens.css"])


if __name__ == "__main__":
    unittest.main()
