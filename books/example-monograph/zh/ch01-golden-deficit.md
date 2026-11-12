# 第一章 黄金整数的进位亏量

每个自然数 $n$ 都可以唯一地写成互不相邻的 Fibonacci 数之和（Zeckendorf 表示），权重取 $F_2 = 1, F_3 = 2, F_4 = 3, \dots$。把每个权重 $F_i$ 换成 $\varphi^i$，其中 $\varphi = (1+\sqrt5)/2$ 是黄金比，就得到实数 $\beta(n)$。

::: {.definition #def-deficit title="归一化亏量" lean="D5/S1/Deficit/DeficitInteger.deficit"}
对自然数 $v_1, v_2$，定义
$$
c(v_1, v_2) = \beta(v_1) + \beta(v_2) - \beta(v_1 + v_2).
$$
:::

$\beta$ 并不保持加法：例如 $\beta(1) = \varphi^2$、$\beta(2) = \varphi^3$，于是 $c(1, 1) = 2\varphi^2 - \varphi^3 = 1$。

::: {.theorem #thm-deficit-integer title="亏量是整数，且等于带符号的进位计数" lean="D5/S1/Deficit/DeficitInteger.deficit_integer"}
对所有自然数 $v_1, v_2$，亏量 $c(v_1, v_2)$ 等于它在收缩面（Galois 共轭）上的读数，是一个整数，并且等于把两个 Zeckendorf 表示逐位相加后、规范化过程中两条最低重复进位规则的带符号计数。
:::

::: {.theorem #thm-deficit-three-valued title="亏量只取三个值" lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
对所有自然数 $v_1, v_2$，
$$
c(v_1, v_2) \in \{-1, 0, 1\}.
$$
:::

::: proof
收缩面把 Zeckendorf 数字放在共轭 $\psi = (1-\sqrt5)/2$ 的幂上求值。每个 $\beta'(v)$ 落在长度恰为 $1$ 的窗口 $[-\psi^2, -\psi]$ 中，所以 $c$ 在收缩面上的读数严格介于 $-2$ 与 $2$ 之间；再由 [@thm-deficit-integer]，它是整数。完整证明已在 Lean 中由内核检查。
:::

::: remark
[@thm-deficit-three-valued] 对任意大的输入都成立：它把一个算术算法（逐位进位）和一个精确界联系起来，可以作为后续推理的前提反复使用。在 Lean 中，它的名字是 [`deficit_three_valued`](lean:D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)。
:::

## 两张面孔 {#sec-two-faces}

$\beta(v)$ 把 $v$ 的 Zeckendorf 数位放在黄金比 $\varphi$ 的幂上求值，称为展开面读数。$\varphi$ 是方程 $x^2 = x + 1$ 的一个根，这个方程的另一个根是 $\psi = (1-\sqrt5)/2 = -1/\varphi \approx -0.618$。把同一组数位放在 $\psi$ 的幂上求值，就得到收缩面读数。[@thm-deficit-integer] 说亏量在两个面上读数相同；本节说明其中的道理，并给出 [@thm-deficit-three-valued] 的证明所用的窗口。

::: {.definition #def-beta-contraction title="收缩面读数 $\beta'$" lean="D5/S1/Deficit/DeficitInteger.betaContraction"}
设自然数 $v$ 的 Zeckendorf 表示为 $v = F_{k_1} + \dots + F_{k_r}$，下标 $k_j \ge 2$ 互不相同且互不相邻（存在与唯一见[附录 A](appendix-a-zeckendorf.md) 的 [@thm-zeckendorf-exists] 与 [@thm-zeckendorf-unique]）。这时 $\beta(v) = \varphi^{k_1} + \dots + \varphi^{k_r}$ 是 $\mathbb{Z}[\varphi]$ 中的元素。对它作 Galois 共轭 $\varphi \mapsto \psi$，再取实数值，得到 $v$ 的收缩面读数

$$
\beta'(v) = \psi^{k_1} + \dots + \psi^{k_r}.
$$

$v = 0$ 时和为空，$\beta'(0) = 0$。
:::

例如 $\beta'(1) = \psi^2 \approx 0.382$，$\beta'(2) = \psi^3 \approx -0.236$，$\beta'(4) = \psi^4 + \psi^2 \approx 0.528$。展开面读数随 $v$ 增长，收缩面读数却始终很小；下面两条引理把这一点说准确。

::: {.lemma #lem-two-faces title="两面之差" lean="D5/S1/Deficit/DoubleFaceLength.betaReal_sub_betaContraction"}
对所有自然数 $v$，

$$
\beta(v) - \beta'(v) = \sqrt5\, v.
$$
:::

例如 $\beta(1) - \beta'(1) = \varphi^2 - \psi^2 = (\varphi - \psi)(\varphi + \psi) = \sqrt5$。道理在于：把 $\beta(v)$ 写成 $a + b\varphi$（$a, b \in \mathbb{Z}$）时，$\varphi$ 的系数 $b$ 恰好是 $v$；共轭只把 $\varphi$ 换成 $\psi$，两者之差是 $b(\varphi - \psi) = \sqrt5\, v$。

::: {.lemma #lem-window title="收缩面的窗口" lean="D5/S1/Words/Expansions/BasePhiNegativeBridge.betaContraction_mem_window"}
对所有自然数 $v$，

$$
-\psi^2 \le \beta'(v) \le -\psi .
$$
:::

窗口的两端是 $-\psi^2 = -1/\varphi^2 \approx -0.382$ 与 $-\psi = 1/\varphi \approx 0.618$，长度为 $\psi^2 - \psi = 1$（用到 $\psi^2 = \psi + 1$）。

::: proof
先看窗口从哪里来。因为 $-1 < \psi < 0$，$\psi^k$ 在 $k$ 为偶数时为正、为奇数时为负。$\beta'(v)$ 是若干个下标互不相同的 $\psi^k$（$k \ge 2$）之和，所以它不超过全部偶数次幂之和，也不低于全部奇数次幂之和：

$$
\beta'(v) \le \psi^2 + \psi^4 + \cdots = \frac{\psi^2}{1 - \psi^2} = -\psi, \qquad \beta'(v) \ge \psi^3 + \psi^5 + \cdots = \frac{\psi^3}{1 - \psi^2} = -\psi^2,
$$

这里用到 $1 - \psi^2 = -\psi$。这就是 [@lem-window]；Lean 证明同样把求和拆成偶次与奇次两部分，各用一个几何级数控制。

再把窗口与整数性结合起来。由 [@lem-two-faces]，$\beta(v) = \beta'(v) + \sqrt5\, v$；代入 [@def-deficit]，线性项 $\sqrt5\, v_1 + \sqrt5\, v_2 - \sqrt5\,(v_1 + v_2)$ 为零，于是

$$
c(v_1, v_2) = \beta'(v_1) + \beta'(v_2) - \beta'(v_1 + v_2),
$$

这就是 [@thm-deficit-integer] 的第一部分。同一个事实也说明 $c$ 是整数：$c$ 的 $\varphi$ 系数是 $v_1 + v_2 - (v_1 + v_2) = 0$。Lean 中 [`deficit_integer`](lean:D5/S1/Deficit/DeficitInteger.deficit_integer) 的前两部分正是由这个系数为零得出的。上式右边三项各落在窗口中，所以

$$
2(-\psi^2) - (-\psi) \le c(v_1, v_2) \le 2(-\psi) - (-\psi^2),
$$

即 $\varphi - 3 \le c(v_1, v_2) \le \varphi$，约为 $-1.382 \le c \le 1.618$。这个区间中的整数只有 $-1$、$0$、$1$，这就是 [@thm-deficit-three-valued]。完整证明由 Lean 内核检查。
:::

::: {.viz src="golden-carry" preset="window" height="500"}
收缩面上的窗口。上半部分每个点是一个 $v \le 34$ 的读数 $\beta'(v)$，横向是它的值：所有的点都在 $-1/\varphi^2$ 与 $1/\varphi$ 两条竖线之间。琥珀色的点是 $v_1 = v_2 = 2$ 与 $v_1 + v_2 = 4$ 的读数；下方的数轴标出由它们算出的 $c = -1$，阴影是 $c$ 能落入的范围，其中的整数只有 $-1$、$0$、$1$。
:::

[@thm-deficit-integer] 的第三部分把同一个整数读成进位的计数。按 [@thm-zeck-add]，$v_1 + v_2$ 的 Zeckendorf 数位，就是把两组数位逐位相加、再用进位规范化的结果。内部的进位在两个面上都不改变值（[@lem-face-invariant]）；只有最低的两条重复进位改变 $\beta$：$2F_2 = F_3$ 使它减少 $1$，$2F_3 = F_2 + F_4$ 使它增加 $1$，亏量等于前者的次数减去后者的次数。无论按什么顺序进位，只要最后得到规范的数位，终点与带符号的总数都相同（[@thm-charge-unique]）。进位规则见[附录 A 的“进位”一节](appendix-a-zeckendorf.md#sec-carries)。

::: {.viz src="golden-carry" preset="cancel" height="500"}
$6 + 6$ 的三次进位。每一行是一步之后的数位，格子里的筹码数就是那一位的数字，连线标出每次进位把筹码从哪里换到哪里。第一步把权重 $1$ 上的两枚换成权重 $2$ 上的一枚（$2F_2 = F_3$），记 $+1$；第三步把权重 $2$ 上的两枚换成权重 $1$ 与 $3$ 上各一枚（$2F_3 = F_2 + F_4$），记 $-1$；中间一步不改变 $\beta$，记 $0$。上方的标尺量的是当前数位的 $\beta$ 比结果的 $\beta$ 多出多少：它从 $0$ 出发，最后回到 $0$，所以 $c(6, 6) = 0$。
:::

## 亏量何时取哪个值 {#sec-phases}

[@thm-deficit-three-valued] 只说亏量落在 $\{-1, 0, 1\}$ 中，没有说哪一对 $(v_1, v_2)$ 取哪个值；[上一节](#sec-two-faces)的窗口也只给出范围。要知道具体的值，先把亏量写成取整算术，再看小数部分。

::: {.theorem #thm-beatty-deficit title="亏量的 Beatty 形式" lean="D5/S1/Deficit/ChargedCarryPath.deficit_eq_beattyDeficit"}
对自然数 $v$，记整数

$$
s(v) = \lfloor (v+1)\varphi \rfloor - 1 .
$$

对所有自然数 $v_1, v_2$，

$$
c(v_1, v_2) = s(v_1) + s(v_2) - s(v_1 + v_2).
$$
:::

::: proof
Lean 证明经过两条闭式。第一条：把 $v$ 的 Zeckendorf 表示中每个 $F_k$ 换成 $F_{k+1}$，得到整数 $S(v)$，则 $\beta(v) = S(v) - v\psi$；这来自 $\varphi^k = F_{k+1} - F_k\psi$，因为各项的 $F_k$ 加起来正是 $v$。第二条：$S(v) = \lfloor (v+1)\varphi \rfloor - 1 = s(v)$（trureturing 中的 `displacement_decode_eq_beatty_floor`）。代入 [@def-deficit]，线性项 $-v\psi$ 相消，剩下 $s(v_1) + s(v_2) - s(v_1 + v_2)$。完整证明由 Lean 内核检查。
:::

$s(v) + 1 = \lfloor (v+1)\varphi \rfloor$ 依次是黄金比的 Beatty 序列 $1, 3, 4, 6, 8, 9, 11, \dots$，定理由此得名。例如 $s(1) = \lfloor 2\varphi \rfloor - 1 = 2$，$s(2) = \lfloor 3\varphi \rfloor - 1 = 3$，于是 $c(1, 1) = 2 + 2 - 3 = 1$，与本章开头直接算出的结果一致。

::: {.theorem #thm-golden-phase title="相位判据" lean="D5/S1/Deficit/GoldenPhaseDeficit.golden_phase_deficit"}
记 $\{x\} = x - \lfloor x \rfloor$ 为 $x$ 的小数部分，$p(v) = \{(v+1)\varphi\}$，并记 $B(v_1, v_2) = s(v_1) + s(v_2) - s(v_1 + v_2)$，其中 $s$ 如 [@thm-beatty-deficit]。对所有自然数 $v_1, v_2$：

- $B(v_1, v_2) = 1$ 当且仅当 $p(v_1) + p(v_2) < 1/\varphi$；
- $B(v_1, v_2) = -1$ 当且仅当 $p(v_1) + p(v_2) \ge \varphi$；
- $B(v_1, v_2) = 0$ 当且仅当 $1/\varphi \le p(v_1) + p(v_2) < \varphi$。
:::

::: proof
只需取整算术。记 $x = (v_1+1)\varphi$，$y = (v_2+1)\varphi$，则 $(v_1 + v_2 + 1)\varphi = x + y - \varphi$。把 $x$、$y$ 拆成整数部分与小数部分，得

$$
B(v_1, v_2) = -1 - \lfloor p(v_1) + p(v_2) - \varphi \rfloor .
$$

因为 $0 \le p(v_1) + p(v_2) < 2$ 且 $1 < \varphi < 2$，取整号内的数落在 $[-\varphi, 2 - \varphi) \subset [-2, 1)$ 中，取整只能是 $-2$、$-1$ 或 $0$，分界点是 $\varphi - 1 = 1/\varphi$ 与 $\varphi$。完整证明由 Lean 内核检查。
:::

由 [@thm-beatty-deficit]，$B(v_1, v_2) = c(v_1, v_2)$，所以这也是亏量本身的判据：两个相位之和小于 $1/\varphi$ 时亏量为 $1$，不小于 $\varphi$ 时为 $-1$，其余情形为 $0$。trureturing 还把这一组合直接写成了进位计数的形式（`carrySignedCount_phase_classifier`）。把两个相位画成单位正方形中的一点，判据就成了一张图：

::: {.figure src="phase-square"}
**相位正方形。** 两条斜线把它分成三块：青色三角形中亏量为 $+1$，品红三角形中为 $-1$，中间的带状区域为 $0$。
:::

横轴是 $p(v_1)$，纵轴是 $p(v_2)$。斜线 $p_1 + p_2 = 1/\varphi$ 连接两轴上的 $1/\varphi$ 刻度，它左下方的三角形中亏量为 $+1$；斜线 $p_1 + p_2 = \varphi$ 连接 $(1/\varphi, 1)$ 与 $(1, 1/\varphi)$，它右上方的小三角形（含这条线）中亏量为 $-1$；两线之间的带状区域（含下面那条线）中亏量为 $0$。图中 64 个点是 $0 \le v_1, v_2 \le 7$ 时的相位对 $(p(v_1), p(v_2))$，按计算值画出，与 [@ex-small-deficits] 的表对应：左下三角形中有 10 个点，右上三角形中有 6 个点。

相位只看小数部分，$p = 0$ 与 $p = 1$ 是同一个相位，所以正方形的左右两边是同一条线，上下两边也是。把它们粘起来，正方形就成了一个环面。这时两条斜线接成了同一条闭曲线：$\varphi = 1 + 1/\varphi$，所以 $p_1 + p_2 = \varphi$ 就是 $p_1 + p_2 \equiv 1/\varphi \ (\mathrm{mod}\ 1)$。

::: {.viz src="phase-torus" preset="torus" height="500"}
**把相位正方形粘成环面。** 先把上下两边粘成管子，再把管子的两端接起来：青色三角形（$c = +1$）与品红三角形（$c = -1$）在环面上隔着同一条紫色闭曲线相对；珠子是 $0 \le v_1, v_2 \le 7$ 的相位对，按亏量着色。颜色按 [@thm-golden-phase] 划分；粘合只说明哪些边是同一条线，不改变任何相位。
:::

::: {.example #ex-small-deficits title="小数值表"}
下表列出 $0 \le v_1, v_2 \le 7$ 时的 $c(v_1, v_2)$，行是 $v_1$，列是 $v_2$。

| $v_1 \backslash v_2$ | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 1 | 0 | +1 | 0 | 0 | +1 | 0 | +1 | 0 |
| 2 | 0 | 0 | −1 | 0 | 0 | 0 | 0 | −1 |
| 3 | 0 | 0 | 0 | 0 | +1 | 0 | 0 | 0 |
| 4 | 0 | +1 | 0 | +1 | +1 | 0 | +1 | 0 |
| 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | −1 |
| 6 | 0 | +1 | 0 | 0 | +1 | 0 | 0 | 0 |
| 7 | 0 | 0 | −1 | 0 | 0 | −1 | 0 | −1 |

每一项都按 [@def-deficit] 在 $\mathbb{Z}[\varphi]$ 中精确算出（用 $\varphi^k = F_{k-1} + F_k\varphi$），再与另外三种算法逐一核对：Beatty 形式 $s(v_1) + s(v_2) - s(v_1 + v_2)$，[@thm-golden-phase] 的相位判据，以及逐位相加再进位时的带符号计数。对 $v_1, v_2 < 120$ 的全部 14400 对，四者都一致。这是有限的计算，不是证明；一般情形由 [@thm-beatty-deficit] 与 [@thm-golden-phase] 保证。

以 $c(2, 2) = -1$ 为例。$2 + 2 = 4 = F_4 + F_2$，所以 $c(2, 2) = 2\varphi^3 - \varphi^4 - \varphi^2 = -1$。Beatty 形式给出 $s(2) + s(2) - s(4) = 3 + 3 - 7 = -1$。相位上 $p(2) = \{3\varphi\} \approx 0.854$，所以 $p(2) + p(2) \approx 1.708 \ge \varphi$。进位上，两组数位相加后 $F_3$ 处的数位是 $2$，规范化恰好用一次 $2F_3 = F_2 + F_4$，记 $-1$。第一行与第一列全是 $0$，因为 $\beta(0) = 0$；表关于对角线对称。
:::

::: {.viz src="golden-carry" preset="map" height="500"}
把上表延伸到 $0 \le v_1, v_2 \le 34$：横轴是 $v_1$，纵轴是 $v_2$，青色格 $c = +1$，品红格 $c = -1$，暗格 $c = 0$。左下角的 $8 \times 8$ 就是上表；琥珀色十字标出 $(17, 17)$。
:::

::: {.proposition #prop-phase-areas title="三种取值的面积" lean="D5/S1/Deficit/GoldenPhaseDistribution.limiting_deficit_distribution"}
令

$$
P = \int_0^{1/\varphi} \Bigl(\frac{1}{\varphi} - x\Bigr)\,dx, \qquad N = \int_0^{1/\varphi^2} \Bigl(\frac{1}{\varphi^2} - x\Bigr)\,dx .
$$

则

$$
P = \frac{1}{2\varphi^2}, \qquad N = \frac{1}{2\varphi^4}, \qquad P - N = \frac{1}{2\varphi^3}.
$$
:::

$P$ 是图中左下三角形 $\{p_1 + p_2 < 1/\varphi\}$ 的面积，按竖直截面积分：横坐标为 $x$ 处的截面长 $1/\varphi - x$。$N$ 是右上三角形 $\{p_1 + p_2 \ge \varphi\}$ 的面积；它的两条直角边长 $2 - \varphi = 1/\varphi^2$，积分是对它关于正方形中心翻转后的三角形做的。数值上 $P \approx 0.1910$，$N \approx 0.0729$，$P - N \approx 0.1180$；于是中间带状区域的面积是 $1 - P - N = \sqrt5 - 3/2 \approx 0.7361$。把积分读成面积，以及最后这一步减法，是本书的说明；所引声明只计算这两个积分。

::: {.remark #rem-areas-not-frequencies title="面积还不是频率"}
若把 $(p(v_1), p(v_2))$ 换成单位正方形中均匀分布的随机点，[@thm-golden-phase] 中每块区域的概率就是它的面积：$P$、$N$ 分别是取 $+1$、$-1$ 的概率，$P - N$ 是期望。Lean 中两个积分因此名为 `positiveFrequency` 与 `negativeFrequency`，trureturing 的 Blueprint 页面 `Blueprint/D5/S1/Deficit/GoldenPhaseDistribution.md` 也把这三个数写成 freq(+1)、freq(−1) 与 E(c)。

但 [@prop-phase-areas] 只计算面积。关于整数的频率说法，即在 $0 \le v_1, v_2 < n$ 的 $n^2$ 对中，$c = 1$ 与 $c = -1$ 所占的比例当 $n \to \infty$ 时分别趋于 $P$ 与 $N$，并不在所引声明之中，trureturing 也没有冻结这一结论。它可以由相位的等分布推出[^equi]。一维的等分布在 trureturing 中有对应的声明（模块 `D5/S1/Phase/IntervalSampling` 中的 `irrational_rotation_interval_sampling`），本书没有引用它；从一维推到相位对、再推到亏量比例的经典论证未在本书形式化。所以这一结论不是开放问题，只是还没有 Lean 证明。

下表的比例是计算，只说明数值上很接近：

| $n$ | $c = 1$ 的比例 | $c = -1$ 的比例 |
| ---: | ---: | ---: |
| 10 | 0.1700 | 0.0600 |
| 100 | 0.1885 | 0.0719 |
| 1000 | 0.1910 | 0.0729 |
| 10000 | 0.1910 | 0.0729 |
:::

::: {.viz src="golden-carry" preset="fill" height="500"}
相位正方形：每个点是一对 $(p(v_1), p(v_2))$，$v_1, v_2$ 取遍小于 $n$ 的自然数，$n$ 写在图的标题里。青色点 $c = +1$，品红点 $c = -1$，灰点 $c = 0$，三种颜色被两条斜线分开；标题下一行给出两种颜色所占的比例与两块三角形的面积。
:::

[^equi]: 这是 Weyl 等分布定理的特例：$\alpha$ 为无理数时，序列 $\{n\alpha\}$（$n = 1, 2, 3, \dots$）在 $[0, 1)$ 中等分布，即对任意 $0 \le a < b \le 1$，满足 $\{n\alpha\} \in [a, b)$ 的 $n \le m$ 所占的比例当 $m \to \infty$ 时趋于 $b - a$（H. Weyl, Über die Gleichverteilung von Zahlen mod. Eins, *Math. Ann.* 77 (1916), 313–352）。取 $\alpha = \varphi$ 并把下标平移一位，$p(v) = \{(v+1)\varphi\}$ 也等分布。$v_1$ 与 $v_2$ 各自取遍 $0, \dots, n-1$ 时，相位对的经验分布是两个一维经验分布的乘积，因而趋于正方形上的均匀分布；两个三角形的边界面积为零，所以比例趋于面积。

## 动手看一看

下面的交互可视化与视频都由本书仓库构建：画面上的数值只是页面上的计算，帮助理解；结论成立与否以 Lean 为准。

::: {.viz src="golden-carry" height="620"}
完整的实验室：换一对数 $v_1, v_2$，在进位、亏量图、相位、窗口四个场景之间切换，或沿实验卡逐张看；亏量 $c(v_1, v_2)$ 总是 $-1$、$0$、$1$ 之一（[@thm-deficit-three-valued]）。
:::

::: {.film src="001-golden-deficit"}
动画：两个 Zeckendorf 表示相加、进位，以及亏量为什么只取 $-1, 0, 1$（[@thm-deficit-three-valued]）。
:::
