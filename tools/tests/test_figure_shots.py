"""Browser geometry of the real figure screenshot pages; no example book dependency."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from test_figure import PANELS, SCRIPT, demo
from test_newbook import Repo, write
from tbook import doctor, figure, paths


NESTED = '''\
SIZE = (620, 260)
ALT = {"zh": "不同宽度与位置的面板。", "en": "Panels of different widths and positions."}


def draw(fig):
    for x, y, w, h in [(7, 13, 220, 180), (263, 29, 330, 210)]:
        panel = fig.panel(x, y, w, h)
        panel.rect(4, 4, w - 8, h - 8, color="cyan")
'''

NODE = shutil.which("node")
ROOT = paths.ROOT


@unittest.skipUnless(NODE and (ROOT / "node_modules/playwright-chromium").is_dir() and doctor.chromium_path(),
                     "node, node_modules/playwright-chromium and a Chromium are required")
class ShotGeometryTests(unittest.TestCase):
    def test_authored_viewports_and_marks_survive_preview_scaling(self):
        with Repo() as repo:
            book = demo(repo, {"nested": NESTED, "line": SCRIPT, "wrapped": PANELS})
            figure.build(book)
            jobs = []
            for name, width, height in (("nested", 620, 260), ("line", 300, 200), ("wrapped", 420, 160)):
                for view in figure.SHOT_VIEWS:
                    viewport = 390 if view == "phone" else 800
                    page = write(repo.root / f"{name}.{view}.html", figure._shot_page(book, name, "en", view))
                    jobs.append(dict(page=str(page), name=name, view=view, viewport=viewport,
                                     width=width, height=height))
            spec = write(repo.root / "jobs.json", json.dumps(jobs))
            result = subprocess.run([NODE, str(Path(__file__).with_name("figure-shots.mjs")), str(spec)],
                                    capture_output=True, text=True, timeout=90, cwd=ROOT,
                                    env={**os.environ, "PW_CHROMIUM_PATH": doctor.chromium_path()})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = json.loads(result.stdout)
            self.assertEqual(len(rows), 12)
            for row in rows:
                with self.subTest(name=row["name"], view=row["view"]):
                    self.assertEqual(row["errors"], [], row)


if __name__ == "__main__":
    unittest.main()
