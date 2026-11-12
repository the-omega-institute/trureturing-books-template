"""Tests for the 2D helpers of the shared visualization runtime (theme/viz: kit.js, shell.js, theme.css), the neutral
evidence box .lean.frozen, the capitals part of the quality gate and the viewport options of viz-shots.mjs.

Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_viz_kit.py'
The browser parts run in Chromium (skipped without node, Playwright or a Chromium): tools/tests/kit_harness.mjs checks
dashed paths of kit.stage3 (the same however finely sampled; undashed paths pixel for pixel as before), kit.plot's
arrows, the ink swatch, capitals that keep Greek letters and one-letter variables, and the stage HUD; a private root
with copies of the starter page checks evidenceChecks on .lean.frozen boxes and the capitals warning of
stageFirstChecks.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tbook import config, doctor, paths, viz
from tbook.model import load_book_models

from test_viz import fake_book

NODE = viz.node_executable()
GID = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"
FROZEN_BOX = ('<div class="lean frozen"><span class="ok">FROZEN</span><span><span class="zh">已冻结，正文未以定理环境引用：</span>'
              '<span class="en">Frozen, not cited by a theorem environment of the text: </span>'
              f'<a data-lean-gid="{GID}" href="#" target="_blank" rel="noopener"><code>deficit_three_valued</code></a></span></div>')


def browser_ready() -> bool:
    return bool(NODE and (paths.ROOT / "node_modules" / "playwright-chromium").is_dir() and doctor.chromium_path())


class FrozenEvidenceBoxes(unittest.TestCase):
    """viz.evidence_boxes / evidence_problems and their Node twins in viz-validate.mjs."""

    PAGE = (
        '<section>\n'
        f'{FROZEN_BOX}\n'
        '<div class="lean frozen"><span class="ok">FROZEN</span><span>no link</span></div>\n'
        '<div class="lean"><span class="ok">LEAN ✓</span><span><a data-lean-gid="D5/S1/A.b" href="#">b</a></span></div>\n'
        '<div class="lean num"><span class="ok">NUM</span><span>x</span></div>\n'
        '<div class="lean shiny"><span class="ok">?</span></div>\n'
        '<!-- <div class="lean frozen"></div> -->\n'
        '</section>\n'
    )

    def test_boxes(self):
        boxes = viz.evidence_boxes(self.PAGE)
        self.assertEqual([(b["line"], b["kinds"], b["gids"]) for b in boxes], [
            (2, ["frozen"], [GID]), (3, ["frozen"], []), (4, [], ["D5/S1/A.b"]), (5, ["num"], []), (6, ["shiny"], [])])
        self.assertEqual(viz.frozen_gids(self.PAGE), [GID])

    def test_problems(self):
        probs = viz.evidence_problems(self.PAGE)
        self.assertEqual([line for line, _ in probs], [3, 6])
        self.assertIn("names the theorem it shows with <a data-lean-gid", probs[0][1])
        self.assertIn("shiny, which is not an evidence kind", probs[1][1])
        self.assertIn(".lean.frozen", probs[1][1])
        self.assertEqual(viz.evidence_problems(FROZEN_BOX), [])
        self.assertIn("frozen", viz.EVIDENCE_KINDS)

    @unittest.skipUnless(NODE, "node not available")
    def test_node_reads_boxes_the_same_way(self):
        code = ("import { evidenceBoxes, evidenceProblems, EVIDENCE_KINDS } from './tools/node/viz-validate.mjs';"
                f"const p = {json.dumps(self.PAGE)};"
                "console.log(JSON.stringify({ boxes: evidenceBoxes(p), problems: evidenceProblems(p), kinds: EVIDENCE_KINDS }));")
        r = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, cwd=paths.ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["boxes"], viz.evidence_boxes(self.PAGE))
        self.assertEqual([(p["line"], p["message"]) for p in out["problems"]], viz.evidence_problems(self.PAGE))
        self.assertEqual(out["kinds"], list(viz.EVIDENCE_KINDS))

    def test_page_check_warns(self):
        tmp = Path(tempfile.mkdtemp(prefix="tbook-frozen-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        page = tmp / "index.html"
        page.write_text(self.PAGE, encoding="utf-8")
        found = [i for i in viz.check_page(fake_book(tmp), "x", page, set()) if "frozen" in i.message or "evidence kind" in i.message]
        self.assertEqual([(i.severity, i.line) for i in found], [("warning", 3), ("warning", 6)])

    def test_example_books_raise_no_evidence_warning(self):
        for page in sorted(paths.BOOKS.glob("example-*/viz/*/index.html")):
            self.assertEqual(viz.evidence_problems(page.read_text(encoding="utf-8")), [], page)

    def test_frozen_gid_cited_by_the_text_is_warned(self):
        """check_frozen: a theorem a theorem environment of the text cites belongs in a green box."""
        book = config.load_book("example-monograph") if (paths.BOOKS / "example-monograph").is_dir() else None
        if book is None:
            self.skipTest("books/example-monograph is absent")
        models = load_book_models(book)
        in_text = sorted({g for m in models.values() for _, _, g, e in m.cited_gids() if e is not None and e.kind == "theorem"})
        self.assertIn(GID, in_text)
        self.assertEqual(viz.check_frozen(book, models), [])   # the example has no frozen box
        tmp = Path(tempfile.mkdtemp(prefix="tbook-frozen-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        fake = fake_book(tmp)
        shutil.copytree(book.viz_dir / "golden-carry", fake.viz_dir / "golden-carry")
        (fake.viz_dir / "visualizations.json").write_text(json.dumps({"version": 1, "visualizations": [{"id": "golden-carry"}]}), encoding="utf-8")
        page = fake.viz_dir / "golden-carry" / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace("</body>", FROZEN_BOX + "</body>"), encoding="utf-8")
        warned = viz.check_frozen(fake, models)
        self.assertEqual(len(warned), 1)
        self.assertEqual(warned[0].severity, "warning")
        self.assertIn("green .lean box", warned[0].message)
        self.assertEqual(viz.check_frozen(fake, {}), [])   # cited by no theorem environment: nothing to say


def visible_page() -> tuple[str, str] | None:
    """(book slug, page id) of the first registered visualization of a visible book, or None.

    A books repository hides the example books (site.toml [books].hide) and viz-shots.mjs refuses a hidden book, so
    the tests of its plan name no book: they run on whichever page is visible first.
    """
    if not paths.BOOKS.is_dir():   # a repository with no book at all
        return None
    hidden = set(config.hidden_books())
    for book in sorted(d for d in paths.BOOKS.iterdir() if (d / "book.toml").is_file() and d.name not in hidden):
        registry = book / "viz" / "visualizations.json"
        if not registry.is_file():
            continue
        try:
            entries = json.loads(registry.read_text(encoding="utf-8")).get("visualizations", [])
        except ValueError:
            continue
        for entry in entries:
            vid = entry.get("id") if isinstance(entry, dict) else None
            if vid and (book / "viz" / vid / "index.html").is_file():
                return book.name, vid
    return None


@unittest.skipUnless(NODE, "node not available")
class ShotsPlan(unittest.TestCase):
    """viz-shots.mjs --plan: the shots it would take, without a browser."""

    def run_shots(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-shots.mjs"), self.book, self.vid, "--plan", *args],
                              capture_output=True, text=True, cwd=paths.ROOT, timeout=60)

    def plan(self, *args: str) -> list[dict]:
        r = self.run_shots(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [json.loads(line) for line in r.stdout.splitlines() if line.startswith("{")]

    def setUp(self):
        page = visible_page()
        if page is None:
            self.skipTest("no visible book has a registered visualization")
        self.book, self.vid = page

    def test_without_the_new_options_the_shots_are_as_before(self):
        rows = [(p["view"], p["lang"], p["width"], p["height"], p["query"], p["fullPage"], Path(p["file"]).name) for p in self.plan()]
        v = self.vid
        self.assertEqual(rows, [
            ("desk", "zh", 1440, 900, "lang=zh", False, f"{v}-desk-zh.png"),
            ("desk", "en", 1440, 900, "lang=en", False, f"{v}-desk-en.png"),
            ("embed", "zh", 740, 620, "embed=1&lang=zh", False, f"{v}-embed-zh.png"),
            ("embed", "en", 740, 620, "embed=1&lang=en", False, f"{v}-embed-en.png"),
            ("phone", "zh", 390, 844, "lang=zh", True, f"{v}-phone-zh.png"),
            ("phone", "en", 390, 844, "lang=en", True, f"{v}-phone-en.png"),
            ("thumb", "zh", 1280, 720, "thumb=1&lang=zh", False, f"{v}-thumb.png"),
        ])

    def test_width_height_and_preset_in_the_book(self):
        rows = self.plan("--views", "embed,thumb", "--width", "390", "--preset", "area", "--lang", "en")
        self.assertEqual([(p["view"], p["width"], p["height"], p["query"], Path(p["file"]).name) for p in rows], [
            ("embed", 390, 620, "embed=1&lang=en&preset=area", f"{self.vid}-embed-390-en-area.png"),
            ("thumb", 1280, 720, "thumb=1&lang=zh", f"{self.vid}-thumb.png"),   # the cover keeps its size
        ])
        rows = self.plan("--views", "desk", "--width", "600", "--height", "500", "--lang", "zh", "--name", "x")
        self.assertEqual([(p["width"], p["height"], p["query"], Path(p["file"]).name) for p in rows],
                         [(600, 500, "lang=zh", f"{self.vid}-desk-600x500-zh-x.png")])

    def test_bad_values_are_refused(self):
        self.assertEqual(self.run_shots().returncode, 0)   # the page itself is accepted: what follows is refused for its value
        for args in (["--width", "abc"], ["--width", "50"], ["--height", "500"], ["--preset", "../x"]):
            self.assertEqual(self.run_shots(*args).returncode, 2, args)

    def test_help_names_the_options(self):
        r = subprocess.run([NODE, str(paths.TOOLS / "node" / "viz-shots.mjs"), "--help"], capture_output=True, text=True, cwd=paths.ROOT, timeout=60)
        for flag in ("--width", "--height", "--preset", "--plan"):
            self.assertIn(flag, r.stdout)


class RuntimeSource(unittest.TestCase):
    """What the runtime files promise, read from their source."""

    def test_theme(self):
        css = (paths.THEME / "viz" / "theme.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.sw\.ik\s*\{\s*background:\s*var\(--ink\);")
        self.assertRegex(css, r"\.lean\.frozen\s*\{[^}]*var\(--ink\)")
        self.assertNotRegex(css, r"\.lean\.frozen[^{]*\{[^}]*--ok")   # neutral, never green
        self.assertRegex(css, r"\.keepcase\s*\{\s*text-transform:\s*none;")
        self.assertIn(".hud-stack .hud-tl", css)

    def test_kit_names_plot_arrow(self):
        kit = (paths.THEME / "viz" / "kit.js").read_text(encoding="utf-8")
        self.assertIn("g.arrow = (a, b, s) =>", kit)
        self.assertIn("lineDashOffset", kit)


@unittest.skipUnless(browser_ready(), "node, node_modules/playwright-chromium and a Chromium are required")
class KitInTheBrowser(unittest.TestCase):
    results: dict = {}

    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env.setdefault("PW_CHROMIUM_PATH", doctor.chromium_path())
        r = subprocess.run([NODE, str(paths.TOOLS / "tests" / "kit_harness.mjs")], capture_output=True, text=True,
                           timeout=600, env=env, cwd=paths.ROOT)
        cls.output = r.stdout + r.stderr
        cls.results = {}
        for line in r.stdout.splitlines():
            if line.startswith("{"):
                row = json.loads(line)
                if "skip" in row:
                    raise unittest.SkipTest(row["skip"])
                cls.results[row["name"]] = row

    def expect(self, *names: str):
        for name in names:
            row = self.results.get(name)
            self.assertIsNotNone(row, f"no result for {name!r}:\n{self.output[-3000:]}")
            self.assertTrue(row["ok"], f"{name}: {row['detail']}")

    def test_dashed_paths_keep_their_dash(self):
        """The regression check of densely sampled dashed paths on kit.stage3."""
        self.expect("stage3: a dashed straight path looks the same sampled with 2 and with 400 points",
                    "stage3: a densely sampled dashed ring stays dashed (about half its length inked)",
                    "stage3: st.circle(…, { dash }) with 720 points draws about half the ink of the solid circle",
                    "stage3: a dashed ring through the centre plane stays dashed on both sides and dimmer behind")

    def test_undashed_paths_are_unchanged(self):
        self.expect("stage3: an undashed path is drawn pixel for pixel as before")

    def test_plot_arrow(self):
        self.expect("plot: g.arrow([x0, y0], [x1, y1], s) draws a shaft in data coordinates and a head at the far end",
                    "plot: g.arrow takes (a, b, s) as st.arrow of kit.stage3")

    def test_ink_swatch(self):
        self.expect("theme: .sw.ik is the ink swatch (the --tr-ink token)")

    def test_capitals(self):
        self.expect("capitals: headings keep δ, u, x, μ and θ as written and set words in capitals",
                    "capitals: the article \"a\" between two words is set in capitals, the variable a is not",
                    "capitals: card codes and chips keep Greek letters",
                    "capitals: stage labels written by st.tag keep δ, u and φ; Δ stays Δ",
                    "capitals: text that is not set in capitals is left alone",
                    "capitals: text the page writes later is kept as well",
                    "capitals: the quality gate finds no lowercase Greek letter set in capitals",
                    "capitals: the quality gate finds lowercase Greek letters set in capitals once the guard is overridden")

    def test_hud(self):
        self.expect("HUD: on a wide stage the title stays at the top left, next to the buttons",
                    "HUD: in a 390px frame the title goes below the buttons, and nothing overlaps",
                    "HUD: in a 334px frame the title goes below the buttons, and nothing overlaps",
                    "HUD: widening the frame again puts the title back at the top")

    def test_no_errors(self):
        self.expect("no page error, console error or failed request")


@unittest.skipUnless(browser_ready(), "node, node_modules/playwright-chromium and a Chromium are required")
class FrozenAndCapitalsGate(unittest.TestCase):
    """evidenceChecks on .lean.frozen boxes, and the capitals warning of stageFirstChecks, run in Chromium on private
    copies of the starter page (a private root with the repository's lock)."""

    SLUG = "frozen-gate-fixture"
    EVIDENCE = '<section class="panel sec" id="evidence">\n'
    HEADING = '<h2><span class="zh">实验卡带</span><span class="en">Experiments</span><span class="aside">PRESETS</span></h2>'
    RUNNER = """
import fs from 'node:fs';
const [kit, out, slug, ...ids] = process.argv.slice(2);
const { session, evidenceChecks, stageFirstChecks, settle } = await import(kit);
const T = await session();
const res = {};
for (const id of ids) {
  const from = T.results.length, warnFrom = T.warnings.length;
  if (id.startsWith('caps-')) await stageFirstChecks(T, slug, id, { rail: false, keys: false, evidence: false, still: false });
  else { const page = await T.goto(slug, id, '?lang=zh'); await settle(page, 200); await evidenceChecks(T, slug, id, page); }
  res[id] = { checks: T.results.slice(from), warnings: T.warnings.slice(warnFrom) };
}
await T.browser.close();
fs.writeFileSync(out, JSON.stringify({ res, errors: T.errors }));
process.exit(0);
"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-frozen-gate-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        root = cls.tmp / "root"
        (root / "books").mkdir(parents=True)
        try:
            (root / "theme").symlink_to(paths.THEME, target_is_directory=True)
            if (paths.ROOT / "node_modules").is_dir():
                (root / "node_modules").symlink_to(paths.ROOT / "node_modules", target_is_directory=True)
        except OSError as exc:
            raise unittest.SkipTest(f"cannot link the theme into a private root: {exc}")
        if not paths.LOCK_FILE.is_file() or GID not in json.loads(paths.LOCK_FILE.read_text(encoding="utf-8")).get("declarations", {}):
            raise unittest.SkipTest(f"the repository's lock does not hold {GID}")
        shutil.copy(paths.LOCK_FILE, root / "trureturing.lock.json")
        book = fake_book(root / "books", cls.SLUG)

        def swap(text: str, old: str, new: str) -> str:
            if text.count(old) != 1:
                raise AssertionError(f"templates/viz/index.html no longer has exactly one {old!r}")
            return text.replace(old, new)

        greek = '<h2><span class="zh">相位 δ 与 φ</span><span class="en">Phase δ and φ</span><span class="aside">PRESETS</span></h2>'
        variants = {
            "ev-frozen": lambda h: swap(h, cls.EVIDENCE, cls.EVIDENCE + FROZEN_BOX + "\n"),
            "ev-frozen-nolink": lambda h: swap(h, cls.EVIDENCE, cls.EVIDENCE + re.sub(r"<a .*?</a>", "<code>x</code>", FROZEN_BOX) + "\n"),
            "ev-frozen-green": lambda h: swap(h, cls.EVIDENCE, cls.EVIDENCE + FROZEN_BOX.replace("lean frozen", "lean num") + "\n"),
            "caps-plain": lambda h: swap(h, cls.HEADING, greek),
            "caps-broken": lambda h: swap(h, cls.HEADING, greek).replace("</head>", "<style>.keepcase { text-transform: uppercase !important; }</style></head>"),
        }
        for vid, change in variants.items():
            viz.scaffold(book, vid, vid.upper().replace("-", "//"), "依据", "Evidence", added="2026-11-12")
            page = book.viz_dir / vid / "index.html"
            page.write_text(change(page.read_text(encoding="utf-8")), encoding="utf-8")
        runner, out = cls.tmp / "frozen-gate.mjs", cls.tmp / "frozen-gate.json"
        runner.write_text(cls.RUNNER, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "VIZ_ORIGIN"}
        env["TBOOK_ROOT"] = str(root)
        env.setdefault("PW_CHROMIUM_PATH", doctor.chromium_path())
        kit = (paths.TOOLS / "node" / "viz-testkit.mjs").as_uri()
        r = subprocess.run([NODE, str(runner), kit, str(out), cls.SLUG, *variants], capture_output=True,
                           text=True, cwd=paths.ROOT, env=env, timeout=900)
        if not out.is_file():
            tail = (r.stdout + r.stderr)[-3000:]
            if re.search(r"Playwright is not installed|Executable doesn't exist|browserType\.launch", tail):
                raise unittest.SkipTest("Playwright Chromium is not available")
            raise AssertionError(f"the gate did not run (exit {r.returncode}):\n{tail}")
        data = json.loads(out.read_text(encoding="utf-8"))
        cls.res, cls.errors = data["res"], data["errors"]

    def outcome(self, vid: str, part: str) -> tuple[bool, str]:
        [c] = [c for c in self.res[vid]["checks"] if part in c["name"]]
        return c["ok"], c["detail"]

    def test_a_frozen_box_passes_and_is_not_the_registry_list(self):
        for part in ("every Lean link names a frozen theorem", "the registry lists exactly", "green boxes are exactly"):
            ok, detail = self.outcome("ev-frozen", part)
            self.assertTrue(ok, f"{part}: {detail}")

    def test_a_frozen_box_needs_its_link(self):
        ok, detail = self.outcome("ev-frozen-nolink", "green boxes are exactly")
        self.assertFalse(ok)
        self.assertIn("FROZEN box without a Lean link", detail)

    def test_a_lean_link_in_another_colour_still_fails(self):
        ok, detail = self.outcome("ev-frozen-green", "green boxes are exactly")
        self.assertFalse(ok)
        self.assertIn("Lean link in a box of another colour", detail)

    def test_capitals_warning(self):
        caps = lambda vid: [w for w in self.res[vid]["warnings"] if w["name"].startswith("capitals:")]  # noqa: E731
        self.assertEqual(caps("caps-plain"), [])
        found = caps("caps-broken")
        self.assertEqual(len(found), 2, found)   # zh and en
        self.assertIn("δ", found[0]["detail"])
        self.assertEqual([c for c in self.res["caps-broken"]["checks"] if "capital" in c["name"]], [], "a warning, not a check")

    def test_no_errors(self):
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
