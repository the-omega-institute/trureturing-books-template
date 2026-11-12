# Chapter 2 Refutation and observability

The theorems of [Chapter 1](ch01-golden-deficit.md) are all positive: the deficit is an integer and takes only three values. This chapter is about two kinds of negative result. One is refutation: a universal claim is false, and a finite certificate shows it. The other is unobservability: some quantity cannot be recovered from a given readout. The chapter uses the following vocabulary.

Certificate
: Finite data together with a check that can be carried out mechanically; if the check passes, the desired conclusion follows.

Counterexample
: A concrete input at which a universal claim fails; the most common kind of certificate.

Counterexample search
: An enumeration of finitely many candidates in a fixed order that returns the first one violating the claim. A hit is a certificate; a miss shows only that none of these candidates is a counterexample, not that the claim holds.

Dual certificate
: Data that points at no candidate at all but rules out every candidate at once, such as Farkas weights ([@thm-farkas]).

Readout
: A map from objects to a space of readings. Objects with the same reading form a fiber, and the readout cannot tell them apart.

## Refuting a conjecture

For a positive integer $n$, let $a(n)$ be the greatest natural number $k$ with $(1 + 1/n)^k \le 2$; this is the OEIS sequence A175406[^sup]. The formula field of the entry reads:

> a(n) = n log 2 + O(1). Conjecture: a(n) = floor((n + 1/2) log 2).
>
> — Charles R Greathouse IV, OEIS A175406, April 3, 2012

The first sentence is an asymptotic estimate; the second is an exact floor formula. It is the second that is refuted.

[^sup]: Lean defines $a(n)$ as the supremum of the set of natural numbers $\{k : (1 + 1/n)^k \le 2\}$, for every natural number $n$. For $n \ge 1$ the set contains $0$ and is bounded, so the supremum is its greatest element. For $n = 0$, Lean's convention $1/0 = 0$ makes the set all of $\mathbb{N}$, which is unbounded, and the supremum of an unbounded set of natural numbers is $0$ by convention. The conjecture concerns only $n \ge 1$, so this convention affects nothing.

::: {.theorem #thm-greathouse-refuted title="The floor formula is false" lean="D5/S0/Certificates/GreathouseLogTwoFloorRefutation.result"}
For $n \ge 1$, let $a(n)$ be the greatest natural number $k$ with $(1 + 1/n)^k \le 2$. The statement
$$
\forall n \in \mathbb{N},\quad n \ge 1 \Rightarrow a(n) = \left\lfloor \left(n + \tfrac12\right) \log 2 \right\rfloor_+
$$
is false. Here $\log$ is the natural logarithm and $\lfloor x \rfloor_+$ is the floor with values in the natural numbers, which is the usual $\lfloor x \rfloor$ for $x \ge 0$.
:::

::: proof
In Lean, the type of [`result`](lean:D5/S0/Certificates/GreathouseLogTwoFloorRefutation.result) is just `¬ claim`. The values below occur only inside the proof: they are facts the proof establishes along the way, not separately exported theorems.

The proof takes $n_0 = 1121626023352383$ and $M = 777451915729368$ and bounds two logarithms from above and below using the series
$$
\log\left(1 + \frac1a\right) = \sum_{k \ge 0} \frac{2}{2k+1} \left(\frac{1}{2a+1}\right)^{2k+1} \qquad (a > 0).
$$
With $a = 1$, the sum $S_{36}$ of the first $36$ terms bounds $\log 2$ from below, and a geometric bound on the tail gives $\log 2 \le S_{36} + 3^{-72}$. With $a = n_0$, the first two terms bound $\log(1 + 1/n_0)$ from below, and $\log(1 + x) \le x$ bounds it from above. Exact rational arithmetic then checks three facts:

- $M \le (n_0 + \tfrac12) S_{36}$ and $(n_0 + \tfrac12)(S_{36} + 3^{-72}) < M + 1$, so $\lfloor (n_0 + \tfrac12) \log 2 \rfloor_+ = M$;
- $M \log(1 + 1/n_0) > \log 2$, so $(1 + 1/n_0)^M > 2$;
- $(M - 1)/n_0 < S_{36} \le \log 2$, so $(1 + 1/n_0)^{M-1} \le 2$.

Hence $a(n_0) = M - 1 \ne M$, and the statement fails at $n_0$. The full proof is checked by the Lean kernel.
:::

Why $36$ terms? In 90-digit decimal arithmetic we find $(n_0 + \tfrac12)\log 2 - M \approx 1.48 \times 10^{-17}$ and $M \log(1 + 1/n_0) - \log 2 \approx 3.28 \times 10^{-32}$. Both margins are tiny, so the estimates must be very sharp. The margins are small for a reason: as we checked, $M/(2n_0 + 1)$ is a continued-fraction convergent of $(\log 2)/2$, so $(n_0 + \tfrac12)\log 2 = (2n_0 + 1) \cdot (\log 2)/2$ lies extremely close to the integer $M$. According to the trureturing problem file, this is exactly how the witness was found. How a certificate is found has no bearing on whether it holds: Lean checks only the inequalities above.

::: {.problem #prob-greathouse-minimal title="The least counterexample"}
Is $n_0 = 1121626023352383$ the least $n \ge 1$ at which the formula fails? What characterizes the $n$ at which it fails? trureturing proves only `¬ claim` and does not claim that $n_0$ is least. The problem file `Problems/oeis-a175406-log-two-floor-refutation.md` mentions a minimality argument from the search and marks it as unverified and not formalized.
:::

As a computation, not a proof: we checked every $1 \le n \le 20000$, and the formula holds for all of them. For $n \le 3000$, $a(n)$ was computed in exact integer arithmetic (since $(1 + 1/n)^k \le 2$ is equivalent to $(n+1)^k \le 2n^k$); all other values were computed with at least 60 significant digits, after checking that each floor was taken well away from an integer. For $n = 1, \dots, 10$, $a(n) = 1, 1, 2, 3, 3, 4, 5, 5, 6, 7$. Such computations say nothing about the range between $20000$ and $n_0$.

## What observations can recover

::: {.theorem #thm-target-recovery title="Target recovery criterion" lean="D5/S3/ConceptDynamics/Restoration/TargetRecoveryCriterion.target_recovery_criterion"}
Let the state space $X$ be nonempty, with a process readout $p: X \to P$ and a target $t: X \to T$. A recovery function $r$ with $t = r \circ p$ exists if and only if any two states with the same readout have the same target value; this in turn is equivalent to the target defect relation (the set of pairs of states $(x, y)$ with the same readout and different targets) being empty. Hence recovery fails exactly when this relation is nonempty.
:::

[@thm-target-recovery] asserts only that a recovery function exists; it gives no algorithm and no cost bound.

## Finite certificates {#sec-certificates}

The proof of [@thm-greathouse-refuted] is itself a certificate: one input plus a few inequalities that can be checked exactly. This section looks at three more kinds of certificate and then compares them. The first is simpler than [@thm-greathouse-refuted]: a small integer and two finite computations. OEIS A008365 lists the 13-rough numbers (positive integers with no prime factor below $13$), and the entry carries this comment:

> Conjecture: Numbers n such that n^24 is congruent to {1,421,631,841} mod 2310.
>
> — Gary Detlefs, OEIS A008365, December 30, 2011

::: {.theorem #thm-detlefs-refuted title="One integer refutes a characterization" lean="D5/S0/Certificates/DetlefsRoughResidueCharacterizationRefutation.result"}
Call a natural number $n$ 13-rough if each of its prime factors is at least $13$ (so $1$ is 13-rough). The statement "for every positive integer $n$: $n$ is 13-rough if and only if $n^{24} \bmod 2310 \in \{1, 421, 631, 841\}$" is false.
:::

::: proof
The certificate is $n = 17$. It is prime, and its only prime factor $17$ is at least $13$, so it is 13-rough. On the other hand $17^{24} \bmod 2310 = 1681$, which is not one of the four residues. Lean checks the primality of $17$ and the residue by kernel computation (`decide`); that a prime is 13-rough once it is at least $13$ follows because a prime has only trivial divisors.

The residue can also be found by hand. $2310 = 2 \cdot 3 \cdot 5 \cdot 7 \cdot 11$. For $p = 2, 3, 5, 7$, $p - 1$ divides $24$, so $17^{24} \equiv 1 \pmod{210}$; modulo $11$, $17 \equiv 6$ and $17^{24} \equiv 6^4 = 1296 \equiv 9$. The residues modulo $2310$ that are congruent to $1$ modulo $210$ are $1 + 210k$ with $0 \le k \le 10$, and $210 \equiv 1 \pmod{11}$, so $k = 8$ and the residue is $1681$. The full proof is checked by the Lean kernel.
:::

The hand computation also shows what the conjecture missed. The four residues all have the form $1 + 210k$, with $k = 0, 2, 3, 4$; modulo $11$ they are $1, 3, 4, 5$. The class that is $9$ modulo $11$ is missing.

::: {.remark #rem-a008365-corrected title="The corrected characterization"}
For every positive integer $n$: $n$ is 13-rough if and only if $n^{24} \bmod 2310 \in \{1, 421, 631, 841, 1681\}$. Both directions have elementary paper proofs, given below, and Lean has checked neither. So the characterization is not an open problem; it only lacks a Lean proof. What remains is to formalize both directions in Lean and freeze them.
:::

This characterization is recorded in the problem file `Problems/oeis-a008365-detlefs-rough-residue-characterization-refutation.md` as "disclosed but not claimed": trureturing does not prove it, and the Blueprint states that it asserts neither the corrected characterization nor its converse. The file gives the structural reason, which is one direction of the characterization. A 13-rough $n$ is coprime to $2310$, so $n^{24} \equiv 1 \pmod{210}$, while modulo $11$ we have $n^{24} \equiv n^4$, which takes only the five quartic residues $1, 3, 4, 5, 9$. The residues modulo $2310$ that are congruent to $1$ modulo $210$ are $1 + 210k$ with $0 \le k \le 10$; since $210 \equiv 1 \pmod{11}$, such a residue is $1 + k$ modulo $11$, which is one of the five values exactly when $k = 0, 2, 3, 4, 8$. These are the residues $1, 421, 631, 841, 1681$. The file does not discuss the other direction, but it is just as direct. If a positive integer $n$ is not 13-rough, it has a prime factor $p < 13$, that is, $p \in \{2, 3, 5, 7, 11\}$; then $p$ divides both $n^{24}$ and $2310$, so it also divides $n^{24} \bmod 2310$. Each of the five residues is congruent to $1$ modulo $210$, so none is divisible by $2$, $3$, $5$ or $7$, and none is $0$ modulo $11$; so $p$ divides none of them, and $n^{24} \bmod 2310$ is not among them. Computation agrees, though it is not a proof: for $1 \le n \le 200000$ the corrected characterization has no exception, while the original four-residue version has $8311$ exceptions, all of them 13-rough numbers outside the four residues; the first five are $17, 61, 71, 83, 127$.

The second kind of certificate shows that "find a counterexample" is a general pattern.

::: {.theorem #thm-finite-counterexample title="Refuting is finding a counterexample" lean="D5/S0/Computability/FiniteCounterexampleCertificate.finite_readout_counterexample_certificate"}
Let $\mathcal{H}$ be the set of all finite words (marker histories) over the two markers $E_0, E_1$, and let $D: \mathcal{H} \to \{\mathrm{true}, \mathrm{false}\}$ be any Boolean predicate. Let $\mathrm{find}(D, n)$ be the bounded search that enumerates all histories of length at most $n$, layer by layer in increasing length, and returns $\mathrm{some}\ h$ for the first history $h$ with $D(h) = \mathrm{false}$, or $\mathrm{none}$ if there is none. Then
$$
\neg\left(\forall h \in \mathcal{H},\ D(h) = \mathrm{true}\right) \iff \exists n \in \mathbb{N},\ \exists h \in \mathcal{H},\ \mathrm{find}(D, n) = \mathrm{some}\ h \ \wedge\ D(h) = \mathrm{false}.
$$
:::

::: proof
Left to right: take a rejected history $h$ and use its length as the bound $n$. The search is complete, so it returns a value $\mathrm{some}\ h'$ when a rejected history lies within the bound, and it is sound, so the returned $h'$ really satisfies $D(h') = \mathrm{false}$. Right to left: a rejected $h$ contradicts the universal claim directly. The full proof is checked by the Lean kernel.
:::

In Lean, $\mathrm{find}$ is `findCounterexample`, defined in the module `D5/S0/History/MarkerHistorySearch`, where trureturing checks one instance with `rfl`: if $D$ accepts the empty word and the words that start with $E_0$, then $\mathrm{find}(D, 1)$ returns the history consisting of the single marker $E_1$. [@thm-finite-counterexample] is not a decision procedure: it does not say how to obtain the bound $n$ from $D$, and when $D$ is true everywhere the search returns $\mathrm{none}$ for every $n$. So bounded search only semi-decides the failure of a universal claim. Nor does the theorem say that the returned counterexample is a shortest one.

The third kind of certificate is not a counterexample.

::: {.theorem #thm-farkas title="Farkas certificates" lean="D5/S0/Certificates/RationalFarkas.infeasible_of_certificate"}
Let $I$ (constraints) and $J$ (variables) be finite sets, and let $A = (A_{ij})_{i \in I, j \in J}$ and $b = (b_i)_{i \in I}$ have rational entries. If rational numbers $y_i$ ($i \in I$) satisfy
$$
y_i \ge 0 \ (i \in I), \qquad \sum_{i \in I} y_i A_{ij} = 0 \ (j \in J), \qquad \sum_{i \in I} y_i b_i < 0,
$$
then there are no rational numbers $x_j$ ($j \in J$) with $\sum_{j \in J} A_{ij} x_j \le b_i$ for every $i \in I$.
:::

::: proof
Suppose $x$ is a solution. Multiply the $i$-th inequality by $y_i \ge 0$ and add: the left side becomes $\sum_j \left(\sum_i y_i A_{ij}\right) x_j = 0$ and the right side $\sum_i y_i b_i$, so $0 \le \sum_i y_i b_i < 0$, a contradiction. The full proof is checked by the Lean kernel.
:::

In Lean, a $y$ with these three properties is the structure `Certificate`. External linear-programming software may propose $y$; Lean checks only the three finite conditions. The theorem gives only the direction "a certificate implies no solution"; the converse (every infeasible system has such a certificate, which is Farkas' lemma) is not stated here. It also speaks only of rational solutions. A minimal example:
$$
\begin{aligned}
x_1 + x_2 &\le 1,\\
-x_1 &\le -1,\\
-x_2 &\le -1.
\end{aligned}
$$
Take $y = (1, 1, 1)$. The coefficients of $x_1$ add up to $1 - 1 + 0 = 0$, those of $x_2$ to $1 + 0 - 1 = 0$, and the right-hand sides to $1 - 1 - 1 = -1 < 0$. So the system has no rational solution: adding the three inequalities gives $0 \le -1$.

::: {.remark #rem-certificates title="Certificates are more than counterexamples"}
The certificates of this chapter can be compared side by side.

| Result | Claim refuted | Certificate | Check |
| --- | --- | --- | --- |
| [@thm-greathouse-refuted] | the formula holds for every $n \ge 1$ | $n_0$, with rational bounds on $\log 2$ and $\log(1 + 1/n_0)$ | exact rational arithmetic on large integers |
| [@thm-detlefs-refuted] | the characterization holds for every $n > 0$ | $n = 17$ | one primality check, one remainder |
| [@thm-finite-counterexample] | $D(h)$ is true for every history $h$ | a bound $n$ and a rejected history $h$ | run the search, evaluate $D(h)$ |
| [@thm-farkas] | some $x$ satisfies $Ax \le b$ | nonnegative weights $y$ | three finite sets of equations and inequalities |

The first three rows are counterexamples: refuting a universal claim takes one input. The fourth row goes the other way: it refutes an existential claim. There are infinitely many candidate points $x$, yet the certificate points at none of them; a finite list of rational numbers rules them all out at once. Note one more thing: in Lean, the statements of [@thm-greathouse-refuted] and [@thm-detlefs-refuted] are just `¬ claim`, and the certificates appear only in the proofs. [@thm-modulus-blind] in the next section is different again: it asserts that witnesses exist, but its proof does not construct them.
:::

## What stays invisible {#sec-blind-spots}

By [@thm-target-recovery], a target cannot be recovered from a readout exactly when two states have the same reading and different targets. Each of the next two theorems is a source of such pairs: one by counting alone, the other from the golden phases of [Chapter 1](ch01-golden-deficit.md).

::: {.theorem #thm-pigeonhole-fiber title="Fewer readings than objects" lean="D5/S0/Diagonal/PigeonholeFiber.finite_reading_has_fiber"}
Let $O$ and $R$ be types and $\mathrm{read}: O \to R$. If the cardinality of $R$ is strictly smaller than that of $O$, that is $|R| < |O|$, then there are $x, y \in O$ with $x \ne y$ and $\mathrm{read}(x) = \mathrm{read}(y)$.
:::

This is the pigeonhole principle for cardinals[^universe]. It does not require $R$ to be finite, and it only asserts that a collision exists: it does not say which pair collides or how many pairs do. Together with [@thm-target-recovery] (take $p = \mathrm{read}$ and the identity map as the target), it shows that the identity target, which separates every object, then cannot be recovered from the reading. For example, there are $8$ three-bit strings but only $4$ possible counts of ones, and indeed $001$ and $010$ have the same count.

[^universe]: Lean requires $O$ and $R$ to live in the same type universe. This is a technical condition of the formalization and does not affect how the book uses the theorem.

::: {.theorem #thm-modulus-blind title="Residues cannot see the deficit" lean="D5/S1/Deficit/FixedModulusNoncongruence.deficit_not_determined_by_fixed_modulus"}
For every natural number $m \ge 2$ there are natural numbers $v_1, v_2, v_1', v_2'$ with
$$
v_1 \equiv v_1' \pmod m, \qquad v_2 \equiv v_2' \pmod m, \qquad c(v_1, v_2) \ne c(v_1', v_2'),
$$
where $c$ is the deficit of [@def-deficit].
:::

::: proof
The proof takes $v_1 = v_1' = 1$ and lets $v_2, v_2'$ be multiples of $m$, so the congruences hold automatically. Write $p(v) = \{(v+1)\varphi\}$ for the golden phase (the fractional part); then $p(1) = 2\varphi - 3 \approx 0.236$. By [@thm-beatty-deficit], $c$ equals its Beatty form (the module carries its own proof of this identity), and by [@thm-golden-phase], $c(1, v) = 1$ when $p(v) < (2 - \varphi)/2$, and $c(1, v) = 0$ when $2 - \varphi < p(v) < (3 - \varphi)/2$. Since $m\varphi$ is irrational, the phases $p(mn)$ for $n = 0, 1, 2, \dots$ are dense in $[0, 1)$, so each of the two intervals contains some $p(mn)$. The proof obtains these $n$ from density alone and does not exhibit them. The full proof is checked by the Lean kernel.
:::

Together with [@thm-target-recovery], take the state space $\mathbb{N} \times \mathbb{N}$, the readout $(v_1 \bmod m, v_2 \bmod m)$ and the target $c$: [@thm-modulus-blind] supplies two states with the same reading and different targets, so no function computes the deficit from the residues modulo $m$. It is the residues that cannot see the deficit, not every readout: [@thm-beatty-deficit] and [@thm-golden-phase] together say that the two golden phases determine it exactly. The theorem only asserts that a disagreement exists; it gives no witnesses and says nothing about how often disagreements occur.

::: {.example #ex-mod-two title="A pair of witnesses modulo 2"}
Take $m = 2$. The input pairs $(1, 2)$ and $(1, 4)$ agree coordinatewise modulo $2$: $1 \equiv 1$ and $2 \equiv 4$. From $\beta(1) = \varphi^2$, $\beta(2) = \varphi^3$, $\beta(3) = \varphi^4$, $\beta(4) = \varphi^4 + \varphi^2$, $\beta(5) = \varphi^5$ and $\varphi^{k+2} = \varphi^{k+1} + \varphi^k$,
$$
\begin{aligned}
c(1, 2) &= \varphi^2 + \varphi^3 - \varphi^4 = 0,\\
c(1, 4) &= \varphi^2 + (\varphi^4 + \varphi^2) - \varphi^5 = 2\varphi^2 - \varphi^3 = \varphi^2 - \varphi = 1.
\end{aligned}
$$
This agrees with [@thm-golden-phase] (with $p$ the golden phase from the proof above, and $1/\varphi \approx 0.618$): $p(1) + p(2) \approx 0.236 + 0.854 = 1.090$ lies in $[1/\varphi, \varphi)$, while $p(1) + p(4) \approx 0.236 + 0.090 = 0.326 < 1/\varphi$. Within a single residue class the deficit can even take all three values, as the class $(0, 0)$ in the table below shows. The table is an exact computation in $\mathbb{Z}[\varphi]$: an illustration, not a theorem.

| $(v_1, v_2)$ | residues mod 2 | $c(v_1, v_2)$ |
| --- | --- | --- |
| $(1, 2)$ | $(1, 0)$ | $0$ |
| $(1, 4)$ | $(1, 0)$ | $1$ |
| $(2, 2)$ | $(0, 0)$ | $-1$ |
| $(2, 4)$ | $(0, 0)$ | $0$ |
| $(4, 4)$ | $(0, 0)$ | $1$ |
:::

[Chapter 3](ch03-refinement-memory.md) continues from here: how a readout can be refined, what refinement costs, and what is lost when a readout becomes coarser over time.

## Slides

::: {.slides src="overview"}
Ten slides: the book at a glance, and the main results of chapters 1 and 2.
:::

An academic seminar version is also available, with speaker notes and a verification ledger.

::: {.slides src="overview-academic"}
Nine Beamer frames in English, with a paper visualization snapshot and a generated book figure.
:::
