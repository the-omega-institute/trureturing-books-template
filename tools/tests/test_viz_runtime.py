"""Browser regressions for shared paths, labels, solid options, screenshots and quality gates."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from tbook import doctor, paths, viz
from test_viz import fake_book
from test_viz_solid import browser_ready

NODE = viz.node_executable()


@unittest.skipUnless(browser_ready(), "Playwright Chromium is required")
class RuntimeRegressions(unittest.TestCase):
    def test_geometry_pixels_and_layout(self):
        r = subprocess.run([NODE, str(paths.TOOLS / "tests" / "viz_runtime_harness.mjs")],
                           capture_output=True, text=True, cwd=paths.ROOT, timeout=600,
                           env={**os.environ, "PW_CHROMIUM_PATH": doctor.chromium_path()})
        rows = [json.loads(s) for s in r.stdout.splitlines() if s.startswith("{")]
        if any("skip" in row for row in rows):
            self.skipTest(rows[0]["skip"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreaterEqual(len(rows), 11)
        self.assertEqual([row for row in rows if not row["ok"]], [])

    def test_selected_solid_card_and_rest_without_finishing_the_story(self):
        with tempfile.TemporaryDirectory(prefix="tbook-solid-gate-") as tmp:
            root = Path(tmp)
            (root / "books").mkdir()
            (root / "theme").symlink_to(paths.THEME, target_is_directory=True)
            (root / "node_modules").symlink_to(paths.ROOT / "node_modules", target_is_directory=True)
            book = fake_book(root / "books", "mixed-gate")
            viz.scaffold(book, "mixed", "MIXED//GATE", "混合舞台", "Mixed stages", added="2026-11-13")
            main = book.viz_dir / "mixed" / "main.js"
            text = main.read_text()
            text = text.replace("  let view = null;", """  let view = null, solid = false;
  const sc = kit.solid($('stage'), { canvas: $('cv'), radius: 0.34, onChange: () => paint() });
  sc.active(false);
""")
            text = text.replace("  function drawStage() {", """  function drawStage() {
    sc.active(solid);
    if (solid) {
      $('hudBig').textContent = 'Ellipsoid';
      sc.begin(); sc.surface('ellipsoid', (u,v) => [0.65*Math.sin(v)*Math.cos(u),0.65*Math.sin(v)*Math.sin(u),1.2*Math.cos(v)], {u:[0,2*Math.PI],v:[0,Math.PI],nu:48,nv:24}); sc.end(); return;
    }
""")
            text = text.replace("    const p = PRESETS[id];", "    const p = PRESETS[id]; solid = id === 'even';")
            text = text.replace("even: { at: 45 }", "even: { at: 45, play: true, still: 45 }")
            text = text.replace("rate: 60", "rate: 0.000001")
            text = text.replace("const toAngle = (ev) => {", "const toAngle = (ev) => { if (solid) return clock.t;")
            text = text.replace("cards.initial('even')", "cards.initial('shadow')")
            main.write_text(text)
            runner = root / "run.mjs"
            kit = (paths.TOOLS / "node" / "viz-testkit.mjs").as_uri()
            runner.write_text(f"""import {{session,stageFirstChecks}} from {json.dumps(kit)};
const T=await session();
await stageFirstChecks(T,'mixed-gate','mixed',{{solid:{{preset:'even',minShare:0.07}},rail:false,evidence:false,labels:false,keys:false}});
console.log(JSON.stringify({{results:T.results,errors:T.errors}}));
await T.browser.close();
process.exit(T.results.every(r=>r.ok)&&T.errors.length===0?0:1);
""")
            r = subprocess.run([NODE, str(runner)], capture_output=True, text=True, cwd=paths.ROOT, timeout=300,
                               env={**os.environ, "TBOOK_ROOT": str(root), "PW_CHROMIUM_PATH": doctor.chromium_path()})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rows = json.loads([s for s in r.stdout.splitlines() if s.startswith("{")][-1])["results"]
            for part in ("turning the camera", "context is given back", "a touch takes"):
                self.assertTrue(any(part in row["name"] and row["ok"] for row in rows), rows)

    def test_screenshot_cli_selects_card_and_viewport(self):
        with tempfile.TemporaryDirectory(prefix="tbook-shots-") as tmp:
            root = Path(tmp)
            (root / "books").mkdir()
            (root / "theme").symlink_to(paths.THEME, target_is_directory=True)
            (root / "node_modules").symlink_to(paths.ROOT / "node_modules", target_is_directory=True)
            book = fake_book(root / "books", "shots-fixture")
            viz.scaffold(book, "circle", "CIRCLE//TEST", "圆", "Circle", added="2026-11-13")
            args = [NODE, str(paths.TOOLS / "node" / "viz-shots.mjs"), book.slug, "circle", "--views", "embed",
                    "--lang", "en", "--width", "431", "--height", "567", "--preset", "height", "--wait", "0", "--out", str(root / "shots")]
            env = {**os.environ, "TBOOK_ROOT": str(root), "PW_CHROMIUM_PATH": doctor.chromium_path()}
            r = subprocess.run(args, capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            png = root / "shots" / "circle-embed-431x567-en-height.png"
            self.assertEqual(struct.unpack(">II", png.read_bytes()[16:24]), (431, 567))
            for bad in ("0", "NaN", "-1"):
                invalid = subprocess.run(args + ["--width", bad], capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual(invalid.returncode, 2)
                self.assertIn("whole number", invalid.stderr)
