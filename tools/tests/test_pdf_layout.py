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
#table(columns: (90pt, 90pt, 120pt),
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

    def test_formulas_and_code_stay_inside_their_containers(self):
        import typst

        short_widths = []
        for cjk in (False, True):
            meta = dict(self.meta, cjk=cjk, lang="zh" if cjk else "en")
            (self.stage / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            for variant in ("screen", "print"):
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
                    self.assertGreater(marks["code-end"]["y"] - marks["code-start"]["y"], 60)
                    self.assertGreater(marks["next-start"]["x"], marks["math-end"]["x"])
                    self.assertGreater(marks["after-display"]["y"], marks["display-end"]["y"])
        # Ordinary formulas retain their text size; fitting never enlarges them.
        for width in short_widths:
            self.assertGreater(width, 15)
            self.assertLess(width, 40)
        self.assertAlmostEqual(short_widths[0], short_widths[1], places=2)
        self.assertAlmostEqual(short_widths[2], short_widths[3], places=2)
