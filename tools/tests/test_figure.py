"""Tests of static figures: the drawing kit (``tbook.figkit``), generation, the three renderings and
the checks (``tbook.figure``, ``tbook.check``), and ``./tbook fig``.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_figure.py'

Every test runs in a throwaway books repository (``test_newbook.Repo``); the palette is this
repository's ``theme/tokens.json`` and the starter script its ``templates/figure/figure.py``.
"""

from __future__ import annotations

import json
import re
import time
import unittest
from pathlib import Path

from test_newbook import Repo, write

from tbook import check, config, figkit, figure, model, paths, render

SCRIPT = '''\
"""A test figure."""
SIZE = (300, 200)
ALT = {"zh": "一条线与一个点。", "en": "A line and a dot."}


def draw(fig):
    fig.line(20, 100, 280, 100, "line", 2)
    fig.dot(150, 100, 4, "now")
    fig.text(150, 60, fig.t("影子", "shadow"), anchor="middle")
'''

PANELS = '''\
SIZE = (420, 160)
WRAP = True
ALT = {"zh": "两栏。", "en": "Two panels."}


def draw(fig):
    left, right = fig.row([200, 200], 160)
    left.circle(100, 80, 40, color="cyan")
    right.rect(60, 40, 80, 80, color="magenta")
    right.text(100, 150, fig.t("右", "right"), anchor="middle")
'''


def chapter(repo: Repo, lang: str, text: str) -> None:
    write(repo.root / "books" / "demo" / lang / "ch01.md", text)


def demo(repo: Repo, scripts: dict[str, str] | None = None) -> config.Book:
    book = repo.book()
    for name, text in (scripts or {"line": SCRIPT}).items():
        p = repo.root / "books" / "demo" / "figures" / f"{name}.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return book


class KitTests(unittest.TestCase):
    def fig(self, **kw) -> figkit.Figure:
        return figkit.Figure("t", "en", 300, 200, alt="alt", **kw)

    def test_coordinate_rounding_ignores_libm_noise(self):
        for coordinate in (118.325, 54.075, -118.325, -54.075):
            with self.subTest(coordinate=coordinate):
                self.assertEqual(figkit.num(coordinate - 1e-12),
                                 figkit.num(coordinate + 1e-12))
        self.assertEqual(figkit.num(-1e-12), "0")
        self.assertNotEqual(figkit.num(118.32), figkit.num(118.33))

    def test_arc_output_ignores_libm_noise_at_segment_boundary(self):
        def make(start, end):
            f = self.fig()
            f.arc(150, 100, 60, start, end)
            return f.svg()

        self.assertEqual(make(30 - 1e-12, 90 + 1e-12),
                         make(30 + 1e-12, 90 - 1e-12))
        self.assertNotEqual(make(30, 90), make(30, 94))

    def test_output_is_deterministic_and_paints_by_role(self):
        def make() -> str:
            f = self.fig()
            f.arrow(10, 10, 200.123456, 90.5, "now")
            f.polygon([(10, 10), (60, 10), (60, 50)], "area")
            f.text(20, 150, "*a*·*b* = cos^{2} θ_{i}", color="lean")
            return f.svg()

        svg = make()
        self.assertEqual(svg, make())
        self.assertIn('class="ts-amber"', svg)  # now → amber
        self.assertIn('class="tf-magenta"', svg)  # area → magenta
        self.assertIn('class="tf-ok"', svg)  # lean → the green role
        self.assertNotRegex(svg.split("</style>")[1], r"#[0-9a-fA-F]{6}", "no colour value outside the style sheet")
        self.assertNotIn("\n\n", svg, "no blank line: the HTML edition inlines the figure in an HTML block")
        self.assertIn('d="M200.12 90.5 L', svg, "coordinates are rounded to two decimals")

    def test_the_standard_is_enforced(self):
        f = self.fig()
        with self.assertRaisesRegex(figkit.FigureError, "font size 10"):
            f.text(10, 20, "small", size=10)
        with self.assertRaisesRegex(figkit.FigureError, "stroke width 0.5"):
            f.line(0, 0, 10, 10, "ink", 0.5)
        with self.assertRaisesRegex(figkit.FigureError, "unknown colour role"):
            f.line(0, 0, 10, 10, "#ff0000")
        with self.assertRaisesRegex(figkit.FigureError, "runs past the right edge"):
            f.text(250, 20, "a label that cannot fit there")
        with self.assertRaisesRegex(figkit.FigureError, "runs past the left edge"):
            f.text(20, 20, "a label that cannot fit there", anchor="end")
        f.cross(40, 40, 6, "open")
        self.assertEqual(f.svg().count('class="ts-warn"'), 2, "a cross is two strokes in the role's colour")
        with self.assertRaisesRegex(figkit.FigureError, "exceeds"):
            figkit.Figure("wide", "en", 900, 100, alt="x")

    def test_markup(self):
        self.assertEqual(figkit.plain("*a*·**b** = x_{i}^{2} \\*"), "a·b = xi2 *")
        f = self.fig()
        f.text(10, 20, "x_{i} + 1")
        svg = f.svg()
        self.assertIn('<tspan dy="0.28em" font-size="72%">i</tspan><tspan dy="-0.28em"> + 1</tspan>', svg)
        f = self.fig()
        f.text(10, 20, "a < b & $c")
        self.assertIn("a &lt; b &amp; &#36;c", f.svg())

    def test_wrapping_panels_hold_everything(self):
        f = self.fig(wrap=True)
        f.row([140, 140], 200)
        f.line(0, 0, 10, 10)
        with self.assertRaisesRegex(figkit.FigureError, "everything is drawn on panels"):
            f.svg()

    def test_sphere_orientation(self):
        sp = self.fig().sphere(150, 100, 80)
        x, y, depth = sp.proj((0, 0, 1))
        self.assertAlmostEqual(x, 150)
        self.assertLess(y, 100, "+z is up")
        self.assertGreater(sp.proj((1, 0, 0))[2], 0, "+x faces the reader")
        self.assertGreater(sp.proj((0, 1, 0))[0], 150, "+y points right")
        r = figkit.rotate((1, 0, 0), (0, 0, 1), 90)
        self.assertAlmostEqual(r[1], 1)
        self.assertAlmostEqual(figkit.dot3(figkit.slerp((1, 0, 0), (0, 1, 0), 0.5), (1, 0, 0)), 2 ** -0.5)


class GenerationTests(unittest.TestCase):
    def test_build_writes_one_file_per_edition_and_check_finds_stale_ones(self):
        with Repo() as repo:
            book = demo(repo, {"line": SCRIPT, "_helper": "X = 1\n"})
            self.assertEqual(figure.names(book), ["line"], "a file that starts with an underscore is a helper")
            changed, errors = figure.build(book)
            self.assertEqual(errors, [])
            self.assertEqual(sorted(p.name for p in changed), ["line.en.svg", "line.zh.svg"])
            zh = figure.out_path(book, "line", "zh").read_text(encoding="utf-8")
            en = figure.out_path(book, "line", "en").read_text(encoding="utf-8")
            self.assertIn(">影子<", zh)
            self.assertIn(">shadow<", en)
            self.assertIn('aria-label="A line and a dot."', en)
            self.assertEqual(figure.build(book, check=True), ([], []))
            self.assertEqual([i for i in figure.check(book) if i.severity == "error"], [])
            script = figure.script_path(book, "line")
            script.write_text(SCRIPT.replace("fig.dot(150", "fig.dot(160"), encoding="utf-8")
            stale, _ = figure.build(book, check=True)
            self.assertEqual(len(stale), 2)
            self.assertIn(">影子<", zh, "check=True writes nothing")
            messages = [i.message for i in figure.check(book) if i.severity == "error"]
            self.assertEqual(len(messages), 2)
            self.assertIn("is stale", messages[0])
            self.assertFalse(list((repo.root / "books").rglob("__pycache__")), "running a script leaves no bytecode")

    def test_slide_decks_keep_a_screen_palette_copy(self):
        with Repo() as repo:
            book = demo(repo)
            figure.build(book)
            canonical = figure.out_path(book, "line", "zh").read_text(encoding="utf-8")
            self.assertIn("prefers-color-scheme:dark", canonical)
            img = repo.root / "books/demo/slides/overview/img"
            write(img / "line.zh.svg", canonical)  # a raw copy: paper palette in a light colour scheme
            write(img / "photo.zh.svg", "<svg/>\n")  # not a figure: left alone
            stale, errors = figure.build(book, check=True)
            self.assertEqual((errors, [p.name for p in stale]), ([], ["line.zh.svg"]))
            messages = [i.message for i in figure.check(book) if i.severity == "error"]
            self.assertEqual(len(messages), 1)
            self.assertIn("screen-palette copy", messages[0])
            changed, _ = figure.build(book)
            self.assertEqual([p.name for p in changed], ["line.zh.svg"])
            copy = (img / "line.zh.svg").read_text(encoding="utf-8")
            self.assertEqual(copy, figure.materialize(canonical, "screen"))
            self.assertNotIn("prefers-color-scheme", copy)
            self.assertEqual((img / "photo.zh.svg").read_text(encoding="utf-8"), "<svg/>\n")
            self.assertFalse((img / "line.en.svg").exists(), "only the copies a deck already has are kept")
            self.assertEqual(figure.build(book, check=True), ([], []))
            script = figure.script_path(book, "line")
            script.write_text(SCRIPT.replace("fig.dot(150", "fig.dot(160"), encoding="utf-8")
            stale, _ = figure.build(book, check=True)
            self.assertEqual(sorted(p.name for p in stale), ["line.en.svg", "line.zh.svg", "line.zh.svg"])
            figure.build(book)
            self.assertIn('cx="160"', (img / "line.zh.svg").read_text(encoding="utf-8"), "the copy follows the script")

    def test_scripts_may_share_a_helper(self):
        with Repo() as repo:
            book = demo(repo, {"_common": "def mark(fig):\n    fig.dot(10, 10, 4, 'cyan')\n",
                               "one": "import _common\nSIZE = (100, 100)\nALT = 'x'\n\n\ndef draw(fig):\n    _common.mark(fig)\n"})
            self.assertEqual(figure.build(book)[1], [])
            self.assertIn('class="tf-cyan"', figure.out_path(book, "one", "zh").read_text(encoding="utf-8"))

    def test_script_errors_are_reported_with_the_file(self):
        with Repo() as repo:
            book = demo(repo, {"bad": "SIZE = (100, 100)\nALT = 'x'\n\n\ndef draw(fig):\n    fig.text(5, 20, 'tiny', size=8)\n",
                               "noalt": "SIZE = (100, 100)\n\n\ndef draw(fig):\n    pass\n",
                               "boom": "SIZE = (100, 100)\nALT = 'x'\n\n\ndef draw(fig):\n    1 / 0\n"})
            _changed, errors = figure.build(book)
            text = "\n".join(errors)
            self.assertIn("books/demo/figures/bad.py (zh): font size 8", text)
            self.assertIn("books/demo/figures/noalt.py: ALT has no text", text)
            self.assertIn("books/demo/figures/boom.py (zh): ZeroDivisionError", text)
            self.assertTrue(all(i.severity == "error" for i in figure.check(book)))

    def test_outputs_without_a_script_are_reported(self):
        with Repo() as repo:
            book = demo(repo)
            figure.build(book)
            write(repo.root / "books/demo/figures/old.zh.svg", "<svg/>\n")
            warnings = [i for i in figure.check(book) if i.severity == "warning"]
            self.assertEqual([i.path.name for i in warnings], ["old.zh.svg"])


class RenderingTests(unittest.TestCase):
    def test_pdf_labels_keep_combining_marks_with_a_latin_font(self):
        f = figkit.Figure("marks", "zh", 300, 100, alt="labels")
        f.text(20, 40, "转轴 n̂，旋子 R̃", size=16)
        f.text(20, 70, "axis *v* and n̂", size=16)
        svg = f.svg()
        from xml.etree import ElementTree as ET
        for palette in ("paper", "screen"):
            pdf = figure.pdf_svg(svg, palette)
            labels = [el for el in ET.fromstring(pdf).iter() if el.tag.endswith("}text")
                      and "n̂" in "".join(el.itertext())]
            self.assertTrue(labels[0].attrib["font-family"].startswith("'Libertinus Serif',"))
            self.assertTrue(all(el.attrib.get("font-family", "").startswith("'Libertinus Serif',")
                                for el in labels))
            self.assertEqual("".join(ET.fromstring(pdf).itertext()),
                             "".join(ET.fromstring(figure.materialize(svg, palette)).itertext()))
        self.assertNotIn("New Computer Modern", svg)

    def test_palettes(self):
        tokens = json.loads((paths.THEME / "tokens.json").read_text(encoding="utf-8"))
        f = figkit.Figure("t", "en", 100, 100, alt="alt")
        f.line(0, 0, 10, 10, "cyan")
        svg = f.svg()
        self.assertIn("@media (prefers-color-scheme:dark)", svg)
        paper = figure.materialize(svg, "paper")
        screen = figure.materialize(svg, "screen", ground=True)
        self.assertIn(f".ts-cyan{{stroke:{tokens['paper']['cyan']}}}", paper)
        self.assertNotIn(tokens["screen"]["cyan"], paper)
        self.assertNotIn("@media", paper)
        self.assertIn(f".ts-cyan{{stroke:{tokens['screen']['cyan']}}}", screen)
        self.assertIn(f'<rect width="100%" height="100%" fill="{tokens["screen"]["void"]}"/>', screen)
        with self.assertRaisesRegex(figkit.FigureError, "not a canonical figure"):
            figure.materialize("<svg/>", "paper")
        css = figure.mdbook_css()
        for name, token in figkit.ROLES.items():
            self.assertIn(f".tr-fig .ts-{name}{{stroke:var(--tr-{token})}}", css)
            self.assertIn(token, tokens["screen"], f"role {name} names a token of both palettes")
            self.assertIn(token, tokens["paper"])
        for alias, name in figkit.ALIASES.items():
            self.assertIn(name, figkit.ROLES, alias)

    def test_inline_html(self):
        with Repo() as repo:
            book = demo(repo, {"line": SCRIPT, "two": PANELS})
            figure.build(book)
            one = figure.inline_html(figure.out_path(book, "line", "en").read_text(encoding="utf-8"))
            self.assertNotIn("<style", one)
            self.assertNotIn("xmlns", one)
            self.assertNotIn("\n\n", one)
            self.assertIn('<svg class="tr-fig" viewBox="0 0 300 200" style="max-width:300px"', one)
            self.assertIn('role="img" aria-label="A line and a dot."', one)
            self.assertEqual(one.count("<svg"), 1)
            two = figure.inline_html(figure.out_path(book, "two", "en").read_text(encoding="utf-8"))
            self.assertIn('<div class="tr-fig-row tr-fig-wrap" style="max-width:420px" role="img" aria-label="Two panels.">', two)
            self.assertEqual(two.count('<svg class="tr-fig tr-fig-part" viewBox="0 0 200 160" style="flex-basis:200px"'), 2)
            self.assertEqual(two.count("</svg>"), 2)
            grid = PANELS.replace("left, right = fig.row([200, 200], 160)",
                                                "left, right = fig.row([200, 200], 80)\n    more = fig.row([200, 200], 80, y=80)") \
                .replace("left.circle(100, 80, 40", "left.circle(100, 40, 30").replace("right.rect(60, 40, 80, 80", "right.rect(60, 10, 80, 60") \
                .replace("right.text(100, 150,", "more[1].line(20, 40, 180, 40, color=\"cyan\")\n    more[0].text(100, 60,")
            (repo.root / "books/demo/figures/grid.py").write_text(grid, encoding="utf-8")
            figure.build(book, ["grid"])
            rows = figure.inline_html(figure.out_path(book, "grid", "en").read_text(encoding="utf-8"))
            self.assertTrue(rows.startswith('<div class="tr-fig-rows" style="max-width:420px" role="img" aria-label="Two panels.">'), rows[:120])
            self.assertEqual(rows.count('<div class="tr-fig-row tr-fig-wrap">'), 2, "one flex row per row of panels")
            self.assertEqual(rows.count('class="tr-fig tr-fig-part"'), 4)

    def ctx(self, book: config.Book, lang: str, target: str) -> tuple[render.RenderContext, model.EditionModel]:
        edition = next(e for e in book.editions if e.lang == lang)
        m = model.load_edition(edition)
        return render.RenderContext(config.load_site(), book, edition, m, None, target=target), m

    def test_chapter_markdown_for_both_targets(self):
        with Repo() as repo:
            book = demo(repo)
            figure.build(book)
            for lang, cap in (("zh", "**影子。** 青色的线。"), ("en", "**The shadow.** The cyan line.")):
                chapter(repo, lang, f'# One\n\nBefore.\n\n::: {{.figure src="line"}}\n{cap}\n:::\n\nAfter.\n')
            ctx, m = self.ctx(book, "en", "mdbook")
            html_md = render.chapter_markdown(m.chapters[0], ctx)
            self.assertEqual(ctx.issues, [])
            self.assertIn('<figure class="tr-media tr-figure" data-figure="line">\n<div class="tr-fig-row">\n<svg class="tr-fig"', html_md)
            self.assertIn('<figcaption class="tr-media-caption">\n\n**The shadow.** The cyan line.\n\n</figcaption>\n</figure>', html_md)
            block = html_md[html_md.index("<figure"):html_md.index("<figcaption")]
            self.assertNotIn("\n\n", block, "a blank line would end the HTML block and show the drawing as text")
            ctx, m = self.ctx(book, "zh", "pandoc")
            md = render.chapter_markdown(m.chapters[0], ctx)
            self.assertEqual(ctx.issues, [])
            self.assertIn("::: {.tr-media .tr-figure}\n![一条线与一个点。](_book/figures/line.zh.svg){width=39% tr-fig=1}\\ \n\n"
                          "**影子。** 青色的线。\n\n:::", md)
            self.assertEqual(sorted(ctx.book_texts), ["figures/line.zh.print.svg", "figures/line.zh.screen.svg",
                                                      "figures/line.zh.svg"])
            self.assertIn('<rect width="100%" height="100%"', ctx.book_texts["figures/line.zh.svg"], "the EPUB file is opaque")
            self.assertNotIn("<rect width=\"100%\"", ctx.book_texts["figures/line.zh.print.svg"])

    def test_a_missing_figure_is_an_issue_not_a_crash(self):
        with Repo() as repo:
            book = demo(repo)
            chapter(repo, "en", '# One\n\n::: {.figure src="nope"}\nCaption.\n:::\n')
            ctx, m = self.ctx(book, "en", "mdbook")
            out = render.chapter_markdown(m.chapters[0], ctx)
            self.assertIn("tr-fig-missing", out)
            self.assertRegex(ctx.issues[0], r"no figure books/demo/figures/nope\.py")
            self.assertRegex(figure.check_ref(book, "line") or "", r"not drawn: .*line\.zh\.svg")
            self.assertRegex(figure.check_ref(book, "Bad Name") or "", "not a figure name")


class CheckTests(unittest.TestCase):
    def issues(self, book: config.Book) -> list[model.Issue]:
        out: list[model.Issue] = []
        models = model.load_book_models(book)
        for m in models.values():
            out.extend(m.issues)
            check.check_env_policy(m, out)
            check.check_captions(m, out)
        check.check_parity(book, models, out)
        check.check_image_parity(book, models, out)
        check.check_unused_figures(book, models, out)
        check.check_unused_assets(book, models, config.load_site(), out)
        return out

    def test_captions(self):
        self.assertIsNone(figure.caption_problem("**The shadow.** The cyan line is $\\cos\\theta$."))
        for bad in ("", "  \n", "——", "图 13", "图13：", "Figure 2.1", "Fig. 3:", "12"):
            self.assertIsNotNone(figure.caption_problem(bad), bad)
        self.assertIsNone(figure.caption_problem("图 13 的左半边是一条线"))
        self.assertIsNone(figure.caption_problem("fig"), "a word is a caption, however short; only a bare number is not")
        self.assertIsNone(figure.caption_problem("3 qubits"))
        self.assertIsNotNone(figure.caption_problem("（图 2-3）"))
        start = time.perf_counter()
        self.assertIsNone(figure.caption_problem("0-" + " -" * 20000 + "x"), "no backtracking on a long run of dashes")
        self.assertLess(time.perf_counter() - start, 1.0)
        with Repo() as repo:
            book = demo(repo)
            figure.build(book)
            write(repo.root / "books/demo/assets/a.svg", "<svg/>\n")
            write(repo.root / "books/demo/assets/b.png", "x")
            chapter(repo, "zh", '# One\n\n::: {.figure src="line"}\n:::\n\n![图 2](../assets/a.svg)\n\n![一张说清楚的图](../assets/a.svg)\n')
            chapter(repo, "en", '# One\n\n::: {.figure src="line"}\nFigure 1\n:::\n\n![](../assets/a.svg)\n\n![A figure that says what it shows](../assets/a.svg)\n')
            found = self.issues(book)
            errors = sorted(i.message for i in found if i.severity == "error")
            self.assertEqual(len(errors), 4, errors)
            self.assertTrue(any("figure line has no caption" in e for e in errors))
            self.assertTrue(any('figure line has a placeholder caption ("Figure 1")' in e for e in errors))
            self.assertTrue(any('image ../assets/a.svg has a placeholder caption ("图 2")' in e for e in errors))
            self.assertTrue(any("image ../assets/a.svg has no caption" in e for e in errors))
            unused = [i for i in found if i.severity == "warning" and "uses this file" in i.message]
            self.assertEqual([i.path.name for i in unused], ["b.png"])

    def test_editions_cite_the_same_figures_in_the_same_order(self):
        with Repo() as repo:
            book = demo(repo, {"line": SCRIPT, "two": PANELS})
            figure.build(book)
            chapter(repo, "zh", '# One\n\n::: {.figure src="line"}\n一条线。\n:::\n\n::: {.figure src="two"}\n两栏。\n:::\n')
            chapter(repo, "en", '# One\n\n::: {.figure src="two"}\nTwo panels.\n:::\n\n::: {.figure src="line"}\nA line.\n:::\n')
            errors = [i.message for i in self.issues(book) if i.severity == "error"]
            self.assertTrue(any("differs between editions" in e for e in errors), errors)

    def test_a_figure_no_chapter_cites_is_reported(self):
        with Repo() as repo:
            book = demo(repo, {"line": SCRIPT, "two": PANELS})
            figure.build(book)
            for lang in ("zh", "en"):
                chapter(repo, lang, '# One\n\n::: {.figure src="line"}\nA line and a dot on it.\n:::\n')
            found = self.issues(book)
            self.assertEqual([i for i in found if i.severity == "error"], [])
            self.assertEqual([(i.path.name, i.message.split(";")[0]) for i in found if i.severity == "warning"],
                             [("two.py", "no chapter cites this figure")])

    def test_editions_show_the_same_number_of_images(self):
        with Repo() as repo:
            book = demo(repo)
            write(repo.root / "books/demo/assets/a.png", "x")
            chapter(repo, "zh", "# One\n\n![一张图](../assets/a.png)\n\n![另一张图](../assets/a.png)\n")
            chapter(repo, "en", "# One\n\n![A picture](../assets/a.png)\n")
            found = self.issues(book)
            self.assertEqual([i for i in found if i.severity == "error"], [])
            warnings = [i.message for i in found if i.severity == "warning" and "image(s)" in i.message]
            self.assertEqual(warnings, ["the en edition shows 1 image(s) in this chapter, the zh edition 2: editions show the "
                                        "same pictures at the same places"])

    def test_a_reference_cannot_target_a_figure(self):
        self.assertIn("figure", model.MEDIA)
        self.assertEqual(model.status_of("figure"), "media")


HAND_DRAWN = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><rect width="200" height="100" fill="#0a0e14"/>'
              '<text x="10" y="50" fill="#00e5ff" font-size="8">label</text></svg>\n')
STYLED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><style>.a{fill:#000}'
          '@media (prefers-color-scheme:dark){.a{fill:#fff}}</style><text class="a" x="10" y="50">label</text></svg>\n')
WIDE = '''\
SIZE = (716, 120)
ALT = {"zh": "一行字。", "en": "A line of text."}


def draw(fig):
    fig.text(20, 60, fig.t("小字", "small"), size=12)
'''
WIDE_PANELS = '''\
SIZE = (716, 120)
WRAP = True
ALT = {"zh": "两栏字。", "en": "Two panels of text."}


def draw(fig):
    for p in fig.row([350, 350], 120):
        p.text(20, 60, fig.t("小字", "small"), size=12)
'''


def media_chapter(*blocks: str) -> str:
    return "# One\n\n" + "\n\n".join(blocks) + "\n"


class StandardTests(unittest.TestCase):
    """The checks that keep pictures to the standard: hand-drawn SVG images, one image for every language,
    labels a phone can show, and media blocks stacked without prose."""

    def issues(self, book: config.Book) -> list[model.Issue]:
        out: list[model.Issue] = []
        models = model.load_book_models(book)
        for m in models.values():
            check.check_media_runs(m, out)
        check.check_drawn_images(book, models, out)
        return out

    def test_hand_drawn_svg_in_assets(self):
        self.assertTrue(check.svg_is_hand_drawn(HAND_DRAWN))
        self.assertFalse(check.svg_is_hand_drawn(STYLED), "it follows the reader's colour scheme")
        with Repo() as repo:
            book = demo(repo)
            figure.build(book)
            self.assertFalse(check.svg_is_hand_drawn(figure.out_path(book, "line", "en").read_text(encoding="utf-8")),
                             "a generated figure paints by role classes")
            self.assertFalse(check.svg_is_hand_drawn('<svg><animate attributeName="x" fill="freeze"/></svg>'))
            write(repo.root / "books/demo/assets/drawn.svg", HAND_DRAWN)
            write(repo.root / "books/demo/assets/photo.png", "x")
            write(repo.root / "books/demo/assets/styled.zh.svg", STYLED)
            chapter(repo, "zh", "# One\n\n![一张手绘图](../assets/drawn.svg)\n\n![照片](../assets/photo.png)\n\n"
                                "![随主题的图](../assets/styled.zh.svg)\n")
            chapter(repo, "en", "# One\n\n![A drawing](../assets/drawn.svg)\n\n![A photograph](../assets/photo.png)\n")
            found = [i for i in self.issues(book) if "hand-drawn" in i.message]
            self.assertEqual([(i.path.parent.name, i.line) for i in found], [("zh", 3), ("en", 3)])
            self.assertIn("::: {.figure", found[0].message)
            self.assertTrue(all(i.severity == "warning" for i in found))

    def test_an_svg_with_text_shared_by_two_editions(self):
        with Repo() as repo:
            book = demo(repo)
            write(repo.root / "books/demo/assets/shared.svg", STYLED)
            write(repo.root / "books/demo/assets/plain.svg", '<svg viewBox="0 0 10 10"><circle class="tf-cyan" r="4"/></svg>\n')
            write(repo.root / "books/demo/assets/own.zh.svg", STYLED)
            write(repo.root / "books/demo/assets/own.en.svg", STYLED)
            chapter(repo, "zh", "# One\n\n![带字的图](../assets/shared.svg)\n\n![无字的图](../assets/plain.svg)\n\n"
                                "![各自的图](../assets/own.zh.svg)\n")
            chapter(repo, "en", "# One\n\n![With text](../assets/shared.svg)\n\n![No text](../assets/plain.svg)\n\n"
                                "![Its own](../assets/own.en.svg)\n")
            found = self.issues(book)
            self.assertEqual([(i.severity, i.path.parent.name, i.line, i.message.split(" has text")[0]) for i in found],
                             [("warning", "en", 3, "books/demo/assets/shared.svg")])
            self.assertIn("every language its own labels", found[0].message)

    def test_media_blocks_in_a_row(self):
        fig = '::: {.figure src="line"}\nA line.\n:::'
        with Repo() as repo:
            book = demo(repo)
            figure.build(book)
            chapter(repo, "zh", media_chapter(fig, fig, "<!-- note -->", fig, fig, "Some prose.", fig, fig))
            chapter(repo, "en", media_chapter(fig, fig, "Prose between.", fig, fig, "More prose.", fig))
            found = self.issues(book)
            self.assertEqual([(i.path.parent.name, i.line) for i in found], [("zh", 13)],
                             "the third block of a run of four; a comment is no prose, two in a row are fine")
            self.assertIn("4 media blocks in a row (figure → figure → figure → figure, from line 3)", found[0].message)
            self.assertIn("line 13, line 17", found[0].message)

    def test_labels_on_a_phone(self):
        with Repo() as repo:
            book = demo(repo, {"wide": WIDE, "panels": WIDE_PANELS, "line": SCRIPT})
            figure.build(book)
            wide = figure.phone_label(figure.out_path(book, "wide", "en").read_text(encoding="utf-8"))
            self.assertEqual((round(wide[0], 2), wide[1], wide[2]), (6.0, 12.0, 716.0), "12 px at 716 wide is 6 px at 358")
            panels = figure.phone_label(figure.out_path(book, "panels", "en").read_text(encoding="utf-8"))
            self.assertEqual((round(panels[0], 2), panels[2]), (12.0, 350.0), "panels stack: the widest panel decides")
            found = figure.check(book)
            self.assertEqual([(i.severity, i.path.name) for i in found], [("warning", "wide.py")])
            msg = found[0].message
            for part in ("6.0 px on a phone", "below 10 px", "width at most 429", "WRAP = True", "at least 20 px"):
                self.assertIn(part, msg)
            write(repo.root / "site.toml", (repo.root / "site.toml").read_text(encoding="utf-8") + '\n[figures]\nphone_labels = "error"\n')
            config.load_site.cache_clear()
            self.assertEqual([i.severity for i in figure.check(book)], ["error"])
            code, out, err = repo.run_cli("fig", "build")
            self.assertEqual(code, 1, "an error by site.toml fails the build")
            self.assertIn("fig: error: figure wide:", err)
            code, out, _err = repo.run_cli("fig", "list")
            self.assertEqual(code, 0)
            self.assertEqual(out.splitlines()[1:], ["demo/line    14.0 px", "demo/panels  12.0 px", "demo/wide    6.0 px  < 10"])
            write(repo.root / "site.toml", (repo.root / "site.toml").read_text(encoding="utf-8").replace('"error"', '"loud"'))
            config.load_site.cache_clear()
            self.assertEqual([(i.severity, i.path.name) for i in figure.check(book)], [("error", "site.toml")])


class CliTests(unittest.TestCase):
    def test_new_build_list(self):
        with Repo() as repo:
            repo.book()
            code, out, err = repo.run_cli("fig", "new", "demo", "ch01-shadow")
            self.assertEqual((code, err), (0, ""))
            script = repo.root / "books/demo/figures/ch01-shadow.py"
            self.assertEqual(script.read_text(encoding="utf-8"), figure.TEMPLATE.read_text(encoding="utf-8"))
            self.assertIn('::: {.figure src="ch01-shadow"}', out)
            code, _out, err = repo.run_cli("fig", "new", "demo", "ch01-shadow")
            self.assertEqual(code, 1)
            self.assertIn("already exists", err)
            code, _out, err = repo.run_cli("fig", "new", "demo", "Bad_Name")
            self.assertEqual(code, 1)
            code, out, _err = repo.run_cli("fig", "build", "--check")
            self.assertEqual(code, 1, "nothing generated yet")
            self.assertIn("stale books/demo/figures/ch01-shadow.zh.svg", out)
            code, out, _err = repo.run_cli("fig", "build")
            self.assertEqual(code, 0)
            self.assertIn("2 file(s) written", out)
            self.assertEqual(repo.run_cli("fig", "build", "--check")[0], 0)
            self.assertEqual(repo.run_cli("fig", "list")[1].splitlines()[1:], ["demo/ch01-shadow  10.4 px"])
            svg = (repo.root / "books/demo/figures/ch01-shadow.en.svg").read_text(encoding="utf-8")
            self.assertTrue(re.search(r">shadow cos θ<", svg), "the starter draws its English labels")

    def test_the_starter_meets_the_standard_in_both_languages(self):
        with Repo() as repo:
            book = repo.book()
            figure.scaffold(book, "starter")
            self.assertEqual(figure.build(book), ([figure.out_path(book, "starter", "zh"), figure.out_path(book, "starter", "en")], []))


if __name__ == "__main__":
    unittest.main()
