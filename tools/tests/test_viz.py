"""Tests for tbook.viz (book-local visualizations) and its Node counterparts in tools/node/viz-*.mjs.

Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_viz.py'
Node-dependent tests are skipped when ``node`` is not on PATH. Browser suites are not run here (see
tools/node/viz-test.mjs); this file covers the registry checks, embeds, the publish step and scaffolding.
"""

from __future__ import annotations

import html.parser
import io
import json
import os
import re
import shutil
import subprocess
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
    """Copy the example visualization (page, thumbnail, test, registry) into ``book``."""
    src = EXAMPLE / "viz"
    for lang in ("zh", "en"):  # the drawer links to chapter 1 of each edition
        (book.dir / lang).mkdir(exist_ok=True)
        (book.dir / lang / "ch01-golden-deficit.md").write_text("# 1\n", encoding="utf-8")
    shutil.copytree(src / "golden-carry", book.viz_dir / "golden-carry")
    (book.viz_dir / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "tests" / "golden-carry.test.mjs", book.viz_dir / "tests" / "golden-carry.test.mjs")
    reg = json.loads((src / "visualizations.json").read_text(encoding="utf-8"))
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
        ]
        for e in expect:
            self.assertTrue(any(e in m for m in msgs), f"missing problem {e!r} in:\n" + "\n".join(msgs))

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
                # four cards cited where the text talks about them, then the whole lab at the end of the chapter
                self.assertEqual(cited, [("golden-carry", c) for c in ("window", "cancel", "map", "fill", "")])
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
        self.assertEqual([v["id"] for v in reg["visualizations"]], ["golden-carry"])
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
        self.assertEqual(len(items), 1)
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
