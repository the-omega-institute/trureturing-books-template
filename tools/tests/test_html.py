"""Tests for the HTML (mdBook) pipeline: math scanning/splicing, staging, search index.

Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_html.py'

Tests that need Node + KaTeX (``npm ci``) or mdBook (``$MDBOOK`` or ``mdbook`` on PATH) are
skipped when those tools are missing.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

from example_support import example_shown

from tbook import config, html, lean, ledger, mathrender, paths
from tbook.model import load_edition
from tbook.summary import parse_summary

NODE = shutil.which("node")
HAVE_KATEX = bool(NODE) and (paths.ROOT / "node_modules" / "katex" / "package.json").exists()
MDBOOK = os.environ.get("MDBOOK") or shutil.which("mdbook")
LOCK = lean.Lock.load()
EXAMPLE = paths.BOOKS / "example-monograph"
# The staging test's own lock: the verified count follows the lock, so it must not be the repository's.
STAGE_LOCK = lean.Lock(
    repo="the-omega-institute/trureturing", branch="dev", commit="d" * 40, pinned_at="2026-01-01T00:00:00Z",
    declarations={
        "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued": {
            "module": "D5/S1/Deficit/DeficitThreeValued", "name": "D5.S1.Deficit.deficit_three_valued",
            "kind": "theorem", "statement_id": "sha256:3v", "line": 12},
        "D5/S1/Deficit/DeficitInteger.deficit_integer": {
            "module": "D5/S1/Deficit/DeficitInteger", "name": "D5.S1.Deficit.deficit_integer",
            "kind": "theorem", "statement_id": "sha256:int", "line": 5},
    })


def texs(text: str) -> list[str]:
    return [s.tex for s in mathrender.find_math(text)[0]]


# --------------------------------------------------------------------------- scanner


class CapitalizedHeadingsKeepMathTest(unittest.TestCase):
    """Where the theme sets text the author writes in capitals (table header cells, SUMMARY part titles, slide
    table headers), math and code keep their case: uppercase would turn $\\varphi$ into $\\Phi$ and $n$ into
    $N$, a different formula."""

    def rules(self, path: Path) -> list[tuple[str, str]]:
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)]

    def test_math_and_code_keep_their_case(self):
        for rel, containers in (("theme/mdbook/tr-book.css", (".content main table th", ".chapter li.part-title")),
                                ("theme/slides/styles/deck.css", ("table.t th",))):
            rules = self.rules(paths.ROOT / rel)
            for container in containers:
                upper = [b for sel, b in rules if container in [x.strip() for x in sel.split(",")]
                         and re.search(r"text-transform:\s*uppercase", b)]
                self.assertTrue(upper, f"{rel}: {container} is no longer capitalized; update this test")
                exempt = [b for sel, b in rules if f"{container} :is(.katex, code)" in re.sub(r"\s+", " ", sel)]
                self.assertTrue(exempt and re.search(r"text-transform:\s*none", exempt[0]), f"{rel}: {container}")


class FindMathTest(unittest.TestCase):
    def test_inline(self):
        self.assertEqual(texs("a $x$ b $y^2$ c"), ["x", "y^2"])

    def test_currency_is_text(self):
        self.assertEqual(texs("costs $5 and $6 today"), [])

    def test_opening_followed_by_space_is_text(self):
        self.assertEqual(texs("a $ x$ b"), [])

    def test_closing_followed_by_digit_is_not_a_closer(self):
        self.assertEqual(texs("$x$2 y"), [])
        self.assertEqual(texs("$a$1 and $b$"), ["a$1 and $b"])

    def test_invalid_closer_is_skipped(self):
        # Pandoc keeps scanning for a closer that is not preceded by whitespace.
        self.assertEqual(texs("$a $b$"), ["a $b"])

    def test_escaped_dollar(self):
        self.assertEqual(texs(r"price \$5 and \$x$"), [])
        self.assertEqual(texs(r"\\$x$"), ["x"])  # even number of backslashes: not escaped

    def test_inline_code_and_fences(self):
        self.assertEqual(texs("`$a$` and $b$"), ["b"])
        self.assertEqual(texs("``x `$a$` y`` $b$"), ["b"])
        text = "```\n$a$\n```\n$b$\n~~~~\n$c$\n~~~\nstill code $d$\n~~~~\n$e$"
        self.assertEqual(texs(text), ["b", "e"])

    def test_html_masks_and_decoding(self):
        text = '<header><span title="$t$">（$a &lt; b$）</span></header>'
        self.assertEqual(texs(text), ["a < b"])
        # In a Markdown paragraph the TeX is raw (Pandoc does not decode entities in math).
        self.assertEqual(texs("text $a &lt; b$"), ["a &lt; b"])
        self.assertEqual(texs("<!-- $x$ --> $y$"), ["y"])
        self.assertEqual(texs("<code>$x$</code> $y$"), ["y"])
        self.assertEqual(texs("[$x$](http://a/$b$)"), ["x"])
        self.assertEqual(texs("<https://a.b/$x$> $y$"), ["y"])

    def test_span_containing_code_is_not_math(self):
        self.assertEqual(texs("$a `b` c$"), [])

    def test_display(self):
        spans, notes = mathrender.find_math("para\n$$\nc = 1\n$$\nafter")
        self.assertEqual([(s.tex, s.display, s.block, s.line) for s in spans], [("c = 1", True, True, 2)])
        self.assertEqual(notes, [])
        spans, _ = mathrender.find_math("inline $$x$$ display")
        self.assertEqual([(s.tex, s.display, s.block) for s in spans], [("x", True, False)])
        self.assertEqual(mathrender.find_math("    $$x$$")[0], [])  # an indented code block
        spans, _ = mathrender.find_math("- item\n\n    $$x$$")  # list item text, not an HTML block
        self.assertFalse(spans[0].block)

    def test_display_in_blockquote(self):
        spans, _ = mathrender.find_math("> $$\n> a^2\n> + b\n> $$")
        self.assertEqual(spans[0].tex, "a^2\n+ b")
        self.assertTrue(spans[0].block)
        self.assertEqual(spans[0].prefix, "> ")

    def test_unpaired_display_and_blank_lines(self):
        spans, notes = mathrender.find_math("$$ unpaired\n\nnext")
        self.assertEqual(spans, [])
        self.assertEqual(notes, [(1, "unpaired $$ left as text")])
        self.assertEqual(texs("$x\n\ny$"), [])
        self.assertEqual(texs("$x\ny$"), ["x\ny"])  # soft line break inside inline math

    def test_table_row_pipe(self):
        # "\|" is the norm bar in a table row too: Pandoc (PDF/EPUB) keeps it, and the formula
        # is rendered before mdBook splits the row, so HTML must not turn it into "|".
        self.assertEqual(texs(r"| $\|x\|$ | b |"), [r"\|x\|"])
        self.assertEqual(texs(r"text $\|x\|$"), [r"\|x\|"])
        self.assertEqual(texs(r"| $|x|$ | b |"), ["|x|"])


class MacroTest(unittest.TestCase):
    def test_newcommands_count_arguments(self):
        self.assertEqual(mathrender.newcommands({"\\a": "x #1 #2", "\\b": "y", "\\c": ""}),
                         "\\newcommand{\\a}[2]{x #1 #2}\n\\newcommand{\\b}{y}\n\\newcommand{\\c}{}")
        self.assertIn("\\newcommand{\\norm}[1]{\\left\\lVert #1\\right\\rVert}", mathrender.newcommands())
        self.assertIn("\\newcommand{\\Tr}{\\operatorname{Tr}}", mathrender.newcommands())

    @unittest.skipUnless(HAVE_KATEX, "node and the katex package are required")
    def test_katex_gets_the_macro_table(self):
        answers = mathrender.render_formulas([(r"\norm{x} + \Tr A + \nicefrac{1}{2}", False)])
        self.assertIn("html", answers[0], answers)
        self.assertNotIn("lenient", answers[0])
        self.assertIn("∥", answers[0]["html"])
        self.assertIn('mathrm">Tr<', answers[0]["html"])


# --------------------------------------------------------------------------- splicing


FAKE = ('<span class="katex" role="math" aria-label="t=r|p"><span class="katex-html" aria-hidden="true">'
        '<span class="katex-base"><span class="mord">t</span><span class="mrel">=</span></span>'
        '<span class="katex-base"><span class="mord">r</span></span>'
        '<span class="katex-base"><span class="mord">p</span></span></span></span>')


class SpliceTest(unittest.TestCase):
    def test_block_and_inline(self):
        text = "a $x$ b\n$$\ny\n$$\nc"
        spans, _ = mathrender.find_math(text)
        out = mathrender.splice(text, spans, ["<X>", "<Y>"])
        self.assertEqual(out, 'a <X> b\n\n<div class="tr-math"><Y></div>\n\nc')

    def test_block_in_blockquote(self):
        text = "> intro\n> $$\n> y\n> $$\n> end"
        spans, _ = mathrender.find_math(text)
        out = mathrender.splice(text, spans, ["<Y>"])
        self.assertEqual(out, '> intro\n>\n> <div class="tr-math"><Y></div>\n>\n> end')

    def test_glue_keeps_punctuation_with_last_box(self):
        text = "使 $t=r|p$，当且"
        spans, _ = mathrender.find_math(text)
        out = mathrender.splice(text, spans, [FAKE])
        self.assertTrue(out.endswith("</span>当且"), out)
        self.assertNotIn("$", out)
        nobr = out[out.index('<span class="tr-nobr">'):]
        self.assertIn('<span class="mord">p</span>', nobr)
        self.assertIn("，</span>", nobr)
        self.assertNotIn('<span class="mord">r</span>', nobr)
        # the accessible formula keeps its label; split-off boxes are hidden from AT
        self.assertIn('role="math" aria-label="t=r|p"', out)
        self.assertIn('<span class="katex" aria-hidden="true">', nobr)

    def test_glue_opening_and_single_box(self):
        single = '<span class="katex"><span class="katex-html" aria-hidden="true"><span class="katex-base">x</span></span></span>'
        text = "（$x$）"
        spans, _ = mathrender.find_math(text)
        out = mathrender.splice(text, spans, [single])
        self.assertEqual(out, f'<span class="tr-nobr">（{single}）</span>')
        text = "($x$."
        spans, _ = mathrender.find_math(text)
        out = mathrender.splice(text, spans, [single])
        self.assertEqual(out, f'<span class="tr-nobr">&#40;{single}&#46;</span>')

    def test_glue_does_not_take_markdown_syntax(self):
        text = "[$x$](u) and *$y$*"
        spans, _ = mathrender.find_math(text)
        out = mathrender.splice(text, spans, ["<X>", "<Y>"])
        self.assertEqual(out, "[<X>](u) and *<Y>*")

    def test_inert(self):
        markup = '<span class="a" aria-label="|x|"><span>a_b*c</span><span>&amp;&#x27;</span></span>'
        out = mathrender.inert(markup)
        self.assertEqual(out, '<span class="a" aria-label="&#124;x&#124;"><span>a&#95;b&#42;c</span>'
                              '<span>&amp;&#x27;</span></span>')

    def test_fallback(self):
        self.assertEqual(mathrender.fallback_html(r"\frac{1}{", False),
                         '<code class="katex-fallback">&#92;frac&#123;1&#125;&#123;</code>')
        self.assertIn('data-display="true"', mathrender.fallback_html("x", True))


@unittest.skipUnless(HAVE_KATEX, "node and the katex package are required")
class RenderFilesTest(unittest.TestCase):
    def test_render_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "a.md"
            md.write_text("A $x^2$ and $\\frac{1}{$.\n\n$$\n\\sum_k k\n$$\n\n| c | $\\|v\\|$ |\n", encoding="utf-8")
            report = mathrender.render_files([md], where=lambda p: p.name)
            out = md.read_text(encoding="utf-8")
        self.assertEqual((report.formulas, report.failures), (4, 1))
        self.assertTrue(any("a.md:1: KaTeX cannot render" in w for w in report.warnings), report.warnings)
        self.assertIn('class="katex-fallback"', out)
        self.assertIn('<div class="tr-math"><span class="katex-display">', out)
        self.assertIn('role="math" aria-label="x^2"', out)
        self.assertEqual(out.count("\n"), 7)  # every formula stays on one line
        row = out.splitlines()[-1]
        self.assertEqual(row.count("|"), 3, row)  # no raw pipe from the formula splits the table
        self.assertIn('aria-label="\\&#124;v\\&#124;"', row)  # the norm, as in the PDF and EPUB
        self.assertIn("∥", row)


# --------------------------------------------------------------------------- staging


def write_book(root: Path) -> Path:
    """A one-edition book with parts, nesting, a draft, a suffix chapter and assets."""
    book = root / "demo-book"
    (book / "zh" / "img").mkdir(parents=True)
    (book / "zh" / "part").mkdir()
    (book / "assets").mkdir()
    (book / "book.toml").write_text(textwrap.dedent("""\
        [book]
        version = "0.2.0"
        authors = ["A", "B"]
        editions = ["zh"]
        code = "DEMO//BOOK"
        [book.title]
        zh = "演示之书"
        [book.description]
        zh = "测试"
    """), encoding="utf-8")
    (book / "assets" / "fig.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (book / "zh" / "img" / "local.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (book / "zh" / ".hidden").write_text("x", encoding="utf-8")
    (book / "zh" / "SUMMARY.md").write_text(textwrap.dedent("""\
        # Summary

        [引言](README.md)

        # 第一部分

        - [第一章 甲](a.md)
          - [第一节 \\[括号\\]](part/sec.md)

        # 第二部分

        - [第二章 乙](b.md)
        - [草稿]()

        [附录](appendix.md)
    """), encoding="utf-8")
    (book / "zh" / "README.md").write_text("# 引言\n\n![图](../assets/fig.svg) ![本地](img/local.svg)\n", encoding="utf-8")
    (book / "zh" / "a.md").write_text(textwrap.dedent("""\
        # 第一章 甲

        ::: {.theorem #thm-a title="界 $v_1 < v_2$" lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
        设 $x > 0$。
        :::

        见 [@thm-b]。
    """), encoding="utf-8")
    (book / "zh" / "part" / "sec.md").write_text("# 第一节\n\n回到 [@thm-a]。![共享](../../assets/fig.svg)\n",
                                                  encoding="utf-8")
    (book / "zh" / "b.md").write_text(textwrap.dedent("""\
        # 第二章 乙

        ::: {.proposition #thm-b lean="D5/S1/Deficit/DeficitInteger.deficit_integer"}
        内容。
        :::

        ::: {.problem #prob-c title="开放"}
        未证。
        :::
    """), encoding="utf-8")
    (book / "zh" / "appendix.md").write_text("# 附录\n\n正文。\n", encoding="utf-8")
    return book


class SummaryTest(unittest.TestCase):
    def test_regenerated_summary_keeps_structure_and_appends_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = config.load_book(write_book(Path(tmp)))
            model = load_edition(book.editions[0])
            staged = {c.path for c in model.summary.chapters if c.path}
            text = html.summary_markdown(model, staged, "形式化验证账本")
            out = Path(tmp) / "SUMMARY.md"
            out.write_text(text, encoding="utf-8")
            again = parse_summary(out)
        orig = [(c.title, c.path, c.section, c.depth, c.part, c.number) for c in model.summary.chapters]
        new = [(c.title, c.path, c.section, c.depth, c.part, c.number) for c in again.chapters]
        self.assertEqual(new[:-1], orig)
        self.assertEqual(new[-1], ("形式化验证账本", ledger.LEDGER_FILE, "suffix", 0, "第二部分", ()))
        self.assertIn("  - [第一节 \\[括号\\]](part/sec.md)", text)
        self.assertIn("- [草稿]()", text)

    def test_missing_chapter_becomes_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = config.load_book(write_book(Path(tmp)))
            model = load_edition(book.editions[0])
            text = html.summary_markdown(model, {"README.md", "a.md", "part/sec.md", "appendix.md"}, "L")
        self.assertIn("- [第二章 乙]()", text)


@unittest.skipUnless(EXAMPLE.is_dir(), "books/example-monograph was removed")
class BookTomlTest(unittest.TestCase):
    def setUp(self):
        self.site = config.load_site()
        self.book = config.load_book("example-monograph")
        self.edition = self.book.edition("zh")

    def test_fields(self):
        site = dataclasses.replace(self.site, repo="owner/name", base_url="https://owner.github.io/name/")
        data = tomllib.loads(html.book_toml(site, self.book, self.edition, ["tr/a.css"], ["tr/b.js"]))
        self.assertEqual(data["book"]["title"], self.edition.title)
        self.assertEqual(data["book"]["language"], "zh-CN")
        self.assertEqual(data["book"]["src"], "src")
        out = data["output"]["html"]
        self.assertEqual(out["default-theme"], "navy")
        self.assertEqual(out["preferred-dark-theme"], "navy")
        self.assertEqual(out["site-url"], "/name/example-monograph/zh/")
        self.assertEqual(out["git-repository-url"], "https://github.com/owner/name")
        self.assertEqual(out["edit-url-template"],
                         "https://github.com/owner/name/edit/main/books/example-monograph/zh/{path}")
        self.assertEqual(out["additional-css"], ["tr/a.css"])
        self.assertTrue(out["print"]["enable"] and out["search"]["enable"])
        self.assertEqual(out["fold"], {"enable": True, "level": 1})

    def test_without_repository(self):
        site = dataclasses.replace(self.site, repo="", base_url="")
        out = tomllib.loads(html.book_toml(site, self.book, self.edition, [], []))["output"]["html"]
        self.assertEqual(out["site-url"], "/example-monograph/zh/")
        self.assertNotIn("git-repository-url", out)
        self.assertNotIn("edit-url-template", out)


class EditLinkTest(unittest.TestCase):
    PREFIX = "https://github.com/o/r/edit/main/books/b/zh/"

    @staticmethod
    def page(path: str) -> str:
        # The menu-bar markup of mdBook 0.5.4, whose {path} is "<src>/<chapter>.md".
        return (f'<div class="right-buttons"><a href="https://github.com/o/r" title="Git repository">G</a>\n'
                f'<a href="{EditLinkTest.PREFIX}src/{path}" title="Suggest an edit" aria-label="Suggest an edit" '
                f'rel="edit">\n<span class=fa-svg id="git-edit-button"><svg></svg></span>\n</a>\n</div>')

    def test_src_dropped_and_generated_pages_lose_the_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "part").mkdir()
            (out / "ch01.html").write_text(self.page("ch01.md"), encoding="utf-8")
            (out / "part" / "sub.html").write_text(self.page("part/sub.md"), encoding="utf-8")
            (out / "verification-ledger.html").write_text(self.page(ledger.LEDGER_FILE), encoding="utf-8")
            (out / "toc.html").write_text("<p>no menu</p>", encoding="utf-8")
            self.assertEqual(html.fix_edit_links(out, self.PREFIX, {ledger.LEDGER_FILE}), 3)
            ch01 = (out / "ch01.html").read_text(encoding="utf-8")
            sub = (out / "part" / "sub.html").read_text(encoding="utf-8")
            led = (out / "verification-ledger.html").read_text(encoding="utf-8")
        self.assertIn(f'href="{self.PREFIX}ch01.md"', ch01)
        self.assertIn(f'href="{self.PREFIX}part/sub.md"', sub)
        self.assertNotIn("/src/", ch01 + sub + led)
        self.assertNotIn('rel="edit"', led)
        self.assertIn('title="Git repository"', led)
        self.assertEqual(html.fix_edit_links(Path(tmp), "", set()), 0)

    def test_prefix(self):
        site = dataclasses.replace(config.load_site(), repo="o/r")
        with tempfile.TemporaryDirectory() as tmp:  # outside the repository: no edit link
            outside = config.load_book(write_book(Path(tmp))).editions[0]
            self.assertEqual(html.edit_url_prefix(site, outside), "")
        if EXAMPLE.is_dir():
            ed = config.load_book("example-monograph").edition("zh")
            self.assertEqual(html.edit_url_prefix(site, ed), "https://github.com/o/r/edit/main/books/example-monograph/zh/")
            self.assertEqual(html.edit_url_prefix(dataclasses.replace(site, repo=""), ed), "")


class ThemeTest(unittest.TestCase):
    def test_paper_palette_is_copied_from_tokens(self):
        css = html.paper_palette_css()
        tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
        self.assertIn("html.light, html.rust {", css)
        self.assertIn("@media print", css)
        for key, value in tokens["paper"].items():
            self.assertIn(f"--tr-{key}: {value};", css)

    def test_theme_sources_restate_no_colour(self):
        for name in ("tr-book.css", "tr-book.js"):
            text = (html.MDBOOK_THEME / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b(?![-\w])|rgba?\(", text), name)

    def test_ui_strings(self):
        self.assertEqual(html.ui("zh", "book_home"), "本书主页")
        self.assertEqual(html.ui("en", "book_home"), "Book home")
        self.assertEqual(html.ui("fr", "book_home"), "Book home")
        self.assertEqual(set(html.LOCAL_I18N["zh"]), set(html.LOCAL_I18N["en"]))


@unittest.skipUnless(HAVE_KATEX, "node and the katex package are required")
class StageTest(unittest.TestCase):
    def test_stage_edition(self):
        site = config.load_site()
        with tempfile.TemporaryDirectory() as tmp:
            book = config.load_book(write_book(Path(tmp)))
            ed = book.editions[0]
            model = load_edition(ed)
            stage = html.stage_edition(site, book, ed, model, STAGE_LOCK, root=Path(tmp) / "stage")
            src = stage.src
            for rel in ("SUMMARY.md", "README.md", "a.md", "part/sec.md", "b.md", "appendix.md",
                        ledger.LEDGER_FILE, "404.md", "img/local.svg", "_book/assets/fig.svg"):
                self.assertTrue((src / rel).is_file(), rel)
            self.assertFalse((src / ".hidden").exists())
            self.assertTrue(list((src / "tr" / "katex" / "fonts").glob("KaTeX_Main-Regular.woff2")))
            for rel in ("tr/tokens.css", "tr/tr-palette.css", "tr/tr-book.css", "tr/tr-book.js",
                        "tr/tr-editions.js", "tr/katex/katex.min.css", "theme/head.hbs", "theme/favicon.svg"):
                self.assertTrue((stage.root / rel).is_file(), rel)
            tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
            head = (stage.root / "theme" / "head.hbs").read_text(encoding="utf-8")
            self.assertIn(tokens["font"]["google-fonts-css"], head)
            self.assertNotIn("@@", head + (stage.root / "theme" / "favicon.svg").read_text(encoding="utf-8"))
            katex_css = (stage.root / "tr" / "katex" / "katex.min.css").read_text(encoding="utf-8")
            self.assertNotIn(".ttf", katex_css)
            conf = tomllib.loads((stage.root / "book.toml").read_text(encoding="utf-8"))
            self.assertIn("tr/katex/katex.min.css", conf["output"]["html"]["additional-css"])
            self.assertEqual(conf["output"]["html"]["additional-js"], ["tr/tr-editions.js", "tr/tr-book.js"])
            data = json.loads((stage.root / "tr" / "tr-editions.js").read_text(encoding="utf-8")
                              .split("=", 1)[1].rstrip().rstrip(";"))
            self.assertEqual((data["current"], data["landing"], data["verified"]), ("zh", "../", 2))
            self.assertEqual(data["langs"][0]["code"], "zh")
            a = (src / "a.md").read_text(encoding="utf-8")
            self.assertNotIn("$", a)
            self.assertIn("(b.md#thm-b)", a)
            self.assertIn('aria-label="v_1 &lt; v_2"', a)  # title math decoded, rendered, re-escaped
            sec = (src / "part" / "sec.md").read_text(encoding="utf-8")
            self.assertIn("(../a.md#thm-a)", sec)
            self.assertIn("(../_book/assets/fig.svg)", sec)
            led = (src / ledger.LEDGER_FILE).read_text(encoding="utf-8")
            self.assertIn("(a.md#thm-a)", led)
            self.assertIn("(b.md#prob-c)", led)
            self.assertEqual(stage.warnings, [])


# --------------------------------------------------------------------------- search


class SearchIndexTest(unittest.TestCase):
    def test_cjk_grams(self):
        self.assertEqual(html.cjk_grams("归一化 x-亏"), ["归", "一", "化", "归一", "一化", "亏"])
        self.assertEqual(html.cjk_grams("plain words"), [])

    def test_augment(self):
        index = {
            "results_options": {}, "search_options": {}, "doc_urls": ["a.html#x"],
            "index": {
                "fields": ["title", "body", "breadcrumbs"], "pipeline": ["trimmer"], "ref": "id",
                "version": "0.9.5", "lang": "English",
                "index": {f: {"root": {"docs": {}, "df": 0}} for f in ("title", "body", "breadcrumbs")},
                "documentStore": {"save": True, "docs": {"0": {"id": "0", "title": "章", "body": "亏量 It's 亏量", "breadcrumbs": ""}},
                                  "docInfo": {"0": {"title": 1, "body": 2, "breadcrumbs": 0}}, "length": 1},
            },
        }
        raw = json.dumps(index, ensure_ascii=False)
        js = "window.search = Object.assign(window.search, JSON.parse('" + raw.replace("\\", "\\\\").replace("'", "\\'") + "'));"
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "searchindex-abc.js"
            p.write_text(js, encoding="utf-8")
            self.assertGreater(html.augment_search(Path(tmp)), 0)
            text = p.read_text(encoding="utf-8")
        m = html._SEARCHINDEX_RE.match(text)
        data = json.loads(re.sub(r"\\([\\'])", r"\1", m.group("json")))
        body = data["index"]["index"]["body"]["root"]
        self.assertEqual(body["亏"]["量"]["docs"]["0"]["tf"], 2 ** 0.5)
        self.assertEqual(body["亏"]["量"]["df"], 1)
        self.assertEqual(body["量"]["docs"]["0"]["tf"], 2 ** 0.5)
        self.assertEqual(data["index"]["documentStore"]["docInfo"]["0"]["body"], 2 + 6)
        self.assertEqual(data["index"]["documentStore"]["docs"]["0"]["body"], "亏量 It's 亏量")

    def test_unexpected_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "searchindex.js"
            p.write_text("var x = 1;", encoding="utf-8")
            with self.assertRaises(html.HtmlError):
                html.augment_search_index(p)


# --------------------------------------------------------------------------- end to end


class CjkEmphasisTest(unittest.TestCase):
    def test_literal_regions_are_unchanged(self):
        for text in (
            r"`中文**（code）**后文`", r"中文\*\*（literal）\*\*后文",
            "```markdown\n中文**（code）**后文\n```",
            "> ```\n> 中文**（code）**后文\n> ```",
            "    中文**（code）**后文",
            "<!-- 中文**（comment）**后文 -->",
            '<span title="中文**（attribute）**后文">text</span>',
            "<div>\n中文**（raw HTML）**后文\n</div>",
            "[link](https://example.org/中文**（url）**后文)",
            r"$\text{中文**（formula）**后文}$",
        ):
            with self.subTest(text=text):
                self.assertEqual(html.cjk_emphasis(text), text)

    @unittest.skipUnless(HAVE_KATEX and MDBOOK, "node, katex and mdBook are required")
    def test_punctuation_math_and_nested_emphasis_render_as_strong(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bdir = write_book(root)
            text = (
                "# CJK emphasis\n\n"
                "这是**术语（term）**的说明。\n\n"
                "也是**“正交一次、正交两次”**两步。\n\n"
                "这里**《书名》**接汉字。\n\n"
                "这是**含 *斜体* 的（术语）**后文。\n\n"
                "这是**$x^2$**后文。\n\n"
                "**普通加粗**；*斜体*；***加粗斜体***；English **bold (term)** text.\n\n"
                "> 这是**「引用」**后文。\n\n"
                "| 名称 |\n| --- |\n| 这是**【表格】**后文 |\n"
            )
            self.assertEqual(html.cjk_emphasis(html.cjk_emphasis(text)), html.cjk_emphasis(text))
            (bdir / "zh" / "a.md").write_text(text, encoding="utf-8")
            book = config.load_book(bdir)
            out = root / "out"
            html.build_edition(config.load_site(), book, book.editions[0], None, STAGE_LOCK, out)
            for name in ("a.html", "print.html"):
                page = (out / name).read_text(encoding="utf-8")
                page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
                self.assertIn("<strong>术语（term）</strong>", page)
                self.assertIn("<strong>“正交一次、正交两次”</strong>", page)
                self.assertIn("<strong>《书名》</strong>", page)
                self.assertIn("<strong>含 <em>斜体</em> 的（术语）</strong>", page)
                self.assertRegex(page, r'<strong><span class="katex".*?</span></strong>')
                self.assertIn("<strong>「引用」</strong>", page)
                self.assertIn("<strong>【表格】</strong>", page)
                self.assertIn("<strong>普通加粗</strong>", page)
                self.assertIn("<em>斜体</em>", page)
                self.assertIn("<em><strong>加粗斜体</strong></em>", page)
                self.assertIn("<strong>bold (term)</strong>", page)
                self.assertNotIn("**", page.split("<main>", 1)[1].split("</main>", 1)[0])


@unittest.skipUnless(HAVE_KATEX and MDBOOK, "node, katex and mdBook are required")
class BuildTitleMathTest(unittest.TestCase):
    def test_titles_in_both_tocs_metadata_and_nested_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bdir = write_book(root)
            conf = bdir / "book.toml"
            conf.write_text(conf.read_text(encoding="utf-8").replace('editions = ["zh"]', 'editions = ["zh", "en"]')
                            .replace('zh = "演示之书"', 'zh = "演示 $x_1^2$"\nen = "Demo $x_1^2$"'), encoding="utf-8")
            shutil.copytree(bdir / "zh", bdir / "en")
            for lang, prefix in (("zh", "界"), ("en", "Bound")):
                ed_dir = bdir / lang
                (ed_dir / "SUMMARY.md").write_text(
                    "# Summary\n\n[Intro](README.md)\n\n# Part $\\varphi$\n\n"
                    f"- [{prefix} $\\beta_1 < \\beta_2$](a.md)\n"
                    "  - [C\\*-algebras $\\norm{x}$](part/sec.md)\n"
                    "- [Literal \\$x\\$ and `$y$`](b.md)\n"
                    "- [Draft $\\{x\\}$]()\n\n"
                    "- [Bad $\\frac{1}{$]()\n\n"
                    "[Appendix $x'$](appendix.md)\n", encoding="utf-8")
                (ed_dir / "a.md").write_text(f"# {prefix} $\\beta_1 < \\beta_2$\n", encoding="utf-8")
                (ed_dir / "part" / "sec.md").write_text("# C*-algebras $\\norm{x}$\n", encoding="utf-8")
            book = config.load_book(bdir)
            book.raw["html"] = {"section-labels": True}
            for ed in book.editions:
                with self.subTest(lang=ed.lang):
                    out = root / "out" / ed.lang
                    html.build_edition(config.load_site(), book, ed, None, STAGE_LOCK, out)
                    toc = (out / "toc.html").read_text(encoding="utf-8")
                    self.assertEqual(toc.count('role="math"'), 5)  # part, two chapters, draft, appendix
                    self.assertIn('aria-label="\\varphi"', toc)
                    self.assertIn('aria-label="\\beta_1 &lt; \\beta_2"', toc)
                    self.assertIn('aria-label="\\norm{x}"', toc)
                    self.assertIn('class="msupsub"', toc)  # subscripts retain their layout
                    self.assertIn('Literal $x$ and `$y$`', toc)
                    self.assertIn('class="katex-fallback"', toc)
                    self.assertIn('<strong aria-hidden="true">1.</strong>', toc)
                    script = next(out.glob("toc-*.js"))
                    js = script.read_text(encoding="utf-8")
                    self.assertEqual(js.count('role="math"'), 5)
                    self.assertIn('aria-label="\\\\norm{x}"', js)  # JS string escaping
                    self.assertEqual(script.stem, "toc-" + hashlib.sha256(js.encode()).hexdigest()[:8])
                    # Parse the actual script; a prime or backslash must not break it.
                    subprocess.run([NODE, "--check", str(script)], check=True, capture_output=True)
                    for rel in ("index.html", "a.html", "part/sec.html", "print.html"):
                        page = (out / rel).read_text(encoding="utf-8")
                        self.assertIn(script.name, page)
                        self.assertRegex(page, r'<h1 class="menu-title">(?:演示|Demo) <span class="katex"')
                        title = re.search(r"<title>(.*?)</title>", page)[1]
                        self.assertNotIn("$", title)
                        self.assertNotIn("<span", title)
                    self.assertIn('id="' + ("界" if ed.lang == "zh" else "bound") + '-β1β2"',
                                  (out / "a.html").read_text(encoding="utf-8"))
                    search = next(out.glob("searchindex*.js")).read_text(encoding="utf-8")
                    self.assertNotIn(r"\\beta", search)


@unittest.skipUnless(HAVE_KATEX and MDBOOK, "node, katex and mdBook are required")
@unittest.skipUnless(EXAMPLE.is_dir(), "books/example-monograph was removed")
@unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden")
class BuildExampleTest(unittest.TestCase):
    """Build both editions of books/example-monograph and check the published pages."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "html"
        site = config.load_site()
        cls.book = config.load_book("example-monograph")
        for ed in cls.book.editions:
            html.build_edition(site, cls.book, ed, None, LOCK, cls.out / ed.lang)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def pages(self, lang):
        return sorted(p for p in (self.out / lang).rglob("*.html") if p.name not in ("toc.html",))

    def main(self, page: Path) -> str:
        text = page.read_text(encoding="utf-8")
        return text.split("<main>", 1)[1].split("</main>", 1)[0] if "<main>" in text else ""

    def test_theorems_have_lean_badges_at_the_pinned_commit(self):
        prefix = f"https://github.com/{LOCK.repo}/blob/{LOCK.commit}/"
        for ed in self.book.editions:
            model = load_edition(ed)
            formal = {e.id for e in model.formal_envs()}
            seen = set()
            for page in self.pages(ed.lang):
                if page.name == "print.html":
                    continue
                for m in re.finditer(r'<section class="tr-env [^"]*tr-status-lean" id="([^"]+)"[^>]*>\s*'
                                     r'<header class="tr-env-head">.*?<a class="tr-badge tr-badge-lean" href="([^"]+)"',
                                     self.main(page), re.S):
                    seen.add(m.group(1))
                    self.assertTrue(m.group(2).startswith(prefix), m.group(2))
                    self.assertRegex(m.group(2), r"\.lean#L\d+$")
            self.assertEqual(seen, formal)

    def test_no_raw_math_left(self):
        for lang in ("zh", "en"):
            for page in self.pages(lang):
                body = re.sub(r"<code[^>]*>.*?</code>", "", self.main(page), flags=re.S)
                body = re.sub(r"<[^>]+>", "", body)
                self.assertNotIn("$", body, page)

    def test_internal_links_resolve(self):
        for lang in ("zh", "en"):
            root = self.out / lang
            for page in self.pages(lang):
                main = self.main(page)
                for href in re.findall(r'href="([^"#:]*\.html)(?:#([^"]*))?"', main):
                    target = (page.parent / href[0]).resolve()
                    self.assertTrue(target.is_file(), f"{page.name} → {href[0]}")
                    if href[1]:
                        self.assertIn(f'id="{href[1]}"', target.read_text(encoding="utf-8"), f"{page.name} → {href}")
            self.assertTrue((root / "verification-ledger.html").is_file())
            self.assertTrue((root / "print.html").is_file())
            self.assertTrue(list(root.glob("searchindex*.js")))

    def test_language_switch_targets_exist(self):
        for lang in ("zh", "en"):
            js = next((self.out / lang / "tr").glob("tr-editions*.js")).read_text(encoding="utf-8")
            data = json.loads(js.split("=", 1)[1].rstrip().rstrip(";"))
            self.assertEqual(data["current"], lang)
            others = [l["code"] for l in data["langs"] if l["code"] != lang]
            self.assertEqual(others, [o for o in ("zh", "en") if o != lang])
            for page in self.pages(lang):
                rel = page.relative_to(self.out / lang)
                for other in others:
                    self.assertTrue((self.out / other / rel).is_file(), f"{other}/{rel}")

    def test_cjk_search_tokens(self):
        js = next((self.out / "zh").glob("searchindex*.js")).read_text(encoding="utf-8")
        self.assertIn('"亏":{', js)
        self.assertIn('"量":{"docs":{', js)

    def test_edit_links_name_existing_source_files(self):
        site = config.load_site()
        seen = 0
        for lang in ("zh", "en"):
            for page in self.pages(lang):
                for href in re.findall(r'<a href="([^"]+)"[^>]*rel="edit"', page.read_text(encoding="utf-8")):
                    m = re.match(rf"https://github\.com/{re.escape(site.repo)}/edit/[^/]+/(.+)$", href)
                    self.assertIsNotNone(m, href)
                    self.assertTrue((paths.ROOT / m.group(1)).is_file(), f"{page.name} → {href}")
                    seen += 1
            ledger_page = (self.out / lang / "verification-ledger.html").read_text(encoding="utf-8")
            self.assertNotIn('rel="edit"', ledger_page)  # generated: no source to edit
        if site.repo:
            self.assertGreater(seen, 0)


if __name__ == "__main__":
    unittest.main()
