# Chapter 1 The carry deficit of golden integers

Every natural number $n$ is, in a unique way, a sum of nonadjacent Fibonacci numbers (its Zeckendorf representation), with weights $F_2 = 1, F_3 = 2, F_4 = 3, \dots$. Replacing each weight $F_i$ by $\varphi^i$, where $\varphi = (1+\sqrt5)/2$ is the golden ratio, gives a real number $\beta(n)$.

::: {.definition #def-deficit title="Normalized deficit" lean="D5/S1/Deficit/DeficitInteger.deficit"}
For natural numbers $v_1, v_2$, define
$$
c(v_1, v_2) = \beta(v_1) + \beta(v_2) - \beta(v_1 + v_2).
$$
:::

$\beta$ does not preserve addition: for example $\beta(1) = \varphi^2$ and $\beta(2) = \varphi^3$, so $c(1, 1) = 2\varphi^2 - \varphi^3 = 1$.

::: {.theorem #thm-deficit-integer title="The deficit is an integer, the signed carry count" lean="D5/S1/Deficit/DeficitInteger.deficit_integer"}
For all natural numbers $v_1, v_2$, the deficit $c(v_1, v_2)$ equals its reading on the contraction face (the Galois conjugate), is an integer, and equals the signed count of the two lowest repeated-carry rules applied while normalizing the digitwise sum of the two Zeckendorf representations.
:::

::: {.theorem #thm-deficit-three-valued title="The deficit takes three values" lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
For all natural numbers $v_1, v_2$,
$$
c(v_1, v_2) \in \{-1, 0, 1\}.
$$
:::

::: proof
The contraction face evaluates Zeckendorf digits at powers of the conjugate $\psi = (1-\sqrt5)/2$. Each $\beta'(v)$ lies in the window $[-\psi^2, -\psi]$, whose length is exactly $1$, so the contraction-face reading of $c$ lies strictly between $-2$ and $2$; by [@thm-deficit-integer] it is an integer. The full proof is checked by the Lean kernel.
:::

::: remark
[@thm-deficit-three-valued] holds however large the inputs are: it ties an arithmetic algorithm (digitwise carrying) to an exact bound, and can be reused as a premise in later arguments. In Lean its name is [`deficit_three_valued`](lean:D5/S1/Deficit/DeficitThreeValued.deficit_three_valued).
:::

## Two faces {#sec-two-faces}

$\beta(v)$ evaluates the Zeckendorf digits of $v$ at powers of the golden ratio $\varphi$; we call it the expansion-face reading. The golden ratio is a root of $x^2 = x + 1$, whose other root is $\psi = (1-\sqrt5)/2 = -1/\varphi \approx -0.618$. Evaluating the same digits at powers of $\psi$ gives the contraction-face reading. [@thm-deficit-integer] says that the deficit reads the same on both faces; this section explains why, and supplies the window used in the proof of [@thm-deficit-three-valued].

::: {.definition #def-beta-contraction title="The contraction-face reading $\beta'$" lean="D5/S1/Deficit/DeficitInteger.betaContraction"}
Let $v = F_{k_1} + \dots + F_{k_r}$ be the Zeckendorf representation of a natural number $v$, with distinct, pairwise nonadjacent indices $k_j \ge 2$ (for existence and uniqueness see [@thm-zeckendorf-exists] and [@thm-zeckendorf-unique] in [Appendix A](appendix-a-zeckendorf.md)). Then $\beta(v) = \varphi^{k_1} + \dots + \varphi^{k_r}$ is an element of $\mathbb{Z}[\varphi]$. Applying the Galois conjugation $\varphi \mapsto \psi$ and taking the real value gives the contraction-face reading of $v$:

$$
\beta'(v) = \psi^{k_1} + \dots + \psi^{k_r}.
$$

For $v = 0$ the sum is empty and $\beta'(0) = 0$.
:::

For example, $\beta'(1) = \psi^2 \approx 0.382$, $\beta'(2) = \psi^3 \approx -0.236$ and $\beta'(4) = \psi^4 + \psi^2 \approx 0.528$. The expansion face grows with $v$, while the contraction face stays small; the next two lemmas make this precise.

::: {.lemma #lem-two-faces title="The gap between the faces" lean="D5/S1/Deficit/DoubleFaceLength.betaReal_sub_betaContraction"}
For every natural number $v$,

$$
\beta(v) - \beta'(v) = \sqrt5\, v.
$$
:::

For instance, $\beta(1) - \beta'(1) = \varphi^2 - \psi^2 = (\varphi - \psi)(\varphi + \psi) = \sqrt5$. The reason is that, written as $a + b\varphi$ with $a, b \in \mathbb{Z}$, $\beta(v)$ has $\varphi$-coefficient exactly $b = v$; conjugation only replaces $\varphi$ by $\psi$, so the two faces differ by $b(\varphi - \psi) = \sqrt5\, v$.

::: {.lemma #lem-window title="The window of the contraction face" lean="D5/S1/Words/Expansions/BasePhiNegativeBridge.betaContraction_mem_window"}
For every natural number $v$,

$$
-\psi^2 \le \beta'(v) \le -\psi .
$$
:::

The endpoints of the window are $-\psi^2 = -1/\varphi^2 \approx -0.382$ and $-\psi = 1/\varphi \approx 0.618$, and its length is $\psi^2 - \psi = 1$ (because $\psi^2 = \psi + 1$).

::: proof
First, where the window comes from. Since $-1 < \psi < 0$, the power $\psi^k$ is positive for even $k$ and negative for odd $k$. As $\beta'(v)$ is a sum of $\psi^k$ over distinct indices $k \ge 2$, it is at most the sum of all even powers and at least the sum of all odd powers:

$$
\beta'(v) \le \psi^2 + \psi^4 + \cdots = \frac{\psi^2}{1 - \psi^2} = -\psi, \qquad \beta'(v) \ge \psi^3 + \psi^5 + \cdots = \frac{\psi^3}{1 - \psi^2} = -\psi^2,
$$

using $1 - \psi^2 = -\psi$. This is [@lem-window]; the Lean proof likewise splits the sum into its even and odd parts and bounds each by a geometric series.

Now combine the window with integrality. By [@lem-two-faces], $\beta(v) = \beta'(v) + \sqrt5\, v$. Substituted into [@def-deficit], the linear terms $\sqrt5\, v_1 + \sqrt5\, v_2 - \sqrt5\,(v_1 + v_2)$ cancel, so

$$
c(v_1, v_2) = \beta'(v_1) + \beta'(v_2) - \beta'(v_1 + v_2),
$$

which is the first part of [@thm-deficit-integer]. The same fact shows that $c$ is an integer: the $\varphi$-coefficient of $c$ is $v_1 + v_2 - (v_1 + v_2) = 0$. In Lean, the first two parts of [`deficit_integer`](lean:D5/S1/Deficit/DeficitInteger.deficit_integer) follow from exactly this vanishing coefficient. Each of the three terms on the right lies in the window, so

$$
2(-\psi^2) - (-\psi) \le c(v_1, v_2) \le 2(-\psi) - (-\psi^2),
$$

that is, $\varphi - 3 \le c(v_1, v_2) \le \varphi$, roughly $-1.382 \le c \le 1.618$. The only integers in this interval are $-1$, $0$ and $1$, which is [@thm-deficit-three-valued]. The full proof is checked by the Lean kernel.
:::

::: {.viz src="golden-carry" preset="window" height="500"}
The window on the contraction face. In the upper part each point is the reading $\beta'(v)$ of one $v \le 34$, placed across by its value: every point lies between the two vertical lines at $-1/\varphi^2$ and $1/\varphi$. The amber points are the readings of $v_1 = v_2 = 2$ and of $v_1 + v_2 = 4$; the axis below marks the value $c = -1$ computed from them, and the shaded band is where $c$ can fall, with $-1$, $0$ and $1$ as its only integers.
:::

The third part of [@thm-deficit-integer] reads the same integer as a count of carries. By [@thm-zeck-add], the Zeckendorf digits of $v_1 + v_2$ are obtained by adding the two digit strings position by position and normalizing with carries. Internal carries leave the value unchanged on both faces ([@lem-face-invariant]). Only the two lowest repeated carries change $\beta$: $2F_2 = F_3$ lowers it by $1$ and $2F_3 = F_2 + F_4$ raises it by $1$, and the deficit is the number of the former minus the number of the latter. Whatever order the carries are applied in, as long as they end with canonical digits, the end point and the signed total are the same ([@thm-charge-unique]). The carry rules are set out in [the section on carries in Appendix A](appendix-a-zeckendorf.md#sec-carries).

::: {.viz src="golden-carry" preset="cancel" height="500"}
The three carries of $6 + 6$. Each row is the digit string after one more pass, the number of tokens in a cell is that digit, and the lines show where each carry takes tokens from and where it puts them. The first pass trades the two tokens on weight $1$ for one on weight $2$ ($2F_2 = F_3$) and counts $+1$; the third trades the two on weight $2$ for one each on weights $1$ and $3$ ($2F_3 = F_2 + F_4$) and counts $-1$; the pass in between leaves $\beta$ unchanged and counts $0$. The gauge above measures by how much $\beta$ of the current digits exceeds $\beta$ of the result: it starts at $0$ and returns to $0$, so $c(6, 6) = 0$.
:::

## When the deficit takes which value {#sec-phases}

[@thm-deficit-three-valued] only says that the deficit lies in $\{-1, 0, 1\}$; it does not say which pairs $(v_1, v_2)$ take which value, and the window of [the previous section](#sec-two-faces) gives no more than the range. To decide the value, we first write the deficit as floor arithmetic and then look at fractional parts.

::: {.theorem #thm-beatty-deficit title="The Beatty form of the deficit" lean="D5/S1/Deficit/ChargedCarryPath.deficit_eq_beattyDeficit"}
For a natural number $v$, let $s(v)$ be the integer

$$
s(v) = \lfloor (v+1)\varphi \rfloor - 1 .
$$

For all natural numbers $v_1, v_2$,

$$
c(v_1, v_2) = s(v_1) + s(v_2) - s(v_1 + v_2).
$$
:::

::: proof
The Lean proof goes through two closed forms. First, replacing every $F_k$ in the Zeckendorf representation of $v$ by $F_{k+1}$ gives an integer $S(v)$ with $\beta(v) = S(v) - v\psi$; this follows from $\varphi^k = F_{k+1} - F_k\psi$, because the $F_k$ add up to $v$. Second, $S(v) = \lfloor (v+1)\varphi \rfloor - 1 = s(v)$ (`displacement_decode_eq_beatty_floor` in trureturing). Substituted into [@def-deficit], the linear terms $-v\psi$ cancel and $s(v_1) + s(v_2) - s(v_1 + v_2)$ remains. The full proof is checked by the Lean kernel.
:::

The values $s(v) + 1 = \lfloor (v+1)\varphi \rfloor$ run through the Beatty sequence of the golden ratio, $1, 3, 4, 6, 8, 9, 11, \dots$, hence the name. For example, $s(1) = \lfloor 2\varphi \rfloor - 1 = 2$ and $s(2) = \lfloor 3\varphi \rfloor - 1 = 3$, so $c(1, 1) = 2 + 2 - 3 = 1$, as computed directly at the start of the chapter.

::: {.theorem #thm-golden-phase title="The phase criterion" lean="D5/S1/Deficit/GoldenPhaseDeficit.golden_phase_deficit"}
Write $\{x\} = x - \lfloor x \rfloor$ for the fractional part of $x$, let $p(v) = \{(v+1)\varphi\}$, and let $B(v_1, v_2) = s(v_1) + s(v_2) - s(v_1 + v_2)$ with $s$ as in [@thm-beatty-deficit]. For all natural numbers $v_1, v_2$:

- $B(v_1, v_2) = 1$ if and only if $p(v_1) + p(v_2) < 1/\varphi$;
- $B(v_1, v_2) = -1$ if and only if $p(v_1) + p(v_2) \ge \varphi$;
- $B(v_1, v_2) = 0$ if and only if $1/\varphi \le p(v_1) + p(v_2) < \varphi$.
:::

::: proof
Only floor arithmetic is needed. With $x = (v_1+1)\varphi$ and $y = (v_2+1)\varphi$ we have $(v_1 + v_2 + 1)\varphi = x + y - \varphi$. Splitting $x$ and $y$ into integer and fractional parts gives

$$
B(v_1, v_2) = -1 - \lfloor p(v_1) + p(v_2) - \varphi \rfloor .
$$

Since $0 \le p(v_1) + p(v_2) < 2$ and $1 < \varphi < 2$, the number inside the floor lies in $[-\varphi, 2 - \varphi) \subset [-2, 1)$, so the floor is $-2$, $-1$ or $0$, and the switching points are $\varphi - 1 = 1/\varphi$ and $\varphi$. The full proof is checked by the Lean kernel.
:::

By [@thm-beatty-deficit], $B(v_1, v_2) = c(v_1, v_2)$, so this is also a criterion for the deficit itself: it is $1$ when the two phases add up to less than $1/\varphi$, $-1$ when they add up to at least $\varphi$, and $0$ otherwise. trureturing also states this combination directly for the carry count (`carrySignedCount_phase_classifier`). Plotting the two phases as a point of the unit square turns the criterion into a picture:

::: {.figure src="phase-square"}
**The phase square.** Two diagonal lines cut it into three regions: the deficit is $+1$ in the cyan triangle, $-1$ in the magenta triangle and $0$ in the band between them.
:::

The horizontal axis is $p(v_1)$ and the vertical axis $p(v_2)$. The line $p_1 + p_2 = 1/\varphi$ joins the two $1/\varphi$ marks on the axes; in the triangle below it the deficit is $+1$. The line $p_1 + p_2 = \varphi$ joins $(1/\varphi, 1)$ and $(1, 1/\varphi)$; in the small triangle above it, the line included, the deficit is $-1$. In the band between the two lines, the lower line included, the deficit is $0$. The 64 dots are the phase pairs $(p(v_1), p(v_2))$ for $0 \le v_1, v_2 \le 7$, plotted from computed values; they match the table of [@ex-small-deficits]: 10 dots lie in the lower triangle and 6 in the upper one.

::: {.example #ex-small-deficits title="A table of small values"}
The table lists $c(v_1, v_2)$ for $0 \le v_1, v_2 \le 7$; rows are $v_1$, columns are $v_2$.

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

Every entry was computed exactly from [@def-deficit] in $\mathbb{Z}[\varphi]$ (using $\varphi^k = F_{k-1} + F_k\varphi$) and checked against three other computations: the Beatty form $s(v_1) + s(v_2) - s(v_1 + v_2)$, the phase criterion of [@thm-golden-phase], and the signed count of carries when the digits are added position by position and normalized. All four agree on all 14400 pairs with $v_1, v_2 < 120$. This is a finite computation, not a proof; the general case is [@thm-beatty-deficit] together with [@thm-golden-phase].

Take $c(2, 2) = -1$. Since $2 + 2 = 4 = F_4 + F_2$, we get $c(2, 2) = 2\varphi^3 - \varphi^4 - \varphi^2 = -1$. The Beatty form gives $s(2) + s(2) - s(4) = 3 + 3 - 7 = -1$. In phases, $p(2) = \{3\varphi\} \approx 0.854$, so $p(2) + p(2) \approx 1.708 \ge \varphi$. In carries, adding the digits puts a $2$ at $F_3$, and normalization uses exactly one carry $2F_3 = F_2 + F_4$, counted $-1$. The first row and the first column are $0$ because $\beta(0) = 0$, and the table is symmetric about the diagonal.
:::

::: {.viz src="golden-carry" preset="map" height="500"}
The table above, continued to $0 \le v_1, v_2 \le 34$: $v_1$ runs across and $v_2$ upward, cyan cells have $c = +1$, magenta cells $c = -1$ and dark cells $c = 0$. The $8 \times 8$ corner at the lower left is the table; the amber cross marks $(17, 17)$.
:::

::: {.proposition #prop-phase-areas title="The areas of the three values" lean="D5/S1/Deficit/GoldenPhaseDistribution.limiting_deficit_distribution"}
Let

$$
P = \int_0^{1/\varphi} \Bigl(\frac{1}{\varphi} - x\Bigr)\,dx, \qquad N = \int_0^{1/\varphi^2} \Bigl(\frac{1}{\varphi^2} - x\Bigr)\,dx .
$$

Then

$$
P = \frac{1}{2\varphi^2}, \qquad N = \frac{1}{2\varphi^4}, \qquad P - N = \frac{1}{2\varphi^3}.
$$
:::

$P$ is the area of the lower triangle $\{p_1 + p_2 < 1/\varphi\}$ of the figure, integrated by vertical cross-sections: at abscissa $x$ the cross-section has length $1/\varphi - x$. $N$ is the area of the upper triangle $\{p_1 + p_2 \ge \varphi\}$, whose legs have length $2 - \varphi = 1/\varphi^2$; the integral is taken over its mirror image through the centre of the square. Numerically $P \approx 0.1910$, $N \approx 0.0729$ and $P - N \approx 0.1180$, so the band in the middle has area $1 - P - N = \sqrt5 - 3/2 \approx 0.7361$. Reading the integrals as areas, and this last subtraction, are the book's commentary; the cited declaration computes the two integrals only.

::: {.remark #rem-areas-not-frequencies title="Areas are not yet frequencies"}
If $(p(v_1), p(v_2))$ is replaced by a random point distributed uniformly on the unit square, each region of [@thm-golden-phase] has probability equal to its area: $P$ and $N$ are the probabilities of $+1$ and $-1$, and $P - N$ is the expected value. That is why the two integrals are called `positiveFrequency` and `negativeFrequency` in Lean, and why the trureturing Blueprint page `Blueprint/D5/S1/Deficit/GoldenPhaseDistribution.md` writes the three numbers as freq(+1), freq(−1) and E(c).

But [@prop-phase-areas] only computes areas. The statement about integers, namely that among the $n^2$ pairs with $0 \le v_1, v_2 < n$ the proportions with $c = 1$ and with $c = -1$ tend to $P$ and $N$ as $n \to \infty$, is not part of the cited declaration, and trureturing has not frozen it. It follows from the equidistribution of the phases[^equi]. The one-dimensional equidistribution has a counterpart in trureturing (`irrational_rotation_interval_sampling` in the module `D5/S1/Phase/IntervalSampling`), which this book does not cite; the classical argument from one dimension to pairs of phases and on to the deficit proportions is not formalized in this book. So the statement is not an open problem; it simply has no Lean proof yet.

The proportions below are a computation and only show that the numbers are close:

| $n$ | proportion with $c = 1$ | proportion with $c = -1$ |
| ---: | ---: | ---: |
| 10 | 0.1700 | 0.0600 |
| 100 | 0.1885 | 0.0719 |
| 1000 | 0.1910 | 0.0729 |
| 10000 | 0.1910 | 0.0729 |
:::

::: {.viz src="golden-carry" preset="fill" height="500"}
The phase square: each point is a pair $(p(v_1), p(v_2))$, with $v_1, v_2$ running through the natural numbers below $n$, and $n$ is written in the title of the figure. Cyan points have $c = +1$, magenta points $c = -1$ and grey points $c = 0$, and two lines separate the three colours; the line under the title gives the shares of the two colours and the areas of the two triangles.
:::

[^equi]: This is a special case of Weyl's equidistribution theorem: for irrational $\alpha$ the sequence $\{n\alpha\}$, $n = 1, 2, 3, \dots$, is equidistributed in $[0, 1)$: for all $0 \le a < b \le 1$, the proportion of $n \le m$ with $\{n\alpha\} \in [a, b)$ tends to $b - a$ as $m \to \infty$ (H. Weyl, Über die Gleichverteilung von Zahlen mod. Eins, *Math. Ann.* 77 (1916), 313–352). With $\alpha = \varphi$ and the index shifted by one, $p(v) = \{(v+1)\varphi\}$ is equidistributed as well. When $v_1$ and $v_2$ each run through $0, \dots, n-1$, the empirical distribution of the phase pairs is the product of two one-dimensional empirical distributions, so it tends to the uniform distribution on the square; the boundaries of the two triangles have area zero, so the proportions tend to the areas.

## See it for yourself

The interactive visualization and the film below are built from this book's repository. The numbers on screen are computations on the page that help you see; whether a result holds is decided by Lean.

::: {.viz src="golden-carry" height="620"}
The whole lab: change the pair $v_1, v_2$, switch between the four scenes (carries, map, phases, window), or go through the experiment cards one by one; the deficit $c(v_1, v_2)$ is always $-1$, $0$ or $1$ ([@thm-deficit-three-valued]).
:::

::: {.film src="001-golden-deficit"}
Animation: adding two Zeckendorf representations, the carries, and why the deficit takes only $-1, 0, 1$ ([@thm-deficit-three-valued]).
:::
