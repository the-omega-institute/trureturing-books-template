"""Check actual Typst layout positions for formulas and identifiers in narrow containers."""

from __future__ import annotations

import json
import re
import shutil
import statistics
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tbook import pandoc as tp
from tbook.model import load_edition
from test_pandoc import fixture_site, have_pandoc, have_typst, make_book


_SVG_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_SVG_TOKEN = re.compile(r"[A-Za-z]|" + _SVG_NUMBER)
_SVG_PARAM_COUNTS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4,
                     "Q": 4, "T": 2, "A": 7, "Z": 0}
_SVG_NS = "{http://www.w3.org/2000/svg}"
_SVG_HREF = "{http://www.w3.org/1999/xlink}href"


def _svg_path_points(d: str) -> list[tuple[float, float]]:
    """Collect path points from a Typst glyph outline without rasterizing it."""
    tokens = _SVG_TOKEN.findall(d)
    points = [(0.0, 0.0)]
    command: str | None = None
    x = y = 0.0
    i = 0
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        if command is None:
            break
        upper = command.upper()
        if upper == "Z":
            command = None
            continue
        count = _SVG_PARAM_COUNTS[upper]
        if i + count > len(tokens) or any(token.isalpha() for token in tokens[i:i + count]):
            command = None
            continue
        values = list(map(float, tokens[i:i + count]))
        i += count
        relative = command.islower()
        if upper in ("M", "L", "T"):
            nx, ny = values[-2:]
            x, y = nx + (x if relative else 0), ny + (y if relative else 0)
            points.append((x, y))
            if upper == "M":
                command = "l" if relative else "L"
        elif upper == "H":
            x = values[0] + (x if relative else 0)
            points.append((x, y))
        elif upper == "V":
            y = values[0] + (y if relative else 0)
            points.append((x, y))
        elif upper in ("C", "S", "Q"):
            for j in range(0, count, 2):
                nx, ny = values[j:j + 2]
                points.append((nx + (x if relative else 0), ny + (y if relative else 0)))
            x, y = points[-1]
        elif upper == "A":
            nx, ny = values[-2:]
            x, y = nx + (x if relative else 0), ny + (y if relative else 0)
            points.append((x, y))
    return points


def _svg_matrix_bounds(bounds: tuple[float, float, float, float], matrix: list[float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bounds
    a, b, c, d, e, f = matrix
    points = [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    transformed = [(a * x + b * y + e, c * x + d * y + f) for x, y in points]
    return (min(x for x, _ in transformed), min(y for _, y in transformed),
            max(x for x, _ in transformed), max(y for _, y in transformed))


def _svg_union(bounds: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (min(item[0] for item in bounds), min(item[1] for item in bounds),
            max(item[2] for item in bounds), max(item[3] for item in bounds))


def _svg_formula_groups(svg: bytes) -> list[dict[str, tuple[float, float, float, float]]]:
    """Read the two display-fraction groups and their actual outline bounds from Typst SVG."""
    root = ET.fromstring(svg)
    symbols = {symbol.attrib["id"]: next(iter(symbol))
               for symbol in root.iter(_SVG_NS + "symbol")}
    groups = []

    def walk(element: ET.Element) -> None:
        transform = element.attrib.get("transform", "")
        if (not transform or transform.startswith("translate(")) and len(element) <= 60:
            wrapper = list(map(float, re.findall(_SVG_NUMBER, transform)))
            while len(wrapper) < 2:
                wrapper.append(0.0)
            children: list[tuple[float, tuple[float, float, float, float]]] = []
            has_fraction_bar = False
            for child in element:
                if child.tag != _SVG_NS + "g":
                    if child.tag == _SVG_NS + "path" and child.attrib.get("stroke"):
                        has_fraction_bar = True
                    continue
                values = list(map(float, re.findall(_SVG_NUMBER, child.attrib.get("transform", ""))))
                if not child.attrib.get("transform", "").startswith("matrix(") or len(values) < 6:
                    continue
                use = next((node for node in child if node.tag == _SVG_NS + "use"), None)
                if use is None:
                    continue
                symbol = symbols.get(use.attrib.get(_SVG_HREF, "")[1:])
                if symbol is None:
                    continue
                points = _svg_path_points(symbol.attrib.get("d", ""))
                bounds = (min(x for x, _ in points), min(y for _, y in points),
                          max(x for x, _ in points), max(y for _, y in points))
                dx, dy = float(use.attrib.get("x", 0)), float(use.attrib.get("y", 0))
                bounds = (bounds[0] + dx, bounds[1] + dy, bounds[2] + dx, bounds[3] + dy)
                bounds = _svg_matrix_bounds(bounds, values)
                bounds = (bounds[0] + wrapper[0], bounds[1] + wrapper[1],
                          bounds[2] + wrapper[0], bounds[3] + wrapper[1])
                children.append((values[5], bounds))
            if has_fraction_bar and len(children) >= 20:
                baseline = statistics.median(value for value, _ in children)
                numerator = _svg_union([bounds for value, bounds in children if value < baseline - 2])
                denominator = _svg_union([bounds for value, bounds in children if value > baseline + 2])
                ink = _svg_union([bounds for _, bounds in children])
                groups.append({"numerator": numerator, "denominator": denominator, "ink": ink})
        for child in element:
            if child.tag != _SVG_NS + "defs":
                walk(child)

    walk(root)
    return groups


_INLINE_TARGET = {
    "zh": r'''#tr-env(kind: "example", status: "informal", label: "Example", number: "22.27", ref: "例22.27", title: [前五个零点在单位圆上的位置，以及离线的点偏出圆周多少], badge: "", badge-url: "", lean: (), id: "ex-cayley-unit-circle-zeros")[
#strong[离线的点。] 取 #[$s = 0.6 + 14 i$<tr-inline-tr-book-52>]：#[$#mark("first-before") class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 1.2, 0.36 + 196)) = - 1.0185 times 10^(- 3) #mark("first-after")$<tr-inline-tr-book-53>]#mark("punct-first")，#[$class("normal", bar.v) w class("normal", bar.v) = 0.999491$<tr-inline-tr-book-54>]。它的镜像 #[$1 - overline(s) = 0.4 + 14 i$<tr-inline-tr-book-55>]：#[$#mark("second-before") class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 0.8, 0.16 + 196)) = + 1.0196 times 10^(- 3) #mark("second-after")$<tr-inline-tr-book-56>]#mark("punct-second")，#[$class("normal", bar.v) w class("normal", bar.v) = 1.000510$<tr-inline-tr-book-57>]。
] <ex-cayley-unit-circle-zeros>
#block(width: 100pt, inset: (x: 10pt))[
  Nested #[$#mark("nested-start") "InterpretationContextTextReaderAdmissionBackgroundEvaluationGoalRuleConceptMeaning" #mark("nested-end")$<tr-inline-nested>]#mark("nested-after").
]
''',
    "en": r'''#tr-env(kind: "example", status: "informal", label: "Example", number: "22.27", ref: "Example 22.27", title: [Where the First Five Zeros Sit on the Unit Circle, and How Far an Off-Line Point Leaves It], badge: "", badge-url: "", lean: (), id: "ex-cayley-unit-circle-zeros")[
#strong[Off-line points.] Take #[$s = 0.6 + 14 i$<tr-inline-tr-book-52>]: #[$#mark("first-before") class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 1.2, 0.36 + 196)) = - 1.0185 times 10^(- 3) #mark("first-after")$<tr-inline-tr-book-53>]#mark("punct-first"), #[$class("normal", bar.v) w class("normal", bar.v) = 0.999491$<tr-inline-tr-book-54>]. Its mirror image #[$1 - overline(s) = 0.4 + 14 i$<tr-inline-tr-book-55>]: #[$#mark("second-before") class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 0.8, 0.16 + 196)) = + 1.0196 times 10^(- 3) #mark("second-after")$<tr-inline-tr-book-56>]#mark("punct-second"), #[$class("normal", bar.v) w class("normal", bar.v) = 1.000510$<tr-inline-tr-book-57>].
] <ex-cayley-unit-circle-zeros>
#block(width: 100pt, inset: (x: 10pt))[
  Nested #[$#mark("nested-start") "InterpretationContextTextReaderAdmissionBackgroundEvaluationGoalRuleConceptMeaning" #mark("nested-end")$<tr-inline-nested>]#mark("nested-after").
]
''',
}


def _inline_stress(width: int) -> str:
    return f'''#block(width: {width}pt)[
#[$class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 1.2, 0.36 + 196)) = - 1.0185 times 10^(- 3)$<tr-inline-stress-first>]， #[$class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 0.8, 0.16 + 196)) = + 1.0196 times 10^(- 3)$<tr-inline-stress-second>]。
]
'''


@unittest.skipUnless(have_pandoc() and have_typst(), "pandoc and typst are required")
class PdfLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-pdf-layout-"))
        book = make_book(cls.tmp)
        ed = book.edition("en")
        cls.stage = tp.typst_source(fixture_site(), book, ed, load_edition(ed), None,
                                    stage_dir=cls.tmp / "stage").dir
        cls.meta = json.loads((cls.stage / "meta.json").read_text())
        # Mark the laid-out positions, including the transform applied to math glyphs.
        # No PDF parser or font-dependent screenshot comparison is needed.
        (cls.stage / "main.typ").write_text(r'''
#import "/_theme/typst/book.typ": tr-book
#show: tr-book
#let mark(name) = context metadata((name: name,
  x: here().position().x.pt(), y: here().position().y.pt(), page: here().page()))
#pagebreak()
#set page(width: 360pt, height: 480pt, margin: 30pt, header: none, footer: none)
#table(columns: (90pt, 90pt, 120pt), inset: (x: 6pt, y: 5pt),
  [Code], [Math], [Neighbour],
  [#mark("code-start")#raw("LongUninterruptedDeclarationName" * 5)#mark("code-end")],
  [$ #mark("math-start") "syndromeDecoding"(S,"syndromeEncoding"(S,sigma,rho))
     = "trace"(sigma) dot rho #mark("math-end") $],
  [#mark("next-start")Neighbouring text stays in its own column.],
)
#block(width: 180pt)[
  $ #mark("display-start") "syndromeDecoding"(S,"syndromeEncoding"(S,sigma,rho))
    = "trace"(sigma) dot rho #mark("display-end") $
  #mark("after-display")Following paragraph.
]
#block(width: 180pt)[
  $ #mark("short-start") x = y #mark("short-end") $
]
''', encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_academic_layout_keeps_semantics_on_paper(self):
        import typst

        main = self.stage / "academic.typ"
        main.write_text(r'''#import "/_theme/typst/book.typ": *
#show: tr-book
#metadata((figure: tr-fig-ext, display: f-display == f-body))
#tr-chapter(id: "chapter", kicker: "1", title: [A chapter])
#context metadata((name: "chapter-position", y: here().position().y.pt()))
#tr-env(kind: "theorem", status: "lean", ref: "Theorem 1", badge: "LEAN ✓", badge-url: "https://example.org/proof",
  lean: ((name: "Test.theorem", url: "https://example.org/source"),))[A verified statement. #context metadata((role: "theorem", style: text.style))]
#tr-env(kind: "definition", status: "definition", ref: "Definition 2")[A definition. #context metadata((role: "definition", style: text.style))]
#context metadata((name: "body", y: here().position().y.pt()))
#link(<chapter>)[Back to chapter]
''', encoding="utf-8")
        options = dict(root=str(self.stage), font_paths=[str(p) for p in tp.font_dirs()],
                       sys_inputs={"tr-variant": "academic"})
        values = json.loads(typst.query(str(main), "metadata", field="value", **options))
        styles = {v["role"]: v["style"] for v in values if isinstance(v, dict) and "role" in v}
        self.assertEqual(styles, {"theorem": "italic", "definition": "normal"})
        roles = next(v for v in values if isinstance(v, dict) and "figure" in v)
        self.assertEqual(roles, {"figure": ".print.svg", "display": True})
        body = next(v for v in values if isinstance(v, dict) and v.get("name") == "body")
        chapter = next(v for v in values if isinstance(v, dict) and v.get("name") == "chapter-position")
        self.assertLess(body["y"] - chapter["y"], 200, "chapter opener must leave room for body text")
        pages = typst.compile(str(main), format="svg", **options)
        from xml.etree import ElementTree
        first = pages[0] if isinstance(pages, list) else pages
        page = ElementTree.fromstring(first)
        self.assertAlmostEqual(float(page.get("width").removesuffix("pt")), 210 / 25.4 * 72, places=2)
        self.assertAlmostEqual(float(page.get("height").removesuffix("pt")), 297 / 25.4 * 72, places=2)
        svg = b"".join(pages) if isinstance(pages, list) else pages
        self.assertIn(b"https://example.org/proof", svg)
        self.assertIn(b"https://example.org/source", svg)
        self.assertNotIn(b"linearGradient", svg)
        self.assertNotIn(b"radialGradient", svg)

    def test_preprint_chapters_share_flow_and_keep_arabic_folios(self):
        import typst

        main = self.stage / "blank.typ"
        main.write_text(r'''#import "/_theme/typst/book.typ": *
#import "/_theme/typst/academic.typ": page-label-at
#show: tr-book
#tr-chapter(id: "preface", section: "prefix", title: [Preface])
#context metadata((role: "preface", folio: counter(page).get().first(), physical: here().page()))
Preface text.
#tr-part(id: "part", title: [Part])
#tr-chapter(id: "chapter", section: "numbered", title: [Chapter])
#context metadata((role: "chapter", folio: counter(page).get().first(), physical: here().page()))
Body text.
#context metadata((role: "toc-chapter", page: page-label-at(query(heading).filter(h => h.body == [Chapter]).first().location())))
''', encoding="utf-8")
        meta = dict(self.meta, description="", cjk=False, lang="en")
        target = self.stage / "blank-meta.json"
        target.write_text(json.dumps(meta), encoding="utf-8")
        pages = typst.compile(str(main), format="svg", root=str(self.stage),
                              font_paths=[str(p) for p in tp.font_dirs()],
                              sys_inputs={"tr-variant": "academic", "tr-meta": "/blank-meta.json"})
        self.assertEqual(len(pages) if isinstance(pages, list) else 1, 1,
                         "title/abstract, contents and body flow without forced page breaks")
        values = json.loads(typst.query(str(main), "metadata", field="value", root=str(self.stage),
                              font_paths=[str(p) for p in tp.font_dirs()],
                              sys_inputs={"tr-variant": "academic", "tr-meta": "/blank-meta.json"}))
        folios = {v["role"]: v["folio"] for v in values if isinstance(v, dict) and "folio" in v}
        positions = {v["role"]: v for v in values if isinstance(v, dict) and "folio" in v}
        self.assertEqual(positions["preface"]["physical"], positions["chapter"]["physical"])
        self.assertEqual(folios["chapter"], positions["chapter"]["physical"])
        self.assertEqual(next(v["page"] for v in values if isinstance(v, dict) and v.get("role") == "toc-chapter"), str(folios["chapter"]))

    def test_preprint_paragraph_boundaries_keep_the_line_spacing(self):
        import typst

        main = self.stage / "paragraphs.typ"
        main.write_text(r'''#import "/_theme/typst/book.typ": *
#show: tr-book
#let mark(name) = context metadata((name: name, y: here().position().y.pt()))
#mark("first")A line of ordinary prose.
#linebreak()
#mark("second")Another line within the same paragraph.

#mark("third")A new paragraph must keep a full baseline interval.

+ #mark("item")An enumerated item follows the paragraph.
''', encoding="utf-8")
        for cjk in (False, True):
            meta = dict(self.meta, cjk=cjk, lang="zh" if cjk else "en")
            target = self.stage / "paragraph-meta.json"
            target.write_text(json.dumps(meta), encoding="utf-8")
            values = json.loads(typst.query(str(main), "metadata", field="value", root=str(self.stage),
                                font_paths=[str(p) for p in tp.font_dirs()],
                                sys_inputs={"tr-variant": "academic", "tr-meta": "/paragraph-meta.json"}))
            ys = {v["name"]: v["y"] for v in values if isinstance(v, dict) and "name" in v}
            interval = ys["second"] - ys["first"]
            self.assertGreaterEqual(ys["third"] - ys["second"], interval - 0.01)
            self.assertGreaterEqual(ys["item"] - ys["third"], interval - 0.01)

    def test_formulas_and_code_stay_inside_their_containers(self):
        import typst

        short_widths = []
        for cjk in (False, True):
            meta = dict(self.meta, cjk=cjk, lang="zh" if cjk else "en")
            (self.stage / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            for variant in ("screen", "print", "academic"):
                with self.subTest(cjk=cjk, variant=variant):
                    values = json.loads(typst.query(
                        str(self.stage / "main.typ"), "metadata", field="value",
                        root=str(self.stage), font_paths=[str(p) for p in tp.font_dirs()],
                        sys_inputs={"tr-variant": variant},
                    ))
                    marks = {v["name"]: v for v in values if isinstance(v, dict) and "name" in v}
                    short_widths.append(marks["short-end"]["x"] - marks["short-start"]["x"])
                    for prefix, left, right in (("math", 126, 204), ("display", 30, 210)):
                        start, end = marks[prefix + "-start"], marks[prefix + "-end"]
                        self.assertGreaterEqual(start["x"], left - 0.1)
                        self.assertLessEqual(end["x"], right + 0.1)
                        self.assertEqual(start["page"], end["page"])
                        self.assertAlmostEqual(start["y"], end["y"], places=2)
                    self.assertGreater(marks["code-end"]["y"] - marks["code-start"]["y"], 30)
                    self.assertGreater(marks["next-start"]["x"], marks["math-end"]["x"])
                    self.assertGreater(marks["after-display"]["y"], marks["display-end"]["y"])
        # Ordinary formulas retain their text size; fitting never enlarges them.
        for width in short_widths:
            self.assertGreater(width, 15)
            self.assertLess(width, 40)
        for index, group in enumerate((short_widths[:3], short_widths[3:])):
            self.assertAlmostEqual(group[0], group[1], places=2)
            ordinary_size = 10.5 if index else 10.8
            self.assertAlmostEqual(group[2] / 11, group[0] / ordinary_size, places=2)

    def test_academic_inline_math_fits_without_interrupting_prose(self):
        import typst

        main = self.stage / "inline.typ"
        main.write_text(r'''#import "/_theme/typst/book.typ": tr-book
#show: tr-book
#pagebreak()
#set page(width: 360pt, height: 480pt, margin: 30pt, header: none, footer: none)
#set par(first-line-indent: (amount: 10pt, all: false))
#let mark(name) = context metadata((name: name,
  x: here().position().x.pt(), y: here().position().y.pt(), same_width: measure([Same]).width.pt(),
  prefix_width: measure([Label before]).width.pt()))
#block(width: 180pt)[
  Same#mark("indent-first") beginning.

  Before #mark("prefix")$#mark("short-start") x = y #mark("short-end")$<tr-inline-short>#mark("after-short") after#mark("suffix").

  Prefix#h(120pt) evaluator $#mark("long-start") "interpret" : "InterpretationContext"
    "Text" "ReaderAdmission" "Background" "EvaluationGoal" "Rule"
    arrow.r "Concept" arrow.r "Meaning" #mark("long-end")$<tr-inline-long> continues.

  Same#mark("indent-next") paragraph follows.
]
#block(width: 100pt, inset: (x: 10pt))[
  Single $#mark("nested-start") "InterpretationContextTextReaderAdmissionBackgroundEvaluationGoalRuleConceptMeaning" #mark("nested-end")$<tr-inline-nested>#mark("nested-after").
]
#let reused = [$#mark("reused-start") "InterpretationContextTextReaderAdmissionBackgroundEvaluationGoalRuleConceptMeaning" #mark("reused-end")$<tr-inline-reused>]
#block(width: 180pt)[#reused]
#block(width: 80pt)[#reused]
#block(width: 180pt)[Label before#mark("wide-prefix") $#mark("wide-start")#box(width: 100pt)[x]#mark("wide-end")$<tr-inline-wide>.]
#block(width: 180pt)[
  + Label before#mark("edge-prefix") $#mark("edge-start")#box(width: 164pt)[x]#mark("edge-end")$<tr-inline-edge>;
]
''', encoding="utf-8")
        for cjk in (False, True):
            with self.subTest(cjk=cjk):
                meta = dict(self.meta, cjk=cjk, lang="zh" if cjk else "en")
                (self.stage / "inline-meta.json").write_text(json.dumps(meta), encoding="utf-8")
                values = json.loads(typst.query(str(main), "metadata", field="value",
                    root=str(self.stage), font_paths=[str(p) for p in tp.font_dirs()],
                    sys_inputs={"tr-variant": "academic", "tr-meta": "/inline-meta.json"}))
                marks = {v["name"]: v for v in values if isinstance(v, dict) and "name" in v}
                self.assertGreaterEqual(marks["long-start"]["x"], 29.9)
                self.assertLessEqual(marks["long-end"]["x"], 210.1)
                self.assertAlmostEqual(marks["long-start"]["y"], marks["long-end"]["y"], places=2)
                self.assertAlmostEqual(marks["prefix"]["y"], marks["suffix"]["y"], places=2)
                self.assertGreaterEqual(marks["after-short"]["x"], marks["short-end"]["x"] - 0.1)
                self.assertAlmostEqual(marks["indent-first"]["x"], 30 + marks["indent-first"]["same_width"], places=2)
                self.assertAlmostEqual(marks["indent-next"]["x"], 40 + marks["indent-next"]["same_width"], places=2)
                self.assertGreaterEqual(marks["nested-start"]["x"], 39.9)
                self.assertLessEqual(marks["nested-end"]["x"], 120.1)
                self.assertGreaterEqual(marks["nested-after"]["x"], marks["nested-end"]["x"] - 0.1)
                reused = [v for v in values if isinstance(v, dict) and v.get("name") == "reused-end"]
                self.assertEqual(len(reused), 2)
                self.assertGreater(reused[0]["x"], 190)
                self.assertLessEqual(reused[0]["x"], 210)
                self.assertGreater(reused[1]["x"], 90)
                self.assertLessEqual(reused[1]["x"], 110)
                self.assertLessEqual(marks["edge-end"]["x"], 210)
                self.assertGreater(marks["edge-start"]["y"], marks["edge-prefix"]["y"])
                self.assertAlmostEqual(marks["wide-prefix"]["x"], 30 + marks["wide-prefix"]["prefix_width"], places=2)
                self.assertAlmostEqual(marks["wide-start"]["y"], marks["wide-prefix"]["y"], places=2)
                self.assertAlmostEqual(marks["wide-end"]["x"] - marks["wide-start"]["x"], 100, places=2)
                self.assertGreater(marks["short-end"]["x"] - marks["short-start"]["x"], 15)

    def _compile_inline_bounds_fixture(self, variant: str, fixture: str, *, cjk: bool, lang: str):
        import typst

        meta = dict(self.meta, cjk=cjk, lang=lang)
        meta_path = self.stage / "inline-bounds-meta.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        main = self.stage / "inline-bounds.typ"
        main.write_text(
            f'''#import "/_theme/typst/{variant}": *
#show: tr-book
#pagebreak()
#let mark(name) = context metadata((name: name,
  x: here().position().x.pt(), y: here().position().y.pt(), page: here().page()))
#let first = $class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 1.2, 0.36 + 196)) = - 1.0185 times 10^(- 3)$
#let second = $class("normal", bar.v) w class("normal", bar.v)^2 - 1 = display(frac(1 - 0.8, 0.16 + 196)) = + 1.0196 times 10^(- 3)$
#context metadata((name: "first-size", width: measure(first).width.pt(), height: measure(first).height.pt()))
#context metadata((name: "second-size", width: measure(second).width.pt(), height: measure(second).height.pt()))
#set page(paper: "a4", margin: 25.4mm, header: none, footer: none)
{fixture}''',
            encoding="utf-8",
        )
        options = dict(root=str(self.stage), font_paths=[str(p) for p in tp.font_dirs()],
                       sys_inputs={"tr-variant": "academic", "tr-meta": "/inline-bounds-meta.json"})
        values = json.loads(typst.query(str(main), "metadata", field="value", **options))
        pages = typst.compile(str(main), format="svg", **options)
        svg_pages = pages if isinstance(pages, list) else [pages]
        groups = [group for page in svg_pages for group in _svg_formula_groups(page)]
        return values, groups

    @staticmethod
    def _named(values):
        return {value["name"]: value for value in values if isinstance(value, dict) and "name" in value}

    @staticmethod
    def _gap(groups):
        groups = sorted(groups, key=lambda item: (item["ink"][1], item["ink"][0]))
        first, second = groups[:2]
        denominator, numerator = first["denominator"], second["numerator"]
        x_overlap = min(denominator[2], numerator[2]) - max(denominator[0], numerator[0])
        return numerator[1] - denominator[3], x_overlap, first, second

    def test_academic_inline_fraction_bounds_clear_real_paragraph_and_scaled_pairs(self):
        """The real Example 22.27 pair clears glyph ink while wrapper and inline geometry remain stable."""
        academic = (self.stage / "_theme/typst/academic.typ").read_text(encoding="utf-8")
        line = '  show math.equation.where(block: false): set text(top-edge: "bounds", bottom-edge: "bounds")\n'
        baseline = self.stage / "_theme/typst/academic-inline-baseline.typ"
        baseline.write_text(academic.replace(line, ""), encoding="utf-8")

        for lang, cjk in (("zh", True), ("en", False)):
            with self.subTest(faithful_paragraph=lang):
                before_values, before_groups = self._compile_inline_bounds_fixture(
                    "academic-inline-baseline.typ", _INLINE_TARGET[lang], cjk=cjk, lang=lang)
                after_values, after_groups = self._compile_inline_bounds_fixture(
                    "academic.typ", _INLINE_TARGET[lang], cjk=cjk, lang=lang)
                self.assertEqual(len(before_groups), 2)
                self.assertEqual(len(after_groups), 2)
                before_gap, before_x, before_first, before_second = self._gap(before_groups)
                after_gap, after_x, after_first, after_second = self._gap(after_groups)
                self.assertLess(before_gap, -1.0, "baseline fixture must contain actual ink overlap")
                self.assertGreater(after_gap, 0.5, "bounds fixture must leave positive actual ink clearance")
                self.assertGreater(before_x, 0.1)
                self.assertAlmostEqual(after_x, before_x, places=2)
                # The bounds style moves the two lines apart, so their absolute y
                # positions change. Glyph widths, x placement, and each line's
                # actual outline height remain unchanged.
                for before_group, after_group in ((before_first, after_first), (before_second, after_second)):
                    for part in ("ink", "numerator", "denominator"):
                        before_box, after_box = before_group[part], after_group[part]
                        self.assertAlmostEqual(after_box[0], before_box[0], places=2)
                        self.assertAlmostEqual(after_box[2], before_box[2], places=2)
                        if part != "ink":
                            self.assertAlmostEqual(after_box[3] - after_box[1],
                                                   before_box[3] - before_box[1], places=2)

                before = self._named(before_values)
                after = self._named(after_values)
                self.assertAlmostEqual(before["first-size"]["width"], after["first-size"]["width"], places=2)
                self.assertAlmostEqual(before["second-size"]["width"], after["second-size"]["width"], places=2)
                self.assertLess(before["first-size"]["height"], after["first-size"]["height"])
                self.assertLess(before["second-size"]["height"], after["second-size"]["height"])
                for name in ("first-before", "first-after", "second-before", "second-after"):
                    self.assertAlmostEqual(before[name]["x"], after[name]["x"], places=2)
                    self.assertEqual(before[name]["page"], after[name]["page"])
                self.assertAlmostEqual(after["first-before"]["y"], after["first-after"]["y"], places=2)
                self.assertAlmostEqual(after["second-before"]["y"], after["second-after"]["y"], places=2)
                self.assertAlmostEqual(after["first-after"]["y"], after["punct-first"]["y"], places=2)
                self.assertAlmostEqual(after["second-after"]["y"], after["punct-second"]["y"], places=2)
                self.assertLessEqual(after["first-after"]["x"], 72 + 451.27559 + 0.1)
                self.assertAlmostEqual(after["nested-end"]["x"] - after["nested-start"]["x"],
                                       before["nested-end"]["x"] - before["nested-start"]["x"], places=2)
                self.assertLessEqual(after["nested-end"]["x"], after["nested-start"]["x"] + 70.1)
                self.assertGreaterEqual(after["nested-after"]["x"], after["nested-end"]["x"] - 0.1)

                fitting_width = None
                for width in (320, 180):
                    stress = _inline_stress(width)
                    stress_before_values, stress_before_groups = self._compile_inline_bounds_fixture(
                        "academic-inline-baseline.typ", stress, cjk=cjk, lang=lang)
                    stress_after_values, stress_after_groups = self._compile_inline_bounds_fixture(
                        "academic.typ", stress, cjk=cjk, lang=lang)
                    self.assertEqual(len(stress_before_groups), 2)
                    self.assertEqual(len(stress_after_groups), 2)
                    stress_before_gap, stress_before_x, stress_before_first, stress_before_second = self._gap(stress_before_groups)
                    stress_after_gap, stress_after_x, stress_after_first, stress_after_second = self._gap(stress_after_groups)
                    self.assertLess(stress_before_gap, -0.5)
                    self.assertGreater(stress_after_gap, 0.5)
                    self.assertGreater(stress_before_x, 0.1)
                    self.assertAlmostEqual(stress_after_x, stress_before_x, places=2)
                    self.assertAlmostEqual(stress_after_first["ink"][2] - stress_after_first["ink"][0],
                                           stress_before_first["ink"][2] - stress_before_first["ink"][0], places=2)
                    if width == 320:
                        fitting_width = stress_after_first["ink"][2] - stress_after_first["ink"][0]
                    else:
                        self.assertLess(stress_after_first["ink"][2] - stress_after_first["ink"][0], fitting_width - 1)
