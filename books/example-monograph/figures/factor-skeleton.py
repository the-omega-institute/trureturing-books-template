"""长度为 n 的因子恰有 n+1 个：证明的骨架（第四章）。
The proof that the golden word has exactly n+1 factors of length n, as a skeleton (chapter 4).

Only what the chapter's proof block says is drawn: the floor formula for the number of a's in a window
(`goldenWindowTrueCount_eq_floor`), the n cut points that split [0, 1) into n + 1 segments, the two bounds,
and the theorem the chapter cites with lean= (green). The script checks the two facts the boxes state on a
long prefix of the word: the floor formula, and that the factor at i is determined by the segment of x_i.
"""

import math

SIZE = (358, 380)
MARKUP = 2
ALT = {
    "zh": "证明骨架图。顶部虚线框“黄金词 g”。第一个方框：窗口中 a 的个数等于 ⌊(i+m+1)/φ⌋ − ⌊(i+1)/φ⌋，"
          "依据 goldenWindowTrueCount_eq_floor。第二个方框：这个个数只看相位 x_i 落在 n 个分点切出的 n+1 段中的哪一段。"
          "由此分成两支：左支“至多 n+1 个：同一段给出同一个因子”，右支“至少 n+1 个：相位稠密，每段都有相位落入”。"
          "两支汇入底部绿色的 LEAN ✓ 方框“恰有 n+1 个因子”，即 golden_factor_complexity。",
    "en": "A proof skeleton. At the top a dashed box, 'the golden word g'. First box: the number of a's in a window equals "
          "⌊(i+m+1)/φ⌋ − ⌊(i+1)/φ⌋, by goldenWindowTrueCount_eq_floor. Second box: that number depends only on which of "
          "the n+1 segments cut by n points the phase x_i falls in. Two branches follow: left, 'at most n+1: one segment, "
          "one factor'; right, 'at least n+1: the phases are dense, every segment is hit'. Both meet in the green LEAN ✓ "
          "box at the bottom, 'exactly n+1 factors', which is golden_factor_complexity.",
}

PHI = (1 + 5 ** 0.5) / 2


def golden_word(length):
    w = "a"
    while len(w) < length:
        w = "".join("ab" if c == "a" else "a" for c in w)
    return w[:length]


G = golden_word(3000)
for _i in range(2000):
    for _m in range(1, 8):  # the floor formula for the a's in the window of length m at i
        assert G[_i:_i + _m].count("a") == math.floor((_i + _m + 1) / PHI) - math.floor((_i + 1) / PHI)
for _n in range(1, 7):  # the factor at i is a function of the segment of x_i, and every segment occurs
    cuts = sorted(1 - ((m / PHI) % 1) for m in range(1, _n + 1))
    seen = {}
    for _i in range(2000):
        seg = sum(((_i + 1) / PHI) % 1 >= c for c in cuts)
        assert seen.setdefault(seg, G[_i:_i + _n]) == G[_i:_i + _n]
    assert len(seen) == _n + 1 == len({G[_i:_i + _n] for _i in range(2000)})


def draw(fig):
    # one column 358 wide (a phone's text column): nothing is scaled down, so every label keeps its size
    t = fig.t
    cx = 179
    g = fig.box(cx, 6, t("黄金词 *g*", "the golden word *g*"), dashed=True)
    count = fig.box(cx, 58, t("窗口中 a 的个数 =\n⌊(*i*+*m*+1)/φ⌋ − ⌊(*i*+1)/φ⌋", "a's in a window =\n⌊(*i*+*m*+1)/φ⌋ − ⌊(*i*+1)/φ⌋"),
                    note="goldenWindowTrueCount_eq_floor")
    seg = fig.box(cx, count.y + count.h + 24, t("个数只看 *x*_{*i*} 落在 *n*+1 段中的哪一段", "the counts depend only on which of *n*+1 "
                                                                      "segments holds *x*_{*i*}"), wrap=290)
    row = seg.y + seg.h + 34
    upper = fig.box(90, row, t("至多 *n*+1 个：\n同一段给出同一个因子", "at most *n*+1: one segment, one factor"), w=170)
    lower = fig.box(268, row, t("至少 *n*+1 个：\n相位稠密，每段都有", "at least *n*+1: the phases are dense, every segment is hit"),
                    w=170)
    goal = fig.box(cx, max(upper.y + upper.h, lower.y + lower.h) + 34, t("恰有 *n*+1 个因子", "exactly *n*+1 factors"),
                   "lean", chip="LEAN ✓")
    fig.link(g, count)
    fig.link(count, seg)
    fig.link((upper.cx, seg.y + seg.h), upper)  # the fork leaves the step above each branch
    fig.link((lower.cx, seg.y + seg.h), lower)
    fig.link(upper, goal, "ink")
    fig.link(lower, goal, "ink")
