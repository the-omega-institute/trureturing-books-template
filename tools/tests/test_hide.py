"""Tests of site.toml ``[books].hide``: books that every command and output treats as absent.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_hide.py'

A books repository keeps the template's example books and hides them (``hide = ["example-*"]``) instead of
deleting them, so that merging template changes never conflicts over deleted files. Every test builds its own
throwaway repository with its own site.toml: nothing here depends on this repository's site.toml or books.
The Node tests (tools/node/slides-lib.mjs, viz-common.mjs and the scripts that use them) are skipped without
node; the workflow steps that look for films and slide decks run in bash against a fake tree.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from fnmatch import fnmatchcase
from pathlib import Path
from unittest import mock

from tbook import buildcache, check, cli, config, doctor, lean, paths, pin, site
from test_core import COMMIT, GID_3V, GID_DEF, GID_INT, SITE, CoreRepo, FakeLedger, lock_decls, make_lock, media_stub
from test_template import copy_real_managed, run_release_plan

ROOT = paths.ROOT
NODE = shutil.which("node")
HIDE_SITE = SITE + 'hide = ["example-*"]\n'
# The error for naming the hidden book example-x (tools/tbook/config.py hidden_error, slides-lib.mjs hiddenError):
# unhiding alone does not bring back the declarations that a pin --refresh made while it was hidden dropped.
HIDDEN_MESSAGE = ('book example-x is hidden by site.toml [books].hide ("example-*"); to use it, remove that pattern '
                  "from hide, then run ./tbook pin --refresh (the lock file keeps only the declarations that visible "
                  "books cite)")
HIDDEN_GID = "D9/S9/Hidden/OnlyHere.claim"  # cited only by the hidden book; the fake ledger cannot resolve it
WORKFLOWS = ROOT / ".github" / "workflows"
SETUP_ACTION = ROOT / ".github" / "actions" / "setup" / "action.yml"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def hidden_book(repo: CoreRepo, slug: str = "example-x") -> config.Book:
    """A book with a problem in every check (a theorem citing a GID the lock lacks, editions that disagree,
    a stray chapter) and a citation that no ledger resolves: hiding it must silence all of that."""
    files = {
        "zh": {"ch01.md": f'# 一\n\n::: {{.theorem #thm-h lean="{HIDDEN_GID}"}}\nx\n:::\n\n::: {{.theorem #thm-bare}}\ny\n:::\n',
               "stray.md": "# stray\n"},
        "en": {"ch01.md": "# One\n"},
    }
    summaries = {"zh": "# Summary\n\n- [一](ch01.md)\n", "en": "# Summary\n\n- [One](ch01.md)\n- [Two](ch02.md)\n"}
    return repo.book(slug, files=files, summaries=summaries)


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- config


class ConfigTests(unittest.TestCase):
    def site_with(self, books_table: str) -> config.Site:
        """The Site of SITE with ``books_table`` in place of its [books] table (top-level keys go first)."""
        rest = SITE.split("[books]")[0]
        text = books_table + rest if not books_table.startswith("[") else rest + books_table
        with CoreRepo(text):
            return config.load_site()

    def test_parsing_and_validation(self):
        self.assertEqual(self.site_with("[books]\norder = []\n").book_hide, [], "absent: every book is shown")
        self.assertEqual(self.site_with("").book_hide, [], "no [books] table at all")
        self.assertEqual(self.site_with('[books]\nhide = ["example-*", "draft-?"]\n').book_hide, ["example-*", "draft-?"])
        for table, msg in (('[books]\nhide = "example-*"\n', r'\[books\]\.hide must be a list of glob patterns.*got "example-\*"'),
                           ("[books]\nhide = [1]\n", r"\[books\]\.hide entries must be non-empty strings.*got 1"),
                           ('[books]\nhide = [""]\n', r'\[books\]\.hide entries must be non-empty strings.*got ""'),
                           ('[books]\nhide = [["example-*"]]\n', r'\[books\]\.hide entries must be non-empty strings.*got \["example-\*"\]'),
                           ("books = 1\n", r"books must be a table")):
            with self.subTest(table=table), self.assertRaisesRegex(config.ConfigError, "site.toml: " + msg):
                self.site_with(table)

    def test_patterns_follow_fnmatchcase(self):
        s = self.site_with('[books]\nhide = ["example-*", "draft-?", "[!a-m]*-old", "Caps"]\n')
        for slug, by in (("example-monograph", "example-*"), ("example-", "example-*"), ("draft-1", "draft-?"),
                         ("draft-12", ""), ("zeta-old", "[!a-m]*-old"), ("alpha-old", ""), ("caps", ""),
                         ("my-example-book", ""), ("Example-x", "")):
            self.assertEqual(s.hidden_by(slug), by, slug)


class BookListTests(unittest.TestCase):
    def test_listing_naming_and_loading(self):
        with CoreRepo(HIDE_SITE) as repo:
            repo.book()
            hidden_book(repo)
            hidden_book(repo, "example-y")
            self.assertEqual(config.book_slugs(), ["demo"])
            self.assertEqual(config.hidden_books(), ["example-x", "example-y"])
            self.assertEqual([b.slug for b in config.load_books()], ["demo"])
            with self.assertRaises(config.ConfigError) as cm:
                config.load_books(["demo", "example-x"])
            self.assertEqual(str(cm.exception), HIDDEN_MESSAGE)
            with self.assertRaisesRegex(config.ConfigError, r"books example-x, example-y are hidden .*to use them, "
                                                            r"remove that pattern from hide, then run \./tbook pin --refresh"):
                config.load_books(["example-x", "example-y"])
            with self.assertRaisesRegex(config.ConfigError, "unknown book.*example-none; known: demo"):
                config.load_books(["example-none"])  # matches the pattern but does not exist: unknown, not hidden
            with self.assertRaisesRegex(config.ConfigError, "example-x is hidden"):
                config.named_book("example-x")
            self.assertEqual(config.named_book("demo").slug, "demo")
            # the loader itself loads any book (tests and the film pipeline load directories)
            self.assertEqual(config.load_book("example-x").slug, "example-x")
            self.assertEqual(config.named_book(repo.root / "books" / "example-x").slug, "example-x", "a path is not a name")

    def test_order_still_applies_and_unset_hide_shows_everything(self):
        with CoreRepo() as repo:  # [books] order = ["second", "demo"], no hide
            repo.book()
            hidden_book(repo)
            self.assertEqual(config.book_slugs(), ["demo", "example-x"])
            self.assertEqual(config.hidden_books(), [])


# --------------------------------------------------------------------------- commands


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.repo = CoreRepo(HIDE_SITE).__enter__()
        self.addCleanup(self.repo.__exit__, None, None, None)
        self.repo.book()
        hidden_book(self.repo)
        make_lock().save()

    def test_check_skips_hidden_books_and_says_so(self):
        with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()), \
                mock.patch.object(check.importlib, "import_module", side_effect=media_stub):
            code, out, err = run_cli("check", "--offline")
            self.assertEqual(code, 0, out + err)
            self.assertIn("check: hidden by site.toml [books].hide, not checked: example-x\n", out)
            self.assertTrue(out.endswith("check: 1 book(s), 0 error(s), 0 warning(s)\n"), out)
            self.assertNotIn("warning", out.replace("0 warning(s)", ""), "an informational line, not a warning")
            code, out, err = run_cli("check", "--offline", "--book", "example-x")
            self.assertEqual(code, 2)
            self.assertIn("tbook: book example-x is hidden by site.toml [books].hide", err)
            # shown again, the same book fails the check
            write(paths.SITE_TOML, SITE)
            config.load_site.cache_clear()
            code, out, err = run_cli("check", "--offline")
            self.assertEqual(code, 1, out + err)
            self.assertIn(HIDDEN_GID, out)
            self.assertNotIn("hidden by", out)

    def test_named_hidden_books_are_errors(self):
        for argv in (("build", "html", "--book", "example-x"), ("cache", "status", "--book", "example-x"),
                     ("new-chapter", "example-x", "ch02", "--title", "zh=二", "--title", "en=Two")):
            code, out, err = run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("example-x is hidden by site.toml [books].hide", err, argv)
        self.assertFalse((self.repo.root / "books" / "example-x" / "zh" / "ch02.md").exists())
        for argv in (("viz", "new", "example-x", "v1", "V//ONE", "一"), ("film", "new", "example-x", "001-a", "一", "One"),
                     ("slides", "list", "example-x"), ("film", "list", "example-x")):
            code, out, err = run_cli(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("example-x is hidden", err, argv)
        self.assertFalse((self.repo.root / "books" / "example-x" / "viz").exists())
        self.assertFalse((self.repo.root / "books" / "example-x" / "films").exists())

    def test_new_book_warns_when_hidden(self):
        code, out, err = run_cli("new-book", "example-new", "--title", "zh=示例", "--title", "en=Example")
        self.assertEqual(code, 0, err)
        self.assertIn("created books/example-new", out)
        self.assertIn('warning: example-new matches "example-*" in site.toml [books].hide', err)
        self.assertTrue((self.repo.root / "books" / "example-new" / "book.toml").is_file())
        code, out, err = run_cli("new-book", "plain", "--title", "zh=书", "--title", "en=Book")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(config.book_slugs(), ["demo", "plain"])

    def test_books_command(self):
        self.assertEqual(run_cli("books")[1], "demo\n")
        self.assertEqual(run_cli("books", "--hidden")[1], "example-x\n")
        self.assertEqual(run_cli("books", "--files", "*/ch01.md")[1], "books/demo/en/ch01.md\nbooks/demo/zh/ch01.md\n")
        self.assertEqual(run_cli("books", "--hidden", "--files", "zh/*.md")[1],
                         "books/example-x/zh/SUMMARY.md\nbooks/example-x/zh/ch01.md\nbooks/example-x/zh/stray.md\n")
        self.assertEqual(run_cli("books", "--files", "films/*/film.json")[1], "", "nothing matches: no output")

    def test_books_command_needs_only_the_standard_library(self):
        """The setup action runs it on the runner's python3, before any package is installed."""
        r = subprocess.run([sys.executable, "-S", "-m", "tbook", "books", "--hidden"], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=str(ROOT / "tools"), TBOOK_ROOT=str(self.repo.root)))
        self.assertEqual((r.returncode, r.stdout), (0, "example-x\n"), r.stderr)

    def test_build_units_and_site_skip_hidden_books(self):
        names = [u.name for u in buildcache.units(config.load_site(), config.load_books())]
        self.assertTrue(names and all(n.startswith("demo/") for n in names), names)
        out = self.repo.root / "_site"
        for slug in ("demo", "example-x"):
            (out / slug).mkdir(parents=True)  # a media-only rebuild keeps the books already published …
        self.assertEqual([b.slug for b in site._site_books([], out)], ["demo"], "… except hidden ones")

    def test_site_builds_remove_hidden_books(self):
        """A book hidden after the site was built: a media-only rebuild (`./tbook build viz`) does not empty
        _site/, so it removes the book's pages itself, and nothing else."""
        out = paths.SITE_OUT
        for slug in ("demo", "example-x"):
            write(out / slug / "zh" / "index.html", "published before")
        write(out / "manifest.json", "{}")
        write(out / "notes" / "keep.txt", "not a book")
        with mock.patch.object(site, "_media_module", lambda part: None), mock.patch.object(site, "_warn") as warn:
            site.build(config.load_site(), config.load_books(), out, only={"viz"})
        self.assertFalse((out / "example-x").exists())
        self.assertTrue((out / "demo" / "zh" / "index.html").is_file())
        self.assertTrue((out / "notes" / "keep.txt").is_file())
        self.assertNotIn("example-x", (out / "index.html").read_text(encoding="utf-8"))
        warn.assert_any_call("removed the pages of example-x (hidden by site.toml [books].hide)")
        self.assertEqual(site._remove_hidden_books(out, set()), [], "nothing left to remove")
        (out / "example-x").symlink_to(out / "notes", target_is_directory=True)
        self.assertEqual(site._remove_hidden_books(out, set()), ["example-x"])
        self.assertTrue((out / "notes" / "keep.txt").is_file(), "a link is removed, not what it points at")
        self.assertFalse((out / "example-x").is_symlink())

    def test_doctor_names_hidden_books(self):
        self.assertEqual(doctor.books_line(), "books: demo; hidden by site.toml [books].hide: example-x")
        write(paths.SITE_TOML, SITE)
        config.load_site.cache_clear()
        self.assertEqual(doctor.books_line(), "books: demo, example-x")


class PinTests(unittest.TestCase):
    def test_hidden_examples_with_a_stripped_lock_keep_unit_tests_runnable(self):
        """The downstream state after hiding both examples and pinning another commit."""
        with CoreRepo(HIDE_SITE) as repo:
            for name in ("tools", "templates", "theme", "node_modules"):
                if (ROOT / name).exists():
                    (repo.root / name).symlink_to(ROOT / name, target_is_directory=True)
            for slug in ("example-monograph", "example-primer"):
                repo.book(slug)
            write(repo.root / "books/example-monograph/slides/overview/slides.md", "# Overview\n")
            lock = make_lock({})
            lock.commit = "4c76e4a56525afbb474bf04a03ee2ff4aec5da45"
            lock.save()
            self.assertEqual(lean.Lock.load().declarations, {})
            self.assertEqual(config.book_slugs(), [])
            tests = [
                "test_film.ExampleFilmTest.test_example_cites_locked_theorems",
                "test_viz.Links.test_pin_links",
                "test_slides.ExampleDeckTest.test_cited_gids_are_locked",
                "test_film.ValidationTest.test_lean_must_cite_theorems",
                "test_viz.Scaffold.test_scaffold_creates_a_valid_draft",
                "test_slides.FirstLanguageTest.test_english_first_book",
            ]
            env = dict(os.environ, TBOOK_ROOT=str(repo.root), PYTHONPATH=os.pathsep.join(
                str(ROOT / p) for p in ("tools", "tools/tests")))
            r = subprocess.run([sys.executable, "-m", "unittest", "-v", *tests], cwd=repo.root,
                               env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Ran 6 tests", r.stderr)
            self.assertIn("OK (skipped=3)", r.stderr)

    def test_refresh_collects_visible_books_only(self):
        with CoreRepo(HIDE_SITE) as repo:
            repo.book()
            hidden_book(repo)
            decls = lock_decls(**{HIDDEN_GID: {"module": "D9/S9/Hidden/OnlyHere", "name": "D9.S9.Hidden.claim",
                                               "kind": "theorem", "statement_id": "sha256:h"}})
            make_lock(decls).save()
            ledger = FakeLedger()
            with mock.patch.object(lean, "Ledger", lambda r, **kw: ledger):
                self.assertEqual(pin.cited_gids(config.load_books()), sorted([GID_3V, GID_DEF, GID_INT]))
                report = pin.pin(refresh=True, offline=True)
            self.assertEqual((report.errors, report.refused), ([], ""), report.markdown())
            self.assertEqual(report.removed, [HIDDEN_GID], "only the hidden book cited it")
            self.assertEqual(sorted(lean.Lock.load().declarations), sorted([GID_3V, GID_DEF, GID_INT]))
            self.assertEqual(lean.Lock.load().commit, COMMIT)


# --------------------------------------------------------------------------- release plan


class ReleasePlanTests(unittest.TestCase):
    """release.yml's plan: a tag naming a hidden book fails and says why; v* releases leave hidden books out."""

    def test_hidden_books_are_not_released(self):
        tmp = Path(tempfile.mkdtemp(prefix="tbook-hide-release-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        root = tmp / "repo"
        root.mkdir()
        copy_real_managed(root, example=False)
        (root / "site.toml").write_text(SITE.replace('order = ["second", "demo"]', "order = []")
                                        + 'hide = ["example-*"]\n', encoding="utf-8")
        env = dict(os.environ, TBOOK_PYTHON=sys.executable)
        env.pop("TBOOK_ROOT", None)
        for slug, title in (("example-a", "Example"), ("my-book", "Mine")):
            r = subprocess.run([str(root / "tbook"), "new-book", slug, "--title", f"zh={title}", "--title", f"en={title}"],
                               cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual("[books].hide" in r.stderr, slug == "example-a", r.stderr)
        rc, outputs, log = run_release_plan(root, "example-a-v0.1.0")
        self.assertEqual(rc, 1, log)
        self.assertIn("tag example-a-v0.1.0 names books/example-a, but book example-a is hidden by site.toml "
                      "[books].hide", log)
        rc, outputs, log = run_release_plan(root, "v2026.11.08")
        self.assertEqual((rc, outputs.get("books")), (0, "my-book"), log)
        rc, outputs, log = run_release_plan(root, "my-book-v0.1.0")
        self.assertEqual((rc, outputs.get("books")), (0, "my-book"), log)


# --------------------------------------------------------------------------- workflow steps


def step_script(path: Path, name: str) -> str:
    """The ``run: |`` script of the step called ``name`` in a workflow or action file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if re.fullmatch(rf"\s*- name: {re.escape(name)}", ln))
    indent = len(lines[start]) - len(lines[start].lstrip()) + 2
    run = next(i for i in range(start + 1, len(lines)) if lines[i].startswith(" " * indent + "run: |"))
    body = []
    for ln in lines[run + 1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) <= indent:
            break
        body.append(ln)
    return textwrap.dedent("\n".join(body)) + "\n"


class WorkflowStepTests(unittest.TestCase):
    """.github/actions/setup "Find films" and ci.yml "Find slide decks" ignore hidden books."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="tbook-hide-steps-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copy2(ROOT / "tbook", self.root / "tbook")
        shutil.copytree(ROOT / "tools" / "tbook", self.root / "tools" / "tbook",
                        ignore=shutil.ignore_patterns("__pycache__"))
        for slug in ("my-book", "example-a"):
            write(self.root / "books" / slug / "book.toml", f'[book]\ntitle = "{slug}"\n')
        write(self.root / "books" / "example-a" / "films" / "001-x" / "film.json", "{}")
        write(self.root / "books" / "example-a" / "slides" / "intro" / "slides.md", "# x\n")

    def site(self, hide: str | None) -> None:
        text = '[site]\nlanguages = ["zh", "en"]\n\n[books]\n' + (f"hide = {hide}\n" if hide is not None else "")
        (self.root / "site.toml").write_text(text, encoding="utf-8")

    def run_step(self, path: Path, name: str, **env: str) -> tuple[dict[str, str], str]:
        out = self.root / "github-output.txt"
        out.write_text("", encoding="utf-8")
        full = {k: v for k, v in os.environ.items() if k not in ("TBOOK_ROOT", "PYTHONPATH")}
        full.update({"GITHUB_OUTPUT": str(out), "TBOOK_PYTHON": sys.executable, **env})
        r = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step_script(path, name)],
                           cwd=self.root, env=full, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return dict(ln.split("=", 1) for ln in out.read_text(encoding="utf-8").splitlines()), r.stdout

    def films(self, **env: str) -> str:
        return self.run_step(SETUP_ACTION, "Find films", **{"WANTED": "true", **env})[0]["install"]

    def decks(self) -> str:
        return self.run_step(WORKFLOWS / "ci.yml", "Find slide decks")[0]["present"]

    def test_find_films(self):
        self.site(None)
        self.assertEqual(self.films(), "true")
        self.assertEqual(self.films(WANTED="false"), "false")
        self.site('["example-*"]')
        self.assertEqual(self.films(), "false")
        _, log = self.run_step(SETUP_ACTION, "Find films", WANTED="true")
        self.assertIn("No film", log)
        write(self.root / "books" / "my-book" / "films" / "002-y" / "film.json", "{}")
        self.assertEqual(self.films(), "true")

    def test_find_films_falls_back_to_every_book(self):
        """Without a Python that runs ./tbook (older than 3.11, say), every book counts: the toolchain is
        installed rather than missing."""
        self.site('["example-*"]')
        self.assertEqual(self.films(TBOOK_PYTHON="false"), "true")

    def test_find_slide_decks(self):
        self.site("[]")
        self.assertEqual(self.decks(), "true")
        self.site('["example-*"]')
        self.assertEqual(self.decks(), "false")
        write(self.root / "books" / "my-book" / "slides" / "talk" / "slides.md", "# t\n")
        self.assertEqual(self.decks(), "true")


# --------------------------------------------------------------------------- Node


def node_eval(root: Path, code: str, stdin: str = "") -> subprocess.CompletedProcess:
    lib = (ROOT / "tools" / "node").as_uri()
    code = code.replace("@LIB@", lib)
    return subprocess.run([NODE, "--input-type=module", "-e", code], input=stdin, capture_output=True, text=True,
                          cwd=root, env=dict(os.environ, TBOOK_ROOT=str(root)), timeout=120)


def fnmatch_cases() -> list[tuple[str, str]]:
    """Slugs and patterns, including the corners of Python's pattern language."""
    patterns = ["example-*", "*", "?", "*-old", "draft-??", "[a-c]*", "[!a-c]*", "[z-a]*", "[!z-a]", "[]a]*", "[!]a]*",
                "[a-c-e]", "[-a]", "[a-]", "[!-]", "[", "[]", "[!]", "a[", "[[]", "[\\]", "[^a]*", "*[0-9]", "ex*-?",
                "a\\b", "(x)", "a+", "a{1}", "$x^", "a.b", "*.*", "**-*", "[x-yz-w]", "[a&&b]", "[a||b]"]
    slugs = ["example-monograph", "example-", "example", "Example-x", "my-book", "draft-01", "draft-1", "a", "b", "z",
             "-", "]", "[", "^", "\\", "a\\b", "(x)", "a{1}", "aa", "$x^", "a.b", "ab", "zeta-old", "x-9", ""]
    rng = random.Random(20261109)
    alphabet = "ab-!]^[\\*?z."
    patterns += ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 6))) for _ in range(300)]
    slugs += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 5))) for _ in range(40)]
    return [(s, p) for p in patterns for s in slugs]


@unittest.skipUnless(NODE, "node not available")
class NodeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="tbook-hide-node-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("theme", "templates", "tools", "node_modules"):
            if (ROOT / name).exists():
                (self.root / name).symlink_to(ROOT / name)
        write(self.root / "site.toml", '[site]\nlanguages = ["zh", "en"]\n\n[books]\nhide = ["example-*"]\n')
        write(self.root / "books" / "demo" / "book.toml", '[book]\ntitle = "Demo"\neditions = ["zh", "en"]\n')
        hidden = self.root / "books" / "example-x"
        write(hidden / "book.toml", '[book]\ntitle = "Hidden"\neditions = ["zh", "en"]\n')
        write(hidden / "viz" / "visualizations.json", "{ not json")
        write(hidden / "viz" / "tests" / "broken.test.mjs", "process.exit(1);\n")
        write(hidden / "slides" / "deck" / "slides.md", "---\ntitle: x\n---\n\n# no English edition\n")

    def node(self, script: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([NODE, str(ROOT / "tools" / "node" / script), *args], capture_output=True, text=True,
                              cwd=self.root, env=dict(os.environ, TBOOK_ROOT=str(self.root)), timeout=120)

    def test_patterns_agree_with_python(self):
        cases = fnmatch_cases()
        r = node_eval(self.root, """
            import { fnmatchcase } from '@LIB@/slides-lib.mjs';
            let s = ''; process.stdin.on('data', (d) => { s += d; }).on('end', () => {
              process.stdout.write(JSON.stringify(JSON.parse(s).map(([n, p]) => fnmatchcase(n, p))));
            });""", json.dumps(cases))
        self.assertEqual(r.returncode, 0, r.stderr)
        node = json.loads(r.stdout)
        wrong = [(s, p, py) for (s, p), py, js in zip(cases, (fnmatchcase(s, p) for s, p in cases), node) if py != js]
        self.assertEqual(wrong, [], "fnmatchcase(slug, pattern) differs between Python and Node")

    def test_listing_and_naming(self):
        r = node_eval(self.root, """
            import * as S from '@LIB@/slides-lib.mjs';
            import * as V from '@LIB@/viz-common.mjs';
            import { route } from '@LIB@/viz-server.mjs';
            const error = (fn) => { try { fn(); return ''; } catch (e) { return e.message; } };
            console.log(JSON.stringify({
              slides: S.listBooks().map((b) => b.slug), hidden: S.hiddenBooks(), decks: S.booksWithDecks().map((b) => b.slug),
              viz: V.listBooks().map((b) => b.slug), isBook: [V.isBook('demo'), V.isBook('example-x')],
              byPath: V.resolveBook(process.cwd() + '/books/example-x').slug,
              errors: [error(() => S.booksWithDecks(['example-x'])), error(() => S.namedBook('example-x')),
                       error(() => V.resolveBook('example-x'))],
              unknown: error(() => V.resolveBook('example-none')),
              routes: [route('/site/demo/viz/'), route('/site/example-x/viz/'), route('/site/example-x/viz/assets/theme.css')],
            }));""")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["errors"], [HIDDEN_MESSAGE] * 3)
        with CoreRepo(HIDE_SITE.replace('"second", "demo"', "")) as repo:  # Python says the same
            hidden_book(repo)
            self.assertEqual(str(config.hidden_error(["example-x"])), HIDDEN_MESSAGE)
        self.assertEqual((got["slides"], got["hidden"], got["decks"], got["viz"], got["isBook"], got["byPath"]),
                         (["demo"], ["example-x"], [], ["demo"], [True, False], "example-x"))
        self.assertIn('no book "example-none"', got["unknown"])
        self.assertEqual(got["routes"], [{"hub": "demo"}, None, None])

    def test_hidden_error_agrees_with_python(self):
        """One or several books, hidden by one or several patterns: the same text from Python and Node."""
        hide = ["example-*", "draft-?"]
        cases = [["example-x"], ["example-x", "example-y"], ["example-x", "draft-1"]]
        r = node_eval(self.root, """
            import { hiddenError } from '@LIB@/slides-lib.mjs';
            console.log(JSON.stringify(@CASES@.map((slugs) => hiddenError(slugs, @HIDE@).message)));"""
                      .replace("@CASES@", json.dumps(cases)).replace("@HIDE@", json.dumps(hide)))
        self.assertEqual(r.returncode, 0, r.stderr)
        node = json.loads(r.stdout)
        with CoreRepo(SITE + f"hide = {json.dumps(hide)}\n"):
            self.assertEqual(node, [str(config.hidden_error(slugs)) for slugs in cases])
        self.assertIn("books example-x, draft-1 are hidden by site.toml [books].hide (\"example-*\", \"draft-?\"); "
                      "to use them, remove those patterns from hide, then run ./tbook pin --refresh", node[2])

    def test_unhide_hint_agrees_with_python(self):
        """A "not in trureturing.lock.json" message about a hidden book read by path says why pin --refresh cannot
        help yet; the same text from Python and Node, and nothing for a visible book."""
        hide = ["example-*"]
        write(self.root / "site.toml", SITE + f"hide = {json.dumps(hide)}\n")
        r = node_eval(self.root, """
            import { unhideHint } from '@LIB@/slides-lib.mjs';
            console.log(JSON.stringify([unhideHint('example-x'), unhideHint('my-book')]));""")
        self.assertEqual(r.returncode, 0, r.stderr)
        node = json.loads(r.stdout)
        with CoreRepo(SITE + f"hide = {json.dumps(hide)}\n"):
            self.assertEqual(node, [config.unhide_hint("example-x"), config.unhide_hint("my-book")])
        self.assertEqual(node[1], "")
        self.assertIn('book example-x is hidden by site.toml [books].hide "example-*"', node[0])
        self.assertIn("pin --refresh collects the citations of visible books only", node[0])

    def test_validation_agrees_with_python(self):
        for text in ('[site]\n[books]\nhide = "example-*"\n', "[site]\n[books]\nhide = [1]\n",
                     '[site]\n[books]\nhide = [""]\n', "books = 1\n[site]\n", "[[books]]\nhide = []\n[site]\n"):
            with self.subTest(text=text):
                write(self.root / "site.toml", text)
                r = node_eval(self.root, "import { hidePatterns } from '@LIB@/slides-lib.mjs';\n"
                                         "try { hidePatterns(); } catch (e) { console.log(e.message); }")
                with CoreRepo(text), self.assertRaises(config.ConfigError) as cm:
                    config.load_site()
                self.assertEqual(r.stdout.strip(), str(cm.exception))

    def test_scripts_skip_hidden_books(self):
        r = self.node("viz-validate.mjs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("viz-validate: 1 book(s)", r.stdout)
        r = self.node("viz-validate.mjs", "example-x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("example-x is hidden by site.toml [books].hide", r.stderr)
        r = self.node("viz-validate.mjs", str(self.root / "books" / "example-x"))
        self.assertEqual(r.returncode, 1, "a directory path is not a name: the hidden book is validated")
        r = self.node("viz-test.mjs", "--list")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), r.stderr)
        if (ROOT / "node_modules" / "@slidev" / "parser").is_dir():
            r = self.node("slides-check.mjs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 deck(s)", r.stdout)
            r = self.node("slides-check.mjs", "--book", "example-x")
            self.assertEqual(r.returncode, 2)
            self.assertIn("slides-check: book example-x is hidden by site.toml [books].hide", r.stderr)


if __name__ == "__main__":
    unittest.main()
