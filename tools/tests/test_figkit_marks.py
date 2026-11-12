"""The drawing kit's answers to what figure scripts kept working around (issue #44): axis ticks that stay
legible on a phone without a hand-set size, bars and hats drawn by the kit instead of combining characters,
a monospace minus that does not read as a hyphen, and light and shade, caps and front-only patches on a
sphere."""

from __future__ import annotations

import math
import re
import unittest

from tbook import figkit, figure


def fig(w: float = 400, h: float = 300, *, markup: int = 1, wrap: bool = False) -> figkit.Figure:
    return figkit.Figure("t", "en", w, h, alt="alt", markup=markup, wrap=wrap)


def path_points(d: str) -> list[tuple[float, float]]:
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return list(zip(nums[::2], nums[1::2]))


def tick_sizes(svg: str) -> set[float]:
    return {float(v) for v in re.findall(r'<text class="tf-dim" [^>]*font-size="([\d.]+)"', svg)}


class TickSizeTests(unittest.TestCase):
    def test_label_floor_follows_the_width(self):
        self.assertEqual(fig(400).label_floor(12), 12, "up to 429 wide, 12 is 10 px or more on a phone")
        self.assertEqual(fig(480).label_floor(12), 13.5, "10 × 480 / 358 = 13.4, rounded up to a half")
        self.assertEqual(fig(716).label_floor(12), 20)
        self.assertEqual(fig(716).label_floor(22), 22, "a larger size stays")

    def test_default_ticks_are_legible_on_a_phone(self):
        for width in (300, 430, 480, 600, 760):
            f = fig(width, 300)
            ax = f.axes(40, 20, width - 80, 220, (0, 1), (0, 1))
            ax.xaxis(ticks=[0, 0.5, 1], label="x")
            ax.yaxis(ticks=[0, 1])
            svg = f.svg()
            phone = figure.phone_label(svg)
            self.assertGreaterEqual(phone[0], 10 - 1e-9, f"{width} wide: {phone}")
            self.assertEqual(min(tick_sizes(svg)), max(12, math.ceil(10 * width / 358 * 2) / 2))

    def test_an_explicit_size_is_kept(self):
        f = fig(600)
        ax = f.axes(40, 20, 500, 220, (0, 1), (0, 1))
        ax.xaxis(ticks=[0, 1], size=12)
        self.assertEqual(tick_sizes(f.svg()), {12.0}, "size=12 is drawn as asked (and warned about)")

    def test_panels_of_a_wrapped_figure_take_the_widest_panel(self):
        f = fig(760, 300, wrap=True)
        a, b = f.row([460, 280], 300)
        self.assertEqual(a.label_floor(12), 13, "a 460 wide panel is shown 358 wide on a phone")
        self.assertEqual(b.label_floor(12), 13, "stacked, every panel takes the scale of the widest")
        g = fig(760, 300)
        self.assertEqual(g.panel(0, 0, 300, 300).label_floor(12), 21.5, "without wrap the whole figure is scaled")


class AccentTests(unittest.TestCase):
    def lines(self, svg: str) -> list[tuple[float, float, float, float]]:
        return [tuple(float(v) for v in m) for m in re.findall(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', svg)]

    def test_overline_sits_over_the_letter(self):
        f = fig()
        f.overline(100, 50, "c", size=20)
        svg = f.svg()
        self.assertIn(">c</text>", svg, "the letter itself, no combining macron")
        self.assertNotIn("̄", svg)
        (x1, y1, x2, y2), = self.lines(svg)
        w = figkit.text_width("c", 20)
        self.assertEqual(y1, y2)
        self.assertTrue(50 - 20 * 0.53 - 20 * 0.2 < y1 < 50 - 20 * 0.53, f"just over the x-height: {y1}")
        self.assertTrue(100 <= x1 < x2 <= 100 + w, (x1, x2, w))
        f = fig()
        f.overline(100, 50, "C", size=20, anchor="middle")
        (x1, y1, x2, _), = self.lines(f.svg())
        self.assertLess(y1, 50 - 20 * 0.72, "over a capital the bar clears the cap height")
        self.assertAlmostEqual((x1 + x2) / 2, 100, delta=0.6, msg="centred over a centred label")

    def test_italic_bars_lean_with_the_letter(self):
        a, b = fig(), fig()
        a.overline(100, 50, "c", size=20)
        b.overline(100, 50, "*c*", size=20)
        (ax1, _, ax2, _), = self.lines(a.svg())
        (bx1, _, bx2, _), = self.lines(b.svg())
        self.assertGreater(bx1, ax1)
        self.assertAlmostEqual(bx2 - bx1, ax2 - ax1, places=6)
        self.assertIn('font-style="italic"', b.svg())

    def test_hat_is_a_drawn_circumflex(self):
        f = fig()
        f.hat(100, 50, "*n*", size=20, color="now")
        svg = f.svg()
        pts = re.search(r'<path d="([^"]+)" class="ts-amber"', svg)
        self.assertIsNotNone(pts, svg)
        (x0, y0), (xm, ym), (x2, y2) = path_points(pts.group(1))
        self.assertEqual(y0, y2)
        self.assertLess(ym, y0, "the apex points up")
        self.assertAlmostEqual(xm - x0, x2 - xm, places=6)
        self.assertNotIn("̂", svg)

    def test_accents_keep_the_standard(self):
        with self.assertRaisesRegex(figkit.FigureError, "below the minimum"):
            fig().overline(10, 20, "c", size=10)
        with self.assertRaisesRegex(figkit.FigureError, "runs past"):
            fig().hat(395, 20, "longer label", size=14)


class MonoMinusTests(unittest.TestCase):
    def test_a_monospace_minus_is_set_in_the_body_face(self):
        f = fig()
        f.text(10, 20, "x − 1 = −0.5", mono=True)
        svg = f.svg()
        self.assertEqual(svg.count('<tspan class="tr-fig-sans" font-family="' + figkit.FONT_BODY + '">−</tspan>'), 2)
        self.assertIn("x <tspan", svg, "the rest stays monospace")
        f = fig()
        f.chip(10, 30, "c = −1")
        self.assertIn('class="tr-fig-sans"', f.svg(), "chips are monospace too")

    def test_hyphens_and_body_text_are_untouched(self):
        f = fig()
        f.text(10, 20, "x − 1", mono=False)
        f.text(10, 40, "a-b", mono=True)
        self.assertNotIn("tr-fig-sans", f.svg())

    def test_the_page_sets_it_in_the_body_face(self):
        from tbook import paths
        css = (paths.THEME / "mdbook" / "tr-book.css").read_text(encoding="utf-8")
        self.assertIn("svg.tr-fig .tr-fig-mono .tr-fig-sans { font-family: var(--tr-font-body); }", css)


class SphereTests(unittest.TestCase):
    def circles(self, svg: str) -> list[tuple[float, float, float, float]]:
        out = []
        for m in re.finditer(r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([-\d.]+)"([^>]*)>', svg):
            op = re.search(r'fill-opacity="([\d.]+)"', m.group(4))
            out.append((float(m.group(1)), float(m.group(2)), float(m.group(3)), float(op.group(1)) if op else 1.0))
        return out

    def test_shade_is_densest_where_the_light_falls(self):
        f = fig()
        sp = f.sphere(200, 150, 100)
        sp.shade("cyan", steps=8)
        cs = self.circles(f.svg())
        self.assertEqual(len(cs), 9)
        self.assertEqual(cs[0][:3], (200, 150, 100))
        self.assertTrue(all(c[2] < 100 for c in cs[1:]))
        for cx, cy, r, _ in cs:  # every disc stays inside the ball
            self.assertLessEqual(math.hypot(cx - 200, cy - 150) + r, 100 + 0.02)
        hx, hy = sp.xy(figkit.unit(tuple(sp.toward[i] + 0.45 * sp.up[i] - 0.35 * sp.right[i] for i in range(3))))
        self.assertLess(hy, 150, "lit from above")
        self.assertLess(hx, 200, "and from the left")
        alpha = 1 - (1 - cs[0][3]) * math.prod(1 - c[3] for c in cs[1:])
        self.assertAlmostEqual(alpha, 0.4, delta=0.03, msg="the lit point reaches about the peak opacity")
        self.assertNotRegex(f.svg().split("</style>")[1], r"#[0-9a-fA-F]{6}", "only colour roles")

    def test_outline_with_shade_and_bad_light(self):
        f = fig()
        sp = f.sphere(200, 150, 100)
        sp.outline(shade="violet")
        self.assertGreater(f.svg().count("tf-violet"), 10)
        with self.assertRaisesRegex(figkit.FigureError, "viewer's side"):
            sp.shade(light=tuple(-c for c in sp.toward))
        with self.assertRaisesRegex(figkit.FigureError, "rim < peak"):
            sp.shade(rim=0.5, peak=0.2)

    def fill_box(self, svg: str) -> list[tuple[float, float]]:
        m = re.search(r'<path d="([^"]+)" class="tf-', svg)
        return path_points(m.group(1))

    def test_a_polar_cap_seen_from_above_is_an_ellipse(self):
        f = fig()
        sp = f.sphere(200, 150, 100, az=0, el=30)
        sp.cap((0, 0, 1), 30, "magenta", color="magenta")
        pts = self.fill_box(f.svg())
        rim = [sp.xy(figkit.sph(30, a)) for a in range(0, 360, 3)]
        self.assertEqual(len(pts), 120, "all of the rim of latitude 60° is in front: its projection, an ellipse")
        self.assertTrue(all(min(math.hypot(x - u, y - v) for u, v in rim) < 0.02 for x, y in pts))
        self.assertIn('class="ts-magenta"', f.svg(), "the rim is drawn")
        self.assertIn('class="ts-magenta"', f.svg(), "the rim is drawn")

    def test_a_cap_over_the_limb_fills_only_its_front(self):
        f = fig()
        sp = f.sphere(200, 150, 100, az=0, el=0)   # looking along +y: z up, x right, the limb is the circle y = 0
        sp.cap((1, 0, 0), 60, "cyan")              # around the right end of the equator: half of it is behind
        pts = self.fill_box(f.svg())
        xs = [x for x, _ in pts]
        self.assertAlmostEqual(max(xs), 300, delta=0.5, msg="it reaches the rim of the ball")
        self.assertAlmostEqual(min(xs), 200 + 100 * math.cos(math.radians(60)), delta=0.5)
        on_rim = [p for p in pts if abs(math.hypot(p[0] - 200, p[1] - 150) - 100) < 0.05]
        self.assertGreater(len(on_rim), 10, "the hidden half is closed along the rim, not painted")

    def test_caps_that_hold_the_view_or_none_of_it(self):
        f = fig()
        sp = f.sphere(200, 150, 100, az=0, el=0)
        sp.cap(tuple(-c for c in sp.toward), 30, "cyan")   # behind the ball: nothing to paint
        self.assertNotIn("<polygon", f.svg())
        sp.cap(sp.toward, 120, "cyan")                     # its rim is behind: the whole disc
        disc = self.fill_box(f.svg())
        self.assertEqual(len(disc), 120)
        self.assertTrue(all(abs(math.hypot(x - 200, y - 150) - 100) < 0.02 for x, y in disc))
        g = fig()
        sq = g.sphere(200, 150, 100, az=0, el=0)
        sq.cap(tuple(-c for c in sq.toward), 150, "cyan")  # the rim in front, the far pole inside: a disc with a hole
        self.assertRegex(g.svg(), r'<path d="M[^"]+Z M[^"]+Z" fill-rule="evenodd" class="tf-cyan"')
        self.assertNotIn("Z M", f.svg())
        with self.assertRaisesRegex(figkit.FigureError, "between 0 and 180"):
            sq.cap((0, 0, 1), 180)

    def test_a_front_patch_is_cut_at_the_rim(self):
        corners = [figkit.sph(60, -60), figkit.sph(60, 60), figkit.sph(120, 60), figkit.sph(120, -60)]
        a, b = fig(), fig()
        sa, sb = a.sphere(200, 150, 100, az=0, el=0), b.sphere(200, 150, 100, az=0, el=0)
        sa.patch(corners, "violet")
        sb.patch(corners, "violet", front=True)
        whole, front = self.fill_box(a.svg()), self.fill_box(b.svg())
        self.assertGreater(len(front), 10)
        for x, y in front:
            self.assertLessEqual(math.hypot(x - 200, y - 150), 100 + 0.02)
        depth = lambda v: figkit.dot3(v, sb.toward)
        self.assertTrue(any(depth(c) < 0 for c in corners) and any(depth(c) > 0 for c in corners), "it crosses the rim")
        self.assertNotEqual(sorted(whole), sorted(front))
        self.assertTrue(figkit._inside_ring([figkit.unit(c) for c in corners], figkit.sph(90, 0)))
        self.assertFalse(figkit._inside_ring([figkit.unit(c) for c in corners], figkit.sph(90, 180)))


if __name__ == "__main__":
    unittest.main()
