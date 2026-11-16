"""Native EPUB overflow regressions."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

from tbook import doctor, pandoc as tp, paths
from tbook.model import load_edition
from test_pandoc import fixture_site, have_pandoc, have_typst, make_book


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
