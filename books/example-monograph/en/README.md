# Preface

This book starts from a concrete arithmetic phenomenon. Every natural number is, in exactly one way, a sum of nonadjacent Fibonacci numbers: its Zeckendorf representation. Replace the Fibonacci weights by powers of the golden ratio $\varphi = (1+\sqrt5)/2$ and addition is no longer exact; what is left over is called the deficit. [Chapter 1](ch01-golden-deficit.md) proves that the deficit is an integer and that, however large the inputs, it takes only the three values $-1$, $0$ and $1$ ([@thm-deficit-three-valued]).

The example leads to two more general questions: how to refute a claim conclusively, and what a readout can and cannot tell us. The book's answer to the first is a finite certificate that can be checked mechanically; its answer to the second is an order on readouts that ties together recovery, memory and entropy.

The book gives priority to matching declarations in [trureturing](https://github.com/the-omega-institute/trureturing) that are kernel-verified in Lean and frozen[^frozen]; its statements claim no more than those declarations. Only when no matching frozen Lean verification exists may a result be marked WRITTEN PROOF. It must have an associated proof, a DOI and source location, and a formalization request registered in [trureturing-requests](https://github.com/the-omega-institute/trureturing-requests). The example here is [@rem-areas-not-frequencies]. Genuinely unresolved results are conjectures or open problems. The Lean code lives in trureturing; this book cites it by GID (module path plus declaration name).

The book is also the sample monograph of the trureturing books template: theorem environments and cross-references, footnotes, tables, figures, definition lists, and interactive visualizations, films and slides all appear in it.

[^frozen]: Freezing is a step in trureturing's workflow: only after a module has been verified by the Lean kernel (no `sorry`, no axioms of the repository's own) does the workflow write a state file for it under `Golden/Frozen/state/`, recording a digest of the module's statements and the name and kind of each declaration in it. The book's theorems, lemmas, propositions and corollaries marked `LEAN ✓` cite only declarations that a state file at the pinned commit lists with kind theorem.

## What each chapter does {#sec-preface-map}

[Chapter 1 The carry deficit of golden integers](ch01-golden-deficit.md)
: Defines the deficit $c(v_1, v_2)$ and proves that it is an integer equal to a signed count of carries ([@thm-deficit-integer]) and takes only three values ([@thm-deficit-three-valued]). It then explains why by reading the same digits on two faces, the expansion face and the contraction face; decides from the sum of two golden phases which value the deficit takes ([@thm-beatty-deficit], [@thm-golden-phase]); and computes the areas of the two regions of the phase square where the deficit is $+1$ and $-1$ ([@prop-phase-areas]).

[Chapter 2 Refutation and observability](ch02-refutation-observation.md)
: Two kinds of negative result. One is refutation: the floor formula Greathouse conjectured for OEIS A175406 is false ([@thm-greathouse-refuted]), and whether the counterexample used in the proof is the least one remains open ([@prob-greathouse-minimal]); finite counterexamples and Farkas weights are both certificates that can be checked mechanically. The other is unobservability: on a nonempty state space, a target can be recovered from a readout exactly when states with the same reading have the same target ([@thm-target-recovery]), and for every modulus $m \ge 2$, residues modulo $m$ do not determine the deficit ([@thm-modulus-blind]).

[Chapter 3 Refinement, memory and information](ch03-refinement-memory.md)
: Treats "can it be recovered?" as an order on readouts and studies it from three directions: refining never adds risk and never lowers cost ([@thm-refinement-tradeoff]); in the definition of forgetting, "no longer known later" can be replaced by a witness, two worlds with different values of the event that the later readout cannot tell apart ([@thm-forgot-iff]); and on a finite state space a deterministic map keeps the entropy exactly when it merges no two states of positive probability ([@thm-entropy-injective]).

[Chapter 4 The golden word and returns](ch04-golden-word.md)
: Listing the lowest Zeckendorf digit of each natural number in turn gives the golden word, which has exactly $n+1$ factors of each length $n$ ([@thm-factor-complexity]). The chapter then studies the returns of the golden rotation at Fibonacci times ([@thm-revival-score]) and one use of the deficit on prime factorizations ([@thm-almost-additive]). It also records an open problem ([@prob-revival-spectrum]) and a conjecture ([@conj-independence]).

[Appendix A Zeckendorf representations and carries](appendix-a-zeckendorf.md)
: The background for Chapter 1: Zeckendorf representations exist, are unique and preserve order, and carry rules bring the digitwise sum of two representations back to canonical form. Two carry paths from the same digit string can always be joined ([@thm-carry-confluent]), and on the way to canonical form both the endpoint and the signed carry charge are independent of the path ([@thm-charge-unique]).

Chapter 1 is where everything starts. Appendix A can be read first or consulted when needed. The refutation half of Chapter 2 does not depend on Chapter 1, while its second half uses the golden phases of Chapter 1; Chapter 3 continues from [@thm-target-recovery] in Chapter 2; Chapter 4 uses the deficit of Chapter 1 and the Zeckendorf representations of Appendix A.

Within a chapter all numbered items share one counter, so labels look like "Theorem 1.3": the chapter number, then the item's position among the chapter's numbered items; items in the appendix are numbered A.1, A.2, and so on. Proof blocks for Lean results explain the idea; written-proof blocks give the cited argument and are checked by authors and reviewers. Every table of numbers in the book was computed by a program, and the text says that it is a computation, not a proof.

## Badges and colors {#sec-preface-badges}

Colors have a fixed meaning in this book.

| Mark | Color | Meaning |
| --- | --- | --- |
| `LEAN ✓` | green | Theorems, lemmas, propositions and corollaries: every declaration cited is kernel-verified in Lean and frozen at the pinned commit. The badge links to the source of the first declaration |
| `WRITTEN PROOF` | purple | No matching frozen Lean verification; an associated proof, DOI, source location and formalization request are supplied, with author and reviewer responsibility |
| `OPEN` | red | Conjectures and open problems: there is no Lean proof, the book never treats them as proved, and it says in which trureturing file the question is recorded |
| current position | amber | Only "where you are now": the chapter being read in the sidebar, the current language in the language switch, the keyboard focus |

Green is reserved for results verified in Lean, amber marks only the current position, red marks open problems, and purple marks written proofs. The badges are generated by the build from the lock file, not written by hand: if the lock file cannot confirm that a cited declaration is a frozen Lean theorem, the build shows a red `UNVERIFIED` badge, `./tbook check` reports an error, and the book cannot be published.

An item that cites Lean ends with the names of the declarations it cites, linked to the source files at the pinned commit. Definitions cite Lean `def`s too, but carry no badge, since a definition has no claim to verify. The text can also link a declaration directly: [@thm-deficit-three-valued], for instance, is [`deficit_three_valued`](lean:D5/S1/Deficit/DeficitThreeValued.deficit_three_valued).

## Visualization, film and slides {#sec-preface-media}

The end of [Chapter 1](ch01-golden-deficit.md) has an interactive visualization: pick $v_1$ and $v_2$, step through the carries after their Zeckendorf representations are added, and see how $c(v_1, v_2)$ is distributed on the deficit map. The same section has a film of about fifty seconds that animates the carries and the three values of the deficit, with English narration and bilingual Chinese and English subtitles.

The end of [Chapter 2](ch02-refutation-observation.md) links a slide deck that surveys the main results of Chapters 1 and 2 and one open problem; you can present it online or download it as a PDF.

The visualization and the film are built from this book's repository and published with the website. The numbers on screen are computations on the page, meant to help understanding, not proofs; green results rely on Lean verification, and purple results on the cited written proof. The PDF and EPUB editions cannot play or interact: they show a thumbnail or poster for the visualization and the film, and give the online address of all three.

## A companion primer {#sec-preface-primer}

This library also holds a short introduction, *Fibonacci and Lucas: A Verified Primer*, which goes from the Fibonacci recurrence to the golden ratio and the Lucas numbers, again with every theorem kernel-verified in Lean. Readers new to Fibonacci numbers and the golden ratio may want to read it first. The two books are independent, and this one cites none of its items.

## The verification ledger {#sec-preface-ledger}

The "Verification ledger" at the end of the book is generated by the build. It opens with the pinned trureturing commit and then lists its Lean-verified theorems, lemmas, propositions and corollaries: each Lean declaration links to its source at that commit, and the state column links to the frozen state file. Written proofs have a separate list with their DOI, source location, associated proof and request link. Last come all the open problems and conjectures. On every check, `./tbook check` rereads the state files at the pinned commit and confirms, item by item, the name, kind and statement digest of each declaration.
