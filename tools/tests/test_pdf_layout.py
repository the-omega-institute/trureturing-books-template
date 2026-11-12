"""Check actual Typst layout positions for formulas and identifiers in narrow containers."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tbook import pandoc as tp
from tbook.model import load_edition
from test_pandoc import fixture_site, have_pandoc, have_typst, make_book


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
        self.assertLess(body["y"], 270, "chapter opener must leave room for body text")
        pages = typst.compile(str(main), format="svg", **options)
        from xml.etree import ElementTree
        first = pages[0] if isinstance(pages, list) else pages
        page = ElementTree.fromstring(first)
        self.assertAlmostEqual(float(page.get("width").removesuffix("pt")), 176 / 25.4 * 72, places=2)
        self.assertAlmostEqual(float(page.get("height").removesuffix("pt")), 250 / 25.4 * 72, places=2)
        svg = b"".join(pages) if isinstance(pages, list) else pages
        self.assertIn(b"https://example.org/proof", svg)
        self.assertIn(b"https://example.org/source", svg)
        self.assertNotIn(b"linearGradient", svg)
        self.assertNotIn(b"radialGradient", svg)

    def test_academic_blank_versos_have_no_folio(self):
        import typst

        main = self.stage / "blank.typ"
        main.write_text(r'''#import "/_theme/typst/book.typ": *
#import "/_theme/typst/academic.typ": page-label-at
#show: tr-book
#tr-chapter(id: "preface", section: "prefix", title: [Preface])
#context metadata((role: "preface", folio: counter(page).get().first()))
Preface text.
#tr-chapter(id: "chapter", section: "numbered", title: [Chapter])
#context metadata((role: "chapter", folio: counter(page).get().first()))
Body text.
#context metadata((role: "toc-chapter", page: page-label-at(query(heading).filter(h => h.body == [Chapter]).first().location())))
''', encoding="utf-8")
        meta = dict(self.meta, description="", cjk=False, lang="en")
        target = self.stage / "blank-meta.json"
        target.write_text(json.dumps(meta), encoding="utf-8")
        pages = typst.compile(str(main), format="svg", root=str(self.stage),
                              font_paths=[str(p) for p in tp.font_dirs()],
                              sys_inputs={"tr-variant": "academic", "tr-meta": "/blank-meta.json"})
        self.assertNotIn(b"<use ", pages[3], "inserted verso must contain no text glyphs")
        values = json.loads(typst.query(str(main), "metadata", field="value", root=str(self.stage),
                              font_paths=[str(p) for p in tp.font_dirs()],
                              sys_inputs={"tr-variant": "academic", "tr-meta": "/blank-meta.json"}))
        folios = {v["role"]: v["folio"] for v in values if isinstance(v, dict) and "folio" in v}
        self.assertGreater(folios["preface"], 1)
        self.assertEqual(folios["chapter"], 1)
        self.assertEqual(next(v["page"] for v in values if isinstance(v, dict) and v.get("role") == "toc-chapter"), "1")

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
        for group in (short_widths[:3], short_widths[3:]):
            self.assertAlmostEqual(group[0], group[1], places=2)
            self.assertLessEqual(group[2], group[0] + 0.01)
