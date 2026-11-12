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
