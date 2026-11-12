"""The shapes of the drawing kit that the figure books kept writing by hand (issue #35): flow-chart boxes
and links, turns, arcs of small circles, sectors, patches and polytopes on a sphere, logarithmic axes,
steps and bars, hulls, nested markup, monospace widths and bounces."""

from __future__ import annotations

import math
import re
import unittest

from tbook import figkit


def fig(markup: int = 1, w: float = 400, h: float = 300) -> figkit.Figure:
    return figkit.Figure("t", "en", w, h, alt="alt", markup=markup)


def numbers(svg: str, tag: str = "path") -> list[str]:
    return re.findall(rf"<{tag} [^>]*>", svg)


class BoxTests(unittest.TestCase):
    def test_box_sizes_itself_and_returns_anchors(self):
        f = fig()
        b = f.box(200, 20, "a step", note="lemma_name")
        self.assertAlmostEqual(b.cx, 200)
        self.assertEqual(b.top, (200, 20))
        self.assertAlmostEqual(b.w, figkit.text_width("lemma_name", 13, mono=True) + 28)
        self.assertGreater(b.h, 13 * 1.35 + 14 * 1.35)
        svg = f.svg()
        self.assertIn('class="ts-edge tf-panel"', svg, "a neutral box is a solid panel")
        self.assertIn("tr-fig-mono", svg, "the note is monospace")

    def test_dashed_and_accent_boxes_paint_by_role(self):
        f = fig()
        f.box(100, 10, "given", dashed=True)
        f.box(100, 80, "the theorem", "lean", chip="LEAN ✓")
        svg = f.svg()
        self.assertIn('stroke-dasharray="4 3"', svg)
        self.assertIn('class="ts-ok tf-ok"', svg, "an accent box is tinted in its role")
        self.assertIn(">LEAN ✓</text>", svg)
        f = fig()
        f.box(200, 10, "wide canvas", "lean", chip="LEAN ✓", chip_size=15)
        self.assertRegex(f.svg(), r'font-size="15"[^>]*>LEAN ✓</text>', "the chip takes chip_size")
        self.assertNotRegex(svg.split("</style>")[1], r"#[0-9a-fA-F]{6}")

    def test_long_text_wraps_to_the_width(self):
        f = fig()
        b = f.box(200, 10, "one two three four five six seven eight nine ten", wrap=120)
        lines = re.findall(r'<text [^>]*text-anchor="middle"[^>]*>([^<]*)</text>', f.svg())
        self.assertGreater(len(lines), 2)
        self.assertTrue(all(figkit.text_width(s, 14) <= 120 for s in lines))
        self.assertLessEqual(b.w, 120 + 28 + 1e-9)
        self.assertEqual(figkit.wrap("一二三四五六，七八", 50, 14), ["一二三", "四五", "六，七", "八"],
                         "CJK breaks between characters, never before closing punctuation")
        self.assertEqual(figkit.wrap("*a b* c", 10, 14), ["*a b*", "c"], "never inside a mark")
        self.assertEqual(figkit.wrap("x\ny", 999), ["x", "y"])

    def test_box_keeps_the_standard(self):
        with self.assertRaisesRegex(figkit.FigureError, "runs past"):
            fig(w=200).box(100, 10, "a label far too long for so small a figure")
        with self.assertRaisesRegex(figkit.FigureError, "font size"):
            fig().box(100, 10, "x", size=10)


class LinkTests(unittest.TestCase):
    def test_links_run_between_facing_sides(self):
        f = fig()
        a = figkit.Box(100, 10, 80, 30)
        b = figkit.Box(60, 100, 200, 30)
        self.assertEqual(f.link(a, b), [(140, 40), (140, 100)], "overlapping columns: straight down")
        c = figkit.Box(250, 10, 60, 30)
        self.assertEqual(f.link(a, c), [(180, 25), (250, 25)], "side by side: straight across")
        d = figkit.Box(300, 200, 40, 20)
        (x0, y0), (x1, y1) = f.link(a, d)
        self.assertEqual((y0, y1), (40, 200))
        self.assertTrue(a.x <= x0 <= a.x + a.w and d.x <= x1 <= d.x + d.w)
        self.assertEqual(f.link((10, 10), (50, 50)), [(10, 10), (50, 50)], "points are used as they are")

    def test_elbows(self):
        f = fig()
        a = figkit.Box(20, 10, 60, 30)
        b = figkit.Box(200, 100, 60, 30)
        self.assertEqual(f.link(a, b, elbow=True), [(80, 25), (230, 25), (230, 100)])
        self.assertEqual(f.link(a, b, elbow="vh"), [(50, 40), (50, 115), (200, 115)])
        wide = figkit.Box(0, 10, 400, 30)
        self.assertEqual(f.link(wide, b, elbow=True), [(230, 40), (230, 100)], "under the box: straight down")
        with self.assertRaisesRegex(figkit.FigureError, "elbow"):
            f.link(a, b, elbow="zz")
        f.link(a, b, label="by cases", side="above")
        self.assertIn(">by cases</text>", f.svg())

    def test_bounce_is_one_bent_arrow_pulled_back_at_the_ends(self):
        f = fig()
        f.bounce((10, 10), (100, 100), (190, 10), gap=10)
        svg = f.svg()
        d = re.search(r'<path d="M([\d.]+) ([\d.]+) L100 100 L([\d.]+) ([\d.]+)"', svg)
        self.assertIsNotNone(d)
        self.assertAlmostEqual(float(d.group(1)), 10 + 10 / math.sqrt(2), places=1)
        self.assertEqual(svg.count("Z\""), 1, "one head")


class SphereTests(unittest.TestCase):
    def test_turn_matches_the_hand_written_arc(self):
        def by_hand() -> str:
            f = fig()
            sp = f.sphere(200, 150, 100)
            pts = [figkit.rotate((1, 0, 0), (0, 0, 1), 90 * k / 30) for k in range(31)]
            sp.curve(pts, "now", 2.2)
            (xa, ya), (xb, yb) = sp.xy(pts[-2]), sp.xy(pts[-1])
            f.arrow_head(xb, yb, math.degrees(math.atan2(-(yb - ya), xb - xa)), "now", head=8)
            return f.svg()

        f = fig()
        sp = f.sphere(200, 150, 100)
        end = sp.turn((0, 0, 1), (1, 0, 0), 90, "now", 2.2, n=30, arrow=True)
        self.assertEqual(f.svg(), by_hand())
        self.assertAlmostEqual(end[1], 1)

    def test_small_circle_arcs_and_the_full_circle_unchanged(self):
        f = fig()
        sp = f.sphere(200, 150, 100)
        sp.small_circle((0, 0, 1), 50)
        full = f.svg()
        f2 = fig()
        f2.sphere(200, 150, 100).small_circle((0, 0, 1), 50)
        self.assertEqual(full, f2.svg())
        f3 = fig()
        sp3 = f3.sphere(200, 150, 100)
        sp3.small_circle((0, 0, 1), 50, "line", 2, start=figkit.sph(50, 10), span=90, arrow=True)
        by_turn = fig()
        by_turn.sphere(200, 150, 100).turn((0, 0, 1), figkit.sph(50, 10), 90, "line", 2, arrow=True)
        self.assertEqual(f3.svg(), by_turn.svg(), "an arc of a small circle is a turn about its axis")
        with self.assertRaisesRegex(figkit.FigureError, "on the axis"):
            sp3.small_circle((0, 0, 1), 50, start=(0, 0, 1), span=10)

    def test_sector_patch_and_polytope(self):
        f = fig()
        sp = f.sphere(200, 150, 100)
        sp.sector((0, 0, 1), (0.6, 0, 0.8), 90, "area", color="area")
        apex = sp.xy((0, 0, 0.8))
        self.assertIn(f'd="M{figkit.num(apex[0])} {figkit.num(apex[1])} L', f.svg(), "the apex is the foot on the axis")
        sp.patch([(1, 0, 0), (0, 1, 0), (0, 0, 1)], "cyan", color="cyan")
        with self.assertRaisesRegex(figkit.FigureError, "three points"):
            sp.patch([(1, 0, 0), (0, 1, 0)])
        cube = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
        faces = sp.polytope(cube)
        self.assertEqual(len(faces), 6)
        self.assertTrue(all(len(order) == 4 for _, _, order in faces))
        self.assertTrue(all(abs(d - 0.5) < 1e-9 for _, d, _ in faces), "outward normals")


class HullTests(unittest.TestCase):
    def test_plane_hull(self):
        pts = [(0, 0), (2, 0), (2, 2), (0, 2), (1, 1), (1, 0), (2, 1)]
        self.assertEqual(figkit.hull(pts), [(0, 0), (2, 0), (2, 2), (0, 2)])
        self.assertEqual(figkit.hull([(1, 1), (1, 1)]), [(1, 1)])

    def test_space_hull_of_an_octahedron(self):
        pts = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (0, 0, 0)]
        faces = figkit.hull3(pts)
        self.assertEqual(len(faces), 8)
        self.assertTrue(all(6 not in order for _, _, order in faces), "an inner point is no corner")
        with self.assertRaisesRegex(figkit.FigureError, "one plane"):
            figkit.hull3([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)])


class AxesTests(unittest.TestCase):
    def test_logarithmic_axes(self):
        f = fig()
        ax = f.axes(40, 20, 300, 200, (0.01, 1), (1e-4, 1), logx=True, logy=True)
        self.assertAlmostEqual(ax.X(0.1), 190)
        self.assertAlmostEqual(ax.Y(1e-2), 120)
        self.assertEqual(ax.decades("x"), [0.01, 0.1, 1.0])
        ax.xaxis()
        ax.yaxis()
        svg = f.svg()
        for label in (">0.01</text>", ">0.1</text>", ">1</text>", "10<tspan dy=\"-0.42em\" font-size=\"72%\">−4</tspan>"):
            self.assertIn(label, svg)
        self.assertEqual(figkit.log_label(1000), "1000")
        self.assertEqual(figkit.log_label(1e4), "10^{4}")
        self.assertEqual(figkit.log_label(0.5), "0.5")
        with self.assertRaisesRegex(figkit.FigureError, "positive range"):
            f.axes(0, 0, 10, 10, (0, 1), (1, 2), logx=True)
        with self.assertRaisesRegex(figkit.FigureError, "logarithmic"):
            ax.X(-1)

    def test_plot_on_log_axes_follows_a_power_law(self):
        f = fig()
        ax = f.axes(40, 20, 300, 200, (0.01, 1), (1e-4, 1), logx=True, logy=True)
        ax.plot(lambda t: t * t, n=4)
        pts = re.search(r'<path d="M([^"]+)"', f.svg()).group(1)
        xy = [tuple(map(float, q.strip().split())) for q in pts.split("L")]
        slopes = {round((y1 - y0) / (x1 - x0), 6) for (x0, y0), (x1, y1) in zip(xy, xy[1:])}
        self.assertEqual(len(slopes), 1, "a power law is a straight line on log-log axes")

    def test_linear_axes_are_unchanged(self):
        def make(**kw) -> str:
            f = fig()
            ax = f.axes(40, 20, 300, 200, (0, 1), (0, 1), **kw)
            ax.xaxis(ticks=[0, 0.5, 1])
            ax.plot(lambda t: t)
            return f.svg()

        self.assertEqual(make(), make(logx=False, logy=False))

    def test_steps_and_bars(self):
        f = fig()
        ax = f.axes(0, 0, 100, 100, (0, 10), (0, 10))
        ax.step([(0, 1), (5, 4), (10, 4)], "line")
        self.assertIn('d="M0 90 L50 90 L50 60 L100 60 L100 60"', f.svg())
        f = fig()
        ax = f.axes(0, 0, 100, 100, (0, 10), (0, 10))
        ax.step([(0, 1), (4, 3)], where="mid")
        self.assertIn('d="M0 90 L20 90 L20 70 L40 70"', f.svg())
        with self.assertRaisesRegex(figkit.FigureError, "where"):
            ax.step([(0, 1), (1, 2)], where="up")
        f = fig()
        ax = f.axes(0, 0, 100, 100, (0, 10), (-5, 5))
        ax.bars([(2, 3), (6, -2)], "area", bar=2, base=0)
        rects = numbers(f.svg(), "rect")
        self.assertIn('x="10" y="20" width="20" height="30"', rects[0])
        self.assertIn('x="50" y="50" width="20" height="20"', rects[1])


class MarkupTests(unittest.TestCase):
    def test_bold_italic_and_bars_at_both_levels(self):
        for level in (1, 2):
            f = fig(level)
            f.text(10, 20, "***v*** and \\bar{z}")
            svg = f.svg()
            self.assertIn('font-weight="700" font-style="italic">v</tspan>', svg)
            self.assertIn('text-decoration="overline">z</tspan>', svg)
        self.assertEqual(figkit.plain("***v*** \\bar{z}"), "v z")

    def test_level_one_reads_marks_flat(self):
        f = fig(1)
        f.text(10, 20, "*W*_{*i*}")
        self.assertIn('<tspan dy="0.28em" font-size="72%">i</tspan>', f.svg(), "level 1 is unchanged")

    def test_level_two_nests_marks(self):
        f = fig(2)
        f.text(10, 20, "*W*_{*i*+1} = *I*")
        svg = f.svg()
        self.assertIn('<tspan dy="0.28em" font-size="72%" font-style="italic">i</tspan>', svg)
        self.assertIn("<tspan font-size=\"72%\">+1</tspan>", svg, "the rest of the script keeps its size")
        self.assertIn(f'font-style="italic" font-family="{figkit.FONT_SERIF}">I</tspan>', svg, "a serif italic I")
        self.assertIn('<tspan dy="-0.2em">', svg, "the baseline is restored in em of the text")
        self.assertEqual(figkit.plain_nested("*W*_{*i*+1}"), "Wi+1")
        f = fig(2)
        f.text(10, 20, "*I*", mono=True)
        self.assertNotIn("font-family=\"'Noto Serif", f.svg(), "a monospace I already has serifs")
        f = fig(2)
        f.text(10, 20, "x^{2^{n}}")
        self.assertIn('font-size="51.84%">n</tspan>', f.svg())
        with self.assertRaisesRegex(figkit.FigureError, "MARKUP"):
            fig(3)

    def test_monospace_width_counts_a_fixed_advance(self):
        self.assertAlmostEqual(figkit.text_width("abc_def", 10, mono=True), 7 * 6)
        self.assertAlmostEqual(figkit.text_width("z̄", 10, mono=True), 6, msg="a combining mark adds nothing")
        self.assertAlmostEqual(figkit.text_width("记录", 10, mono=True), 20)
        self.assertAlmostEqual(fig().measure("*a*_{b}", 10, mono=True), 12)


if __name__ == "__main__":
    unittest.main()
