# Appendix A Zeckendorf representations and carries

This appendix supplies the background used in [Chapter 1](ch01-golden-deficit.md). [The first section](#sec-zeckendorf) writes Zeckendorf representations as digit strings and states that they exist, are unique and preserve order; [the second](#sec-carries) gives the four carry rules that bring the digitwise sum of two representations back to canonical form. The deficit $c(v_1, v_2)$ of Chapter 1 ([@def-deficit]) is exactly the signed count of the two lowest of these rules ([@thm-deficit-integer]).

Fibonacci numbers follow the Lean convention (mathlib's `Nat.fib`): $F_0 = 0$, $F_1 = 1$, $F_{n+2} = F_{n+1} + F_n$.

## Digit strings and Zeckendorf's theorem {#sec-zeckendorf}

Chapter 1 writes a Zeckendorf representation as $F_{k_1} + \dots + F_{k_r}$ with indices $k_j \ge 2$. This appendix counts positions from $0$ instead: position $i$ stands for the index $k = i + 2$ and has weight

$$
W_i = F_{i+2}, \qquad (W_0, W_1, W_2, W_3, W_4, \dots) = (1, 2, 3, 5, 8, \dots).
$$

In this form a carry is a local rewrite of a digit string, and a digit may temporarily exceed $1$.

::: {.definition #def-canonical-raw title="Canonical digit strings and their value" lean="D5/S1/Digit/Raw.CanonicalRaw D5/S1/Digit/Raw.rawValue"}
A digit string is a function $r : \mathbb{N} \to \mathbb{N}$ that is nonzero at only finitely many positions; $r(i)$ is the digit at position $i$ and may exceed $1$. Its value is

$$
\mathrm{val}(r) = \sum_{i} r(i)\, W_i .
$$

The string $r$ is canonical if every digit is at most $1$ and no two adjacent digits are both $1$: for all $i$, $r(i) \le 1$, and $r(i) = 1$ implies $r(i+1) = 0$.
:::

In Lean a digit string has type `RawDigits` (that is, `ℕ →₀ ℕ`), and the value and canonicity are [`rawValue`](lean:D5/S1/Digit/Raw.rawValue) and [`CanonicalRaw`](lean:D5/S1/Digit/Raw.CanonicalRaw). We write digit strings from the highest position down, with a subscript $W$: $10101_W$ has a $1$ at positions $4$, $2$ and $0$ and value $8 + 3 + 1 = 12$, while $202_W$ has a $2$ at positions $2$ and $0$, value $2 \cdot 3 + 2 \cdot 1 = 8$, and is not canonical. Digit strings are added position by position. Write $e_i$ for the string with a single $1$ at position $i$; for example $202_W = 2e_2 + 2e_0$.

For a natural number $n$, let $\mathrm{zeck}(n)$ be its Zeckendorf index list (`Z n` in Lean, whose list is mathlib's `Nat.zeckendorf n`). By construction it lists Fibonacci indices in decreasing order, each at least $2$, any two consecutive ones differing by at least $2$. Lowering every index by $2$ gives the digit string $z(n)$ (`toRaw (Z n)` in Lean). For example $\mathrm{zeck}(12) = [6, 4, 2]$ and $z(12) = 10101_W$.

::: {.theorem #thm-zeckendorf-exists title="Zeckendorf representations exist" lean="D5/S1/Digit/Addition.rawValue_toRaw_Z"}
For every natural number $n$,

$$
\mathrm{val}(z(n)) = n,
$$

where $z(n)$ is the digit string obtained by lowering every index of the Zeckendorf index list $\mathrm{zeck}(n)$ by $2$.
:::

::: proof
Lowering the indices by $2$ and evaluating with $W_i = F_{i+2}$ is the same as summing $F_k$ over the indices $k$ of the list, and that sum is $n$ by mathlib's `Nat.sum_zeckendorf_fib`. The full proof is checked by the Lean kernel.
:::

By construction $\mathrm{zeck}(n)$ satisfies the Zeckendorf conditions, and [@thm-zeckendorf-exists] says that it really sums to $n$; so every natural number has a Zeckendorf representation. The string $z(n)$ is also canonical; that is `canonicalRaw_toRaw` in the same trureturing module, which this book does not cite separately. The theorem is about the value only: it says nothing about how $\mathrm{zeck}(n)$ is found.

::: {.theorem #thm-zeckendorf-unique title="Zeckendorf representations are unique" lean="D5/S1/Digit/Normalize.canonicalRaw_unique"}
Let $r$ and $s$ be canonical digit strings. If $\mathrm{val}(r) = \mathrm{val}(s)$, then $r = s$.
:::

::: proof
The Lean proof hands the question to mathlib. Raising every position of a canonical string $r$ by $2$ and listing the results in decreasing order gives a Zeckendorf index list, which by mathlib's uniqueness theorem `Nat.zeckendorf_sum_fib` is $\mathrm{zeck}(\mathrm{val}(r))$. Since $r$ and $s$ have the same value, they give the same list, and lowering its indices by $2$ recovers the string; hence $r = s$. The full proof is checked by the Lean kernel.
:::

Canonicity cannot be dropped: $2e_1 = 20_W$ and $e_2 + e_0 = 101_W$ both have value $4$, and only the second is canonical. Together, every natural number $n$ has exactly one canonical digit string, namely $z(n)$; this is Zeckendorf's theorem[^zeck]. The table lists the representations of $1$ to $20$, with the last column right-aligned.

| $n$ | Zeckendorf representation | $\mathrm{zeck}(n)$ | $z(n)$ |
| ---: | :--- | :--- | ---: |
| 1 | $1$ | $[2]$ | 1 |
| 2 | $2$ | $[3]$ | 10 |
| 3 | $3$ | $[4]$ | 100 |
| 4 | $3 + 1$ | $[4, 2]$ | 101 |
| 5 | $5$ | $[5]$ | 1000 |
| 6 | $5 + 1$ | $[5, 2]$ | 1001 |
| 7 | $5 + 2$ | $[5, 3]$ | 1010 |
| 8 | $8$ | $[6]$ | 10000 |
| 9 | $8 + 1$ | $[6, 2]$ | 10001 |
| 10 | $8 + 2$ | $[6, 3]$ | 10010 |
| 11 | $8 + 3$ | $[6, 4]$ | 10100 |
| 12 | $8 + 3 + 1$ | $[6, 4, 2]$ | 10101 |
| 13 | $13$ | $[7]$ | 100000 |
| 14 | $13 + 1$ | $[7, 2]$ | 100001 |
| 15 | $13 + 2$ | $[7, 3]$ | 100010 |
| 16 | $13 + 3$ | $[7, 4]$ | 100100 |
| 17 | $13 + 3 + 1$ | $[7, 4, 2]$ | 100101 |
| 18 | $13 + 5$ | $[7, 5]$ | 101000 |
| 19 | $13 + 5 + 1$ | $[7, 5, 2]$ | 101001 |
| 20 | $13 + 5 + 2$ | $[7, 5, 3]$ | 101010 |

Every row was computed by a program and checked for canonicity and for $\mathrm{val}(z(n)) = n$. The program also listed all canonical strings whose positions are all below $14$: there are $987$ of them (counting the all-zero string), and their values are exactly $0$ to $986$, each once. These are finite computations, not proofs; the general case is [@thm-zeckendorf-exists] together with [@thm-zeckendorf-unique].

Right-aligned, the column $z(n)$ increases down the table like a counter: to compare two strings, find the first difference from the highest position. The next proposition says exactly this, in terms of index lists.

::: {.proposition #prop-zeckendorf-order title="Lexicographic order is numeric order" lean="D5/S1/Words/ZeckendorfOrder.zeckendorf_lex_iff_lt"}
For all natural numbers $m$ and $n$,

$$
\mathrm{zeck}(m) <_{\mathrm{lex}} \mathrm{zeck}(n) \iff m < n .
$$

Here $<_{\mathrm{lex}}$ is the strict lexicographic order on lists: compare entries from the first one on; at the first position where they differ, the list with the smaller entry is smaller, and a proper prefix of a list is smaller than the list.
:::

For example $\mathrm{zeck}(5) = [5]$ is a proper prefix of $\mathrm{zeck}(6) = [5, 2]$, then $[5, 2] <_{\mathrm{lex}} [5, 3] = \mathrm{zeck}(7)$ and $[5, 3] <_{\mathrm{lex}} [6] = \mathrm{zeck}(8)$, matching $5 < 6 < 7 < 8$. Because the lists start with the largest index, lexicographic order amounts to comparing digit strings from the highest position, just as one compares decimal numbers; this rephrasing is ours, and the Lean statement is about index lists. The proposition concerns Zeckendorf lists only: $[4, 3]$ and $[5]$ both stand for $F_4 + F_3 = F_5 = 5$, yet the first is lexicographically smaller.

[^zeck]: Named after Édouard Zeckendorf, who published it in 1972; C. G. Lekkerkerker had already published it in 1952.

## Carries {#sec-carries}

Adding two canonical strings position by position can produce a digit $2$ or two adjacent $1$s. The carry rules rewrite these away locally. Lean has four rules (the four constructors of `CarryStep`); each changes two or three positions and leaves the rest $q$ untouched. Since $q$ can be any digit string, a rule only needs enough units at the positions it rewrites: if position $i$ holds a $2$ and position $i+1$ a $1$, for instance, the adjacent carry uses only one of the two units at position $i$.

Adjacent carry `adjacent`
: $q + e_i + e_{i+1} \to q + e_{i+2}$, for every $i$.

Lowest repeated carry `double_zero`
: $q + 2e_0 \to q + e_1$.

Second repeated carry `double_one`
: $q + 2e_1 \to q + e_0 + e_2$.

General repeated carry `double_succ`
: $q + 2e_{i+2} \to q + e_i + e_{i+3}$, for every $i$.

::: {.figure src="carry-rules"}
**The four carry rules.** In each row the digits before the rewrite are on the left, the digits after it on the right; the cyan row has charge $+1$, the magenta row charge $-1$.
:::

In the figure, each row is headed by the rule's name and the identity behind it, and each box by its position. Digits run from the highest position down, and positions not drawn are unchanged. The middle two rows are the two lowest repeated carries; the $+1$ and $-1$ on the right are the signs they get in the signed count of Chapter 1, called their charges below (see [@thm-charge-unique]). The other two rules have charge $0$.

::: {.lemma #lem-carry-value title="A carry keeps the value" lean="D5/S1/Digit/Carry.rawValue_carryStep"}
If a digit string $r$ becomes $s$ by one carry step, then $\mathrm{val}(r) = \mathrm{val}(s)$.
:::

::: proof
Evaluation is additive under digitwise addition, and the untouched part $q$ is the same on both sides, so only the rewritten part matters. The four rules correspond to the identities $W_i + W_{i+1} = W_{i+2}$, $2W_0 = W_1$ (that is, $2 = 2$), $2W_1 = W_0 + W_2$ (that is, $4 = 1 + 3$) and $2W_{i+2} = W_i + W_{i+3}$. The first is the recurrence itself, and the last uses it twice: $2W_{i+2} = W_{i+2} + W_{i+1} + W_i = W_{i+3} + W_i$. The full proof is checked by the Lean kernel.
:::

The two lowest rules are listed separately because the general rule has no lower positions to borrow from there. In Fibonacci numbers the general rule reads $2F_k = F_{k-2} + F_{k+1}$. For $k = 2$ the term $F_0 = 0$ on the right disappears, which gives $2W_0 = W_1$; for $k = 3$ the right side is $F_1 + F_4$, and $F_1 = 1 = F_2$ can only be written at position $0$, which gives $2W_1 = W_0 + W_2$. These two adjustments are where the deficit of Chapter 1 comes from; see the discussion after [@lem-face-invariant].

::: {.theorem #thm-carry-confluent title="Carries are confluent" lean="D5/S1/Digit/CarryStepConfluence.carryStep_confluent"}
Write $r \to^* s$ when the digit string $r$ becomes $s$ after finitely many (possibly zero) carry steps. For all digit strings $r$, $s$, $t$: if $r \to^* s$ and $r \to^* t$, then there is a digit string $u$ with $s \to^* u$ and $t \to^* u$.
:::

::: proof
The Lean proof does not go through the cases where two rules overlap; it uses the normalization procedure $\mathrm{normalize}$ described below. That procedure has three properties: every carry step lowers the sum of all digits, or keeps that sum and lowers a weighted sum of positions, so normalization stops; when it stops the string is canonical; and by [@lem-carry-value] it keeps the value. Hence along any carry path the normalizations of the two ends are canonical with the same value, and they are equal by [@thm-zeckendorf-unique]. Take $u = \mathrm{normalize}(r)$: normalizing $s$, and normalizing $t$, both reach $u$. The full proof is checked by the Lean kernel.
:::

Confluence is about end points, not about the number of steps, and it does not include termination. That carrying cannot go on forever follows from another trureturing theorem, `carryStep_measure_decreases`, which this book does not cite separately.

The normalization procedure $\mathrm{normalize}$ (`normalize` in Lean) applies one carry per step:

1. if some position holds a digit of at least $2$, take the lowest such position and apply the matching repeated carry (there is one rule for position $0$, one for position $1$ and one for higher positions);
2. otherwise, if there are two adjacent $1$s, take the lowest such pair and apply the adjacent carry;
3. otherwise the string is canonical, and the procedure stops.

::: {.theorem #thm-zeck-add title="Golden addition" lean="D5/S1/Digit/Addition.zeck_add"}
For all natural numbers $m$ and $n$,

$$
z(m + n) = \mathrm{normalize}\bigl(z(m) + z(n)\bigr),
$$

where digit strings are added position by position.
:::

In words: add two canonical strings position by position, carry step by step as above, and the result is the canonical string of the sum. Take $4 + 7$: $z(4) = 101_W$ and $z(7) = 1010_W$, whose digitwise sum is $1111_W$. Normalization applies four carries in turn:

| Step | Carry applied | Digit string | Value |
| ---: | :--- | ---: | :--- |
| 0 | (digitwise sum) | 1111 | $5 + 3 + 2 + 1 = 11$ |
| 1 | adjacent, positions $0, 1 \to 2$ | 1200 | $5 + 2 \cdot 3 = 11$ |
| 2 | general repeated, position $2 \to 0, 3$ | 2001 | $2 \cdot 5 + 1 = 11$ |
| 3 | general repeated, position $3 \to 1, 4$ | 10011 | $8 + 2 + 1 = 11$ |
| 4 | adjacent, positions $0, 1 \to 2$ | 10100 | $8 + 3 = 11$ |

After step 1 position $2$ holds a $2$. Normalization deals with repeated digits first, so step 2 is a general repeated carry, although an adjacent carry at positions $2, 3$ would also apply. The result $10100_W = z(11)$ agrees with [@thm-zeck-add]. All four steps are internal carries and neither of the two lowest rules occurs, so $c(4, 7) = 0$, as in the table of [@ex-small-deficits] in Chapter 1.

The number of steps is not fixed. Starting again from $1111_W$, an adjacent carry at positions $0, 1$ gives $1200_W$, and an adjacent carry at positions $2, 3$ (using only one of the two units at position $2$) reaches $10100_W$ in two steps. An exhaustive search by program finds $4$ carry paths from $1111_W$, of lengths $2, 2, 3, 4$, all ending at $10100_W$. [@thm-zeck-add] is about the result of normalization and gives no bound on the number of carries.

Chapter 1's $\beta$ puts the digit at position $i$ on $\varphi^{i+2}$ (Chapter 1 writes $F_k \mapsto \varphi^k$ with $k = i + 2$), and the contraction-face reading $\beta'$ puts it on $\psi^{i+2}$. For any digit string $r$ and $x \in \{\varphi, \psi\}$, write

$$
\langle r \rangle_x = \sum_i r(i)\, x^{i+2},
$$

so that $\beta(v) = \langle z(v) \rangle_\varphi$ and $\beta'(v) = \langle z(v) \rangle_\psi$. How do these readings change when a carry rewrites the string?

::: {.lemma #lem-face-invariant title="Internal carries cost nothing on the $\varphi$ and $\psi$ faces" lean="D5/S1/Deficit/GoldenCarryLedger.carry_rewrite_face_invariant"}
Let $\varphi = (1+\sqrt5)/2$ and $\psi = (1-\sqrt5)/2$. For every natural number $k$, both $x = \varphi$ and $x = \psi$ satisfy

$$
x^{k+1} + x^{k+2} = x^{k+3}, \qquad 2x^{k+2} = x^{k+3} + x^{k} .
$$
:::

::: proof
Both identities use only $x^2 = x + 1$, and $\varphi$ and $\psi$ are the two roots of this equation. The first identity is $x^2 = x + 1$ multiplied by $x^{k+1}$. For the second, $x^3 = x \cdot x^2 = x^2 + x = 2x + 1$ gives $x^3 + 1 = 2x + 2 = 2x^2$; multiply by $x^k$. The full proof is checked by the Lean kernel.
:::

Substituting the four carry rules into $\langle \cdot \rangle_x$:

- The adjacent carry $e_i + e_{i+1} \to e_{i+2}$ replaces $x^{i+2} + x^{i+3}$ by $x^{i+4}$. By the first identity ($k = i + 1$) the reading is unchanged.
- The general repeated carry $2e_{i+2} \to e_i + e_{i+3}$ replaces $2x^{i+4}$ by $x^{i+2} + x^{i+5}$. By the second identity ($k = i + 2$) the reading is unchanged.
- The lowest repeated carry $2e_0 \to e_1$ replaces $2x^2$ by $x^3$. For $k = 0$ the second identity reads $2x^2 = x^3 + 1$, so the reading drops by exactly $1$.
- The second repeated carry $2e_1 \to e_0 + e_2$ replaces $2x^3$ by $x^2 + x^4$. For $k = 1$ the second identity reads $2x^3 = x^4 + x$, so the reading drops by $x - x^2 = -1$; that is, it rises by $1$.

So internal carries leave both readings unchanged; only the two lowest rules change them, and by the same integer on both faces. This correspondence is our explanation; [@lem-face-invariant] itself states only the power identities. The identities for $k = 0$ and $k = 1$ involve $x^0$ and $x^1$, which belong to no position of a digit string: these are the adjustments mentioned above.

By [@thm-zeck-add] and the additivity of $\langle \cdot \rangle_\varphi$ under digitwise addition,

$$
c(v_1, v_2) = \bigl\langle z(v_1) + z(v_2) \bigr\rangle_\varphi - \bigl\langle \mathrm{normalize}\bigl(z(v_1) + z(v_2)\bigr) \bigr\rangle_\varphi ,
$$

the total drop of the $\varphi$-face reading during normalization: the number of lowest repeated carries minus the number of second repeated carries. This is the third part of [@thm-deficit-integer]. The total drop on the $\psi$ face is the same, which corresponds to its first part.

Chapter 1 counts the two lowest repeated carries as $+1$ and $-1$. In general, give every carry step a charge: $+1$ for the lowest repeated carry, $-1$ for the second repeated carry and $0$ for the other two rules. The charge of a finite carry path is the sum of the charges of its steps; a path of zero steps has charge $0$. Write $r \Rightarrow_z s$ when there is a carry path from $r$ to $s$ with charge $z$.

::: {.theorem #thm-charge-unique title="The carry charge does not depend on the path" lean="D5/S1/Deficit/ChargedCarryPath.charged_normal_form_unique"}
For all digit strings $r$, $s$, $t$ and integers $z$, $w$: if $r \Rightarrow_z s$ and $r \Rightarrow_w t$, and both $s$ and $t$ are canonical, then $s = t$ and $z = w$.
:::

::: proof
End points: forgetting the charges, both paths are ordinary carry paths with canonical ends, so by the argument in the proof of [@thm-carry-confluent] both ends equal $\mathrm{normalize}(r)$. Charges: Lean keeps the books in $\mathbb{Z}[\varphi]$, where each charged carry step lowers $\langle \cdot \rangle_\varphi$ by exactly its charge (the computation after [@lem-face-invariant]). The charge of a path is therefore the difference between the readings of its two ends and depends only on them. The ends agree, so the charges agree. The full proof is checked by the Lean kernel.
:::

Take $6 + 6$: $z(6) = 1001_W$, and the digitwise sum is $2002_W$. An exhaustive search by program finds three carry paths from it, all ending at $10101_W = z(12)$:

| Path | Strings visited | Step charges | Total charge |
| :--- | :--- | :--- | ---: |
| 1 (normalization) | 2002 → 2010 → 10020 → 10101 | $+1, 0, -1$ | $0$ |
| 2 | 2002 → 10012 → 10101 | $0, 0$ | $0$ |
| 3 | 2002 → 10012 → 10020 → 10101 | $0, +1, -1$ | $0$ |

The second path uses neither of the two lowest rules: its last step is an adjacent carry at positions $0, 1$, which uses only one of the two units at position $0$. The other two paths each use one $+1$ and one $-1$. All three have total charge $0 = c(6, 6)$.

Combining [@thm-charge-unique] with the third part of [@thm-deficit-integer]: every carry path from $z(v_1) + z(v_2)$ to a canonical string ends at $z(v_1 + v_2)$ and has total charge $c(v_1, v_2)$. This step also uses `charged_normalize_exists` in trureturing (normalization itself is a charged path whose charge is its signed count), a declaration this book does not cite separately. The deficit is thus an invariant of golden addition itself, independent of the order of the carries. For all $900$ pairs with $v_1, v_2 < 30$, a program enumerated all $4431$ carry paths, and every end point and total charge agrees with this; that is a finite computation, not a proof.

[@thm-charge-unique] holds for arbitrary digit strings, but it does not bound the charge. [@thm-deficit-three-valued] puts the total charge in $\{-1, 0, 1\}$, but only for sums of two canonical strings. For instance, from $5e_0$ (a $5$ at position $0$, value $5$) normalization takes $5$ steps to $1000_W = z(5)$ with total charge $2$; directly, $5\varphi^2 - \varphi^5 = 2$.
