"""Tests for the Pandoc pipeline: staging, Lua filters, metadata, PDF/EPUB builds, covers.

Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_pandoc.py'

A small synthetic book (prefix, parts, a nested chapter, a draft, an appendix without an H1,
setext headings, book and edition images, cross-chapter links) is written to a temporary
directory; every build output goes to temporary directories too. Tests that need pandoc,
typst, Java/epubcheck or the example book's Lean lock skip themselves when unavailable.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from example_support import example_shown

from tbook import config, cover, lean, mathrender, paths
from tbook import pandoc as tp
from tbook.model import load_edition

HAVE_KATEX = bool(shutil.which("node")) and (paths.ROOT / "node_modules" / "katex" / "package.json").exists()


def _png(width: int = 4, height: int = 4) -> bytes:
    """A valid RGB PNG (cyan pixels) built with zlib, so the fixture needs no binary blobs."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\x19\xf0\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG_1PX = _png()
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60" viewBox="0 0 120 60">'
       '<rect width="120" height="60" fill="#888"/><circle cx="60" cy="30" r="20" fill="#fff"/></svg>')

FILES = {
    "book.toml": """
[book]
version = "1.2.3"
authors = ["A. Author", "B. Author"]
license = "CC-BY-4.0"
editions = ["en"]
code = "TEST//BOOK"
date = "2026-01-02"

[book.title]
en = "Test Book"

[book.subtitle]
en = "A fixture"

[book.isbn]
en = "978-3-16-148410-0"

[pdf]
paper = "a5"
""",
    "assets/fig.svg": SVG,
    "assets/data.csv": "a,b\n1,2\n",
    "en/img/dot.png": PNG_1PX,
    "en/files/table.csv": "c,d\n3,4\n",
    "en/SUMMARY.md": """# Summary

[Preface](README.md)

# Part One

- [Chapter A](a.md)
  - [Section A.1](part/a1.md)
- [Draft]()

# Part Two

- [Chapter B](b.md)

[Appendix](appendix.md)
""",
    "en/README.md": "# Preface\n\nSee [chapter B](b.md#sec-b) and [A](a.md).\n",
    "en/a.md": """Chapter A
=========

Intro with ![a figure](../assets/fig.svg) and a local image:

![dot](img/dot.png)

::: {.definition #def-a title="Size of $x$"}
Define $x$ and see [B](./b.md).
:::

```text
# not a heading [x](b.md)
```

::: {.tr-media .tr-viz}
![media poster](../assets/fig.svg)
:::

## Sub A {#sub-a}

Text with a note[^n]. Thanks @alice; a norm $\\norm{x}$ and $\\floor{y}$; see
[the summary of B](b.md#summary) and [this summary](#summary).

[^n]: NOTE-A-TEXT

Download [the data](../assets/data.csv) or [the table](files/table.csv).

## Summary

Summary of A.
""",
    "en/part/a1.md": """# Section A.1

Back to [the definition](../a.md#def-a), ![f](../../assets/fig.svg), [missing](../nope.md).

## Deeper

[ref]: ../b.md
""",
    "en/b.md": """# Chapter B

## Section B {#sec-b}

::: {.remark title="Case of [@def-a]"}
See [@def-a] and the [sub section](a.md#sub-a). Another note[^n].

[^n]: NOTE-B-TEXT
:::

## Summary

Summary of B.

## Bound $x^2$ for $\\norm{x}$

Text.
""",
    "en/appendix.md": "Text of the appendix with a [dangling](#nowhere) link.\n",
}


def have_pandoc() -> bool:
    try:
        return bool(tp.pandoc_path())
    except tp.PandocError:
        return False


# The Pandoc that requirements.txt pins (pypandoc_binary 1.17 bundles Pandoc 3.9). Tests that compare the
# scanners with Pandoc's own reading of a case were recorded with it; another Pandoc may read some cases otherwise
# (Pandoc 3.1 reads a definition two blank lines after its term as a paragraph).
PINNED_PANDOC = "3.9"


def pandoc_version() -> str:
    """The version of the Pandoc that tbook.pandoc.pandoc_path() finds ("" without one)."""
    try:
        out = subprocess.run([tp.pandoc_path(), "--version"], capture_output=True, text=True, check=True).stdout
    except (tp.PandocError, OSError, subprocess.CalledProcessError):
        return ""
    m = re.match(r"pandoc(?:\.exe)? (\S+)", out)
    return m.group(1) if m else ""


def have_pinned_pandoc() -> bool:
    return pandoc_version() == PINNED_PANDOC


def have_typst() -> bool:
    try:
        import typst  # noqa: F401
        return True
    except ImportError:
        return False


def make_book(root: Path) -> config.Book:
    bdir = root / "test-book"
    for rel, content in FILES.items():
        f = bdir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            f.write_bytes(content)
        else:
            f.write_text(content.lstrip("\n"), encoding="utf-8")
    return config.load_book(bdir)


def run_filters(md: str, fmt: str, meta: dict[str, str] | None = None) -> str:
    args = [tp.pandoc_path(), "-f", tp.READER, "-t", fmt, "--wrap", "none", *tp._filters()]
    for k, v in (meta or {}).items():
        args += ["--metadata", f"{k}={v}"]
    proc = subprocess.run(args, input=md, capture_output=True, text=True, check=True)
    return proc.stdout


ENV_MD = """\
# Chapter {#ch-x .tr-chapter tr-section="numbered" tr-kicker="§ 01"}

See [the theorem](#thm-x) and [nothing](#missing).

:::::: {#thm-x .tr-env .theorem tr-kind="theorem" tr-status="lean" tr-label="Theorem" tr-number="1.2" tr-ref="Theorem 1.2" tr-title="Bound on $c$" tr-badge="LEAN ✓" tr-badge-url="https://example.org/X.lean#L3" tr-lean="D5/S1/X.y" tr-lean-name="D5.S1.X.y" tr-lean-url="https://example.org/X.lean#L3"}
Statement $c \\in \\{0, 1\\}$.
::::::

:::::: {.tr-env .proof tr-kind="proof" tr-status="proof" tr-label="Proof" tr-number="" tr-ref="Proof"}
Easy.
::::::

:::::: {#prob-x .tr-env .problem tr-kind="problem" tr-status="open" tr-label="Open problem" tr-number="1.3" tr-ref="Open problem 1.3" tr-badge="OPEN"}
Is it minimal?
::::::
"""


BASE_URL = "https://example.org/books/"


def fixture_site() -> config.Site:
    """The repository's site with a fixed base URL (links to files point there)."""
    return dataclasses.replace(config.load_site(), base_url=BASE_URL)


class StagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-test-pandoc-"))
        cls.site = fixture_site()
        cls.book = make_book(cls.tmp)
        cls.ed = cls.book.edition("en")
        cls.model = load_edition(cls.ed)
        cls.stage = tp.stage(cls.site, cls.book, cls.ed, cls.model, None, out_dir=cls.tmp / "stage")
        cls.md = cls.stage.book_md.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def heading(self, text: str) -> str:
        for line in self.md.splitlines():
            if re.match(r"^#{1,6} " + re.escape(text) + r"( \{|$)", line):
                return line
        self.fail(f"heading {text!r} not found in book.md:\n{self.md}")

    def test_model_has_no_issues(self):
        self.assertEqual([i.format() for i in self.model.issues], [])

    def test_chapter_order_and_ids(self):
        self.assertEqual([c.path for c in self.stage.chapters],
                         ["README.md", "a.md", "part/a1.md", "b.md", "appendix.md", "verification-ledger.md"])
        self.assertEqual([c.id for c in self.stage.chapters],
                         ["ch-readme", "ch-a", "ch-part-a1", "ch-b", "ch-appendix", "tr-verification-ledger"])

    def test_setext_title_and_attributes(self):
        h = self.heading("Chapter A")
        self.assertTrue(h.startswith("# Chapter A {#ch-a .tr-chapter"), h)
        self.assertIn('tr-section="numbered"', h)
        self.assertIn('tr-kicker="§ 01"', h)
        self.assertNotIn(".unnumbered", h)

    def test_prefix_and_suffix_unnumbered(self):
        pre = self.heading("Preface")
        self.assertIn(".unnumbered", pre)
        self.assertIn('epub:type="preface"', pre)
        app = self.heading("Appendix")  # synthesized from SUMMARY: the file has no H1
        self.assertTrue(app.startswith("# Appendix {#ch-appendix .tr-chapter .unnumbered"), app)
        self.assertIn('tr-section="suffix"', app)
        self.assertIn('tr-kicker="§ A"', app)

    def test_nested_chapter_headings_shift(self):
        self.assertTrue(self.heading("Section A.1").startswith("## Section A.1 {#ch-part-a1 .tr-chapter"))
        self.assertEqual(self.heading("Deeper"), "### Deeper {#deeper}")
        self.assertEqual(self.heading("Sub A"), "## Sub A {#sub-a}")

    def test_footnotes_scoped_per_chapter(self):
        # Both chapters define [^n]; in one document Pandoc would give both the last text.
        self.assertIn("note[^ch-a--n].", self.md)
        self.assertIn("[^ch-a--n]: NOTE-A-TEXT", self.md)
        self.assertIn("note[^ch-b--n].", self.md)
        self.assertIn("[^ch-b--n]: NOTE-B-TEXT", self.md)
        self.assertNotIn("[^n]", self.md)

    def test_repeated_heading_links_stay_in_their_chapter(self):
        # "Summary" exists in a.md and b.md: each keeps a distinct id, and a link resolves in
        # the chapter it names (b.md#summary → B's summary), as the HTML edition does.
        self.assertEqual(self.heading("Summary").split(" {")[0], "## Summary")
        ids = re.findall(r"^## Summary \{#([^}]+)\}$", self.md, re.M)
        self.assertEqual(ids, ["summary", "ch-b--summary"])
        self.assertIn("[the summary of B](#ch-b--summary)", self.md)
        self.assertIn("[this summary](#summary)", self.md)
        # mdBook's id is made from the text KaTeX shows ("Bound x2 for ∥x∥"); without Node
        # the TeX stands in.
        bound = "bound-x2-for-x" if HAVE_KATEX else "bound-x2-for-normx"
        self.assertIn("## Bound $x^2$ for $\\norm{x}$ {#" + bound + "}", self.md)

    def test_plain_file_links_point_to_the_site(self):
        # Pandoc embeds images only: a relative link to a CSV is dead in the PDF and breaks the EPUB.
        self.assertIn(f"[the data]({BASE_URL}test-book/en/_book/assets/data.csv)", self.md)
        self.assertIn(f"[the table]({BASE_URL}test-book/en/files/table.csv)", self.md)
        self.assertNotIn("_book/en/files/table.csv", self.stage.files)

    def test_macros_defined_before_the_first_chapter(self):
        head = self.md.split("\n# ", 1)[0]
        self.assertIn("\\newcommand{\\norm}[1]{\\left\\lVert #1\\right\\rVert}", head)
        self.assertEqual(head.strip(), mathrender.newcommands())

    def test_parts(self):
        self.assertTrue(self.heading("Part One").startswith("# Part One {#tr-part-1 .tr-part .unnumbered"))
        self.assertTrue(self.heading("Part Two").startswith("# Part Two {#tr-part-2 .tr-part"))
        self.assertLess(self.md.index("# Part One"), self.md.index("# Chapter A"))
        self.assertLess(self.md.index("# Part Two"), self.md.index("# Chapter B"))

    def test_draft_skipped(self):
        self.assertNotIn("Draft", self.md)

    def test_links_between_chapters(self):
        self.assertIn("[chapter B](#sec-b)", self.md)
        self.assertIn("[A](#ch-a)", self.md)
        self.assertIn("[the definition](#def-a)", self.md)
        self.assertIn("[B](#ch-b)", self.md)  # ./b.md inside an environment
        self.assertIn("[sub section](#sub-a)", self.md)
        self.assertIn("[ref]: #ch-b", self.md)  # reference definition rebased
        self.assertIn("[Definition 1.1](#def-a)", self.md)  # [@def-a]

    def test_link_to_non_chapter_dropped(self):
        self.assertIn(", missing.", self.md)
        self.assertTrue(any("nope.md" in w for w in self.stage.warnings), self.stage.warnings)

    def test_images_rebased_and_copied(self):
        self.assertIn("![a figure](_book/assets/fig.svg)", self.md)
        self.assertIn("![f](_book/assets/fig.svg)", self.md)  # nested chapter: ../../assets
        self.assertIn("![dot](_book/en/img/dot.png)", self.md)  # edition-local image
        self.assertIn("_book/assets/fig.svg", self.stage.files)
        self.assertIn("_book/en/img/dot.png", self.stage.files)
        self.assertTrue((self.stage.dir / "_book/assets/fig.svg").is_file())
        self.assertTrue((self.stage.dir / "_book/en/img/dot.png").is_file())

    def test_code_blocks_untouched(self):
        self.assertIn("# not a heading [x](b.md)", self.md)

    def test_ledger_appended_last(self):
        last = self.md.rsplit("\n# ", 1)[1]
        self.assertTrue(last.startswith("Verification ledger {#tr-verification-ledger"), last[:120])
        self.assertIn(".tr-ledger", last.splitlines()[0])
        self.assertIn('tr-section="back"', last.splitlines()[0])
        self.assertIn(".unnumbered", last.splitlines()[0])

    def test_environment_divs_present(self):
        self.assertRegex(self.md, r':{6} \{#def-a \.tr-env \.definition tr-kind="definition"')

    def test_theme_and_meta_staged(self):
        for rel in ("_theme/typst/book.typ", "_theme/typst/cover.typ", "_theme/typst/pandoc-template.typst",
                    "_theme/generated/tokens.typ", "_theme/typst/code-screen.tmTheme", "_theme/typst/code-print.tmTheme"):
            self.assertTrue((self.stage.dir / rel).is_file(), rel)
        meta = json.loads((self.stage.dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["title"], "Test Book")
        self.assertEqual(meta["paper"], "a5")
        self.assertEqual(meta["authors"], ["A. Author", "B. Author"])
        self.assertEqual(meta["formal_count"], 0)
        self.assertEqual(meta["isbn"], "978-3-16-148410-0")
        self.assertEqual(meta["date"], {"year": 2026, "month": 1, "day": 2, "iso": "2026-01-02"})

    def test_restage_is_clean_and_deterministic(self):
        again = tp.stage(self.site, self.book, self.ed, self.model, None, out_dir=self.tmp / "stage2")
        self.assertEqual(again.book_md.read_text(encoding="utf-8"), self.md)


class HeadingHelpersTest(unittest.TestCase):
    def test_parse_heading_attrs_and_closing_hashes(self):
        level, text, attrs = tp.parse_heading("## Title ## {#x .y k=\"v\"}")
        self.assertEqual((level, text, attrs.id, attrs.classes, attrs.kv), (2, "Title", "x", ["y"], {"k": "v"}))
        self.assertIsNone(tp.parse_heading("#hashtag"))
        self.assertIsNone(tp.parse_heading("    # indented code"))

    def test_setext(self):
        self.assertEqual(tp.normalize_setext("Title\n===\n\nSub\n---\n"), "# Title\n\n## Sub\n")
        # a list item followed by --- is not a setext heading
        self.assertEqual(tp.normalize_setext("- item\n---\n"), "- item\n---\n")
        # inside a fence nothing changes
        self.assertEqual(tp.normalize_setext("```\nx\n===\n```\n"), "```\nx\n===\n```\n")

    def test_shift_caps_at_six(self):
        out = tp.restructure_chapter("# T\n\n###### Six\n", chapter_path="x.md", depth=2, chapter_id="ch-x",
                                     title="T", classes=["tr-chapter"], kv={}, linker=None)
        self.assertIn("### T {#ch-x .tr-chapter}", out)
        self.assertIn("###### Six", out)

    def test_chapter_slug(self):
        self.assertEqual(tp.chapter_slug("part 1/Intro.md"), "ch-part-1-intro")

    def test_heading_slugs_follow_mdbook(self):
        self.assertEqual(tp.heading_slugs("小结"), ["小结"])
        self.assertEqual(tp.heading_slugs("Section B.1: *Why*?"), ["section-b1-why"])
        # A footnote reference is its number for mdBook, its label for Pandoc (here the second footnote).
        self.assertEqual(tp.heading_slugs("The [`foo_bar`](x.md) _case_[^1]", notes={"0": 1, "1": 2}),
                         ["the-foo_bar-case2", "the-foo_bar-case1"])
        self.assertEqual(tp.heading_slugs("Ünïcode Title"), ["ünïcode-title"])
        self.assertEqual(tp.heading_slugs("$!$"), [])

    def test_scope_footnotes(self):
        md = "A[^1] and [^x].\n\n[^1]: one\n\n```\n[^1]\n```\n\n`[^1]` and ^[inline]\n"
        out = tp.scope_footnotes(md, "ch-a")
        self.assertIn("A[^ch-a--1] and [^x].", out)  # [^x] is not defined here: left alone
        self.assertIn("[^ch-a--1]: one", out)
        self.assertIn("```\n[^1]\n```", out)
        self.assertIn("`[^1]` and ^[inline]", out)
        self.assertEqual(tp.scope_footnotes("no notes [^1]\n", "ch-a"), "no notes [^1]\n")

    def test_assign_heading_ids(self):
        chapters = [("a.md", "# A\n\n## Summary\n\n## Summary\n\n## Own {#own}\n"),
                    ("b.md", "# B {#b-title}\n\n## Summary\n\n## Own\n\n::: {.remark #thm-x}\n:::\n\n## thm-x\n")]
        taken = {"thm-x", "ch-a", "b-title"}
        ids = tp.assign_heading_ids(chapters, {"a.md": "ch-a", "b.md": "b-title"}, taken)
        self.assertEqual(list(ids.by_line["a.md"].values()), ["summary", "summary-1"])
        self.assertEqual(list(ids.by_line["b.md"].values()), ["b-title--summary", "b-title--own", "b-title--thm-x"])
        # Explicit ids reach themselves, in their own chapter only.
        self.assertEqual(ids.anchors["a.md"], {"own": "own", "a": "ch-a", "summary": "summary", "summary-1": "summary-1"})
        # b.md: its title has an explicit id; "thm-x" is an id of its own (the remark), so the
        # heading slug "thm-x" does not take it over.
        self.assertEqual(ids.anchors["b.md"], {"b-title": "b-title", "thm-x": "thm-x", "summary": "b-title--summary",
                                               "own": "b-title--own"})
        self.assertLessEqual({"summary", "summary-1", "b-title--summary"}, taken)

    def test_file_links_without_base_url_keep_their_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            ed = make_book(Path(tmp)).edition("en")
            warnings: list[str] = []
            linker = tp._Linker(Path(tmp) / "stage", ed, {"a.md": "ch-a"}, warnings, set(), online="")
            self.assertEqual(linker.rewrite_line("Get [the table](files/table.csv).", "a.md"), "Get the table.")
            self.assertEqual(linker.rewrite_line("See ![dot](img/dot.png).", "a.md"), "See ![dot](_book/en/img/dot.png).")
            self.assertEqual(linker.rewrite_line("[t]: files/table.csv", "a.md"), "[t]: files/table.csv")
            # An angle-bracket destination that cannot be rewritten stays as written.
            self.assertEqual(linker.rewrite_line("[t]: <files/my table.csv>", "a.md"), "[t]: <files/my table.csv>")
        self.assertTrue(any("base_url" in w for w in warnings), warnings)

    NESTED_FENCES = """# A

> ```markdown
> See [B](b.md) and [outside](../out.md).
> ```

- item

  - nested item

    ```markdown
    See [B](b.md#sec-b).
    ```

````markdown
> ```
Shown after a quoted fence line: [B](b.md).
````

<!--
[B](b.md)
-->

Real [B](b.md).
"""

    def test_links_in_quoted_and_list_fences_are_not_rewritten(self):
        # Fences in block quotes and list items are code, as for tbook.render and Pandoc: a
        # chapter link inside one is shown as written, and nothing there is warned about.
        with tempfile.TemporaryDirectory() as tmp:
            ed = make_book(Path(tmp)).edition("en")
            warnings: list[str] = []
            linker = tp._Linker(Path(tmp) / "stage", ed, {"a.md": "ch-a", "b.md": "ch-b"}, warnings, set(),
                                anchors={"b.md": {"sec-b": "sec-b"}}, online=BASE_URL)
            out = tp.restructure_chapter(self.NESTED_FENCES, chapter_path="a.md", depth=1, chapter_id="ch-a",
                                         title="A", classes=["tr-chapter"], kv={}, linker=linker)
        self.assertIn("> See [B](b.md) and [outside](../out.md).", out)
        self.assertIn("    See [B](b.md#sec-b).", out)
        self.assertIn("Shown after a quoted fence line: [B](b.md).", out)
        self.assertIn("<!--\n[B](b.md)\n-->", out)
        self.assertIn("Real [B](#ch-b).", out)
        self.assertEqual(warnings, [])

    def test_code_mask_follows_mdscan(self):
        lines = self.NESTED_FENCES.split("\n")
        code = [line for line, hidden in zip(lines, tp._code_mask(lines)) if hidden]
        self.assertIn("> See [B](b.md) and [outside](../out.md).", code)
        self.assertIn("    See [B](b.md#sec-b).", code)
        self.assertIn("Shown after a quoted fence line: [B](b.md).", code)
        self.assertIn("[B](b.md)", code)
        self.assertNotIn("Real [B](b.md).", code)
        self.assertNotIn("- item", code)

    def test_spaced_and_encoded_paths(self):
        # tbook.render writes <…> destinations percent-encoded; the linker looks files up by
        # the decoded path and writes the staged path percent-encoded.
        with tempfile.TemporaryDirectory() as tmp:
            ed = make_book(Path(tmp)).edition("en")
            (ed.dir / "img dir").mkdir()
            (ed.dir / "img dir" / "a b.png").write_bytes(PNG_1PX)
            (ed.dir / "my notes.md").write_text("# Notes\n", encoding="utf-8")
            warnings: list[str] = []
            files: set[str] = set()
            chapters = {"a.md": "ch-a", "my notes.md": "ch-notes", "part/a1.md": "ch-part-a1"}
            linker = tp._Linker(Path(tmp) / "stage", ed, chapters, warnings, files, online=BASE_URL)
            staged = "_book/en/img%20dir/a%20b.png"
            for src in ("![x](<img dir/a b.png>)", "![x](img%20dir/a%20b.png)"):
                self.assertEqual(linker.rewrite_line(src, "a.md"), f"![x]({staged})")
            self.assertEqual(linker.rewrite_line("![x](<../img dir/a b.png>)", "part/a1.md"), f"![x]({staged})")
            self.assertEqual(linker.rewrite_line("[r]: <img dir/a b.png>", "a.md"), f"[r]: {staged}")
            self.assertEqual(linker.rewrite_line("[n](my%20notes.md) [m](<my notes.md>)", "a.md"),
                             "[n](#ch-notes) [m](#ch-notes)")
            self.assertEqual(linker.rewrite_line("[f](<img dir/a b.png>)", "a.md"),
                             f"[f]({BASE_URL}img%20dir/a%20b.png)")
            self.assertEqual(linker.rewrite_line("![b](_book/assets/my%20fig.svg)", "a.md"),
                             "![b](_book/assets/my%20fig.svg)")
            self.assertEqual(linker.rewrite_line("![x](%2Fetc%2Fhosts)", "a.md"), "![x](%2Fetc%2Fhosts)")
            self.assertTrue((Path(tmp) / "stage" / "_book/en/img dir/a b.png").is_file())
        self.assertEqual(files, {"_book/en/img dir/a b.png"})
        self.assertEqual(warnings, ["test-book/en/a.md: link leaves the edition: %2Fetc%2Fhosts"])


@unittest.skipUnless(have_pandoc(), "pandoc not available")
class LuaFilterTest(unittest.TestCase):
    META = {"tr-punct-open": " (", "tr-punct-close": ")", "tr-lean-label": "Lean", "tr-badge-lean-title": "verified"}

    def test_typst_output(self):
        out = run_filters(ENV_MD, "typst", self.META)
        self.assertIn('#tr-env(kind: "theorem", status: "lean", label: "Theorem", number: "1.2", '
                      'ref: "Theorem 1.2", title: [Bound on $c$], badge: "LEAN ✓", '
                      'badge-url: "https://example.org/X.lean#L3", lean: ((gid: "D5/S1/X.y", name: "D5.S1.X.y", url: "https://example.org/X.lean#L3"),), '
                      'id: "thm-x")[', out)
        self.assertRegex(out, r"\]\s*<thm-x>")
        self.assertIn("#link(<thm-x>)[the theorem]", out)
        self.assertNotIn("<missing>", out)  # dangling link became text
        self.assertIn('#tr-proof(label: "Proof", id: "")[', out)
        self.assertIn('#tr-proof-label("Proof")', out)
        self.assertIn("#tr-qed()", out)
        self.assertIn('status: "open"', out)
        self.assertIn('#tr-chapter(id: "ch-x", kicker: "§ 01", section: "numbered", outlined: true, title: [Chapter])', out)

    def test_html_output(self):
        out = run_filters(ENV_MD, "html5", self.META)
        self.assertIn('<section id="thm-x" class="tr-env tr-theorem tr-status-lean" data-kind="theorem">', out)
        self.assertIn('<header class="tr-env-head">', out)
        self.assertIn('<span class="tr-env-label">Theorem 1.2</span>', out)
        self.assertRegex(out, r'<span class="tr-env-title"> \(Bound on <span class="math inline">')
        self.assertIn('class="tr-badge tr-badge-lean"', out)
        self.assertIn('title="verified"', out)
        self.assertIn('<footer class="tr-env-lean">', out)
        self.assertIn('<a href="https://example.org/X.lean#L3" class="tr-lean-decl" title="D5/S1/X.y"><code>D5.S1.X.y</code></a>', out)
        self.assertIn('class="tr-env tr-proof tr-status-proof"', out)
        self.assertIn('<span class="tr-qed" aria-hidden="true">∎</span>', out)
        self.assertIn('class="tr-badge tr-badge-open"', out)
        self.assertIn('<span class="tr-dangling">nothing</span>', out)
        self.assertIn('<a href="#thm-x">the theorem</a>', out)

    def test_generic_fallback(self):
        out = run_filters(ENV_MD, "markdown", self.META)
        self.assertIn("**Theorem 1.2** (Bound on $c$)", out)
        self.assertIn("Lean: [`D5.S1.X.y`](https://example.org/X.lean#L3)", out)

    def test_long_code_gets_break_hints(self):
        md = "`D5.S3.ConceptDynamics.Restoration.target_recovery_criterion`\n"
        self.assertIn("#tr-code-break(", run_filters(md, "typst"))
        self.assertIn(".<wbr/>", run_filters(md, "html5"))

    TITLED = ('# C {#ch-c .tr-chapter}\n\nThanks @alice.\n\n'
              ':::::: {#rem-x .tr-env .remark tr-kind="remark" tr-status="informal" tr-label="Remark" '
              'tr-number="1.1" tr-ref="Remark 1.1" tr-title="Case of [@thm-x] for $\\\\norm{v}$"}\n'
              'Body $\\norm{w}$.\n::::::\n')

    def test_at_signs_are_text_not_citations(self):
        # A Typst #cite needs a bibliography the book does not have: the PDF build would fail.
        out = run_filters(self.TITLED, "typst", self.META)
        self.assertNotIn("#cite", out)
        self.assertIn("Thanks \\@alice.", out)
        self.assertIn("title: [Case of \\[\\@thm-x\\] for", out)
        self.assertNotIn("<thm-x>", out)

    def test_macros_reach_titles_and_body(self):
        meta = {**self.META, "tr-tex-macros": mathrender.newcommands()}
        typst = run_filters(mathrender.newcommands() + "\n\n" + self.TITLED, "typst", meta)
        self.assertNotIn("\\norm", typst)
        self.assertIn("for $lr(bar.v.double v bar.v.double)$]", typst)  # the title, read by tr-env.lua with the macros
        self.assertIn("Body $lr(bar.v.double w bar.v.double)$.", typst)
        html = run_filters(mathrender.newcommands() + "\n\n" + self.TITLED, "html5", meta)
        self.assertNotIn("\\norm", html)
        self.assertNotIn("newcommand", html)


@unittest.skipUnless(have_pandoc(), "pandoc not available")
class TypstSymbolTest(unittest.TestCase):
    """Pandoc's Typst writer still emits symbol names the pinned Typst renamed (\\cap → sect, \\odot →
    dot.circle); tools/filters/typst-compat.lua writes the new names, in the text and in environment titles."""

    META = LuaFilterTest.META

    @unittest.skipUnless(have_typst(), "typst not available")
    def test_fixed_size_delimiters_are_symbols_in_text_and_titles(self):
        import typst
        import xml.etree.ElementTree as ET

        formula = r"\Bigl\langle x,y\Bigr\rangle + \bigl\lceil x\bigr\rceil + \bigl\lfloor y\bigr\rfloor"
        out = run_filters(f"${formula}$", "typst", self.META)
        for name in ("chevron.l", "chevron.r", "ceil.l", "ceil.r", "floor.l", "floor.r"):
            self.assertIn(f"stretch({name}, size: #", out)
        self.assertNotIn("#scale", out)
        # These delimiters must occupy glyph widths, not the widths of their names.
        svg = typst.compile(('#set page(width: auto, height: auto, margin: 0pt)\n' + out).encode(),
                            format="svg")
        width = ET.fromstring(svg).attrib["width"]
        self.assertLess(float(width.removesuffix("pt")), 150)
        title = formula.replace("\\", "\\\\")
        env = (':::::: {.tr-env .remark tr-kind="remark" tr-status="informal" '
               f'tr-label="Remark" tr-ref="Remark 1.1" tr-title="${title}$"}}\nBody.\n::::::\n')
        titled = run_filters(env, "typst", self.META)
        self.assertIn("title: [", titled)
        for name in ("chevron.l", "chevron.r", "ceil.l", "ceil.r", "floor.l", "floor.r"):
            self.assertIn(f"stretch({name}, size: #", titled)
        literal = run_filters(r'$\text{chevron.l} + \text{ceil.l} + \text{floor.l}$', "typst", self.META)
        self.assertNotIn("#sym.", literal)

    def test_renamed_symbols(self):
        md = ("Meet $A \\cap B$, $\\bigcap_i A_i$, $A \\Cap B$, $a \\sqcap b$, $a \\odot b$, $\\bigodot_i a_i$, "
              "$a \\otimes b$, $\\bigotimes_i a_i$, $a \\ominus b$, $a \\circleddash b$, $\\text{sect} \\cap x$, "
              "$\\mathrm{intersect}$.\n\n"
              ':::::: {#rem-x .tr-env .remark tr-kind="remark" tr-status="informal" tr-label="Remark" '
              'tr-number="1.1" tr-ref="Remark 1.1" tr-title="On $A \\\\cap B$"}\nBody.\n::::::\n')
        out = run_filters(md, "typst", self.META)
        for new in ("A inter B", "inter.big", "inter.double", "inter.sq", "dot.o", "dot.o.big", "times.o",
                    "times.o.big", "minus.o", "dash.o", 'title: [On $A inter B$]', 'upright("sect")/**/inter x'):
            self.assertIn(new, out)
        self.assertNotRegex(re.sub(r'"[^"]*"', "", out), r"\bsect\b|\.circle\b")
        self.assertIn("upright(i n t e r s e c t)", out)  # letters, not the name sect

    @unittest.skipUnless(have_typst(), "typst not available")
    def test_every_katex_symbol_compiles(self):
        """Every math symbol KaTeX renders in HTML compiles in the PDF too."""
        import typst  # type: ignore

        katex = paths.ROOT / "node_modules" / "katex" / "dist" / "katex.js"
        if not katex.is_file():
            self.skipTest("node_modules/katex is not installed")
        names = sorted(set(re.findall(r'defineSymbol\(math, \w+, \w+, [^,]*, "\\\\([A-Za-z]+)"',
                                      katex.read_text(encoding="utf-8"))))
        self.assertGreater(len(names), 300)
        out = run_filters("\n\n".join(f"$a \\{n} b$" for n in names), "typst", self.META)
        paras = [p for p in re.split(r"\n\s*\n", out) if p.strip()]
        self.assertEqual(len(paras), len(names))
        failed = []
        with tempfile.TemporaryDirectory() as tmp:
            for name, para in zip(names, paras):
                src = Path(tmp) / "m.typ"
                src.write_text(para, encoding="utf-8")
                try:
                    typst.compile(str(src), format="svg")
                except Exception as exc:  # noqa: BLE001 - collect every failing symbol
                    failed.append(f"\\{name} → {para.strip()}: {str(exc).splitlines()[0]}")
        self.assertEqual(failed, [], "add the rename to tools/filters/typst-compat.lua")


class MetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-test-meta-"))
        cls.book = make_book(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_identifier(self):
        ed = self.book.edition("en")
        self.assertEqual(tp.edition_identifier(self.book, ed), "urn:isbn:9783161484100")
        self.book.isbn = {}
        try:
            ident = tp.edition_identifier(self.book, ed)
            self.assertRegex(ident, r"^urn:uuid:[0-9a-f-]{36}$")
            self.assertEqual(ident, tp.edition_identifier(self.book, ed))  # deterministic (uuid5)
        finally:
            self.book.isbn = {"en": "978-3-16-148410-0"}

    def test_source_date_epoch(self):
        old = os.environ.pop("SOURCE_DATE_EPOCH", None)
        try:
            self.assertEqual(tp.source_date_epoch(self.book), 1767312000)  # 2026-01-02T00:00:00Z
        finally:
            if old is not None:
                os.environ["SOURCE_DATE_EPOCH"] = old

    def test_strings_fallback(self):
        self.assertEqual(tp.t("zh", "pdf.colophon"), "版权信息")
        self.assertEqual(tp.t("en", "pdf.colophon"), "Colophon")
        self.assertEqual(tp.t("fr", "pdf.colophon"), "Colophon")
        self.assertEqual(tp.t("en", "ui.contents"), "Contents")  # shared i18n wins
        self.assertIn("3", tp.t("en", "pdf.verified_statement", n=3))

    def test_display_options(self):
        self.assertIn('<option name="specified-fonts">false</option>', tp.display_options_xml(False))
        self.assertIn('<option name="specified-fonts">true</option>', tp.display_options_xml(True))

    def test_palette_css_uses_tokens(self):
        css = tp.epub_palette_css()
        tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
        self.assertIn(f"--tr-cyan: {tokens['paper']['cyan']};", css)
        self.assertIn(f"--tr-cyan: {tokens['screen']['cyan']};", css)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn('__ibooks_internal_theme*="Night"', css)

    def test_code_theme_from_tokens(self):
        tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
        xml = tp.code_theme(tokens["screen"], "screen")
        self.assertIn(tokens["screen"]["magenta"], xml)
        self.assertNotIn(tokens["screen"]["ok"], xml)  # green is reserved for Lean-verified

    def test_woff_conversion(self):
        src = paths.ROOT / "node_modules/@fontsource/chakra-petch/files/chakra-petch-latin-400-normal.woff"
        if not src.exists():
            self.skipTest("@fontsource/chakra-petch not installed")
        ttf = tp._woff_to_sfnt(src.read_bytes())
        self.assertEqual(ttf[:4], b"\x00\x01\x00\x00")

    def test_finalize_epub_layout(self):
        raw = self.tmp / "raw.epub"
        with zipfile.ZipFile(raw, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            z.writestr("META-INF/container.xml", "<container/>")
            z.writestr("META-INF/com.apple.ibooks.display-options.xml", "old")
            z.writestr("EPUB/text/ch001.xhtml", "<html><head><title>ch001.xhtml</title></head>"
                                                "<body><h1 id=\"a\">One <em>two</em></h1></body></html>")
        out = tp.finalize_epub(raw, self.tmp / "out.epub", specified_fonts=False, epoch=1767312000, title="T")
        with zipfile.ZipFile(out) as z:
            infos = z.infolist()
            self.assertEqual(infos[0].filename, "mimetype")
            self.assertEqual(infos[0].compress_type, zipfile.ZIP_STORED)
            self.assertEqual(infos[1].filename, "META-INF/container.xml")
            self.assertEqual(infos[2].filename, tp.DISPLAY_OPTIONS)
            self.assertIn(b"false", z.read(tp.DISPLAY_OPTIONS))
            self.assertIn(b"<title>One two</title>", z.read("EPUB/text/ch001.xhtml"))
            self.assertTrue(all(i.date_time == (2026, 1, 2, 0, 0, 0) for i in infos))

    def test_finalize_epub_declares_mathml_in_nav(self):
        # Pandoc copies heading MathML into nav.xhtml but declares `mathml` only for chapters
        # (epubcheck OPF-014).
        math = b'<math display="inline" xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'
        opf = (b'<package><manifest>\n'
               b'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />\n'
               b'<item id="c1" href="text/ch001.xhtml" media-type="application/xhtml+xml" properties="mathml" />\n'
               b'<item id="c2" href="text/ch002.xhtml" media-type="application/xhtml+xml" />\n'
               b'<item id="c3" href="text/ch003.xhtml" media-type="application/xhtml+xml" />\n'
               b'</manifest></package>')
        raw = self.tmp / "math.epub"
        with zipfile.ZipFile(raw, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="EPUB/content.opf" '
                                                 'media-type="application/oebps-package+xml" /></rootfiles></container>')
            z.writestr("EPUB/content.opf", opf)
            z.writestr("EPUB/nav.xhtml", b"<nav><a href='text/ch001.xhtml#h'>T " + math + b"</a></nav>")
            z.writestr("EPUB/text/ch001.xhtml", b"<html><body><h1>T " + math + b"</h1></body></html>")
            z.writestr("EPUB/text/ch002.xhtml", b"<html><body><p>" + math + b"</p></body></html>")
            z.writestr("EPUB/text/ch003.xhtml", b"<html><body><p>no math</p></body></html>")
        out = tp.finalize_epub(raw, self.tmp / "math-out.epub", specified_fonts=False, epoch=0)
        with zipfile.ZipFile(out) as z:
            new = z.read("EPUB/content.opf").decode("utf-8")
        self.assertIn('href="nav.xhtml" media-type="application/xhtml+xml" properties="nav mathml" />', new)
        self.assertIn('href="text/ch001.xhtml" media-type="application/xhtml+xml" properties="mathml" />', new)
        self.assertIn('href="text/ch002.xhtml" media-type="application/xhtml+xml" properties="mathml"/>', new)
        self.assertIn('href="text/ch003.xhtml" media-type="application/xhtml+xml" />', new)


@unittest.skipUnless(have_pandoc() and have_typst(), "pandoc or typst not available")
class BuildTest(unittest.TestCase):
    """End-to-end builds of the synthetic book (PDF variants, EPUB, covers)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-test-build-"))
        cls.site = fixture_site()
        cls.book = make_book(cls.tmp)
        cls.ed = cls.book.edition("en")
        cls.model = load_edition(cls.ed)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_pdf_variants(self):
        for variant in config.PDF_VARIANTS:
            out = tp.build_pdf(self.site, self.book, self.ed, self.model, None, variant,
                               self.tmp / f"book-{variant}.pdf", stage_dir=self.tmp / f"stage-{variant}")
            data = out.read_bytes()
            self.assertTrue(data.startswith(b"%PDF-"))
            self.assertGreater(len(data), 20_000)
        main = (self.tmp / "stage-screen" / "main.typ").read_text(encoding="utf-8")
        self.assertIn('#tr-part(id: "tr-part-1"', main)
        self.assertIn('#tr-media(kind: "viz")[', main)
        self.assertNotIn("<nowhere>", main)
        # Each chapter keeps its own footnote text.
        self.assertIn("note#footnote[NOTE-A-TEXT]", main)
        self.assertIn("note#footnote[NOTE-B-TEXT]", main)
        # "@alice" is text, not a citation (Typst would demand a bibliography).
        self.assertNotIn("#cite", main)
        # Macros are expanded in math (no raw TeX fallback), titles included.
        self.assertNotIn("\\norm", main)
        self.assertIn("a norm $lr(bar.v.double x bar.v.double)$ and $⌊y⌋$", main)
        self.assertIn("== Bound $x^2$ for $lr(bar.v.double x bar.v.double)$", main)
        # b.md#summary reaches B's "Summary", not A's.
        self.assertIn("#link(<ch-b--summary>)[the summary of B]", main)
        self.assertRegex(main, r"== Summary\s*<ch-b--summary>")
        self.assertIn(f'#link("{BASE_URL}test-book/en/_book/assets/data.csv")[the data]', main)

    def test_pdf_rejects_unknown_variant(self):
        with self.assertRaises(tp.PandocError):
            tp.build_pdf(self.site, self.book, self.ed, self.model, None, "glossy", self.tmp / "x.pdf")

    def test_epub(self):
        old = os.environ.get("TBOOK_EPUBCHECK")
        os.environ["TBOOK_EPUBCHECK"] = "0"
        try:
            out = tp.build_epub(self.site, self.book, self.ed, self.model, None, self.tmp / "book.epub",
                                stage_dir=self.tmp / "stage-epub")
        finally:
            if old is None:
                os.environ.pop("TBOOK_EPUBCHECK", None)
            else:
                os.environ["TBOOK_EPUBCHECK"] = old
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            self.assertEqual(names[0], "mimetype")
            opf = z.read("EPUB/content.opf").decode("utf-8")
            css = z.read("EPUB/styles/stylesheet1.css").decode("utf-8")
            texts = "".join(z.read(n).decode("utf-8") for n in names if n.endswith(".xhtml"))
            nav = z.read("EPUB/nav.xhtml").decode("utf-8")
            chapter = {n: z.read(n).decode("utf-8") for n in names if re.search(r"text/ch\d+\.xhtml$", n)}
        a = next(t for t in chapter.values() if "NOTE-A-TEXT" in t)
        b = next(t for t in chapter.values() if "NOTE-B-TEXT" in t)
        self.assertNotEqual(a, b)  # each note's text stays in its own chapter file
        self.assertNotIn("NOTE-B-TEXT", a)
        self.assertIn("<math", nav)  # "## Bound $x^2$ …" in the table of contents
        self.assertRegex(opf, r'href="nav\.xhtml"[^>]*properties="nav mathml"')
        self.assertIn(f'href="{BASE_URL}test-book/en/files/table.csv"', texts)
        self.assertNotIn("\\norm", texts)  # expanded before MathML conversion (annotations too)
        self.assertIn("<dc:title id=\"epub-title-1\">Test Book</dc:title>", opf)
        self.assertIn('property="title-type">subtitle</meta>', opf)
        self.assertIn("<dc:language>en</dc:language>", opf)
        self.assertIn("9783161484100", opf)
        self.assertIn('<meta property="ibooks:version">1.2.3</meta>', opf)
        self.assertIn("<dc:rights>CC-BY-4.0</dc:rights>", opf)
        self.assertIn("A. Author", opf)
        self.assertIn('properties="cover-image"', opf)
        self.assertIn("2026-01-02T00:00:00Z", opf)  # dcterms:modified from SOURCE_DATE_EPOCH
        self.assertIn("--tr-ok:", css)
        self.assertIn('epub:type="copyright-page"', texts)
        self.assertIn('href="ch', texts)  # cross-file links resolved by the EPUB writer
        self.assertIn('<math', texts)  # MathML
        self.assertIn("tr-dangling", texts)
        self.assertNotIn("<title>ch0", texts)
        if shutil.which("java"):
            report = tp.check_epub(out)
            if not report.skipped:
                self.assertEqual(report.errors, [])

    def test_epub_embedded_fonts(self):
        fonts = [f for f in tp.epub_font_files() if tp._font_face(f) and not tp._font_face(f)[0].endswith(" SC")]
        if not fonts:
            self.skipTest("no Latin font files to embed")
        self.book.epub["embed_fonts"] = True
        os.environ["TBOOK_EPUBCHECK"] = "0"
        try:
            out = tp.build_epub(self.site, self.book, self.ed, self.model, None, self.tmp / "fonts.epub",
                                stage_dir=self.tmp / "stage-fonts")
        finally:
            self.book.epub.pop("embed_fonts", None)
            os.environ.pop("TBOOK_EPUBCHECK", None)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            css = z.read("EPUB/styles/stylesheet1.css").decode("utf-8")
            self.assertIn(b"<option name=\"specified-fonts\">true</option>", z.read(tp.DISPLAY_OPTIONS))
        self.assertTrue(any(n.startswith("EPUB/fonts/") for n in names), names)
        self.assertIn("@font-face", css)
        if shutil.which("java"):
            report = tp.check_epub(out)
            if not report.skipped:
                self.assertEqual(report.errors, [])

    def test_epub_deterministic(self):
        os.environ["TBOOK_EPUBCHECK"] = "0"
        try:
            a = tp.build_epub(self.site, self.book, self.ed, self.model, None, self.tmp / "a.epub",
                              stage_dir=self.tmp / "stage-a")
            b = tp.build_epub(self.site, self.book, self.ed, self.model, None, self.tmp / "b.epub",
                              stage_dir=self.tmp / "stage-b")
        finally:
            os.environ.pop("TBOOK_EPUBCHECK", None)
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_cover_formats(self):
        png = cover.render_cover(self.site, self.book, self.ed, self.tmp / "c.png", model=self.model, lock=None)
        data = png.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        self.assertEqual((width, height), (1600, 2560))
        pdf = cover.render_cover(self.site, self.book, self.ed, self.tmp / "c.pdf", fmt="pdf",
                                 variant="print", model=self.model, lock=None)
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
        svg = cover.render_cover(self.site, self.book, self.ed, self.tmp / "c.svg", fmt="svg", model=self.model, lock=None)
        self.assertIn(b"<svg", svg.read_bytes()[:400])
        academic = cover.render_cover(self.site, self.book, self.ed, self.tmp / "academic.svg", fmt="svg",
                                      variant="academic", model=self.model, lock=None)
        self.assertNotIn(b"Gradient", academic.read_bytes())
        with self.assertRaises(ValueError):
            cover.render_cover(self.site, self.book, self.ed, self.tmp / "c.gif", fmt="gif")


class VerifiedCountTest(unittest.TestCase):
    """Only formal results the lock backs count as LEAN ✓: ledger kicker, colophon, cover."""

    GID_OK = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"
    GID_MISSING = "D5/S1/Deficit/DeficitThreeValued.not_in_the_lock"

    def test_unbacked_results_are_not_counted(self):
        lock = lean.Lock(repo="the-omega-institute/trureturing", branch="dev", commit="c" * 40, declarations={
            self.GID_OK: {"module": "D5/S1/Deficit/DeficitThreeValued", "name": "D5.S1.Deficit.deficit_three_valued",
                          "kind": "theorem", "statement_id": "sha256:3v", "line": 12, "signature": ""}})
        site = fixture_site()
        with tempfile.TemporaryDirectory() as tmp:
            book = make_book(Path(tmp))
            ed = book.edition("en")
            with (ed.dir / "b.md").open("a", encoding="utf-8") as f:
                f.write(f'\n::: {{.theorem #thm-ok lean="{self.GID_OK}"}}\nBacked.\n:::\n\n'
                        f'::: {{.lemma #lem-missing lean="{self.GID_MISSING}"}}\nNot in the lock.\n:::\n\n'
                        f'::: {{.corollary #cor-half lean="{self.GID_OK}, {self.GID_MISSING}"}}\nHalf backed.\n:::\n')
            model = load_edition(ed)
            with contextlib.redirect_stderr(io.StringIO()):  # the fixture's own link warnings
                staged = tp.stage(site, book, ed, model, lock, out_dir=Path(tmp) / "stage")
            md = staged.book_md.read_text(encoding="utf-8")
            cover_meta = tp.book_meta(site, book, ed, model, lock)  # what tbook.cover draws
        self.assertEqual([e.id for e in model.formal_envs()], ["thm-ok", "lem-missing", "cor-half"])
        self.assertEqual(staged.formal_count, 1)
        self.assertEqual(staged.meta["formal_count"], 1)
        self.assertEqual(cover_meta["formal_count"], 1)
        kicker = next(line for line in md.splitlines() if "{#tr-verification-ledger" in line)
        self.assertIn('tr-kicker="LEAN ✓ 1"', kicker)
        statement = tp.t("en", "pdf.verified_statement", n=1)
        self.assertEqual(staged.meta["strings"]["verified_statement"], statement)
        self.assertIn(tp._md_escape(statement), tp.epub_colophon(staged.meta))
        # The ledger still lists every formal result; the unbacked ones are not linked as verified.
        for env_id in ("thm-ok", "lem-missing", "cor-half"):
            self.assertIn(f"](#{env_id})", md)


@unittest.skipUnless(have_pandoc() and have_typst(), "pandoc or typst not available")
class SpacedPathBuildTest(unittest.TestCase):
    """An edition image whose path has spaces, written as ``<…>`` or percent-encoded, is staged
    under its real name and embedded in the PDF and the EPUB, with no warning."""

    STAGED = "_book/en/img dir/a b.png"
    ALTS = ("spaced angle", "spaced encoded", "spaced reference", "spaced nested")

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-test-spaced-"))
        cls.site = fixture_site()
        cls.book = make_book(cls.tmp)
        cls.ed = cls.book.edition("en")
        (cls.ed.dir / "img dir").mkdir()
        (cls.ed.dir / "img dir" / "a b.png").write_bytes(_png(6, 6))
        with (cls.ed.dir / "b.md").open("a", encoding="utf-8") as f:
            f.write("\n![spaced angle](<img dir/a b.png>)\n\n![spaced encoded](img%20dir/a%20b.png)\n\n"
                    "![spaced reference][sp]\n\n[sp]: <img dir/a b.png>\n")
        with (cls.ed.dir / "part" / "a1.md").open("a", encoding="utf-8") as f:
            f.write("\n![spaced nested](<../img dir/a b.png>)\n")
        cls.model = load_edition(cls.ed)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def quiet(self, fn, *args, **kwargs):
        """Run ``fn`` with stderr captured (stage warnings, Pandoc and Lua filter messages)."""
        err = io.StringIO()
        old = os.environ.get("TBOOK_EPUBCHECK")
        os.environ["TBOOK_EPUBCHECK"] = "0"
        try:
            with contextlib.redirect_stderr(err):
                out = fn(*args, **kwargs)
        finally:
            if old is None:
                os.environ.pop("TBOOK_EPUBCHECK", None)
            else:
                os.environ["TBOOK_EPUBCHECK"] = old
        self.assertNotIn("not found", err.getvalue())
        self.assertNotIn("a b.png", err.getvalue())
        self.assertNotIn("a%20b.png", err.getvalue())
        return out

    def test_staged(self):
        staged = self.quiet(tp.stage, self.site, self.book, self.ed, self.model, None, out_dir=self.tmp / "stage")
        md = staged.book_md.read_text(encoding="utf-8")
        encoded = self.STAGED.replace(" ", "%20")
        for alt in ("spaced angle", "spaced encoded", "spaced nested"):
            self.assertIn(f"![{alt}]({encoded})", md)
        self.assertIn(f"[sp]: {encoded}", md)
        self.assertIn(self.STAGED, staged.files)
        self.assertTrue((staged.dir / self.STAGED).is_file())
        self.assertEqual([w for w in staged.warnings if "img" in w], [])

    def test_pdf(self):
        out = self.quiet(tp.build_pdf, self.site, self.book, self.ed, self.model, None, "print",
                         self.tmp / "spaced.pdf", stage_dir=self.tmp / "stage-pdf")
        self.assertTrue(out.read_bytes().startswith(b"%PDF-"))
        main = (self.tmp / "stage-pdf" / "main.typ").read_text(encoding="utf-8")
        self.assertEqual(main.count(f'image("{self.STAGED}"'), len(self.ALTS), main)

    def test_epub(self):
        out = self.quiet(tp.build_epub, self.site, self.book, self.ed, self.model, None, self.tmp / "spaced.epub",
                         stage_dir=self.tmp / "stage-epub")
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            pages = {n: z.read(n).decode("utf-8") for n in names if n.endswith(".xhtml")}
            image = (self.tmp / "stage-epub" / self.STAGED).read_bytes()
            found = []
            for name, page in pages.items():
                for src, alt in re.findall(r'<img src="([^"]+)" alt="(spaced [a-z]+)"', page):
                    target = os.path.normpath(os.path.join(os.path.dirname(name), src))
                    self.assertIn(target, names, f"{alt}: {src}")
                    self.assertEqual(z.read(target), image, alt)
                    found.append(alt)
        self.assertEqual(sorted(found), sorted(self.ALTS))
        if shutil.which("java"):
            report = tp.check_epub(out)
            if not report.skipped:
                self.assertEqual(report.errors, [])


@unittest.skipUnless(have_pandoc() and have_typst() and shutil.which("java"), "pandoc, typst or java missing")
@unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden")
class ExampleBookEpubcheckTest(unittest.TestCase):
    """The shipped example book must produce an EPUB that epubcheck accepts with zero errors."""

    def test_example_epub_valid(self):
        try:
            lock = lean.Lock.load()
        except lean.LeanError as exc:
            self.skipTest(str(exc))
        try:
            book = config.load_book("example-monograph")
        except config.ConfigError as exc:
            self.skipTest(str(exc))
        site = config.load_site()
        with tempfile.TemporaryDirectory(prefix="tbook-test-example-") as tmp:
            for ed in book.editions:
                os.environ["TBOOK_EPUBCHECK"] = "0"
                try:
                    out = tp.build_epub(site, book, ed, load_edition(ed), lock, Path(tmp) / f"{ed.lang}.epub",
                                        stage_dir=Path(tmp) / f"stage-{ed.lang}")
                finally:
                    os.environ.pop("TBOOK_EPUBCHECK", None)
                report = tp.check_epub(out)
                if report.skipped:
                    self.skipTest(report.skipped)
                self.assertEqual(report.errors, [], f"{ed.lang}: {report.errors}")


if __name__ == "__main__":
    unittest.main()
