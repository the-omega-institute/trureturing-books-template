"""Tests for kit.solid (theme/viz/kit.js): lit solids drawn with the pinned three.js of theme/viz/vendor/.

Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_viz_solid.py'
The browser part runs tools/tests/solid_harness.mjs in Chromium (skipped without node, Playwright or a Chromium) and
checks each of its lines: picking against the analytic sphere and torus, occlusion that flips with the camera, the two
sides of a surface, the key light, giving the WebGL context back and taking it again, and that three.js is fetched only
by the first call of kit.solid. tools/tests/viz_solid_program_harness.mjs draws frame after frame with the core and with
kit.solid and counts WebGL calls: once warm, a frame that draws the same kinds of primitive as the frame before links
no shader program (through changes, resizing, parking and waking), and live resources stay bounded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import unittest

from tbook import doctor, paths, viz

NODE = viz.node_executable()
VIZ = paths.THEME / "viz"
VENDOR = VIZ / "vendor"


class VendoredThree(unittest.TestCase):
    """three.js is pinned in theme/viz/vendor/: the files the README names, unmodified, with their licence."""

    def readme(self) -> str:
        return (VENDOR / "README.md").read_text(encoding="utf-8")

    def test_readme_names_version_source_and_licence(self):
        text = self.readme()
        self.assertRegex(text, r"three@\d+\.\d+\.\d+")
        self.assertIn("MIT", text)
        self.assertTrue((VENDOR / "three.LICENSE").is_file())

    def test_checksums_match(self):
        sums = dict((name, digest) for digest, name in re.findall(r"`([0-9a-f]{64})`\s+`([\w.]+)`", self.readme()))
        self.assertEqual(set(sums), {"three.module.min.js", "three.core.min.js"})
        for name, digest in sums.items():
            self.assertEqual(hashlib.sha256((VENDOR / name).read_bytes()).hexdigest(), digest, name)

    def test_licence_headers_are_kept(self):
        for name in ("three.module.min.js", "three.core.min.js"):
            head = (VENDOR / name).read_text(encoding="utf-8")[:200]
            self.assertIn("@license", head, name)
            self.assertIn("SPDX-License-Identifier: MIT", head, name)

    def test_kit_loads_the_core_lazily(self):
        kit = (VIZ / "kit.js").read_text(encoding="utf-8")
        self.assertNotRegex(kit, r"(?m)^\s*import\s", "kit.js stays a classic script")
        self.assertIn("import(CORE)", kit)
        self.assertNotIn("vendor/three", kit)

    def test_core_is_independent_of_the_page(self):
        core = (VIZ / "solid-core.js").read_text(encoding="utf-8")
        self.assertIn("from './vendor/three.module.min.js'", core)   # relative to the module: pages and films alike
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", core, flags=re.S)
        for word in ("document", "window", "TRV", "requestAnimationFrame", "addEventListener", "Math.random", "performance.now", "Date"):
            self.assertNotIn(word, code, word)
        self.assertIn("solid-core.js", viz.RUNTIME_FILES)

    def test_browser_fixture_names_no_book(self):
        # A books repository hides the example books; the harness must run under whichever book is visible.
        for name in ("solid_harness.mjs", "viz_solid_program_harness.mjs"):
            harness = (paths.TOOLS / "tests" / name).read_text(encoding="utf-8")
            self.assertNotIn("/site/example-", harness, name)
            self.assertIn("listBooks()", harness, name)

    def test_published_with_the_runtime(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            viz.publish_assets(Path(tmp))
            for name in ("three.module.min.js", "three.core.min.js", "three.LICENSE"):
                self.assertTrue((Path(tmp) / "assets" / "vendor" / name).is_file(), name)
            self.assertTrue((Path(tmp) / "assets" / "solid-core.js").is_file())


def browser_ready() -> bool:
    return bool(NODE and (paths.ROOT / "node_modules" / "playwright-chromium").is_dir() and doctor.chromium_path())


def run_harness(name: str) -> tuple[dict, str]:
    """Run a browser harness of tools/tests/ and collect its { name, ok, detail } lines by name."""
    env = dict(os.environ)
    env.setdefault("PW_CHROMIUM_PATH", doctor.chromium_path())
    r = subprocess.run([NODE, str(paths.TOOLS / "tests" / name)], capture_output=True, text=True,
                       timeout=600, env=env, cwd=paths.ROOT)
    results = {}
    for line in r.stdout.splitlines():
        if line.startswith("{"):
            row = json.loads(line)
            if "skip" in row:  # no visible book to serve the runtime from
                raise unittest.SkipTest(row["skip"])
            if "name" in row:
                results[row["name"]] = row
    return results, r.stdout + r.stderr


class BrowserHarness(unittest.TestCase):
    harness = ""
    results: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.results, cls.output = run_harness(cls.harness)

    def expect(self, name: str):
        row = self.results.get(name)
        self.assertIsNotNone(row, f"no result for {name!r}:\n{self.output[-3000:]}")
        self.assertTrue(row["ok"], f"{name}: {row['detail']}")


@unittest.skipUnless(browser_ready(), "node, node_modules/playwright-chromium and a Chromium are required")
class SolidInTheBrowser(BrowserHarness):
    harness = "solid_harness.mjs"

    def test_three_is_fetched_on_first_use_only(self):
        self.expect("no three.js before kit.solid is called")
        self.expect("three.js is fetched by the first call of kit.solid")
        self.expect("the stage renders with WebGL")

    def test_picking_on_the_sphere(self):
        self.expect("picking on the sphere agrees with the analytic intersection (point and (u, v))")

    def test_picking_on_the_torus(self):
        self.expect("picking on the torus (front and inner walls) agrees with the ray–torus root")

    def test_occlusion_follows_the_camera(self):
        self.expect("a point in front of the sphere is visible, one behind it and its centre are hidden")
        self.expect("turning the camera half round swaps what the sphere hides")
        self.expect("a mark inside the sphere cannot be picked")

    def test_front_and_back_differ(self):
        self.expect("the two sides of a surface are told apart (colour and hit.front)")

    def test_key_light(self):
        self.expect("one key light: the upper left of the sphere is brighter than the lower right")

    def test_context_is_given_back_and_taken_again(self):
        self.expect("parking gives the WebGL context back and leaves the frame on the 2D canvas")
        self.expect("the next frame takes a new context and draws the same picture")
        self.expect("one context per stay on screen (2 after one park)")

    def test_core_draws_a_frame_on_its_own(self):
        """The modelling core without the page shell, as the film engine calls it."""
        self.expect("core: one frame drawn synchronously into a 640 × 360 canvas at pixel ratio 1")
        self.expect("core: the same state drawn twice gives the same pixels, another view different ones")
        self.expect("core: the projection of an anchor agrees with the camera basis, and says which anchors a solid hides")

    def test_dashed_lines_keep_their_dash_however_finely_sampled(self):
        """sc.line(pts, { dash }) of the core (kit.solid, the film engine's solid shots) cuts dashes along the whole
        polyline: a densely sampled curve stays dashed (regression check of the dense-sampling case)."""
        self.expect("core: a dashed line looks the same sampled with 2 and with 400 points, about half of it inked")

    def test_no_errors(self):
        self.expect("no page error, console error or failed request")


@unittest.skipUnless(browser_ready(), "node, node_modules/playwright-chromium and a Chromium are required")
class SolidProgramsInTheBrowser(BrowserHarness):
    """Lines, circles, arrows, beads, rings and fans are made anew each frame, and three.js deletes a shader program
    with the last material that uses it: the core keeps the last frame's materials until the next frame is drawn, so a
    played page does not link its programs again on every frame (a stall of seconds on a busy machine). Every frame is
    drawn for real; the counts are of WebGL calls, not of time."""
    harness = "viz_solid_program_harness.mjs"

    def test_frames_reuse_the_programs_of_the_frame_before(self):
        self.expect("core: the first frame links the programs it needs (the counter sees links)")
        self.expect("core: after one cycle, frames that draw the same kinds of primitive link no program")
        self.expect("core: the same state gives the same pixels, the next state other pixels")

    def test_changes_and_resizing_link_only_what_is_new(self):
        self.expect("core: a change of geometry, colours and kinds of primitive links on its first frame only")
        self.expect("core: resizing the canvas links no program")
        self.expect("core: when they come back, their programs are linked on the first frame only")

    def test_live_resources_stay_bounded(self):
        self.expect("core: live programs, buffers, materials and geometries are the same one cycle later (nothing piles up)")
        self.expect("core: primitives no longer drawn are released with their materials, buffers and programs")
        self.expect("core: frames built but not drawn keep at most one frame of materials, and the next drawn frame lets them go")
        self.expect("core: dispose() frees every material and geometry")

    def test_kit_solid_frames_parking_and_resizing(self):
        self.expect("kit.solid: played frames link no program after warm-up")
        self.expect("kit.solid: picking and hidden marks are unchanged")
        self.expect("kit.solid: after parking and waking, the new context draws the same picture and links nothing once warm")
        self.expect("kit.solid: resizing the stage links no program")

    def test_no_errors(self):
        self.expect("no page error, console error or failed request")


if __name__ == "__main__":
    unittest.main()
