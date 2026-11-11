"""一张图只讲一件事：把这句话换成这张图要让读者看见的那一件事。
One figure, one idea: replace this line by the one thing the figure lets the reader see.

Draw with the kit (tools/tbook/figkit.py, skills/book-figure); never write a colour value: every
stroke and fill names a role. Run `./tbook fig build` after each change and look at the result with
`./tbook fig shots <book> <name>`.
"""

import math

# natural size in CSS pixels: the largest the figure is ever shown (≤ 760 wide; text ≥ 12, lines ≥ 1)
SIZE = (480, 290)

# what a reader who cannot see the figure is told; one entry per edition
ALT = {
    "zh": "箭头 b 在箭头 a 上的影子：从 b 的尖端向 a 作垂线，垂足到原点的一段就是影子，长度为 cos θ。",
    "en": "The shadow of arrow b on arrow a: drop a perpendicular from the tip of b onto a; the segment from "
          "the origin to its foot is the shadow, of length cos θ.",
}


def draw(fig):
    t = fig.t                      # t("中文", "English") → the label for this edition
    ox, oy, r = 70, 232, 250       # the origin and the length of a unit arrow
    theta = 50                     # degrees between a and b
    bx = ox + r * math.cos(math.radians(theta))
    by = oy - r * math.sin(math.radians(theta))

    fig.arc(ox, oy, r, 0, 62, "faint", 1.2, dash="3 4")             # the unit circle the two arrows end on
    fig.arrow(ox, oy, ox + r, oy, "ink", 2.2)                        # a: the known state, the ruler
    fig.line(bx, by, bx, oy, "dim", 1.3, dash="4 3")                 # the perpendicular from the tip of b
    fig.right_angle(bx, oy, 90, 9)
    fig.line(ox, oy, bx, oy, "line", 4.5, cap="round")               # the shadow (cyan: the collinear part)
    fig.arrow(ox, oy, bx, by, "now", 2.4)                            # b: the state being measured (amber: current)
    fig.angle(ox, oy, 46, 0, theta, "θ")

    fig.text(ox + r + 8, oy + 5, "*a*", size=16)
    fig.text(bx + 8, by - 4, "*b*", size=16, color="now")
    fig.text((ox + bx) / 2, oy + 26, t("影子 cos θ", "shadow cos θ"), color="line", anchor="middle")
    fig.text(bx + 12, (by + oy) / 2, t("垂线", "perpendicular"), size=13, color="dim", middle=True)
