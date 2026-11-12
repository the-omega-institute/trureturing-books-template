"""回归得分：等待时间 F_n 按 φ^n 增长，误差 |F_nφ − F_{n+1}| 按 φ^{−n} 缩小，两者之积趋于 1/√5（第四章）。
The revival score: the waiting time F_n grows like φ^n, the error |F_nφ − F_{n+1}| shrinks like φ^{−n}, and
their product tends to 1/√5 (chapter 4).

On a logarithmic y axis the two exponentials are straight lines of opposite slope ±log φ. The script checks
the exact residual F_nφ − F_{n+1} = −(−1/φ)^n with integer arithmetic in Q(√5) and the alternation of the
score about 1/√5 that the chapter's table shows.
"""

from fractions import Fraction

SIZE = (430, 300)
MARKUP = 2
ALT = {
    "zh": "对数纵轴，横轴 n 从 1 到 14。青色的点沿一条上升的直线排列，是等待时间 F_n；品红的点沿一条下降的直线排列，"
          "是误差 |F_nφ − F_{n+1}| = φ^{−n}，两条直线斜率相反。中间白色的点是两者之积，即回归得分，在绿色虚线 1/√5 "
          "两侧上下交替，越来越贴近它。",
    "en": "A logarithmic vertical axis, with n from 1 to 14 across. The cyan dots lie on a rising straight line: the waiting "
          "time F_n. The magenta dots lie on a falling straight line: the error |F_nφ − F_{n+1}| = φ^{−n}; the two lines "
          "have opposite slopes. In between, the ink dots are their product, the revival score, alternating above and "
          "below the green dashed line at 1/√5 and closing in on it.",
}

PHI = (1 + 5 ** 0.5) / 2
N = 14
F = [0, 1]
while len(F) < N + 3:
    F.append(F[-1] + F[-2])

# exact: F_n φ − F_{n+1} = −(−1/φ)^n, in Q(√5) as (a, b) = a + b√5, with φ = (1 + √5)/2 and 1/φ = φ − 1


def mul(x, y):
    return (x[0] * y[0] + 5 * x[1] * y[1], x[0] * y[1] + x[1] * y[0])


PH = (Fraction(1, 2), Fraction(1, 2))
INV = (Fraction(-1, 2), Fraction(1, 2))
power = (Fraction(1), Fraction(0))
for n in range(1, N + 1):
    power = mul(power, (-INV[0], -INV[1]))          # (−1/φ)^n
    lhs = (F[n] * PH[0] - F[n + 1], F[n] * PH[1])
    assert lhs == (-power[0], -power[1])

RESID = [abs(F[n] * PHI - F[n + 1]) for n in range(N + 1)]
SCORE = [F[n] * RESID[n] for n in range(N + 1)]
LIMIT = 1 / 5 ** 0.5
assert all((SCORE[n] > LIMIT) == (n % 2 == 1) for n in range(1, N + 1))   # odd n above, even n below


def draw(fig):
    t = fig.t
    ax = fig.axes(56, 22, 318, 226, (0.5, N + 0.5), (5e-4, 1e3), logy=True)
    ax.grid(ys=ax.decades("y"))
    ax.xaxis(ticks=[1, 4, 7, 10, 13], size=14)
    ax.yaxis(size=14)
    fig.text(215, 290, "*n*", size=14, color="dim", anchor="middle")
    ax.hline(LIMIT, "lean", 1.6, dash="6 4")
    ax.text(N + 0.5, LIMIT, "1/√5", dx=6, size=14, color="lean", middle=True)
    ns = range(1, N + 1)
    ax.path([(n, F[n]) for n in ns], "cyan", 1.4, dash="3 3")
    ax.path([(n, RESID[n]) for n in ns], "magenta", 1.4, dash="3 3")
    ax.points([(n, F[n]) for n in ns], "cyan", 3.6)
    ax.points([(n, RESID[n]) for n in ns], "magenta", 3.6)
    ax.path([(n, SCORE[n]) for n in ns], "ink", 1.6)
    ax.points([(n, SCORE[n]) for n in ns], "ink", 3.2, ring="bg")
    ax.text(6, F[6], t("等待 *F*_{*n*}", "wait *F*_{*n*}"), dx=-8, dy=-16, size=14, color="cyan", anchor="middle",
            halo=True)
    ax.text(6, RESID[6], t("误差 φ^{−*n*}", "error φ^{−*n*}"), dx=-8, dy=28, size=14, color="magenta", anchor="middle",
            halo=True)
    ax.text(4, SCORE[4], t("得分 = 两者之积", "score = their product"), dy=-14, size=14, halo=True)
