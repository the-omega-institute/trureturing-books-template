"""One block model for every target: :func:`tbook.mdscan.scan_blocks`.

Which lines are code (fenced or indented, in any container: block quote, list item, footnote or
definition body), HTML comment blocks, or inside an inline comment that spans lines is decided once,
by the CommonMark block rules that mdBook and Pandoc share. :func:`tbook.mdscan.parse_blocks` (and
so check, the model and both render targets), the PDF/EPUB stager (:func:`tbook.pandoc._code_mask`)
and the math scanner (:func:`tbook.mathrender.find_math`) all read it, so nothing inside code or a
comment is rewritten, checked or typeset as math by one of them and not by the others. A formula
over lines is one paragraph (no block starts inside it). Where mdBook and Pandoc read a text
differently (fences that end without their closing fence, definition terms, comments in table
cells), the model follows one of them and parse_blocks warns; RenderersAgreeTest checks both.

Run: PYTHONPATH=tools:tools/tests .venv/bin/python -m unittest test_blocks
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from tbook import check, config, mathrender, mdscan, model
from tbook import pandoc as tp
from test_followups_pandoc import MDBOOK, fixture_site, math_hidden_lines, stage_chapters, write_book
from test_markdown import GID_OK, Repo, write
from test_pandoc import HAVE_KATEX, PINNED_PANDOC, have_pandoc, have_pinned_pandoc


def parse_hidden(text: str) -> list[bool]:
    """The lines parse_blocks keeps away from rewriting and checking: code and comment nodes, and
    text lines wholly inside an inline comment that spans lines."""
    lines = text.split("\n")
    hidden = [False] * len(lines)
    for node in mdscan.walk(mdscan.parse_blocks(text)):
        if isinstance(node, mdscan.Code):
            hidden[node.start - 1:node.start - 1 + len(node.lines)] = [True] * len(node.lines)
        elif isinstance(node, mdscan.Text):
            for k, (line, (lead, _)) in enumerate(zip(node.lines, node.carry)):
                hidden[node.start - 1 + k] = lead and "-->" not in line
    return hidden


# A varied corpus: code and comments in every container, and the text around them.
CORPUS = {
    "top-level indented code": "段落 $a$\n\n    代码 $x$ [@t]\n\n    仍是代码 [一](ch02.md)\n\n正文 $b$\n",
    "paragraph continuation is text": "文字 $a$\n    续行 $b$ [@t]\n",
    "comment opener in indented code": "示例：\n\n    <!-- 待补 $x$\n\n之后 [@t] $a$。\n\n::: {.theorem #t}\n内容。\n:::\n",
    "list item code": "1. 运行：\n\n       echo $HOME/$USER\n       见[一](ch02.md)与[^n]\n\n正文 $a$[^n]。\n\n[^n]: 脚注。\n",
    "list item paragraph": "- 项 $a$\n\n    项的续段 $b$ [@t]\n\n结束\n",
    "nested list code": "- 甲\n  - 乙\n\n        乙的代码 $x$\n\n  甲的续段 $a$\n",
    "definition paragraph": "黄金比\n\n:   满足 $a$ 的正数。\n\n    它的倒数是 $b$，见[第二章](ch02.md)。\n\n        定义里的代码 $x$\n",
    "footnote body": "正文[^n]。\n\n[^n]: 注 $a$\n\n    注的第二段 $b$\n\n        注里的代码 $x$\n",
    "block quote code": "> 引文 $a$\n>\n>     引文里的代码 $x$\n",
    "quote in item": "- 项\n\n  > 引 $a$\n  >\n  >     代码 $x$\n",
    "fences in containers": "> ```\n> $x$\n> ```\n\n- 项\n\n  ```\n  $y$ [@t]\n  ```\n\n正文 $a$\n",
    "comment block": "正文 $a$\n\n<!--\n![图](fig.svg) $x$\n\n[@t]\n-->\n后文 $b$\n",
    "inline comment over lines": "正文 <!-- 待补 $x$\n![图 5](fig5.svg) [@t]\n还在注释里 $y$ --> 可见 $a$\n",
    "inline comment never closed": "段落 <!-- 未闭合 $a$\n下一行 $b$\n\n再下一段 $c$\n",
    "inline comment in list item": "- 项 <!-- 跨行 $x$\n  续行 --> 可见 $a$\n- 新项 $b$\n",
    "code span opener": "`<!--` 不是注释 $a$\n下一行 $b$ -->\n",
    "div with code": "::: {.theorem #t}\n陈述 $a$。\n\n    代码 $x$\n:::\n\n后文 $b$\n",
    "display math over a list marker": "竖式：\n\n$$\n\\begin{array}{r}\n  1234567 \\\\\n+      89 \\\\\n\\hline\n"
                                       "\\end{array}\n$$\n\n    代码 $x$\n",
    "display math over a setext line": "求和：\n\n$$\n\\sum_{k=1}^n k\n=\n    \\frac{n(n+1)}{2}\n$$\n",
    "colon line after code": "命令：\n\n    lake build\n\n:   冒号开头。\n\n    echo $x/$y [二](ch02.md)\n",
    "comment open in a table cell": "| 项 | 说明 |\n| --- | --- |\n| 一 | 待定 <!-- 稍后补 |\n| 二 | 见 [@t] $a$ |\n"
                                    "| 三 | 完成 --> 了 |\n",
}


class ScannersAgreeTest(unittest.TestCase):
    """parse_blocks, the Pandoc stager's mask and the math scanner hide the same lines."""

    def test_same_hidden_lines(self):
        for name, text in CORPUS.items():
            lines = text.split("\n")
            want = parse_hidden(text)
            with self.subTest(name):
                self.assertEqual(tp._code_mask(lines), want)
                self.assertEqual(mdscan.scan_blocks(lines).hidden, want)
                math = math_hidden_lines(text)
                self.assertEqual([h for h, line in zip(math, lines) if line.strip()],
                                 [h for h, line in zip(want, lines) if line.strip()])

    def test_corpus_math(self):
        """Formulas in code and comments ($x$, $y$ in the corpus) are not math; the others are."""
        for name, text in CORPUS.items():
            with self.subTest(name):
                found = [s.tex for s in mathrender.find_math(text)[0]]
                self.assertNotIn("x", found)
                self.assertNotIn("y", found)
        self.assertEqual([s.tex for s in mathrender.find_math(CORPUS["definition paragraph"])[0]], ["a", "b"])
        self.assertEqual([s.tex for s in mathrender.find_math(CORPUS["inline comment over lines"])[0]], ["a"])
        self.assertEqual([s.tex for s in mathrender.find_math(CORPUS["inline comment never closed"])[0]],
                         ["a", "b", "c"])
        # A display formula over lines is one paragraph: "+      89" in it starts no list item and no
        # code, "=" no setext heading.
        for name in ("display math over a list marker", "display math over a setext line"):
            with self.subTest(name):
                spans, notes = mathrender.find_math(CORPUS[name])
                self.assertEqual([(s.display, s.block, s.line) for s in spans], [(True, True, 3)])
                self.assertEqual(notes, [])
        self.assertEqual(mathrender.find_math(CORPUS["colon line after code"])[0], [])
        self.assertEqual([s.tex for s in mathrender.find_math(CORPUS["comment open in a table cell"])[0]], ["a"])


# --------------------------------------------------------------------------- finding 8: definition lists

DEFINITION = textwrap.dedent("""\
    # 第一章 甲

    黄金比

    :   满足 $\\varphi^2=\\varphi+1$ 的正数。

        它的倒数是 $\\varphi-1$，见[第二章](ch02.md)与脚注[^n]。

    [^n]: 脚注。
    """)


class DefinitionListTest(unittest.TestCase):
    """A definition's second paragraph (indented like its first line) is not indented code."""

    def test_not_code(self):
        lines = DEFINITION.split("\n")
        self.assertFalse(any(mdscan.indented_code_lines(lines)))
        self.assertFalse(any(tp._code_mask(lines)))
        self.assertEqual([s.tex for s in mathrender.find_math(DEFINITION)[0]],
                         ["\\varphi^2=\\varphi+1", "\\varphi-1"])
        for marker in (":", "~", "  :"):
            text = f"术语\n\n{marker} 定义\n\n  第二段\n\n      定义里的代码\n"
            with self.subTest(marker):
                self.assertEqual(mdscan.indented_code_lines(text.split("\n")),
                                 [False] * 6 + [True, False])

    def test_staged_links_and_footnotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            staged = stage_chapters(Path(tmp), {"ch01.md": DEFINITION, "ch02.md": "# 第二章 乙\n\n正文。\n"})
            md = staged.book_md.read_text(encoding="utf-8")
        self.assertIn("    它的倒数是 $\\varphi-1$，见[第二章](#ch-ch02)与脚注[^ch-ch01--n]。", md)
        self.assertEqual(staged.warnings, [])


# --------------------------------------------------------------------------- findings 3 and 5: indented code

INDENTED_COMMENT = textwrap.dedent(f"""\
    # 第一章

    ::: {{.theorem #thm-ok lean="{GID_OK}"}}
    陈述。
    :::

    HTML 注释以这样的一行开头：

        <!-- 待补

    之后的引用 [@thm-nonexistent] 与 [Lean](lean:Fake/Module.fake)。

    ::: {{.theorem #thm-extra title="补充" lean="Fake/Module.not_a_theorem"}}
    内容。
    :::
    """)

INDENTED_LINKS = textwrap.dedent(f"""\
    # 第一章

    ::: {{.theorem #thm-ok lean="{GID_OK}"}}
    陈述。
    :::

    引用的写法（缩进代码块）：

        见 [@thm-ok] 与 [名](lean:D5/X/Y.z)，图 ![图](../assets/nope.svg)，章 [一](README.md)。

    1. 列表项里的代码：

           见 [@thm-ok] 与 [名](lean:D5/X/Y.z)，图 ![图](../assets/nope.svg)，$HOME/$USER

    > 引文里的代码：
    >
    >     见 [@thm-ok] 与 ![图](../assets/nope.svg)

    正文 [@thm-ok]，[一](README.md)。
    """)
CODE_LINES = [line for line in INDENTED_LINKS.split("\n") if "[@thm-ok] 与" in line]


def checked(m: model.EditionModel) -> list[str]:
    """What ``./tbook check`` says about one edition's chapters (no lock needed)."""
    issues = list(m.issues)
    check.check_env_policy(m, issues)
    check.check_links(m, config.load_site(), issues)
    return [i.format() for i in issues]


class IndentedCodeCommentTest(unittest.TestCase):
    """Finding 3: ``    <!--`` in an indented code block is code, not the start of a comment block."""

    def test_scanner(self):
        issues: list[mdscan.ScanIssue] = []
        blocks = mdscan.parse_blocks(INDENTED_COMMENT, issues)
        self.assertEqual(issues, [])
        self.assertEqual([type(b).__name__ for b in blocks], ["Text", "Div", "Text", "Code", "Text", "Div", "Text"])
        self.assertEqual(blocks[3].lines, ["    <!-- 待补"])
        self.assertIn("thm-extra", [d.attrs.id for d in mdscan.walk(blocks) if isinstance(d, mdscan.Div)])
        lines = INDENTED_COMMENT.split("\n")
        self.assertEqual([line for line, h in zip(lines, tp._code_mask(lines)) if h], ["    <!-- 待补"])
        # Without a later comment there is no false "never closed" error either.
        issues.clear()
        mdscan.parse_blocks("示例：\n\n    <!-- 待补\n\n之后 [@x]。\n", issues)
        self.assertEqual(issues, [])

    def test_check_sees_what_follows(self):
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", INDENTED_COMMENT)
            m = model.load_edition(repo.edition)
            self.assertIn("thm-extra", m.envs)
            out = "\n".join(checked(m))
            self.assertIn("[@thm-nonexistent] refers to no environment", out)
            self.assertIn("'Fake/Module.fake'", out)
            self.assertIn("'Fake/Module.not_a_theorem'", out)
            self.assertNotIn("never closed", out)


class IndentedCodeVerbatimTest(unittest.TestCase):
    """Findings 5 and 9: links, references, images and math in indented code — top level, in a
    list item or a block quote — are neither rewritten nor checked, by every target."""

    def test_model_and_check_skip_code(self):
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", INDENTED_LINKS)
            m = model.load_edition(repo.edition)
            doc = next(d for d in m.chapters if d.chapter.path == "ch01.md")
            self.assertEqual([r for _, r in doc.refs], ["thm-ok"])
            self.assertEqual(doc.lean_links, [])
            self.assertEqual(checked(m), [])

    def test_render_leaves_code_alone(self):
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", INDENTED_LINKS)
            repo.model = model.load_edition(repo.edition)
            for target in ("mdbook", "pandoc"):
                with self.subTest(target):
                    out, ctx = repo.render("ch01.md", target)
                    for line in CODE_LINES:
                        self.assertIn("\n" + line + "\n", out)
                    self.assertNotIn("[@thm-ok]", out.replace(CODE_LINES[0], "").replace(CODE_LINES[1], "")
                                     .replace(CODE_LINES[2], ""))
                    self.assertEqual(ctx.issues, [])

    def test_math_and_staging_leave_code_alone(self):
        self.assertEqual(mathrender.find_math(INDENTED_LINKS)[0], [])
        with tempfile.TemporaryDirectory() as tmp:
            text = "# 第一章\n\n1. 运行：\n\n       见[一](ch02.md)与[^n]\n\n正文[^n]，[一](ch02.md)。\n\n[^n]: 脚注。\n"
            staged = stage_chapters(Path(tmp), {"ch01.md": text, "ch02.md": "# 第二章\n"})
            md = staged.book_md.read_text(encoding="utf-8")
        self.assertIn("\n       见[一](ch02.md)与[^n]\n", md)
        self.assertIn("正文[^ch-ch01--n]，[一](#ch-ch02)。", md)

    def test_containers(self):
        cases = {
            "list item, content column + 4": ("1. a\n\n       code\n", [False, False, True, False]),
            "list item paragraph": ("- a\n\n    para\n", [False, False, False, False]),
            "nested list": ("- a\n  - b\n\n        code\n", [False, False, False, True, False]),
            "code on the marker line": ("-     code\n", [True, False]),
            "block quote": ("> a\n>\n>     code\n", [False, False, True, False]),
            "quote in a list item": ("- a\n\n  > q\n  >\n  >     code\n", [False] * 4 + [True, False]),
            "footnote body": ("[^n]: a\n\n    para\n\n        code\n", [False] * 4 + [True, False]),
            "item ends at a blank line": ("- a\n\n  b\n\n    c\n\nd\n\n    code\n", [False] * 8 + [True, False]),
            "lazy line": ("- a\nlazy\n\n      code\n", [False] * 3 + [True, False]),
            "paragraph continuation": ("text\n    more\n", [False, False, False]),
            "blank lines inside the block": ("x\n\n    a\n\n    b\n", [False, False, True, True, True, False]),
        }
        for name, (text, want) in cases.items():
            with self.subTest(name):
                self.assertEqual(mdscan.indented_code_lines(text.split("\n")), want)


# --------------------------------------------------------------------------- finding 7: comments over lines

COMMENT_OVER_LINES = textwrap.dedent(f"""\
    # 第一章

    ::: {{.theorem #thm-ok lean="{GID_OK}"}}
    陈述。
    :::

    正文继续 <!-- TODO: 以后补图
    ![图 5](fig5.svg) 与 [@thm-todo3] $x$
    还没完 [名](lean:Fake/Module.fake) --> 见 [@thm-ok] 与 ![图](../assets/fig.svg)。
    """)


class CommentOverLinesTest(unittest.TestCase):
    """Finding 7: a ``<!--`` left open on a line goes on over the following lines of its
    paragraph up to ``-->``; if the paragraph ends first, it was text."""

    def test_carry(self):
        lines = COMMENT_OVER_LINES.split("\n")
        scan = mdscan.scan_blocks(lines)
        self.assertEqual(scan.carry[6:9], [(False, True), (True, True), (True, False)])
        self.assertEqual(scan.hidden[6:9], [False, True, False])
        self.assertEqual(mdscan.hidden_spans(lines[6], scan.carry[6]), [(5, len(lines[6]))])
        self.assertEqual(mdscan.hidden_spans(lines[8], scan.carry[8]), [(0, lines[8].index("-->") + 3)])
        text = [line for _, line in mdscan.iter_text_lines(mdscan.parse_blocks(COMMENT_OVER_LINES))]
        self.assertEqual([m.group("id") for line in text for m in mdscan.find_outside_code(mdscan.REF_RE, line)],
                         ["thm-ok"])
        self.assertEqual([s.tex for s in mathrender.find_math(COMMENT_OVER_LINES)[0]], [])

    def test_paragraph_end_makes_it_text(self):
        cases = {
            "blank line": "段落 <!-- 未闭合\n下一行 [@a]\n\n再下一段 [@b] -->\n",
            "new list item": "- 项 <!-- 不闭合\n- 新项 [@a] --> [@b]\n",
            "heading": "段落 <!-- 未闭合\n# 标题 [@a] -->\n[@b]\n",
            "fence": "段落 <!-- 未闭合\n```\n-->\n```\n[@a] [@b]\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                issues: list[mdscan.ScanIssue] = []
                blocks = mdscan.parse_blocks(text, issues)
                refs = [m.group("id") for _, line in mdscan.iter_text_lines(blocks)
                        for m in mdscan.find_outside_code(mdscan.REF_RE, line)]
                self.assertEqual(refs, ["a", "b"])
                lines = text.split("\n")
                self.assertEqual(tp._code_mask(lines), parse_hidden(text))
                # mdBook shows such a "<!--" as text; Pandoc hides everything up to the next "-->".
                self.assertEqual([(i.line, i.severity, "not closed in its paragraph" in i.message)
                                  for i in issues], [(1, "warning", True)])
        issues = []
        mdscan.parse_blocks("段落 <!-- 未闭合\n\n再下一段\n", issues)
        self.assertEqual(issues, [], "no later '-->': text in every target")

    def test_model_check_render_and_staging(self):
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", COMMENT_OVER_LINES)
            m = model.load_edition(repo.edition)
            doc = next(d for d in m.chapters if d.chapter.path == "ch01.md")
            self.assertEqual([r for _, r in doc.refs], ["thm-ok"])
            self.assertEqual(doc.lean_links, [])
            self.assertEqual(checked(m), [])
            repo.model = m
            for target in ("mdbook", "pandoc"):
                with self.subTest(target):
                    out, ctx = repo.render("ch01.md", target)
                    self.assertIn("正文继续 <!-- TODO: 以后补图\n![图 5](fig5.svg) 与 [@thm-todo3] $x$\n"
                                  "还没完 [名](lean:Fake/Module.fake) --> 见 [定理1.1](", out)
                    self.assertIn("与 ![图](_book/assets/fig.svg)。", out)
                    self.assertEqual(ctx.issues, [])
            with tempfile.TemporaryDirectory() as tmp:
                warnings: list[str] = []
                linker = tp._Linker(Path(tmp), repo.edition, {"ch01.md": "ch-ch01"}, warnings, set(), online="")
                md = "正文 <!-- 待补\n![图 5](fig5.svg) [二](ch02.md)\n还在 --> [一](ch01.md)\n"
                out = tp.restructure_chapter(md, chapter_path="ch01.md", depth=0, chapter_id="ch-ch01", title="一",
                                             classes=["tr-chapter"], kv={}, linker=linker)
                self.assertIn("正文 <!-- 待补\n![图 5](fig5.svg) [二](ch02.md)\n还在 --> [一](#ch-ch01)\n", out)
                self.assertEqual(warnings, [])
        scoped = tp.scope_footnotes("正文[^n] <!-- 待补[^n]\n仍在[^n] --> 之后[^n]\n\n[^n]: 注。\n", "ch-ch01")
        self.assertEqual(scoped, "正文[^ch-ch01--n] <!-- 待补[^n]\n仍在[^n] --> 之后[^ch-ch01--n]\n\n"
                                 "[^ch-ch01--n]: 注。\n")

    def test_map_closed(self):
        def upper(line: str) -> str:  # like every per-line rewrite: comments and code spans are left alone
            return mdscan.sub_outside_code(re.compile("[a-z]"), lambda m: m.group().upper(), line)

        self.assertEqual(mdscan.map_closed(upper, "a <!-- b", (False, True)), "A <!-- b")
        self.assertEqual(mdscan.map_closed(upper, "x --> x <!-- x", (True, True)), "x --> X <!-- x")
        self.assertEqual(mdscan.map_closed(upper, "x --> x `y`", (True, False)), "x --> X `y`")
        self.assertEqual(mdscan.map_closed(upper, "plain <!-- c -->", (False, False)), "PLAIN <!-- c -->")
        self.assertEqual(mdscan.close_comments("x --> y <!-- z", (True, True)), "<!--x --> y <!-- z-->")


# --------------------------------------------------------------------------- formulas over lines

MATH_OVER_ITEM = ("# 第一章 甲\n\n竖式加法：\n\n$$\n\\begin{array}{r}\n  1234567 \\\\\n+      89 \\\\\n\\hline\n"
                  "  1234656\n\\end{array}\n$$\n\n之后 $y$。\n")
MATH_OVER_SETEXT = "求和：\n\n$$\n\\sum_{k=1}^n k\n=\n    \\frac{n(n+1)}{2}\n$$\n"


class FormulaOverLinesTest(unittest.TestCase):
    """A display formula over lines is opaque to the block rules: "+      89 \\\\" in it is no list item
    with code, "=" no setext underline (Pandoc reads the formula first; the HTML edition renders it
    before mdBook runs)."""

    def test_scanner_and_math(self):
        spans, notes = mathrender.find_math(MATH_OVER_ITEM)
        self.assertEqual([(s.display, s.block, s.line) for s in spans], [(True, True, 5), (False, False, 14)])
        self.assertIn("+      89 \\\\", spans[0].tex)
        self.assertEqual(notes, [])
        spans, notes = mathrender.find_math(MATH_OVER_SETEXT)
        self.assertEqual([s.tex for s in spans], ["\\sum_{k=1}^n k\n=\n    \\frac{n(n+1)}{2}"])
        self.assertEqual(notes, [])
        for text in (MATH_OVER_ITEM, MATH_OVER_SETEXT):
            lines = text.split("\n")
            self.assertEqual(set(mdscan.scan_blocks(lines).kinds), {mdscan.TEXT, mdscan.BLANK})
            self.assertFalse(any(tp._code_mask(lines)))
            self.assertFalse(any(isinstance(b, mdscan.Code) for b in mdscan.walk(mdscan.parse_blocks(text))))

    def test_formula_must_close(self):
        """Lines after an opening $$ that a blank line, a code span or a comment keeps from closing are
        read as usual."""
        for text in ("$$ a\n+      b\n\n$$\n", "$$ a\n+      b `c`\n$$\n", "$$ a\n+      b <!-- c -->\n$$\n",
                     "$$ a\n+      b <span>\n$$\n", "a \\$$ b\n+      c\n$$\n", "[x](http://a.b/$c) d\n+      e$\n"):
            with self.subTest(text):
                self.assertEqual(mdscan.scan_blocks(text.split("\n")).kinds[1], mdscan.CODE)
                self.assertEqual(mathrender.find_math(text)[0], [])

    @unittest.skipUnless(HAVE_KATEX and MDBOOK and have_pandoc(), "node, katex, mdBook and pandoc are required")
    def test_html_and_pdf(self):
        from tbook import html

        slug = "tbook-test-blocks"
        self.addCleanup(shutil.rmtree, config.paths.BUILD / "stage" / slug, True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ed = write_book(root, {"ch01.md": MATH_OVER_ITEM}, slug)
            html.build_edition(fixture_site(), ed.book, ed, None, None, root / "html")
            page = (root / "html" / "ch01.html").read_text(encoding="utf-8")
            main = page[page.index("<main>"):page.index("</main>")]
            self.assertIn('<div class="tr-math"><span class="katex-display">', main)
            self.assertNotIn("<li>", main)
            self.assertNotIn("<pre>", main)
            self.assertNotIn("$$", main)
            md = stage_chapters(root / "pdf", {"ch01.md": MATH_OVER_ITEM}).book_md.read_text(encoding="utf-8")
            self.assertIn("$$\n\\begin{array}{r}\n  1234567 \\\\\n+      89 \\\\\n", md)


# --------------------------------------------------------------------------- the review findings, end to end

FENCE_CUT_BY_ITEM = textwrap.dedent("""\
    # 第一章 甲

    ::: {.definition #def-a}
    甲。
    :::

    1. 运行：

       ```bash
       lake build
      ```

    见 [@def-a]、[@def-nope] 与[前言](README.md)。

    ::: {.theorem #thm-b lean="Fake/Module.bad"}
    乙。
    :::
    """)
COLON_AFTER_CODE = "# 第一章 甲\n\n命令：\n\n    lake build\n\n:   这一行以冒号开头。\n\n    echo $HOME/$USER 见[二](ch02.md)\n"
TABLE_COMMENT = textwrap.dedent("""\
    # 第一章 甲

    ::: {.definition #def-a}
    甲。
    :::

    | 项 | 说明 |
    | --- | --- |
    | 一 | 待定 <!-- 稍后补 |
    | 二 | 见 [@def-a] 与 [前言](README.md) |
    | 三 | 完成 --> 了 |
    """)


class FindingsTest(unittest.TestCase):
    def test_fence_cut_by_its_item_is_reported(self):
        """mdBook ends the block at the under-indented fence (which opens a new block to the end of the
        chapter), Pandoc takes that fence as the closing one: check says so instead of going quiet."""
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", FENCE_CUT_BY_ITEM)
            out = checked(model.load_edition(repo.edition))
        self.assertEqual(len(out), 2, out)
        self.assertTrue(out[0].startswith("WARNING") and "ch01.md:11:" in out[0], out)
        self.assertIn("the fenced code block opened on line 9 ends at this line without a closing fence", out[0])
        self.assertTrue(out[1].startswith("WARNING") and "ch01.md:11:" in out[1], out)
        self.assertIn("fenced code block is never closed", out[1])
        issues: list[mdscan.ScanIssue] = []
        mdscan.parse_blocks(FENCE_CUT_BY_ITEM.replace("  ```\n\n见", "   ```\n\n见"), issues)
        self.assertEqual(issues, [], "a closing fence indented like the opening one")

    def test_list_right_after_a_paragraph_is_reported(self):
        """mdBook (CommonMark) lets a list interrupt a paragraph; Pandoc's Markdown needs a blank line
        before a top-level list and runs the items into the paragraph ("… - 甲 …") in the PDF/EPUB."""
        cases = {
            "bullet": ("段落：\n- 甲\n- 乙\n", [2]),
            "ordered from one": ("段落：\n1. 一\n2. 二\n", [2]),
            "after a display formula": ("$$\na\n$$\n- 甲\n", [4]),
            "ordered from three (no list for either)": ("段落：\n3. 三\n", []),
            "blank line before": ("段落：\n\n- 甲\n", []),
            "after a heading": ("# 标题\n- 甲\n", []),
            "after a div fence": ("::: {.remark}\n- 甲\n:::\n", []),
            "sublist in an item": ("1. 项\n   - 子\n", []),
            "sublist after an item's second line": ("- a\n  续\n  - b\n", []),
            "minus inside a display formula": ("段落\n\n$$\na\n- b\n$$\n", []),
            "empty item": ("段落\n-\n", []),
        }
        for name, (md, lines) in cases.items():
            with self.subTest(name):
                issues: list[mdscan.ScanIssue] = []
                mdscan.parse_blocks(md, issues)
                found = [i for i in issues if "a list starts right after a line of a paragraph" in i.message]
                self.assertEqual([i.line for i in found], lines)
                self.assertEqual({i.severity for i in found} or {"warning"}, {"warning"})
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", "# 一\n\n段落：\n- 甲\n")
            out = checked(model.load_edition(repo.edition))
        self.assertTrue(any(o.startswith("WARNING") and "ch01.md:4:" in o and "blank line before the list" in o
                            for o in out), out)

    def test_colon_line_after_code_is_no_definition(self):
        """":" after indented code (or a list item, a block quote) is a paragraph, so the 4-space line after
        it is code, as both renderers read it: no math, no link rewriting in it."""
        code = "    echo $HOME/$USER 见[二](ch02.md)"
        self.assertEqual(mdscan.indented_code_lines(COLON_AFTER_CODE.split("\n")),
                         [False] * 4 + [True] + [False] * 3 + [True, False])
        self.assertEqual(mathrender.find_math(COLON_AFTER_CODE)[0], [])
        for before in ("- 项", "> 引"):
            text = f"{before}\n\n:   定义?\n\n    第二段\n"
            with self.subTest(before):
                self.assertEqual(mdscan.indented_code_lines(text.split("\n")), [False] * 4 + [True, False])
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", COLON_AFTER_CODE)
            repo.model = model.load_edition(repo.edition)
            for target in ("mdbook", "pandoc"):
                with self.subTest(target):
                    out, ctx = repo.render("ch01.md", target)
                    self.assertIn("\n" + code + "\n", out)
        with tempfile.TemporaryDirectory() as tmp:
            staged = stage_chapters(Path(tmp), {"ch01.md": COLON_AFTER_CODE, "ch02.md": "# 第二章 乙\n"})
            self.assertIn("\n" + code + "\n", staged.book_md.read_text(encoding="utf-8"))

    def test_comment_left_open_in_a_table_cell(self):
        """Each table row is a paragraph for inline comments: mdBook shows the "<!--" of row 一 as text,
        so the references of the next rows are resolved and checked, and check warns that Pandoc
        hides those rows."""
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", TABLE_COMMENT)
            m = model.load_edition(repo.edition)
            doc = next(d for d in m.chapters if d.chapter.path == "ch01.md")
            self.assertEqual(doc.refs, [(10, "def-a")])
            out = checked(m)
            self.assertEqual(len(out), 1, out)
            self.assertIn("ch01.md:9: '<!--' (column 10) is not closed in its paragraph", out[0])
            repo.model = m
            out, ctx = repo.render("ch01.md", "mdbook")
            self.assertNotIn("[@def-a]", out)
            self.assertIn("| 一 | 待定 <!-- 稍后补 |", out)

    def test_unpaired_dollar_before_a_fence(self):
        """A '$' left unpaired right above a fenced code block that holds a '$' does not take the code into a
        formula (whose closing fence would open a code block to the end of the chapter): check reads what
        follows and names the '$', which Pandoc does pair over the fence."""
        lines = UNPAIRED_DOLLAR.split("\n")
        self.assertEqual(mdscan.scan_blocks(lines).kinds[7:10], [mdscan.FENCE] * 3)
        self.assertEqual(mathrender.find_math(UNPAIRED_DOLLAR)[0], [])
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", UNPAIRED_DOLLAR)
            m = model.load_edition(repo.edition)
            self.assertIn("thm-b", m.envs)
            out = checked(m)
        self.assertEqual(len(out), 3, out)
        self.assertTrue(out[0].startswith("WARNING") and "ch01.md:7: the '$' at column 12 is not closed before the "
                        "fenced code block on line 8" in out[0], out)
        self.assertIn("pairs this '$' with the one on line 9", out[0])
        errors = "\n".join(out[1:])
        self.assertIn("ch01.md:12: [@def-nope] refers to no environment", errors)
        self.assertIn("ch01.md:14: not a declaration GID: 'Fake/Module.bad'", errors)

    @unittest.skipUnless(HAVE_KATEX and MDBOOK, "node, katex and mdBook are required")
    def test_unpaired_dollar_before_a_fence_html(self):
        from tbook import html

        slug = "tbook-test-blocks-dollar"
        self.addCleanup(shutil.rmtree, config.paths.BUILD / "stage" / slug, True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ed = write_book(root, {"ch01.md": UNPAIRED_DOLLAR}, slug)
            html.build_edition(fixture_site(), ed.book, ed, None, None, root / "html")
            page = (root / "html" / "ch01.html").read_text(encoding="utf-8")
        main = page[page.index("<main>"):page.index("</main>")]
        self.assertIn('<code class="language-bash">export PATH=$HOME/bin:$PATH\n</code>', main)
        self.assertIn('<section class="tr-env tr-theorem', main)
        self.assertNotIn("katex", main)


UNPAIRED_DOLLAR = textwrap.dedent("""\
    # 第一章 甲

    ::: {.definition #def-a}
    甲。
    :::

    把 bin 目录加入 $PATH：
    ```bash
    export PATH=$HOME/bin:$PATH
    ```

    见 [@def-a] 与 [@def-nope]。

    ::: {.theorem #thm-b lean="Fake/Module.bad"}
    乙。
    :::
    """)


class ScanTimeTest(unittest.TestCase):
    """Pairing '$' over lines stays linear: many '$' left unpaired in one table or paragraph (a price in
    every row) once made scan_blocks and find_math quadratic."""

    def test_many_unpaired_dollars(self):
        rows = 3000
        texts = {"table": "| 项 | 值 |\n| --- | --- |\n" + "".join(f"| 项目{k} | 约 $5 起 |\n" for k in range(rows)),
                 "paragraph": "".join(f"{k} 行，价格 $5 起，\n" for k in range(rows)),
                 "line": "价格 $5 起，" * rows + "\n",
                 "before a fence": "".join(f"{k} 行 $x 与 $5\n" for k in range(rows)) + "```\na=$b\n```\n"}
        for name, text in texts.items():
            with self.subTest(name):
                start = time.perf_counter()
                mdscan.scan_blocks(text.split("\n"))
                mathrender.find_math(text)
                self.assertLess(time.perf_counter() - start, 1.5)


# --------------------------------------------------------------------------- the renderers themselves

# Every token zNN is code, hidden (in a comment), math or text for mdBook (given the source the HTML
# edition gives it: formulas rendered) and Pandoc alike; raw HTML blocks are left out (Pandoc reads
# Markdown in them). Where the two disagree, DISAGREE below says whom the block model follows.
AGREED = {
    "top-level indented": "z01 para\n\n    z02 code\n\n    z03 code\n\nz04 text\n",
    "paragraph continuation": "z01 text\n    z02 more text\n",
    "after heading": "# z01 T\n    z02 code\n",
    "after fence": "```\nz01\n```\n    z02 code\n",
    "list item code": "1. z01 运行：\n\n       z02 echo $HOME\n       z03 见[一](ch02.md)\n\nz04 正文\n",
    "list item para": "- z01 item\n\n    z02 para in item\n\nz03 out\n",
    "nested list code": "- z01 a\n  - z02 b\n\n        z03 code under b\n",
    "nested list para": "- z01 a\n\n  - z02 b\n\n    z03 para in b\n",
    "four after marker": "-    z01 four after\n\n         z02 code\n",
    "code on marker line": "-     z01 code on marker line\n",
    "ordered ten": "10. z01 ten\n\n        z02 code\n",
    "lazy continuation": "- z01 c\nz02 lazy c\n\n      z03 code under c\n",
    "definition": "z01 Term\n\n:   z02 def\n\n    z03 second para\n\n        z04 code in def\n",
    "definition short": "z01 Term2\n\n: z02 short\n\n  z03 second2\n\n      z04 code2\n\nz05 after\n",
    "definition no blank": "z01 Term3\n:   z02 no blank def\n\n        z03 code under def\n",
    "footnote": "z00 Text[^n].\n\n[^n]: z01 note\n\n    z02 second note para\n\n        z03 code in note\n",
    "footnote ends": "z00 Text[^k].\n\n[^k]: z01 note k\n\n  z02 two-space para\n\n     z03 five-space code\n",
    "quote code": "> z01 quote\n>\n>     z02 code in quote\n",
    "quote item code": "> - z01 qi\n>\n>       z02 code in quote item\n",
    "item quote code": "- z01 li\n\n  > z02 q in li\n  >\n  >     z03 code in q in li\n",
    "quote lazy": "> z01 a\n    z02 lazy\n",
    "comment in indented code": "z01 示例：\n\n    <!-- z02 待补\n\nz03 之后。\n",
    "comment block": "z01 a\n\n<!--\nz02 hidden\n\nz03 hidden\n-->\nz04 after\n",
    "comment block in item": "- z01 a\n\n  <!-- z02\n  z03 -->\n\nz04 out\n",
    "comment indented 4 in paragraph": "z01 text\n    <!-- z02 四格续行\n    z03 中间\n    --> z04 visible\n",
    "inline comment over lines": "z01 正文 <!-- z02 TODO\nz03 ![图](fig5.svg) --> z04 可见\n",
    "inline comment in item": "- z01 项 <!-- z02 跨行\n  z03 续行 --> z04 可见\n",
    "inline comment items": "- z01 项 <!-- z02 不闭合\n- z03 新项 z04\n",
    "inline comment quote": "> z01 引 <!-- z02 跨行\n> z03 续 --> z04 可见\n",
    "inline comment three lines": "z01 a <!-- z02\nz03\nz04 --> z05 b <!-- z06 --> z07\n",
    "code span opener": "z01 `<!--` z02 不是注释\nz03 下一行 -->\n",
    "fence in nested item": "- z01 item\n\n  - z02 nested\n\n    ```\n    z03 code\n    ```\n\nz04 out\n",
    "indented fence in paragraph": "z01 text\n    ```\n    z02 still text\n    ```\n",
    "fence indented four": "z01 text\n\n    ```\n    z02 code\n    ```\n",
    "tab indented": "z01 a\n\n\tz02 code\n",
    "list after paragraph": "z01 para\n- z02 b\n\n      z03 code\n",
    "heading in item": "- z01 a\n\n  # z02 h\n      z03 code\n",
    "setext": "z01 a\n---\n    z02 code\n",
    "empty item": "-\n  z01 foo\n\n      z02 code\n",
    # A formula over lines is read before the block rules (Pandoc), and rendered before mdBook runs.
    "display math over a list marker": "z01 竖式：\n\n$$\n\\begin{array}{r}\n  z02 \\\\\n+      z03 \\\\\n\\hline\n"
                                       "  z04\n\\end{array}\n$$\n\nz05 之后 $z06$。\n",
    "display math over a setext line": "z01 求和：\n\n$$\n\\sum_{k=1}^n z02\n=\n    \\frac{z03}{2}\n$$\n\nz04 后文\n",
    "display math over a heading": "z01 a\n$$\n# z02\n$$\n",
    "display math in a quote": "> z01 引\n>\n> $$\n> z02\n> +      z03\n> $$\n\nz04 后\n",
    "inline math over a code line": "z01 a $z02\n+     z03$ z04\n",
    # A fenced code block ends a formula that has not closed before it; nobody pairs these '$' over it.
    "unpaired $ before a fence without $": "z01 价格 $5：\n```\nz02 code\n```\n\nz03 后\n",
    "unpaired $ before a fence, no closer for Pandoc": "z01 a $x\n```\nz02 $y$\n```\n\nz03 后\n",
    "four-space fence in a formula is no fence": "z01 a $b\n    ```\n    z02 c$ d\n",
    "fence after a formula over lines": "z01 a $b\nc$ d\n```\nz02 x=$y\n```\n\nz03 后\n",
    # ':' starts a definition only after its term or another definition (in the same container).
    "colon line after code": "z01 命令：\n\n    z02 lake build\n\n:   z03 冒号开头。\n\n    z04 echo $HOME/$USER 见[二](ch02.md)\n",
    "colon line after an item": "- z01 项\n\n:   z02 定义?\n\n    z03 第二段\n",
    "colon line after a quote": "> z01 引\n\n:   z02 定义?\n\n    z03 第二段\n",
    "colon line after a table": "| z01 a | b |\n| - | - |\n| z02 c | d |\n\n:   z03 定义?\n\n    z04 第二段\n",
    "colon line after an HTML block": "<div>\nz01\n</div>\n\n:   z02 定义?\n\n    z03 第二段\n",
    "colon line in a new list item": "z01 Term\n\n- :   z02 def\n\n        z03 code\n",
    "definition after a fence in a definition": "z01 术语\n\n:   z02 定义\n\n    ```\n    z03 code\n    ```\n\n"
                                                ":   z04 第二个\n\n    z05 第二段\n",
    "definition right after code in a definition": "z01 术语\n\n:   z02 定义\n\n        z03 代码\n:   z04 第二个\n\n"
                                                   "    z05 第二段\n",
    "definition two blank lines after a definition": "z01 术语\n\n:   z02 定义\n\n\n:   z03 第二个\n\n    z04 第二段\n",
    # A ':' line that holds nothing starts a definition whose body starts in the column after the ':'.
    "empty colon definition": "z01 术语\n:\n    z02 定义\n\n    z03 第二段\n\nz04 后\n",
    "empty colon definition, code": "z01 术语\n:\n    z02 定义\n\n     z03 代码\n\nz04 后\n",
    "empty colon definition in a list": "- z01 术语\n  :\n      z02 定义\n\n      z03 第二段\n\nz04 后\n",
    "empty colon definition in a quote": "> z01 术语\n> :\n>     z02 定义\n>\n>     z03 第二段\n\nz04 后\n",
    "empty colon definition, then another": "z01 术语\n:\n    z02 定义\n:   z03 第二个\n\n    z05 第二段\n\nz04 后\n",
    # Each row of a table is a paragraph of its own for inline comments.
    "table comment closed in its cell": "| z01 a | b |\n| - | - |\n| z02 c <!-- z03 --> z04 | d |\n",
    "table comment open in a header cell": "| z01 a <!-- z02 | b |\n| - | - |\n| z03 c --> z04 | d |\n",
    "table ended by a list item": "| z01 a | b |\n| - | - |\n- z02 c <!-- z03\n  z04 e --> z05\n",
    "table ended by a lazy line": "- | z01 a | b |\n  | - | - |\n| z02 c <!-- z03 | x |\n| z04 e --> z05 | y |\n",
    "no table: cells differ": "| z01 a | b |\n| - |\n| z02 c <!-- z03 | d |\n| z04 e --> z05 | f |\n",
    "no table: header indented four": "z00 p\n    | z01 a | b |\n| - | - |\n| z02 c <!-- z03 | x |\n"
                                      "| z04 e --> z05 | y |\n",
}
TOKEN_RE = re.compile(r"z\d\d")

# Where mdBook and Pandoc read a text differently, the block model follows one of them and
# parse_blocks warns: (text, the renderer the model follows, the lines warned about).
DISAGREE = {
    "fence cut by its list item": ("1. z01 运行：\n\n   ```bash\n   z02 lake build\n  ```\n\nz03 见\n", "mdbook", [5, 5]),
    "fence cut by its block quote": ("> ```\n> z01 code\n\nz02 after\n", "mdbook", [3]),
    "fence cut by the next item": ("- z01 a\n\n  ```\n  z02 code\n- z03 b\n", "mdbook", [5]),
    "fence never closed": ("z01 text\n\n```\nz02 code\n\nz03 more\n", "mdbook", [3]),
    "term of two lines": ("z01 第一行\nz02 第二行\n\n:   z03 定义?\n\n    z04 第二段\n", "pandoc", [4]),
    "term of two lines, no blank": ("z01 第一行\nz02 第二行\n:   z03 定义?\n\n    z04 第二段\n", "pandoc", [3]),
    "two blank lines after the term": ("z01 术语\n\n\n:   z02 定义?\n\n    z03 第二段\n", "pandoc", [4]),
    "tilde definition": ("z01 术语\n\n~   z02 定义\n\n    z03 第二段\n", "pandoc", [3]),
    "comment open in a table cell": ("| z01 项 | 说明 |\n| --- | --- |\n| 一 | z02 待定 <!-- z03 稍后补 |\n| 二 | z04 见 |\n"
                                     "| 三 | z05 完成 --> z06 了 |\n", "mdbook", [3]),
    "comment open in a row after a paragraph": ("z00 text\n| z01 a | b |\n| - | - |\n| z02 c <!-- z03 | d |\n"
                                                "| z04 e --> z05 | f |\n", "mdbook", [4]),
    # A '$' left unpaired before a fenced code block: Pandoc pairs it with a '$' in the code, the HTML
    # edition (formulas rendered around code, then mdBook) shows the code block.
    "unpaired $ over a fence": ("z01 把 bin 目录加入 $PATH：\n```bash\nz02 export PATH=$HOME/bin:$PATH\n```\n\nz03 见\n",
                                "mdbook", [1]),
    "currency over a fence": ("z01 费用约 $5（见下）：\n```python\nz02 total=$x\n```\n\nz03 见\n", "mdbook", [1]),
    "typo over a fence": ("z01 其中 $a 为常数\n```lean\nz02 example : ($x) := by\n```\n\nz03 见\n", "mdbook", [1]),
    "two lines above a fence": ("z01 a $b\nz02 c\n```\nz03 x=$y\n```\n\nz04 见\n", "mdbook", [1]),
    "over a fence in a list item": ("1. z01 运行 $PATH：\n   ```bash\n   z02 export PATH=$HOME\n   ```\n\nz03 后\n",
                                    "mdbook", [1]),
    "over a fence in a block quote": ("> z01 用 $PATH：\n> ```bash\n> z02 export PATH=$HOME\n> ```\n\nz03 后\n",
                                      "mdbook", [1]),
    "display math over a fence": ("z01 a\n\n$$\n```\nz02\n```\n$$\n\nz03 b\n", "mdbook", [3]),
    "$$ before a fence": ("z01 用 $$ 表示进程号：\n```bash\nz02 echo $$\n```\n\nz03 后\n", "mdbook", [1]),
    # mdBook ends a definition whose ':' line holds nothing at the blank line after it; Pandoc does not.
    "empty colon definition, blank line": ("z01 术语\n:\n\n    z02 定义\n\nz04 后\n", "pandoc", [2]),
    "colon and space, blank line": ("z01 术语\n: \n\n    z02 定义\n\nz04 后\n", "pandoc", [2]),
}


def math_spans(md: str) -> list[tuple[int, int]]:
    return [(s.start, s.end) for s in mathrender.find_math(md)[0]]


def for_mdbook(md: str) -> str:
    """``md`` as the HTML edition hands it to mdBook: each formula replaced by inert HTML (here its
    TeX in a ``katex-fallback`` element, as when KaTeX cannot render it)."""
    spans = mathrender.find_math(md)[0]
    return mathrender.splice(md, spans, [mathrender.fallback_html(s.tex, s.display) for s in spans])


def ours(md: str) -> dict[str, str]:
    lines = md.split("\n")
    scan = mdscan.scan_blocks(lines)
    math = math_spans(md)
    out = {}
    offset = 0
    for line, kind, carry in zip(lines, scan.kinds, scan.carry):
        view = mdscan.close_comments(line, carry)
        shift = 4 if carry[0] else 0
        comments = [(a - shift, b - shift) for a, b in mdscan.code_spans(view, comments=True) if view[a] == "<"]
        for m in TOKEN_RE.finditer(line):
            if any(a <= offset + m.start() < b for a, b in math):
                out[m.group()] = "math"
            elif kind in (mdscan.FENCE, mdscan.CODE):
                out[m.group()] = "code"
            elif kind == mdscan.COMMENT or any(a <= m.start() < b for a, b in comments):
                out[m.group()] = "hidden"
            else:
                out[m.group()] = "text"
        offset += len(line) + 1
    return out


def pandoc_kinds(md: str) -> dict[str, str]:
    proc = subprocess.run([tp.pandoc_path(), "--from", tp.READER, "--to", "json"], input=md, capture_output=True,
                          text=True, check=True)
    out: dict[str, str] = {}

    def walk(x) -> None:
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            kind, c = x.get("t"), x.get("c")
            if kind == "CodeBlock":
                out.update(dict.fromkeys(TOKEN_RE.findall(c[1]), "code"))
            elif kind == "Math":
                out.update(dict.fromkeys(TOKEN_RE.findall(c[1]), "math"))
            elif kind in ("RawBlock", "RawInline"):
                out.update(dict.fromkeys(TOKEN_RE.findall(c[1]), "hidden"))
            elif kind in ("Str", "Code"):
                for tok in TOKEN_RE.findall(c if kind == "Str" else c[1]):
                    out.setdefault(tok, "text")
            elif c is not None:
                walk(c)

    walk(json.loads(proc.stdout)["blocks"])
    return out


def mdbook_kinds(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r'<code class="katex-fallback"[^>]*>(.*?)</code>', html, re.S):  # see for_mdbook
        out.update(dict.fromkeys(TOKEN_RE.findall(m.group(1)), "math"))
    html = re.sub(r'<code class="katex-fallback"[^>]*>.*?</code>', "", html, flags=re.S)
    for m in re.finditer(r"<pre><code[^>]*>(.*?)</code></pre>", html, re.S):
        out.update(dict.fromkeys(TOKEN_RE.findall(m.group(1)), "code"))
    html = re.sub(r"<pre><code[^>]*>.*?</code></pre>", "", html, flags=re.S)
    for m in re.finditer(r"<!--(.*?)-->", html, re.S):
        out.update(dict.fromkeys(TOKEN_RE.findall(m.group(1)), "hidden"))
    for tok in TOKEN_RE.findall(re.sub(r"<!--.*?-->", "", html, flags=re.S)):
        out.setdefault(tok, "text")
    return out


class RenderersAgreeTest(unittest.TestCase):
    """The block model is the one mdBook and Pandoc apply (checked against both when installed); where
    they disagree, it is the one of the renderer DISAGREE names, and parse_blocks warns."""

    def test_warnings(self):
        for name, (md, _, lines) in DISAGREE.items():
            with self.subTest(name):
                issues: list[mdscan.ScanIssue] = []
                mdscan.parse_blocks(md, issues)
                self.assertEqual(sorted(i.line for i in issues), lines)
                self.assertEqual({i.severity for i in issues}, {"warning"})
        for name, md in AGREED.items():
            if not name.startswith("table comment open"):
                with self.subTest(name):
                    issues = []
                    mdscan.parse_blocks(md, issues)
                    if name == "list after paragraph":  # its tokens agree, its list does not (FindingsTest)
                        issues = [i for i in issues if i.message != mdscan._LIST_CUT]
                    self.assertEqual(issues, [])

    @unittest.skipUnless(have_pinned_pandoc(), f"Pandoc {PINNED_PANDOC} needed (requirements.txt)")
    def test_pandoc(self):
        for name, md in AGREED.items():
            with self.subTest(name):
                self.assertEqual(pandoc_kinds(md), ours(md))
        for name, (md, side, _) in DISAGREE.items():
            with self.subTest(name):
                (self.assertEqual if side == "pandoc" else self.assertNotEqual)(pandoc_kinds(md), ours(md))

    @unittest.skipUnless(MDBOOK and (shutil.which(MDBOOK) or os.path.exists(MDBOOK)), "mdBook needed")
    def test_mdbook(self):
        texts = dict(AGREED, **{name: md for name, (md, _, _) in DISAGREE.items()})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "book.toml").write_text('[book]\ntitle = "t"\n\n[output.html]\n', encoding="utf-8")
            names = {f"c{k:02d}": name for k, name in enumerate(texts)}
            (root / "src" / "SUMMARY.md").write_text(
                "# Summary\n\n" + "".join(f"- [{c}]({c}.md)\n" for c in names), encoding="utf-8")
            for c, name in names.items():
                (root / "src" / f"{c}.md").write_text(for_mdbook(texts[name]), encoding="utf-8")
            subprocess.run([MDBOOK, "build"], cwd=root, capture_output=True, check=True)
            for c, name in names.items():
                page = (root / "book" / f"{c}.html").read_text(encoding="utf-8")
                main = page[page.index("<main>"):page.index("</main>")]
                with self.subTest(name):
                    same = name in AGREED or DISAGREE[name][1] == "mdbook"
                    (self.assertEqual if same else self.assertNotEqual)(mdbook_kinds(main), ours(texts[name]))


if __name__ == "__main__":
    unittest.main()
