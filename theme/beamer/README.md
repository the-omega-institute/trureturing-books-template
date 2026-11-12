# Academic Beamer decks

`beamerthemeTBookAcademic.sty` is an original Apache-2.0 theme using Beamer's public APIs. It contains no Lin Zhang/HDU theme code, institutional artwork or default logo. The reference talk informed the conventions: white 4:3 pages, a single blue structure colour (RGB 14,44,142), serif mathematics with sans text, rounded shadowed blocks, red alerts, compressed section/subsection navigation and a split short-author/short-title footer. `appendixnumberbeamer` keeps appendix frames out of the main total. The original theme labels appendix footers “Appendix”. Solid blue title/navigation/footer bands carry white text; inactive navigation is dimmed white. Rounded block titles use the structure colour over a 12% body tint, while open problems and alerts use the paper semantic red. Verification tags have white backing. The title box has a centred, even blurred shadow. Navigation symbols are hidden by default.

```bash
./tbook slides new example-monograph seminar "Golden integers" --academic --editions en
./tbook slides snapshots example-monograph
./tbook check
./tbook build slides --book example-monograph
```

A deck can select a nonempty subset of the book editions. Give one title per requested edition in the declared order. `slides.tex` belongs to the first **deck** edition; subsequent editions use `slides.<lang>.tex`. Each deck's languages align with one another, independently of other decks. Slidev's existing file names, mandatory book editions and theme remain as before.

The descriptor is `books/<book>/slides/<deck>/deck.toml`:

```toml
kind = "academic"
editions = ["en"]
aspect = "4:3"                         # or "16:9"
structure_colour = "#0e2c8e"
short_author = "W. Zhang, H. Ma"
short_title = "Seminar"
institution = "Example Mathematics Seminar"  # optional; overrides \institute
coauthors = "the seminar contributors"        # optional: Joint work with …
date = "Seminar overview"                      # optional; overrides \date
navigation_symbols = false                     # true restores Beamer controls
# institution_graphic = "assets/institution.pdf"  # relative to the deck; no default
# theme_dir = "my-theme"               # relative to the deck; absolute paths also work locally
# theme_name = "MyTheme"               # defaults to LinZhang with theme_dir
[title]
en = "Seminar title"
```

Place the speaker, coauthors and their verified affiliations in ordinary `\author`/`\institute` fields. Wenlin Zhang's affiliations are NUS, Singapore, and Chrono AI, Singapore; Haobo Ma's affiliation is Chrono AI, Singapore. A graphic must be supplied and licensed by the deck author. `theme_dir` loads its `beamertheme<theme_name>.sty` using a TeX search path; the files stay owned by the deck and are included in the cache key. Its supporting images can live beneath that directory. A custom theme controls its own navigation layout, footers, logo and colours; navigation symbols are hidden by default for both theme choices (`navigation_symbols = true` restores them). The original title page supports the descriptor’s optional `coauthors` line; custom title pages can use `\TBookCoauthors`. The generated result package, notes switch and appendix total continue to work. Custom fonts and additional packages must be available to the pinned engine.

Every edition starts with `\documentclass{beamer}` and `\input{tbook-deck}`. The builder supplies aspect/compress options and generates `tbook-deck.tex` and `tbook-lean.sty` in `build/stage/<book>/beamer/<deck>/<lang>/`; do not commit those files. Use sections, subsections and ordinary `frame` environments. Add a `% Manuscript: ...` comment for each frame and retain `\note{...}` in the source. Put optional technical frames after `\appendix`.

```tex
% Manuscript: Chapter 1, Theorem 1.3
\begin{frame}{The carry deficit}
  \begin{bookresult}{thm-deficit-three-valued}
    For all natural numbers $v_1,v_2$, $c(v_1,v_2)\in\{-1,0,1\}$.
  \end{bookresult}
  \note{Recall the normalization before stating the bound.}
\end{frame}
```

`bookresult` looks up the result in this language's book model. Its block title contains the book kind, number and title; the speaker writes the body. Every GID of a formal result must resolve to a frozen Lean theorem for a green linked `Lean ✓`. Open problems/conjectures display red `OPEN` and forbid GIDs. Definitions with resolved Lean citations display neutral `LEAN DEF`. An unresolved citation displays red, unlinked `UNVERIFIED`; checking/building refuses it. A definition without a Lean citation receives no verification badge. No source option can override the result's kind, number, GID or verification state.

`\PinnedCommit` links the short pinned SHA to its commit tree. End with `\FormalVerification`, normally in the appendix: it generates ledger frames for every distinct cited result in first-citation order, up to twelve entries per frame in a compact result/GID/status table, with every GID and its resolved pinned source link. Long GIDs wrap in smaller monospace text; the pinned commit appears at the bottom of each ledger frame. Open entries explicitly have no GID. Link line numbers come only from the lock. A missing line number is never guessed.

```tex
\begin{frame}{A positive carry}
  \centering
  \BookViz{golden-carry}{plus}
\end{frame}
\begin{frame}{The phase square}
  \centering
  \BookFigure{phase-square}
\end{frame}
\appendix
\FormalVerification
```

`BookViz` takes a registered local visualization and an existing experiment-card name. `./tbook slides snapshots <book>` uses the visualization server, still/card state, local fonts and Chromium already used by `viz-shots` to capture `viz/<id>/fig-<card>.<lang>.paper.png`. Stills use an 800 × 450 CSS viewport at 4× device scale (3200 × 1800 pixels) and fill the slide’s text width. It sets the paper tokens before the page draws and removes screen vignette/scanline effects. Commit these snapshots. Checking rejects unknown visualizations/cards and missing paper snapshots. The PDF image links to the published live page with the same card and language. Regenerate snapshots when the visualization changes.

`BookFigure` takes a figure script name. Checking compares its canonical SVG to the script output and reports stale/missing figures; regenerate with `./tbook fig build --book <book>`. Building calls `figure.materialize(svg, "paper", ground=True)` and converts that SVG to a PDF asset through the existing Typst worker and font configuration. Those fonts join the slides cache inputs. It never uses a hand-maintained deck copy. Optional graphic sizing works as `\BookFigure[width=.8\linewidth]{phase-square}`. Both media commands preserve proportions. The visualization uses the full text width; keep additional captions brief on a 4:3 slide.

## Source parsing contract

The checker lexes literal TeX rather than searching with a line regex. It handles escaped percent/braces, nested mandatory/optional arguments, overlay arguments, multiline calls, comments, inline `\verb`/`\verb*`/`\lstinline` and `verbatim`, `Verbatim`, `lstlisting`, `minted`, `comment` environments. It counts literal frames and generated ledger frames only between the editions of the same deck. Frame overlays and notes may produce additional PDF pages; those do not change frame alignment.

Write citation and media ids literally, directly in the edition source. Keep frame bodies there as well. Source imports other than `\input{tbook-deck}`, computed ids, category-code changes and `\csname` are rejected. Do not define aliases or macros that construct citation/media commands or frames: arbitrary TeX macro expansion is outside this static contract. The audience source and notes source are identical; the builder toggles `hide notes` / `show notes`. Notes PDFs interleave audience frames and the notes attached to them; audience PDFs contain no speaker notes.

## Engine and reproducibility

Academic decks require **Tectonic 0.16.9**, an XeTeX-based engine supporting Unicode and Beamer. It uses the explicit `default_bundle_v33.tar` bundle rather than the moving default, a repository-local cache (or the prewarmed `TECTONIC_CACHE_DIR` in the toolchain image), `SOURCE_DATE_EPOCH=946684800` unless explicitly overridden, stable wrapper names and `-Z deterministic-mode`. Tectonic fetches only needed TeX resources. Chinese editions use the bundle's `ctex`/Fandol font set; other scripts may require deck font declarations. This keeps a full system TeX Live installation out of CI.

`TECTONIC=/path/to/tectonic` selects the executable; the builder rejects another version. `tools/install-tectonic.sh DESTINATION` installs checksum-verified Linux release binaries into the explicit destination (amd64/arm64). The optional container prewarms the versioned bundle; its offline smoke test compiles a Beamer frame. The hosted-runner setup installs the engine locally only for browser/media jobs with academic descriptors. No runner or required check is changed.

Two uncached builds of the English example produced identical audience PDFs and identical notes PDFs with this configuration. The epoch is part of the cache key. Custom theme fonts, platform font substitution or external resources can affect outputs; avoid system font selection when cross-platform identity is required. Tectonic checks downloaded resources against the bundle index; a cold build requires access to the bundle server. The cache contains bundle resources, never generated verification facts.

Audience and notes PDFs are written to `build/slides/<book>/<deck>-<lang>.pdf` and `<deck>-<lang>-notes.pdf`. They join the existing per-book slides cache, site index, chapter links and book-release attachments. The site publishes a simple PDF landing page for each academic edition, plus both downloads. The existing Slidev skip-PDF switches apply to Slidev only; academic decks always build both PDFs.
