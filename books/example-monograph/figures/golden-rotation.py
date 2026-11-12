"""黄金词是黄金旋转的编码：相位圆每一步转过 1/φ，落在哪一段就写哪个字母（第四章）。
The golden word codes the golden rotation: each step turns the phase circle by 1/φ, and the segment the
phase lands in gives the letter (chapter 4).

The phase circle (circumference 1) is drawn as the equator of a ball seen from above its rim; phase x sits
at azimuth 360·x degrees. With n = 1 the proof of the factor-complexity theorem cuts the circle at
1 − {1/φ}: g(i) = a exactly when x_i = {(i+1)/φ} ≥ 1 − {1/φ}. The script checks that against the word
built by the substitution, for the first 3000 letters.
"""

from tbook import figkit

SIZE = (400, 272)
MARKUP = 2
ALT = {
    "zh": "一个球，赤道是周长为 1 的相位圆，圆盘按两段着色：青色的一段（长 1/φ ≈ 0.618）对应字母 a，品红的一段"
          "（长 1/φ² ≈ 0.382）对应字母 b。赤道上标出相位 x₀ 到 x₇ 的点，按所在的段着色，旁边写着序号。"
          "一支绕竖直轴的箭头沿球外从 x₀ 转到 x₁，标注“转过 1/φ”。",
    "en": "A ball whose equator is the phase circle of circumference 1. The disc is coloured in two segments: cyan, of "
          "length 1/φ ≈ 0.618, for the letter a, and magenta, of length 1/φ² ≈ 0.382, for the letter b. The phases x₀ "
          "to x₇ are dots on the equator, coloured by their segment and numbered. An arrow turning about the vertical "
          "axis runs outside the ball from x₀ to x₁, labelled 'turn by 1/φ'.",
}

PHI = (1 + 5 ** 0.5) / 2
CUT = 1 - (1 / PHI) % 1          # the cut point 1 − {1/φ} = 1/φ²


def golden_word(length):
    w = "a"
    while len(w) < length:
        w = "".join("ab" if c == "a" else "a" for c in w)
    return w[:length]


def phase(i):
    return ((i + 1) / PHI) % 1


G = golden_word(3000)
assert all((G[i] == "a") == (phase(i) >= CUT) for i in range(3000))
assert abs(CUT - 1 / PHI ** 2) < 1e-12

Z = (0.0, 0.0, 1.0)


def at(x, r=1.0):
    return tuple(r * c for c in figkit.sph(90, 360 * x))


def draw(fig):
    t = fig.t
    sp = fig.sphere(212, 150, 108, az=110, el=34)
    sp.outline(fill=None, color="faint", width=1.2)
    sp.sector(Z, at(CUT), 360 * (1 - CUT), "cyan", fill_opacity=0.2)
    sp.sector(Z, at(0), 360 * CUT, "magenta", fill_opacity=0.24)
    sp.small_circle(Z, 90, "dim", 1.6)
    for x in (0, CUT):
        sp.segment((0, 0, 0), at(x), "dim", 1.2)
    sp.segment((0, 0, -1.25), (0, 0, 1.25), "faint", 1.2, dash="3 3")
    end = sp.turn(Z, at(phase(0), 1.2), 360 / PHI, "ink", 2.0, arrow=True)
    sp.label(at(0.06, 1.2), t("转过 1/φ", "turn by 1/φ"), dy=22, size=14, anchor="middle", halo=True)
    for i in range(8):
        role = "cyan" if G[i] == "a" else "magenta"
        sp.dot(at(phase(i)), role, 4.4, ring="bg")
        sp.label(at(phase(i)), f"*x*_{{{i}}}", scale=0.82, size=13, color=role, anchor="middle", middle=True, halo=True)
    fig.legend(16, 24, [("cyan", t("*g*(*i*) = a", "*g*(*i*) = a")), ("magenta", t("*g*(*i*) = b", "*g*(*i*) = b"))],
               swatch="box")
