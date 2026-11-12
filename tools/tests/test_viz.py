"""Tests for tbook.viz (book-local visualizations) and its Node counterparts in tools/node/viz-*.mjs.

Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_viz.py'
Node-dependent tests are skipped when ``node`` is not on PATH. The browser suites of the books are not run here (see
tools/node/viz-test.mjs); this file covers the registry checks, embeds, the publish step and scaffolding, and, where
Playwright's Chromium is installed, the rail and keys parts of the shared quality gate on private copies of the starter
page.
"""

from __future__ import annotations

import html.parser
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from example_support import example_shown

from tbook import config, lean, mdscan, paths, render, viz
from tbook.model import load_edition

NODE = viz.node_executable()
EXAMPLE = paths.BOOKS / "example-monograph"
GID3 = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"
GIDI = "D5/S1/Deficit/DeficitInteger.deficit_integer"
GIDDEF = "D5/S1/Deficit/DeficitInteger.deficit"  # a Lean def
# every theorem the example page cites, in the order of its registry entry
EXAMPLE_GIDS = [
    GID3, GIDI,
    "D5/S1/Deficit/GoldenPhaseDeficit.golden_phase_deficit",
    "D5/S1/Deficit/ChargedCarryPath.deficit_eq_beattyDeficit",
    "D5/S1/Words/Expansions/BasePhiNegativeBridge.betaContraction_mem_window",
    "D5/S1/Deficit/DoubleFaceLength.betaReal_sub_betaContraction",
    "D5/S1/Deficit/GoldenPhaseDistribution.limiting_deficit_distribution",
    "D5/S1/Digit/Addition.zeck_add",
]
# Downstream repositories may delete the example book (skills/book-new); tests built on it skip then.
needs_example = unittest.skipUnless(EXAMPLE.is_dir(), "books/example-monograph is absent")
needs_listed_example = unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden")


def example_book():
    return config.load_book("example-monograph")


def fake_lock() -> lean.Lock:
    """A lock with the theorems of the example page and one definition (independent of the repository's lock)."""
    def decl(gid: str, kind: str) -> dict:
        module, name = gid.rsplit(".", 1)
        return {"module": module, "name": "D5.S1.Deficit." + name, "kind": kind, "statement_id": "sha256:x", "line": 7}

    return lean.Lock(repo="the-omega-institute/trureturing", branch="dev", commit="a" * 40,
                     declarations={**{g: decl(g, "theorem") for g in EXAMPLE_GIDS}, GIDDEF: decl(GIDDEF, "def")})


def fake_book(root: Path, slug: str = "tbook-viz-fixture"):
    """A book-like object living in a temporary directory (viz functions only need these attributes)."""
    bdir = root / slug
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "book.toml").write_text('[book]\ntitle = { zh = "测试", en = "Test" }\neditions = ["zh", "en"]\n', encoding="utf-8")
    return SimpleNamespace(slug=slug, dir=bdir, viz_dir=bdir / "viz", languages=["zh", "en"],
                           title={"zh": "测试", "en": "Test"}, code="TEST//BOOK", license="CC-BY-4.0")


def copy_golden_carry(book) -> None:
    """Copy the example page and registry, with an independent validation-only suite."""
    src = EXAMPLE / "viz"
    for lang in ("zh", "en"):  # the drawer links to chapter 1 of each edition
        (book.dir / lang).mkdir(exist_ok=True)
        (book.dir / lang / "ch01-golden-deficit.md").write_text("# 1\n", encoding="utf-8")
    shutil.copytree(src / "golden-carry", book.viz_dir / "golden-carry")
    # a downstream copy of the example may predate .nummark: its readout ticks are the page's own checks either way
    script = book.viz_dir / "golden-carry" / "main.js"
    script.write_text(script.read_text(encoding="utf-8").replace('class="okmark"', 'class="nummark"'), encoding="utf-8")
    (book.viz_dir / "tests").mkdir(parents=True, exist_ok=True)
    # Downstream example books are not managed and may retain an older browser
    # suite. Registry fixtures do not execute it; browser behaviour is checked
    # separately by viz-test.mjs against the real book.
    (book.viz_dir / "tests" / "golden-carry.test.mjs").write_text(
        "// Registry fixture: browser behaviour is checked separately.\nexport {};\n", encoding="utf-8")
    reg = json.loads((src / "visualizations.json").read_text(encoding="utf-8"))
    reg["visualizations"] = [v for v in reg["visualizations"] if v["id"] == "golden-carry"]   # the one page copied
    # the chapter link of the example points into its own editions; keep the fixture self-contained
    for ref in reg["visualizations"][0]["theory"]:
        if not ref["href"].startswith("{trureturing}"):
            ref["href"], ref["href_en"] = "https://example.org/zh", "https://example.org/en"
    write_registry(book, reg)


def write_registry(book, reg: dict) -> None:
    book.viz_dir.mkdir(parents=True, exist_ok=True)
    (book.viz_dir / "visualizations.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def messages(issues) -> list[str]:
    return [i.message for i in issues]


class RegistryChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))
        self.lock = fake_lock()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @needs_example
    @needs_listed_example
    def test_example_book_is_clean(self):
        issues = viz.check(example_book())
        self.assertEqual([i.format() for i in issues if i.severity == "error"], [])
        self.assertEqual([i.format() for i in issues], [])

    def test_no_viz_dir_means_nothing_to_check(self):
        book = fake_book(self.tmp)
        self.assertEqual(viz.check(book), [])
        self.assertEqual(viz.items(book), [])

    def test_viz_dir_without_registry(self):
        book = fake_book(self.tmp)
        book.viz_dir.mkdir()
        msgs = messages(viz.check_native(book, lock=self.lock))
        self.assertTrue(any("no visualizations.json" in m for m in msgs), msgs)

    def test_invalid_json_reports_the_line(self):
        book = fake_book(self.tmp)
        book.viz_dir.mkdir()
        (book.viz_dir / "visualizations.json").write_text('{\n  "version": 1,\n  oops\n}\n', encoding="utf-8")
        issues = viz.check_native(book, lock=self.lock)
        self.assertEqual(len(issues), 1)
        self.assertIn(":3: not valid JSON", issues[0].message)

    @needs_example
    def test_copied_fixture_is_clean(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        self.assertEqual([i.format() for i in viz.check_native(book, lock=self.lock)], [])

    def broken_book(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        reg = json.loads((book.viz_dir / "visualizations.json").read_text(encoding="utf-8"))
        good = reg["visualizations"][0]
        reg["visualizations"] += [
            dict(good, id="golden-carry"),  # duplicate
            {"id": "Bad_Id", "code": "X", "title": "x", "path": "x/", "thumbnail": "x/t.jpg", "status": "maybe",
             "added": "2026/01/01", "theory": [], "lean": [{"gid": "not a gid"}]},
            {"id": "half", "code": "HALF//DONE", "title": "半成品", "title_en": "", "summary": "", "summary_en": "",
             "path": "half/", "thumbnail": "half/thumb.jpg", "status": "live", "added": "2026-11-08",
             "tags": ["一", "二"], "tags_en": ["one"],
             "theory": [{"label": "无英文", "href": "http://insecure.example.org"},
                        {"label": "绝对", "label_en": "absolute", "href": "/zh/ch01.html"}],
             "lean": [{"gid": "D5/S1/Nowhere/Missing.thing"}]},
        ]
        write_registry(book, reg)
        half = book.viz_dir / "half"
        half.mkdir()
        page = (EXAMPLE / "viz" / "golden-carry" / "index.html").read_text(encoding="utf-8")
        page = page.replace('data-viz-id="golden-carry"', 'data-viz-id="half"')
        page = page.replace('<span class="en">The pair</span>', "", 1)  # break zh/en parity
        page = page.replace('href="../assets/theme.css"', 'href="/assets/theme.css"')
        page = page.replace(f'data-lean-gid="{GIDI}"', 'data-lean-gid="D5/S1/Nowhere/Missing.thing"', 1)
        (half / "index.html").write_text(page, encoding="utf-8")
        (book.viz_dir / "stray").mkdir()
        suite = book.viz_dir / "tests" / "golden-carry.test.mjs"
        suite.write_text(suite.read_text(encoding="utf-8") + "await page.waitForTimeout(300);\n", encoding="utf-8")
        return book

    @needs_example
    def test_broken_registry_and_pages(self):
        book = self.broken_book()
        msgs = messages(viz.check_native(book, lock=self.lock))
        expect = [
            "duplicate id",
            "id must be kebab-case",
            "status must be one of live, draft",
            "added must be YYYY-MM-DD",
            "not a declaration GID: not a gid",
            'a live entry needs "title_en"',
            'a live entry needs "summary"',
            "tags_en must translate every tag",
            'theory reference "无英文" needs label_en',
            "must use https",
            'root-absolute link "/zh/ch01.html"',
            "D5/S1/Nowhere/Missing.thing is not in trureturing.lock.json",
            "thumbnail does not exist",
            ".zh fragments but",
            'loads the shared theme (expected href="../assets/theme.css")',
            'data-lean-gid="D5/S1/Nowhere/Missing.thing" is not in trureturing.lock.json',
            "viz/stray/ is not registered",
            "should have a browser test tests/half.test.mjs",
            "waits a fixed time",
        ]
        for e in expect:
            self.assertTrue(any(e in m for m in msgs), f"missing problem {e!r} in:\n" + "\n".join(msgs))

    def test_fixed_waits(self):
        text = ("await settle(page, 400);\n"
                "check('plays', await until(page, () => window.D.t > 0));\n"
                "// never page.waitForTimeout(300) in a suite\n"
                " * a doc comment may name waitForTimeout(…) too\n"
                "await pick('x'); await page.waitForTimeout(400); await thumb.waitForTimeout (50);\n"
                "const waitForTimeoutish = 1;\n")
        self.assertEqual(viz.fixed_waits(text), [5, 5])
        self.assertEqual(viz.fixed_waits("await settle(page);\n"), [])

    @needs_example
    def test_fixed_waits_in_suites_are_warned(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        suite = book.viz_dir / "tests" / "golden-carry.test.mjs"
        clean = suite.read_text(encoding="utf-8")
        self.assertEqual([i for i in viz.check_native(book, lock=self.lock) if "fixed time" in i.message], [])
        suite.write_text(clean + "// page.waitForTimeout(300) is how not to wait\nawait page.waitForTimeout(300);\n",
                         encoding="utf-8")
        line = clean.count("\n") + 2
        found = [i for i in viz.check_native(book, lock=self.lock) if "fixed time" in i.message]
        self.assertEqual([(i.severity, i.path.name, i.line) for i in found], [("warning", suite.name, line)])
        self.assertIn(f"at line {line} waits a fixed time", found[0].message)
        self.assertIn("settle(page)", found[0].message)
        self.assertIn("until(page", found[0].message)
        if NODE:
            r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-validate.mjs"), "--json", "--only=tests", str(book.dir)],
                               capture_output=True, text=True, cwd=paths.ROOT, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            node = [(p["severity"], p["message"]) for p in json.loads(r.stdout) if "fixed time" in p["message"]]
            self.assertEqual(node, [("warning", found[0].message)])

    def test_okmarks_outside_lean_boxes(self):
        page = ('<html><body>\n'
                '<!-- <span class="okmark">a comment</span> -->\n'
                '<div class="lean"><a data-lean-gid="x">T</a> <span class="okmark">✓</span><b id="inBox"></b></div>\n'
                '<dl class="ro"><dd id="roKey"></dd><dd><span class="okmark">✓</span></dd></dl>\n'
                '<div class="lean num"><img src="a.png"><br><span id="numBox"></span></div>\n'
                '<script>const s = "<span class=\\"okmark\\">";</script>\n'
                '</body></html>\n')
        js = ("$('inBox').innerHTML = '<span class=\"okmark\">✓</span>';\n"
              "$('roKey').innerHTML = `${x} <span class=\"okmark\">✓</span>`;\n"
              "set(3, 'sum', `${s} <span class=\"okmark\">✓</span>`);\n"
              "// <span class=\"okmark\"> in a comment\n"
              "document.getElementById('numBox').innerHTML = '<span class=\"okmark\">✓</span>';\n"
              "$('roKey').innerHTML = `${x} <span class=\"nummark\">✓</span>`;\n")
        self.assertEqual(viz.okmarks_outside_lean(page, js), [("index.html", 4), ("main.js", 2), ("main.js", 3)],
                         "inside any .lean box (also .lean.num) a tick is fine; a readout, a helper or a comment is not a box")
        self.assertIn(".nummark", viz.okmark_message("main.js", 2))
        if NODE:
            code = ("import { okmarksOutsideLean } from './tools/node/viz-validate.mjs';"
                    f"console.log(JSON.stringify(okmarksOutsideLean({json.dumps(page)}, {json.dumps(js)})));")
            r = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, cwd=paths.ROOT, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([(o["where"], o["line"]) for o in json.loads(r.stdout.strip().splitlines()[-1])],
                             [("index.html", 4), ("main.js", 2), ("main.js", 3)], "the Node twin agrees")

    @needs_example
    def test_okmarks_in_pages_are_warned(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        script = book.viz_dir / "golden-carry" / "main.js"
        self.assertEqual([i for i in viz.check_native(book, lock=self.lock) if "okmark" in i.message], [])
        text = script.read_text(encoding="utf-8")
        script.write_text(text.replace('class="nummark"', 'class="okmark"', 1), encoding="utf-8")
        found = [i for i in viz.check_native(book, lock=self.lock) if "okmark" in i.message]
        self.assertEqual([(i.severity, i.path.name) for i in found], [("warning", "main.js")])
        line = text[:text.index('class="nummark"')].count("\n") + 1
        self.assertEqual(found[0].line, line)
        if NODE:
            r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-validate.mjs"), "--json", "--only=lean", str(book.dir)],
                               capture_output=True, text=True, cwd=paths.ROOT, timeout=120)
            node = [(p["severity"], p["message"]) for p in json.loads(r.stdout) if "okmark" in p["message"]]
            self.assertEqual(node, [("warning", found[0].message)])

    @needs_example
    def test_registry_line_numbers(self):
        book = self.broken_book()
        issues = viz.check_native(book, lock=self.lock)
        dup = next(i for i in issues if "half" in i.message and "summary" in i.message)
        text = (book.viz_dir / "visualizations.json").read_text(encoding="utf-8")
        self.assertIn('"id": "half"', text.splitlines()[dup.line - 1])

    @needs_example
    @unittest.skipUnless(NODE, "node not available")
    @needs_listed_example
    def test_node_validator_agrees_with_python(self):
        book = self.broken_book()
        # messages name files relative to the repository (Node) or absolutely (Python, outside the repo)
        norm = lambda m: re.sub(r"\((?:/|\.\./)[^)]*\)", "(…)", m)  # noqa: E731
        py = {(i.severity, norm(i.message)) for i in viz.check_native(book, lock=self.lock)}
        r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-validate.mjs"), "--json", str(book.dir)],
                           capture_output=True, text=True, cwd=paths.ROOT, timeout=120)
        self.assertEqual(r.returncode, 1, r.stderr)
        node = {(p["severity"], norm(p["message"])) for p in json.loads(r.stdout)}
        self.assertEqual(py - node, set(), "Python reports problems Node does not")
        self.assertEqual(node - py, set(), "Node reports problems Python does not")

    @needs_example
    @unittest.skipUnless(NODE, "node not available")
    @needs_listed_example
    def test_node_validator_passes_the_example(self):
        r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-validate.mjs"), str(EXAMPLE)],
                           capture_output=True, text=True, cwd=paths.ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 error(s)", r.stdout)

    @needs_example
    @unittest.skipUnless(NODE, "node not available")
    def test_javascript_syntax_errors_are_reported_through_node(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        (book.viz_dir / "golden-carry" / "main.js").write_text("(() => { const = 1; })();\n", encoding="utf-8")
        issues = viz.check_scripts(book)
        self.assertTrue(any(i.severity == "error" and "does not parse" in i.message and i.path.name == "main.js"
                            for i in issues), [i.format() for i in issues])

    @needs_example
    @unittest.skipUnless(lean.Ledger("the-omega-institute/trureturing", offline=True).sources[0].__class__.__name__ == "GitSource",
                         "needs a local trureturing checkout (TRURETURING_DIR or ../trureturing)")
    @needs_listed_example
    def test_trureturing_paths_must_exist_at_the_pinned_commit(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        reg = json.loads((book.viz_dir / "visualizations.json").read_text(encoding="utf-8"))
        reg["visualizations"][0]["theory"][1]["href"] = "{trureturing}/Blueprint/D5/Nope.md"
        write_registry(book, reg)
        page = book.viz_dir / "golden-carry" / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace('data-trureturing-path="D5/S1/Digit/Normalize.lean"',
                                                                 'data-trureturing-path="D5/S1/Digit/Nope.lean"'), encoding="utf-8")
        msgs = messages(viz.check(book))
        self.assertTrue(any("Blueprint/D5/Nope.md does not exist in trureturing at the pinned commit" in m for m in msgs), msgs)
        self.assertTrue(any('data-trureturing-path="D5/S1/Digit/Nope.lean" does not exist' in m for m in msgs), msgs)

    @needs_example
    def test_cited_gids(self):
        gids = {g for _, _, g in viz.cited_gids(example_book())}
        self.assertEqual(gids, set(EXAMPLE_GIDS))


@unittest.skipUnless(NODE, "node not available")
class NodeToolsWithoutVisualizations(unittest.TestCase):
    """A books repository without visualizations (or without the example book): the Node tools are no-ops."""

    def test_validate_and_test_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {**os.environ, "TBOOK_ROOT": str(root)}
            for books in (False, True):  # no books/ at all, then a book without viz/
                if books:
                    fake_book(root / "books", "plain-book")
                for script, args in (("viz-validate.mjs", []), ("viz-test.mjs", []), ("viz-test.mjs", ["--shard", "2/3"])):
                    r = subprocess.run([NODE, str(paths.TOOLS / "node" / script), *args], capture_output=True, text=True,
                                       cwd=root, env=env, timeout=120)
                    self.assertEqual(r.returncode, 0, f"{script} {args} (books={books}): {r.stdout}{r.stderr}")
            self.assertIn("0 error(s)", subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-validate.mjs")], capture_output=True,
                                                       text=True, cwd=root, env=env, timeout=120).stdout)


@unittest.skipUnless(NODE, "node not available")
class NodeSuiteRunner(unittest.TestCase):
    """tools/node/viz-test.mjs runs each suite in a child process; --slow hands it VIZ_SLOW_FRAMES=1000."""

    def run_suites(self, *args, env_extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = fake_book(root / "books", "plain-book")
            (book.viz_dir / "tests").mkdir(parents=True)
            (book.viz_dir / "tests" / "probe.test.mjs").write_text(
                "console.log(`frames=${process.env.VIZ_SLOW_FRAMES || 'none'}`);\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "VIZ_SLOW_FRAMES"}
            env.update(TBOOK_ROOT=str(root), **(env_extra or {}))
            return subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-test.mjs"), *args], capture_output=True,
                                  text=True, cwd=root, env=env, timeout=120)

    def test_slow_sets_slow_frames(self):
        r = self.run_suites("--slow")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("frames=1000", r.stdout)
        self.assertIn("1/1 suites passed, with slow frames (1000 ms)", r.stdout)

    def test_without_slow_frames_are_not_slowed(self):
        r = self.run_suites()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("frames=none", r.stdout)
        self.assertNotIn("slow frames", r.stdout)

    def test_slow_frames_from_the_environment_are_kept(self):
        r = self.run_suites(env_extra={"VIZ_SLOW_FRAMES": "250"})
        self.assertIn("frames=250", r.stdout)
        self.assertIn("with slow frames (250 ms)", r.stdout)

    def test_help_names_slow(self):
        r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-test.mjs"), "--help"], capture_output=True, text=True,
                           timeout=60)
        self.assertIn("[--slow]", r.stdout)


class TheoremCitations(unittest.TestCase):
    """LEAN ✓ belongs to theorems only: the registry ``lean`` and page ``data-lean-gid`` must name theorems."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))
        self.lock = fake_lock()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def book_citing(self, *gids: str):
        book = fake_book(self.tmp / "books")
        viz.scaffold(book, "fib-walk", "FIB//WALK", "斐波那契行走", "Fibonacci walk", added="2026-11-08")
        reg = json.loads((book.viz_dir / "visualizations.json").read_text(encoding="utf-8"))
        reg["visualizations"][0]["lean"] = [{"gid": g} for g in gids]
        write_registry(book, reg)
        page = book.viz_dir / "fib-walk" / "index.html"
        links = "".join(f'<a data-lean-gid="{g}" href="#">{g}</a>' for g in gids)
        page.write_text(page.read_text(encoding="utf-8").replace("</body>", f"<p>{links}</p>\n</body>"), encoding="utf-8")
        return book

    def kind_errors(self, issues) -> list[str]:
        return sorted(i.message for i in issues if i.severity == "error" and "not a theorem" in i.message)

    def test_definitions_are_refused(self):
        book = self.book_citing(GID3, GIDDEF)
        issues = viz.check_native(book, lock=self.lock)
        self.assertEqual(self.kind_errors(issues), sorted([
            f'data-lean-gid="{GIDDEF}" names a Lean def, not a theorem; data-lean-gid cites verified theorems (LEAN ✓); '
            'link a definition with data-trureturing-path="<module>.lean"',
            f"visualizations[0] (fib-walk): lean[1]: {GIDDEF} is a Lean def, not a theorem; lean lists the theorems "
            "the visualization cites (shown as LEAN ✓)",
        ]))
        self.assertEqual([i.format() for i in issues if i.severity == "error" and GID3 in i.message], [])

    def test_theorems_pass(self):
        issues = viz.check_native(self.book_citing(GID3, GIDI), lock=self.lock)
        self.assertEqual([i.format() for i in issues if i.severity == "error"], [])

    @unittest.skipUnless(NODE, "node not available")
    def test_node_validator_refuses_definitions_too(self):
        book = self.book_citing(GID3, GIDDEF)
        self.lock.save(self.tmp / "trureturing.lock.json")
        r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-validate.mjs"), "--json", "--only=lean", str(book.dir)],
                           capture_output=True, text=True, cwd=paths.ROOT, timeout=120,
                           env={**os.environ, "TBOOK_ROOT": str(self.tmp)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        node = sorted(p["message"] for p in json.loads(r.stdout) if "not a theorem" in p["message"])
        self.assertEqual(node, self.kind_errors(viz.check_native(book, lock=self.lock)))

    def test_hub_card_marks_only_theorems_verified(self):
        v = {"id": "fib-walk", "code": "FIB//WALK", "title": "斐波那契", "title_en": "Fib", "summary": "s",
             "summary_en": "s", "lean": [{"gid": GID3}, {"gid": GIDDEF}]}
        card = viz._card(v, self.lock, False)
        self.assertEqual(card.count('<span class="k ok">LEAN ✓</span>'), 1)
        self.assertIn('<span class="k">LEAN</span><a href="https://github.com/the-omega-institute/trureturing/blob/'
                      + "a" * 40 + '/D5/S1/Deficit/DeficitInteger.lean#L7"', card)
        self.assertEqual([r["kind"] for r in viz.lean_refs(v, self.lock)], ["theorem", "def"])


class CheckRef(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @needs_example
    def test_local_and_external(self):
        book = example_book()
        self.assertIsNone(viz.check_ref(book, "golden-carry"))
        self.assertIsNone(viz.check_ref(book, "trureturing-visualize:robin-lattice"))
        self.assertIn("not registered", viz.check_ref(book, "no-such-viz"))
        self.assertIn("trureturing-visualize:<id>", viz.check_ref(book, "trureturing-visualize:Bad Id"))
        self.assertIn("expected the id", viz.check_ref(book, "../escape"))

    @needs_example
    def test_draft_cannot_be_embedded(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        reg = json.loads((book.viz_dir / "visualizations.json").read_text(encoding="utf-8"))
        reg["visualizations"][0]["status"] = "draft"
        write_registry(book, reg)
        self.assertIn("is a draft", viz.check_ref(book, "golden-carry"))

    def test_book_without_viz(self):
        self.assertIn("does not exist", viz.check_ref(fake_book(self.tmp), "golden-carry"))


@needs_example
class CitedCards(unittest.TestCase):
    """``::: {.viz src=… preset=…}``: a chapter cites one experiment card of a visualization."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))
        self.book = fake_book(self.tmp)
        copy_golden_carry(self.book)
        page = self.book.viz_dir / "golden-carry" / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace(
            "</body>", '<button class="preset" data-preset="demo"></button><button data-preset="second-card"></button></body>'),
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ctx(self, lang: str, target: str):
        return SimpleNamespace(site=config.load_site(), book=self.book, lang=lang, target=target, issues=[],
                               book_files=set(), book_prefix="_book")

    def _still(self, card: str, lang: str) -> Path:
        f = self.book.viz_dir / "golden-carry" / viz.still_name(card, lang)
        f.write_bytes(b"jpg")
        return f

    def test_page_presets(self):
        cards = viz.page_presets(self.book, "golden-carry")
        self.assertEqual(cards[-2:], ["demo", "second-card"])
        self.assertEqual(viz.page_presets(self.book, "no-such-page"), [])

    def test_check_preset(self):
        book = self.book
        self.assertIsNone(viz.check_preset(book, "golden-carry", "demo"))
        missing = viz.check_preset(book, "golden-carry", "demo", "zh")
        self.assertIn("fig-demo.zh.jpg", missing)
        self.assertIn("viz-thumbs.mjs", missing)
        self._still("demo", "zh")
        self.assertIsNone(viz.check_preset(book, "golden-carry", "demo", "zh"))
        self.assertIn("fig-demo.en.jpg", viz.check_preset(book, "golden-carry", "demo", "en"))  # one still per edition
        unknown = viz.check_preset(book, "golden-carry", "nope")
        self.assertIn('no experiment card data-preset="nope"', unknown)
        self.assertIn("demo, second-card", unknown)
        self.assertIn("not a card name", viz.check_preset(book, "golden-carry", "a b"))
        self.assertIn("not a card name", viz.check_preset(book, "golden-carry", ""))
        self.assertIn("not a card name", viz.check_preset(book, "golden-carry", "1,1"))  # card names are identifiers
        self.assertIsNone(viz.check_preset(book, "trureturing-visualize:zeno-watch", "itano", "zh"))  # not on disk

    def test_mdbook_figure_opens_the_cited_card(self):
        ctx = self._ctx("en", "mdbook")
        out = viz.render_embed(_env(src="golden-carry", preset="demo", height="480"), ctx, "Caption.", _doc("part/ch.md"))
        self.assertIn('<figure class="tr-media tr-viz" data-viz="golden-carry" data-preset="demo">', out)
        self.assertIn('src="../../viz/golden-carry/index.html?embed=1&amp;lang=en&amp;preset=demo" '
                      'data-tr-src="viz/golden-carry/index.html?embed=1&amp;lang=en&amp;preset=demo"', out)
        self.assertIn('href="../../viz/golden-carry/index.html?lang=en&amp;preset=demo"', out)  # full screen, same card
        self.assertEqual(ctx.issues, [])

    def test_mdbook_without_preset_is_unchanged(self):
        ctx = self._ctx("zh", "mdbook")
        out = viz.render_embed(_env(src="golden-carry"), ctx, "", _doc("ch.md"))
        self.assertIn('<figure class="tr-media tr-viz" data-viz="golden-carry">', out)
        self.assertNotIn("preset", out)

    def test_unknown_card_is_reported_and_not_linked(self):
        ctx = self._ctx("zh", "mdbook")
        out = viz.render_embed(_env(src="golden-carry", preset="nope"), ctx, "", _doc("ch.md"))
        self.assertNotIn("preset", out)
        self.assertTrue(any('data-preset="nope"' in m for m in ctx.issues), ctx.issues)

    def test_pandoc_shows_the_still_of_the_edition(self):
        still = self._still("demo", "zh")
        ctx = self._ctx("zh", "pandoc")
        out = viz.render_embed(_env(src="golden-carry", preset="demo"), ctx, "图注。", _doc("ch.md"))
        self.assertIn("](_book/viz/golden-carry/fig-demo.zh.jpg){width=100%}", out)
        self.assertEqual(ctx.book_files, {still.resolve()})
        self.assertEqual(ctx.issues, [])
        # the English edition has no still yet: the cover is shown and the build says how to capture one
        ctx = self._ctx("en", "pandoc")
        out = viz.render_embed(_env(src="golden-carry", preset="demo"), ctx, "", _doc("ch.md"))
        self.assertIn("](_book/viz/golden-carry/thumb.jpg){width=100%}", out)
        self.assertTrue(any("fig-demo.en.jpg" in m and "viz-thumbs.mjs" in m for m in ctx.issues), ctx.issues)

    def test_stills_are_not_published_with_the_site(self):
        names = ["index.html", "thumb.jpg", "fig-demo.zh.jpg", "fig-demo.en.jpg", ".DS_Store", "figure.jpg"]
        self.assertEqual(viz._ignore("x", names), ["fig-demo.zh.jpg", "fig-demo.en.jpg", ".DS_Store"])

    def test_editions_must_cite_the_same_card(self):
        from tbook import check

        def model(preset):
            kv = {"src": "golden-carry"} | ({"preset": preset} if preset else {})
            media = [SimpleNamespace(kind="viz", attrs=mdscan.Attrs(classes=["viz"], kv=kv))]
            return SimpleNamespace(chapters=[SimpleNamespace(chapter=SimpleNamespace(path="ch.md"), envs=[], media=media)])

        self.assertEqual(check._env_signature(model("demo")), [("ch.md", [("viz", "golden-carry", ("demo",))])])
        self.assertEqual(check._env_signature(model(None)), [("ch.md", [("viz", "golden-carry", ())])])
        self.assertNotEqual(check._env_signature(model("demo")), check._env_signature(model("second-card")))


# The chapters of a book as the builds read them (tbook.model.load_edition), with embeds of golden-carry in every
# accepted attribute form, embeds no build shows, and Markdown no SUMMARY.md publishes.
CITING_ZH = r"""# 一

正文。

::: {.viz src='golden-carry' preset='single' height='480px'}
单引号。
:::

正文。

::: {.viz src=golden-carry preset=bare height=620}
不加引号。
:::

正文。

::: {.viz src="golden-carry" title="$\{0,1\}^n$" preset="braces" height="450"}
引号里的花括号。
:::

```markdown
::: {.viz src="golden-carry" preset="code-only"}
:::
```

<!--
::: {.viz src="golden-carry" preset="comment-only"}
:::
-->

    ::: {.viz src="golden-carry" preset="indented-only"}
    :::

- 列表项

  ::: {.viz src="golden-carry" preset="list-only"}
  :::

正文 `::: {.viz src="golden-carry" preset="inline-only"}`。

::: {.figure .viz src="golden-carry" preset="figure-first"}
:::

::: {.viz-like src="golden-carry" preset="lookalike"}
:::

::: {.viz src="other-viz" preset="other"}
:::

::: {.viz src="trureturing-visualize:golden-carry" preset="external"}
:::

::: {.callout .viz src=" golden-carry " preset=" spaced " height="0x200"}
:::

::: {.remark #rem-a}
::: {.viz src="golden-carry" preset="a b" height="5e2"}
:::
:::

::: {.viz src="golden-carry" height="100"}
:::
"""


def citing_book(root: Path):
    """A book (book.toml editions zh, en) whose published chapters cite golden-carry; see CITING_ZH."""
    book = fake_book(root)
    files = {
        "zh/SUMMARY.md": "# 目录\n\n- [前言](z-first.md)\n- [一](ch01.md)\n- [草稿]()\n",
        "zh/z-first.md": '# 前言\n\n::: {.viz src="golden-carry" preset="first" height="300"}\n:::\n',
        "zh/ch01.md": CITING_ZH,
        "zh/unlisted.md": '# 未列出\n\n::: {.viz src="golden-carry" preset="unlisted"}\n:::\n',
        "zh/drafts/later.md": '# 草稿\n\n::: {.viz src="golden-carry" preset="draft"}\n:::\n',
        "en/SUMMARY.md": "# Contents\n\n- [Preface](z-first.md)\n- [One](ch01.md)\n",
        "en/z-first.md": '# Preface\n\n::: {.viz src="golden-carry" preset="first"}\n:::\n',
        "en/ch01.md": '# One\n\n::: {.viz src="golden-carry" preset="single" height="500"}\n:::\n',
        # a language directory that book.toml does not list as an edition is not published
        "fr/SUMMARY.md": "# Sommaire\n\n- [Un](ch01.md)\n",
        "fr/ch01.md": '# Un\n\n::: {.viz src="golden-carry" preset="french"}\n:::\n',
    }
    for name, text in files.items():
        (book.dir / name).parent.mkdir(parents=True, exist_ok=True)
        (book.dir / name).write_text(text, encoding="utf-8")
    return book


# editions in book.toml order, chapters in SUMMARY.md order, embeds in document order
CITED = [
    {"lang": "zh", "preset": "first", "height": 300},
    {"lang": "zh", "preset": "single", "height": 480},
    {"lang": "zh", "preset": "bare", "height": 620},
    {"lang": "zh", "preset": "braces", "height": 450},
    {"lang": "zh", "preset": "spaced", "height": 560},  # src and preset as the build strips them; 0x200 is no number
    {"lang": "zh", "preset": None, "height": 560},  # "a b" is no card name; 5e2 is no number of pixels
    {"lang": "zh", "preset": None, "height": 560},  # the whole lab; 100 is outside 160–2400
    {"lang": "en", "preset": "first", "height": 560},
    {"lang": "en", "preset": "single", "height": 500},
]


class Citations(unittest.TestCase):
    """viz.citations, and vizCitations / citedCards of tools/node/viz-common.mjs that return it to the browser quality
    gate (stageFirstChecks) and to viz-thumbs.mjs: the embeds of the published chapters, read as the builds read them."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))
        self.book = citing_book(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def node(self, viz_id: str = "golden-carry", **env: str) -> subprocess.CompletedProcess:
        script = ("import { vizCitations, citedCards, resolveBook } from './tools/node/viz-common.mjs';"
                  "const [dir, id] = process.argv.slice(1), book = resolveBook(dir);"
                  "process.stdout.write(JSON.stringify({ citations: vizCitations(book, id), cards: citedCards(book, id) }));")
        return subprocess.run([NODE, "--input-type=module", "-e", script, str(self.book.dir), viz_id],
                              capture_output=True, text=True, cwd=paths.ROOT, timeout=120,
                              env={**os.environ, "TBOOK_PYTHON": sys.executable, **env})

    def test_the_published_embeds(self):
        book = config.load_book(self.book.dir)
        self.assertEqual(viz.citations(book, "golden-carry"), CITED)
        self.assertEqual(viz.citations(book, "other-viz"), [{"lang": "zh", "preset": "other", "height": 560}])
        self.assertEqual(viz.citations(book, "no-such-viz"), [])

    def test_the_builds_read_the_same_blocks(self):
        """Every embed of the edition model is a citation or is not a viz of golden-carry; nothing else is."""
        book = config.load_book(self.book.dir)
        media = [(e.kind, e.attrs.get("src").strip(), e.attrs.get("preset").strip())
                 for ch in load_edition(book.edition("zh")).chapters for e in ch.media]
        self.assertEqual([p for k, s, p in media if k == "viz" and s == "golden-carry"],
                         ["first", "single", "bare", "braces", "spaced", "a b", ""])
        self.assertIn(("figure", "golden-carry", "figure-first"), media)  # the first kind class names the kind

    def test_an_edition_whose_chapters_cannot_be_selected_is_an_error(self):
        (self.book.dir / "en" / "SUMMARY.md").unlink()
        with self.assertRaisesRegex(viz.VizError, "cannot read the chapters of tbook-viz-fixture/en: .*SUMMARY.md is missing"):
            viz.citations(config.load_book(self.book.dir), "golden-carry")
        (self.book.dir / "en" / "SUMMARY.md").write_text("# Contents\n\n- [Gone](gone.md)\n", encoding="utf-8")
        with self.assertRaisesRegex(viz.VizError, "chapter file not found: gone.md"):
            viz.citations(config.load_book(self.book.dir), "golden-carry")
        (self.book.dir / "en" / "SUMMARY.md").write_text("# Contents\n\n- [x\n", encoding="utf-8")
        with self.assertRaisesRegex(viz.VizError, r"SUMMARY.md:3: list items must be links"):
            viz.citations(config.load_book(self.book.dir), "golden-carry")

    def test_an_edition_without_a_directory_has_no_text_to_cite(self):
        shutil.rmtree(self.book.dir / "en")  # e.g. a book of visualizations only, as the quality-gate fixtures are
        self.assertEqual(viz.citations(config.load_book(self.book.dir), "golden-carry"),
                         [c for c in CITED if c["lang"] == "zh"])

    @unittest.skipUnless(NODE, "node not available")
    def test_node_returns_the_published_embeds(self):
        r = self.node()
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["citations"], CITED)
        self.assertEqual(got["cards"], [{"preset": p, "lang": lang} for lang, p in (
            ("zh", "first"), ("zh", "single"), ("zh", "bare"), ("zh", "braces"), ("zh", "spaced"), ("en", "first"),
            ("en", "single"))])

    @unittest.skipUnless(NODE, "node not available")
    def test_node_fails_rather_than_cite_nothing(self):
        r = self.node(TBOOK_PYTHON=str(self.tmp / "no-python"))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertIn('cannot read the citations of viz "golden-carry"', r.stderr)
        self.assertIn("ENOENT", r.stderr)
        (self.book.dir / "zh" / "SUMMARY.md").unlink()
        r = self.node()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertIn("SUMMARY.md is missing", r.stderr)


class Links(unittest.TestCase):
    @needs_example
    @needs_listed_example
    def test_pin_links(self):
        lock = lean.Lock.load()
        html_in = (f'<p><a class="x" data-lean-gid="{GID3}" href="https://old/link">a</a> '
                   f'<a data-trureturing-path="Blueprint/X.md">b</a> <a href="keep.html">c</a></p>')
        out = viz.pin_links(html_in, lock)
        self.assertIn(f'href="{lock.source_url(GID3)}"', out)
        self.assertIn(f'<a href="https://github.com/{lock.repo}/blob/{lock.commit}/Blueprint/X.md" data-trureturing-path', out)
        self.assertIn('<a href="keep.html">c</a>', out)
        self.assertNotIn("https://old/link", out)
        self.assertEqual(viz.pin_links(html_in, None), html_in)
        self.assertTrue(lock.source_url(GID3).endswith("DeficitThreeValued.lean#L264"))

    @needs_example
    @unittest.skipUnless(NODE, "node not available")
    @needs_listed_example
    def test_node_pin_links_is_identical(self):
        lock = lean.Lock.load()
        page = (EXAMPLE / "viz" / "golden-carry" / "index.html").read_text(encoding="utf-8")
        page = page.replace(lock.commit, "0" * 40)  # make the rewrite observable
        script = ("import { pinLinks, readLock } from './tools/node/viz-common.mjs';"
                  "process.stdin.setEncoding('utf8');let s='';process.stdin.on('data',d=>s+=d).on('end',()=>process.stdout.write(pinLinks(s, readLock())));")
        r = subprocess.run([NODE, "--input-type=module", "-e", script], input=page, capture_output=True, text=True,
                           cwd=paths.ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, viz.pin_links(page, lock))
        self.assertNotIn("0" * 40, r.stdout)

    @needs_example
    def test_link_problem(self):
        book = example_book()
        ok = ["../", "../assets/theme.css", "../assets/tokens.css", "style.css", "thumb.jpg",
              "../../zh/ch01-golden-deficit.html#thm-deficit-integer", "https://x.org", "#a", "../golden-carry/"]
        for url in ok:
            self.assertIsNone(viz.link_problem(book, "viz/golden-carry/", url, {"golden-carry"}), url)
        self.assertIn("root-absolute", viz.link_problem(book, "viz/golden-carry/", "/x.css", None))
        self.assertIn("leaves the published book", viz.link_problem(book, "viz/golden-carry/", "../../../x", None))
        self.assertIn("not part of the shared runtime", viz.link_problem(book, "viz/golden-carry/", "../assets/nope.js", None))
        self.assertIn("chapter that does not exist", viz.link_problem(book, "viz/", "../zh/nope.html", None))
        self.assertIn("not registered", viz.link_problem(book, "viz/golden-carry/", "../other/", {"golden-carry"}))
        self.assertIsNone(viz.link_problem(book, "viz/", "../en/ch01-golden-deficit.html", None))

    def test_resolve_href(self):
        lock = lean.Lock.load()
        self.assertEqual(viz.resolve_href("{trureturing}/Blueprint/A.md", lock), lock.blob("Blueprint/A.md"))
        self.assertEqual(viz.resolve_href("https://x.org", lock), "https://x.org")


def _ctx(book, lang: str, target: str, site=None):
    site = site or config.load_site()
    ed = book.edition(lang)
    return render.RenderContext(site=site, book=book, edition=ed, model=None, lock=lean.Lock.load(), target=target)


def _env(**kv):
    return SimpleNamespace(attrs=mdscan.Attrs(classes=["viz"], kv=kv))


def _doc(path: str):
    return SimpleNamespace(chapter=SimpleNamespace(path=path), path=Path(path))


@needs_example
@needs_listed_example
class Embeds(unittest.TestCase):
    def test_mdbook_iframe(self):
        book = example_book()
        ctx = _ctx(book, "zh", "mdbook")
        out = viz.render_embed(_env(src="golden-carry", height="480"), ctx, "图注 *强调*。", _doc("ch01-golden-deficit.md"))
        self.assertIn('<figure class="tr-media tr-viz" data-viz="golden-carry">', out)
        self.assertIn('src="../viz/golden-carry/index.html?embed=1&amp;lang=zh"', out)
        self.assertIn('loading="lazy"', out)
        self.assertIn('height="480"', out)
        self.assertIn('<figcaption class="tr-media-caption">\n\n图注 *强调*。\n\n<div class="tr-media-links">', out)
        self.assertIn('href="../viz/golden-carry/index.html?lang=zh"', out)
        self.assertIn(config.s("zh", "ui.open_fullscreen"), out)
        self.assertEqual(ctx.issues, [])

    def test_mdbook_nested_chapter_and_english(self):
        book = example_book()
        ctx = _ctx(book, "en", "mdbook")
        out = viz.render_embed(_env(src="golden-carry"), ctx, "", _doc("part/sub/ch.md"))
        self.assertIn('src="../../../viz/golden-carry/index.html?embed=1&amp;lang=en" '
                      'data-tr-src="viz/golden-carry/index.html?embed=1&amp;lang=en"', out)  # for print.html
        self.assertIn(f'height="{viz.DEFAULT_HEIGHT}"', out)
        self.assertIn("Golden carry · the carry deficit", out)  # caption falls back to the English title
        self.assertIn(config.s("en", "ui.open_fullscreen"), out)

    def test_mdbook_bad_height(self):
        ctx = _ctx(example_book(), "zh", "mdbook")
        out = viz.render_embed(_env(src="golden-carry", height="tall"), ctx, "", _doc("a.md"))
        self.assertIn(f'height="{viz.DEFAULT_HEIGHT}"', out)
        self.assertTrue(any("height must be" in m for m in ctx.issues))

    def test_mdbook_external(self):
        ctx = _ctx(example_book(), "en", "mdbook")
        out = viz.render_embed(_env(src="trureturing-visualize:robin-lattice"), ctx, "", _doc("a.md"))
        self.assertIn(f'src="{viz.EXTERNAL_BASE}robin-lattice/?embed=1&amp;lang=en"', out)
        self.assertNotIn("data-tr-src", out)  # absolute: nothing to repair in print.html
        self.assertIn(f'href="{viz.EXTERNAL_BASE}robin-lattice/?lang=en"', out)

    def test_pandoc_card_with_base_url(self):
        book = example_book()
        site = config.load_site()
        site = SimpleNamespace(**{**site.__dict__, "base_url": "https://books.example.org/"})
        site.book_url = lambda slug, *parts: config.Site.book_url(site, slug, *parts)
        ctx = _ctx(book, "en", "pandoc", site=site)
        out = viz.render_embed(_env(src="golden-carry"), ctx, "Caption.", _doc("ch01-golden-deficit.md"))
        self.assertTrue(out.startswith("::: {.tr-media .tr-viz}\n"))
        self.assertIn("](_book/viz/golden-carry/thumb.jpg){width=100%}", out)
        self.assertIn("\n\nCaption.\n\n", out)
        self.assertIn(config.s("en", "ui.viz_static_note") + "\\\n<https://books.example.org/example-monograph/viz/golden-carry/>", out)
        self.assertEqual(ctx.book_files, {(EXAMPLE / "viz" / "golden-carry" / "thumb.jpg").resolve()})

    def test_pandoc_card_without_base_url_and_nested(self):
        book = example_book()
        site = config.load_site()
        site = SimpleNamespace(**{**site.__dict__, "base_url": ""})
        site.book_url = lambda slug, *parts: config.Site.book_url(site, slug, *parts)
        ctx = _ctx(book, "zh", "pandoc", site=site)
        out = viz.render_embed(_env(src="golden-carry"), ctx, "", _doc("part/ch.md"))
        self.assertIn("](../_book/viz/golden-carry/thumb.jpg)", out)
        self.assertIn(config.s("zh", "ui.viz_static_note") + "\\\n`example-monograph/viz/golden-carry/`", out)

    def test_pandoc_external_is_a_text_card(self):
        ctx = _ctx(example_book(), "zh", "pandoc")
        out = viz.render_embed(_env(src="trureturing-visualize:robin-lattice"), ctx, "", _doc("a.md"))
        self.assertNotIn("![", out)
        self.assertIn(f"<{viz.EXTERNAL_BASE}robin-lattice/>", out)
        self.assertEqual(ctx.book_files, set())

    def test_render_pipeline_uses_render_embed(self):
        """The example's chapter-1 viz block, through tbook.render for both targets."""
        tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))
        try:
            bdir = tmp / "viz-pipeline"
            shutil.copytree(EXAMPLE, bdir, ignore=shutil.ignore_patterns("tests"))
            book = config.load_book(bdir)
            for lang in ("zh", "en"):
                model = load_edition(book.edition(lang))
                doc = next(d for d in model.chapters if d.chapter.path == "ch01-golden-deficit.md")
                cited = [(m.attrs.get("src"), m.attrs.get("preset")) for m in doc.media if m.kind == "viz"]
                # cards cited where the text talks about them (the phase torus after the phase square), then the
                # whole lab at the end of the chapter
                self.assertEqual(cited, [("golden-carry", "window"), ("golden-carry", "cancel"), ("phase-torus", "torus"),
                                         ("golden-carry", "map"), ("golden-carry", "fill"), ("golden-carry", "")])
                ctx = render.RenderContext(config.load_site(), book, book.edition(lang), model, lean.Lock.load(), "mdbook",
                                           env_href=render.mdbook_env_href(model))
                html_md = render.chapter_markdown(doc, ctx)
                self.assertIn(f'src="../viz/golden-carry/index.html?embed=1&amp;lang={lang}"', html_md)
                self.assertIn(f'src="../viz/golden-carry/index.html?embed=1&amp;lang={lang}&amp;preset=window"', html_md)
                ctx = render.RenderContext(config.load_site(), book, book.edition(lang), model, lean.Lock.load(), "pandoc")
                pd = render.chapter_markdown(doc, ctx)
                self.assertIn("::: {.tr-media .tr-viz}", pd)
                self.assertIn("_book/viz/golden-carry/thumb.jpg", pd)
                self.assertIn(f"_book/viz/golden-carry/fig-window.{lang}.jpg", pd)  # a cited card prints its own still
                self.assertEqual(ctx.issues, [])
                for name in ("thumb.jpg", f"fig-window.{lang}.jpg", f"fig-fill.{lang}.jpg"):
                    self.assertIn((bdir / "viz" / "golden-carry" / name).resolve(), ctx.book_files)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, out: Path):
        viz.build(config.load_site(), example_book(), out)
        return out

    @needs_example
    @needs_listed_example
    def test_build_layout_and_links(self):
        out = self.build(self.tmp / "viz")
        lock = lean.Lock.load()
        for name in viz.RUNTIME_FILES + ("tokens.css",):
            self.assertTrue((out / "assets" / name).is_file(), name)
        self.assertEqual((out / "assets" / "tokens.css").read_bytes(), (paths.GENERATED / "tokens.css").read_bytes())
        self.assertNotIn("@@", (out / "assets" / "favicon.svg").read_text(encoding="utf-8"))
        for name in ("index.html", "style.css", "main.js", "thumb.jpg"):
            self.assertTrue((out / "golden-carry" / name).is_file(), name)
        page = (out / "golden-carry" / "index.html").read_text(encoding="utf-8")
        for gid in (GID3, GIDI):
            self.assertIn(f'href="{lock.source_url(gid)}"', page)
        # every link of the published tree is relative and resolves
        for f in [out / "index.html", out / "golden-carry" / "index.html"]:
            text = f.read_text(encoding="utf-8")
            for url in re.findall(r'\s(?:src|href)="([^"]+)"', text):
                if re.match(r"^(https?:|#|data:|mailto:)", url):
                    continue
                self.assertFalse(url.startswith("/"), url)
                target = (f.parent / url.split("#")[0].split("?")[0])
                if url.startswith("../") and not (f.parent / url).resolve().is_relative_to(out.resolve()):
                    continue  # the book landing page and chapters are written by other builders
                if url.endswith("/") or url == "../":
                    target = target / "index.html"
                self.assertTrue(target.exists(), f"{f.name}: {url}")

    @needs_example
    @needs_listed_example
    def test_hub(self):
        out = self.build(self.tmp / "viz")
        hub = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="crumb" href="../"', hub)
        self.assertIn('<article class="card panel featured" data-viz="golden-carry">', hub)
        self.assertIn('<img src="golden-carry/thumb.jpg"', hub)
        self.assertIn('href="../zh/ch01-golden-deficit.html"', hub)
        self.assertIn('href="../en/ch01-golden-deficit.html"', hub)
        self.assertIn("LEAN ✓", hub)
        self.assertEqual(len(re.findall(r'class="(?:[^"]*\s)?zh(?:\s[^"]*)?"', hub)) - hub.count('class="alt-title zh"'),
                         len(re.findall(r'class="(?:[^"]*\s)?en(?:\s[^"]*)?"', hub)))
        self.assertIn('data-title-en="GOLDEN//OBSERVE', hub)
        reg = json.loads((out / "visualizations.json").read_text(encoding="utf-8"))
        self.assertEqual([v["id"] for v in reg["visualizations"]], ["golden-carry", "phase-torus"])
        self.assertEqual(reg["visualizations"][0]["lean"][0]["href"], lean.Lock.load().source_url(GID3))
        self.assertTrue(reg["visualizations"][0]["theory"][1]["href"].startswith("https://github.com/"))

    @needs_example
    @needs_listed_example
    def test_build_is_deterministic(self):
        a, b = self.build(self.tmp / "a"), self.build(self.tmp / "b")
        files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file()))
        for rel in files:
            self.assertEqual((a / rel).read_bytes(), (b / rel).read_bytes(), str(rel))

    @needs_example
    @needs_listed_example
    def test_build_replaces_stale_output(self):
        out = self.tmp / "viz"
        (out / "old-viz").mkdir(parents=True)
        self.build(out)
        self.assertFalse((out / "old-viz").exists())

    @needs_example
    @needs_listed_example
    def test_build_refuses_a_broken_registry(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        (book.viz_dir / "golden-carry" / "thumb.jpg").unlink()
        with self.assertRaises(viz.VizError) as cm:
            viz.build(config.load_site(), book, self.tmp / "out")
        self.assertIn("thumbnail does not exist", str(cm.exception))

    @needs_example
    @needs_listed_example
    def test_drafts_are_not_published(self):
        book = fake_book(self.tmp)
        copy_golden_carry(book)
        reg = json.loads((book.viz_dir / "visualizations.json").read_text(encoding="utf-8"))
        reg["visualizations"][0]["status"] = "draft"
        write_registry(book, reg)
        out = self.tmp / "out"
        viz.build(config.load_site(), book, out)
        self.assertFalse((out / "golden-carry").exists())
        self.assertIn(viz.t("en", "none_live"), (out / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(viz.items(book), [])

    def test_book_without_viz_publishes_nothing(self):
        out = self.tmp / "out"
        viz.build(config.load_site(), fake_book(self.tmp), out)
        self.assertFalse(out.exists())

    @needs_example
    @needs_listed_example
    def test_items(self):
        items = viz.items(example_book())
        self.assertEqual([it["id"] for it in items], ["golden-carry", "phase-torus"])
        it = items[0]
        self.assertEqual((it["id"], it["href"], it["thumb"], it["hub"]),
                         ("golden-carry", "viz/golden-carry/", "viz/golden-carry/thumb.jpg", "viz/"))
        self.assertTrue(it["thumb_file"].is_file())
        self.assertTrue(it["title"]["zh"].startswith("黄金进位"))
        self.assertTrue(it["title"]["en"].startswith("Golden carry"))
        self.assertEqual([x["gid"] for x in it["lean"]], EXAMPLE_GIDS)
        self.assertEqual(it["lean"][0]["label"], "deficit_three_valued")
        self.assertEqual(it["theory"][0]["href"]["en"], "../en/ch01-golden-deficit.html")


class Scaffold(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-viz-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scaffold_creates_a_valid_draft(self):
        book = fake_book(self.tmp)
        created = viz.scaffold(book, "fib-walk", "FIB//WALK", "斐波那契行走", "Fibonacci walk", added="2026-11-08")
        names = sorted(p.relative_to(book.viz_dir).as_posix() for p in created)
        self.assertEqual(names, ["fib-walk/index.html", "fib-walk/main.js", "fib-walk/style.css",
                                 "tests/fib-walk.test.mjs", "visualizations.json"])
        page = (book.viz_dir / "fib-walk" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-viz-id="fib-walk"', page)
        self.assertIn("FIB<b>//</b>WALK", page)
        self.assertNotIn("__", page.replace("__proto__", ""))
        test = (book.viz_dir / "tests" / "fib-walk.test.mjs").read_text(encoding="utf-8")
        self.assertIn(f"T.goto('{book.slug}', 'fib-walk'", test)
        entry = viz.entry(book, "fib-walk")
        self.assertEqual((entry["status"], entry["path"], entry["thumbnail"]), ("draft", "fib-walk/", "fib-walk/thumb.jpg"))
        errors = [i.format() for i in viz.check_native(book, lock=lean.Lock.load()) if i.severity == "error"]
        self.assertEqual(errors, [])
        with self.assertRaises(viz.VizError):
            viz.scaffold(book, "fib-walk", "FIB//WALK", "重复")
        with self.assertRaises(viz.VizError):
            viz.scaffold(book, "tests", "X", "保留名")
        with self.assertRaises(viz.VizError):
            viz.scaffold(book, "Bad", "X", "大写")

    @unittest.skipUnless(NODE, "node not available")
    def test_node_scaffold_is_identical(self):
        py_book, js_book = fake_book(self.tmp / "py"), fake_book(self.tmp / "js")
        args = ("fib-walk", "FIB//WALK", "斐波那契行走", "Fibonacci walk")
        viz.scaffold(py_book, *args)
        r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-new.mjs"), str(js_book.dir), *args],
                           capture_output=True, text=True, cwd=paths.ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(p.relative_to(py_book.viz_dir) for p in py_book.viz_dir.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(p.relative_to(js_book.viz_dir) for p in js_book.viz_dir.rglob("*") if p.is_file()))
        for rel in files:
            self.assertEqual((py_book.viz_dir / rel).read_text(encoding="utf-8"),
                             (js_book.viz_dir / rel).read_text(encoding="utf-8"), str(rel))

    @unittest.skipUnless(NODE and hasattr(time, "tzset"), "node and time.tzset needed")
    def test_node_scaffold_is_identical_at_utc_day_boundaries(self):
        script = """
        const RealDate = Date;
        const [stamp, bookPath] = process.argv.slice(1);
        globalThis.Date = class extends RealDate {
          constructor(...args) { super(...(args.length ? args : [Number(stamp)])); }
          static now() { return Number(stamp); }
        };
        const { scaffold } = await import('./tools/node/viz-new.mjs');
        const { resolveBook } = await import('./tools/node/viz-common.mjs');
        scaffold(resolveBook(bookPath), { id: 'fib-walk', code: 'FIB//WALK', title: '行走', titleEn: 'Walk' });
        """
        for zone in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
            for instant in ("2026-12-31T00:01:00+00:00", "2026-12-31T23:59:00+00:00"):
                with self.subTest(zone=zone, instant=instant), tempfile.TemporaryDirectory(dir=self.tmp) as tmp:
                    stamp = datetime.fromisoformat(instant)
                    py_book, js_book = fake_book(Path(tmp) / "py"), fake_book(Path(tmp) / "js")
                    try:
                        with mock.patch.dict(os.environ, TZ=zone):
                            time.tzset()
                            with mock.patch.object(viz, "datetime", wraps=datetime) as clock:
                                clock.now.side_effect = lambda tz=None: datetime.fromtimestamp(stamp.timestamp(), tz)
                                viz.scaffold(py_book, "fib-walk", "FIB//WALK", "行走", "Walk")
                                clock.now.assert_called_once_with(timezone.utc)
                            r = subprocess.run([NODE, "--input-type=module", "-e", script,
                                                str(int(stamp.timestamp() * 1000)), str(js_book.dir)],
                                               capture_output=True, text=True, cwd=paths.ROOT, timeout=60)
                    finally:
                        time.tzset()
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(viz.entry(py_book, "fib-walk")["added"], "2026-12-31")
                    files = lambda book: {p.relative_to(book.viz_dir): p.read_bytes()
                                          for p in book.viz_dir.rglob("*") if p.is_file()}
                    self.assertEqual(files(py_book), files(js_book))

    QUOTED = ("quote-viz", 'Q//"V"', '黄金 "进位" & <比较> */', "Golden 'carry' & <compare> */")

    def test_scaffold_escapes_titles(self):
        book = fake_book(self.tmp)
        viz.scaffold(book, *self.QUOTED, added="2026-11-08")
        page = (book.viz_dir / "quote-viz" / "index.html").read_text(encoding="utf-8")

        class Collect(html.parser.HTMLParser):
            def __init__(self):
                super().__init__()
                self.attrs, self.tags = {}, []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
                self.attrs.setdefault(tag, dict(attrs))

        p = Collect()
        p.feed(page)
        self.assertEqual(p.attrs["html"]["data-title-en"], "Q//\"V\" · Golden 'carry' & <compare> */")
        self.assertEqual(p.attrs["h1"]["data-text"], 'Q//"V"')
        self.assertNotIn("compare", p.tags)
        self.assertIn("Q<b>//</b>&quot;V&quot;</h1>", page)
        # main.js names the titles in its opening comment, which must not end early
        head = (book.viz_dir / "quote-viz" / "main.js").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(head, '/* Q//"V" · 黄金 "进位" & <比较> * /')
        self.assertEqual(viz.entry(book, "quote-viz")["title_en"], self.QUOTED[3])  # the registry keeps the text
        self.assertEqual([i.format() for i in viz.check_native(book, lock=fake_lock()) if i.severity == "error"], [])

    @unittest.skipUnless(NODE, "node not available")
    def test_node_scaffold_escapes_identically(self):
        py_book, js_book = fake_book(self.tmp / "py"), fake_book(self.tmp / "js")
        viz.scaffold(py_book, *self.QUOTED, added=datetime.now(timezone.utc).date().isoformat())
        r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-new.mjs"), str(js_book.dir), *self.QUOTED],
                           capture_output=True, text=True, cwd=paths.ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in ("quote-viz/index.html", "quote-viz/main.js", "quote-viz/style.css", "tests/quote-viz.test.mjs"):
            self.assertEqual((py_book.viz_dir / rel).read_text(encoding="utf-8"),
                             (js_book.viz_dir / rel).read_text(encoding="utf-8"), rel)
        r = subprocess.run([NODE, "--check", str(js_book.viz_dir / "quote-viz" / "main.js")], capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(NODE, "node not available")
    def test_template_scripts_parse(self):
        for f in sorted((paths.TEMPLATES / "viz").glob("*.*js")):
            r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"{f.name}: {r.stderr}")

    @needs_listed_example
    def test_cli(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(viz.cli(SimpleNamespace(action="list", rest=[])), 0)
            self.assertEqual(viz.cli(SimpleNamespace(action="new", rest=["example-monograph", "x"])), 2)
            self.assertEqual(viz.cli(SimpleNamespace(action="new", rest=["no-such-book", "a-b", "A//B", "标题", "Title"])), 2)
            self.assertEqual(viz.cli(SimpleNamespace(action="new", rest=["example-monograph", "golden-carry", "A//B", "重复", "Dup"])), 2)
        self.assertIn("example-monograph/golden-carry", out.getvalue())
        self.assertIn("live", out.getvalue())
        self.assertIn("usage: ./tbook viz new", err.getvalue())
        self.assertIn("already exists", err.getvalue())


@unittest.skipUnless(NODE, "node not available")
class RailGate(unittest.TestCase):
    """The "rail" part of stageFirstChecks (tools/node/viz-testkit.mjs), run in Chromium on private copies of the
    starter page. Each copy changes one thing about its clock; the gate must accept the legitimate ones and refuse
    the broken ones. Skipped where Playwright or its Chromium is not installed (the unit-test job of a books
    repository need not have a browser); the visualization suites exercise the same gate on every real page."""

    SLUG = "rail-gate-fixture"
    CLOCK = "  const clock = kit.clock({\n"
    PRESET = "    const p = PRESETS[id];\n"
    # the page keeps thinking in degrees; the rail (kit.clock and its <input type=range>) runs over 0 … 2π
    RADIANS = (
        "  const radians = (o) => {\n"
        "    const K = Math.PI / 180;\n"
        "    const R = kit.clock(Object.assign({}, o, { max: 2 * Math.PI, t: o.t * K, rate: o.rate * K, step: o.step * K,\n"
        "      format: (t) => o.format(t / K), onChange: (t) => o.onChange(t / K) }));\n"
        "    return { get t() { return R.t / K; }, get playing() { return R.playing; }, set: (t, quiet) => R.set(t * K, quiet),\n"
        "      play: R.play, pause: R.pause };\n"
        "  };\n"
    )
    DISABLE = "    for (const k of ['now', 'play', 'rew']) $(k).disabled = %s;\n"
    DEAF = "document.addEventListener('input', (ev) => { if (ev.target.id === 'now') ev.stopPropagation(); }, true);\n"
    RUNNER = """
import fs from 'node:fs';
const [kit, out, slug, ...ids] = process.argv.slice(2);
const { session, stageFirstChecks } = await import(kit);
const T = await session();
const rail = {};
for (const id of ids) {
  const from = T.results.length;
  await stageFirstChecks(T, slug, id, { cards: false, labels: false, evidence: false });
  rail[id] = T.results.slice(from).filter((r) => r.name.startsWith('rail ('));
}
await T.browser.close();
fs.writeFileSync(out, JSON.stringify(rail));
process.exit(0);
"""

    @classmethod
    def variants(cls) -> dict:
        def swap(text: str, old: str, new: str) -> str:
            if text.count(old) != 1:
                raise AssertionError(f"templates/viz/main.js no longer has exactly one {old!r}")
            return text.replace(old, new)

        return {
            # the starter as it is: a clock over 0 … 360
            "rail-plain": lambda js: js,
            # an angle: max = 2π = 6.283185307179586, which End reads back with 15 significant digits
            "rail-angle": lambda js: swap(js, cls.CLOCK, cls.RADIANS + "  const clock = radians({\n"),
            # nothing to run on the opening card: the clock is disabled until the reader picks the card that plays
            "rail-empty": lambda js: swap(js, cls.PRESET, cls.PRESET + cls.DISABLE % "!p.play"),
            # disabled whatever the reader picks
            "rail-dead": lambda js: swap(js, cls.PRESET, cls.PRESET + cls.DISABLE % "true"),
            # the slider moves but the clock never hears it
            "rail-deaf": lambda js: cls.DEAF + js,
        }

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-rail-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        root = cls.tmp / "root"  # a repository root for the Node tools: the real theme and fonts, one private book
        (root / "books").mkdir(parents=True)
        try:
            (root / "theme").symlink_to(paths.THEME, target_is_directory=True)
            if (paths.ROOT / "node_modules").is_dir():
                (root / "node_modules").symlink_to(paths.ROOT / "node_modules", target_is_directory=True)
        except OSError as exc:
            raise unittest.SkipTest(f"cannot link the theme into a private root: {exc}")
        book = fake_book(root / "books", cls.SLUG)
        for vid, change in cls.variants().items():
            viz.scaffold(book, vid, vid.upper().replace("-", "//"), "时间轴", "Rail", added="2026-11-12")
            main = book.viz_dir / vid / "main.js"
            main.write_text(change(main.read_text(encoding="utf-8")), encoding="utf-8")
        runner, out = cls.tmp / "rail-gate.mjs", cls.tmp / "rail-gate.json"
        runner.write_text(cls.RUNNER, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "VIZ_ORIGIN"}
        env["TBOOK_ROOT"] = str(root)
        kit = (paths.TOOLS / "node" / "viz-testkit.mjs").as_uri()
        r = subprocess.run([NODE, str(runner), kit, str(out), cls.SLUG, *cls.variants()], capture_output=True,
                           text=True, cwd=paths.ROOT, env=env, timeout=900)
        if not out.is_file():
            tail = (r.stdout + r.stderr)[-3000:]
            if re.search(r"Playwright is not installed|Executable doesn't exist|browserType\.launch", tail):
                raise unittest.SkipTest("Playwright Chromium is not available")
            raise AssertionError(f"the rail gate did not run (exit {r.returncode}):\n{tail}")
        cls.rail = json.loads(out.read_text(encoding="utf-8"))

    def checks(self, vid: str, part: str) -> list[dict]:
        found = [c for c in self.rail[vid] if part in c["name"]]
        self.assertTrue(found, f"{vid}: no rail check named …{part}… in {[c['name'] for c in self.rail[vid]]}")
        return found

    def failed(self, vid: str) -> list[str]:
        return [f"{c['name']} — {c['detail']}" for c in self.rail[vid] if not c["ok"]]

    def keyboard(self, vid: str) -> list[dict]:
        found = self.checks(vid, "Home, → and End move the clock and the readout")
        self.assertEqual(len(found), 2, "one keyboard check per language")
        return found

    def test_the_starter_passes_with_every_positive_check(self):
        self.assertEqual(self.failed("rail-plain"), [])
        for part in ("neither the document nor the body scrolls sideways", "inside the frame and named",
                     "can be pressed where it is drawn", "runs from 0 over a finite positive range",
                     "dragging the slider moves the clock"):
            self.assertGreaterEqual(len(self.checks("rail-plain", part)), 2, part)
        for c in self.keyboard("rail-plain"):
            d = json.loads(c["detail"])
            self.assertTrue(d["focused"])
            self.assertEqual((d["home"][0], d["end"][0], d["max"]), (0, 360, 360))
            self.assertNotEqual(d["home"][1], d["end"][1])
        self.assertFalse([c["name"] for c in self.rail["rail-plain"] if "starts disabled" in c["name"]])

    def test_an_angle_endpoint_rounded_by_the_range_input_is_the_end(self):
        """End on max = 2π reads 6.28318530717959 for a max of 6.283185307179586: the same end, not a failure."""
        self.assertEqual(self.failed("rail-angle"), [])
        for c in self.keyboard("rail-angle"):
            d = json.loads(c["detail"])
            end, top = d["end"][0], d["max"]
            self.assertNotEqual(end, top, "the fixture no longer reproduces the rounded endpoint (an exact comparison would pass)")
            self.assertLess(abs(end - top), 1e-13)
            self.assertAlmostEqual(top, 6.283185307179586, places=12)
            self.assertEqual(d["home"][0], 0)
            self.assertTrue(0 < d["right"] < end - 1e-6)
            self.assertTrue(d["home"][1].startswith("θ 0°"), d["home"][1])
            self.assertTrue(d["end"][1].startswith("θ 360°"), d["end"][1])  # the readout reaches the end as well

    def test_a_clock_with_nothing_to_run_is_checked_after_a_card_enables_it(self):
        self.assertEqual(self.failed("rail-empty"), [])
        enabled = self.checks("rail-empty", "a slider that starts disabled is enabled by an experiment card")
        self.assertEqual([c["detail"] for c in enabled], ["card sweep", "card sweep"])  # zh, en: the only card that plays
        names = [c["name"] for c in self.rail["rail-empty"]]
        for lang in ("zh", "en"):
            for width in (320, 334, 360, 600, 601):
                for state in ("", ", card sweep"):  # laid out as it opens (disabled) and again once enabled
                    for part in ("neither the document nor the body scrolls sideways",
                                 "the transport, the readout and the slider are inside the frame and named"):
                        name = f"rail ({lang}, {width}px frame{state}): {part}"
                        self.assertTrue(any(n.startswith(name) for n in names), name)
        self.assertEqual(len(self.checks("rail-empty", "dragging the slider moves the clock")), 2)
        for c in self.keyboard("rail-empty"):
            d = json.loads(c["detail"])
            self.assertTrue(d["focused"])
            self.assertEqual((d["home"][0], d["end"][0]), (0, 360))

    def test_a_clock_no_card_enables_fails(self):
        enabled = self.checks("rail-dead", "a slider that starts disabled is enabled by an experiment card")
        self.assertEqual([(c["ok"], c["detail"]) for c in enabled], [(False, "no experiment card enables the slider")] * 2)
        self.assertEqual([c["ok"] for c in self.keyboard("rail-dead")], [False, False])
        self.assertEqual([c["ok"] for c in self.checks("rail-dead", "dragging the slider moves the clock")], [False, False])
        # the layout of the disabled rail is still checked, and it is fine
        self.assertTrue(all(c["ok"] for c in self.checks("rail-dead", "inside the frame and named")))

    def test_a_slider_the_clock_does_not_follow_fails(self):
        self.assertEqual([c["ok"] for c in self.keyboard("rail-deaf")], [False, False])
        for c in self.keyboard("rail-deaf"):
            d = json.loads(c["detail"])
            self.assertEqual(d["home"][1], d["end"][1], "the readout must be what gave the broken clock away")
        self.assertTrue(all(c["ok"] for c in self.checks("rail-deaf", "inside the frame and named")))


@unittest.skipUnless(NODE, "node not available")
class StageViewGate(unittest.TestCase):
    """The "layout" and "title" parts of stageFirstChecks (stageView in tools/node/viz-testkit.mjs), run in Chromium
    on private copies of the starter page. Some copies add scene buttons with long labels; others put back, in the
    page's own style.css, one piece of the shared layout that let the strip be drawn over the stage, left the lab
    without a way to scroll, put the title under the buttons, cut the title, or painted the buttons under the
    canvas. The gate must accept the shared layout and refuse each of those. Skipped like RailGate."""

    SLUG = "stage-view-fixture"
    HUD = '      <div class="hud-tl"><span class="big" id="hudBig"></span><span class="sub" id="hudSub"></span></div>\n'
    BUTTONS = (
        '      <div class="hud-tr chips" role="group" aria-label="场景" data-aria-en="Scene">'
        + "".join(f'<button class="chip" aria-pressed="{str(i == 0).lower()}"><span class="zh">{zh}</span>'
                  f'<span class="en">{en}</span></button>'
                  for i, (zh, en) in enumerate([("影子与高度", "Shadow and height"), ("两个平方", "Both squares"),
                                                ("单位圆", "Unit circle"), ("整圈", "Full turn")]))
        + "</div>\n"
    )
    # the shared layout of 0.5.2, which these copies put back one piece at a time
    OLD_HUD = (".stage:has(> .hud-tl, > .hud-tr) { display: block; padding: 0; }\n"
               ".stage > .hud-tl, .stage.hud-stack > .hud-tl { position: absolute; top: 14px; left: 20px; max-width: calc(100% - 40px); }\n"
               ".stage > .hud-tr { position: absolute; top: 12px; right: 18px; max-width: 60%; }\n")
    OLD_ROWS = (".app.lab { grid-template-rows: auto minmax(0, 1fr) auto; }\n"
                ".lab .center { min-height: 0; grid-template-rows: minmax(0, 1fr) auto; }\n"
                ".lab .center > .stage:has(> .hud-tl, > .hud-tr) { padding-bottom: 0; }\n")
    NO_SCROLL = "body:has(> .app.lab) { overflow: hidden; }\n"
    RUNNER = """
import fs from 'node:fs';
const [kit, out, slug, ...ids] = process.argv.slice(2);
const { session, stageFirstChecks } = await import(kit);
const T = await session();
const view = {};
const ours = /: the (stage, the tour bar and the strip keep their own regions|title, the scene buttons and the legend are whole)|the scene button can be pressed/;
for (const id of ids) {
  const from = T.results.length;
  await stageFirstChecks(T, slug, id, { labels: false, evidence: false, rail: false });
  view[id] = T.results.slice(from).filter((r) => ours.test(r.name));
}
await T.browser.close();
fs.writeFileSync(out, JSON.stringify(view));
process.exit(0);
"""

    @classmethod
    def variants(cls) -> dict:
        """id → (change to index.html, rules appended to style.css)."""
        buttons = lambda html: cls.swap(html, cls.HUD, cls.HUD + cls.BUTTONS)
        same = lambda html: html
        return {
            "view-plain": (same, ""),
            "view-scenes": (buttons, ""),
            "view-old-hud": (buttons, cls.OLD_HUD),
            "view-old-rows": (same, cls.OLD_ROWS + cls.NO_SCROLL),
            "view-no-scroll": (same, cls.NO_SCROLL),
            "view-cut": (buttons, ".stage > .hud-tl .sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n"),
            "view-buried": (buttons, ".stage > .hud-tr { z-index: -1; }\n"),
        }

    @staticmethod
    def swap(text: str, old: str, new: str) -> str:
        if text.count(old) != 1:
            raise AssertionError(f"templates/viz/index.html no longer has exactly one {old!r}")
        return text.replace(old, new)

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-view-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        root = cls.tmp / "root"
        (root / "books").mkdir(parents=True)
        try:
            (root / "theme").symlink_to(paths.THEME, target_is_directory=True)
            if (paths.ROOT / "node_modules").is_dir():
                (root / "node_modules").symlink_to(paths.ROOT / "node_modules", target_is_directory=True)
        except OSError as exc:
            raise unittest.SkipTest(f"cannot link the theme into a private root: {exc}")
        book = fake_book(root / "books", cls.SLUG)
        for vid, (page, rules) in cls.variants().items():
            viz.scaffold(book, vid, vid.upper().replace("-", "//"), "版式", "Layout", added="2026-11-12")
            index, style = book.viz_dir / vid / "index.html", book.viz_dir / vid / "style.css"
            index.write_text(page(index.read_text(encoding="utf-8")), encoding="utf-8")
            style.write_text(style.read_text(encoding="utf-8") + rules, encoding="utf-8")
        runner, out = cls.tmp / "view-gate.mjs", cls.tmp / "view-gate.json"
        runner.write_text(cls.RUNNER, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "VIZ_ORIGIN"}
        env["TBOOK_ROOT"] = str(root)
        kit = (paths.TOOLS / "node" / "viz-testkit.mjs").as_uri()
        r = subprocess.run([NODE, str(runner), kit, str(out), cls.SLUG, *cls.variants()], capture_output=True,
                           text=True, cwd=paths.ROOT, env=env, timeout=1500)
        if not out.is_file():
            tail = (r.stdout + r.stderr)[-3000:]
            if re.search(r"Playwright is not installed|Executable doesn't exist|browserType\.launch", tail):
                raise unittest.SkipTest("Playwright Chromium is not available")
            raise AssertionError(f"the stage view gate did not run (exit {r.returncode}):\n{tail}")
        cls.view = json.loads(out.read_text(encoding="utf-8"))

    def results(self, vid: str, prefix: str = "", part: str = "") -> list[dict]:
        found = [c for c in self.view[vid] if c["name"].startswith(prefix) and part in c["name"]]
        self.assertTrue(found, f"{vid}: no check {prefix}…{part}…")
        return found

    def failed(self, vid: str, prefix: str = "", part: str = "") -> list[dict]:
        return [c for c in self.results(vid, prefix, part) if not c["ok"]]

    LAYOUT, TITLE = "keep their own regions", "are whole and clear of each other"

    def test_the_shared_layout_passes_in_every_state(self):
        for vid in ("view-plain", "view-scenes"):
            self.assertEqual([f"{c['name']} — {c['detail']}" for c in self.view[vid] if not c["ok"]], [], vid)
            for prefix in ("desktop", "English", "short screen (zh, 1440 ×", "short screen (en, 1081 ×", "embed",
                           "frame (zh, 320 × 620)", "frame (en, 334 × 620)", "cited figure (zh,", "cited figure (en,",
                           "still for PDF/EPUB", "phone"):
                self.results(vid, prefix)
        # both sides of the height the lab needs on a short screen, read off the page
        names = [c["name"] for c in self.results("view-scenes", "short screen (en, 1081 ×", self.LAYOUT)]
        need = int(re.search(r"needs (\d+)\)", names[0]).group(1))
        self.assertTrue(any(f"× {need - 1}," in n for n in names) and any(f"× {need + 1}," in n for n in names), names)
        self.assertGreater(need, 500, "the fixture no longer needs more height than a 500px screen gives it")
        self.assertEqual(len({c["name"].split(":")[0] for c in self.results("view-scenes", "English, scene ")}), 4)

    def test_a_strip_drawn_over_the_stage_fails(self):
        bad = self.failed("view-old-rows", "short screen", self.LAYOUT)
        self.assertTrue(bad)
        self.assertTrue(any("the stage" in c["detail"] and "overlaps div.strip" in c["detail"] for c in bad), bad)
        self.assertTrue(any("painted over by" in c["detail"] for c in bad), bad)
        self.assertFalse(self.failed("view-old-rows", "desktop", self.LAYOUT), "a tall screen has room for both")

    def test_a_lab_that_cannot_scroll_fails_even_when_nothing_overlaps(self):
        bad = self.failed("view-no-scroll", "short screen", self.LAYOUT)
        self.assertTrue(bad)
        self.assertTrue(all("cannot be scrolled into view" in c["detail"] and "overlaps" not in c["detail"] for c in bad), bad)
        self.assertTrue(any("#rail (bottom" in c["detail"] for c in bad), bad)
        self.assertFalse(self.failed("view-no-scroll", "frame", self.LAYOUT), "a chapter's frame scrolls on its own")

    def test_a_title_under_the_scene_buttons_fails(self):
        bad = self.failed("view-old-hud", part=self.TITLE)
        self.assertTrue(any("runs under button" in c["detail"] for c in bad), bad)
        for prefix in ("frame (zh, 334", "frame (en, 334", "cited figure (en,"):
            self.assertTrue(self.failed("view-old-hud", prefix, self.TITLE), prefix)
        self.assertFalse(self.failed("view-old-hud", part=self.LAYOUT))

    def test_a_cut_title_fails(self):
        bad = self.failed("view-cut", part=self.TITLE)
        self.assertTrue(bad and any("is cut off by #hudSub" in c["detail"] for c in bad), bad)
        self.assertTrue(self.failed("view-cut", "frame (en, 334", self.TITLE))

    def test_buttons_painted_under_the_canvas_fail(self):
        bad = self.failed("view-buried", "desktop", self.TITLE)
        self.assertTrue(bad and all("is covered by #cv" in c["detail"] for c in bad), bad)
        self.assertTrue(self.failed("view-buried", "English, scene", "the scene button can be pressed"))


class KeysGate(unittest.TestCase):
    """The "keys" part of stageFirstChecks (spaceAfterCard in tools/node/viz-testkit.mjs), run in Chromium on private
    copies of the starter page: Space right after a pointer click on a card plays and pauses the clock; a page whose
    card keeps the focus fails; a page without a clock button, or with one no card enables, is skipped. Skipped where
    Playwright or its Chromium is not installed."""

    SLUG = "keys-gate-fixture"
    NAME = "keyboard: after a card is clicked, Space plays and pauses the clock"
    RUNNER = """
import fs from 'node:fs';
const [kit, out, slug, ...ids] = process.argv.slice(2);
const { session, spaceAfterCard, settle } = await import(kit);
const T = await session();
const res = {};
for (const id of ids) {
  const from = T.results.length;
  const page = await T.goto(slug, id, '?lang=zh'); await settle(page, 300);
  await spaceAfterCard(T, page);
  const focus = await page.evaluate(() => document.activeElement === document.body);
  res[id] = { checks: T.results.slice(from), blurred: focus };
}
await T.browser.close();
fs.writeFileSync(out, JSON.stringify({ res, errors: T.errors }));
process.exit(0);
"""
    # what kit.js did before: the clicked card keeps the focus, so Space presses it again
    STICKY = ("document.addEventListener('click', (ev) => { const b = ev.target.closest && ev.target.closest('[data-preset]');"
              " if (b && ev.detail > 0) b.focus(); });\n")
    DISABLE = "    for (const k of ['now', 'play', 'rew']) $(k).disabled = true;\n"
    PRESET = "    const p = PRESETS[id];\n"

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-keys-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        root = cls.tmp / "root"
        (root / "books").mkdir(parents=True)
        try:
            (root / "theme").symlink_to(paths.THEME, target_is_directory=True)
            if (paths.ROOT / "node_modules").is_dir():
                (root / "node_modules").symlink_to(paths.ROOT / "node_modules", target_is_directory=True)
        except OSError as exc:
            raise unittest.SkipTest(f"cannot link the theme into a private root: {exc}")
        book = fake_book(root / "books", cls.SLUG)

        def swap(text: str, old: str, new: str) -> str:
            if text.count(old) != 1:
                raise AssertionError(f"templates/viz no longer has exactly one {old!r}")
            return text.replace(old, new)

        variants = {
            "keys-plain": (lambda js: js, lambda h: h),
            "keys-sticky": (lambda js: js + cls.STICKY, lambda h: h),
            "keys-dead": (lambda js: swap(js, cls.PRESET, cls.PRESET + cls.DISABLE), lambda h: h),
            # a page without the clock's ▶ in footer.rail (here: the same button under another id)
            "keys-noplay": (lambda js: swap(js, "$('play')", "$('playBtn')"),
                            lambda h: swap(h, 'id="play"', 'id="playBtn"')),
        }
        for vid, (js, page) in variants.items():
            viz.scaffold(book, vid, vid.upper().replace("-", "//"), "键盘", "Keys", added="2026-11-12")
            for name, change in (("main.js", js), ("index.html", page)):
                f = book.viz_dir / vid / name
                f.write_text(change(f.read_text(encoding="utf-8")), encoding="utf-8")
        runner, out = cls.tmp / "keys-gate.mjs", cls.tmp / "keys-gate.json"
        runner.write_text(cls.RUNNER, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "VIZ_ORIGIN"}
        env["TBOOK_ROOT"] = str(root)
        kit = (paths.TOOLS / "node" / "viz-testkit.mjs").as_uri()
        r = subprocess.run([NODE, str(runner), kit, str(out), cls.SLUG, *variants], capture_output=True,
                           text=True, cwd=paths.ROOT, env=env, timeout=600)
        if not out.is_file():
            tail = (r.stdout + r.stderr)[-3000:]
            if re.search(r"Playwright is not installed|Executable doesn't exist|browserType\.launch", tail):
                raise unittest.SkipTest("Playwright Chromium is not available")
            raise AssertionError(f"the keys gate did not run (exit {r.returncode}):\n{tail}")
        data = json.loads(out.read_text(encoding="utf-8"))
        cls.res, cls.errors = data["res"], data["errors"]

    def outcome(self, vid: str) -> list[tuple[bool, str]]:
        return [(c["ok"], c["detail"]) for c in self.res[vid]["checks"] if c["name"] == self.NAME]

    def test_the_starter_passes(self):
        [(ok, detail)] = self.outcome("keys-plain")
        self.assertTrue(ok, detail)
        self.assertRegex(detail, r"playing (true|false) → Space → (true|false) → Space → (true|false)")
        self.assertTrue(self.res["keys-plain"]["blurred"], "the check leaves nothing focused for the checks after it")
        self.assertEqual(self.errors, [])

    def test_a_card_that_keeps_the_focus_fails(self):
        [(ok, detail)] = self.outcome("keys-sticky")
        self.assertFalse(ok, detail)

    def test_pages_without_a_clock_to_run_are_skipped(self):
        for vid in ("keys-dead", "keys-noplay"):
            with self.subTest(vid):
                self.assertEqual(self.outcome(vid), [])
                self.assertEqual([c for c in self.res[vid]["checks"] if not c["ok"]], [])


class Strings(unittest.TestCase):
    def test_local_strings_cover_both_languages(self):
        self.assertEqual(set(viz.STRINGS["zh"]), set(viz.STRINGS["en"]))
        for key in viz.STRINGS["en"]:
            self.assertTrue(viz.t("zh", key) and viz.t("en", key), key)
        self.assertEqual(viz.t("en", "published", n=3), "3 published · in registry order")
        self.assertFalse(re.search(r"[㐀-鿿]", " ".join(viz.STRINGS["en"].values())))

    def test_pages_load_the_theme_fonts(self):
        """Visualization pages link the Google Fonts URL of theme/tokens.json (it carries the Latin face English
        text uses), not a copy that drifts from it."""
        url = json.loads((paths.THEME / "tokens.json").read_text(encoding="utf-8"))["font"]["google-fonts-css"]
        pages = [paths.ROOT / "templates" / "viz" / "index.html"] + sorted(paths.BOOKS.glob("*/viz/*/index.html"))
        for page in pages:
            text = page.read_text(encoding="utf-8")
            if "fonts.googleapis.com/css" in text:
                self.assertIn(f'href="{url}"', text, page)

    def test_runtime_has_no_hard_coded_palette(self):
        """theme/viz colours come from tokens.css; hex values appear only in marked fallbacks."""
        tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
        for name in ("theme.css", "hub.css", "hub.js", "kit.js"):
            text = (paths.THEME / "viz" / name).read_text(encoding="utf-8")
            bare = re.sub(r"var\(--tr-[a-z-]+, #[0-9a-f]{6}\)", "", text)
            self.assertFalse(re.search(r"#[0-9a-fA-F]{6}\b", bare), name)
        shell = (paths.THEME / "viz" / "shell.js").read_text(encoding="utf-8")
        fallback = re.search(r"const FALLBACK = \{([^}]*)\}", shell).group(1)
        for key, value in re.findall(r"'?([a-z-]+)'?: '(#[0-9a-f]{6})'", fallback):
            self.assertEqual(tokens["screen"][key], value, f"shell.js fallback {key} drifted from tokens.json")
        for name in ("style.css", "main.js"):
            for page_dir in (paths.TEMPLATES / "viz", EXAMPLE / "viz" / "golden-carry"):
                if page_dir.is_dir():  # the example book may have been deleted downstream
                    text = (page_dir / name).read_text(encoding="utf-8")
                    self.assertFalse(re.search(r"#[0-9a-fA-F]{6}\b", text), f"{page_dir.name}/{name}")


if __name__ == "__main__":
    unittest.main()
