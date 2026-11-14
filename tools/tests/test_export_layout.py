"""Lossless page-stream compression and native EPUB overflow regressions."""

import json
import os
import re
import random
import shutil
import subprocess
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from tbook import doctor, pandoc as tp, paths
from tbook.model import load_edition
from test_pandoc import fixture_site, have_pandoc, have_typst, make_book


class PageCompressionTest(unittest.TestCase):
    def test_numeric_streams_improve_beyond_default_flate_without_changing_bytes(self):
        positions = random.Random(5)
        content = b"".join(
            (f"q 1 0 0 -1 {positions.uniform(72, 523):.5f} {positions.uniform(72, 770):.5f} cm"
             "/c0 cs 0.043137256 0.08627451 0.13333334 scn\n"
             "BT 0 Tr/f0 11 Tf 1 0 0 -1 0 0 Tm[(\\000\\003\\000\\004)32(\\000\\020)]TJ\nET\nQ\n"
             ).encode() for _ in range(6000))
        self.assert_stream_fidelity(content, beyond_filtered=False)

    def test_low_iteration_deflate_improves_beyond_filtered(self):
        positions = random.Random(5)
        content = b"".join(
            (f"q 1 0 0 -1 {positions.uniform(72, 523):.0f} {positions.uniform(72, 770):.0f} cm\n"
             "BT /f0 11 Tf [(retained text)32(other text)]TJ ET Q\n").encode() for _ in range(1500))
        self.assert_stream_fidelity(content, beyond_filtered=True)

    def assert_stream_fidelity(self, content, *, beyond_filtered):
        import pikepdf
        import zopfli.zlib

        encoded = zlib.compress(content)
        encoder = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_FILTERED)
        filtered = encoder.compress(content) + encoder.flush()
        image = zlib.compress(bytes(range(256)) * 12, 1)
        font = zlib.compress(b"font program bytes" * 100, 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "numeric.pdf"
            with pikepdf.Pdf.new() as pdf:
                stream = pdf.make_stream(encoded, Filter=pikepdf.Name.FlateDecode)
                image_stream = pdf.make_stream(image, Type=pikepdf.Name.XObject,
                    Subtype=pikepdf.Name.Image, Width=32, Height=32, BitsPerComponent=8,
                    ColorSpace=pikepdf.Name.DeviceRGB, Filter=pikepdf.Name.FlateDecode)
                font_stream = pdf.make_stream(font, Filter=pikepdf.Name.FlateDecode)
                run_stream = pdf.make_stream(b"\x02q Q\x80", Filter=pikepdf.Name.RunLengthDecode)
                params_stream = pdf.make_stream(zlib.compress(b"q Q"), Filter=pikepdf.Name.FlateDecode,
                                               DecodeParms=pikepdf.Dictionary(Predictor=1))
                for i in range(2):
                    page = pdf.add_blank_page()
                    # Shared streams and Contents arrays must remain valid.
                    page.Contents = pikepdf.Array([stream, run_stream, params_stream]) if i else stream
                    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image_stream))
                pdf.add_blank_page().Contents = pikepdf.Array([])
                del pdf.add_blank_page().obj.Contents
                pdf.Root.TestFont = pikepdf.Dictionary(FontFile2=font_stream)
                pdf.save(path, object_stream_mode=pikepdf.ObjectStreamMode.generate)
            before = path.stat().st_size
            with patch.object(zopfli.zlib, "compress", wraps=zopfli.zlib.compress) as compress:
                tp._compact_pdf(path)
            self.assertEqual(compress.call_count, 1)  # shared /Contents is processed once
            self.assertLess(path.stat().st_size, before)
            with pikepdf.open(path) as pdf:
                a = pdf.pages[0].Contents
                b = pdf.pages[1].Contents[0]
                self.assertEqual(a.objgen, b.objgen)
                self.assertEqual(a.read_bytes(), content)
                self.assertLess(len(a.read_raw_bytes()), len(zlib.compress(content, 9)))
                self.assertLessEqual(len(a.read_raw_bytes()), len(filtered))
                if beyond_filtered:
                    self.assertLess(len(a.read_raw_bytes()), len(filtered))
                self.assertEqual(pdf.pages[0].Resources.XObject.Im.read_raw_bytes(), image)
                self.assertEqual(pdf.Root.TestFont.FontFile2.read_raw_bytes(), font)
                self.assertEqual(pdf.pages[1].Contents[1].Filter, pikepdf.Name.RunLengthDecode)
                self.assertEqual(pdf.pages[1].Contents[1].read_raw_bytes(), b"\x02q Q\x80")
                self.assertEqual(pdf.pages[1].Contents[1].read_bytes(pikepdf.StreamDecodeLevel.all), b"q Q")
                self.assertEqual(pdf.pages[1].Contents[2].read_raw_bytes(), zlib.compress(b"q Q"))
                self.assertEqual(pdf.pages[1].Contents[2].DecodeParms.Predictor, 1)
                self.assertEqual(len(pdf.pages[2].Contents), 0)
                self.assertNotIn("/Contents", pdf.pages[3].obj)


@unittest.skipUnless(have_pandoc() and have_typst(), "pandoc or typst not available")
class EpubLayoutTest(unittest.TestCase):
    def test_full_native_math_and_tables_scroll_inside_the_reading_column(self):
        chromium = doctor.chromium_path()
        if (not shutil.which("node") or not (paths.ROOT / "node_modules/playwright-chromium").is_dir()
                or not chromium):
            self.skipTest("node, node_modules/playwright-chromium and a Chromium are required")
        with tempfile.TemporaryDirectory(prefix="tbook-epub-layout-") as tmp:
            root = Path(tmp)
            book = make_book(root)
            long_math = r"\mathrm{LongOperatorName}(a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p) = " * 4 + "0"
            with (book.dir / "en/a.md").open("a") as f:
                f.write("\n\n## Native overflow\n\nShort $x^2$ then $" + long_math + "$ end.\n\n$$"
                        + long_math + "$$\n\n| Expression | Identifier | Value |\n|---|---|---|\n| $"
                        + long_math + "$ | `" + "identifier_" * 30 + "` | retained |\n")
            ed = book.edition("en")
            with patch.dict(os.environ, {"TBOOK_EPUBCHECK": "0"}):
                out = tp.build_epub(fixture_site(), book, ed, load_edition(ed), None, root / "book.epub",
                                    stage_dir=root / "stage")
            with zipfile.ZipFile(root / "stage/epub/pandoc.epub") as raw, zipfile.ZipFile(out) as final:
                for name in raw.namelist():
                    if name.endswith(".xhtml"):
                        self.assertEqual(re.findall(rb'<math\b.*?</math>', raw.read(name), re.S),
                                         re.findall(rb'<math\b.*?</math>', final.read(name), re.S))
                    elif "/media/" in name:
                        self.assertEqual(raw.read(name), final.read(name))
                final.extractall(root / "preview")
                chapter = next(n for n in final.namelist()
                               if n.endswith(".xhtml") and b"Native overflow" in final.read(n)
                               and "/text/" in n)
            result = subprocess.run(["node", str(Path(__file__).with_name("epub-layout.mjs")),
                                     str(root / "preview" / chapter)], capture_output=True, text=True,
                                    env={**os.environ, "PW_CHROMIUM_PATH": chromium})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(len(report), 2)
            for row in report:
                self.assertLessEqual(row["documentOverflow"], 1, row)
                self.assertGreater(row["mathScrolls"], 0, row)
                self.assertGreater(row["tableScrolls"], 0, row)
                self.assertEqual(row["inaccessibleEnds"], 0, row)
                self.assertEqual(row["narrowCells"], 0, row)
                self.assertEqual(row["pageErrors"], [], row)


if __name__ == "__main__":
    # CI invokes this focused path after browser installation. Unlike discovery,
    # missing dependencies or any skipped regression must fail the required step.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EpubLayoutTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        raise SystemExit("Required EPUB layout regression must run; skipping is not allowed.")
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
