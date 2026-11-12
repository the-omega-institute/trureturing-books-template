---
# 01 Cover (cover layout: no header or footer; shows the book code, the pinned commit and the page)
theme: ../../../../theme/slides
title: "Golden Integers and Observability · Overview"
info: "An overview of the sample monograph Golden Integers and Observability: what the template guarantees, the main theorems of Chapters 1 and 2, one open problem, and every output."
htmlAttrs:
  lang: "en"
deck:
  code: "GOLDEN//OBSERVE"
  book: "Golden Integers and Observability"
  title: "Overview"
  version: "0.1.0"
  blurb: "The template's guarantees, the main theorems of Chapters 1 and 2, one open problem and every output."
layout: cover
---

<p class="kicker">Sample monograph · Slides</p>
<h1 class="display">Golden Integers<br>and <em>Observability</em></h1>
<p class="lead">A sample monograph distinguishing Lean verification, written proofs and open questions. Matching frozen Lean results take priority; written proofs include a DOI and formalization request.</p>

---
# 02 What the template guarantees
section: "Guarantees"
---

<div class="body">
  <p class="kicker">What the template guarantees</p>
  <h2 class="t">Give priority to <em>frozen Lean declarations</em></h2>
  <p class="lead">Lean results are checked at the pinned commit. Only without matching verification may a written proof be used, with a DOI, associated argument and registered request.</p>
  <div class="flow mt-l">
    <div class="step"><span class="i">01 · Book</span><b>Name the GID</b><p>Lean results carry <code>lean="…"</code>, at least one.</p></div>
    <div class="step"><span class="i">02 · Lock</span><b>Pin a commit</b><p><code>trureturing.lock.json</code> records the commit and what it resolved.</p></div>
    <div class="step"><span class="i">03 · Frozen</span><b>Frozen only</b><p>Listed in <code>Golden/Frozen/state</code>, of kind theorem.</p></div>
    <div class="step ok"><span class="i">04 · Kernel</span><b><LeanBadge gid="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued" /></b><p>The badge links to the Lean source at the pinned commit.</p></div>
  </div>
  <div class="g3 mt-l">
    <Stat value="33" label="Lean-verified results in the whole book" tone="ok" />
    <Stat value="3" label="open problems and conjectures in the whole book, marked OPEN" tone="warn" />
    <Stat value="1" label="written proof, with a DOI and formalization request" />
  </div>
</div>
<Source>docs/ARCHITECTURE.md §1, §4; trureturing.lock.json</Source>

---
# 03 Chapter 1 (section layout: large chapter numeral)
layout: section
chapter: "01"
section: "Chapter 1"
---

<p class="kicker">Chapter 1</p>
<h2 class="t">The carry deficit of <em>golden integers</em></h2>
<p class="lead">Every natural number is, in a unique way, a sum of nonadjacent Fibonacci numbers. Replacing each weight <Tex t="F_i" /> by the golden power <Tex t="\varphi^i" /> gives a real number <Tex t="\beta(n)" />; <Tex t="\beta" /> does not preserve addition, and the difference is the deficit.</p>
<TheoremCard class="compact mt-l" kind="definition" label="Definition 1.1" title="Normalized deficit" gid="D5/S1/Deficit/DeficitInteger.deficit" cite="def-deficit">

$$c(v_1, v_2) = \beta(v_1) + \beta(v_2) - \beta(v_1 + v_2)$$

</TheoremCard>

---
# 04 Theorem 1.3: three values
section: "Chapter 1 · Deficit"
---

<div class="body">
  <p class="kicker">Theorem 1.3</p>
  <h2 class="t">However large the inputs, the deficit is <em>−1, 0 or 1</em></h2>
<TheoremCard class="mt" label="Theorem 1.3" title="The deficit takes three values" gid="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued" cite="thm-deficit-three-valued">

For all natural numbers $v_1, v_2$,

$$c(v_1, v_2) \in \{-1,\ 0,\ 1\}.$$

</TheoremCard>
  <p class="lead mt">For example <Tex t="\beta(1) = \varphi^2" /> and <Tex t="\beta(2) = \varphi^3" />, so <Tex t="c(1, 1) = 2\varphi^2 - \varphi^3 = 1" />. The bound holds for arbitrarily large inputs: it ties an arithmetic algorithm, digitwise carrying, to an exact result that later arguments can reuse as a premise.</p>
</div>
<Source>D5/S1/Deficit/DeficitThreeValued.lean · Chapter 1, Theorem 1.3</Source>

---
# 05 Theorem 1.2: integer and carries; the idea behind Theorem 1.3
section: "Chapter 1 · Deficit"
---

<div class="body">
  <p class="kicker">Theorem 1.2</p>
  <h2 class="t">The deficit is an integer: it <em>counts the carries</em></h2>
<TheoremCard class="compact mt-s" label="Theorem 1.2" title="The deficit is an integer, the signed carry count" gid="D5/S1/Deficit/DeficitInteger.deficit_integer" cite="thm-deficit-integer">

For all natural numbers $v_1, v_2$, the deficit $c(v_1, v_2)$ equals its reading on the contraction face (the Galois conjugate), is an integer, and equals the signed count of the two lowest repeated-carry rules applied while normalizing the digitwise sum of the two Zeckendorf representations.

</TheoremCard>
  <p class="kicker mt-s">Proof of theorem 1.3 · the idea</p>
  <div class="flow mt-s">
    <div class="step"><span class="i">01 · Contraction</span><b>Use the conjugate</b><p>At powers of <Tex t="\psi = (1-\sqrt5)/2" />, each <Tex t="\beta'(v)" /> lies in <Tex t="[-\psi^2, -\psi]" />, of length 1.</p></div>
    <div class="step"><span class="i">02 · Squeeze</span><b>Strictly below 2</b><p>So the contraction-face reading satisfies <Tex t="-2 \lt c(v_1, v_2) \lt 2" />.</p></div>
    <div class="step ok"><span class="i">03 · Integer</span><b>Three values left</b><p>By Theorem 1.2 it is an integer, so <Tex t="c \in \{-1, 0, 1\}" />; the Lean kernel checks the full proof.</p></div>
  </div>
</div>
<Source>D5/S1/Deficit/DeficitInteger.lean · Chapter 1, Theorem 1.2 and the proof of Theorem 1.3</Source>

---
section: "Chapter 1 · Written proof"
---

<div class="body">
  <p class="kicker">Written proof · Proposition 1.12</p>
  <h2 class="t">From phase areas to <em>limiting pair frequencies</em></h2>
<TheoremCard class="mt-s" label="Proposition 1.12" title="Limiting frequencies of the deficit" status="written-proof" cite="rem-areas-not-frequencies" doi="10.1007/BF01475864" source="pp.313-352 (equidistribution; derived result)" request="https://github.com/the-omega-institute/trureturing-requests/issues/1">

Let $a_n^+$ and $a_n^-$ be the proportions of $0\le v_1,v_2<n$ with deficit $+1$ and $-1$.

$$\lim_{n\to\infty}a_n^+=\frac{1}{2\varphi^2},\qquad \lim_{n\to\infty}a_n^-=\frac{1}{2\varphi^4}.$$

</TheoremCard>
  <p class="lead mt">Weyl equidistribution gives interval proportions; products of rectangle counts and grid approximations extend this to the two phase triangles. This argument has no matching frozen Lean verification and has a registered request.</p>
</div>
<Source>Written argument · pf-deficit-frequencies · trureturing-requests#1</Source>

---
# 06 Chapter 2
layout: section
chapter: "02"
section: "Chapter 2"
---

<p class="kicker">Chapter 2</p>
<h2 class="t">Refutation and <em>observability</em></h2>
<p class="lead">For a positive integer <Tex t="n" />, let <Tex t="a(n)" /> be the greatest natural number <Tex t="k" /> with <Tex t="(1 + 1/n)^k \le 2" />. For OEIS A175406, Greathouse conjectured a floor formula:</p>
<div class="card hot mt">
  <h4>Conjecture · Greathouse (OEIS A175406)</h4>
  <Tex display t="a(n) = \left\lfloor \left(n + \tfrac{1}{2}\right) \log 2 \right\rfloor \qquad (n \ge 1)" />
</div>

---
# 07 Theorem 2.1 and open problem 2.2
section: "Chapter 2 · Refutation"
---

<div class="body">
  <p class="kicker">Theorem 2.1 · Open problem 2.2</p>
  <h2 class="t">A counterexample refutes it; <em class="warn">minimality is open</em></h2>
  <div class="g2 mt-s">
    <div>
      <TheoremCard class="compact" label="Theorem 2.1" title="The floor formula is false" gid="D5/S0/Certificates/GreathouseLogTwoFloorRefutation.result" cite="thm-greathouse-refuted">
        <p>The conjectured formula does not hold for all <Tex t="n \ge 1" />.</p>
      </TheoremCard>
      <p class="kicker mt-s">From the proof · not the statement</p>
      <dl class="readout">
        <dt><Tex t="n_0" /></dt><dd class="cy">1121626023352383</dd>
        <dt>formula</dt><dd>777451915729368</dd>
        <dt><Tex t="a(n_0)" /></dt><dd class="hot">777451915729367<small>one less</small></dd>
      </dl>
    </div>
    <TheoremCard class="compact" label="Open problem 2.2" title="The least counterexample" status="open" cite="prob-greathouse-minimal">
      <p>Is <Tex t="n_0" /> = <span class="mono">1121626023352383</span> the least <Tex t="n" /> at which the formula fails? What characterizes the inputs where it fails?</p>
      <p>trureturing proves only that the formula does not always hold; it does not claim that <Tex t="n_0" /> is the least.</p>
    </TheoremCard>
  </div>
</div>
<Source>D5/S0/Certificates/GreathouseLogTwoFloorRefutation.lean (result : ¬ claim) · Chapter 2</Source>

---
# 08 Theorem 2.3: target recovery
section: "Chapter 2 · Observability"
---

<div class="body">
  <p class="kicker">Theorem 2.3</p>
  <h2 class="t">What observation recovers: <em>same readout, same target</em></h2>
<TheoremCard class="mt-s" label="Theorem 2.3" title="Target recovery criterion" gid="D5/S3/ConceptDynamics/Restoration/TargetRecoveryCriterion.target_recovery_criterion" cite="thm-target-recovery">

Let the state space $X$ be nonempty, with a process readout $p: X \to P$ and a target $t: X \to T$. A recovery function $r$ with $t = r \circ p$ exists if and only if any two states with the same readout have the same target value; this in turn is equivalent to the target defect relation being empty.

$$\exists\, r,\ t = r \circ p \iff \bigl(p(x) = p(y) \Rightarrow t(x) = t(y)\bigr) \iff \operatorname{defect}(p, t) = \varnothing$$

</TheoremCard>
  <p class="lead mt">Scope: the theorem asserts only that a recovery function <b>exists</b>; it gives no algorithm and no cost bound.</p>
</div>
<Source>D5/S3/ConceptDynamics/Restoration/TargetRecoveryCriterion.lean · Chapter 2, Theorem 2.3</Source>

---
# 09 Outputs
section: "Outputs"
---

<div class="body">
  <p class="kicker">One source, every format</p>
  <h2 class="t">One Markdown source, <em>six outputs</em></h2>
  <p class="lead">Numbers, evidence badges and source links agree everywhere; Chinese is authoritative and English is aligned item by item.</p>
  <div class="g3 mt">
    <div class="tile"><i>MDBOOK</i><b>HTML</b><span>Read online: KaTeX math, a language switch, theorems linked to their Lean source.</span></div>
    <div class="tile"><i>TYPST</i><b>PDF</b><span>A dark screen edition and a white print edition, with the same numbers and badges.</span></div>
    <div class="tile"><i>EPUB 3</i><b>Apple Books</b><span>MathML math, for reading on iPhone, iPad and Mac.</span></div>
    <div class="tile"><i>TRURETURING-VISUALIZE</i><b>Visualizations</b><span>Interactive pages inside chapters; thumbnails and links in PDF and EPUB.</span></div>
    <div class="tile"><i>TRURETURING-FILM</i><b>Films</b><span>Script, scenes and subtitles live in the repository; films are built with the site.</span></div>
    <div class="tile now"><i>SLIDEV · NOW</i><b>Slides</b><span>This deck: present it online or download the PDF.</span></div>
  </div>
</div>
<Source>./tbook build all → build/ and _site/ (GitHub Pages)</Source>

---
# 10 Closing (cover layout)
layout: cover
---

<p class="kicker">Read · Verify · Extend</p>
<h1 class="display">The book explains,<br><em>Lean</em> decides</h1>
<p class="lead">Read online, download the PDF and EPUB, or check every theorem yourself at the pinned trureturing commit.</p>
<p class="lead mt mono hl-cyan">./tbook check · ./tbook build all</p>
