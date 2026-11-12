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
import unicodedata
from typing import Callable, Iterable, Sequence

MIN_FONT = 12.0
MIN_STROKE = 1.0
MAX_WIDTH = 760  # the text column of the HTML edition; wider figures are scaled down everywhere
TEXT_SLACK = 3.0  # how far the estimated extent of a label may pass the edge of its canvas
MONO_ADVANCE = 0.6  # the advance of every monospace character in em (JetBrains Mono, DejaVu Sans Mono, Menlo)

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
FONT_SERIF = "'Noto Serif SC', 'Noto Serif', 'Times New Roman', serif"  # italic I with serifs (MARKUP = 2)

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
    # libm may put the same geometric coordinate on either side of a half-cent.
    # Remove that noise before rounding to the SVG's visible precision.
    s = f"{round(float(v), 10):.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def esc(text: str) -> str:
    # "$" would open a formula for the HTML edition's math pass; "\\" its escape
    return html.escape(str(text), quote=True).replace("$", "&#36;").replace("\\", "&#92;")


_WIDE = re.compile("[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")  # CJK with its punctuation, Hangul, full-width forms


def text_width(text: str, size: float = 14.0, mono: bool = False) -> float:
    """Estimated advance of ``text`` (plain, markup already removed) at ``size``. Monospace text
    counts :data:`MONO_ADVANCE` per character (combining marks, which add no advance, count nothing)."""
    w = 0.0
    for ch in text:
        if mono and unicodedata.combining(ch):
            continue
        if _WIDE.match(ch):
            w += 1.0
        elif mono:
            w += MONO_ADVANCE
        elif ch in "iljtfI.,:;'|!()[] ":
            w += 0.32
        elif ch in "mwMW@":
            w += 0.86
        elif ch.isupper() or ch.isdigit():
            w += 0.62
        else:
            w += 0.54
    return w * size


# ``*x*`` italic, ``_{i}`` subscript, ``^{2}`` superscript, ``**b**`` bold, ``***x***`` bold italic,
# ``\\bar{z}`` a letter with a bar over it; ``\*`` etc. are literal.
_MARK = re.compile(r"\\(?P<esc>[*_^{}\\])|\\bar\{(?P<bar>.*?)\}|\*\*\*(?P<bi>.+?)\*\*\*|\*\*(?P<b>.+?)\*\*|"
                   r"\*(?P<i>.+?)\*|_\{(?P<sub>.*?)\}|\^\{(?P<sup>.*?)\}", re.S)


def plain(markup: str) -> str:
    """``markup`` without its marks (for width estimates and accessible text)."""
    return _MARK.sub(lambda m: next((g for g in m.groups() if g is not None), ""), markup)


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
        if m.group("esc") is not None:
            emit(m.group("esc"))
        elif m.group("bar") is not None:
            emit(plain(m.group("bar")), ' text-decoration="overline"')
        elif m.group("bi") is not None:
            emit(plain(m.group("bi")), ' font-weight="700" font-style="italic"')
        elif m.group("b") is not None:
            emit(plain(m.group("b")), ' font-weight="700"')
        elif m.group("i") is not None:
            emit(plain(m.group("i")), ' font-style="italic"')
        elif m.group("sub") is not None:
            emit(plain(m.group("sub")), ' font-size="72%"', 0.28)
        else:
            emit(plain(m.group("sup")), ' font-size="72%"', -0.42)
        pos = m.end()
    emit(markup[pos:])
    if abs(pending) > 1e-9:  # restore the baseline for whatever follows in the same <text>
        out.append(f'<tspan dy="{num(-pending)}em">​</tspan>')
    return "".join(out)


# ---------------------------------------------------------------- markup level 2 (a script's ``MARKUP = 2``)
#
# The same marks, parsed as a tree: ``*W*_{*i*+1}`` keeps the italic inside the subscript, a script may hold
# a script, ``\bar{z}`` may hold marks, and an italic capital I is set in a serif face so that it does not
# read as a slanted stroke. Level 1 (the default) is the flat reading above and stays byte for byte as it was.

_Style = tuple[bool, bool, bool, float, float]  # bold, italic, overline, scale, baseline shift (em of the text)
_BASE: _Style = (False, False, False, 1.0, 0.0)
SCRIPT_SCALE = 0.72


def _brace(s: str, i: int) -> int:
    """The index of the ``}`` matching the ``{`` at ``s[i]`` (escapes skipped), or -1."""
    depth = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _closing(s: str, i: int, delim: str) -> int:
    """The index of the ``delim`` that closes an emphasis opened just before ``s[i]``, or -1. Groups in
    braces are skipped, and an italic skips a bold inside it."""
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            j = _brace(s, i)
            if j < 0:
                return -1
            i = j + 1
            continue
        if s.startswith(delim, i):
            if delim == "*" and s.startswith("**", i):
                j = _closing(s, i + 2, "**")
                if j < 0:
                    return -1
                i = j + 2
                continue
            return i
        i += 1
    return -1


def _atom(s: str, i: int) -> tuple[int, str | None, str, int]:
    """The construct starting at ``s[i]``: (end, kind, inner, inner start); kind None is one plain character."""
    c = s[i]
    if c == "\\":
        if s.startswith("\\bar{", i):
            j = _brace(s, i + 4)
            if j >= 0:
                return j + 1, "bar", s[i + 5:j], i + 5
        if i + 1 < len(s) and s[i + 1] in "*_^{}\\":
            return i + 2, "esc", s[i + 1], i + 1
    elif c == "*":
        for delim, kind in (("***", "bi"), ("**", "b"), ("*", "i")):
            if s.startswith(delim, i):
                j = _closing(s, i + len(delim), delim)
                if j > i + len(delim):
                    return j + len(delim), kind, s[i + len(delim):j], i + len(delim)
                if j >= 0:  # an empty emphasis like ``**`` is two literal stars
                    break
    elif c in "_^" and s.startswith("{", i + 1):
        j = _brace(s, i + 1)
        if j >= 0:
            return j + 1, "sub" if c == "_" else "sup", s[i + 2:j], i + 2
    return i + 1, None, c, i


def _runs(s: str, st: _Style = _BASE) -> list[tuple[str, _Style]]:
    """``s`` as runs of text with one style each, in order."""
    out: list[tuple[str, _Style]] = []
    buf: list[str] = []
    bold, italic, over, scale, shift = st

    def flush() -> None:
        if buf:
            out.append(("".join(buf), st))
            buf.clear()

    i = 0
    while i < len(s):
        end, kind, inner, _ = _atom(s, i)
        if kind is None or kind == "esc":
            buf.append(inner)
        else:
            flush()
            if kind == "bar":
                out.extend(_runs(inner, (bold, italic, True, scale, shift)))
            elif kind == "bi":
                out.extend(_runs(inner, (True, True, over, scale, shift)))
            elif kind == "b":
                out.extend(_runs(inner, (True, italic, over, scale, shift)))
            elif kind == "i":
                out.extend(_runs(inner, (bold, True, over, scale, shift)))
            else:
                small = scale * SCRIPT_SCALE
                out.extend(_runs(inner, (bold, italic, over, small, shift + (0.28 if kind == "sub" else -0.42) * small)))
        i = end
    flush()
    return out


def plain_nested(markup: str) -> str:
    """:func:`plain` for level-2 markup (marks inside scripts and bars removed as well)."""
    return "".join(text for text, _ in _runs(markup))


def _spans2(markup: str, mono: bool = False) -> str:
    """The inside of a ``<text>`` for level-2 ``markup``. Every run is a sibling ``<tspan>``: its size is a
    percentage of the text's, and its ``dy`` (in its own em) moves the baseline to the run's shift."""
    out: list[str] = []
    pending = 0.0  # the baseline shift in force, in em of the text
    for text, (bold, italic, over, scale, shift) in _runs(markup):
        pieces = [(text, False)]
        if italic and not mono and "I" in text:  # a serif I: a sans-serif italic I reads as a slash
            pieces = [(p, p == "I") for p in re.split("(I)", text) if p]
        for piece, serif in pieces:
            dy = shift - pending
            pending = shift
            attrs: list[str] = []
            if abs(dy) > 1e-9:
                attrs.append(f'dy="{num(dy / scale)}em"')
            if abs(scale - 1) > 1e-9:
                attrs.append(f'font-size="{num(scale * 100)}%"')
            if bold:
                attrs.append('font-weight="700"')
            if italic:
                attrs.append('font-style="italic"')
            if over:
                attrs.append('text-decoration="overline"')
            if serif:
                attrs.append(f'font-family="{FONT_SERIF}"')
            out.append(f"<tspan {' '.join(attrs)}>{esc(piece)}</tspan>" if attrs else esc(piece))
    if abs(pending) > 1e-9:
        out.append(f'<tspan dy="{num(-pending)}em">​</tspan>')
    return "".join(out)


_NO_BREAK_BEFORE = set("，。、；：！？）》」』〉】”’,.;:!?)]}")


def wrap(markup: str, width: float, size: float = 14.0, *, mono: bool = False, level: int = 1) -> list[str]:
    """``markup`` broken into lines of at most ``width`` (estimated) at ``size``: at spaces, and between two
    CJK characters; never inside a mark, and never before closing punctuation. A word longer than
    ``width`` keeps a line of its own. A ``\\n`` in ``markup`` always breaks."""
    strip = plain_nested if level >= 2 else plain
    lines: list[str] = []
    for para in markup.split("\n"):
        tokens: list[tuple[bool, str]] = []  # (space before, token)
        space = False
        i = 0
        while i < len(para):
            end, kind, _, _ = _atom(para, i)
            piece = para[i:end]
            i = end
            if kind is None and piece == " ":
                space = True
                continue
            wide = kind is None and _WIDE.match(piece) is not None
            after_wide = bool(tokens) and _WIDE.match(tokens[-1][1][-1]) is not None
            breakable = space or ((wide or after_wide) and piece not in _NO_BREAK_BEFORE)
            if tokens and not breakable:
                tokens[-1] = (tokens[-1][0], tokens[-1][1] + piece)
            else:
                tokens.append((space, piece))
            space = False
        line = ""
        for sp, tok in tokens:
            cand = line + (" " if sp and line else "") + tok
            if line and text_width(strip(cand), size, mono) > width:
                lines.append(line)
                line = tok
            else:
                line = cand
        lines.append(line)
    return lines


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

    def _plain(self, s: str) -> str:
        return plain_nested(s) if self.fig.markup >= 2 else plain(s)

    def _tspans(self, s: str, mono: bool = False) -> str:
        return _spans2(s, mono) if self.fig.markup >= 2 else _spans(s)

    def measure(self, s: str, size: float = 14.0, *, mono: bool = False) -> float:
        """The estimated width of the label ``s`` (markup read as this figure reads it) at ``size``."""
        return text_width(self._plain(s), size, mono)

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
        n = max(8, int(round(abs(a1 - a0), 10) / 4))
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
            w = text_width(self._plain(s), size, mono)
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
        self.add(f'<text class="{" ".join(cls)}" {" ".join(attrs)}>{self._tspans(s, mono)}</text>')

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

    # ------------------------------------------------------------------ diagrams: boxes, links, bounces

    def box(self, x: float, y: float, text: str, kind: str = "edge", *, note: str | None = None, dashed: bool = False,
            chip: str | None = None, anchor: str = "middle", w: float | None = None, wrap: float | None = None,
            size: float = 14.0, note_size: float = 13.0, note_mono: bool = True, pad: float = 14.0,
            rx: float | None = None, chip_size: float = 12.0) -> "Box":
        """A framed box for a flow chart, its top at ``y`` and ``x`` its centre (its left edge with
        ``anchor="start"``, its right edge with ``"end"``); returns its :class:`Box` for :meth:`link`.

        ``text`` is what the box says (``\\n`` breaks a line; with ``wrap`` or ``w`` long text is broken
        to fit), ``note`` a second, smaller line in monospace (the lemma or tactic of a proof step).
        ``kind`` is the role: a neutral role (``edge``, the default) draws a solid panel with ink text,
        an accent role (``lean``, ``cyan`` …) a tinted box with text in that role; ``dashed=True`` an
        unfilled dashed pill (a hypothesis, an input). ``chip`` puts a tag such as ``"LEAN ✓"`` before
        the first line (only on a statement the chapter cites with ``lean=``), at ``chip_size``.

        The defaults (14, 13, a 12 chip) are made for a chart at most 358 wide, a phone's text column,
        where nothing is scaled down; on a wider canvas raise them so that ``size × 358 / width`` stays
        at least 10 (see skills/book-figure), or stack the chart into a narrow column."""
        r = role(kind)
        neutral = r in ("edge", "ink", "dim", "faint", "panel", "bg", "sheet", "hot")
        chip_w = text_width(chip, chip_size, mono=True) + 14 + 8 if chip else 0.0
        limit = wrap if wrap is not None else (w - 2 * pad if w is not None else None)
        lines = (self.wrap_text(text, limit - chip_w, size) if limit is not None else text.split("\n")) if text else []
        notes = (self.wrap_text(note, limit, note_size, mono=note_mono) if limit is not None else note.split("\n")) if note else []
        lh, nlh, py = size * 1.35, note_size * 1.35, 7.0
        h = 2 * py + len(lines) * lh + len(notes) * nlh
        inner = max([self.measure(s, size) + (chip_w if i == 0 else 0) for i, s in enumerate(lines)] +
                    [self.measure(s, note_size, mono=note_mono) for s in notes] + [chip_w])
        bw = w if w is not None else inner + 2 * pad
        if anchor not in ("start", "middle", "end"):
            raise FigureError(f"anchor must be start, middle or end, not {anchor!r}")
        x0 = x - (bw if anchor == "end" else bw / 2 if anchor == "middle" else 0)
        if dashed:
            self.rect(x0, y, bw, h, color="dim" if r == "edge" else kind, width=1.2, dash="4 3",
                      rx=min(h / 2, 14.0) if rx is None else rx)
        elif neutral:
            self.rect(x0, y, bw, h, color="edge" if r == "panel" else kind, fill="panel", width=1.3, rx=6 if rx is None else rx)
        else:
            self.rect(x0, y, bw, h, color=kind, fill=kind, fill_opacity=0.10, width=1.6, rx=6 if rx is None else rx)
        ink = ("dim" if dashed else "ink") if neutral else kind
        cx = x0 + bw / 2
        for i, s in enumerate(lines):
            ym = y + py + (i + 0.5) * lh
            if i == 0 and chip:
                left = cx - (chip_w + self.measure(s, size)) / 2
                self.chip(left, ym + chip_size / 2 - 0.5, chip, kind, size=chip_size)
                self.text(left + chip_w, ym, s, size=size, color=ink, middle=True)
            else:
                self.text(cx, ym, s, size=size, color=ink, anchor="middle", middle=True)
        for i, s in enumerate(notes):
            self.text(cx, y + py + len(lines) * lh + (i + 0.5) * nlh, s, size=note_size, color="dim", mono=note_mono,
                      anchor="middle", middle=True)
        return Box(x0, y, bw, h)

    def wrap_text(self, s: str, width: float, size: float = 14.0, *, mono: bool = False) -> list[str]:
        """The label ``s`` broken into lines of at most ``width`` at ``size`` (see :func:`wrap`)."""
        return wrap(s, width, size, mono=mono, level=self.fig.markup)

    def link(self, a: "Box | Point", b: "Box | Point", color: str = "dim", width: float = 1.4, *,
             elbow: bool | str = False, dash: str | None = None, head: float = 7.0, label: str | None = None,
             side: str = "right", size: float = 13.0, inset: float = 12.0) -> list[Point]:
        """An arrow from ``a`` to ``b``, each a :class:`Box` or a point; returns the path drawn.

        Between boxes the arrow runs straight from the facing sides: one above the other it leaves the
        bottom and enters the top (vertically wherever the two overlap, at least ``inset`` from a
        corner), side by side it runs from side to side, otherwise along the line of centres.
        ``elbow=True`` (or ``"hv"``) leaves ``a`` sideways and enters ``b`` from above or below (straight
        down when ``b``'s centre is under ``a``); ``elbow="vh"`` leaves ``a`` downwards or upwards and
        enters ``b`` from the side (straight across when ``b``'s middle is beside ``a``). ``label`` is
        written beside the middle of the longest leg, on ``side`` (right, left, above, below)."""
        A, B = _as_box(a), _as_box(b)
        pts: list[Point]
        if elbow:
            mode = "hv" if elbow is True else str(elbow)
            if mode not in ("hv", "vh"):
                raise FigureError(f"elbow must be True, 'hv' or 'vh', not {elbow!r}")
            if mode == "hv" and A.x < B.cx < A.x + A.w:  # b is under (or over) a: straight down (up) at b's centre
                pts = [(B.cx, A.y + A.h if B.cy > A.cy else A.y), (B.cx, B.y if B.cy > A.cy else B.y + B.h)]
            elif mode == "vh" and A.y < B.cy < A.y + A.h:  # b is beside a: straight across at b's middle
                pts = [(A.x + A.w if B.cx > A.cx else A.x, B.cy), (B.x if B.cx > A.cx else B.x + B.w, B.cy)]
            elif mode == "hv":
                xa = A.x + A.w if B.cx > A.cx else A.x
                yb = B.y if B.cy > A.cy else B.y + B.h
                pts = [(xa, A.cy), (B.cx, A.cy), (B.cx, yb)]
            else:
                ya = A.y + A.h if B.cy > A.cy else A.y
                xb = B.x if B.cx > A.cx else B.x + B.w
                pts = [(A.cx, ya), (A.cx, B.cy), (xb, B.cy)]
            self.curve_arrow(pts, color, width, head=head, dash=dash)
        else:
            pts = list(_facing(A, B, inset))
            self.arrow(pts[0][0], pts[0][1], pts[1][0], pts[1][1], color, width, head=head, dash=dash)
        if label:
            (x1, y1), (x2, y2) = max(zip(pts, pts[1:]), key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            if side == "right":
                self.text(mx + 8, my, label, size=size, color="dim", middle=True)
            elif side == "left":
                self.text(mx - 8, my, label, size=size, color="dim", anchor="end", middle=True)
            elif side == "above":
                self.text(mx, my - 7, label, size=size, color="dim", anchor="middle")
            elif side == "below":
                self.text(mx, my + 7 + size * 0.8, label, size=size, color="dim", anchor="middle")
            else:
                raise FigureError(f"side must be right, left, above or below, not {side!r}")
        return pts

    def bounce(self, a: Point, m: Point, b: Point, color: str = "dim", width: float = 1.4, *, gap: float = 0.0,
               head: float = 7.0, **kw) -> None:
        """A ray from ``a`` that meets a mirror at ``m`` and goes on to ``b``: one bent arrow, its two ends
        pulled back by ``gap`` (to stop short of the dots at ``a`` and ``b``), the head at ``b``."""
        def pull(p: Point, q: Point) -> Point:
            d = math.hypot(q[0] - p[0], q[1] - p[1])
            k = min(gap / d, 0.45) if d > 1e-9 else 0.0
            return (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)

        self.curve_arrow([pull(a, m), m, pull(b, m)], color, width, head=head, **kw)

    # ------------------------------------------------------------------ composites

    def axes(self, x: float, y: float, w: float, h: float, xr: tuple[float, float], yr: tuple[float, float], *,
             logx: bool = False, logy: bool = False) -> "Axes":
        """A plot area mapping data ``xr × yr`` onto the rectangle ``(x, y, w, h)``; ``logx``/``logy``
        make that axis logarithmic (ranges, points and ticks stay in data values)."""
        return Axes(self, x, y, w, h, xr, yr, logx=logx, logy=logy)

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

    def __init__(self, name: str, lang: str, width: float, height: float, *, alt: str = "", wrap: bool = False,
                 markup: int = 1):
        if markup not in (1, 2):
            raise FigureError(f"figure {name}: MARKUP must be 1 or 2, not {markup!r}")
        if width > MAX_WIDTH:
            raise FigureError(f"figure {name}: width {width} exceeds {MAX_WIDTH}; split it into panels or figures")
        if width <= 0 or height <= 0:
            raise FigureError(f"figure {name}: empty size {width}×{height}")
        super().__init__(self, width, height)
        self.name = name
        self._lang = lang
        self.alt = alt
        self.wrap = wrap
        self.markup = markup  # 2: marks nest inside scripts, a serif italic I (see _spans2)
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

    def __init__(self, cv: Canvas, x: float, y: float, w: float, h: float, xr: tuple[float, float], yr: tuple[float, float],
                 *, logx: bool = False, logy: bool = False):
        self.cv, self.x, self.y, self.w, self.h = cv, x, y, w, h
        self.xr, self.yr = xr, yr
        self.logx, self.logy = logx, logy
        for on, r, name in ((logx, xr, "x"), (logy, yr, "y")):
            if on and min(r) <= 0:
                raise FigureError(f"a logarithmic {name} axis needs a positive range, not {r}")

    def X(self, v: float) -> float:
        if self.logx:
            return self.x + (_log(v) - _log(self.xr[0])) / (_log(self.xr[1]) - _log(self.xr[0])) * self.w
        return self.x + (v - self.xr[0]) / (self.xr[1] - self.xr[0]) * self.w

    def Y(self, v: float) -> float:
        if self.logy:
            return self.y + self.h - (_log(v) - _log(self.yr[0])) / (_log(self.yr[1]) - _log(self.yr[0])) * self.h
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
        if self.logx and not ticks:  # decades, and short ticks at 2…9 between them
            ticks = self.decades("x")
            for v in self._minor("x"):
                self.cv.line(self.X(v), y, self.X(v), y + 3, color, 1.0)
        for i, v in enumerate(ticks):
            self.cv.line(self.X(v), y, self.X(v), y + 5, color, 1.2)
            s = labels[i] if labels else (fmt(v) if fmt else log_label(v) if self.logx else num(v))
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
        if self.logy and not ticks:
            ticks = self.decades("y")
            for v in self._minor("y"):
                self.cv.line(x - 3, self.Y(v), x, self.Y(v), color, 1.0)
        for i, v in enumerate(ticks):
            self.cv.line(x - 5, self.Y(v), x, self.Y(v), color, 1.2)
            s = labels[i] if labels else (fmt(v) if fmt else log_label(v) if self.logy else num(v))
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
            if self.logx:  # even steps in log x
                xv = 10 ** (_log(x0) + (_log(x1) - _log(x0)) * i / n)
            else:
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

    # ---- logarithmic axes, steps and bars

    def decades(self, axis: str = "x") -> list[float]:
        """The powers of ten in the range of a logarithmic axis (every second or third one when there are
        more than seven): the default ticks, and the lines to pass to :meth:`grid`."""
        lo, hi = sorted(self.xr if axis == "x" else self.yr)
        k0, k1 = math.ceil(_log(lo) - 1e-9), math.floor(_log(hi) + 1e-9)
        step = max(1, math.ceil((k1 - k0 + 1) / 7))
        return [10.0 ** k for k in range(k0, k1 + 1, step)]

    def _minor(self, axis: str) -> list[float]:
        lo, hi = sorted(self.xr if axis == "x" else self.yr)
        k0, k1 = math.floor(_log(lo)), math.ceil(_log(hi))
        if k1 - k0 > 6:
            return []
        return [m * 10.0 ** k for k in range(k0, k1) for m in range(2, 10) if lo <= m * 10.0 ** k <= hi]

    def step(self, pts: Iterable[Point], color: str = "cyan", width: float = 2.0, *, where: str = "post", **kw) -> None:
        """A staircase through ``pts``: each value holds until the next x (``where="post"``), or takes
        over from the previous x (``"pre"``), or changes half-way (``"mid"``)."""
        pts = list(pts)
        if where not in ("post", "pre", "mid"):
            raise FigureError(f"where must be post, pre or mid, not {where!r}")
        out: list[Point] = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if where == "post":
                out += [(x0, y0), (x1, y0)]
            elif where == "pre":
                out += [(x0, y0), (x0, y1)]
            else:
                xm = math.sqrt(x0 * x1) if self.logx else (x0 + x1) / 2
                out += [(x0, y0), (xm, y0), (xm, y1)]
        if pts:
            out.append(pts[-1])
        self.path(out, color, width, **kw)

    def bars(self, pts: Iterable[Point], fill: str = "cyan", *, bar: float = 0.8, base: float | None = None,
             color: str | None = None, width: float = 1.2, fill_opacity: float = 0.3, **kw) -> None:
        """A bar for each ``(x, y)``: ``bar`` data units wide (decades on a logarithmic x axis), centred on
        ``x``, from ``base`` (the bottom of the y range) to ``y``; outlined in ``color`` (``fill`` by default)."""
        b = self.yr[0] if base is None else base
        for xv, yv in pts:
            if self.logx:
                xa, xb = self.X(xv / 10 ** (bar / 2)), self.X(xv * 10 ** (bar / 2))
            else:
                xa, xb = self.X(xv - bar / 2), self.X(xv + bar / 2)
            ya, yb = self.Y(b), self.Y(yv)
            self.cv.rect(min(xa, xb), min(ya, yb), abs(xb - xa), abs(yb - ya), color=color or fill, fill=fill,
                         width=width, fill_opacity=fill_opacity, **kw)


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

    def small_circle(self, axis: Sequence[float], angle: float, color: str = "faint", width: float = 1.3, *,
                     start: Sequence[float] | None = None, span: float | None = None, arrow: bool = False,
                     head: float = 8.0, **kw) -> None:
        """The circle of points at ``angle`` degrees from ``axis`` (a latitude circle when the axis is z).
        With ``start`` and/or ``span`` only an arc of it: from the point of the circle nearest ``start``,
        ``span`` degrees right-handed about ``axis`` (see :meth:`turn`); ``arrow`` puts a head at its end."""
        if start is not None or span is not None or arrow:
            self._small_arc(axis, angle, color, width, start=start, span=360.0 if span is None else span, arrow=arrow,
                            head=head, **kw)
            return
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

    # ---- turns, arcs of small circles, sectors, patches and polytopes

    def _head(self, pts: Sequence[Sequence[float]], color: str, head: float, scale: float = 1.0,
              opacity: float | None = None) -> None:
        """An arrow head at the projection of ``pts[-1]``, along the last visible step of the curve."""
        xb, yb = self.xy(pts[-1], scale)
        for v in reversed(pts[:-1]):
            xa, ya = self.xy(v, scale)
            if math.hypot(xb - xa, yb - ya) > 0.5:
                self.cv.arrow_head(xb, yb, math.degrees(math.atan2(-(yb - ya), xb - xa)), color, head=head, opacity=opacity)
                return

    def turn(self, axis: Sequence[float], start: Sequence[float], angle: float, color: str = "ink", width: float = 2.0, *,
             n: int | None = None, arrow: bool = False, head: float = 8.0, **kw) -> Vec:
        """The path of ``start`` turned about ``axis`` by ``angle`` degrees (right-handed; on the sphere
        when ``start`` is a unit vector, on a larger or smaller sphere otherwise); ``arrow`` puts a head at
        its end. Returns the end point. Takes :meth:`curve`'s keywords (``scale``, ``back`` …)."""
        n = n or max(8, int(math.ceil(abs(angle) / 3)))
        pts = [rotate(start, axis, angle * k / n) for k in range(n + 1)]
        self.curve(pts, color, width, **kw)
        if arrow:
            self._head(pts, color, head, kw.get("scale", 1.0), kw.get("opacity"))
        return pts[-1]

    def _small_arc(self, axis: Sequence[float], angle: float, color: str, width: float, *, start: Sequence[float] | None,
                   span: float, arrow: bool, head: float, **kw) -> None:
        k = unit(axis)
        if start is None:
            a = unit(cross(k, (0.0, 0.0, 1.0) if abs(k[2]) < 0.9 else (1.0, 0.0, 0.0)))
        else:
            s0 = unit(start)
            d = dot3(s0, k)
            perp = tuple(s0[i] - d * k[i] for i in range(3))
            if math.sqrt(dot3(perp, perp)) < 1e-9:
                raise FigureError("small_circle: start lies on the axis, so it picks no point of the circle")
            a = unit(perp)
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        p0 = tuple(k[i] * c + a[i] * s for i in range(3))
        self.turn(k, p0, span, color, width, n=max(8, int(math.ceil(abs(span) / 3))), arrow=arrow, head=head, **kw)

    def sector(self, axis: Sequence[float], start: Sequence[float], angle: float, fill: str = "area", *,
               color: str | None = None, width: float = 1.2, fill_opacity: float = 0.2, n: int | None = None,
               scale: float = 1.0, **kw) -> None:
        """The flat sector swept when ``start`` turns about ``axis`` by ``angle`` degrees: its apex is the
        foot of ``start`` on the axis (the centre when ``start`` is perpendicular to it), its rim the
        arc of :meth:`turn`. ``color`` outlines it."""
        k = unit(axis)
        d = dot3(start, k)
        n = n or max(8, int(math.ceil(abs(angle) / 3)))
        rim = [rotate(start, axis, angle * j / n) for j in range(n + 1)]
        pts = [self.xy((k[0] * d, k[1] * d, k[2] * d), scale)] + [self.xy(v, scale) for v in rim]
        self.cv.polygon(pts, fill, color=color, width=width, fill_opacity=fill_opacity, **kw)

    def patch(self, points: Sequence[Sequence[float]], fill: str = "cyan", *, color: str | None = None, width: float = 1.3,
              fill_opacity: float = 0.18, flat: bool = False, n: int = 24, scale: float = 1.0) -> None:
        """The region bounded by ``points`` in order: on the sphere, its sides great-circle arcs (``flat``:
        straight, a face of a solid). Filled in projection; ``color`` draws the boundary, dashed behind."""
        pts = [tuple(v) for v in points]
        if len(pts) < 3:
            raise FigureError("patch: a region needs at least three points")
        ring: list[Sequence[float]] = []
        for a, b in zip(pts, pts[1:] + pts[:1]):
            if flat:
                ring.append(a)
            else:
                ring.extend(slerp(a, b, j / n) for j in range(n))
        self.cv.polygon([self.xy(v, scale) for v in ring], fill, fill_opacity=fill_opacity)
        if color:
            self.curve(ring + ring[:1], color, width, scale=scale)

    def polytope(self, points: Sequence[Sequence[float]], color: str = "line", *, fill: str | None = "cyan",
                 fill_opacity: float = 0.07, width: float = 1.5, back: str = "dim", dots: bool = True) -> list:
        """The convex hull of ``points`` (vectors in or on the ball, see :func:`hull3`): faces towards the
        reader lightly filled, edges solid in front and dashed behind, the points as dots. Returns the faces."""
        faces = hull3(points)
        edges: dict[tuple[int, int], bool] = {}
        for nrm, _, order in faces:
            front = dot3(nrm, self.toward) > 0
            if front and fill:
                self.cv.polygon([self.xy(points[m]) for m in order], fill, fill_opacity=fill_opacity)
            for a, b in zip(order, order[1:] + order[:1]):
                e = (min(a, b), max(a, b))
                edges[e] = edges.get(e, False) or front
        for (a, b), front in edges.items():
            if not front:
                self.segment(points[a], points[b], back, 1.0, dash="3 3", opacity=0.6)
        for (a, b), front in edges.items():
            if front:
                self.segment(points[a], points[b], color, width)
        if dots:
            for v in points:
                if dot3(v, self.toward) >= 0:
                    self.dot(v, color, 3.6, ring="bg")
                else:
                    self.dot(v, back, 2.6)
        return faces


# ---------------------------------------------------------------- flow-chart boxes, logarithms, hulls


class Box:
    """A rectangle that :meth:`Canvas.link` can join: what :meth:`Canvas.box` returns."""

    def __init__(self, x: float, y: float, w: float, h: float):
        self.x, self.y, self.w, self.h = float(x), float(y), float(w), float(h)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def top(self) -> Point:
        return (self.cx, self.y)

    @property
    def bottom(self) -> Point:
        return (self.cx, self.y + self.h)

    @property
    def left(self) -> Point:
        return (self.x, self.cy)

    @property
    def right(self) -> Point:
        return (self.x + self.w, self.cy)

    def at(self, fx: float, fy: float) -> Point:
        """The point a fraction ``fx`` across and ``fy`` down the box."""
        return (self.x + self.w * fx, self.y + self.h * fy)

    def exit(self, px: float, py: float) -> Point:
        """Where the ray from the centre towards ``(px, py)`` leaves the box."""
        dx, dy = px - self.cx, py - self.cy
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            return (self.cx, self.cy)
        t = min(self.w / 2 / abs(dx) if abs(dx) > 1e-12 else math.inf, self.h / 2 / abs(dy) if abs(dy) > 1e-12 else math.inf)
        return (self.cx + dx * t, self.cy + dy * t)


def _as_box(p: "Box | Sequence[float]") -> Box:
    return p if isinstance(p, Box) else Box(p[0], p[1], 0, 0)


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def _facing(A: Box, B: Box, inset: float) -> tuple[Point, Point]:
    """The ends of a straight link from ``A`` to ``B`` (see :meth:`Canvas.link`)."""
    if B.y >= A.y + A.h - 1e-9 or A.y >= B.y + B.h - 1e-9:  # one above the other
        down = B.y >= A.y + A.h - 1e-9
        ia, ib = min(inset, A.w / 2), min(inset, B.w / 2)
        lo, hi = max(A.x + ia, B.x + ib), min(A.x + A.w - ia, B.x + B.w - ib)
        if lo <= hi:
            xa = xb = _clamp(A.cx, lo, hi)
        else:
            xa, xb = _clamp(B.cx, A.x + ia, A.x + A.w - ia), _clamp(A.cx, B.x + ib, B.x + B.w - ib)
        return (xa, A.y + A.h if down else A.y), (xb, B.y if down else B.y + B.h)
    if B.x >= A.x + A.w - 1e-9 or A.x >= B.x + B.w - 1e-9:  # side by side
        right = B.x >= A.x + A.w - 1e-9
        ia, ib = min(inset, A.h / 2), min(inset, B.h / 2)
        lo, hi = max(A.y + ia, B.y + ib), min(A.y + A.h - ia, B.y + B.h - ib)
        if lo <= hi:
            ya = yb = _clamp(A.cy, lo, hi)
        else:
            ya, yb = _clamp(B.cy, A.y + ia, A.y + A.h - ia), _clamp(A.cy, B.y + ib, B.y + B.h - ib)
        return (A.x + A.w if right else A.x, ya), (B.x if right else B.x + B.w, yb)
    return A.exit(B.cx, B.cy), B.exit(A.cx, A.cy)


def _log(v: float) -> float:
    if v <= 0:
        raise FigureError(f"{v} has no place on a logarithmic axis")
    return math.log10(v)


def log_label(v: float) -> str:
    """A tick label on a logarithmic axis: the powers of ten from ``0.01`` to ``1000`` as numbers, the others
    as ``10^{−3}``, anything else as :func:`num` writes it."""
    k = round(math.log10(v)) if v > 0 else 0
    if v > 0 and abs(v - 10.0 ** k) <= 1e-9 * v:
        return num(v) if -2 <= k <= 3 else "10^{" + str(k).replace("-", "−") + "}"
    return num(v)


def hull(points: Iterable[Sequence[float]]) -> list[Point]:
    """The convex hull of plane points: its corners in order (counter-clockwise with y up, clockwise on
    the page), without repeated or collinear points."""
    pts = sorted({(float(p[0]), float(p[1])) for p in points})
    if len(pts) < 3:
        return pts

    def turn_(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and turn_(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and turn_(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def hull3(points: Sequence[Sequence[float]], eps: float = 1e-9) -> list[tuple[Vec, float, list[int]]]:
    """The faces of the convex hull of space points (at least four, not all in a plane): for each, its
    outward unit normal, its offset (``normal · p`` on the face) and the indices of its corners in
    cyclic order. The outline of a point set on a sphere is :meth:`Sphere.polytope`."""
    pts = [tuple(float(c) for c in p) for p in points]

    def sub(a: Sequence[float], b: Sequence[float]) -> Vec:
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    faces: dict[frozenset, tuple[Vec, float, list[int]]] = {}
    m = len(pts)
    for i in range(m):
        for j in range(i + 1, m):
            for k in range(j + 1, m):
                nv = cross(sub(pts[j], pts[i]), sub(pts[k], pts[i]))
                ln = math.sqrt(dot3(nv, nv))
                if ln < 1e-9:
                    continue
                nv = (nv[0] / ln, nv[1] / ln, nv[2] / ln)
                d = dot3(nv, pts[i])
                side = [dot3(nv, p) - d for p in pts]
                if all(t >= -eps for t in side):
                    nv, d = (-nv[0], -nv[1], -nv[2]), -d
                elif not all(t <= eps for t in side):
                    continue
                on = frozenset(q for q, t in enumerate(side) if abs(t) <= eps)
                if on in faces:
                    continue
                c = tuple(sum(pts[q][a] for q in on) / len(on) for a in range(3))
                u = unit(sub(pts[next(iter(on))], c))
                v = cross(nv, u)
                order = sorted(on, key=lambda q: math.atan2(dot3(sub(pts[q], c), v), dot3(sub(pts[q], c), u)))
                faces[on] = (nv, d, order)
    if len(faces) < 4:
        raise FigureError("hull3: the points are fewer than four or all lie in one plane")
    return list(faces.values())
