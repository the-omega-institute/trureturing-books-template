# 第二章 反驳与可观测性

[第一章](ch01-golden-deficit.md) 的定理都是肯定的：亏量是整数，只取三个值。本章讨论两种否定。一种是反驳：一个全称断言为假，由一份有限的证书说明。另一种是不可观测：某个量不能从给定的读数恢复。本章用到下面几个词。

证书
: 有限的数据，连同一个可以机械执行的检查；检查通过，就推出要证的结论。

反例
: 使一个全称断言不成立的具体输入，是最常见的证书。

反例搜索
: 按固定顺序穷举有限多个候选，返回第一个不满足断言的候选。找到了，就得到一份证书；没有找到，只说明这些候选中没有反例，不说明断言成立。

对偶证书
: 不指向任何一个候选、而是一次排除全部候选的数据，例如 Farkas 权重（[@thm-farkas]）。

读数
: 从对象到读数空间的映射。读数相同的对象构成一个纤维；纤维里的对象在读数下无法区分。

## 反驳一个猜想

对正整数 $n$，令 $a(n)$ 为满足 $(1 + 1/n)^k \le 2$ 的自然数 $k$ 中最大的一个[^sup]，这是 OEIS 数列 A175406。该条目的公式栏写道：

> a(n) = n log 2 + O(1). Conjecture: a(n) = floor((n + 1/2) log 2).
>
> —— Charles R Greathouse IV，OEIS A175406，2012 年 4 月 3 日

前半句是渐近估计，后半句是一个精确的取整公式。被反驳的是后半句。

[^sup]: Lean 把 $a(n)$ 定义为自然数集合 $\{k : (1 + 1/n)^k \le 2\}$ 的上确界，对所有自然数都有定义。$n \ge 1$ 时这个集合含 $0$ 且有上界，上确界就是最大元。$n = 0$ 时，按 Lean 的约定 $1/0 = 0$，集合是全体自然数，没有上界，按自然数上确界的约定取 $0$。猜想只涉及 $n \ge 1$，这个约定不影响任何结论。

::: {.theorem #thm-greathouse-refuted title="该取整公式不成立" lean="D5/S0/Certificates/GreathouseLogTwoFloorRefutation.result"}
对 $n \ge 1$，令 $a(n)$ 为满足 $(1 + 1/n)^k \le 2$ 的最大自然数 $k$。命题
$$
\forall n \in \mathbb{N},\quad n \ge 1 \Rightarrow a(n) = \left\lfloor \left(n + \tfrac12\right) \log 2 \right\rfloor_+
$$
不成立。这里 $\log$ 是自然对数，$\lfloor x \rfloor_+$ 是取值于自然数的下取整，$x \ge 0$ 时就是通常的 $\lfloor x \rfloor$。
:::

::: proof
在 Lean 中，[`result`](lean:D5/S0/Certificates/GreathouseLogTwoFloorRefutation.result) 的类型只是 `¬ claim`。下面的数值都只出现在证明内部，是证明建立的局部事实，不是单独导出的定理。

证明取 $n_0 = 1121626023352383$ 与 $M = 777451915729368$，从级数
$$
\log\left(1 + \frac1a\right) = \sum_{k \ge 0} \frac{2}{2k+1} \left(\frac{1}{2a+1}\right)^{2k+1} \qquad (a > 0)
$$
得到两个对数的上下界。取 $a = 1$：前 $36$ 项之和 $S_{36}$ 是 $\log 2$ 的下界，用几何级数控制尾项，又得 $\log 2 \le S_{36} + 3^{-72}$。取 $a = n_0$：前两项给出 $\log(1 + 1/n_0)$ 的下界，$\log(1 + x) \le x$ 给出上界。然后用精确的有理数运算验证三件事：

- $M \le (n_0 + \tfrac12) S_{36}$ 且 $(n_0 + \tfrac12)(S_{36} + 3^{-72}) < M + 1$，所以 $\lfloor (n_0 + \tfrac12) \log 2 \rfloor_+ = M$；
- $M \log(1 + 1/n_0) > \log 2$，所以 $(1 + 1/n_0)^M > 2$；
- $(M - 1)/n_0 < S_{36} \le \log 2$，所以 $(1 + 1/n_0)^{M-1} \le 2$。

于是 $a(n_0) = M - 1 \ne M$，命题在 $n_0$ 处失效。完整证明由 Lean 内核检查。
:::

为什么要 $36$ 项？我们用 90 位十进制运算算得 $(n_0 + \tfrac12)\log 2 - M \approx 1.48 \times 10^{-17}$，$M \log(1 + 1/n_0) - \log 2 \approx 3.28 \times 10^{-32}$：两处的余量都极小，估计必须足够精确。余量这样小也有原因：我们核对过，$M/(2n_0 + 1)$ 是 $(\log 2)/2$ 的一个连分数渐近分数，所以 $(n_0 + \tfrac12)\log 2 = (2n_0 + 1) \cdot (\log 2)/2$ 离整数 $M$ 极近。trureturing 的问题文档记载，这个见证正是从这个连分数中找到的。怎样找到证书不影响证书是否成立：Lean 只检查上面的不等式。

::: {.problem #prob-greathouse-minimal title="最小反例"}
$n_0 = 1121626023352383$ 是否是使公式失效的最小 $n \ge 1$？使公式失效的 $n$ 有怎样的刻画？trureturing 只证明了 `¬ claim`，不主张 $n_0$ 最小。问题文档 `Problems/oeis-a175406-log-two-floor-refutation.md` 提到搜索者给出的一个最小性论证，并注明它未经核实、也未形式化。
:::

作为计算（不是证明）：我们逐个核对了 $1 \le n \le 20000$，公式在这些 $n$ 上都成立。其中 $n \le 3000$ 时 $a(n)$ 用精确整数运算算出（$(1 + 1/n)^k \le 2$ 等价于 $(n+1)^k \le 2n^k$），其余的值用至少 60 位十进制运算算出，并确认取整时离整数足够远；$n = 1, \dots, 10$ 时 $a(n) = 1, 1, 2, 3, 3, 4, 5, 5, 6, 7$。$20000$ 与 $n_0$ 之间的情形，这样的计算什么也没有说明。

## 观测能恢复什么

::: {.theorem #thm-target-recovery title="目标恢复判据" lean="D5/S3/ConceptDynamics/Restoration/TargetRecoveryCriterion.target_recovery_criterion"}
设状态空间 $X$ 非空，过程读数 $p: X \to P$，目标 $t: X \to T$。存在恢复函数 $r$ 使 $t = r \circ p$，当且仅当任意两个读数相同的状态有相同的目标值；这又等价于目标缺陷关系（读数相同而目标不同的状态对 $(x, y)$ 构成的集合）为空。因此，不能恢复当且仅当这个关系非空。
:::

[@thm-target-recovery] 只断言恢复函数存在，不提供算法，也不给出代价界。

## 有限证书 {#sec-certificates}

[@thm-greathouse-refuted] 的证明本身就是一份证书：一个输入，加上几条可以精确检查的不等式。本节再看三种证书，最后比较它们。第一种比 [@thm-greathouse-refuted] 更简单，只需要一个小整数和两次有限计算。OEIS A008365 是 13-粗糙数（没有小于 $13$ 的素因子的正整数），条目中有这样一条注释：

> Conjecture: Numbers n such that n^24 is congruent to {1,421,631,841} mod 2310.
>
> —— Gary Detlefs，OEIS A008365，2011 年 12 月 30 日

::: {.theorem #thm-detlefs-refuted title="一个整数推翻一条刻画" lean="D5/S0/Certificates/DetlefsRoughResidueCharacterizationRefutation.result"}
称自然数 $n$ 为 13-粗糙数，如果它的每个素因子都至少是 $13$（于是 $1$ 也是）。命题“对所有正整数 $n$：$n$ 是 13-粗糙数，当且仅当 $n^{24} \bmod 2310 \in \{1, 421, 631, 841\}$”不成立。
:::

::: proof
证书是 $n = 17$。$17$ 是素数，唯一的素因子 $17 \ge 13$，所以它是 13-粗糙数。另一方面 $17^{24} \bmod 2310 = 1681$，不在四个剩余之中。Lean 用内核计算（`decide`）检查 $17$ 的素性和这个余数；从 $17$ 是素数推出它 13-粗糙，用的是素数只有平凡因子。

余数也可以手算。$2310 = 2 \cdot 3 \cdot 5 \cdot 7 \cdot 11$。对 $p = 2, 3, 5, 7$，$p - 1$ 整除 $24$，所以 $17^{24} \equiv 1 \pmod{210}$；模 $11$ 有 $17 \equiv 6$ 与 $17^{24} \equiv 6^4 = 1296 \equiv 9$。模 $2310$ 中与 $1$ 模 $210$ 同余的数是 $1 + 210k$（$0 \le k \le 10$），而 $210 \equiv 1 \pmod{11}$，所以 $k = 8$，余数是 $1681$。完整证明由 Lean 内核检查。
:::

这个手算也说明了猜想漏掉了什么：四个剩余都是 $1 + 210k$ 的形状，$k = 0, 2, 3, 4$，模 $11$ 分别是 $1, 3, 4, 5$；漏掉的是模 $11$ 余 $9$ 的那一类。

::: {.remark #rem-a008365-corrected title="修正后的刻画"}
对所有正整数 $n$：$n$ 是 13-粗糙数，当且仅当 $n^{24} \bmod 2310 \in \{1, 421, 631, 841, 1681\}$。两个方向都有初等的纸面证明（见下文），都没有经过 Lean 检查。所以这一刻画不是开放问题，只是还没有 Lean 证明；尚待完成的是在 Lean 中形式化这两个方向并冻结。
:::

这一刻画记录在问题文档 `Problems/oeis-a008365-detlefs-rough-residue-characterization-refutation.md` 中，标注为“披露但不主张”：trureturing 没有证明它，Blueprint 写明既不主张这个修正刻画，也不主张它的逆。文档给出了它的结构原因，也就是刻画的一个方向：13-粗糙数 $n$ 与 $2310$ 互素，所以 $n^{24} \equiv 1 \pmod{210}$；模 $11$ 时 $n^{24} \equiv n^4$，只取四次剩余 $1, 3, 4, 5, 9$ 这五个值。模 $2310$ 中与 $1$ 模 $210$ 同余的余数是 $1 + 210k$（$0 \le k \le 10$）；因为 $210 \equiv 1 \pmod{11}$，它模 $11$ 等于 $1 + k$，恰在 $k = 0, 2, 3, 4, 8$ 时取这五个值之一，对应的余数就是 $1, 421, 631, 841, 1681$。另一个方向文档没有讨论，但同样直接：若正整数 $n$ 不是 13-粗糙数，它有一个小于 $13$ 的素因子 $p$，即 $p \in \{2, 3, 5, 7, 11\}$；$p$ 同时整除 $n^{24}$ 与 $2310$，所以也整除 $n^{24} \bmod 2310$。而五个剩余都与 $1$ 模 $210$ 同余，不被 $2, 3, 5, 7$ 整除，模 $11$ 又都不为 $0$，没有一个被 $p$ 整除，所以 $n^{24} \bmod 2310$ 不在其中。数值计算与此一致（计算不是证明）：$1 \le n \le 200000$ 中修正刻画没有例外；原来的四剩余刻画有 $8311$ 个例外，都是 13-粗糙而不在四个剩余中的数，前五个是 $17, 61, 71, 83, 127$。

第二种证书说明这种“找到一个反例”的模式是普遍的。

::: {.theorem #thm-finite-counterexample title="否定即找到反例" lean="D5/S0/Computability/FiniteCounterexampleCertificate.finite_readout_counterexample_certificate"}
设 $\mathcal{H}$ 是两个标记 $E_0, E_1$ 上全体有限字（标记历史）的集合，$D: \mathcal{H} \to \{\mathrm{true}, \mathrm{false}\}$ 是任一布尔判定。记 $\mathrm{find}(D, n)$ 为有界搜索：按长度从小到大逐层枚举长度不超过 $n$ 的全部历史，返回第一个满足 $D(h) = \mathrm{false}$ 的历史 $\mathrm{some}\ h$，没有时返回 $\mathrm{none}$。则
$$
\neg\left(\forall h \in \mathcal{H},\ D(h) = \mathrm{true}\right) \iff \exists n \in \mathbb{N},\ \exists h \in \mathcal{H},\ \mathrm{find}(D, n) = \mathrm{some}\ h \ \wedge\ D(h) = \mathrm{false}.
$$
:::

::: proof
从左到右：取一个被拒绝的历史 $h$，以它的长度为界 $n$；搜索是完备的，界内有被拒绝的历史就一定返回某个 $\mathrm{some}\ h'$，又是可靠的，返回的 $h'$ 确实满足 $D(h') = \mathrm{false}$。从右到左：被拒绝的 $h$ 直接与全称断言矛盾。完整证明由 Lean 内核检查。
:::

$\mathrm{find}$ 在 Lean 中是 `findCounterexample`，定义在模块 `D5/S0/History/MarkerHistorySearch` 中；trureturing 在那里用 `rfl` 检查过一个实例：$D$ 接受空字和以 $E_0$ 开头的字，则 $\mathrm{find}(D, 1)$ 返回只含一个标记 $E_1$ 的历史。[@thm-finite-counterexample] 不是判定方法：它不说明怎样从 $D$ 得到界 $n$；$D$ 处处为真时，对每个 $n$ 搜索都返回 $\mathrm{none}$。所以有界搜索只能半判定全称断言的失败。定理也不断言返回的反例最短。

第三种证书不是反例。

::: {.theorem #thm-farkas title="Farkas 证书" lean="D5/S0/Certificates/RationalFarkas.infeasible_of_certificate"}
设 $I$（约束）与 $J$（变量）是有限集，$A = (A_{ij})_{i \in I, j \in J}$ 与 $b = (b_i)_{i \in I}$ 的分量都是有理数。若有理数 $y_i$（$i \in I$）满足
$$
y_i \ge 0 \ (i \in I), \qquad \sum_{i \in I} y_i A_{ij} = 0 \ (j \in J), \qquad \sum_{i \in I} y_i b_i < 0,
$$
则不存在有理数 $x_j$（$j \in J$）使得对所有 $i \in I$ 都有 $\sum_{j \in J} A_{ij} x_j \le b_i$。
:::

::: proof
设 $x$ 是一个解。把第 $i$ 个不等式乘以 $y_i \ge 0$ 再相加：左边是 $\sum_j \left(\sum_i y_i A_{ij}\right) x_j = 0$，右边是 $\sum_i y_i b_i$，于是 $0 \le \sum_i y_i b_i < 0$，矛盾。完整证明由 Lean 内核检查。
:::

满足这三个条件的 $y$ 在 Lean 中是结构 `Certificate`。$y$ 可以由外部的线性规划软件给出，Lean 只检查这三个有限条件。定理只给出“有证书则无解”这一方向；反方向（每个无解的系统都有这样的证书，即 Farkas 引理）这里没有陈述。它谈的也只是有理解。一个最小的例子：
$$
\begin{aligned}
x_1 + x_2 &\le 1,\\
-x_1 &\le -1,\\
-x_2 &\le -1.
\end{aligned}
$$
取 $y = (1, 1, 1)$：$x_1$ 的系数之和是 $1 - 1 + 0 = 0$，$x_2$ 的是 $1 + 0 - 1 = 0$，右边之和是 $1 - 1 - 1 = -1 < 0$。所以这个系统没有有理解：三式相加就是 $0 \le -1$。

::: {.remark #rem-certificates title="证书不只是反例"}
本章的几份证书可以并排比较。

| 结论 | 被否定的断言 | 证书 | 检查 |
| --- | --- | --- | --- |
| [@thm-greathouse-refuted] | 对所有 $n \ge 1$，公式成立 | $n_0$，以及 $\log 2$ 与 $\log(1 + 1/n_0)$ 的有理上下界 | 大整数上的精确有理运算 |
| [@thm-detlefs-refuted] | 对所有 $n > 0$，刻画成立 | $n = 17$ | 一次素性检查，一次取余 |
| [@thm-finite-counterexample] | 对所有历史 $h$，$D(h)$ 为真 | 界 $n$ 与被拒绝的历史 $h$ | 运行搜索，计算 $D(h)$ |
| [@thm-farkas] | 存在 $x$ 使 $Ax \le b$ | 非负权重 $y$ | 三组有限的等式与不等式 |

前三行都是反例：否定一个全称断言，一个输入就够了。第四行方向相反：被否定的是一个存在断言，候选点 $x$ 有无穷多个，证书却不指向其中任何一个，而是用有限多个有理数一次排除全部。另一点也值得注意：在 Lean 中，[@thm-greathouse-refuted] 与 [@thm-detlefs-refuted] 的陈述都只是 `¬ claim`，证书只出现在证明里。下一节的 [@thm-modulus-blind] 又不同：它断言见证存在，证明却不构造见证。
:::

## 看不见的部分 {#sec-blind-spots}

按 [@thm-target-recovery]，目标不能从读数恢复，恰好是因为有两个读数相同、目标不同的状态。下面两条定理各给出这样一对状态的来源：一条只靠计数，另一条来自 [第一章](ch01-golden-deficit.md) 的黄金相位。

::: {.theorem #thm-pigeonhole-fiber title="读数少于对象" lean="D5/S0/Diagonal/PigeonholeFiber.finite_reading_has_fiber"}
设 $O$ 与 $R$ 是两个类型，$\mathrm{read}: O \to R$。若 $R$ 的基数严格小于 $O$ 的基数，即 $|R| < |O|$，则存在 $x, y \in O$，使 $x \ne y$ 且 $\mathrm{read}(x) = \mathrm{read}(y)$。
:::

这是鸽笼原理的基数形式[^universe]。它不要求 $R$ 有限，只断言碰撞存在，不说是哪一对，也不说有多少对。与 [@thm-target-recovery] 合起来（取 $p = \mathrm{read}$，目标取恒等映射）：此时区分每一个对象的恒等目标不能从读数恢复。例如三位二进制串有 $8$ 个，按其中 $1$ 的个数读数只有 $4$ 种，$001$ 与 $010$ 就读数相同。

[^universe]: Lean 要求 $O$ 与 $R$ 在同一个类型宇宙中。这是形式化的技术条件，对本书的用法没有影响。

::: {.theorem #thm-modulus-blind title="余数看不见亏量" lean="D5/S1/Deficit/FixedModulusNoncongruence.deficit_not_determined_by_fixed_modulus"}
对每个满足 $m \ge 2$ 的自然数 $m$，存在自然数 $v_1, v_2, v_1', v_2'$，使
$$
v_1 \equiv v_1' \pmod m, \qquad v_2 \equiv v_2' \pmod m, \qquad c(v_1, v_2) \ne c(v_1', v_2'),
$$
其中 $c$ 是 [@def-deficit] 中的亏量。
:::

::: proof
证明取 $v_1 = v_1' = 1$，并让 $v_2, v_2'$ 都是 $m$ 的倍数，同余就自动成立。记 $p(v) = \{(v+1)\varphi\}$ 为黄金相位（小数部分），则 $p(1) = 2\varphi - 3 \approx 0.236$。由 [@thm-beatty-deficit]，$c$ 等于它的 Beatty 形式（该模块自带这条等式的一份证明）；再由 [@thm-golden-phase]：$p(v) < (2 - \varphi)/2$ 时 $c(1, v) = 1$，$2 - \varphi < p(v) < (3 - \varphi)/2$ 时 $c(1, v) = 0$。因为 $m\varphi$ 是无理数，相位 $p(mn)$（$n = 0, 1, 2, \dots$）在 $[0, 1)$ 中稠密，所以两个区间里各有某个 $p(mn)$。证明只用稠密性断言这样的 $n$ 存在，并不给出它们。完整证明由 Lean 内核检查。
:::

与 [@thm-target-recovery] 合起来：取状态空间 $\mathbb{N} \times \mathbb{N}$，读数为 $(v_1 \bmod m, v_2 \bmod m)$，目标为 $c$；[@thm-modulus-blind] 给出读数相同、目标不同的一对状态，所以没有函数能从模 $m$ 的余数算出亏量。看不见亏量的是余数，而不是一切读数：[@thm-beatty-deficit] 与 [@thm-golden-phase] 合起来说明，两个黄金相位精确地决定亏量。定理只断言分歧存在，不给出见证，也不涉及分歧在输入中占多大比例。

::: {.example #ex-mod-two title="模 2 的一对反例"}
取 $m = 2$。输入对 $(1, 2)$ 与 $(1, 4)$ 模 $2$ 逐个同余：$1 \equiv 1$，$2 \equiv 4$。由 $\beta(1) = \varphi^2$、$\beta(2) = \varphi^3$、$\beta(3) = \varphi^4$、$\beta(4) = \varphi^4 + \varphi^2$、$\beta(5) = \varphi^5$ 与 $\varphi^{k+2} = \varphi^{k+1} + \varphi^k$，
$$
\begin{aligned}
c(1, 2) &= \varphi^2 + \varphi^3 - \varphi^4 = 0,\\
c(1, 4) &= \varphi^2 + (\varphi^4 + \varphi^2) - \varphi^5 = 2\varphi^2 - \varphi^3 = \varphi^2 - \varphi = 1.
\end{aligned}
$$
这与 [@thm-golden-phase] 一致（$p$ 是上面证明中的黄金相位，$1/\varphi \approx 0.618$）：$p(1) + p(2) \approx 0.236 + 0.854 = 1.090$ 落在 $[1/\varphi, \varphi)$ 中，$p(1) + p(4) \approx 0.236 + 0.090 = 0.326 < 1/\varphi$。同一个余数类中，亏量甚至可以取遍三个值，例如下表中的余数类 $(0, 0)$。下表在 $\mathbb{Z}[\varphi]$ 中精确计算，只是例子，不是定理。

| $(v_1, v_2)$ | 模 2 的余数 | $c(v_1, v_2)$ |
| --- | --- | --- |
| $(1, 2)$ | $(1, 0)$ | $0$ |
| $(1, 4)$ | $(1, 0)$ | $1$ |
| $(2, 2)$ | $(0, 0)$ | $-1$ |
| $(2, 4)$ | $(0, 0)$ | $0$ |
| $(4, 4)$ | $(0, 0)$ | $1$ |
:::

[第三章](ch03-refinement-memory.md) 从这里继续：怎样细化读数、细化的代价是什么，以及读数随时间变粗时丢失了什么。

## 演示文稿

::: {.slides src="overview"}
十页演示文稿：全书概况，以及第一、二章的主要结果。
:::

另附传统学术报告版，提供演讲者备注与形式化验证账本。

::: {.slides src="overview-academic"}
九帧英文 Beamer 报告，包含纸面配色的可视化静态图和由书中脚本生成的图件。
:::
