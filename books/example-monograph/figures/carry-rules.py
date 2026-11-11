"""四条进位规则：每行左边是改写前的数字，右边是改写后的数字（附录 A）。
The four carry rules: on each row the digits before the rewrite on the left, after it on the right (appendix A).

Rule names are Lean identifiers and stay as they are in both editions. The two lowest double carries are
the only rules with a charge: +1 in cyan (a positive difference), −1 in magenta (a negative one).
"""

SIZE = (440, 356)
ALT = {
    "zh": "四行，每行一条进位规则：adjacent 把相邻的 1、1 改写成高一位的 1（电荷 0）；double_zero 把最低位的 2 改写成高一位的 1（电荷 +1）；"
          "double_one 把次低位的 2 改写成两侧各一个 1（电荷 −1）；double_succ 把一般位置的 2 改写成低两位与高一位各一个 1（电荷 0）。",
    "en": "Four rows, one carry rule each: adjacent rewrites neighbouring 1, 1 as a 1 one place up (charge 0); double_zero "
          "rewrites a 2 in the lowest place as a 1 one place up (charge +1); double_one rewrites a 2 in the next place as a "
          "1 on either side (charge −1); double_succ rewrites a 2 in a general place as a 1 two places down and a 1 one "
          "place up (charge 0).",
}

RULES = [
    ("adjacent", "*W*_{*i*} + *W*_{*i*+1} = *W*_{*i*+2}", ["*i*+2", "*i*+1", "*i*"], [0, 1, 1], [1, 0, 0], 0),
    ("double_zero", "2*W*_{0} = *W*_{1}", ["1", "0"], [0, 2], [1, 0], +1),
    ("double_one", "2*W*_{1} = *W*_{0} + *W*_{2}", ["2", "1", "0"], [0, 2, 0], [1, 0, 1], -1),
    ("double_succ", "2*W*_{*i*+2} = *W*_{*i*} + *W*_{*i*+3}", ["*i*+3", "*i*+2", "*i*+1", "*i*"], [0, 2, 0, 0], [1, 0, 0, 1], 0),
]
BOX, STEP, ROW = 28, 32, 86


def digits(fig, x, y, places, values):
    """A row of digit boxes with their places above; returns the x after the last box."""
    for k, (place, v) in enumerate(zip(places, values)):
        bx = x + k * STEP
        fig.text(bx + BOX / 2, y - 7, place, size=12, color="dim", anchor="middle")
        if v:
            fig.rect(bx, y, BOX, BOX, color="ink", fill="ink", fill_opacity=0.12, width=1.4, rx=3)
            fig.text(bx + BOX / 2, y + BOX / 2, str(v), size=16, weight=700, anchor="middle", middle=True)
        else:
            fig.rect(bx, y, BOX, BOX, color="faint", width=1.1, rx=3)
            fig.text(bx + BOX / 2, y + BOX / 2, "0", size=16, color="dim", anchor="middle", middle=True)
    return x + len(places) * STEP - (STEP - BOX)


def draw(fig):
    for r, (name, identity, places, before, after, charge) in enumerate(RULES):
        top = 8 + r * ROW
        role = "cyan" if charge > 0 else "magenta" if charge < 0 else None
        if role:  # the two rules that carry a charge
            fig.rect(6, top, 394, ROW - 6, color=role, fill=role, fill_opacity=0.08, width=1.3, rx=8, dash="5 4")
        fig.text(18, top + 20, name, size=12, color="dim", mono=True)
        fig.text(132, top + 20, identity, size=14, color="dim")
        y = top + 44
        n = len(places)
        left = 150 - n * STEP                      # the two digit rows end at fixed columns
        end = digits(fig, left, y, places, before)
        fig.arrow(end + 12, y + BOX / 2, end + 50, y + BOX / 2, "dim", 1.5, head=8)
        digits(fig, end + 62, y, places, after)
        label = "0" if charge == 0 else ("+1" if charge > 0 else "−1")
        fig.text(376, y + BOX / 2, label, size=16, color=role or "dim", weight=700 if role else None, anchor="middle", middle=True)
