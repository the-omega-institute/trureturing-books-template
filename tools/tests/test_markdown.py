"""Regression tests for the Markdown layer: mdscan, summary titles, render links/badges, ledger.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_markdown.py'

Every test that needs a book builds a throwaway books repository (``Repo``): the
``tbook.paths`` attributes the core reads at call time are patched to point into it, and the
cached ``config.load_site`` / ``config.i18n`` are cleared on entry and exit. The lock is an
in-memory ``lean.Lock``; nothing touches the network, mdBook or Pandoc. The i18n tables are
read from this repository's ``theme/`` (read-only). Nothing here depends on
``books/example-monograph``.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from tbook import config, lean, ledger, mdscan, model, paths, render, summary

REAL_I18N = paths.THEME / "i18n"
TRU = "the-omega-institute/trureturing"
COMMIT = "c" * 40
GID_OK = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"
GID_DEF = "D5/S1/Deficit/DeficitInteger.deficit"
GID_MISSING = "D5/S1/Deficit/DeficitThreeValued.riemann_hypothesis"
MOD_OK = "D5/S1/Deficit/DeficitThreeValued"
MOD_INT = "D5/S1/Deficit/DeficitInteger"
SOURCE_OK = f"https://github.com/{TRU}/blob/{COMMIT}/{MOD_OK}.lean#L12"
SOURCE_DEF = f"https://github.com/{TRU}/blob/{COMMIT}/{MOD_INT}.lean#L7"

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
"""

SUMMARY = """\
# Summary

[前言](README.md)

- [第一章](ch01.md)
  - [小节](sub/sec.md)

[附录 A：$\\varphi$-边界 \\[x\\] a\\\\b](appendix/app-a.md)
"""

CHAPTERS = {
    "README.md": """\
        # 前言

        ::: {.definition #def-pre title="前言里的定义"}
        定义。
        :::
        """,
    "ch01.md": f"""\
        # 第一章

        ::: {{.theorem #thm-ok title="关于 $\\varphi^n$ 与 $\\{{-1,0,1\\}}$ 的定理" lean="{GID_OK}"}}
        陈述。
        :::

        ::: {{.theorem #thm-missing title="伪定理" lean="{GID_MISSING}"}}
        不在锁文件中。
        :::

        ::: {{.lemma #lem-def lean="{GID_DEF}"}}
        引用的是 def。
        :::

        ::: {{.corollary #cor-none}}
        没有 Lean 引用。
        :::

        见 [@def-pre]；[前言](README.md)；[锚](README.md#def-pre)；[`rh`](lean:{GID_MISSING})；[`ok`](lean:{GID_OK})。

        > ```markdown
        > 写作 [@thm-ok] 引用定理；图片写 ![x](../assets/fig.svg)
        > ```

        - 列表
            - 嵌套

                ```markdown
                写作 [@thm-ok] 与 [@nope] 引用定理
                ```

        ![引用式][fig]

        ![带空格](<../assets/fig two.svg>)

        ![百分号](../assets/fig%20two.svg)

        [fig]: ../assets/fig.svg "Figure"
        [^note]: ../assets/fig.svg
        """,
    "sub/sec.md": """\
        # 小节

        见 [@def-pre] 与 [前言](../README.md#def-pre)。
        """,
    "appendix/app-a.md": """\
        # 附录 A

        [前言](../README.md)，[@def-pre]，[外部](<https://example.org/a b>)。
        """,
}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def make_lock() -> lean.Lock:
    return lean.Lock(repo=TRU, branch="dev", commit=COMMIT, pinned_at="2026-01-01T00:00:00Z", declarations={
        GID_OK: {"module": MOD_OK, "name": "D5.S1.Deficit.deficit_three_valued", "kind": "theorem",
                 "statement_id": "sha256:3v", "line": 12, "signature": ""},
        GID_DEF: {"module": MOD_INT, "name": "D5.S1.Deficit.deficit", "kind": "def",
                  "statement_id": "sha256:def", "line": 7, "signature": ""},
    })


class Repo:
    """A throwaway books repository with one zh edition; ``tbook.paths`` points into it while active."""

    def __enter__(self) -> "Repo":
        self._tmp = tempfile.TemporaryDirectory(prefix="tbook-md-")
        r = self.root = Path(self._tmp.name)
        self.stack = ExitStack()
        for name, value in dict(ROOT=r, BOOKS=r / "books", BUILD=r / "build", SITE_OUT=r / "_site", CACHE=r / ".cache",
                                SITE_TOML=r / "site.toml", TEMPLATE_TOML=r / "template.toml",
                                LOCK_FILE=r / "trureturing.lock.json", I18N_LOCAL=r / "i18n",
                                I18N_THEME=REAL_I18N).items():
            self.stack.enter_context(mock.patch.object(paths, name, value))
        self.stack.enter_context(mock.patch.dict(os.environ))
        for key in ("TBOOK_REPO", "TBOOK_BASE_URL", "GITHUB_REPOSITORY", "TRURETURING_DIR", "TBOOK_ROOT"):
            os.environ.pop(key, None)
        config.load_site.cache_clear()
        config.i18n.cache_clear()
        self.stack.callback(config.i18n.cache_clear)
        self.stack.callback(config.load_site.cache_clear)
        write(r / "site.toml", SITE)
        bdir = r / "books" / "demo"
        write(bdir / "book.toml", """\
            [book]
            version = "1.0.0"
            editions = ["zh"]

            [book.title]
            zh = "示例"
            """)
        write(bdir / "zh" / "SUMMARY.md", SUMMARY)
        for rel, text in CHAPTERS.items():
            write(bdir / "zh" / rel, text)
        write(bdir / "assets" / "fig.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
        write(bdir / "assets" / "fig two.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
        self.book = config.load_book("demo")
        self.edition = self.book.primary
        self.model = model.load_edition(self.edition)
        return self

    def __exit__(self, *exc) -> None:
        self.stack.close()
        self._tmp.cleanup()

    def ctx(self, target: str = "mdbook", lock: lean.Lock | None | str = "default") -> render.RenderContext:
        return render.RenderContext(site=config.load_site(), book=self.book, edition=self.edition, model=self.model,
                                    lock=make_lock() if lock == "default" else lock, target=target,
                                    env_href=render.mdbook_env_href(self.model) if target == "mdbook" else None)

    def doc(self, path: str) -> model.ChapterDoc:
        return next(d for d in self.model.chapters if d.chapter.path == path)

    def render(self, path: str, target: str = "mdbook", lock: lean.Lock | None | str = "default"):
        ctx = self.ctx(target, lock)
        return render.chapter_markdown(self.doc(path), ctx), ctx

    @property
    def assets(self) -> Path:
        return (self.root / "books" / "demo" / "assets").resolve()


# --------------------------------------------------------------------------- finding 1: TeX in titles


class TitleBackslashTests(unittest.TestCase):
    """Regression: attribute and SUMMARY titles lost every backslash (``$\\varphi$`` → ``$varphi$``)."""

    def test_parse_attrs_keeps_tex(self):
        a = mdscan.parse_attrs(r'''.theorem #thm-x title="关于 $\varphi$ 与 $\{-1,0,1\}$"''')
        self.assertEqual(a.kv["title"], r"关于 $\varphi$ 与 $\{-1,0,1\}$")

    def test_parse_attrs_unescapes_only_quoting(self):
        a = mdscan.parse_attrs(r'''title="say \"hi\" a\\b \alpha" note='it\'s \le' bare=x\y''')
        self.assertEqual(a.kv, {"title": 'say "hi" a\\b \\alpha', "note": "it's \\le", "bare": "x\\y"})
        again = mdscan.parse_attrs(a.to_pandoc()[1:-1])
        self.assertEqual(again.kv, a.kv, "to_pandoc round-trips backslashes")

    def test_div_title_may_contain_braces(self):
        issues: list[mdscan.ScanIssue] = []
        blocks = mdscan.parse_blocks('::: {.theorem #t title="$\\mathbb{N}$ 上 {x}" lean="A/B.c"}\nbody\n:::\n', issues)
        self.assertEqual(issues, [])
        div = blocks[0]
        self.assertIsInstance(div, mdscan.Div)
        self.assertEqual((div.attrs.id, div.attrs.get("title"), div.attrs.get("lean")),
                         ("t", "$\\mathbb{N}$ 上 {x}", "A/B.c"))
        self.assertEqual(div.end, 3)

    def test_unparseable_div_opener_is_reported(self):
        issues: list[mdscan.ScanIssue] = []
        blocks = mdscan.parse_blocks('::: {.theorem #t title="unterminated}\nbody\n:::\n', issues)
        self.assertEqual([i.line for i in issues], [1])
        self.assertIn("cannot parse", issues[0].message)
        self.assertFalse(any(isinstance(b, mdscan.Div) for b in blocks))

    def test_summary_titles_keep_tex(self):
        self.assertEqual(summary._unescape(r"附录 B：$\varphi$-边界 \[x\] a\\b \{"), r"附录 B：$\varphi$-边界 [x] a\b {",
                         "Markdown escapes are undone outside math, as mdBook does")
        with Repo() as repo:
            app = repo.model.summary.chapters[-1]
            self.assertEqual(app.title, "附录 A：$\\varphi$-边界 [x] a\\b")

    def test_env_title_reaches_every_target(self):
        title = "关于 $\\varphi^n$ 与 $\\{-1,0,1\\}$ 的定理"
        with Repo() as repo:
            self.assertEqual(repo.model.envs["thm-ok"].title, title)
            html_out, _ = repo.render("ch01.md")
            self.assertIn('<span class="tr-env-title">（关于 $\\varphi^n$ 与 $\\{-1,0,1\\}$ 的定理）</span>', html_out)
            pandoc_out, _ = repo.render("ch01.md", target="pandoc")
            first = next(line for line in pandoc_out.splitlines() if line.startswith(":::::: {#thm-ok"))
            self.assertEqual(mdscan.parse_attrs(first[len(":::::: {"):-1]).kv["tr-title"], title)
            self.assertIn(f"| {title} |", ledger.ledger_markdown(repo.model, make_lock()))


# --------------------------------------------------------------------------- finding 13: README → index


class ReadmeLinkTests(unittest.TestCase):
    """Regression: links and [@id] into the README.md preface pointed to README.html (mdBook writes index.html)."""

    def test_mdbook_chapter_path(self):
        self.assertEqual(render.mdbook_chapter_path("README.md"), "index.md")
        self.assertEqual(render.mdbook_chapter_path("part/Readme.md"), "part/index.md")
        self.assertEqual(render.mdbook_chapter_path("ch01.md"), "ch01.md")
        self.assertEqual(render.mdbook_chapter_path("readme-notes.md"), "readme-notes.md")

    def test_mdbook_links_into_readme(self):
        with Repo() as repo:
            ch01, ctx = repo.render("ch01.md")
            self.assertIn("见 [定义0.1](index.md#def-pre)；[前言](index.md)；[锚](index.md#def-pre)", ch01)
            sec, _ = repo.render("sub/sec.md")
            self.assertIn("见 [定义0.1](../index.md#def-pre) 与 [前言](../index.md#def-pre)。", sec)
            app, _ = repo.render("appendix/app-a.md")
            self.assertIn("[前言](../index.md)，[定义0.1](../index.md#def-pre)", app)
            self.assertEqual(ctx.issues, [])

    def test_pandoc_links_into_readme_unchanged(self):
        with Repo() as repo:
            ch01, _ = repo.render("ch01.md", target="pandoc")
            self.assertIn("见 [定义0.1](#def-pre)；[前言](README.md)；[锚](README.md#def-pre)", ch01,
                          "the Pandoc linker maps chapter files to ids itself")

    def test_readme_that_is_not_a_chapter_is_left_alone(self):
        with Repo() as repo:
            write(repo.edition.dir / "notes" / "README.md", "# notes\n")
            out = render.transform_line("[n](notes/README.md)", repo.doc("ch01.md"), repo.ctx())
            self.assertEqual(out, "[n](notes/README.md)")


# --------------------------------------------------------------------------- finding 18: asset link forms


class AssetLinkFormTests(unittest.TestCase):
    """Regression: reference-style and ``<…>`` asset links were never rewritten into ``_book/``."""

    def test_reference_definition_angle_and_percent_forms(self):
        with Repo() as repo:
            out, ctx = repo.render("ch01.md")
            self.assertIn('[fig]: _book/assets/fig.svg "Figure"', out)
            self.assertIn("![带空格](_book/assets/fig%20two.svg)", out)
            self.assertIn("![百分号](_book/assets/fig%20two.svg)", out)
            self.assertIn("[^note]: ../assets/fig.svg", out, "footnotes are not reference definitions")
            self.assertEqual(ctx.book_files, {repo.assets / "fig.svg", repo.assets / "fig two.svg"})
            self.assertEqual(ctx.issues, [])

    def test_nested_chapter_and_pandoc_target(self):
        with Repo() as repo:
            doc = repo.doc("sub/sec.md")
            ctx = repo.ctx(target="pandoc")
            self.assertEqual(render.transform_line("[f]: <../../assets/fig two.svg>", doc, ctx),
                             "[f]: ../_book/assets/fig%20two.svg")
            self.assertEqual(render.transform_line("![a](<../../assets/fig two.svg> \"T\")", doc, ctx),
                             '![a](../_book/assets/fig%20two.svg "T")')
            self.assertEqual(ctx.book_files, {repo.assets / "fig two.svg"})

    def test_other_angle_destinations_become_plain(self):
        with Repo() as repo:
            app, ctx = repo.render("appendix/app-a.md")
            self.assertIn("[外部](https://example.org/a%20b)", app)
            out = render.transform_line("[x](<ch01.md#thm-ok>) [y](plain.md)", repo.doc("ch01.md"), ctx)
            self.assertEqual(out, "[x](ch01.md#thm-ok) [y](plain.md)")

    def test_link_leaving_the_book_is_reported(self):
        with Repo() as repo:
            ctx = repo.ctx()
            out = render.transform_line("[o]: <../../../out side.png>", repo.doc("ch01.md"), ctx)
            self.assertEqual(out, "[o]: ../../../out%20side.png")
            self.assertTrue(any("link leaves the book directory" in i for i in ctx.issues), ctx.issues)


# --------------------------------------------------------------------------- finding 20: fences in containers


class ContainerFenceTests(unittest.TestCase):
    """Regression: fences inside block quotes or nested list items were treated as prose."""

    def test_quote_and_list_fences_are_code(self):
        text = textwrap.dedent("""\
            > ```markdown
            > [@a] ![x](../assets/fig.svg)
            > ```

            - item
                - nested

                    ~~~
                    [@b]
                    ~~~

            after [@c]
            """)
        blocks = mdscan.parse_blocks(text)
        codes = [b for b in blocks if isinstance(b, mdscan.Code)]
        self.assertEqual([c.lines[1].strip() for c in codes], ["> [@a] ![x](../assets/fig.svg)", "[@b]"])
        self.assertEqual([line for _, line in mdscan.iter_text_lines(blocks) if "[@" in line], ["after [@c]"])

    def test_fences_shown_inside_a_code_example_do_not_close_it(self):
        text = textwrap.dedent("""\
            ```markdown
            > ```
            > # quoted [@x]
            > ```

                ```
                code [@y]
                ```
            ```
            after [@z]
            """)
        blocks = mdscan.parse_blocks(text)
        self.assertIsInstance(blocks[0], mdscan.Code)
        self.assertEqual(len(blocks[0].lines), 9)
        self.assertEqual([line for _, line in mdscan.iter_text_lines(blocks) if line], ["after [@z]"])

    def test_unclosed_container_fence_ends_with_its_container(self):
        text = "> ```\n> code [@a]\n\nprose [@b]\n\n- a\n    - b\n\n        ```\n        code [@c]\nprose [@d]\n"
        blocks = mdscan.parse_blocks(text)
        prose = [line for _, line in mdscan.iter_text_lines(blocks) if "[@" in line]
        self.assertEqual(prose, ["prose [@b]", "prose [@d]"])
        mask = mdscan.fenced_code_lines(text.split("\n"))
        code = {line for line, hidden in zip(text.split("\n"), mask) if hidden}
        self.assertEqual(code, {"> ```", "> code [@a]", "        ```", "        code [@c]"},
                         "fenced_code_lines agrees with parse_blocks")

    def test_inline_triple_backticks_are_not_a_fence(self):
        blocks = mdscan.parse_blocks("```x``` is inline code\n[@a]\n")
        self.assertEqual([type(b).__name__ for b in blocks], ["Text"])
        self.assertIsNone(mdscan.FENCE_RE.match("```x``` y"))
        self.assertIsNotNone(mdscan.FENCE_RE.match("```python title=x"))
        self.assertIsNone(mdscan.FENCE_RE.match("> ```"), "FENCE_RE stays top-level only")

    def test_render_and_model_leave_fence_contents_alone(self):
        with Repo() as repo:
            doc = repo.doc("ch01.md")
            self.assertNotIn("nope", [ref for _, ref in doc.refs], "no check error for refs inside code")
            out, ctx = repo.render("ch01.md")
            self.assertIn("> 写作 [@thm-ok] 引用定理；图片写 ![x](../assets/fig.svg)", out)
            self.assertIn("        写作 [@thm-ok] 与 [@nope] 引用定理", out)
            self.assertFalse(any("nope" in i for i in ctx.issues), ctx.issues)


# --------------------------------------------------------------------------- finding 33: no unbacked LEAN badge


class UnverifiedBadgeTests(unittest.TestCase):
    """Regression: the green LEAN ✓ badge and ledger links were shown for GIDs the lock does not resolve."""

    def test_env_view(self):
        with Repo() as repo:
            ctx = repo.ctx()
            ok = render.env_view(repo.model.envs["thm-ok"], ctx)
            self.assertEqual((ok["badge"], ok["status"], ok["unverified"]), ("LEAN ✓", "lean", False))
            for env_id in ("thm-missing", "lem-def", "cor-none"):
                view = render.env_view(repo.model.envs[env_id], ctx)
                self.assertEqual((view["badge"], view["status"], view["unverified"]), ("UNVERIFIED", "open", True),
                                 env_id)
            bare = render.env_view(repo.model.envs["thm-ok"], repo.ctx(lock=None))
            self.assertEqual((bare["badge"], bare["unverified"]), ("UNVERIFIED", True), "no lock, no verification")
            missing = render.lean_view(GID_MISSING, make_lock())
            self.assertEqual((missing["resolved"], missing["url"], missing["state_url"]), (False, "", ""))

    def test_mdbook_markup(self):
        with Repo() as repo:
            out, _ = repo.render("ch01.md")
            self.assertIn(f'<a class="tr-badge tr-badge-lean" href="{SOURCE_OK}"', out)
            self.assertEqual(out.count("tr-badge-lean"), 1, "only the resolved theorem is green")
            self.assertIn('<section class="tr-env tr-theorem tr-status-open tr-unverified" id="thm-missing"', out)
            self.assertIn('<span class="tr-badge tr-badge-open tr-badge-unverified" title="', out)
            self.assertIn(f'<code class="tr-lean-decl tr-lean-unresolved" title="{GID_MISSING}">', out)
            self.assertNotIn(f'href="https://github.com/{TRU}/blob/{COMMIT}/{MOD_OK}.lean"', out,
                             "no source link for the unresolved declaration")
            self.assertIn(f'<a class="tr-lean-decl" href="{SOURCE_DEF}"', out, "a locked def still links")
            self.assertIn(f"；`rh`；[`ok`]({SOURCE_OK})。", out, "an unresolved lean: link keeps only its text")

    def test_pandoc_attributes(self):
        with Repo() as repo:
            out, _ = repo.render("ch01.md", target="pandoc")
            first = next(line for line in out.splitlines() if line.startswith(":::::: {#thm-missing"))
            kv = mdscan.parse_attrs(first[len(":::::: {"):-1]).kv
            self.assertEqual((kv["tr-status"], kv["tr-badge"], kv["tr-lean-url"]), ("open", "UNVERIFIED", "-"))

    def test_ledger(self):
        with Repo() as repo:
            text = ledger.ledger_markdown(repo.model, make_lock())
            rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| [")}
            self.assertIn(f"[`D5.S1.Deficit.deficit_three_valued`]({SOURCE_OK})", rows["[定理1.1](#thm-ok)"])
            self.assertIn("[`3v`]", rows["[定理1.1](#thm-ok)"])
            self.assertIn(f"| `{GID_MISSING}` | **UNVERIFIED** |", rows["[定理1.2](#thm-missing)"])
            self.assertIn(f"[`D5.S1.Deficit.deficit`]({SOURCE_DEF}) | **UNVERIFIED** |", rows["[引理1.3](#lem-def)"])
            self.assertIn("| **UNVERIFIED** |", rows["[推论1.4](#cor-none)"])
            bare = ledger.ledger_markdown(repo.model, None)
            self.assertNotIn("https://github.com", bare)
            self.assertEqual(bare.count("**UNVERIFIED**"), 4)

    def test_unverified_badge_never_links(self):
        """Re-review 7/8: the UNVERIFIED badge is never a link and says "unverified" in every target;
        the footer still links each declaration the lock resolves (here a def)."""
        with Repo() as repo:
            ctx = repo.ctx()
            self.assertEqual(render.env_view(repo.model.envs["thm-ok"], ctx)["badge_url"], SOURCE_OK)
            self.assertEqual(render.env_view(repo.model.envs["lem-def"], ctx)["badge_url"], "")
            out, _ = repo.render("ch01.md", target="pandoc")
            kv = {}
            for env_id in ("thm-ok", "lem-def"):
                first = next(line for line in out.splitlines() if line.startswith(f":::::: {{#{env_id}"))
                kv[env_id] = mdscan.parse_attrs(first[len(":::::: {"):-1]).kv
            self.assertEqual(kv["lem-def"]["tr-badge-title"], config.s("zh", "badge.unverified_title"))
            self.assertNotEqual(kv["lem-def"]["tr-badge-title"], config.s("zh", "badge.open_title"))
            self.assertEqual(kv["lem-def"]["tr-unverified"], "1")
            self.assertNotIn("tr-badge-url", kv["lem-def"])
            self.assertEqual(kv["lem-def"]["tr-lean-url"], SOURCE_DEF, "the footer still links the locked def")
            self.assertEqual((kv["thm-ok"]["tr-badge-url"], kv["thm-ok"]["tr-badge-title"]),
                             (SOURCE_OK, config.s("zh", "badge.lean_title")))
            self.assertNotIn("tr-unverified", kv["thm-ok"])

    def test_lua_filter_badges(self):
        from test_pandoc import have_pandoc, run_filters

        if not have_pandoc():
            self.skipTest("pandoc not available")
        with Repo() as repo:
            out, _ = repo.render("ch01.md", target="pandoc")
            unverified, lean_title = config.s("zh", "badge.unverified_title"), config.s("zh", "badge.lean_title")
        epub = run_filters(out, "html5")
        self.assertIn(f'<span class="tr-badge tr-badge-open tr-badge-unverified" title="{unverified}">UNVERIFIED</span>',
                      epub)
        self.assertNotIn(config.s("zh", "badge.open_title"), epub, "no open-problem tooltip on a theorem")
        self.assertNotRegex(epub, r'<a [^>]*class="tr-badge[^"]*unverified')
        self.assertIn(f'<a href="{SOURCE_OK}" class="tr-badge tr-badge-lean" title="{lean_title}">LEAN ✓</a>', epub)
        self.assertIn(f'<a href="{SOURCE_DEF}" class="tr-lean-decl"', epub, "the footer still links the locked def")
        self.assertIn('class="tr-env tr-theorem tr-status-open tr-unverified"', epub)
        typst = run_filters(out, "typst")
        self.assertIn(f'badge: "UNVERIFIED", badge-url: "", lean: ((gid: "{GID_DEF}", name: "D5.S1.Deficit.deficit", '
                      f'url: "{SOURCE_DEF}"),)', typst)
        self.assertIn(f'badge: "LEAN ✓", badge-url: "{SOURCE_OK}"', typst)


# --------------------------------------------------------------------------- re-review 3: reference definitions


class ReferenceDefinitionTests(unittest.TestCase):
    """Re-review 3: only a line CommonMark reads as a link reference definition is one. A paragraph
    that starts with ``[注]:`` kept its real links unrewritten (a dead image) and check named a file
    after the first word."""

    PROSE = "[注]: 原始图见 [fig](../assets/fig.svg)。"

    def test_prose_is_not_a_definition(self):
        for line in (self.PROSE, "[1]: Knuth, TAOCP.", "[@thm-x]: this shows [fig](../assets/fig.svg)",
                     '[x]: url "title" trailing', "[^n]: ../assets/fig.svg"):
            self.assertIsNone(mdscan.refdef(line), line)
        with Repo() as repo:
            ctx, doc = repo.ctx(), repo.doc("ch01.md")
            self.assertEqual(render.transform_line(self.PROSE, doc, ctx), "[注]: 原始图见 [fig](_book/assets/fig.svg)。")
            self.assertEqual(ctx.book_files, {repo.assets / "fig.svg"})
            self.assertEqual(render.transform_line("[1]: Knuth, TAOCP.", doc, ctx), "[1]: Knuth, TAOCP.")

    def test_pandoc_reads_such_a_line_as_a_paragraph_too(self):
        """Pandoc's Markdown takes a URL of several words, so ``[1]: Knuth, TAOCP.`` would vanish from
        PDF/EPUB while mdBook shows it: for Pandoc the bracket is escaped."""
        image = "[注]: 原始图见 ![fig](../assets/fig.svg)。"
        with Repo() as repo:
            ctx, doc = repo.ctx(target="pandoc"), repo.doc("ch01.md")
            self.assertEqual(render.transform_line(image, doc, ctx), "\\[注]: 原始图见 ![fig](_book/assets/fig.svg)。")
            self.assertEqual(render.transform_line("[1]: Knuth, TAOCP.", doc, ctx), "\\[1]: Knuth, TAOCP.")
            self.assertEqual(render.transform_line("[f]: ../assets/fig.svg", doc, ctx), "[f]: _book/assets/fig.svg")
            self.assertEqual(render.transform_line("[f]:", doc, ctx), "[f]:", "the destination may follow on the next line")
            self.assertEqual(render.transform_line("[@thm-ok]: 见上。", doc, ctx), "[定理1.1](#thm-ok): 见上。")
            self.assertEqual(render.transform_line("[1]: Knuth, TAOCP.", doc, repo.ctx()), "[1]: Knuth, TAOCP.",
                             "mdBook reads CommonMark: a paragraph already")
            md = render.transform_line(image, doc, ctx) + "\n\n" + render.transform_line("[1]: Knuth, TAOCP.", doc, ctx)
        from test_pandoc import have_pandoc

        if have_pandoc():
            from tbook import pandoc

            native = subprocess.run([pandoc.pandoc_path(), "-f", pandoc.READER, "-t", "plain"], input=md,
                                    capture_output=True, text=True, check=True).stdout
            self.assertIn("[注]: 原始图见", native)
            self.assertIn("[1]: Knuth, TAOCP.", native)

    def test_definitions_with_titles(self):
        with Repo() as repo:
            ctx, doc = repo.ctx(), repo.doc("ch01.md")
            for title in ("", ' "T"', " 'T'", " (T)", ' "continued on the next line', "  "):
                line = f"[f]: ../assets/fig.svg{title}"
                self.assertIsNotNone(mdscan.refdef(line), line)
                self.assertEqual(render.transform_line(line, doc, ctx), f"[f]: _book/assets/fig.svg{title}")
            self.assertEqual(render.transform_line("   [f]: <../assets/fig two.svg> 'T'", doc, ctx),
                             "   [f]: _book/assets/fig%20two.svg 'T'")

    def test_pandoc_stager_and_check_agree(self):
        from tbook import check, pandoc

        self.assertIs(pandoc.REFDEF_RE, mdscan.REFDEF_RE)
        with Repo() as repo, tempfile.TemporaryDirectory() as tmp:
            warnings: list[str] = []
            linker = pandoc._Linker(Path(tmp), repo.edition, {"ch01.md": "ch-01"}, warnings, set(), online="")
            self.assertEqual(linker.rewrite_line("[注]: 见 [第一章](ch01.md)。", "ch01.md"), "[注]: 见 [第一章](#ch-01)。")
            self.assertEqual(warnings, [])
            write(repo.edition.dir / "ch01.md", "# 第一章\n\n[注]: 原始图见 [fig](../assets/missing.svg)。\n\n"
                                                "[1]: Knuth, TAOCP.\n")
            issues: list[model.Issue] = []
            check.check_links(model.load_edition(repo.edition), config.load_site(), issues)
            self.assertEqual([(i.line, i.message) for i in issues],
                             [(3, "links to books/demo/assets/missing.svg, which does not exist")])


# --------------------------------------------------------------------------- re-review 4/5: escapes in titles


class TitleEscapeTests(unittest.TestCase):
    """Re-review 4/5: titles are inline Markdown. A backslash escape outside math (``C\\*-代数``) showed
    its backslash in mdBook headers, the sidebar, page titles and the site, but not in PDF, EPUB or the
    ledger; every target now shows ``C*-代数``, and TeX inside ``$…$`` keeps its backslashes."""

    TITLE = r"C\*-代数 与 snake\_case 与 \$5 与 $\{x\}$ 与 \$y\$"
    PLAIN = r"C*-代数 与 snake_case 与 $5 与 $\{x\}$ 与 $y$"

    def test_unescape_markdown(self):
        self.assertEqual(mdscan.unescape_markdown(self.TITLE), self.PLAIN)
        self.assertEqual(mdscan.unescape_markdown(r"`a\_b` \`c\` a\b \α"), r"`a\_b` `c` a\b \α",
                         "code spans stay as written; only ASCII punctuation is escaped")
        self.assertEqual(mdscan.unescape_markdown(r"$$\{a\}$$ \{b\}"), r"$$\{a\}$$ {b}")

    def chapter(self, repo: Repo) -> model.EditionModel:
        write(repo.edition.dir / "ch01.md", f"""\
            # 第一章

            ::: {{.theorem #thm-ok title="{self.TITLE}" lean="{GID_OK}"}}
            陈述。
            :::

            ::: {{.remark #rem-r title="[@thm-ok] 的 \\_注记"}}
            注。
            :::
            """)
        return model.load_edition(repo.edition)

    def test_every_target_reads_the_title_alike(self):
        from tbook import mathrender

        with Repo() as repo:
            m = self.chapter(repo)
            env = m.envs["thm-ok"]
            self.assertEqual(env.title, self.TITLE)
            self.assertEqual(m.title_text(env), self.PLAIN, "the site and headings show plain text")
            self.assertEqual(m.title_text(m.envs["rem-r"]), "定理1.1 的 _注记")
            ctx = render.RenderContext(config.load_site(), repo.book, repo.edition, m, make_lock(), target="mdbook",
                                       env_href=render.mdbook_env_href(m))
            view = render.env_view(env, ctx)
            self.assertEqual((view["title_text"], view["heading"]), (self.PLAIN, f"定理1.1（{self.PLAIN}）"))
            out = render.chapter_markdown(m.chapters[1], ctx)
            header = next(line for line in out.splitlines() if "<header" in line and "C*" in line)
            self.assertIn("（C*-代数 与 snake_case 与 &#36;5 与 $\\{x\\}$ 与 &#36;y&#36;）", header)
            spans, _ = mathrender.find_math(header)
            self.assertEqual([s.tex for s in spans], [r"\{x\}"], "the header has exactly Pandoc's formulas")
            self.assertIn("（定理1.1 的 _注记）", out)
            pctx = render.RenderContext(config.load_site(), repo.book, repo.edition, m, make_lock(), target="pandoc")
            pout = render.chapter_markdown(m.chapters[1], pctx)
            first = next(line for line in pout.splitlines() if line.startswith(":::::: {#thm-ok"))
            self.assertEqual(mdscan.parse_attrs(first[len(":::::: {"):-1]).kv["tr-title"], self.TITLE,
                             "Pandoc reads the Markdown itself")
            self.assertIn(f"| {self.TITLE} |", ledger.ledger_markdown(m, make_lock()), "the ledger is Markdown too")

    def test_summary_titles_are_markdown(self):
        from tbook import html

        with Repo() as repo:
            write(repo.edition.summary, SUMMARY.replace("- [第一章](ch01.md)", r"- [C\*-代数 与 snake\_case $\{x\}$](ch01.md)"))
            m = model.load_edition(repo.edition)
            ch = m.summary.chapters[1]
            self.assertEqual(ch.title, r"C*-代数 与 snake_case $\{x\}$")
            self.assertEqual(ch.title_md, r"C\*-代数 与 snake\_case $\{x\}$")
            app = m.summary.chapters[-1]
            self.assertEqual((app.title, app.title_md), ("附录 A：$\\varphi$-边界 [x] a\\b", "附录 A：$\\varphi$-边界 \\[x\\] a\\\\b"))
            staged = html.summary_markdown(m, {c.path for c in m.summary.chapters}, "账本")
            line = next(x for x in staged.splitlines() if "ch01.md" in x)
            text = line[line.index("[") + 1:line.rindex("](")]
            # mdBook (CommonMark, no math) undoes every escape of ASCII punctuation in a SUMMARY title
            self.assertEqual(re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", text), ch.title)
            for plain in (app.title, "a [b] c\\d `e` <f> & *g* $h$"):
                self.assertEqual(re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", html._escape_title(plain)), plain)

    def test_pandoc_heading_from_summary_keeps_markdown(self):
        from tbook import pandoc

        with Repo() as repo:
            write(repo.edition.summary, SUMMARY.replace("[附录 A：$\\varphi$-边界 \\[x\\] a\\\\b]",
                                                        r"[附录 A：C\*-代数 \$5 $\{x\}$]"))
            write(repo.edition.dir / "appendix" / "app-a.md", "没有标题的附录。\n")
            with tempfile.TemporaryDirectory() as tmp:
                st = pandoc.stage(config.load_site(), repo.book, repo.edition, None, make_lock(), out_dir=Path(tmp))
                book_md = st.book_md.read_text(encoding="utf-8")
            self.assertRegex(book_md, r"(?m)^# \[\]\{#ch-appendix-app-a [^\n]+\.tr-heading-meta\} "
                             + re.escape(r"附录 A：C\*-代数 \$5 $\{x\}$"))


# --------------------------------------------------------------------------- re-review 6: lean: link forms


class LeanLinkFormTests(unittest.TestCase):
    """Re-review 6: ``lean:`` GIDs in reference definitions and ``<lean:…>`` destinations were rendered
    but never checked or pinned; an unresolved definition shipped a dead ``lean:`` href."""

    def text(self) -> str:
        return (f"# 第一章\n\n::: {{.theorem #thm-ok lean=\"{GID_OK}\"}}\n陈述。\n:::\n\n"
                f"见 [该定理][lt]、[另一个](<lean:{GID_MISSING}>)、[第三](lean:{GID_DEF} \"Lean\")、[缺失][gone]。\n\n"
                f"[lt]: lean:{GID_OK}\n[gone]: <lean:{GID_MISSING}>\n"
                f"`[code](lean:not/a.gid)` <!-- [c](lean:not/b.gid) -->\n")

    def test_lean_link_gids(self):
        self.assertEqual(mdscan.lean_link_gids(f"[a](lean:{GID_OK}) [b](<lean:{GID_DEF}>) ![c](lean:X/Y.z \"t\") "
                                               "`[d](lean:X/Y.code)` <!-- [e](lean:X/Y.comment) -->"),
                         [GID_OK, GID_DEF, "X/Y.z"])
        self.assertEqual(mdscan.lean_link_gids(f"[lt]: lean:{GID_OK}"), [GID_OK])
        self.assertEqual(mdscan.lean_link_gids(f"  [lt]: <lean:{GID_OK}> 'Lean'"), [GID_OK])
        self.assertEqual(mdscan.lean_link_gids(f"[^lt]: lean:{GID_OK}"), [])

    def test_model_collects_every_form(self):
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", self.text())
            m = model.load_edition(repo.edition)
            doc = m.chapters[1]
            self.assertEqual(doc.lean_links, [(7, GID_MISSING), (7, GID_DEF), (9, GID_OK), (10, GID_MISSING)])
            self.assertEqual({g for _, _, g, env in m.cited_gids() if env is None}, {GID_OK, GID_DEF, GID_MISSING})

    def test_render_never_writes_a_lean_url(self):
        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", self.text())
            repo.model = model.load_edition(repo.edition)
            for target in ("mdbook", "pandoc"):
                out, _ = repo.render("ch01.md", target=target)
                self.assertIn(f"[lt]: {SOURCE_OK}", out)
                self.assertIn("[gone]: #", out, "an unresolved definition gets no lean: URL")
                self.assertIn(f"、另一个、[第三]({SOURCE_DEF} \"Lean\")、", out)
                self.assertNotIn("](lean:", out.replace("`[code](lean:not/a.gid)`", "").replace(
                    "<!-- [c](lean:not/b.gid) -->", ""))
                self.assertNotIn(": lean:", out)


# --------------------------------------------------------------------------- re-review 9: HTML comments


class HtmlCommentTests(unittest.TestCase):
    """Re-review 9: links and references inside HTML comments, which no target shows, were checked
    (missing-file warnings, unknown-reference errors) and rewritten."""

    TEXT = textwrap.dedent(f"""\
        # 第一章

        ::: {{.theorem #thm-ok lean="{GID_OK}"}}
        陈述。
        :::

        <!--
        ![图 3](../assets/fig3.svg) [@todo]
        ::: {{.theorem #thm-hidden}}
        :::
        -->
        正文 <!-- ![图 4](../assets/fig4.svg) [@todo2] --> ![图](../assets/fig.svg) [@thm-ok]
        `<!--` 不是注释 [@thm-ok] -->
        """)

    def test_scanner(self):
        blocks = mdscan.parse_blocks(self.TEXT)
        comments = [b for b in blocks if isinstance(b, mdscan.Comment)]
        self.assertEqual([(c.start, c.lines[0], c.lines[-1]) for c in comments], [(7, "<!--", "-->")])
        self.assertNotIn("thm-hidden", [d.attrs.id for d in mdscan.walk(blocks) if isinstance(d, mdscan.Div)])
        self.assertFalse(any("fig3" in line for _, line in mdscan.iter_text_lines(blocks)))
        line = "a <!-- [@x] --> [@y] `<!--` [@z] -->"
        self.assertEqual([m.group("id") for m in mdscan.find_outside_code(mdscan.REF_RE, line)], ["y", "z"])
        self.assertEqual(mdscan.sub_outside_code(mdscan.REF_RE, lambda m: "R", line), "a <!-- [@x] --> R `<!--` R -->")
        issues: list[mdscan.ScanIssue] = []
        mdscan.parse_blocks("x\n\n<!-- todo\n[@a]\n", issues)
        self.assertEqual([(i.line, "never closed" in i.message) for i in issues], [(3, True)])

    def test_pandoc_stager_masks_the_same_lines(self):
        from tbook import pandoc

        lines = self.TEXT.split("\n")
        hidden = {i + 1 for i, masked in enumerate(pandoc._code_mask(lines)) if masked}
        self.assertEqual(hidden, set(range(7, 12)))
        mask = mdscan.fenced_code_lines(["<!--", "```", "-->", "x", "```"])
        self.assertEqual(mask, [False, False, False, False, True], "a fence inside a comment is not one")

    def test_model_check_and_render_skip_comments(self):
        from tbook import check

        with Repo() as repo:
            write(repo.edition.dir / "ch01.md", self.TEXT)
            m = model.load_edition(repo.edition)
            self.assertEqual([i.format() for i in m.issues], [])
            doc = m.chapters[1]
            self.assertEqual([r for _, r in doc.refs], ["thm-ok", "thm-ok"])
            self.assertNotIn("thm-hidden", m.envs)
            issues: list[model.Issue] = []
            check.check_links(m, config.load_site(), issues)
            self.assertEqual([i.format() for i in issues], [])
            repo.model = m
            out, ctx = repo.render("ch01.md")
            self.assertIn("<!--\n![图 3](../assets/fig3.svg) [@todo]\n::: {.theorem #thm-hidden}\n:::\n-->", out)
            self.assertIn("正文 <!-- ![图 4](../assets/fig4.svg) [@todo2] --> ![图](_book/assets/fig.svg) [定理1.1](#thm-ok)",
                          out)
            self.assertEqual(ctx.book_files, {repo.assets / "fig.svg"})
            self.assertEqual(ctx.issues, [])
            with tempfile.TemporaryDirectory() as tmp:
                warnings: list[str] = []
                linker = pandoc_linker(tmp, repo, warnings)
                linker.rewrite_line("正文 <!-- ![图 4](fig4.svg) --> 后文", "ch01.md")
                self.assertEqual(warnings, [])


def pandoc_linker(tmp: str, repo: Repo, warnings: list[str]):
    from tbook import pandoc

    return pandoc._Linker(Path(tmp), repo.edition, {"ch01.md": "ch-01"}, warnings, set(), online="")


if __name__ == "__main__":
    unittest.main()
