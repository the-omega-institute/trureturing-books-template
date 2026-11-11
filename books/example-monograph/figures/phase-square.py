"""相位正方形：两条斜线把它分成亏量取 +1、0、−1 的三块（第一章）。
The phase square: two diagonal lines cut it into the regions where the deficit is +1, 0 and −1 (chapter 1).

Every dot is computed: the phase pair (p(v1), p(v2)) for 0 ≤ v1, v2 ≤ 7 with p(v) = {(v+1)φ}. The counts
the chapter states (10 dots in the lower-left triangle, 6 in the upper-right one) are asserted below.
"""

import math

SIZE = (420, 372)
ALT = {
    "zh": "单位正方形，横轴 p(v₁)，纵轴 p(v₂)。斜线 p₁ + p₂ = 1/φ 的左下方是亏量 +1 的三角形，斜线 p₁ + p₂ = φ 的右上方是亏量 −1 的小三角形，"
          "两线之间的带状区域亏量为 0。64 个点是 0 ≤ v₁, v₂ ≤ 7 的相位对：左下三角形中 10 个，右上三角形中 6 个。",
    "en": "The unit square with p(v₁) across and p(v₂) up. Below the line p₁ + p₂ = 1/φ is the triangle where the deficit "
          "is +1, above the line p₁ + p₂ = φ the small triangle where it is −1, and in the band between them it is 0. The 64 "
          "dots are the phase pairs for 0 ≤ v₁, v₂ ≤ 7: 10 in the lower-left triangle, 6 in the upper-right one.",
}

PHI = (1 + math.sqrt(5)) / 2


def phase(v):
    return ((v + 1) * PHI) % 1.0


def draw(fig):
    t = fig.t
    ax = fig.axes(84, 34, 290, 290, (0, 1), (0, 1))
    q = 1 / PHI
    ax.cv.polygon([ax.pt(0, 0), ax.pt(q, 0), ax.pt(0, q)], "cyan", fill_opacity=0.22)        # c = +1
    ax.cv.polygon([ax.pt(q, 1), ax.pt(1, 1), ax.pt(1, q)], "magenta", fill_opacity=0.22)     # c = −1
    ax.grid([q], [q], "faint", 1.0, dash="3 4")
    ax.frame("dim", 1.3)
    ax.path([(0, q), (q, 0)], "dim", 1.7)
    ax.path([(q, 1), (1, q)], "dim", 1.7)

    pts = [(phase(a), phase(b)) for a in range(8) for b in range(8)]
    plus = [p for p in pts if p[0] + p[1] < q]
    minus = [p for p in pts if p[0] + p[1] >= PHI]
    assert (len(pts), len(plus), len(minus)) == (64, 10, 6)
    ax.points([p for p in pts if p not in plus and p not in minus], "dim", 2.4)
    ax.points(plus, "cyan", 2.8)
    ax.points(minus, "magenta", 2.8)

    ticks = [0, q, 1]
    names = ["0", "1/*φ*", "1"]
    ax.xaxis(ticks=ticks, labels=names, size=13)
    ax.yaxis(ticks=ticks, labels=names, size=13)
    fig.text(ax.x + ax.w / 2, 362, "*p*(*v*_{1})", size=14, color="dim", anchor="middle")
    fig.text(24, ax.y + ax.h / 2, "*p*(*v*_{2})", size=14, color="dim", anchor="middle", rotate=90)
    ax.text(0.2, 0.17, "*c* = +1", color="cyan", size=14, weight=600, anchor="middle", halo=True)
    ax.text(0.5, 0.52, "*c* = 0", color="dim", size=14, weight=600, anchor="middle", halo=True)
    ax.text(0.87, 0.9, "*c* = −1", color="magenta", size=14, weight=600, anchor="middle", halo=True)
    del t
