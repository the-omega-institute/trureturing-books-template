"""Solid shots of the film engine (theme/film/engine.js solid()): lit solids drawn by the modelling core of the
visualizations (theme/viz/solid-core.js) and composited into the 2D frame.

The page assembly (out/solid/, DATA.solid, the inlined scripts) is checked without a browser; the browser part runs
tools/tests/film_solid_harness.mjs on a fixture film (skipped without node, Playwright or a Chromium): the same t
drawn twice and in two processes gives the same pixels, the anchors of 2D labels say whether the solid hides them,
and without WebGL the page refuses to boot and says why.
Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_film_solid.py'
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from test_film import copy_example, fake_lock, needs_example, needs_listed_example, temp_book
from tbook import doctor, film, paths

THEME_FILM = paths.THEME / "film"
NODE = film.node_executable()
HARNESS = Path(__file__).with_name("film_solid_harness.mjs")

SCRIPT = {"voice": "af_heart", "speed": 0.94, "scenes": [
    {"id": "ball", "lead": 0.5, "tail": 0.5, "lines": [["A lit sphere, drawn as a solid.", "一个受光的球。"]]}]}
SCENES = """'use strict';
SCENES.ball = S => {
  const sh = solid('ball', { x: 560, y: 140, w: 800, h: 800, yaw: 0.4, pitch: 0.3, radius: 0.3 });
  sh.begin();
  sh.surface('sphere', (u, v) => [Math.sin(v) * Math.cos(u), Math.sin(v) * Math.sin(u), Math.cos(v)],
    { u: [0, 2 * Math.PI], v: [0, Math.PI], nu: 64, nv: 32, color: C.cyan });
  sh.bead([0, 0, 1.05], { color: C.now, r: 6 });
  sh.end();
  const a = sh.anchor([0, 0, 1.05]);
  txt('NORTH', a.x + 12, a.y, { size: 22, c: C.now, a: a.hidden ? 0.3 : 1 });
  window.SHOT = sh;
};
"""


def load_build():
    sys.path.insert(0, str(THEME_FILM))
    try:
        spec = importlib.util.spec_from_file_location("tbook_test_film_solid_build", THEME_FILM / "build.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(THEME_FILM))


def fixture(case: unittest.TestCase, *, solid: bool = True) -> Path:
    """A film with one scene that draws a unit sphere as a solid shot (or, without ``solid``, the example film
    as it is but with no solid shots)."""
    tmp = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, tmp)
    book = temp_book(tmp)
    d = copy_example(book)
    meta = json.loads((d / "film.json").read_text(encoding="utf-8"))
    if solid:
        meta["solid"] = True
        meta.pop("scripts", None)
        (d / "script.json").write_text(json.dumps(SCRIPT, ensure_ascii=False), encoding="utf-8")
        (d / "scenes.js").write_text(SCENES, encoding="utf-8")
    else:
        meta.pop("solid", None)
    (d / "film.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def assemble(d: Path, **kw) -> str:
    build = load_build()
    with mock.patch.object(film, "_lock", return_value=fake_lock()), \
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        page = build.build(d, **kw)
    return page.read_text(encoding="utf-8")


def page_data(html: str) -> dict:
    return json.loads(html.split("window.DATA=", 1)[1].split(";</script>", 1)[0].replace("<\\/", "</"))


@needs_example
class PageAssemblyTest(unittest.TestCase):
    def test_solid_film_gets_the_core_and_three(self):
        d = fixture(self)
        data = page_data(assemble(d))
        self.assertEqual(data["solid"], {"core": "solid/solid-core.js"})
        solid = d / "out" / "solid"
        self.assertEqual((solid / "solid-core.js").read_bytes(), film.SOLID_CORE.read_bytes())
        for name in ("three.module.min.js", "three.core.min.js", "three.LICENSE"):
            self.assertEqual((solid / "vendor" / name).read_bytes(), (film.SOLID_VENDOR / name).read_bytes(), name)

    def test_film_without_solid_shots_loads_no_three(self):
        d = fixture(self, solid=False)
        (d / "out" / "solid").mkdir(parents=True)  # left over from an earlier build with solid shots
        html = assemble(d)
        self.assertNotIn("solid", page_data(html))
        self.assertFalse((d / "out" / "solid").exists())
        self.assertNotIn("three", html.split("<script>", 2)[0])

    @needs_listed_example
    def test_scripts_are_inlined_before_scenes(self):
        d = fixture(self, solid=False)  # the example: film.json scripts lists the phase torus model
        html = assemble(d)
        model = html.index("window.PHASE_TORUS")
        self.assertLess(html.index("function solid(key"), model)
        self.assertLess(model, html.index("SCENES.zeck"))

    def test_engine_stays_deterministic(self):
        engine = (THEME_FILM / "engine.js").read_text(encoding="utf-8")
        solid_part = engine.split("/* ---------- solid shots", 1)[1].split("SCENES (registered by scenes.js)", 1)[0]
        for word in ("requestAnimationFrame", "Math.random", "performance.now", "Date.now", "setTimeout"):
            self.assertNotIn(word, solid_part, word)
        self.assertIn("createRenderer(canvas, { pixelRatio: 1 })", solid_part)
        lib = (THEME_FILM / "lib.js").read_text(encoding="utf-8")
        self.assertIn("'--enable-unsafe-swiftshader'", lib)
        self.assertNotIn("'--use-angle=swiftshader'", lib)  # it moves the 2D canvas onto ANGLE: frames would change


def browser_ready() -> bool:
    return bool(NODE and (paths.ROOT / "node_modules" / "playwright-chromium").is_dir() and doctor.chromium_path())


@needs_example
@unittest.skipUnless(browser_ready(), "node, node_modules/playwright-chromium and a Chromium are required")
class SolidShotInTheBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = fixture(cls._case())
        assemble(cls.dir)
        cls.out = cls.dir / "out"
        cls.first = cls.run_harness(["1", "2.2", "0.9"])
        cls.second = cls.run_harness(["2.2", "0.9", "1"])

    @classmethod
    def _case(cls):
        case = unittest.TestCase()
        cls._cleanups = case
        return case

    @classmethod
    def tearDownClass(cls):
        cls._cleanups.doCleanups()

    @classmethod
    def run_harness(cls, times: list[str], extra_args: str = "") -> dict:
        env = dict(os.environ)
        if extra_args:
            env["FILM_CHROMIUM_ARGS"] = extra_args
        r = subprocess.run([NODE, str(HARNESS), str(cls.out), *times], capture_output=True, text=True, env=env,
                           timeout=300, cwd=paths.ROOT)
        if r.returncode != 0:
            raise AssertionError(f"harness failed: {r.stderr[-2000:]}")
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_checks(self):
        for run in (self.first, self.second):
            for c in run["checks"]:
                with self.subTest(c["name"]):
                    self.assertTrue(c["ok"], c["detail"])

    def test_frames_do_not_depend_on_the_frames_before(self):
        # two processes, two orders: what parallel segments and a whole-range capture rely on
        self.assertEqual(self.first["hashes"], self.second["hashes"])
        self.assertEqual(len(set(self.first["hashes"].values())), 3)

    def test_no_webgl_no_fallback(self):
        r = self.run_harness(["1"], "--disable-3d-apis")
        self.assertIn("boot", r)
        self.assertIn("cannot create a WebGL context", r["boot"])
        self.assertIn('"solid": true', r["boot"])


if __name__ == "__main__":
    unittest.main()
