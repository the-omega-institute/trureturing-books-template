"""Drawing kit for static figures (``books/<slug>/figures/<name>.py``; see skills/book-figure).

A figure script draws on a :class:`Figure` with the methods below and never writes a colour: every
stroke and fill names a *role* (``ink``, ``cyan``, ``lean`` …) taken from ``theme/tokens.json``. The
tool renders one SVG per language; the HTML edition inlines it so that the roles follow the page's
palette, the PDF and EPUB get the same drawing with the palette of that output written in
(:mod:`tbook.figure`).

The standard the kit enforces (``FigureError`` when a script breaks it):

* text is at least :data:`MIN_FONT` units and lines at least :data:`MIN_STROKE` units (one unit is
  one CSS pixel at the figure's natural size, which is also its largest size on a page);
* colours are roles, never literals; green (``lean``) is reserved for Lean-verified statements,
  amber (``now``) for the current choice, red (``open``) for open problems;
* output is deterministic: coordinates are rounded, nothing depends on time or randomness the script
  does not seed itself.

Coordinates are user units with the origin at the top left and ``y`` growing downwards, as in SVG;
angles given to :meth:`Canvas.arc` are degrees, counter-clockwise from the positive x axis as on paper.
"""

from __future__ import annotations

import html
import math
import re
from typing import Callable, Iterable, Sequence

MIN_FONT = 12.0
MIN_STROKE = 1.0
MAX_WIDTH = 760  # the text column of the HTML edition; wider figures are scaled down everywhere
TEXT_SLACK = 3.0  # how far the estimated extent of a label may pass the edge of its canvas

# role → token of theme/tokens.json (the same names in the "screen" and the "paper" palette)
ROLES: dict[str, str] = {
    "ink": "ink", "dim": "dim", "faint": "faint", "edge": "panel-edge", "hot": "line-hot",
    "bg": "void", "panel": "panel-solid", "sheet": "sheet",
    "cyan": "cyan", "magenta": "magenta", "amber": "amber", "violet": "violet",
    "ok": "ok", "warn": "warn", "blue": "blue", "orange": "orange", "sigma": "sigma",
}
# semantic names a script may use; each is one of the roles above
ALIASES: dict[str, str] = {
    "lean": "ok", "open": "warn", "argued": "violet", "now": "amber", "model": "amber",
    "line": "cyan", "area": "magenta", "axis": "violet",
}
FONT_BODY = "'Noto Sans SC', 'Noto Sans CJK SC', 'Source Sans 3', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
FONT_MONO = "'JetBrains Mono', 'DejaVu Sans Mono', ui-monospace, Menlo, Consolas, monospace"

Point = tuple[float, float]


class FigureError(Exception):
    """A figure script broke the standard, or cannot be drawn."""


def role(name: str) -> str:
    """The palette role behind ``name`` (a role or a semantic alias)."""
    r = ALIASES.get(name, name)
    if r not in ROLES:
        raise FigureError(f"unknown colour role {name!r}; use one of {', '.join(sorted(set(ROLES) | set(ALIASES)))} "
                          "(figures never write colour values)")
    return r


def num(v: float) -> str:
    """A coordinate as written in the SVG: two decimals at most, no ``-0``."""
    s = f"{float(v):.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def esc(text: str) -> str:
    # "$" would open a formula for the HTML edition's math pass; "\\" its escape
    return html.escape(str(text), quote=True).replace("$", "&#36;").replace("\\", "&#92;")


_WIDE = re.compile("[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")  # CJK with its punctuation, Hangul, full-width forms


def text_width(text: str, size: float = 14.0, mono: bool = False) -> float:
    """Estimated advance of ``text`` (plain, markup already removed) at ``size``."""
    w = 0.0
    for ch in text:
        if _WIDE.match(ch):
            w += 1.0
        elif mono:
            w += 0.6
        elif ch in "iljtfI.,:;'|!()[] ":
            w += 0.32
        elif ch in "mwMW@":
            w += 0.86
        elif ch.isupper() or ch.isdigit():
            w += 0.62
        else:
            w += 0.54
    return w * size


# ``*x*`` italic, ``_{i}`` subscript, ``^{2}`` superscript, ``**b**`` bold; ``\*`` etc. are literal.
_MARK = re.compile(r"\\([*_^{}\\])|\*\*(.+?)\*\*|\*(.+?)\*|_\{(.*?)\}|\^\{(.*?)\}", re.S)


def plain(markup: str) -> str:
    """``markup`` without its marks (for width estimates and accessible text)."""
    return _MARK.sub(lambda m: m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5) or "", markup)


def _spans(markup: str) -> str:
    """The inside of a ``<text>`` for ``markup``; sub- and superscripts are shifted with ``dy``
    (every renderer the builds use reads it; ``baseline-shift`` is not read by all)."""
    out: list[str] = []
    pos = 0
    pending = 0.0  # em to undo on the next span

    def emit(text: str, attrs: str = "", shift: float = 0.0) -> None:
        nonlocal pending
        if not text:
            return
        dy = shift - pending
        pending = shift
        if not attrs and abs(dy) < 1e-9:
            out.append(esc(text))
            return
        d = f' dy="{num(dy)}em"' if abs(dy) > 1e-9 else ""
        out.append(f"<tspan{d}{attrs}>{esc(text)}</tspan>")

    for m in _MARK.finditer(markup):
        emit(markup[pos:m.start()])
        if m.group(1) is not None:
            emit(m.group(1))
        elif m.group(2) is not None:
            emit(plain(m.group(2)), ' font-weight="700"')
        elif m.group(3) is not None:
            emit(plain(m.group(3)), ' font-style="italic"')
        elif m.group(4) is not None:
            emit(plain(m.group(4)), ' font-size="72%"', 0.28)
        else:
            emit(plain(m.group(5)), ' font-size="72%"', -0.42)
        pos = m.end()
    emit(markup[pos:])
    if abs(pending) > 1e-9:  # restore the baseline for whatever follows in the same <text>
        out.append(f'<tspan dy="{num(-pending)}em">​</tspan>')
    return "".join(out)


class Canvas:
    """Something to draw on: a :class:`Figure` or one of its panels. Every method takes colour
    *roles*; ``color`` paints the stroke (or the text), ``fill`` the inside."""

    def __init__(self, fig: "Figure", width: float, height: float):
        self.fig = fig
        self.width = float(width)
        self.height = float(height)
        self.items: list[str] = []

    # ------------------------------------------------------------------ helpers

    @property
    def lang(self) -> str:
        return self.fig.lang

    def t(self, zh: str, en: str | None = None, **more: str) -> str:
        """The text for this figure's language: ``fig.t("影子", "shadow")``."""
        return self.fig.t(zh, en, **more)

    def _paint(self, color: str | None, fill: str | None, width: float | None, *, dash: str | Sequence[float] | None = None,
               opacity: float | None = None, fill_opacity: float | None = None, cap: str | None = None,
               join: str | None = None) -> str:
        cls: list[str] = []
        attrs: list[str] = []
        if color:
            if width is None:
                width = 1.6
            if width < MIN_STROKE:
                raise FigureError(f"stroke width {width} is below the minimum {MIN_STROKE}")
            cls.append("ts-" + role(color))
            attrs.append(f'stroke-width="{num(width)}"')
            if dash:
                d = dash if isinstance(dash, str) else " ".join(num(v) for v in dash)
                attrs.append(f'stroke-dasharray="{d}"')
            if cap:
                attrs.append(f'stroke-linecap="{cap}"')
            if join:
                attrs.append(f'stroke-linejoin="{join}"')
        if fill:
            cls.append("tf-" + role(fill))
            if fill_opacity is not None and fill_opacity < 1:
                attrs.append(f'fill-opacity="{num(fill_opacity)}"')
        else:
            attrs.append('fill="none"')
        if opacity is not None and opacity < 1:
            attrs.append(f'opacity="{num(opacity)}"')
        return (f' class="{" ".join(cls)}"' if cls else "") + (" " + " ".join(attrs) if attrs else "")

    def add(self, markup: str) -> None:
        self.items.append(markup)

    # ------------------------------------------------------------------ shapes

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str = "ink", width: float = 1.6, **kw) -> None:
        self.add(f'<line x1="{num(x1)}" y1="{num(y1)}" x2="{num(x2)}" y2="{num(y2)}"{self._paint(color, None, width, **kw)}/>')

    def polyline(self, pts: Iterable[Point], color: str | None = "ink", width: float = 1.6, *, fill: str | None = None,
                 closed: bool = False, **kw) -> None:
        pts = list(pts)
        if len(pts) < 2:
            return
        d = "M" + " L".join(f"{num(x)} {num(y)}" for x, y in pts) + ("Z" if closed else "")
        kw.setdefault("join", "round")
        self.add(f'<path d="{d}"{self._paint(color, fill, width if color else None, **kw)}/>')

    def polygon(self, pts: Iterable[Point], fill: str | None = "cyan", *, color: str | None = None, width: float = 1.6,
                fill_opacity: float | None = 0.18, **kw) -> None:
        self.polyline(pts, color, width, fill=fill, closed=True, fill_opacity=fill_opacity, **kw)

    def path(self, d: str, color: str | None = "ink", width: float = 1.6, *, fill: str | None = None, **kw) -> None:
        """Raw SVG path data, for what the other shapes do not cover."""
        self.add(f'<path d="{d}"{self._paint(color, fill, width if color else None, **kw)}/>')

    def curve(self, fn: Callable[[float], Point], t0: float, t1: float, n: int = 96, color: str | None = "ink",
              width: float = 1.8, **kw) -> None:
        """A parametric curve ``fn(t) -> (x, y)`` sampled at ``n + 1`` points."""
        self.polyline([fn(t0 + (t1 - t0) * i / n) for i in range(n + 1)], color, width, **kw)

    def rect(self, x: float, y: float, w: float, h: float, *, color: str | None = "edge", fill: str | None = None,
             width: float = 1.2, rx: float = 0, **kw) -> None:
        r = f' rx="{num(rx)}"' if rx else ""
        self.add(f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}"{r}'
                 f'{self._paint(color, fill, width if color else None, **kw)}/>')

    def circle(self, cx: float, cy: float, r: float, *, color: str | None = "ink", fill: str | None = None,
               width: float = 1.6, **kw) -> None:
        self.add(f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}"{self._paint(color, fill, width if color else None, **kw)}/>')

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, *, rotate: float = 0, color: str | None = "ink",
                fill: str | None = None, width: float = 1.6, **kw) -> None:
        tr = f' transform="rotate({num(-rotate)} {num(cx)} {num(cy)})"' if rotate else ""
        self.add(f'<ellipse cx="{num(cx)}" cy="{num(cy)}" rx="{num(rx)}" ry="{num(ry)}"{tr}'
                 f'{self._paint(color, fill, width if color else None, **kw)}/>')

    def dot(self, x: float, y: float, r: float = 3.6, color: str = "ink", *, ring: str | None = None, **kw) -> None:
        """A filled point; ``ring`` adds an outline in another role (a knockout against lines: ``ring="bg"``)."""
        self.add(f'<circle cx="{num(x)}" cy="{num(y)}" r="{num(r)}"{self._paint(ring, color, 1.4 if ring else None, **kw)}/>')

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float, color: str | None = "ink", width: float = 1.6, *,
            fill: str | None = None, ry: float | None = None, **kw) -> None:
        """The arc of the circle (ellipse with ``ry``) from angle ``a0`` to ``a1`` in degrees,
        counter-clockwise when ``a1 > a0``; with ``fill`` the sector from the centre."""
        ry = r if ry is None else ry
        n = max(8, int(abs(a1 - a0) / 4))
        pts = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                cy - ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
        if fill:
            self.polyline([(cx, cy)] + pts, color, width, fill=fill, closed=True, **kw)
        else:
            self.polyline(pts, color, width, **kw)

    def arrow(self, x1: float, y1: float, x2: float, y2: float, color: str = "ink", width: float = 2.0, *,
              head: float = 9.0, both: bool = False, **kw) -> None:
        """A straight arrow; the head is drawn as a shape, so it takes the role's colour in every output."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return
        ux, uy = dx / length, dy / length
        h = min(head, length * 0.6)
        sx, sy = (x1 + ux * h * 0.85, y1 + uy * h * 0.85) if both else (x1, y1)
        self.line(sx, sy, x2 - ux * h * 0.85, y2 - uy * h * 0.85, color, width, **kw)
        self.arrow_head(x2, y2, math.degrees(math.atan2(-dy, dx)), color, head=h, opacity=kw.get("opacity"))
        if both:
            self.arrow_head(x1, y1, math.degrees(math.atan2(dy, -dx)), color, head=h, opacity=kw.get("opacity"))

    def arrow_head(self, x: float, y: float, angle: float, color: str = "ink", *, head: float = 9.0,
                   opacity: float | None = None) -> None:
        """An arrow head with its tip at ``(x, y)`` pointing along ``angle`` (degrees, counter-clockwise)."""
        a = math.radians(angle)
        ux, uy = math.cos(a), -math.sin(a)
        px, py = -uy, ux
        w = head * 0.42
        pts = [(x, y), (x - ux * head + px * w, y - uy * head + py * w), (x - ux * head - px * w, y - uy * head - py * w)]
        self.polyline(pts, None, fill=color, closed=True, opacity=opacity)

    def curve_arrow(self, pts: Sequence[Point], color: str = "ink", width: float = 2.0, *, head: float = 9.0, **kw) -> None:
        """An arrow along the polyline ``pts`` (for arcs and curved paths)."""
        pts = list(pts)
        if len(pts) < 2:
            return
        self.polyline(pts, color, width, **kw)
        (xa, ya), (xb, yb) = pts[-2], pts[-1]
        self.arrow_head(xb, yb, math.degrees(math.atan2(-(yb - ya), xb - xa)), color, head=head, opacity=kw.get("opacity"))

    # ------------------------------------------------------------------ text

    def text(self, x: float, y: float, s: str, *, size: float = 14.0, color: str = "ink", anchor: str = "start",
             weight: int | str | None = None, italic: bool = False, mono: bool = False, halo: bool = False,
             rotate: float = 0, middle: bool = False, opacity: float | None = None) -> None:
        """Text with its baseline at ``y`` (its vertical centre with ``middle=True``). ``s`` may mark
        ``*italic*``, ``**bold**``, ``_{sub}`` and ``^{sup}``; write mathematics with Unicode symbols.
        ``halo`` paints the page colour around the glyphs so that a label stays legible over lines."""
        if size < MIN_FONT:
            raise FigureError(f"font size {size} is below the minimum {MIN_FONT} ({plain(s)!r})")
        if anchor not in ("start", "middle", "end"):
            raise FigureError(f"anchor must be start, middle or end, not {anchor!r}")
        if not rotate:  # a label that runs off the canvas is cut off in every output
            w = text_width(plain(s), size, mono)
            left = x - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
            if left < -TEXT_SLACK or left + w > self.width + TEXT_SLACK:
                raise FigureError(f"text {plain(s)!r} at x={num(x)} runs past the {'left' if left < 0 else 'right'} edge "
                                  f"(about {num(left)}…{num(left + w)} of 0…{num(self.width)}): move it, shorten it or "
                                  "widen the figure")
            if y - size * (0.5 if middle else 0.9) < -TEXT_SLACK or y + size * (0.5 if middle else 0.25) > self.height + TEXT_SLACK:
                raise FigureError(f"text {plain(s)!r} at y={num(y)} runs past the top or bottom edge (0…{num(self.height)})")
        attrs = [f'x="{num(x)}"', f'y="{num(y + (size * 0.36 if middle else 0))}"', f'font-size="{num(size)}"']
        cls = ["tf-" + role(color)]
        if mono:
            cls.append("tr-fig-mono")
            attrs.append(f'font-family="{FONT_MONO}"')
        if anchor != "start":
            attrs.append(f'text-anchor="{anchor}"')
        if weight:
            attrs.append(f'font-weight="{weight}"')
        if italic:
            attrs.append('font-style="italic"')
        if rotate:
            attrs.append(f'transform="rotate({num(-rotate)} {num(x)} {num(y)})"')
        if opacity is not None and opacity < 1:
            attrs.append(f'opacity="{num(opacity)}"')
        if halo:
            cls.append("ts-bg")
            attrs.append(f'stroke-width="{num(max(3.0, size * 0.28))}" stroke-linejoin="round" paint-order="stroke"')
        self.add(f'<text class="{" ".join(cls)}" {" ".join(attrs)}>{_spans(s)}</text>')

    def lines(self, x: float, y: float, rows: Sequence[str], *, size: float = 14.0, leading: float = 1.45, **kw) -> None:
        """Several lines of text, the first with its baseline at ``y``."""
        for i, row in enumerate(rows):
            self.text(x, y + i * size * leading, row, size=size, **kw)

    def chip(self, x: float, y: float, s: str, kind: str = "ink", *, size: float = 12.0, anchor: str = "start") -> float:
        """A small framed tag (``LEAN ✓``, ``OPEN`` …) in role ``kind``; returns its width. Use
        ``kind="lean"`` only for statements a chapter cites with ``lean=``."""
        w = text_width(plain(s), size, mono=True) + 14
        h = size + 9
        x0 = x - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
        self.rect(x0, y - h + 5, w, h, color=kind, fill=kind, fill_opacity=0.12, width=1.2)
        self.text(x0 + 7, y, s, size=size, color=kind, mono=True, weight=600)
        return w

    def legend(self, x: float, y: float, entries: Sequence[tuple[str, str]], *, size: float = 13.0, gap: float = 20.0,
               swatch: str = "line") -> None:
        """Rows of ``(role, text)``: a swatch in the role's colour and what it stands for."""
        for i, (c, label) in enumerate(entries):
            yy = y + i * gap
            if swatch == "dot":
                self.dot(x + 9, yy - size * 0.32, 4.2, c)
            elif swatch == "box":
                self.rect(x + 2, yy - size * 0.82, 14, 12, color=c, fill=c, fill_opacity=0.3, width=1.2)
            else:
                self.line(x, yy - size * 0.32, x + 18, yy - size * 0.32, c, 2.6)
            self.text(x + 26, yy, label, size=size, color="dim")

    # ------------------------------------------------------------------ marks

    def angle(self, cx: float, cy: float, r: float, a0: float, a1: float, label: str = "", *, color: str = "dim",
              size: float = 14.0, width: float = 1.4, label_r: float | None = None, **kw) -> None:
        """An angle mark at ``(cx, cy)`` from ``a0`` to ``a1`` degrees, with its label on the bisector."""
        self.arc(cx, cy, r, a0, a1, color, width, **kw)
        if label:
            mid = math.radians((a0 + a1) / 2)
            lr = (r + size * 0.85) if label_r is None else label_r
            self.text(cx + lr * math.cos(mid), cy - lr * math.sin(mid), label, size=size, color=color, anchor="middle", middle=True)

    def right_angle(self, x: float, y: float, a: float, size: float = 9.0, color: str = "dim", width: float = 1.2) -> None:
        """The small square of a right angle at ``(x, y)`` between directions ``a`` and ``a + 90`` degrees."""
        u = (math.cos(math.radians(a)), -math.sin(math.radians(a)))
        v = (math.cos(math.radians(a + 90)), -math.sin(math.radians(a + 90)))
        self.polyline([(x + u[0] * size, y + u[1] * size), (x + (u[0] + v[0]) * size, y + (u[1] + v[1]) * size),
                       (x + v[0] * size, y + v[1] * size)], color, width)

    def cross(self, x: float, y: float, size: float = 8.0, color: str = "dim", width: float = 1.8) -> None:
        """A cross centred at ``(x, y)``: something struck out or ruled out."""
        self.line(x - size, y - size, x + size, y + size, color, width, cap="round")
        self.line(x - size, y + size, x + size, y - size, color, width, cap="round")

    def brace(self, x1: float, y1: float, x2: float, y2: float, label: str = "", *, color: str = "dim", size: float = 13.0,
              depth: float = 8.0) -> None:
        """A bracket from ``(x1, y1)`` to ``(x2, y2)`` bulging to its left-hand side, labelled at the tip."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        nx, ny = dy / length, -dx / length
        a = (x1 + nx * depth, y1 + ny * depth)
        b = (x2 + nx * depth, y2 + ny * depth)
        self.polyline([(x1, y1), a, b, (x2, y2)], color, 1.3)
        if label:
            mx, my = (a[0] + b[0]) / 2 + nx * (size * 0.9), (a[1] + b[1]) / 2 + ny * (size * 0.9)
            anchor = "middle" if abs(nx) < 0.5 else ("start" if nx > 0 else "end")
            self.text(mx, my, label, size=size, color=color, anchor=anchor, middle=True)

    # ------------------------------------------------------------------ composites

    def axes(self, x: float, y: float, w: float, h: float, xr: tuple[float, float], yr: tuple[float, float]) -> "Axes":
        """A plot area mapping data ``xr × yr`` onto the rectangle ``(x, y, w, h)``."""
        return Axes(self, x, y, w, h, xr, yr)

    def sphere(self, cx: float, cy: float, r: float, *, az: float = 110.0, el: float = 16.0) -> "Sphere":
        """A unit sphere drawn with radius ``r``: +z up, and with the default view (azimuth ``az``,
        elevation ``el``, degrees) +x towards the reader and down to the left, +y to the right."""
        return Sphere(self, cx, cy, r, az, el)

    def markup(self) -> str:
        return "\n".join(self.items)


class Panel(Canvas):
    """A part of a figure with its own origin. In a figure made with ``wrap=True`` the panels sit side
    by side where there is room and stack on a narrow screen."""

    def __init__(self, fig: "Figure", x: float, y: float, width: float, height: float):
        super().__init__(fig, width, height)
        self.x = float(x)
        self.y = float(y)


class Figure(Canvas):
    """One figure in one language. ``alt`` is what a reader who cannot see the figure is told."""

    def __init__(self, name: str, lang: str, width: float, height: float, *, alt: str = "", wrap: bool = False):
        if width > MAX_WIDTH:
            raise FigureError(f"figure {name}: width {width} exceeds {MAX_WIDTH}; split it into panels or figures")
        if width <= 0 or height <= 0:
            raise FigureError(f"figure {name}: empty size {width}×{height}")
        super().__init__(self, width, height)
        self.name = name
        self._lang = lang
        self.alt = alt
        self.wrap = wrap
        self.panels: list[Panel] = []

    @property
    def lang(self) -> str:
        return self._lang

    def t(self, zh: str, en: str | None = None, **more: str) -> str:
        table = {"zh": zh, "en": en if en is not None else zh, **more}
        return table.get(self._lang) or table.get("en") or zh

    def panel(self, x: float, y: float, width: float, height: float) -> Panel:
        """A panel at ``(x, y)``; draw on what this returns."""
        p = Panel(self, x, y, width, height)
        self.panels.append(p)
        self.items.append(p)  # type: ignore[arg-type]  # placeholder keeps the drawing order
        return p

    def row(self, widths: Sequence[float], height: float, *, gap: float = 16.0, y: float = 0.0) -> list[Panel]:
        """Panels of the given widths in one row, centred in the figure."""
        total = sum(widths) + gap * (len(widths) - 1)
        x = (self.width - total) / 2
        out = []
        for w in widths:
            out.append(self.panel(x, y, w, height))
            x += w + gap
        return out

    def svg(self) -> str:
        """The canonical SVG: role classes, both palettes in its style sheet (:func:`tbook.figure.style_sheet`)."""
        from . import figure

        if self.wrap and any(not isinstance(it, Panel) for it in self.items):
            raise FigureError(f"figure {self.name}: with wrap=True everything is drawn on panels (they are laid out "
                              "separately on a narrow screen)")
        body: list[str] = []
        for it in self.items:
            if isinstance(it, Panel):
                body.append(f'<svg class="tr-fig-panel" x="{num(it.x)}" y="{num(it.y)}" width="{num(it.width)}" '
                            f'height="{num(it.height)}" viewBox="0 0 {num(it.width)} {num(it.height)}">')
                body.append(it.markup())
                body.append("</svg>")
            else:
                body.append(it)
        alt = self.alt.strip()
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" class="tr-fig" data-tr-fig="{esc(self.name)}" '
                f'data-lang="{esc(self._lang)}"' + (' data-wrap="1"' if self.wrap else "") +
                f' viewBox="0 0 {num(self.width)} {num(self.height)}" width="{num(self.width)}" height="{num(self.height)}" '
                f'font-family="{FONT_BODY}" role="img"' + (f' aria-label="{esc(alt)}"' if alt else "") + ">")
        parts = [head]
        if alt:
            parts.append(f"<title>{esc(alt)}</title>")
        parts.append(figure.style_sheet())
        parts.extend(p for p in body if p)
        parts.append("</svg>")
        return "\n".join(parts) + "\n"


class Axes:
    """A plot area: data coordinates in, canvas coordinates out."""

    def __init__(self, cv: Canvas, x: float, y: float, w: float, h: float, xr: tuple[float, float], yr: tuple[float, float]):
        self.cv, self.x, self.y, self.w, self.h = cv, x, y, w, h
        self.xr, self.yr = xr, yr

    def X(self, v: float) -> float:
        return self.x + (v - self.xr[0]) / (self.xr[1] - self.xr[0]) * self.w

    def Y(self, v: float) -> float:
        return self.y + self.h - (v - self.yr[0]) / (self.yr[1] - self.yr[0]) * self.h

    def pt(self, x: float, y: float) -> Point:
        return self.X(x), self.Y(y)

    def frame(self, color: str = "edge", width: float = 1.2) -> None:
        self.cv.rect(self.x, self.y, self.w, self.h, color=color, width=width)

    def xaxis(self, at: float | None = None, *, ticks: Sequence[float] = (), labels: Sequence[str] | None = None, label: str = "",
              color: str = "dim", size: float = 12.0, arrow: bool = False, fmt: Callable[[float], str] | None = None) -> None:
        """The horizontal axis at data height ``at`` (the bottom edge by default) with ticks and a label."""
        y = self.Y(self.yr[0] if at is None else at)
        if arrow:
            self.cv.arrow(self.x, y, self.x + self.w + 8, y, color, 1.3, head=7)
        else:
            self.cv.line(self.x, y, self.x + self.w, y, color, 1.3)
        for i, v in enumerate(ticks):
            self.cv.line(self.X(v), y, self.X(v), y + 5, color, 1.2)
            s = labels[i] if labels else (fmt(v) if fmt else num(v))
            if s:
                self.cv.text(self.X(v), y + 5 + size, s, size=size, color=color, anchor="middle")
        if label:
            self.cv.text(self.x + self.w, y + (5 + size * 2.25 if ticks else size * 1.4), label, size=max(size, 13), color=color, anchor="end")

    def yaxis(self, at: float | None = None, *, ticks: Sequence[float] = (), labels: Sequence[str] | None = None, label: str = "",
              color: str = "dim", size: float = 12.0, arrow: bool = False, fmt: Callable[[float], str] | None = None) -> None:
        """The vertical axis at data abscissa ``at`` (the left edge by default) with ticks and a label."""
        x = self.X(self.xr[0] if at is None else at)
        if arrow:
            self.cv.arrow(x, self.y + self.h, x, self.y - 8, color, 1.3, head=7)
        else:
            self.cv.line(x, self.y, x, self.y + self.h, color, 1.3)
        for i, v in enumerate(ticks):
            self.cv.line(x - 5, self.Y(v), x, self.Y(v), color, 1.2)
            s = labels[i] if labels else (fmt(v) if fmt else num(v))
            if s:
                self.cv.text(x - 8, self.Y(v), s, size=size, color=color, anchor="end", middle=True)
        if label:
            self.cv.text(x + 6, self.y + max(size, 13) * 0.4, label, size=max(size, 13), color=color)

    def grid(self, xs: Sequence[float] = (), ys: Sequence[float] = (), color: str = "faint", width: float = 1.0,
             dash: str | None = "2 4") -> None:
        for v in xs:
            self.cv.line(self.X(v), self.y, self.X(v), self.y + self.h, color, width, dash=dash)
        for v in ys:
            self.cv.line(self.x, self.Y(v), self.x + self.w, self.Y(v), color, width, dash=dash)

    def plot(self, fn: Callable[[float], float], x0: float | None = None, x1: float | None = None, n: int = 160,
             color: str = "cyan", width: float = 2.0, **kw) -> None:
        """The graph of ``fn`` over ``[x0, x1]`` (the whole x range by default), clipped to the y range."""
        x0 = self.xr[0] if x0 is None else x0
        x1 = self.xr[1] if x1 is None else x1
        lo, hi = min(self.yr), max(self.yr)
        seg: list[Point] = []
        for i in range(n + 1):
            xv = x0 + (x1 - x0) * i / n
            try:
                yv = fn(xv)
            except (ValueError, ZeroDivisionError, OverflowError):
                yv = float("nan")
            if yv != yv or yv < lo - 1e-9 or yv > hi + 1e-9:
                if len(seg) > 1:
                    self.cv.polyline(seg, color, width, **kw)
                seg = []
                continue
            seg.append(self.pt(xv, yv))
        if len(seg) > 1:
            self.cv.polyline(seg, color, width, **kw)

    def points(self, pts: Iterable[Point], color: str = "cyan", r: float = 3.2, **kw) -> None:
        for x, y in pts:
            self.cv.dot(self.X(x), self.Y(y), r, color, **kw)

    def path(self, pts: Iterable[Point], color: str | None = "cyan", width: float = 2.0, **kw) -> None:
        self.cv.polyline([self.pt(x, y) for x, y in pts], color, width, **kw)

    def area(self, pts: Iterable[Point], fill: str = "cyan", *, base: float | None = None, fill_opacity: float = 0.18, **kw) -> None:
        """The region between the polyline ``pts`` and the height ``base`` (the bottom of the y range)."""
        pts = list(pts)
        if not pts:
            return
        b = self.yr[0] if base is None else base
        poly = [self.pt(pts[0][0], b)] + [self.pt(x, y) for x, y in pts] + [self.pt(pts[-1][0], b)]
        self.cv.polygon(poly, fill, fill_opacity=fill_opacity, **kw)

    def hline(self, y: float, color: str = "dim", width: float = 1.3, **kw) -> None:
        self.cv.line(self.x, self.Y(y), self.x + self.w, self.Y(y), color, width, **kw)

    def vline(self, x: float, color: str = "dim", width: float = 1.3, **kw) -> None:
        self.cv.line(self.X(x), self.y, self.X(x), self.y + self.h, color, width, **kw)

    def text(self, x: float, y: float, s: str, *, dx: float = 0, dy: float = 0, **kw) -> None:
        self.cv.text(self.X(x) + dx, self.Y(y) + dy, s, **kw)


Vec = tuple[float, float, float]


def unit(v: Sequence[float]) -> Vec:
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot3(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sph(theta: float, phi: float = 0.0) -> Vec:
    """The unit vector at polar angle ``theta`` from +z and azimuth ``phi`` from +x (degrees)."""
    t, p = math.radians(theta), math.radians(phi)
    return (math.sin(t) * math.cos(p), math.sin(t) * math.sin(p), math.cos(t))


def slerp(a: Sequence[float], b: Sequence[float], s: float) -> Vec:
    """The point a fraction ``s`` of the way along the great-circle arc from ``a`` to ``b``."""
    a, b = unit(a), unit(b)
    w = math.acos(max(-1.0, min(1.0, dot3(a, b))))
    if w < 1e-9:
        return a
    k = math.sin(w)
    ca, cb = math.sin((1 - s) * w) / k, math.sin(s * w) / k
    return (ca * a[0] + cb * b[0], ca * a[1] + cb * b[1], ca * a[2] + cb * b[2])


def rotate(v: Sequence[float], axis: Sequence[float], angle: float) -> Vec:
    """``v`` turned by ``angle`` degrees about ``axis`` (right-handed)."""
    k = unit(axis)
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    kv = cross(k, v)
    kd = dot3(k, v)
    return tuple(v[i] * c + kv[i] * s + k[i] * kd * (1 - c) for i in range(3))  # type: ignore[return-value]


class Sphere:
    """A sphere drawn in orthographic projection: +z is up on the page, the view is turned by ``az``
    about z and tilted by ``el``. Curves on the far side are dashed and fainter."""

    def __init__(self, cv: Canvas, cx: float, cy: float, r: float, az: float, el: float):
        self.cv, self.cx, self.cy, self.r = cv, cx, cy, r
        a, e = math.radians(az), math.radians(el)
        # camera basis: right, up, towards the viewer. az = 0, el = 0 looks along +y with x to the right.
        self.right: Vec = (math.cos(a), math.sin(a), 0.0)
        self.toward: Vec = (math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))
        self.up: Vec = cross(self.toward, self.right)

    def proj(self, v: Sequence[float], scale: float = 1.0) -> tuple[float, float, float]:
        """Canvas ``(x, y)`` of the point ``scale · v`` and its depth (positive towards the viewer)."""
        return (self.cx + self.r * scale * dot3(v, self.right), self.cy - self.r * scale * dot3(v, self.up),
                scale * dot3(v, self.toward))

    def xy(self, v: Sequence[float], scale: float = 1.0) -> Point:
        x, y, _ = self.proj(v, scale)
        return x, y

    def outline(self, color: str = "dim", width: float = 1.5, *, fill: str | None = "cyan", fill_opacity: float = 0.04) -> None:
        self.cv.circle(self.cx, self.cy, self.r, color=color, fill=fill, width=width, fill_opacity=fill_opacity)

    def curve(self, pts: Sequence[Sequence[float]], color: str = "ink", width: float = 1.8, *, back: bool = True,
              scale: float = 1.0, dash_back: str = "4 4", back_opacity: float = 0.55, **kw) -> None:
        """The curve through the 3-vectors ``pts``: solid where it faces the viewer, dashed behind."""
        runs: list[tuple[bool, list[Point]]] = []
        for v in pts:
            x, y, d = self.proj(v, scale)
            front = d >= -1e-9
            if runs and runs[-1][0] == front:
                runs[-1][1].append((x, y))
            else:
                if runs:  # join the two runs at the limb
                    runs[-1][1].append((x, y))
                runs.append((front, [(x, y)]))
        for front, run in runs:
            if front:
                self.cv.polyline(run, color, width, **kw)
            elif back:
                self.cv.polyline(run, color, max(MIN_STROKE, width * 0.75), dash=dash_back, opacity=back_opacity)

    def great_circle(self, normal: Sequence[float], color: str = "faint", width: float = 1.3, **kw) -> None:
        """The great circle perpendicular to ``normal``."""
        n = unit(normal)
        a = unit(cross(n, (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0)))
        b = cross(n, a)
        self.curve([tuple(a[i] * math.cos(t) + b[i] * math.sin(t) for i in range(3))
                    for t in (2 * math.pi * k / 120 for k in range(121))], color, width, **kw)

    def small_circle(self, axis: Sequence[float], angle: float, color: str = "faint", width: float = 1.3, **kw) -> None:
        """The circle of points at ``angle`` degrees from ``axis`` (a latitude circle when the axis is z)."""
        n = unit(axis)
        a = unit(cross(n, (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0)))
        b = cross(n, a)
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        self.curve([tuple(n[i] * c + s * (a[i] * math.cos(t) + b[i] * math.sin(t)) for i in range(3))
                    for t in (2 * math.pi * k / 120 for k in range(121))], color, width, **kw)

    def arc(self, u: Sequence[float], v: Sequence[float], color: str = "ink", width: float = 2.0, *, n: int = 48,
            arrow: bool = False, **kw) -> None:
        """The shorter great-circle arc from ``u`` to ``v``."""
        pts = [slerp(u, v, i / n) for i in range(n + 1)]
        self.curve(pts, color, width, **kw)
        if arrow:
            (xa, ya), (xb, yb) = self.xy(pts[-2]), self.xy(pts[-1])
            self.cv.arrow_head(xb, yb, math.degrees(math.atan2(-(yb - ya), xb - xa)), color, head=8)

    def path(self, pts: Sequence[Sequence[float]], color: str = "ink", width: float = 2.0, *, arrow: bool = False, **kw) -> None:
        """A path through unit vectors, joined by great-circle arcs."""
        full: list[Vec] = []
        for a, b in zip(pts, pts[1:]):
            full.extend(slerp(a, b, i / 24) for i in range(24))
        full.append(unit(pts[-1]))
        self.curve(full, color, width, **kw)
        if arrow and len(full) > 1:
            (xa, ya), (xb, yb) = self.xy(full[-2]), self.xy(full[-1])
            self.cv.arrow_head(xb, yb, math.degrees(math.atan2(-(yb - ya), xb - xa)), color, head=8)

    def arrow(self, v: Sequence[float], color: str = "ink", width: float = 2.2, *, scale: float = 1.0, start: float = 0.0,
              **kw) -> None:
        """An arrow from the centre (from ``start · v``) to ``scale · v``."""
        x0, y0 = self.xy(v, start)
        x1, y1 = self.xy(v, scale)
        self.cv.arrow(x0, y0, x1, y1, color, width, **kw)

    def segment(self, a: Sequence[float], b: Sequence[float], color: str = "dim", width: float = 1.3, **kw) -> None:
        """The straight segment between two points of space (not along the surface)."""
        (x0, y0), (x1, y1) = self.xy(a), self.xy(b)
        self.cv.line(x0, y0, x1, y1, color, width, **kw)

    def dot(self, v: Sequence[float], color: str = "ink", r: float = 3.8, *, scale: float = 1.0, **kw) -> None:
        x, y = self.xy(v, scale)
        self.cv.dot(x, y, r, color, **kw)

    def label(self, v: Sequence[float], s: str, *, dx: float = 0, dy: float = 0, scale: float = 1.0, **kw) -> None:
        """Text at the projection of ``scale · v``, offset by ``(dx, dy)`` canvas units."""
        x, y = self.xy(v, scale)
        self.cv.text(x + dx, y + dy, s, **kw)

    def axes(self, color: str = "faint", width: float = 1.2, *, length: float = 1.0, labels: Sequence[str] | None = None,
             size: float = 13.0) -> None:
        """The three coordinate axes through the centre, optionally labelled at their positive ends."""
        for i, e in enumerate(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))):
            self.segment(tuple(-c * length for c in e), tuple(c * length for c in e), color, width, dash="3 3")
            if labels and labels[i]:
                self.label(e, labels[i], scale=length + 0.12, size=size, color="dim", anchor="middle", middle=True)

    def disc(self, normal: Sequence[float], fill: str = "magenta", *, fill_opacity: float = 0.12, color: str | None = None,
             width: float = 1.3, scale: float = 1.0) -> None:
        """The flat disc through the centre perpendicular to ``normal`` (a plane inside the ball)."""
        n = unit(normal)
        a = unit(cross(n, (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0)))
        b = cross(n, a)
        pts = [self.xy(tuple(a[i] * math.cos(t) + b[i] * math.sin(t) for i in range(3)), scale)
               for t in (2 * math.pi * k / 96 for k in range(96))]
        self.cv.polygon(pts, fill, color=color, width=width, fill_opacity=fill_opacity)
