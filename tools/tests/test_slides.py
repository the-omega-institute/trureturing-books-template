"""Tests for tbook.slides (run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_slides.py').

Most tests are pure Python. Tests that compare with Slidev's own parser, run tools/node/slides-*.mjs or
scaffold a deck need Node and node_modules (``npm ci``) and are skipped otherwise; the end-to-end
``cli new`` test also needs the trureturing checkout ($TRURETURING_DIR or ../trureturing) for
``./tbook check --offline``. Tests on books/example-monograph skip when a books repository has removed
it; the others use scratch books and a fake lock.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from example_support import example_shown

from tbook import config, lean, paths, slides

ROOT = paths.ROOT
EXAMPLE = paths.BOOKS / "example-monograph"
DECK = EXAMPLE / "slides" / "overview"
HAVE_EXAMPLE = (DECK / "slides.md").is_file()
needs_example = unittest.skipUnless(HAVE_EXAMPLE, "books/example-monograph (with its overview deck) is not in this repository")
NODE = shutil.which("node")
HAVE_NODE = bool(NODE) and (ROOT / "node_modules" / "@slidev" / "parser").is_dir()
HAVE_UNO = HAVE_NODE and (ROOT / "node_modules" / "unocss").is_dir()
GID_3V = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"
GID_INT = "D5/S1/Deficit/DeficitInteger.deficit_integer"
GID_DEF = "D5/S1/Deficit/DeficitInteger.deficit"
needs_listed_example = unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden")

# A fake lock for the scratch-book tests: one Lean theorem, one Lean def.
FAKE_THM = "D5/S1/Fake/FakeModule.fake_theorem"
FAKE_DEF = "D5/S1/Fake/FakeModule.fake_def"
FAKE_DECLS = {gid: {"module": "D5/S1/Fake/FakeModule", "name": f"D5.S1.Fake.{gid.rsplit('.', 1)[1]}", "kind": kind,
                    "statement_id": "sha256:0", "line": 1, "signature": ""}
              for gid, kind in ((FAKE_THM, "theorem"), (FAKE_DEF, "def"))}


def fake_lock() -> lean.Lock:
    return lean.Lock(repo="o/trureturing", branch="dev", commit="0" * 40, declarations=dict(FAKE_DECLS))


def make_book(parent: Path, slug: str, editions: list[str]) -> config.Book:
    """A minimal book (book.toml only) at parent/slug."""
    bdir = parent / slug
    bdir.mkdir(parents=True)
    titles = "\n".join(f'{lang} = "Book {lang}"' for lang in editions)
    (bdir / "book.toml").write_text(f'[book]\nversion = "0.1.0"\neditions = {json.dumps(editions)}\ncode = "S//B"\n\n'
                                    f"[book.title]\n{titles}\n", encoding="utf-8")
    return config.load_book(bdir)


def fake_build(book: config.Book, out: Path, *, deck: str = "d1", pdfs: tuple[str, ...] = ()) -> Path:
    """A fake slides build (build/slides/<slug>/ layout and manifest) of `deck`; PDFs only for `pdfs`."""
    base = slides.base_path(config.load_site())
    langs = {}
    for lang in book.languages:
        (out / deck / lang).mkdir(parents=True)
        (out / deck / lang / "index.html").write_text(f"<title>{lang}</title>", encoding="utf-8")
        pdf = slides.build_pdf_name(deck, lang) if lang in pdfs else ""
        if pdf:
            (out / pdf).write_bytes(b"%PDF-1.7 fake")
        langs[lang] = {"dir": f"{deck}/{lang}/", "site_path": slides.site_path(book, deck, lang), "base": base,
                       "pdf": pdf, "pdf_name": slides.pdf_name(book, deck, lang)}
    (out / "manifest.json").write_text(json.dumps({"schema": slides.MANIFEST_SCHEMA, "base": base,
                                                   "decks": {deck: {"langs": langs}}}), encoding="utf-8")
    return out


def deck_head(theme: str, lang: str, **over) -> str:
    """Headmatter of a valid one-slide edition in `lang` (cover layout)."""
    fields = {"theme": theme, "title": f'"T {lang}"', "bcp": f'"{config.bcp47(lang)}"', "version": '"0.1.0"'}
    fields.update(over)
    return (f"---\ntheme: {fields['theme']}\ntitle: {fields['title']}\nhtmlAttrs:\n  lang: {fields['bcp']}\n"
            f"deck:\n  code: \"G//O\"\n  title: \"t\"\n  version: {fields['version']}\nlayout: cover\n---\n\n# cover\n")


def node_parse(text: str) -> list[dict]:
    """Slides of `text` according to @slidev/parser (frontmatter and content of every slide)."""
    script = (
        "import { parseSync } from '@slidev/parser';"
        "import { readFileSync } from 'node:fs';"
        "const md = readFileSync(0, 'utf8');"
        "const out = parseSync(md, 'x.md').slides.map(s => ({ frontmatter: s.frontmatter ?? {}, content: s.content, start: s.start }));"
        "process.stdout.write(JSON.stringify(out));"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", script], input=text, capture_output=True, text=True,
                       cwd=ROOT, check=True)
    return json.loads(r.stdout)


TRICKY = """---
theme: x
title: "A: b # not a comment"
deck:
  code: 'G//O'
  list: [a, "b, c", 3]
---

# one

```md
---
not a separator
---
```

---
layout: section
chapter: "01"
hide: false
---

<!--
---
in a comment
-->
two

----

three (after a ---- line: no frontmatter)

---

four
<!-- speaker notes -->

---

```yaml
layout: cover
```

five
"""


# Decks whose slides start or end with characters Python and JavaScript disagree on as whitespace, and a
# frontmatter opener with a line separator in it (JavaScript's . stops there).
UNICODE_EDGES = [
    '# a\n\n---\n\n\u0085```\n<LeanBadge gid="x" />\n```\n\n---\n\n\ufeff\x1ctext\ufeff\n',
    "a\n\n---\n\n\ufeff```\nb\n```\n\n---\n\nc\n\n\u0085",
    "a\n\n---\u2028x\nlayout: cover\n---\n\nb\n",
    "a\n\n---\nlayout: cover\n---\u0085\n\nb\n\n---\n\n\x1f```yaml\nlayout: cover\n```\n\nc\n",
    "a\n\n\u0085```\n---\n```\n\nb\n",
]


class SplitTest(unittest.TestCase):
    def test_tricky_counts_and_frontmatter(self):
        got = slides.split_slides(TRICKY)
        self.assertEqual(len(got), 5)
        self.assertEqual(got[0].frontmatter["title"], "A: b # not a comment")
        self.assertEqual(got[0].frontmatter["deck"], {"code": "G//O", "list": ["a", "b, c", 3]})
        self.assertEqual(got[1].frontmatter, {"layout": "section", "chapter": "01", "hide": False})
        self.assertEqual(got[4].frontmatter, {"layout": "cover"})
        self.assertEqual(got[3].content, "four")  # trailing comment = notes

    def test_hidden_slides_are_not_counted(self):
        text = "---\ntitle: t\n---\n\na\n\n---\nhide: true\n---\n\nb\n\n---\n\nc\n"
        self.assertEqual(len(slides.split_slides(text)), 3)
        self.assertEqual(slides.count_slides(text), 2)

    def test_slides_are_trimmed_as_javascript_trims(self):
        """Finding (Python vs JavaScript whitespace): @slidev/parser trims a slide with JavaScript's trim(),
        which keeps U+0085 and U+001C-U+001F and drops U+FEFF. Behind U+0085 a ``` is no fence, so the badge
        below it is rendered and checked."""
        got = [s.content for s in slides.split_slides(UNICODE_EDGES[0])]
        self.assertEqual(got, ["# a", '\u0085```\n<LeanBadge gid="x" />\n```', "\x1ctext"])
        self.assertEqual([c.gid for c in slides.citations(got[1])[0]], ["x"])

    @unittest.skipUnless(HAVE_NODE, "node and node_modules/@slidev/parser needed")
    def test_matches_slidev_parser_on_unicode_spaces(self):
        for text in UNICODE_EDGES:
            mine = slides.split_slides(text)
            theirs = node_parse(text)
            self.assertEqual([(s.frontmatter, s.content, s.line) for s in mine],
                             [(s["frontmatter"], s["content"], s["start"] + 1) for s in theirs], repr(text))

    @unittest.skipUnless(HAVE_NODE, "node and node_modules/@slidev/parser needed")
    def test_matches_slidev_parser(self):
        texts = [TRICKY] + [p.read_text(encoding="utf-8").replace("{{THEME}}", "x")
                            for p in sorted((ROOT / "templates" / "slides").glob("slides*.md"))]
        if HAVE_EXAMPLE:
            texts += [(DECK / "slides.md").read_text(encoding="utf-8"), (DECK / "slides.en.md").read_text(encoding="utf-8")]
        for text in texts:
            mine = slides.split_slides(text)
            theirs = node_parse(text)
            self.assertEqual(len(mine), len(theirs))
            for a, b in zip(mine, theirs):
                self.assertEqual(a.frontmatter, b["frontmatter"])
                self.assertEqual(a.content, b["content"].strip())
                self.assertEqual(a.line, b["start"] + 1)


class YamlTest(unittest.TestCase):
    def test_subset(self):
        doc = slides.parse_yaml(
            "# comment\n"
            "a: 1\n"
            "b: 2.5\n"
            "c: true\n"
            "d: ~\n"
            "e: \"x\\\"y\\u00e9\"\n"
            "f: 'it''s'\n"
            "g: plain text # trailing comment\n"
            "h:\n"
            "  i: deep\n"
            "  j:\n"
            "    - one\n"
            "    - two: 2\n"
            "      three: 3\n"
            "k: |\n"
            "  line 1\n"
            "  line 2\n"
            "l: [1, 'b', \"c, d\"]\n"
            "m: {x: 1, y: z}\n"
        )
        self.assertEqual(doc["a"], 1)
        self.assertEqual(doc["b"], 2.5)
        self.assertIs(doc["c"], True)
        self.assertIsNone(doc["d"])
        self.assertEqual(doc["e"], 'x"yé')
        self.assertEqual(doc["f"], "it's")
        self.assertEqual(doc["g"], "plain text")
        self.assertEqual(doc["h"], {"i": "deep", "j": ["one", {"two": 2, "three": 3}]})
        self.assertEqual(doc["k"], "line 1\nline 2\n")
        self.assertEqual(doc["l"], [1, "b", "c, d"])
        self.assertEqual(doc["m"], {"x": 1, "y": "z"})

    def test_errors(self):
        with self.assertRaises(slides.YamlError):
            slides.parse_yaml('a: "unterminated\n')
        with self.assertRaises(slides.YamlError):
            slides.parse_yaml("a: 1\n   b: 2\n")


class ConventionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-slides-conv-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_files_and_paths(self):
        book = make_book(self.tmp, "zh-first", ["zh", "en", "ja"])
        self.assertEqual(slides.edition_file(book, "zh"), "slides.md")
        self.assertEqual(slides.edition_file(book, "en"), "slides.en.md")
        self.assertEqual(slides.edition_file(book, "ja"), "slides.ja.md")
        self.assertEqual(slides.lang_of_file(book, "slides.md"), "zh")
        self.assertEqual(slides.lang_of_file(book, "slides.en.md"), "en")
        self.assertIsNone(slides.lang_of_file(book, "notes.md"))
        self.assertEqual(slides.site_path(book, "overview", "zh"), "overview/")
        self.assertEqual(slides.site_path(book, "overview", "en"), "overview/en/")
        self.assertEqual(slides.build_pdf_name("overview", "en"), "overview-en.pdf")
        self.assertEqual(slides.pdf_name(book, "overview", "zh"), "zh-first-overview-zh.pdf")
        self.assertEqual(slides.theme_ref(paths.BOOKS / "any-book" / "slides" / "overview"), "../../../../theme/slides")

    def test_first_language_owns_slides_md(self):
        """slides.md is the book's first language, whichever it is; slides.<first>.md is no edition."""
        zh_first = make_book(self.tmp, "zh-first", ["zh", "en"])
        en_first = make_book(self.tmp, "en-first", ["en", "zh"])
        self.assertIsNone(slides.lang_of_file(zh_first, "slides.zh.md"))
        self.assertEqual(slides.edition_file(en_first, "en"), "slides.md")
        self.assertEqual(slides.edition_file(en_first, "zh"), "slides.zh.md")
        self.assertEqual(slides.lang_of_file(en_first, "slides.md"), "en")
        self.assertEqual(slides.lang_of_file(en_first, "slides.zh.md"), "zh")
        self.assertIsNone(slides.lang_of_file(en_first, "slides.en.md"))
        self.assertEqual(slides.site_path(en_first, "overview", "en"), "overview/")
        self.assertEqual(slides.site_path(en_first, "overview", "zh"), "overview/zh/")

    def test_base_path(self):
        site = config.load_site()
        for url, want in [("", "/"), ("https://o.github.io/", "/"), ("https://o.github.io/books/", "/books/"),
                          ("https://o.github.io/books", "/books/"), ("https://example.org/a/b/", "/a/b/")]:
            with mock.patch.object(site, "base_url", url):
                self.assertEqual(slides.base_path(site), want)

    def test_strings_fall_back_to_local_table(self):
        self.assertEqual(slides.t("zh", "pages", n=10), "10 页")
        self.assertEqual(slides.t("en", "pages", n=10), "10 slides")
        self.assertEqual(slides.t("fr", "present"), "Present online")


@needs_example
class ExampleDeckTest(unittest.TestCase):
    def setUp(self):
        self.book = config.load_book("example-monograph")

    def test_page_for_page(self):
        zh = slides.read_edition(self.book, "overview", "zh")
        en = slides.read_edition(self.book, "overview", "en")
        self.assertEqual(zh.count, en.count)
        self.assertTrue(8 <= zh.count <= 10)
        self.assertEqual(zh.head["htmlAttrs"]["lang"], "zh-CN")
        self.assertEqual(en.head["htmlAttrs"]["lang"], "en")
        self.assertEqual(zh.meta["code"], self.book.code)

    @needs_listed_example
    def test_check_passes(self):
        self.assertEqual([i.format() for i in slides.check(self.book)], [])

    @needs_listed_example
    def test_cited_gids_are_locked(self):
        lock = lean.Lock.load()
        gids = {g for _, _, g in slides.cited_gids(self.book)}
        self.assertIn(GID_3V, gids)
        self.assertIn("D5/S0/Certificates/GreathouseLogTwoFloorRefutation.result", gids)
        self.assertIn("D5/S3/ConceptDynamics/Restoration/TargetRecoveryCriterion.target_recovery_criterion", gids)
        for g in gids:
            self.assertIsNotNone(lock.get(g), g)

    def test_items(self):
        it = next(it for it in slides.items(self.book) if it["id"] == "overview")
        self.assertEqual(it["id"], "overview")
        self.assertEqual(it["languages"], ["zh", "en"])
        self.assertEqual(it["href"], {"zh": "slides/overview/", "en": "slides/overview/en/"})
        self.assertEqual(it["pdf"]["en"], "slides/overview/example-monograph-overview-en.pdf")
        self.assertEqual(it["title"], {"zh": "概览", "en": "Overview"})
        self.assertEqual(it["slides"], slides.read_edition(self.book, "overview", "zh").count)

    def test_check_ref(self):
        self.assertIsNone(slides.check_ref(self.book, "overview"))
        self.assertIn("not found", slides.check_ref(self.book, "missing-deck"))
        self.assertIn("kebab-case", slides.check_ref(self.book, "../x"))
        self.assertIn("src", slides.check_ref(self.book, ""))


def _ctx(book, lang, target):
    site = config.load_site()
    return SimpleNamespace(site=site, book=book, edition=book.edition(lang), lang=lang, target=target,
                           issues=[], book_files=set(), book_prefix="_book")


@needs_example
class EmbedTest(unittest.TestCase):
    def setUp(self):
        self.book = config.load_book("example-monograph")
        self.env = SimpleNamespace(attrs={"src": "overview"}, kind="slides")

    def test_mdbook_card(self):
        for chapter, up in [("ch02-refutation-observation.md", "../"), ("part/ch.md", "../../")]:
            doc = SimpleNamespace(path=Path("x.md"), chapter=SimpleNamespace(path=chapter))
            out = slides.render_embed(self.env, _ctx(self.book, "en", "mdbook"), "A caption.", doc)
            self.assertIn('<aside class="tr-media tr-slides"', out)
            self.assertIn(f'href="{up}slides/overview/en/"', out)
            self.assertIn(f'href="{up}slides/overview/example-monograph-overview-en.pdf"', out)
            self.assertIn("\n\nA caption.\n\n", out)  # Markdown inside HTML needs blank lines
            self.assertIn("Present online", out)
        zh = slides.render_embed(self.env, _ctx(self.book, "zh", "mdbook"), "",
                                 SimpleNamespace(path=Path("x.md"), chapter=SimpleNamespace(path="ch01.md")))
        self.assertIn('href="../slides/overview/"', zh)
        self.assertIn("在线演示", zh)

    def test_pandoc_block(self):
        ctx = _ctx(self.book, "zh", "pandoc")
        doc = SimpleNamespace(path=Path("x.md"), chapter=SimpleNamespace(path="ch01.md"))
        with mock.patch.object(ctx.site, "base_url", "https://o.github.io/books/"):
            out = slides.render_embed(self.env, ctx, "图注。", doc)
        self.assertTrue(out.startswith("::: {.tr-media .tr-slides}"))
        self.assertIn("<https://o.github.io/books/example-monograph/slides/overview/>", out)
        self.assertIn("图注。", out)
        self.assertTrue(out.rstrip().endswith(":::"))
        with mock.patch.object(ctx.site, "base_url", ""):
            out = slides.render_embed(self.env, _ctx(self.book, "en", "pandoc"), "", doc)
        self.assertIn("`example-monograph/slides/overview/en/`", out)

    def test_unknown_deck_reports(self):
        ctx = _ctx(self.book, "zh", "mdbook")
        doc = SimpleNamespace(path=Path("x.md"), chapter=SimpleNamespace(path="ch01.md"))
        out = slides.render_embed(SimpleNamespace(attrs={"src": "nope"}), ctx, "", doc)
        self.assertIn("tr-slides", out)
        self.assertTrue(ctx.issues)


@needs_example
class BrokenDeckTest(unittest.TestCase):
    """check() on a scratch copy of the example book with deliberately broken decks."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-slides-"))
        lock = fake_lock()
        lock.declarations = {
            gid: {"module": gid.rsplit(".", 1)[0], "name": gid.rsplit(".", 1)[1],
                  "kind": kind, "statement_id": "sha256:x", "line": 1}
            for gid, kind in ((GID_3V, "theorem"), (GID_INT, "theorem"), (GID_DEF, "def"))
        }
        patch = mock.patch.object(lean.Lock, "load", return_value=lock)
        patch.start()
        self.addCleanup(patch.stop)
        self.bdir = self.tmp / "scratch-book"
        shutil.copytree(EXAMPLE, self.bdir, ignore=shutil.ignore_patterns("slides", "viz", "films"))
        self.deck = self.bdir / "slides" / "d1"
        self.deck.mkdir(parents=True)
        self.theme = slides.theme_ref(self.deck)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def head(self, lang: str, **over) -> str:
        bcp = {"zh": "zh-CN", "en": "en"}[lang]
        fields = {"theme": self.theme, "title": f'"T {lang}"', "bcp": f'"{bcp}"', "version": '"0.1.0"'}
        fields.update(over)
        return (f"---\ntheme: {fields['theme']}\ntitle: {fields['title']}\nhtmlAttrs:\n  lang: {fields['bcp']}\n"
                f"deck:\n  code: \"G//O\"\n  title: \"t\"\n  version: {fields['version']}\nlayout: cover\n---\n\n# cover\n")

    def write(self, lang: str, text: str) -> None:
        (self.deck / slides.edition_file(config.load_book(self.bdir), lang)).write_text(text, encoding="utf-8")

    def issues(self) -> list[str]:
        return [i.message for i in slides.check(config.load_book(self.bdir))]

    def test_good_scratch_deck(self):
        body = f'\n---\nsection: "s"\n---\n\n<TheoremCard label="{{label}}" gid="{GID_3V}" cite="thm-deficit-three-valued">\n\nx\n\n</TheoremCard>\n'
        self.write("zh", self.head("zh") + body.replace("{label}", "定理1.3"))
        self.write("en", self.head("en") + body.replace("{label}", "Theorem 1.3"))
        self.assertEqual(self.issues(), [])

    def test_missing_edition_and_bad_headmatter(self):
        self.write("zh", self.head("zh", theme="../theme/slides", bcp='"zh"', title='"a <b>"'))
        msgs = "\n".join(self.issues())
        self.assertIn("has no slides.en.md", msgs)
        self.assertIn("theme:", msgs)
        self.assertIn('htmlAttrs.lang: "zh-CN"', msgs)
        self.assertIn("must not contain <", msgs)

    def test_parity_and_citations(self):
        self.write("zh", self.head("zh") + f'\n---\n\n<LeanBadge gid="{GID_3V}" />\n\n---\n\nthree\n')
        self.write("en", self.head("en", version='"0.2.0"') + f'\n---\nlayout: section\n---\n\n<LeanBadge gid="{GID_INT}" />\n')
        msgs = "\n".join(self.issues())
        self.assertIn("2 slides, but", msgs)
        self.assertIn("deck.version", msgs)
        self.assertIn("slide 2: layout", msgs)
        self.assertIn(f"cites [{GID_INT}]", msgs)

    def test_lean_rules(self):
        body = (
            '\n---\n\n<LeanBadge gid="D5/S1/Deficit/Nope.missing" />\n'
            f'<TheoremCard label="x" gid="{GID_DEF}">\n\ns\n\n</TheoremCard>\n'
            f'<TheoremCard label="x" status="open" gid="{GID_3V}">\n\ns\n\n</TheoremCard>\n'
            '<LeanBadge />\n<LeanBadge gid="not a gid" />\n'
            '<a href="/abs/path">x</a> [y](/z) <img src="file:///tmp/x.png">\n'
        )
        self.write("zh", self.head("zh") + body)
        self.write("en", self.head("en") + body)
        msgs = "\n".join(self.issues())
        self.assertIn("Nope.missing is not in trureturing.lock.json", msgs)
        self.assertIn("is a Lean def; a TheoremCard must cite a theorem", msgs)
        self.assertIn('status="open"> must not cite Lean', msgs)
        self.assertIn('needs gid="<GID>"', msgs)
        self.assertIn("not a declaration GID", msgs)
        self.assertIn("link /abs/path is absolute", msgs)
        self.assertIn("link /z is absolute", msgs)
        self.assertIn("link file:///tmp/x.png is absolute", msgs)

    def test_cite_must_match_the_book(self):
        zh = (self.head("zh") + f'\n---\n\n<TheoremCard label="定理9.9" gid="{GID_INT}" cite="thm-deficit-three-valued">\n\ns\n\n</TheoremCard>\n'
              '<TheoremCard label="开放问题2.2" cite="prob-greathouse-minimal">\n\ns\n\n</TheoremCard>\n'
              '<TheoremCard label="x" status="open" cite="no-such-env">\n\ns\n\n</TheoremCard>\n')
        self.write("zh", zh)
        self.write("en", zh.replace("zh-CN", "en").replace("T zh", "T en"))
        msgs = [m for m in self.issues() if "slides.md" in m or True]
        joined = "\n".join(msgs)
        self.assertIn("label is '定理9.9' but the book numbers it '定理1.3'", joined)
        self.assertIn(f"cites {GID_INT}, the book cites {GID_3V}", joined)
        self.assertIn('is a problem; use status="open"', joined)
        self.assertIn("no environment #no-such-env", joined)

    def test_stray_files(self):
        self.write("zh", self.head("zh"))
        self.write("en", self.head("en"))
        (self.deck / "slides.fr.md").write_text(self.head("en"), encoding="utf-8")
        (self.deck / "index.html").write_text("<p>x</p>", encoding="utf-8")
        msgs = "\n".join(self.issues())
        self.assertIn("'fr' is not an edition of this book", msgs)
        self.assertIn("index.html", msgs)


@needs_example
class PublishTest(unittest.TestCase):
    def setUp(self):
        # This fixture builds only the original Slidev deck; academic publication
        # has its own scratch-book integration test in test_academic.
        patch = mock.patch.object(slides, "deck_names", return_value=["overview"])
        patch.start()
        self.addCleanup(patch.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-slides-pub-"))
        self.book = config.load_book("example-monograph")
        self.site = config.load_site()
        self.out = self.tmp / "build"
        base = slides.base_path(self.site)
        langs = {}
        for lang in ("zh", "en"):
            d = self.out / "overview" / lang
            (d / "assets").mkdir(parents=True)
            (d / "index.html").write_text(f"<!doctype html><title>{lang}</title>", encoding="utf-8")
            (d / "assets" / "a.js").write_text("//", encoding="utf-8")
            (self.out / f"overview-{lang}.pdf").write_bytes(b"%PDF-1.7 fake")
            langs[lang] = {"title": lang, "info": "", "blurb": "", "slides": 10, "dir": f"overview/{lang}/",
                           "site_path": slides.site_path(self.book, "overview", lang), "base": base,
                           "pdf": f"overview-{lang}.pdf", "pdf_name": slides.pdf_name(self.book, "overview", lang)}
        (self.out / "manifest.json").write_text(json.dumps(
            {"schema": slides.MANIFEST_SCHEMA, "book": self.book.slug, "base": base, "decks": {"overview": {"langs": langs}}}),
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_publish_layout_and_index(self):
        site_dir = self.tmp / "_site" / self.book.slug / "slides"
        (site_dir / "overview" / "stale.txt").parent.mkdir(parents=True)
        (site_dir / "overview" / "stale.txt").write_text("old", encoding="utf-8")
        with mock.patch.object(slides, "build_dir", lambda book: self.out):
            published = slides.publish(self.site, self.book, site_dir, build_missing=False)
        self.assertEqual([p["id"] for p in published], ["overview"])
        self.assertTrue((site_dir / "overview" / "index.html").is_file())
        self.assertTrue((site_dir / "overview" / "assets" / "a.js").is_file())
        self.assertTrue((site_dir / "overview" / "en" / "index.html").is_file())
        self.assertTrue((site_dir / "overview" / "example-monograph-overview-zh.pdf").is_file())
        self.assertTrue((site_dir / "overview" / "example-monograph-overview-en.pdf").is_file())
        self.assertFalse((site_dir / "overview" / "stale.txt").exists())
        index = (site_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="overview/"', index)
        self.assertIn('href="overview/en/"', index)
        self.assertIn('href="overview/example-monograph-overview-en.pdf"', index)
        self.assertIn("在线演示", index)
        self.assertIn("Present online", index)
        self.assertIn("--tr-void", index)  # colours come from the generated tokens
        self.assertNotIn('href="/', index)  # only relative links

    def test_stale_build_is_refused_without_building(self):
        with mock.patch.object(slides, "build_dir", lambda book: self.out), \
                mock.patch.object(self.site, "base_url", "https://o.github.io/other/"):
            with self.assertRaisesRegex(RuntimeError, "built for base"):
                slides.publish(self.site, self.book, self.tmp / "s", build_missing=False)


@needs_example
@needs_listed_example
@unittest.skipUnless(HAVE_NODE, "node and node_modules needed")
class CliNewTest(unittest.TestCase):
    """./tbook slides new in a scratch repository root, then ./tbook check on it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-slides-new-"))
        for name in ("theme", "templates", "tools", "node_modules"):
            (self.tmp / name).symlink_to(ROOT / name)
        for name in ("site.toml", "trureturing.lock.json"):
            shutil.copy2(ROOT / name, self.tmp / name)
        (self.tmp / "books").mkdir()
        shutil.copytree(EXAMPLE, self.tmp / "books" / "bk", ignore=shutil.ignore_patterns("slides", "viz", "films"))
        self.env = dict(os.environ, TBOOK_ROOT=str(self.tmp), PYTHONPATH=str(ROOT / "tools"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tbook(self, *args):
        return subprocess.run([sys.executable, "-m", "tbook", *args], cwd=self.tmp, env=self.env,
                              capture_output=True, text=True)

    def test_new_then_check(self):
        r = self.tbook("slides", "new", "bk", "intro", "入门 \"概览\"", "Getting started")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        zh = (self.tmp / "books" / "bk" / "slides" / "intro" / "slides.md").read_text(encoding="utf-8")
        en = (self.tmp / "books" / "bk" / "slides" / "intro" / "slides.en.md").read_text(encoding="utf-8")
        self.assertIn('title: "入门 \\"概览\\""', zh)
        self.assertIn('lang: "zh-CN"', zh)
        self.assertIn('lang: "en"', en)
        self.assertIn('version: "0.1.0"', en)
        self.assertEqual(slides.count_slides(zh), slides.count_slides(en))
        self.assertNotIn("{{", zh + en)
        r = self.tbook("slides", "new", "bk", "intro", "x", "y")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already exists", r.stderr)
        r = self.tbook("slides", "new", "bk", "Bad_Name", "x", "y")
        self.assertEqual(r.returncode, 2)
        r = self.tbook("slides", "list")
        self.assertIn("bk/intro", r.stdout)
        if os.environ.get("TRURETURING_DIR") or (ROOT.parent / "trureturing" / ".git").exists():
            r = self.tbook("check", "--offline", "--book", "bk")
            slide_errors = [line for line in r.stdout.splitlines() if "slides/intro" in line]
            self.assertEqual(slide_errors, [], r.stdout)


class ScratchDeckCase(unittest.TestCase):
    """A scratch book with one deck d1 (no example book needed) and the fake lock."""

    EDITIONS = ["zh", "en"]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-slides-scratch-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.book = make_book(self.tmp, "scratch-book", self.EDITIONS)
        self.deck = self.book.slides_dir / "d1"
        self.deck.mkdir(parents=True)
        p = mock.patch.object(lean.Lock, "load", return_value=fake_lock())
        p.start()
        self.addCleanup(p.stop)

    def head(self, lang: str, **over) -> str:
        return deck_head(slides.theme_ref(self.deck), lang, **over)

    def write(self, lang: str, text: str) -> None:
        (self.deck / slides.edition_file(self.book, lang)).write_text(text, encoding="utf-8")

    def issues(self) -> list[str]:
        return [i.message for i in slides.check(config.load_book(self.book.dir))]


class FirstLanguageTest(ScratchDeckCase):
    """Finding: slides.md is the book's first language; slides.<first>.md is reported, not shadowed."""

    EDITIONS = ["en", "zh"]

    def write_both(self, body: str = "") -> None:
        self.write("en", self.head("en") + body)
        self.write("zh", self.head("zh") + body)

    def test_english_first_book(self):
        self.write_both(f'\n---\n\n<LeanBadge gid="{FAKE_THM}" />\n')
        self.assertEqual(sorted(p.name for p in self.deck.iterdir()), ["slides.md", "slides.zh.md"])
        self.assertEqual(self.issues(), [])
        self.assertEqual(slides.deck_langs(self.book, "d1"), ["en", "zh"])
        self.assertEqual(slides.read_edition(self.book, "d1", "en").head["htmlAttrs"]["lang"], "en")
        self.assertEqual(slides.read_edition(self.book, "d1", "zh").path.name, "slides.zh.md")
        (it,) = slides.items(self.book)
        self.assertEqual(it["languages"], ["en", "zh"])
        self.assertEqual(it["href"], {"en": "slides/d1/", "zh": "slides/d1/zh/"})
        self.assertIsNone(slides.check_ref(self.book, "d1"))

    def test_first_language_file_is_reported(self):
        self.write_both()
        (self.deck / "slides.en.md").write_text(self.head("en"), encoding="utf-8")
        msgs = self.issues()
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("en is the book's first language, whose edition is slides.md", msgs[0])
        self.assertEqual(slides.deck_langs(self.book, "d1"), ["en", "zh"])  # no duplicate, nothing shadowed

    def test_zh_named_file_in_a_chinese_first_book(self):
        zh_first = make_book(self.tmp, "zh-book", ["zh", "en"])
        d = zh_first.slides_dir / "d1"
        d.mkdir(parents=True)
        theme = slides.theme_ref(d)
        (d / "slides.md").write_text(deck_head(theme, "zh"), encoding="utf-8")
        (d / "slides.en.md").write_text(deck_head(theme, "en"), encoding="utf-8")
        (d / "slides.zh.md").write_text(deck_head(theme, "zh"), encoding="utf-8")
        msgs = [i.message for i in slides.check(zh_first)]
        self.assertTrue(any("zh is the book's first language" in m for m in msgs), msgs)
        self.assertEqual(slides.deck_langs(zh_first, "d1"), ["zh", "en"])
        self.assertEqual([it["languages"] for it in slides.items(zh_first)], [["zh", "en"]])

    def test_english_first_publish_layout(self):
        self.write_both()
        out = fake_build(self.book, self.tmp / "build", pdfs=("en",))
        site_dir = self.tmp / "_site" / "slides"
        with mock.patch.object(slides, "build_dir", lambda book: out):
            slides.publish(config.load_site(), self.book, site_dir, build_missing=False)
        self.assertIn("<title>en</title>", (site_dir / "d1" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("<title>zh</title>", (site_dir / "d1" / "zh" / "index.html").read_text(encoding="utf-8"))
        self.assertTrue((site_dir / "d1" / "scratch-book-d1-en.pdf").is_file())
        index = (site_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="d1/"', index)
        self.assertIn('href="d1/zh/"', index)
        self.assertIn("scratch-book-d1-en.pdf", index)
        self.assertNotIn("scratch-book-d1-zh.pdf", index)  # built without the zh PDF


class StaleBuildTest(ScratchDeckCase):
    """Finding: a slides build made before the book's first language (or its languages) changed put every
    edition at the old path; publish must rebuild it, or refuse with the reason."""

    def set_editions(self, editions: list[str]) -> config.Book:
        toml = self.book.dir / "book.toml"
        text = toml.read_text(encoding="utf-8")
        old, new = (f"editions = {json.dumps(langs)}" for langs in (self.book.languages, editions))
        toml.write_text(text.replace(old, new), encoding="utf-8")
        self.book = config.load_book(self.book.dir)
        self.assertEqual(self.book.languages, editions)
        return self.book

    def test_first_language_change(self):
        self.write("zh", self.head("zh"))
        self.write("en", self.head("en"))
        out = fake_build(self.book, self.tmp / "build")
        base = slides.base_path(config.load_site())
        self.assertEqual(slides._stale(self.book, out, slides.read_manifest(out), base), "")
        # English first now: the files are renamed as check requires, the build is not
        (self.deck / "slides.md").rename(self.deck / "slides.zh.md")
        (self.deck / "slides.en.md").rename(self.deck / "slides.md")
        book = self.set_editions(["en", "zh"])
        self.assertEqual(self.issues(), [])
        why = slides._stale(book, out, slides.read_manifest(out), base)
        self.assertEqual(why, "d1 (en) was built for 'd1/en/', the site uses 'd1/' (en is the book's first language)")
        site_dir = self.tmp / "_site" / "slides"
        with mock.patch.object(slides, "build_dir", lambda b: out):
            with self.assertRaisesRegex(RuntimeError, r"d1 \(en\) was built for 'd1/en/'.*run ./tbook build slides"):
                slides.publish(config.load_site(), book, site_dir, build_missing=False)
            self.assertFalse((site_dir / "d1").exists())

            def rebuild(site, b, out_dir):
                shutil.rmtree(out_dir)
                return fake_build(b, out_dir)

            with mock.patch.object(slides, "build", side_effect=rebuild) as build:
                slides.publish(config.load_site(), book, site_dir)
            build.assert_called_once()
        self.assertIn("<title>en</title>", (site_dir / "d1" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("<title>zh</title>", (site_dir / "d1" / "zh" / "index.html").read_text(encoding="utf-8"))
        self.assertFalse((site_dir / "d1" / "en").exists())

    def test_dropped_language(self):
        """The built decks link every language they were built with: drop one and they link a missing page."""
        self.write("zh", self.head("zh"))
        self.write("en", self.head("en"))
        out = fake_build(self.book, self.tmp / "build")
        (self.deck / "slides.en.md").unlink()
        book = self.set_editions(["zh"])
        why = slides._stale(book, out, slides.read_manifest(out), slides.base_path(config.load_site()))
        self.assertEqual(why, "d1 was built with en as well, which is no longer an edition of it")


class PublishedPdfLinkTest(ScratchDeckCase):
    """Finding: with a PDF-less slides build (TBOOK_SLIDES_NO_PDF=1), chapter cards must not link PDFs
    that are never published, even when the chapters were built (with the link) before."""

    def test_unpublished_pdf_links_are_removed(self):
        self.write("zh", self.head("zh"))
        self.write("en", self.head("en"))
        out = fake_build(self.book, self.tmp / "build", pdfs=("zh",))  # the en PDF was not built
        book_site = self.tmp / "_site"
        env = SimpleNamespace(attrs={"src": "d1"}, kind="slides")
        pages = {}
        for lang, rel in (("zh", "ch01.html"), ("en", "ch01.html"), ("en", "part/ch02.html"), ("en", "print.html")):
            doc = SimpleNamespace(path=Path("x.md"), chapter=SimpleNamespace(path=rel.replace(".html", ".md")))
            card = slides.render_embed(env, _ctx(self.book, lang, "mdbook"), "", doc)
            card = card.replace(" download>", ' download="">')  # as mdBook writes it
            page = book_site / lang / rel
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(card + '\n<a href="../downloads/book.pdf">book</a>\n', encoding="utf-8")
            pages[(lang, rel)] = page
        with mock.patch.object(slides, "build_dir", lambda book: out):
            slides.publish(config.load_site(), self.book, book_site / "slides", build_missing=False)
        zh = pages[("zh", "ch01.html")].read_text(encoding="utf-8")
        self.assertIn('href="../slides/d1/scratch-book-d1-zh.pdf"', zh)
        self.assertTrue((book_site / "slides" / "d1" / "scratch-book-d1-zh.pdf").is_file())
        for rel in ("ch01.html", "part/ch02.html", "print.html"):
            en = pages[("en", rel)].read_text(encoding="utf-8")
            self.assertNotIn("scratch-book-d1-en.pdf", en, rel)
            self.assertIn("slides/d1/en/", en)  # the other links stay
            self.assertIn("downloads/book.pdf", en)
        self.assertFalse((book_site / "slides" / "d1" / "scratch-book-d1-en.pdf").exists())


class CitationSpellingTest(ScratchDeckCase):
    """Finding: green LEAN ✓ only for Lean theorems; kebab-case component tags are checked too."""

    def test_vue_spellings_resolve_to_the_components(self):
        found, _ = slides.citations(
            '<lean-badge gid="A" /> <leanBadge gid="B"/> <theorem-card label="x" gid="C">s</theorem-card>\n'
            '<Lean-Badge gid="D" /> <lean-badge-x gid="E" /> <LeanBadgeX gid="F" /> <leanbadge gid="G" />')
        self.assertEqual([(c.tag, c.gid) for c in found],
                         [("LeanBadge", "A"), ("LeanBadge", "B"), ("TheoremCard", "C"), ("LeanBadge", "D")])
        self.assertEqual(slides.component("theorem-card"), "TheoremCard")

    def test_kebab_case_and_non_theorems_are_checked(self):
        body = ('\n---\n\n<lean-badge gid="D5/S9/Fake/Nope.not_locked" />\n'
                f'<theorem-card label="x" gid="{FAKE_DEF}">\n\ns\n\n</theorem-card>\n'
                f'<LeanBadge gid="{FAKE_DEF}" />\n'
                f'<leanBadge gid="{FAKE_THM}" />\n'
                f'<lean-badge kind="definition" gid="{FAKE_DEF}" />\n'
                f'<TheoremCard kind="definition" label="d" gid="{FAKE_DEF}">\n\ns\n\n</TheoremCard>\n')
        self.write("zh", self.head("zh") + body)
        self.write("en", self.head("en") + body)
        msgs = self.issues()
        want = {"D5/S9/Fake/Nope.not_locked is not in trureturing.lock.json",
                f'{FAKE_DEF} is a Lean def; a TheoremCard must cite a theorem (or say kind="definition")',
                f'{FAKE_DEF} is a Lean def; a LeanBadge must cite a theorem (or say kind="definition")'}
        self.assertEqual(len(msgs), 6, msgs)  # three per edition
        for w in want:
            self.assertEqual(sum(w in m for m in msgs), 2, (w, msgs))
        self.assertIn("D5/S9/Fake/Nope.not_locked", {g for _, _, g in slides.cited_gids(self.book)})

    def test_slide_imports_are_rejected(self):
        body = "\n---\nsrc: ./more.md\n---\n"
        self.write("zh", self.head("zh") + body)
        self.write("en", self.head("en") + body)
        msgs = self.issues()
        self.assertEqual(len(msgs), 2, msgs)
        self.assertTrue(all("src: imports slides from another file" in m for m in msgs), msgs)


# Tags as Slidev reads them: its Markdown hands a tag to Vue only where a complete open tag starts at the '<'. A '<'
# that starts none ($a <b + 1$, a <b in prose) is text, and so is a '<' in a code span or after a backslash, even
# where a complete tag starts: the tag after it is rendered (all checked against the components Vue compiles from
# Slidev's Markdown in NodeTagScanTest). Findings: the scan ran from such a '<' to the next '>', past the tag.
LONE_LT = {
    "a < in inline math (finding)": 'For all $a <b + 1$ the claim holds <LeanBadge gid="x" />',
    "two in inline math, a TheoremCard on later lines (finding)":
        'If $0 <x <1$ then\n\n<TheoremCard label="T" gid="x">\nbody\n</TheoremCard>',
    "a < in prose, the tag on the next line": 'a <b and\n<lean-badge gid="x"/> c',
    "a quoted value from one code span to the next": "`<b x='` <LeanBadge gid=\"x\" /> `'>`",
    "a quoted value after an escaped <": "\\<b x='y <LeanBadge gid=\"x\" /> '>",
}
# A component tag that is not complete: text in a paragraph, rendered by Vue in an HTML block (#slot is no attribute
# name to Slidev's Markdown), unchecked either way, so reported.
INCOMPLETE_TAG = '<LeanBadge gid="x" #foo />'
LONE_LT_GIDS = [f"D5/S9/Lt/Case.c{i}" for i in range(len(LONE_LT) + 1)]
LONE_LT_DECK = "".join("\n---\n\n" + text.replace('gid="x"', f'gid="{gid}"')
                       for gid, text in zip(LONE_LT_GIDS, [*LONE_LT.values(), INCOMPLETE_TAG]))

# The gid prop as Vue's compiler passes it (checked against it in NodeTagScanTest): of gid, :gid and v-bind:gid the
# first in the tag wins; :gid.<modifier> and v-model:gid bind it too, and a v-bind without an argument merges an
# object over the attributes before it. (tag, the gid Vue renders (None: not a string literal, or an object merged
# in), the gid the checks read (None: the slide reports the tag)); '@' is a GID the fake lock has (FAKE_THM).
# Findings: the checks read the static gid where Vue renders v-bind:gid or the object, and :gid where Vue renders
# the static gid.
GID_BINDINGS = [
    ("<LeanBadge v-bind:gid=\"'D5/S9/Bind/Vue.long_first'\" gid=\"@\" />", "D5/S9/Bind/Vue.long_first",
     "D5/S9/Bind/Vue.long_first"),
    ("<LeanBadge gid=\"D5/S9/Bind/Vue.static_first\" :gid=\"'@'\" />", "D5/S9/Bind/Vue.static_first",
     "D5/S9/Bind/Vue.static_first"),
    ("<LeanBadge :gid=\"'D5/S9/Bind/Vue.short_first'\" v-bind:gid=\"'@'\" />", "D5/S9/Bind/Vue.short_first",
     "D5/S9/Bind/Vue.short_first"),
    ('<theorem-card v-bind:gid="`D5/S9/Bind/Vue.long_only`" status="argued">s</theorem-card>',
     "D5/S9/Bind/Vue.long_only", "D5/S9/Bind/Vue.long_only"),
    ('<LeanBadge gid="D5/S9/Bind/Vue.before_expr" :gid="x" />', "D5/S9/Bind/Vue.before_expr",
     "D5/S9/Bind/Vue.before_expr"),
    ("<LeanBadge gid=\"D5/S9/Bind/Vue.later\" v-bind:gid=\"'@'\" :gid.camel=\"'@'\" v-model:gid=\"m\" />",
     "D5/S9/Bind/Vue.later", "D5/S9/Bind/Vue.later"),
    # not gid: another prop, an argument that is not gid, an attribute that is no directive (Vue's are lower case)
    ("<LeanBadge v-bind:kind=\"'theorem'\" :gid:x=\"'@'\" V-BIND:gid=\"'@'\" gid=\"D5/S9/Bind/Vue.other\" />",
     "D5/S9/Bind/Vue.other", "D5/S9/Bind/Vue.other"),
    # a v-on object starts a group of props that Vue merges over the earlier ones: its first gid wins
    ("<LeanBadge gid=\"@\" v-on=\"{}\" :gid=\"'D5/S9/Bind/Vue.on_group'\" v-bind:gid=\"'@'\" />",
     "D5/S9/Bind/Vue.on_group", "D5/S9/Bind/Vue.on_group"),
    ("<LeanBadge gid=\"D5/S9/Bind/Vue.on_kept\" :gid=\"'@'\" v-on.x=\"{}\" />",
     "D5/S9/Bind/Vue.on_kept", "D5/S9/Bind/Vue.on_kept"),
    ("<LeanBadge gid=\"@\" v-bind=\"{ gid: 'D5/S9/Bind/Vue.spread' }\" />", None, None),
    ("<LeanBadge v-bind=\"{ gid: 'D5/S9/Bind/Vue.spread_first' }\" gid=\"@\" />", None, None),
    ("<lean-badge gid=\"@\" :=\"{ gid: 'D5/S9/Bind/Vue.short_spread' }\" />", None, None),
    ("<LeanBadge gid=\"@\" v-bind:.prop=\"{ gid: 'D5/S9/Bind/Vue.prop_spread' }\" />", None, None),
    ("<LeanBadge :gid.camel=\"'D5/S9/Bind/Vue.modifier'\" gid=\"@\" />", "D5/S9/Bind/Vue.modifier", None),
    ('<LeanBadge v-model:gid="x" gid="@" />', None, None),
]
GID_BINDINGS = [(text.replace("@", FAKE_THM), rendered, checked) for text, rendered, checked in GID_BINDINGS]
# A slide per tag, and how the messages of the checks on it begin, slide by slide (the gid of a tag reported for a
# modifier or v-model is none: it needs one)
GID_BINDING_DECK = "".join(f"\n---\n\n{text}\n" for text, _, _ in GID_BINDINGS)
GID_BINDING_ISSUES = [
    *(f"{checked} is not in trureturing.lock.json" for _, _, checked in GID_BINDINGS[:9]),
    "<LeanBadge v-bind=…>: an object bound", "<LeanBadge v-bind=…>: an object bound",
    "<lean-badge :=…>: an object bound", "<LeanBadge v-bind:.prop=…>: an object bound",
    "<LeanBadge :gid.camel=\"'D5/S9/Bind/Vue.modifier'\">: write gid", "<LeanBadge> needs gid=",
    '<LeanBadge v-model:gid="x">: write gid', "<LeanBadge> needs gid=",
]


class TagScanTest(unittest.TestCase):
    """Finding: a '<' that starts no complete tag hid the next LeanBadge / TheoremCard from the checks. citations()
    tries a complete tag (as Slidev's Markdown reads one) at every '<' and reports a component tag that is not
    complete."""

    def test_a_lone_lt_hides_no_tag(self):
        for name, text in LONE_LT.items():
            found, problems = slides.citations(text)
            self.assertEqual([c.gid for c in found], ["x"], name)
            self.assertEqual(problems, [], name)

    def test_attributes_as_html_writes_them(self):
        # unquoted values, spaces around =, attributes on several lines, Vue's own; the tag in the span's quoted value
        # is checked as well: where Slidev's Markdown reads the span's '<' as text, the quotes are no attribute value
        found, problems = slides.citations(
            "<LeanBadge gid=D5/S1/A.b /> <lean-badge kind = definition\tgid='D5/S1/A.c'/>\n"
            '<TheoremCard\n  label="a > b"\n  gid="D5/S1/A.d"\n  v-click\n  :class="{ x: y }"\n>\n\ns\n\n</TheoremCard>\n'
            '<LeanBadge status=open gid="" /> <LeanBadge :gid="\'D5/S1/A.e\'" /> <span title="<LeanBadge gid=\'in\'/>">')
        self.assertEqual(problems, [])
        self.assertEqual([(c.tag, c.gid) for c in found],
                         [("LeanBadge", "D5/S1/A.b"), ("LeanBadge", "D5/S1/A.c"), ("TheoremCard", "D5/S1/A.d"),
                          ("LeanBadge", ""), ("LeanBadge", "D5/S1/A.e"), ("LeanBadge", "in")])
        self.assertEqual(found[1].attrs, {"kind": "definition", "gid": "D5/S1/A.c"})
        self.assertEqual(found[2].attrs, {"label": "a > b", "gid": "D5/S1/A.d", "v-click": True, ":class": "{ x: y }"})
        self.assertEqual(found[3].attrs, {"status": "open", "gid": ""})

    def test_incomplete_component_tags_are_reported(self):
        for text in (INCOMPLETE_TAG, '<div>\n<lean-badge gid="x" v-bind:[k]="v"/>\n</div>',
                     '<TheoremCard gid="a"b="c">\n\ns\n\n</TheoremCard>', 'text <leanBadge gid="x"', "<LeanBadge",
                     '<LeanBadge gid="x"/ >'):
            found, problems = slides.citations(text)
            self.assertEqual(found, [], text)
            self.assertEqual(len(problems), 1, (text, problems))
            self.assertIn("is not a complete tag", problems[0])
        # other names, or a name that Vue reads on past the component's: no component tag
        for text in ("a <b + 1", '<LeanBadgeX gid="x"', '<lean-badge_x gid="x"', '<LeanBadge.x gid="x"',
                     '<TheoremCard\u3000gid="x"', "<LeanBadge\u0085"):
            self.assertEqual(slides.citations(text), ([], []), text)

    def test_gid_is_read_as_vue_passes_it(self):
        """Findings: the first of gid, :gid and v-bind:gid is the gid (Vue keeps the first); a v-bind object, a
        modifier or v-model on gid is reported."""
        for text, rendered, checked in GID_BINDINGS:
            found, problems = slides.citations(text)
            self.assertEqual(len(found), 1, text)
            if checked is None:
                self.assertEqual(len(problems), 1, (text, problems))
            else:
                self.assertEqual((found[0].gid, problems), (checked, []), text)
                self.assertEqual(checked, rendered)
        for text, want in (('<LeanBadge v-bind="{ gid: \'x\' }" gid="a" />', '<LeanBadge v-bind=…>: an object bound'),
                           ('<LeanBadge :.prop="o" />', '<LeanBadge :.prop=…>: an object bound'),
                           ("<LeanBadge :gid.prop=\"'x'\" gid=\"a\" />", '<LeanBadge :gid.prop="\'x\'">: write gid'),
                           ('<LeanBadge v-model:gid="m" />', '<LeanBadge v-model:gid="m">: write gid'),
                           ('<LeanBadge v-bind:gid="m" />', '<LeanBadge v-bind:gid="m">: write gid as a literal')):
            self.assertTrue(slides.citations(text)[1][0].startswith(want), (text, slides.citations(text)))
        # a v-on with an argument binds one listener and starts no group (Vue: { onClick: f, gid: "a" })
        found, problems = slides.citations('<LeanBadge gid="a" @click="f" v-on:x="g" :gid="\'b\'" />')
        self.assertEqual(([c.gid for c in found], problems), (["a"], []))

    def test_scan_is_linear(self):
        """The tag scan (citations() and slides-lib.mjs citations()) stays linear in the slide's size, also on
        thousands of tags, tags left open and many attributes: each input takes about 0.1 s, the bound is generous."""
        tags = "".join(f"<LeanBadge v-bind:gid=\"'D5/S9/G/M.g{i}'\" gid=\"x\" v-click kind=definition />\n"
                       for i in range(3000))
        inputs = [tags, "<LeanBadge" + " a=1 :gid='x'" * 20000, '<LeanBadge gid="' * 5000,
                  "<b c='<LeanBadge v-bind:gid=1 " * 5000, "<LeanBadge v-bind " * 5000,
                  '<b c="' + "<LeanBadge a=1 " * 5000 + '">', "<LeanBadge" + " v-bind:gid.a.b=1 :=x" * 20000 + " />",
                  "\n".join(f"<lean-badge :gid=\"'a{i}'\" v-bind=\"o\" />" for i in range(10000))]
        for text in inputs:
            t = time.monotonic()
            slides.citations(text)
            self.assertLess(time.monotonic() - t, 2.0)
        self.assertEqual(len(slides.citations(tags)[0]), 3000)
        if not HAVE_NODE:
            return
        script = ("import { readFileSync } from 'node:fs';"
                  "const { citations } = await import(process.argv[1]);"
                  "const times = JSON.parse(readFileSync(0, 'utf8')).map((text) => {"
                  "  const t = performance.now(); citations(text); return (performance.now() - t) / 1000; });"
                  "process.stdout.write(JSON.stringify(times));")
        r = subprocess.run([NODE, "--input-type=module", "-e", script,
                            (ROOT / "tools" / "node" / "slides-lib.mjs").as_uri()],
                           input=json.dumps(inputs), capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        for seconds in json.loads(r.stdout):
            self.assertLess(seconds, 2.0)


# Code as Slidev's Markdown (markdown-exit set up as Slidev sets it up) reads it: (name, Markdown, indices of the
# lines shown as code).
FENCE_CASES = [
    ("a tag between two code blocks", '# t\n\n```js\ncode\n```\n\n<LeanBadge gid="x" />\n\n```\nmore\n```\n',
     {2, 3, 4, 8, 9, 10}),
    ("tildes, a longer closer", "~~~~\n~~~\n```\n~~~~~\nafter", {0, 1, 2, 3}),
    ("the closer has the opener's character, no info, at least its length", "````\n~~~~\n```` x\n```\n`````\nafter",
     {0, 1, 2, 3, 4}),
    ("a backtick in the info string: not a fence", '``` a`b\n<LeanBadge gid="x" />\n```\ny', {2, 3}),
    ("indented 4 columns: indented code, not a fence", 'text\n\n    ```\n\n<LeanBadge gid="x" />\n\n    ```\nz',
     {2, 6}),
    ("an unclosed fence runs to the end", 'a\n\n```\n<LeanBadge gid="x" />', {2, 3}),
    ("a fence in a list item ends with it", '- ```js\n  <LeanBadge gid="in" />\n  ```\n\n<LeanBadge gid="out" />\n\n'
     '```\nx\n```', {0, 1, 2, 6, 7, 8}),
    ("a fence in a block quote ends with it", '> ```\n> code\n\n<LeanBadge gid="out" />\n\n```\nx\n```',
     {0, 1, 5, 6, 7}),
    ("no lazy line in a quoted fence", "> ```\n> a\nb\n", {0, 1}),
    ("``` inside an HTML block is HTML", '<div>\n```\n<LeanBadge gid="x" />\n```\n</div>', set()),
    ("a component line starts an HTML block up to a blank line", "<v-click>\n```\nx\n```\n</v-click>\n\n```\ny\n```",
     {6, 7, 8}),
    ("CRLF and tabs (a tab indents to column 4: indented code)", "```\r\ncode\r\n```\r\n\t```\r\nafter", {0, 1, 2, 3}),
    ("nested list items", "1. a\n\n   - b\n\n     ```\n     c\n     ```\nd", {4, 5, 6}),
    ("a footnote holds its indented fence", "x[^1]\n\n[^1]: note\n\n    ```\n    c\n    ```\nd", {4, 5, 6}),
    # GFM tables: a header row and a delimiter row open one; it takes no lazy line and ends at a blank line, a
    # line indented 4 columns, a line outside its containers or a block that may interrupt a block quote
    ("a table in a block quote ends at a lazy line, which starts an HTML block (finding)",
     '> | a | b |\n> |---|---|\n<span>\n```js\n<LeanBadge gid="x" />\n```\n</span>\n', set()),
    ("a table in a list item ends at an outdented line (finding)",
     '- | a | b |\n  |---|---|\n<v-click>\n```js\n<LeanBadge gid="x" />\n```\n</v-click>\n', set()),
    ("a table ends at a line indented 4 columns: indented code (finding)",
     '| a | b |\n|---|---|\n| 1 | 2 |\n    x\n<span>\n```\n<LeanBadge gid="x" />\n```\n</span>\n', {3}),
    ("a delimiter row without pipes at the ends opens a table too (finding)",
     'a | b\n-|-\n    >\n</TheoremCard>\n```\n<LeanBadge gid="x" />\n```\n', {2}),
    ("a table row needs no pipe; a fence ends the table", "| a |\n|---|\n<span>\n```\nx\n```", {3, 4, 5}),
    ("a table interrupts a paragraph; a line indented 4 columns after it is code",
     'text\n| a |\n|---|\n    <LeanBadge gid="x" />', {3}),
    ("different cell counts: no table", '| a | b |\n|---|\n    <LeanBadge gid="x" />', set()),
    # whitespace after a tag name is JavaScript's \s; tag names fold case in ASCII only
    ("U+3000 after a block tag name: an HTML block (finding)",
     'text\n<div\u3000class="x">\n```\n<LeanBadge gid="x" />\n```\n', set()),
    ("U+00A0 likewise (finding)", 'text\n<div\u00a0class="x">\n```\n<LeanBadge gid="x" />\n```\n', set()),
    ("U+FEFF likewise (finding)", 'text\n<div\ufeff/>\n```\n<LeanBadge gid="x" />\n```\n', set()),
    ("U+0085 is no space in JavaScript: no HTML block", "text\n<div\u0085/>\n```\nx\n```\n", {2, 3, 4}),
    ("long s does not fold to s", "<\u017ftyle>\n```\nx\n```", {1, 2, 3}),
    # HTML blocks as @mdit-vue/plugin-component reads them
    ("a component tag interrupts a paragraph", 'text\n<v-click>\n```\n<LeanBadge gid="x" />\n```\n</v-click>\n',
     set()),
    ("a self-closing component fills just its line", '<LeanBadge gid="x" />\n```\ncode\n```\n', {1, 2, 3}),
    ("so does a component opened and closed on its line", "<Stat>4</Stat>\n```\nx\n```", {1, 2, 3}),
    ("an inline HTML tag cannot interrupt a paragraph", "text\n<span>\n```\nx\n```\n</span>", {2, 3, 4}),
    ("textarea is inline there: its HTML block ends at a blank line", "<textarea>\n\n```\nx\n```\n</textarea>",
     {2, 3, 4}),
    ("indented code is code", 'text\n\n    <LeanBadge gid="x" />\n\nz', {2}),
    ("a line indented 4 columns goes on with a paragraph", 'text\n    <LeanBadge gid="x" />', set()),
    # Slidev's own block rules
    ("a <<< snippet import is code and ends a paragraph", "text\n<<< ./snippet.ts\n<span>\n```\nx\n```\n</span>",
     {1}),
    ("<<< … {monaco-write} is an editor, not code", "<<< ./snippet.ts {monaco-write}", set()),
    ("::slot:: ends a paragraph", "text\n::right::\n<span>\n```\nx\n```\n</span>", set()),
    ("``` inside a $$ math block is not a fence", '$$\n```\n$$\n<LeanBadge gid="x" />\n```\ny\n```', {4, 5, 6}),
    ("a $$ block that its quote ends takes the next line too", '> $$\n> a\n```\n<LeanBadge gid="x" />\n```\n', {4}),
    # markdown-it's other rules
    ("a link reference definition over several lines is not a paragraph", "[a]:\n/url\n<span>\n```\nx\n```\n</span>",
     set()),
    ("a javascript: destination makes no definition", "[a]: javascript&colon;x\n<span>\n```\nx\n```\n", {2, 3, 4}),
    ("a list marker 4 columns right of its list is text", "- a\n - b\n  - c\n   - d\n    - e\n<span>\n```\nx\n```",
     {6, 7, 8}),
    ("99 nested block quotes", ">" * 99 + " ```", {0}),
    ("markdown-it reads nothing below 100 nested containers", ">" * 100 + " ```", set()),
]

# The cases where the scanner before tables and JavaScript's \s missed a rendered tag (the findings), and a deck
# with one slide per case, each citing its own GID that the lock does not have.
HIDDEN_TAGS = {name: text for name, text, _ in FENCE_CASES if name.endswith("(finding)")}
HIDDEN_GIDS = [f"D5/S9/Hidden/Case.c{i}" for i in range(len(HIDDEN_TAGS))]
HIDDEN_DECK = "".join("\n---\n\n" + text.replace('gid="x"', f'gid="{gid}"')
                      for gid, text in zip(HIDDEN_GIDS, HIDDEN_TAGS.values()))

# Pieces of random decks for the comparison with Slidev's parser: containers, and line contents that start,
# go on with or end blocks.
CORPUS_PREFIXES = ["> ", ">", ">  ", ">\t", "> > ", "- ", "* ", "+ ", "-\t", "1. ", "2) ", "10. ", "1.\t", "-    ",
                   "-     ", " ", "  ", "   ", "    ", "\t", " \t", "[^n]: ", "[^n]:\t", "> - ", "1. > ", "\u3000",
                   "\u0085", "\ufeff", "\x1c"]
CORPUS_LINES = [
    "```", "```js", "````", "``````", "~~~", "~~~~", "~~~ ~", "``` x`", "``", "```  ", "text", "text", "a", "",
    '<LeanBadge gid="x" />', '<LeanBadge gid="x">', "</LeanBadge>", "<TheoremCard>", "</TheoremCard>", "<v-click>",
    "</v-click>", "<Stat>4</Stat>", "<Foo>x</Bar>", "<foo-bar a=1>", "<template #x>", '<component :is="x">',
    "<div>", "</div>", "<DIV>", '<div\u3000class="x">', "<div\u00a0/>", "<div\ufeff>", "<div\u0085/>", "<span>",
    "</span>", "<span>x</span>", "<SPAN>", "<a href=\"x\">", "<textarea>", "<pre>", "</pre>", "<script>x</script>",
    "<style>", "</style>", "<!-- c", "-->", "<!-- c -->", "<?x", "?>", "<!X", ">", "<![CDATA[", "]]>",
    "| a | b |", "|---|---|", "| a |", "|-|", "|:--|--:|", "a | b", "-|-", "--- | ---", "- | -", "\\| a | b |",
    "- a", "1. a", "2.", "-", "*", "---", "===", "--", "* * *", "_ _ _", "# h", "#", "####### x", "#\tx",
    "[^n]: note", "[^x]", "[a]: /u", '[a]: /u "t"', "[a]:", "/url", '"title"', "'t", "[a]: <u v>",
    "[a]: javascript:x", "[a]: javascript&colon;x", "[a]: &#106;avascript:x", "[a]: data:image/png;x", "[ ]: /u",
    "$$", "$$ x $$", "x $$", "$$$$", "::right::", ":: a ::", "::\u3000a::", "<<< ./snippet.ts", "<<<",
    "<<< ./snippet.ts {monaco-write}", "\\", "x\u2028y",
]


def deck_corpus(n: int = 600, seed: int = 11) -> list[str]:
    """Random decks: slides of random lines in random containers, between slide separators (some with
    frontmatter). A random line starting with --- separates slides too; a blank line after it keeps the next
    random line from being read as frontmatter (Slidev refuses a deck whose frontmatter is not YAML)."""
    rng = random.Random(seed)
    decks = []
    for _ in range(n):
        lines: list[str] = []
        for k in range(rng.randint(1, 3)):
            if k:
                lines += rng.choice([["---", ""], ["", "---", ""], ["---", "layout: default", "---"], ["----"]])
            for _ in range(rng.randint(1, 14)):
                lines.append("".join(rng.choice(CORPUS_PREFIXES) for _ in range(rng.choice([0, 0, 0, 1, 1, 2, 3])))
                             + rng.choice(CORPUS_LINES) + rng.choice(["", "", "", " ", "\t", " x", "\u0085", "\ufeff"]))
                if lines[-1].startswith("---"):
                    lines.append("")
        deck = "\n".join(lines)
        parts = deck.split("[^n]")  # unique footnote labels
        decks.append("".join(p + (f"[^{i + 1}]" if i < len(parts) - 1 else "") for i, p in enumerate(parts)))
    return decks


class FenceScanTest(unittest.TestCase):
    """Findings: the code-stripping regex ran from one code block to the next, so tags between two blocks were
    never checked; the line scanner after it knew no tables and no Unicode spaces after a tag name, so a tag
    Slidev renders could be taken for code. code_lines() (and slides-lib.mjs codeLines()) now run Slidev's
    block rules."""

    def test_cases(self):
        for name, text, want in FENCE_CASES:
            got = {i for i, code in enumerate(slides.code_lines(text)) if code}
            self.assertEqual(got, want, name)

    def test_tag_between_two_code_blocks_is_cited(self):
        found, _ = slides.citations(FENCE_CASES[0][1].replace("```\nmore", '```\n<LeanBadge gid="in-code" />'))
        self.assertEqual([c.gid for c in found], ["x"])
        found, _ = slides.citations(FENCE_CASES[6][1])
        self.assertEqual([c.gid for c in found], ["out"])

    def test_tags_slidev_renders_are_cited(self):
        self.assertEqual(len(HIDDEN_TAGS), 7)
        for name, text in HIDDEN_TAGS.items():
            found, _ = slides.citations(text)
            self.assertEqual([c.gid for c in found], ["x"], name)

    def test_strip_code_keeps_the_lines(self):
        text = "a\r\n```\r\n<b>\r\n```\r\nc"
        self.assertEqual(slides.strip_code(text), "a\n\n\n\nc")


# Slides as Slidev renders them: @slidev/parser splits the deck, and the markdown-exit instance Slidev builds for
# a deck of the theme (captured through the markdownSetup hook, footnote_tail off so that every footnote's
# blocks stay in place) parses each slide. With `render`, the slide is also rendered and Vue compiles the HTML (the
# template of the slide's component): `rendered` lists the LeanBadge / TheoremCard components in it with the gid
# Vue's code passes them ('' without one, null where it is no string literal or an object is merged in), null when
# Vue cannot compile the slide (Slidev's build fails).
SLIDEV_MARKDOWN = """
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const [root, dir] = process.argv.slice(1);
const items = JSON.parse(readFileSync(0, 'utf8')); // before Slidev loads: it leaves stdin non-blocking
const url = (p) => pathToFileURL(join(root, p)).href;
const { resolveOptions, ViteSlidevPlugin } = await import(url('node_modules/@slidev/cli/dist/index.mjs'));
const { parseSync } = await import(url('node_modules/@slidev/parser/dist/index.mjs'));
const { COMPONENTS, citations, codeLines, component } = await import(url('tools/node/slides-lib.mjs'));
const { compileTemplate, parse: parseSfc } = createRequire(join(root, 'package.json'))('@vue/compiler-sfc');
writeFileSync(join(dir, 'slides.md'), `---\\ntheme: ${join(root, 'theme', 'slides')}\\n---\\n\\n$$\\nx\\n$$\\n`);
// every file a <<< line of the corpus imports (a missing one fails Slidev's build)
for (const name of ['snippet.ts', 'x', '\\u0085', 'snippet.ts\\u0085', 'snippet.ts\\ufeff'])
  writeFileSync(join(dir, name), 'x\\n');
const options = await resolveOptions({ entry: join(dir, 'slides.md') }, 'build');
const md = await new Promise((resolve) => { ViteSlidevPlugin(options, { markdown: { markdownSetup: resolve } }); });
md.core.ruler.disable('footnote_tail');
const env = () => ({ id: '/@slidev/slides/__slidev_1.md' });
// the string a prop's value is (a static attribute, or a bound expression that evaluates to a string), else null
const string = (e) => {
  if (e?.type !== 4) return null;
  if (e.isStatic) return e.content;
  let v;
  try { v = new Function(`return (${e.content});`)(); } catch { return null; }
  return typeof v === 'string' ? v : null;
};
// the gid prop Vue's code passes to a component (its codegen: duplicates resolved, modifiers applied): '' without
// one, null when it is no string literal or the props are merged with an object bound by v-bind. mergeProps(…)
// merges groups of props, a later one over the earlier ones; toHandlers(…) (a v-on object) holds listeners only.
const helper = (e) => (e?.type === 14 && typeof e.callee === 'symbol' ? e.callee.description : undefined);
const gidProp = (node) => {
  const props = node.codegenNode?.props;
  if (!props) return '';
  const groups = props.type === 15 ? [props] : helper(props) === 'mergeProps' ? props.arguments : null;
  if (!groups) return null; // normalizeProps(…)
  let gid = '';
  for (const g of groups) {
    if (helper(g) === 'toHandlers') continue;
    if (g.type !== 15) return null;
    const p = g.properties.find((q) => q.key.type === 4 && q.key.isStatic && q.key.content === 'gid');
    if (p) gid = string(p.value);
  }
  return gid;
};
const rendered = async (content) => {
  let html;
  try { html = await md.renderAsync(content, env()); } catch { return null; } // e.g. a fence in an unknown language
  const { descriptor, errors } = parseSfc(`<template>${html}</template>`);
  if (errors.length) return null;
  const compiled = compileTemplate({ source: descriptor.template.content, filename: 'x.vue', id: 'x' });
  if (compiled.errors.length) return null;
  const out = [];
  const walk = (node) => {
    if (node.type === 1 && node.tagType === 1 && COMPONENTS.has(component(node.tag)))
      out.push([component(node.tag), gidProp(node)]);
    for (const child of [...(node.children ?? []), ...(node.branches ?? [])]) walk(child);
  };
  walk(compiled.ast);
  return out;
};
const one = async (content, render) => {
  const code = new Set();
  for (const t of md.parse(content, env()))
    if ((t.type === 'fence' || t.type === 'code_block') && t.map) for (let i = t.map[0]; i < t.map[1]; i++) code.add(i);
  const out = { content, js: codeLines(content), md: [...code].sort((a, b) => a - b), cites: citations(content) };
  if (render) out.rendered = await rendered(content);
  return out;
};
const out = [];
for (const [text, deck, render] of items)
  out.push(await Promise.all(deck ? parseSync(text, 'x.md').slides.map((s) => one(s.content, render)) : [one(text, render)]));
process.stdout.write(JSON.stringify(out), () => process.exit(0));
"""


def slidev_markdown(test: unittest.TestCase, items: list) -> list:
    """SLIDEV_MARKDOWN's slides of each item ([text, whether it is a deck, render]), one list per item."""
    with tempfile.TemporaryDirectory(prefix="tbook-slides-md-") as tmp:
        r = subprocess.run([NODE, "--input-type=module", "-e", SLIDEV_MARKDOWN, str(ROOT), tmp],
                           input=json.dumps(items), capture_output=True, text=True, cwd=ROOT)
    test.assertEqual(r.returncode, 0, r.stderr)
    out = json.loads(r.stdout)
    test.assertEqual(len(out), len(items))
    return out


def py_citations(content: str) -> list:
    """citations() in the form slides-lib.mjs citations() returns (as JSON)."""
    found, problems = slides.citations(content)
    return [[{"tag": c.tag, "gid": c.gid, "attrs": c.attrs} for c in found], problems]


@unittest.skipUnless(HAVE_NODE and (ROOT / "node_modules" / "@slidev" / "cli").is_dir(),
                     "node and node_modules (@slidev/cli, @slidev/parser) needed")
class NodeFenceScanTest(unittest.TestCase):
    """code_lines() and slides-lib.mjs codeLines() agree with each other and with the parser Slidev builds
    (fence and code_block tokens) on the cases and on seeded random decks, split into slides as Slidev and
    split_slides() split them; citations() and slides-lib.mjs citations() agree on them too."""

    def test_python_node_and_slidev_agree(self):
        items = [[text, False, False] for _, text, _ in FENCE_CASES] + [[deck, True, False] for deck in deck_corpus()]
        out = slidev_markdown(self, items)
        compared = 0
        for (text, deck, _), got in zip(items, out):
            contents = [s.content for s in slides.split_slides(text)] if deck else [text]
            self.assertEqual([g["content"] for g in got], contents, repr(text))
            for g in got:
                mask = slides.code_lines(g["content"])
                self.assertEqual(g["js"], mask, repr(g["content"]))
                self.assertEqual([i for i, code in enumerate(mask) if code], g["md"], repr(g["content"]))
                self.assertEqual(g["cites"], py_citations(g["content"]), repr(g["content"]))
                compared += 1
        self.assertGreater(compared, 1000)


# Pieces of random slides for the comparison with the components Vue compiles: text with a lone '<', math, code spans,
# escapes, quotes that open in them and close later, comments, links, HTML and component tags, complete or not (@
# becomes a GID of its own). Most elements close in the piece that opens them: Vue compiles no slide that leaves an
# element open.
TAG_PIECES = [
    "text", "a", "x > y", "<", ">", "a <b", "<x <1", "$a <b + 1$", "$0 <x <1$", "$x$", "$", "'", '"', "`", "\\",
    "\\<", "&lt;", "**", "[a](<b c>)", "<http://x.y>", "[^1]", "<!-- c -->", "<!--", "-->", "<br>", "<b>x</b>",
    "<span title='a > b'>x</span>", "`<i x='`", "`'/>`", "<i x='", "'/>", '<i x="', '"/>', "$<i x='$", "\\<i x='",
    "``<i x='``", '<LeanBadge gid="@" />', "<LeanBadge gid='@'/>", "<lean-badge gid=@ />", '<leanBadge\ngid="@"/>',
    '<TheoremCard label="a > b" gid="@">s</TheoremCard>', '<theorem-card gid="@">\n\ns\n\n</theorem-card>',
    '<LeanBadge gid="@" #d />', '<LeanBadge gid="@"/ >', '<LeanBadge gid="@"', "<LeanBadge", 'gid="@" />',
    '<LeanBadge\u3000gid="@"/>', '<LeanBadge v-click gid="@" />', '<lean-badge kind=definition gid="@"/>',
    '<LeanBadge gid="@" v-bind:[k]="v" />',
]
# Pieces that bind gid (GID_BINDINGS): Vue passes the first of gid, :gid and v-bind:gid
BIND_PIECES = [
    "<LeanBadge v-bind:gid=\"'@'\" gid=\"@\" />", "<LeanBadge gid=\"@\" :gid=\"'@'\" />",
    "<LeanBadge :gid=\"'@'\" v-bind:gid=\"`@`\" />", "<lean-badge v-bind:gid='\"@\"' status=argued />",
    "<LeanBadge gid=\"@\" v-bind=\"{ gid: '@' }\" />", "<LeanBadge :=\"{ gid: '@' }\" gid=\"@\" />",
    "<LeanBadge :gid.camel=\"'@'\" gid=\"@\" />", "<LeanBadge gid=\"@\" :gid.prop=\"'@'\" />",
    '<TheoremCard v-model:gid="m" gid="@">s</TheoremCard>', '<LeanBadge gid="@" :gid="m" />',
    "<LeanBadge gid=\"@\" v-on=\"{}\" :gid=\"'@'\" />", "<LeanBadge :gid=\"'@'\" v-on:=\"{}\" gid=\"@\" />",
]
TAG_LINES = [("", "")] * 6 + [("> ", ""), ("- ", ""), ("1. ", ""), ("  ", ""), ("    ", ""), ("```\n", "\n```"),
                              ("<div>", "</div>"), ("<div>\n", "\n</div>"), ("<v-click>\n", "\n</v-click>"),
                              ("| a |\n|---|\n| ", " |")]


def tag_corpus(n: int = 1500, seed: int = 5, pieces: list[str] = TAG_PIECES) -> list[str]:
    """Random slides: lines of random pieces (some in a container, an HTML block, a table or code), some blank."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        lines = []
        for _ in range(rng.randint(1, 6)):
            start, end = rng.choice(TAG_LINES)
            lines.append("" if rng.random() < 0.2 else start + rng.choice(["", " "]).join(
                rng.choice(pieces) for _ in range(rng.randint(1, 5))) + end)
        parts = "\n".join(lines).split("@")
        out.append("".join(p + (f"D5/S9/G/M.g{i}" if i < len(parts) - 1 else "") for i, p in enumerate(parts)))
    return out


@unittest.skipUnless(HAVE_NODE and (ROOT / "node_modules" / "@slidev" / "cli").is_dir()
                     and (ROOT / "node_modules" / "@vue" / "compiler-sfc").is_dir(),
                     "node and node_modules (@slidev/cli, @slidev/parser, @vue/compiler-sfc) needed")
class NodeTagScanTest(unittest.TestCase):
    """Findings: a '<' that starts no complete tag hid the next tag from the checks; the checks read another gid than
    the one Vue passes. On the cases and on seeded random slides, citations() and slides-lib.mjs citations() agree,
    and the LeanBadge / TheoremCard components that Vue compiles from a slide as Slidev renders it are, in order, tags
    they check with the gid Vue passes, or the slide reports a problem (a component tag that is not complete, a gid it
    cannot read)."""

    def test_every_rendered_tag_is_checked(self):
        cases = [*LONE_LT.values(), INCOMPLETE_TAG, '<div>\n<lean-badge gid="x" v-bind:[k]="v"/>\n</div>']
        items = [[text.replace('gid="x"', f'gid="D5/S9/G/Case.c{i}"'), False, True] for i, text in enumerate(cases)]
        items += [[text, False, True] for text, _, _ in GID_BINDINGS]
        items += [[text, False, True] for text in tag_corpus()]
        items += [[text, False, True] for text in tag_corpus(500, 6, TAG_PIECES + BIND_PIECES)]
        out = slidev_markdown(self, items)
        rendered = reported = 0
        for (text, _, _), [got] in zip(items, out):
            self.assertEqual(got["cites"], py_citations(text), repr(text))
            if got["rendered"] is None:  # Slidev's build fails
                continue
            found, problems = slides.citations(text)
            checked = iter([(c.tag, c.gid) for c in found])  # in order: each tag is checked after the one before
            unchecked = [r for r in got["rendered"] if r[1] is None or (r[0], r[1]) not in checked]
            self.assertTrue(not unchecked or problems, (text, unchecked))
            rendered += len(got["rendered"])
            reported += bool(unchecked)
        # each case renders its tag (the first ones only as unchecked tags the slide reports), with the gid
        # GID_BINDINGS gives
        n = len(cases) + len(GID_BINDINGS)
        self.assertEqual([len(got["rendered"]) for [got] in out[:n]], [1] * n)
        self.assertEqual([got["rendered"][0][1] for [got] in out[len(cases):n]], [r for _, r, _ in GID_BINDINGS])
        self.assertGreater(rendered, 600)
        self.assertGreater(reported, 50)


class CodeBlockCitationTest(ScratchDeckCase):
    """Finding: a LeanBadge / TheoremCard between two code blocks is checked (lock, kind, page parity)."""

    def test_tags_between_code_blocks_are_checked(self):
        self.write("zh", self.head("zh") + BETWEEN_BLOCKS)
        self.write("en", self.head("en") + BETWEEN_BLOCKS)
        msgs = self.issues()
        for want in ("D5/S9/Fake/Nope.not_locked is not in trureturing.lock.json",
                     f"{FAKE_DEF} is a Lean def; a TheoremCard must cite a theorem", "link /abs is absolute"):
            self.assertEqual(sum(want in m for m in msgs), 2, (want, msgs))
        self.assertEqual(len(msgs), 6, msgs)
        self.assertNotIn("in-code", " ".join(msgs))
        # only the zh edition cites them: the page-for-page check sees that too
        self.write("en", self.head("en") + "\n---\n\n```\nx\n```\n\ntext\n\n```\ny\n```\n")
        want = f"/slides.md cites [D5/S9/Fake/Nope.not_locked {FAKE_DEF}]"
        msgs = self.issues()
        self.assertTrue(any(m.startswith("slide 2: cites [], ") and m.endswith(want) for m in msgs), msgs)

    def test_tags_after_tables_and_unicode_spaces_are_checked(self):
        """Findings: a tag Slidev renders after a table, or after a block tag and a Unicode space, is checked."""
        self.write("zh", self.head("zh") + HIDDEN_DECK)
        self.write("en", self.head("en") + HIDDEN_DECK)
        msgs = self.issues()
        for gid in HIDDEN_GIDS:
            self.assertEqual(sum(f"{gid} is not in trureturing.lock.json" in m for m in msgs), 2, (gid, msgs))
        self.assertEqual(len(msgs), 2 * len(HIDDEN_GIDS), msgs)

    def test_tags_after_a_lone_lt_are_checked(self):
        """Finding: a tag Slidev renders after a '<' that starts no complete tag ($a <b + 1$, $0 <x <1$) is checked,
        and a component tag that is not complete is reported."""
        self.write("zh", self.head("zh") + LONE_LT_DECK)
        self.write("en", self.head("en") + LONE_LT_DECK)
        msgs = self.issues()
        for gid in LONE_LT_GIDS[:-1]:
            self.assertEqual(sum(f"{gid} is not in trureturing.lock.json" in m for m in msgs), 2, (gid, msgs))
        self.assertEqual(sum("<LeanBadge …> is not a complete tag" in m for m in msgs), 2, msgs)
        self.assertEqual(len(msgs), 2 * len(LONE_LT_GIDS), msgs)
        self.assertEqual({g for _, _, g in slides.cited_gids(self.book)}, set(LONE_LT_GIDS[:-1]))

    def test_gid_as_vue_passes_it(self):
        """Findings: the deck checks the gid Vue renders (the first of gid, :gid and v-bind:gid) and reports a v-bind
        object, a modifier or v-model on gid; the GID the lock has (FAKE_THM) is never what renders."""
        self.write("zh", self.head("zh") + GID_BINDING_DECK)
        self.write("en", self.head("en") + GID_BINDING_DECK)
        msgs = self.issues()
        self.assertEqual(len(msgs), 2 * len(GID_BINDING_ISSUES), msgs)
        for m, want in zip(msgs, GID_BINDING_ISSUES * 2):
            self.assertTrue(m.startswith(want), (m, want))
        self.assertEqual({g for _, _, g in slides.cited_gids(self.book)},
                         {checked for _, _, checked in GID_BINDINGS if checked} | {FAKE_THM})


# A slide with tags between two code blocks (and inside them, which is not checked).
BETWEEN_BLOCKS = ('\n---\n\n## Code\n\n```js\nconst a = \'<LeanBadge gid="in-code-1" />\';\n```\n\n'
                  '<LeanBadge gid="D5/S9/Fake/Nope.not_locked" />\n'
                  f'<TheoremCard label="x" gid="{FAKE_DEF}">\n\ns\n\n</TheoremCard>\n'
                  '<a href="/abs">x</a>\n\n```\n<LeanBadge gid="in-code-2" />\n```\n')


@unittest.skipUnless(HAVE_UNO, "node and node_modules (@slidev/parser, unocss) needed")
class NodeScriptsTest(unittest.TestCase):
    """tools/node/slides-check.mjs and slides-new.mjs in a scratch repository root (TBOOK_ROOT)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-slides-node-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("theme", "templates", "tools", "node_modules"):
            (self.tmp / name).symlink_to(ROOT / name)
        (self.tmp / "site.toml").write_text('[site]\ntitle = "t"\nlanguages = ["zh", "en"]\n', encoding="utf-8")
        self.env = dict(os.environ, TBOOK_ROOT=str(self.tmp))

    def node(self, script: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([NODE, str(ROOT / "tools" / "node" / script), *args], cwd=self.tmp, env=self.env,
                              capture_output=True, text=True)

    def book(self, editions: list[str]) -> Path:
        (self.tmp / "trureturing.lock.json").write_text(json.dumps(
            {"schema": lean.LOCK_SCHEMA, "repo": "o/trureturing", "branch": "dev", "commit": "0" * 40,
             "declarations": FAKE_DECLS}), encoding="utf-8")
        return make_book(self.tmp / "books", "bk", editions).dir

    def test_check_without_decks_succeeds(self):
        r = self.node("slides-check.mjs")  # no books/, no lock
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 deck(s)", r.stdout)
        (self.tmp / "books").mkdir()
        make_book(self.tmp / "books", "plain", ["zh", "en"])
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_first_language_and_citations(self):
        deck = self.book(["en", "zh"]) / "slides" / "d1"
        deck.mkdir(parents=True)
        theme = "../../../../theme/slides"
        good = f'\n---\n\n<leanBadge gid="{FAKE_THM}" />\n<TheoremCard kind="definition" label="d" gid="{FAKE_DEF}">\n\ns\n\n</TheoremCard>\n'
        (deck / "slides.md").write_text(deck_head(theme, "en") + good, encoding="utf-8")
        (deck / "slides.zh.md").write_text(deck_head(theme, "zh") + good, encoding="utf-8")
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("books/bk/slides/d1/slides.md: en", r.stdout)
        self.assertIn("books/bk/slides/d1/slides.zh.md: zh", r.stdout)

        bad = ('\n---\n\n<lean-badge gid="D5/S9/Fake/Nope.not_locked" />\n'
               f'<theorem-card label="x" gid="{FAKE_DEF}">\n\ns\n\n</theorem-card>\n<LeanBadge gid="{FAKE_DEF}" />\n'
               '\n---\nsrc: ./more.md\n---\n')
        (deck / "slides.md").write_text(deck_head(theme, "en") + bad, encoding="utf-8")
        (deck / "slides.zh.md").write_text(deck_head(theme, "zh") + bad, encoding="utf-8")
        (deck / "slides.en.md").write_text(deck_head(theme, "en"), encoding="utf-8")
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for want in ["slides.en.md: en is the book's first language, whose edition is slides.md",
                     "D5/S9/Fake/Nope.not_locked is not in trureturing.lock.json",
                     f'{FAKE_DEF} is a Lean def; a TheoremCard must cite a theorem',
                     f'{FAKE_DEF} is a Lean def; a LeanBadge must cite a theorem',
                     "src: imports slides from another file"]:
            self.assertIn(want, r.stderr)

    def test_check_tags_between_code_blocks(self):
        """Finding: slides-check.mjs, like check(), sees tags between two code blocks (not those inside)."""
        deck = self.book(["zh", "en"]) / "slides" / "d1"
        deck.mkdir(parents=True)
        theme = "../../../../theme/slides"
        (deck / "slides.md").write_text(deck_head(theme, "zh") + BETWEEN_BLOCKS, encoding="utf-8")
        (deck / "slides.en.md").write_text(deck_head(theme, "en") + BETWEEN_BLOCKS, encoding="utf-8")
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for want in ("D5/S9/Fake/Nope.not_locked is not in trureturing.lock.json",
                     f"{FAKE_DEF} is a Lean def; a TheoremCard must cite a theorem", "link /abs is absolute"):
            self.assertEqual(r.stderr.count(want), 2, (want, r.stderr))
        self.assertIn("slides-check failed (6)", r.stderr)
        self.assertNotIn("in-code", r.stderr)
        # the same verdict as the Python check on the same files
        with mock.patch.object(lean.Lock, "load", return_value=fake_lock()), \
                mock.patch.object(slides, "theme_ref", lambda deck_dir: theme):
            py = [i.message for i in slides.check(config.load_book(self.tmp / "books" / "bk"))]
        self.assertEqual(len(py), 6, py)
        for want in ("D5/S9/Fake/Nope.not_locked", FAKE_DEF, "/abs"):
            self.assertEqual(sum(want in m for m in py), 2, (want, py))

    def test_check_tags_after_tables_and_unicode_spaces(self):
        """Findings: slides-check.mjs, like check(), sees a tag Slidev renders after a table, or after a block
        tag and a Unicode space."""
        deck = self.book(["zh", "en"]) / "slides" / "d1"
        deck.mkdir(parents=True)
        theme = "../../../../theme/slides"
        (deck / "slides.md").write_text(deck_head(theme, "zh") + HIDDEN_DECK, encoding="utf-8")
        (deck / "slides.en.md").write_text(deck_head(theme, "en") + HIDDEN_DECK, encoding="utf-8")
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for gid in HIDDEN_GIDS:
            self.assertEqual(r.stderr.count(f"{gid} is not in trureturing.lock.json"), 2, (gid, r.stderr))
        self.assertIn(f"slides-check failed ({2 * len(HIDDEN_GIDS)})", r.stderr)
        with mock.patch.object(lean.Lock, "load", return_value=fake_lock()), \
                mock.patch.object(slides, "theme_ref", lambda deck_dir: theme):
            py = [i.message for i in slides.check(config.load_book(self.tmp / "books" / "bk"))]
        self.assertEqual(len(py), 2 * len(HIDDEN_GIDS), py)

    def test_check_tags_after_a_lone_lt(self):
        """Finding: slides-check.mjs, like check(), checks a tag Slidev renders after a '<' that starts no complete
        tag ($a <b + 1$, $0 <x <1$) and reports a component tag that is not complete."""
        deck = self.book(["zh", "en"]) / "slides" / "d1"
        deck.mkdir(parents=True)
        theme = "../../../../theme/slides"
        (deck / "slides.md").write_text(deck_head(theme, "zh") + LONE_LT_DECK, encoding="utf-8")
        (deck / "slides.en.md").write_text(deck_head(theme, "en") + LONE_LT_DECK, encoding="utf-8")
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for gid in LONE_LT_GIDS[:-1]:
            self.assertEqual(r.stderr.count(f"{gid} is not in trureturing.lock.json"), 2, (gid, r.stderr))
        self.assertEqual(r.stderr.count("<LeanBadge …> is not a complete tag"), 2, r.stderr)
        self.assertIn(f"slides-check failed ({2 * len(LONE_LT_GIDS)})", r.stderr)
        with mock.patch.object(lean.Lock, "load", return_value=fake_lock()), \
                mock.patch.object(slides, "theme_ref", lambda deck_dir: theme):
            py = [i.message for i in slides.check(config.load_book(self.tmp / "books" / "bk"))]
        self.assertEqual(len(py), 2 * len(LONE_LT_GIDS), py)

    def test_check_gid_as_vue_passes_it(self):
        """Findings: slides-check.mjs, like check(), checks the gid Vue renders (the first of gid, :gid and
        v-bind:gid) and reports a v-bind object, a modifier or v-model on gid."""
        deck = self.book(["zh", "en"]) / "slides" / "d1"
        deck.mkdir(parents=True)
        theme = "../../../../theme/slides"
        (deck / "slides.md").write_text(deck_head(theme, "zh") + GID_BINDING_DECK, encoding="utf-8")
        (deck / "slides.en.md").write_text(deck_head(theme, "en") + GID_BINDING_DECK, encoding="utf-8")
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        msgs = r.stderr.split("\n- ")[1:]
        self.assertEqual(len(msgs), 2 * len(GID_BINDING_ISSUES), r.stderr)
        for want in GID_BINDING_ISSUES:  # problems of the tags come before the checks of their GIDs
            self.assertEqual(sum(f": {want}" in m for m in msgs), 2 * GID_BINDING_ISSUES.count(want), (want, msgs))
        self.assertNotIn(FAKE_THM, r.stderr)

    def test_new_deck_in_an_english_first_book(self):
        self.book(["en", "zh"])
        r = self.node("slides-new.mjs", "bk", "intro", "入门", "Getting started")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        deck = self.tmp / "books" / "bk" / "slides" / "intro"
        self.assertEqual(sorted(p.name for p in deck.iterdir()), ["slides.md", "slides.zh.md"])
        en = (deck / "slides.md").read_text(encoding="utf-8")
        zh = (deck / "slides.zh.md").read_text(encoding="utf-8")
        self.assertIn('lang: "en"', en)
        self.assertIn("Getting started", en)
        self.assertIn('lang: "zh-CN"', zh)
        self.assertIn("入门", zh)
        r = self.node("slides-check.mjs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(NODE, "node needed")
class PrintBackdropTest(unittest.TestCase):
    """Finding: slide PDFs paged slowly (about two seconds a page) because every page drew the backdrop as
    full-page translucent gradients, which PDF readers composite with soft masks. The print view shows one
    image instead (theme/slides/styles/backdrop.css, backdrop.jpg); its fingerprint keeps it in step with
    the CSS and the tokens it is rendered from."""

    SCRIPT = ROOT / "tools" / "node" / "slides-backdrop.mjs"

    def node(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([NODE, *args], cwd=root, env=dict(os.environ, TBOOK_ROOT=str(root)),
                              capture_output=True, text=True)

    def fingerprint(self, css: str, tokens: str) -> str:
        code = (f"import {{ backdropFingerprint }} from {json.dumps(self.SCRIPT.as_uri())};"
                "const [css, tokens] = JSON.parse(process.argv[1]);"
                "process.stdout.write(backdropFingerprint(css, tokens));")
        r = subprocess.run([NODE, "--input-type=module", "-e", code, json.dumps([css, tokens])],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_committed_backdrop_is_up_to_date(self):
        r = self.node(ROOT, str(self.SCRIPT), "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        meta = json.loads((ROOT / "theme" / "slides" / "styles" / "backdrop.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["width"], meta["height"]), (1920, 1080))
        css = (ROOT / "theme" / "slides" / "styles" / "backdrop.css").read_text(encoding="utf-8")
        self.assertIn(':where(html.print) .slide:where(:not(.tr-own-bg)) { background-image: url("./backdrop.jpg"); }', css)
        self.assertIn(":where(html.print) .slide:where(:not(.tr-own-bg)) > .tr-fx { display: none; }", css)
        index = (ROOT / "theme" / "slides" / "styles" / "index.ts").read_text(encoding="utf-8")
        self.assertLess(index.index("./deck.css"), index.index("./backdrop.css"))  # its .slide rule wins

    def test_fingerprint_follows_what_the_image_shows(self):
        css = (ROOT / "theme" / "slides" / "styles" / "backdrop.css").read_text(encoding="utf-8")
        tokens = (ROOT / "theme" / "generated" / "tokens.css").read_text(encoding="utf-8")
        base = self.fingerprint(css, tokens)
        self.assertEqual(base, json.loads((ROOT / "theme" / "slides" / "styles" / "backdrop.json")
                                          .read_text(encoding="utf-8"))["fingerprint"])

        def token(name: str, value: str) -> str:
            out, n = re.subn(rf"({re.escape(name)}\s*:\s*)[^;]*;", rf"\g<1>{value};", tokens, count=1)
            self.assertEqual(n, 1, name)
            return out
        # what the backdrop uses: the void, the aurora, scanlines, vignette and the cyan of the brackets
        for name in ("--tr-void", "--tr-fx-aurora", "--tr-fx-scanlines", "--tr-fx-vignette", "--tr-cyan"):
            self.assertNotEqual(self.fingerprint(css, token(name, "#123456")), base, name)
        self.assertNotEqual(self.fingerprint(css.replace("width: 46px", "width: 40px"), tokens), base)
        # what it does not: another colour, and the print rules (they only use the image)
        self.assertEqual(self.fingerprint(css, token("--tr-sem-link", "#123456")), base)
        self.assertEqual(self.fingerprint(css.replace('url("./backdrop.jpg")', 'url("./other.jpg")'), tokens), base)
        self.assertEqual(self.fingerprint(css.replace("corner brackets, each open", "brackets: each opens"), tokens), base)

    def test_what_the_rendering_cannot_see_is_reported(self):
        """Reviewer finding: a property backdrop.css takes from deck.css, or a url() it loads, is not in the image
        (rendered from backdrop.css and tokens.css alone) while the fingerprint could not tell."""
        tmp = Path(tempfile.mkdtemp(prefix="tbook-backdrop-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "tools").symlink_to(ROOT / "tools")
        shutil.copytree(ROOT / "theme", tmp / "theme")
        css = tmp / "theme" / "slides" / "styles" / "backdrop.css"
        text = css.read_text(encoding="utf-8")
        for change, want in ((".tr-fx::after { border-top: 1px solid var(--hair);", "uses --hair, which"),
                             (".tr-fx::after { border-image: url(x.png);", "loads a url() outside its print rules")):
            with self.subTest(want):
                css.write_text(text.replace(".tr-fx::after {", change, 1), encoding="utf-8")
                for args in (("--check",), ()):
                    r = self.node(tmp, str(self.SCRIPT), *args)
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn(want, r.stderr)
        css.write_text(text, encoding="utf-8")
        self.assertEqual(self.node(tmp, str(self.SCRIPT), "--check").returncode, 0)

    def test_stale_backdrop_is_reported(self):
        tmp = Path(tempfile.mkdtemp(prefix="tbook-backdrop-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("templates", "tools", "node_modules", "tbook"):
            (tmp / name).symlink_to(ROOT / name)
        (tmp / "theme").mkdir()
        for child in (ROOT / "theme").iterdir():
            if child.name != "generated":
                (tmp / "theme" / child.name).symlink_to(child)
        shutil.copytree(ROOT / "theme" / "generated", tmp / "theme" / "generated")
        tokens = tmp / "theme" / "generated" / "tokens.css"
        tokens.write_text(re.sub(r"(--tr-void\s*:\s*)[^;]*;", r"\g<1>#102030;", tokens.read_text(encoding="utf-8"),
                                 count=1), encoding="utf-8")
        (tmp / "site.toml").write_text('[site]\ntitle = "t"\nlanguages = ["zh", "en"]\n', encoding="utf-8")
        r = self.node(tmp, str(self.SCRIPT), "--check")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("theme/slides/styles/backdrop.jpg does not match", r.stderr)
        r = self.node(tmp, str(ROOT / "tools" / "node" / "slides-check.mjs"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("run node tools/node/slides-backdrop.mjs", r.stderr)
        r = subprocess.run([sys.executable, "-m", "tbook", "theme", "--check"], cwd=tmp, capture_output=True, text=True,
                           env=dict(os.environ, TBOOK_ROOT=str(tmp), PYTHONPATH=str(ROOT / "tools")))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("backdrop.jpg does not match", r.stdout + r.stderr)


def have_chromium() -> bool:
    """Chromium for slides-build: $PW_CHROMIUM_PATH, or Playwright's own download."""
    if os.environ.get("PW_CHROMIUM_PATH"):
        return Path(os.environ["PW_CHROMIUM_PATH"]).is_file()
    if not NODE or not (ROOT / "node_modules" / "playwright-chromium").is_dir():
        return False
    r = subprocess.run([NODE, "-e", "const p = require('playwright-chromium').chromium.executablePath();"
                        "process.exit(require('fs').existsSync(p) ? 0 : 1)"], cwd=ROOT, capture_output=True)
    return r.returncode == 0


OWN_BG_DECK = """---
theme: ../../../../theme/slides
title: Backdrop
htmlAttrs:
  lang: zh-CN
deck:
  code: BG
  title: Backdrop
  version: 0.1.0
---

# 默认背景

---
class: tint
---

# 只改底色

---
class: tr-own-bg hero
---

# 自己的背景
"""
OWN_BG_STYLE = """.slide.tint { background-color: #401028; }
.slide.hero { background-image: radial-gradient(circle at 30% 30%, rgba(255, 47, 208, .25), transparent 60%); }
"""


@unittest.skipUnless(NODE and (ROOT / "node_modules" / "@slidev" / "cli").is_dir() and have_chromium(),
                     "node, node_modules (@slidev/cli) and Chromium needed")
class OwnBackgroundBuildTest(unittest.TestCase):
    """Findings: in the PDF a slide with a background of its own lost the scanlines, brackets and vignette, or the
    print backdrop covered its colour, and no check said so; the print-view check looked at slide 1 only. A slide
    with its own background has the class tr-own-bg and keeps the backdrop layers in the PDF; slides-build reports
    one without it, and checks every PDF page against the slides."""

    def test_own_backgrounds(self):
        tmp = Path(tempfile.mkdtemp(prefix="tbook-own-bg-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("templates", "tools", "node_modules"):
            (tmp / name).symlink_to(ROOT / name)
        # a copy: the export's dev server serves no file whose real path is outside the root (the backdrop image)
        shutil.copytree(ROOT / "theme", tmp / "theme")
        (tmp / "site.toml").write_text('[site]\ntitle = "t"\nlanguages = ["zh", "en"]\n', encoding="utf-8")
        deck = make_book(tmp / "books", "bk", ["zh"]).dir / "slides" / "bg"
        deck.mkdir(parents=True)
        (deck / "slides.md").write_text(OWN_BG_DECK, encoding="utf-8")
        (deck / "style.css").write_text(OWN_BG_STYLE, encoding="utf-8")
        out = tmp / "out"
        env = dict(os.environ, TBOOK_ROOT=str(tmp))

        def build(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run([NODE, str(ROOT / "tools" / "node" / "slides-build.mjs"), "--book", "bk", "--out", str(out),
                                   *args], cwd=tmp, env=env, capture_output=True, text=True, timeout=600)

        r = build()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        failures = [line for line in r.stderr.splitlines() if line.startswith("- ")]
        self.assertEqual(len(failures), 1, r.stderr)
        self.assertIn("slide 2: the slide has a background of its own (backgroundColor rgb(64, 16, 40))", failures[0])
        self.assertIn("add tr-own-bg", failures[0])
        # the PDF was checked page by page: 1 and 2 draw the print backdrop, 3 (tr-own-bg) keeps the layers
        self.assertTrue((out / "bg-zh.pdf").is_file())
        self.assertNotIn("not draw the print backdrop", r.stderr)

        (deck / "slides.md").write_text(OWN_BG_DECK.replace("class: tint", "class: tr-own-bg tint"), encoding="utf-8")
        r = build()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # and the PDF check fails a page that should draw the print backdrop but does not
        (tmp / "theme" / "slides" / "styles" / "backdrop.css").write_text(
            (tmp / "theme" / "slides" / "styles" / "backdrop.css").read_text(encoding="utf-8")
            .replace(':where(html.print) .slide:where(:not(.tr-own-bg)) { background-image: url("./backdrop.jpg"); }', ""),
            encoding="utf-8")
        r = build("--deck", "bg")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("slide 1: the print view does not show the print backdrop", r.stderr)
        self.assertIn("PDF page 1 does not draw the print backdrop", r.stderr)


class IndexFontsTest(unittest.TestCase):
    def test_index_uses_the_theme_fonts(self):
        """The decks page links the fonts URL of theme/tokens.json and gives English text the Latin face."""
        import json as _json

        url = _json.loads((paths.THEME / "tokens.json").read_text(encoding="utf-8"))["font"]["google-fonts-css"]
        site = config.load_site()
        books = config.load_books()
        if not books:
            self.skipTest("no book")
        page = slides.index_html(site, books[0], [])
        self.assertIn(f'href="{url}"', page.replace("&amp;", "&"))
        self.assertIn(":not(:lang(zh), :lang(ja), :lang(ko)) { --tr-font-body: var(--tr-font-body-latin); }", page)


class BuildOncePerProcessTest(unittest.TestCase):
    """`./tbook build all` builds the decks, then the site step publishes them through build() again: with
    the cache off (TBOOK_CACHE=0), or a store that failed, they must not be built a second time."""

    def test_build_then_publish_builds_once(self):
        from tbook import buildcache

        tmp = Path(tempfile.mkdtemp(prefix="tbook-slides-once-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        out = tmp / "build" / "slides" / "bk"
        calls = []

        def fake_build(site, book, out_dir):
            calls.append(Path(out_dir))
            Path(out_dir).mkdir(parents=True, exist_ok=True)

        unit = SimpleNamespace(key="k1", label="slides bk")
        book = SimpleNamespace(slug="bk")
        with mock.patch.dict(os.environ, {"TBOOK_CACHE": "0"}), \
                mock.patch.object(slides, "deck_names", return_value=["overview"]), \
                mock.patch.object(slides, "_build", side_effect=fake_build), \
                mock.patch.object(slides, "_BUILT", set()), \
                mock.patch.object(buildcache, "slides_unit", return_value=unit):
            slides.build(None, book, out)
            slides.build(None, book, out)
            self.assertEqual(len(calls), 1, "the second call reuses this process's build")
            unit.key = "k2"  # an input changed: build again
            slides.build(None, book, out)
            self.assertEqual(len(calls), 2)
            shutil.rmtree(out)  # the output is gone: build again
            slides.build(None, book, out)
            self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
