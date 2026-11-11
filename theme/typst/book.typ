// theme/typst/book.typ — trureturing book layout for the Pandoc → Typst PDF.
//
// Used through theme/typst/pandoc-template.typst:  #show: tr-book
//
// Inputs (tools/tbook/pandoc.py):
//   /meta.json                       book metadata, strings and counts (book_meta)
//   sys.inputs "tr-variant"          "screen" (dark void, neon accents) | "print" (white paper)
//   /_theme/typst/code-<variant>.tmTheme   code highlighting derived from tokens.json
// Functions called from raw Typst emitted by tools/filters/tr-book.lua and tr-env.lua:
//   tr-chapter, tr-part, tr-env, tr-proof, tr-proof-label, tr-qed, tr-media, tr-code-break
// and `horizontalrule`, which Pandoc's Typst writer emits for `---`.
//
// Colours come only from theme/generated/tokens.typ (tr-screen / tr-paper). Semantics:
// green (ok) = Lean-verified only (LEAN ✓ badge, frame of formal results, ledger kicker),
// red (warn) = open problems, dim = informal remarks and proofs, cyan = labels, links and
// structure, magenta = decorative accents. Amber ("now") and violet ("argued") have no
// role in a static book and are not used.

#import "../generated/tokens.typ": tr-screen, tr-paper
#import "cover.typ": tr-cover

#let variant = sys.inputs.at("tr-variant", default: "screen")
#let meta = json(sys.inputs.at("tr-meta", default: "/meta.json"))
#let is-print = variant == "print"
#let pal = if is-print { tr-paper } else { tr-screen }
#let S = meta.strings
#let cjk = meta.at("cjk", default: false)

// ------------------------------------------------------------------ fonts
// Font stacks degrade gracefully: missing families are skipped (CI installs Noto CJK,
// tools/fetch-fonts.sh adds Chakra Petch / JetBrains Mono / Noto Serif SC).
#let f-cjk-serif = ("Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", "WenQuanYi Zen Hei")
#let f-cjk-sans = ("Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "PingFang SC", "WenQuanYi Zen Hei")
#let f-mono = ("JetBrains Mono", "DejaVu Sans Mono", ..f-cjk-sans)
// Decorative symbols (∎ ▪ ✓) from a known font, never from an emoji or bitmap fallback.
#let f-symbol = ("DejaVu Sans", "Noto Sans Symbols 2", "Noto Sans Math", "Libertinus Serif")
#let f-latin-serif = ("Noto Serif", "Libertinus Serif", "DejaVu Serif")
#let f-latin-display = ("Chakra Petch", "Inter", "Noto Sans", "DejaVu Sans")
#let latin-in-cjk(names) = names.map(n => (name: n, covers: "latin-in-cjk"))
#let f-body = if cjk {
  (..latin-in-cjk(("Noto Serif", "Libertinus Serif")), ..f-cjk-serif, "Libertinus Serif")
} else { (..f-latin-serif, ..f-cjk-serif) }
#let f-display = if cjk {
  (..latin-in-cjk(("Chakra Petch", "Inter")), ..f-cjk-sans, "DejaVu Sans")
} else { (..f-latin-display, ..f-cjk-sans) }
#let f-sans = if cjk {
  (..latin-in-cjk(("Inter", "Noto Sans")), ..f-cjk-sans, "DejaVu Sans")
} else { ("Inter", "Noto Sans", "DejaVu Sans", ..f-cjk-sans) }

#let base-size = if cjk { 10.5pt } else { 10.8pt }

// ------------------------------------------------------------------ palette roles
#let page-fill = if is-print { none } else { pal.void }
#let page-bg = if is-print { pal.void } else { pal.void }
#let ink = pal.ink
#let link-colour = pal.cyan
#let heading-colour = if is-print { pal.ink } else { pal.ink }
#let accent-colour = pal.cyan
#let panel-fill = if is-print { pal.void-deep } else { pal.panel-solid }
// Frame accent per status (same mapping as theme/mdbook/tr-book.css): green only for
// Lean-verified results; labels stay cyan so green marks the verification itself.
#let status-colour(status) = (
  lean: pal.ok, definition: pal.cyan, open: pal.warn, informal: pal.dim,
  proof: pal.dim, media: pal.cyan,
).at(status, default: pal.cyan)
#let label-colour(status) = (
  lean: pal.cyan, definition: pal.cyan, open: pal.warn, informal: pal.dim, proof: pal.dim,
).at(status, default: pal.cyan)

#let margins = if is-print {
  (inside: 26mm, outside: 21mm, top: 25mm, bottom: 27mm)
} else {
  (x: 25mm, top: 26mm, bottom: 25mm)
}

// ------------------------------------------------------------------ small pieces

#let mono-text(size: 7.5pt, fill: pal.dim, tracking: 0.08em, body) = text(font: f-mono, size: size, fill: fill, tracking: tracking, body)

#let kicker-colour(section) = (
  numbered: pal.cyan, suffix: pal.cyan, prefix: pal.dim, back: pal.ok, part: pal.magenta,
).at(section, default: pal.cyan)

// A cut-corner frame: notch the top-right corner of a filled/stroked block.
#let cut-corner(size: 8pt, dx: 0pt, dy: 0pt, stroke: none) = {
  place(top + right, dx: dx, dy: dy, polygon(fill: page-bg, (0pt, 0pt), (size, 0pt), (size, size)))
  if stroke != none {
    place(top + right, dx: dx, dy: dy, line(start: (0pt, 0pt), end: (size, size), stroke: stroke))
  }
}

#let horizontalrule = align(center, block(above: 1.4em, below: 1.4em, {
  box(width: 18pt, height: 0.6pt, fill: pal.line-hot)
  h(5pt)
  box(width: 4pt, height: 4pt, fill: pal.magenta)
  h(5pt)
  box(width: 18pt, height: 0.6pt, fill: pal.line-hot)
}))

// Long inline code (Lean names): allow line breaks after dots and slashes.
#let tr-code-break(s) = raw(s.replace(".", ".\u{200B}").replace("/", "/\u{200B}"))

#let breakable-name(s) = s.replace(".", ".\u{200B}").replace("/", "/\u{200B}")

// Keep indivisible formulas inside their actual container (also inside lists/frames).
// scale must reflow: reserving the original height makes neighbouring rows drift.
#let fit-width(body, width) = {
  let natural = measure(body)
  if natural.width > width {
    let ratio = width / natural.width * 100%
    scale(x: ratio, y: ratio, reflow: true, body)
  } else { body }
}

// ------------------------------------------------------------------ environments

#let lean-footer(lean, colour) = {
  block(above: 7pt, below: 0pt, width: 100%, {
    line(length: 100%, stroke: (paint: pal.panel-edge, thickness: 0.4pt, dash: "densely-dotted"))
    v(1pt)
    set par(first-line-indent: 0pt, justify: false, leading: 0.5em)
    mono-text(size: 6.8pt, fill: pal.dim)[#upper(S.lean_label) ›]
    for e in lean {
      h(5pt)
      let name = mono-text(size: 6.8pt, fill: if e.url != "" { link-colour } else { pal.dim }, tracking: 0em, breakable-name(e.name))
      if e.url != "" { link(e.url, name) } else { name }
    }
  })
}

#let tr-badge(badge, colour, url: "") = {
  let b = box(stroke: 0.6pt + colour, inset: (x: 4pt, y: 2.4pt), baseline: 0pt,
    text(font: f-mono, size: 6.8pt, weight: "bold", fill: colour, tracking: 0.08em, badge))
  if url != "" { link(url, b) } else { b }
}

// badge-url: where the badge links ("" for none; tools/filters/tr-env.lua passes it, so an
// UNVERIFIED badge never links even when the footer links a declaration the lock resolves).
#let tr-env(kind: "", status: "", label: "", number: "", ref: "", title: none, badge: "", badge-url: "", lean: (), id: "", body) = {
  let c = status-colour(status)
  let light = status == "informal"
  let head = {
    text(font: f-display, weight: "bold", fill: label-colour(status), size: 0.95em, tracking: 0.02em, ref)
    if title != none {
      text(font: f-display, weight: "semibold", fill: heading-colour, size: 0.95em)[#S.title_open#title#S.title_close]
    }
  }
  let badge-box = if badge != "" {
    tr-badge(badge, c, url: badge-url)
  } else { none }
  let fill = if light { none } else { panel-fill }
  let edge = if light { none } else { 0.5pt + pal.panel-edge }
  block(width: 100%, breakable: true, above: 1.35em, below: 1.35em, fill: fill,
    stroke: (left: 2pt + c, top: edge, right: edge, bottom: edge),
    inset: (left: 11pt, right: 11pt, top: 8pt, bottom: 9pt), {
      if not light { cut-corner(size: 8pt, dx: 11.25pt, dy: -8.25pt, stroke: 0.5pt + pal.panel-edge) }
      set par(first-line-indent: 0pt)
      block(below: 0.75em, sticky: true, grid(columns: (1fr, auto), column-gutter: 10pt,
        align: (left + bottom, right + bottom), head, badge-box))
      body
      if lean.len() > 0 { lean-footer(lean, c) }
    })
}

#let tr-proof-label(label) = text(font: f-display, weight: "semibold", fill: pal.dim)[#label#if cjk { h(0.6em) } else { [.#h(0.35em)] }]

#let tr-qed() = { h(1fr); text(font: f-symbol, fill: pal.dim, size: 0.9em)[∎] }

#let tr-proof(label: "", id: "", body) = block(width: 100%, breakable: true, above: 1em, below: 1.3em,
  inset: (left: 10pt), stroke: (left: (paint: pal.faint, thickness: 0.6pt, dash: "dashed")), {
    set par(first-line-indent: 0pt)
    body
  })

#let tr-media(kind: "media", body) = block(width: 100%, breakable: false, above: 1.4em, below: 1.4em,
  fill: panel-fill, stroke: 0.5pt + pal.panel-edge, inset: 10pt, {
    cut-corner(size: 10pt, dx: 10.25pt, dy: -10.25pt, stroke: 0.5pt + pal.panel-edge)
    set par(first-line-indent: 0pt)
    mono-text(size: 6.8pt, fill: pal.cyan, tracking: 0.16em, upper(kind))
    v(4pt)
    body
  })

// ------------------------------------------------------------------ chapters

#let chapter-start = <tr-chapter-start>
#let chapter-end = <tr-chapter-end>

// Start a new page (a recto in print). The end marker lands on the last page of what
// precedes, so pages between an end and the next start are the blank versos inserted
// by `pagebreak(to: "odd")`; the running header and footer leave them empty.
#let new-recto() = {
  [#metadata("end")#chapter-end]
  pagebreak(weak: true, to: if is-print { "odd" } else { none })
}

#let tr-chapter(id: "", kicker: "", section: "", outlined: true, title: []) = {
  new-recto()
  [#metadata(section)#chapter-start]
  v(30mm)
  let kc = kicker-colour(section)
  block(below: 12pt, grid(columns: (auto, 1fr), column-gutter: 10pt, align: horizon,
    if kicker != "" { text(font: f-mono, size: 12pt, weight: "bold", fill: kc, tracking: 0.12em, kicker) },
    {
      line(length: 100%, stroke: 0.6pt + pal.line-hot)
    },
  ))
  let hd = heading(level: 1, outlined: outlined, bookmarked: outlined, title)
  if id != "" [#hd#label(id)] else { hd }
  block(above: 10pt, below: 26pt, {
    box(width: 34pt, height: 2pt, fill: pal.magenta)
    h(4pt)
    box(width: 7pt, height: 2pt, fill: pal.cyan)
  })
}

#let tr-part(id: "", kicker: "", section: "", outlined: true, title: []) = {
  new-recto()
  [#metadata("part")#chapter-start]
  v(1fr)
  if kicker != "" { mono-text(size: 9pt, fill: pal.magenta, tracking: 0.2em, kicker) }
  v(6pt)
  line(length: 100%, stroke: 0.6pt + pal.line-hot)
  v(10pt)
  let hd = heading(level: 1, outlined: outlined, bookmarked: outlined, title)
  if id != "" [#hd#label(id)] else { hd }
  v(2fr)
  pagebreak(weak: true)
}

// ------------------------------------------------------------------ page furniture

#let on-opener-page() = {
  let pg = here().page()
  query(chapter-start).any(m => m.location().page() == pg)
}

#let on-blank-page() = {
  let pg = here().page()
  let last-end = none
  let blank = false
  for m in query(selector(chapter-end).or(chapter-start)) {
    if m.value == "end" { if last-end == none { last-end = m.location().page() } } else {
      if last-end != none and last-end < pg and pg < m.location().page() { blank = true }
      last-end = none
    }
  }
  blank
}

#let running-header = context {
  if on-opener-page() or on-blank-page() { return }
  let before = query(heading.where(level: 1).before(here()))
  let chapter = if before.len() > 0 { before.last().body } else { none }
  let book-title = text(font: f-display, size: 7.5pt, fill: pal.dim, tracking: 0.04em, meta.title)
  let chapter-title = if chapter != none { text(font: f-display, size: 7.5pt, fill: pal.dim, chapter) }
  let code = mono-text(size: 6.8pt, fill: pal.faint, meta.code)
  let verso = is-print and calc.even(here().page())
  set par(first-line-indent: 0pt, justify: false)
  // print: verso = book title (outer left), recto = chapter title (outer right)
  if verso {
    grid(columns: (auto, 1fr), column-gutter: 8pt, align: (left, right), book-title, code)
  } else if is-print {
    grid(columns: (auto, 1fr), column-gutter: 8pt, align: (left, right), code, chapter-title)
  } else {
    grid(columns: (1fr, 2fr), column-gutter: 8pt, align: (left, right), book-title, chapter-title)
  }
  v(-4pt)
  stack(dir: ltr,
    if verso or not is-print { box(width: 22pt, height: 0.8pt, fill: accent-colour) },
    box(width: 1fr, height: 0.4pt, fill: pal.panel-edge),
    if is-print and not verso { box(width: 22pt, height: 0.8pt, fill: accent-colour) },
  )
}

#let running-footer = context {
  if on-blank-page() { return }
  let n = counter(page).display(here().page-numbering())
  let num = text(font: f-mono, size: 8pt, fill: pal.cyan, weight: "bold", tracking: 0.08em, n)
  let tag = mono-text(size: 6.5pt, fill: pal.faint, [#meta.code #h(4pt) v#meta.version])
  set par(first-line-indent: 0pt)
  if is-print {
    if calc.odd(here().page()) { grid(columns: (1fr, auto), align: (left, right), tag, num) }
    else { grid(columns: (auto, 1fr), align: (left, right), num, tag) }
  } else {
    grid(columns: (1fr, auto), align: (left, right), tag, [#text(fill: pal.faint, size: 7pt)[\[] #num #text(fill: pal.faint, size: 7pt)[\]]])
  }
}

#let opener-background = context {
  if is-print or on-blank-page() or not on-opener-page() { return }
  // scanline band and a faint aurora on chapter opener pages (screen only)
  place(top, rect(width: 100%, height: 92mm, fill: gradient.linear(
    (pal.cyan.transparentize(91%), 0%), (pal.cyan.transparentize(100%), 100%), angle: 90deg)))
  place(top, rect(width: 100%, height: 92mm, fill: tiling(size: (6pt, 2.4pt),
    place(rect(width: 6pt, height: 0.5pt, fill: white.transparentize(95%))))))
  place(top + right, dx: -14mm, dy: 14mm, polygon(fill: none, stroke: 0.6pt + pal.magenta,
    (0pt, 0pt), (16pt, 0pt), (16pt, 16pt)))
}

// ------------------------------------------------------------------ front matter

#let kv-row(k, v) = (mono-text(size: 7.5pt, fill: pal.dim, upper(k)), text(size: 9pt, fill: ink, v))

#let title-page() = page(header: none, footer: none, background: none, {
  set par(first-line-indent: 0pt, justify: false)
  v(16%)
  mono-text(size: 9pt, fill: pal.cyan, tracking: 0.22em, meta.code)
  v(4pt)
  line(length: 34%, stroke: 0.6pt + pal.line-hot)
  v(18pt)
  block(width: 92%, {
    set par(leading: if cjk { 0.5em } else { 0.4em })
    text(font: f-display, size: if cjk { 30pt } else { 31pt }, weight: "bold", fill: ink, hyphenate: false, meta.title)
  })
  if meta.subtitle != "" {
    v(14pt)
    block(width: 86%, text(font: f-sans, size: 12.5pt, fill: pal.dim, meta.subtitle))
  }
  v(22pt)
  box(width: 40pt, height: 2.2pt, fill: pal.magenta)
  h(4pt)
  box(width: 8pt, height: 2.2pt, fill: pal.cyan)
  v(1fr)
  text(font: f-display, size: 13pt, weight: "semibold", fill: ink, meta.authors.join(if cjk { "、" } else { ", " }))
  v(10pt)
  grid(columns: (auto, auto, auto), column-gutter: 10pt, align: horizon,
    mono-text(size: 8pt, fill: pal.dim, meta.publisher),
    box(stroke: 0.6pt + pal.magenta, inset: (x: 4pt, y: 2.5pt), mono-text(size: 7pt, fill: pal.magenta, [#S.lang_short · #S.lang_name])),
    mono-text(size: 8pt, fill: pal.faint, [v#meta.version]),
  )
  v(8%)
})

#let colophon-page() = page(header: none, footer: none, background: none, {
  set par(first-line-indent: 0pt, justify: false)
  v(1fr)
  text(font: f-display, size: 13pt, weight: "bold", fill: ink, meta.title)
  if meta.subtitle != "" { linebreak(); text(size: 9pt, fill: pal.dim, meta.subtitle) }
  v(12pt)
  let tru = meta.trureturing
  let rows = (
    kv-row(S.version, [#meta.version #h(6pt) #text(fill: pal.dim)[#if is-print { S.variant_print } else { S.variant_screen }]]),
    kv-row(S.date, meta.date.iso),
  )
  if meta.authors.len() > 0 { rows.push(kv-row(S.authors, meta.authors.join(if cjk { "、" } else { ", " }))) }
  if meta.license != "" { rows.push(kv-row(S.license, meta.license)) }
  if meta.isbn != "" { rows.push(kv-row(S.isbn, meta.isbn)) }
  if meta.publisher != "" { rows.push(kv-row(S.publisher, meta.publisher)) }
  if tru.commit != "" {
    rows.push(kv-row(S.pinned_at, [#link(tru.url, text(font: f-mono, size: 8.5pt, fill: link-colour, tru.short)) #h(4pt) #text(font: f-mono, size: 8pt, fill: pal.dim, tru.repo)]))
  }
  if meta.online_url != "" { rows.push(kv-row(S.online, link(meta.online_url, text(font: f-mono, size: 8pt, fill: link-colour, breakable-name(meta.online_url))))) }
  if meta.repo_url != "" { rows.push(kv-row(S.source, link(meta.repo_url, text(font: f-mono, size: 8pt, fill: link-colour, meta.repo_url)))) }
  rows.push(kv-row(S.typeset, S.typeset_value))
  grid(columns: (30%, 1fr), column-gutter: 14pt, row-gutter: 7pt, align: (left + top, left + top), ..rows.flatten())
  v(16pt)
  block(width: 100%, inset: (left: 10pt, y: 8pt), stroke: (left: 2pt + pal.ok), {
    set par(leading: 0.6em)
    text(font: f-mono, size: 7.5pt, weight: "bold", fill: pal.ok, tracking: 0.1em)[#S.badge_lean #h(4pt) #meta.formal_count]
    linebreak()
    text(size: 8.8pt, fill: ink, S.verified_statement)
    if S.open_statement != "" { linebreak(); text(size: 8.8pt, fill: pal.dim, S.open_statement) }
  })
  v(10%)
})

#let contents-page() = {
  set par(first-line-indent: 0pt, justify: false)
  v(18mm)
  block(below: 8pt, grid(columns: (auto, 1fr), column-gutter: 10pt, align: horizon,
    text(font: f-mono, size: 12pt, weight: "bold", fill: pal.cyan, tracking: 0.12em, "//"),
    line(length: 100%, stroke: 0.6pt + pal.line-hot)))
  text(font: f-display, size: 22pt, weight: "bold", fill: ink, S.contents)
  v(18pt)
  outline(title: none, depth: 2, indent: 1.4em)
}

// ------------------------------------------------------------------ the book

#let tr-book(doc) = {
  let d = meta.date
  set document(title: meta.title, author: meta.authors, keywords: meta.keywords,
    date: datetime(year: d.year, month: d.month, day: d.day), description: meta.description)
  set page(paper: meta.paper, margin: margins, fill: page-fill, numbering: "i",
    header: none, footer: running-footer, background: none, header-ascent: 40%, footer-descent: 40%)
  set text(font: f-body, size: base-size, fill: ink, lang: meta.lang,
    region: if meta.region != "" { lower(meta.region) } else { none }, hyphenate: not cjk)
  set par(justify: true,
    leading: if cjk { 0.95em } else { 0.72em },
    spacing: if cjk { 0.95em } else { 0.72em },
    first-line-indent: if cjk { (amount: 2em, all: true) } else { (amount: 1.3em, all: false) })
  set raw(theme: "/_theme/typst/code-" + variant + ".tmTheme")
  show raw: set text(font: f-mono, size: 0.9em)
  show raw.where(block: false): set text(fill: if is-print { pal.sigma } else { pal.sigma })
  show raw.where(block: true): it => block(width: 100%, fill: panel-fill, stroke: 0.5pt + pal.panel-edge,
    inset: (x: 10pt, y: 8pt), above: 1.1em, below: 1.1em, breakable: true, {
      cut-corner(size: 7pt, dx: 10.25pt, dy: -8.25pt, stroke: 0.5pt + pal.panel-edge)
      if it.lang != none and it.lang != "" {
        place(top + right, dx: 2pt, dy: -2pt, mono-text(size: 6pt, fill: pal.faint, tracking: 0.12em, upper(it.lang)))
      }
      set par(justify: false, first-line-indent: 0pt, leading: 0.55em)
      set text(size: 8.4pt)
      it
    })
  show math.equation: set text(font: ("New Computer Modern Math",), fallback: true)
  // TeX keeps the dot of i and j under an accent (\hat{a_i}); Typst would remove it, in subscripts too.
  set math.accent(dotless: false)
  // TeX (and KaTeX) set 1em between the columns of a matrix; Typst's default is half of that.
  set math.mat(column-gap: 1em)
  show math.equation.where(block: true): set block(above: 0.9em, below: 0.9em)
  show math.equation.where(block: true): it => layout(size => fit-width(it, size.width))
  show link: set text(fill: link-colour)
  show footnote: set text(fill: pal.magenta)
  set footnote.entry(separator: line(length: 22%, stroke: 0.5pt + pal.line-hot), gap: 0.45em, indent: 0em)
  show footnote.entry: set text(size: 8.3pt, fill: pal.dim)
  show footnote.entry: set par(first-line-indent: 0pt)
  set list(marker: (box(width: 0.34em, height: 0.34em, fill: pal.cyan, baseline: -0.18em),
    box(width: 0.5em, height: 0.08em, fill: pal.dim, baseline: -0.3em)), indent: 0.4em, body-indent: 0.6em)
  set enum(numbering: n => text(font: f-mono, size: 0.85em, fill: pal.cyan, weight: "bold")[#n.], indent: 0.2em)
  show list: set par(first-line-indent: 0pt)
  show enum: set par(first-line-indent: 0pt)
  show terms.item: it => block(breakable: false, {
    text(weight: "bold", it.term)
    block(inset: (left: 1.5em, top: -0.4em), it.description)
  })
  show quote.where(block: true): it => block(width: 100%, inset: (left: 12pt, y: 3pt), above: 1.1em, below: 1.1em,
    stroke: (left: 2pt + pal.line-hot), { set text(fill: pal.sigma); set par(first-line-indent: 0pt); it.body })

  // tables (the verification ledger and pipe tables)
  set table(stroke: none, inset: (x: 6pt, y: 5pt),
    fill: (x, y) => if y == 0 { panel-fill } else if calc.even(y) { if is-print { pal.void-deep } else { pal.sheet } } else { none })
  set table.hline(stroke: 0.7pt + pal.line-hot)
  show table: set text(size: 0.86em)
  // Pandoc centres tables (align(center)[#table…]) and leaves column alignment on auto,
  // which would inherit the centring: default cells to the start edge instead.
  show table: set align(start)
  show table: set par(justify: false, first-line-indent: 0pt, leading: 0.55em)
  show table: it => {
    // Raw identifiers can contain a segment wider than an entire narrow column.
    show raw.where(block: false): code => text(code.text.clusters().join("\u{200B}"))
    show table.cell: cell => layout(size => {
      show math.equation.where(block: false): equation => fit-width(equation, size.width)
      cell
    })
    it
  }
  show table.cell.where(y: 0): set text(font: f-display, weight: "semibold", fill: pal.cyan, size: 0.95em)
  show figure.where(kind: table): set figure.caption(position: top)
  show figure.where(kind: table): set block(breakable: true)

  // figures
  show figure.where(kind: image): it => block(width: 100%, above: 1.4em, below: 1.4em, breakable: false, {
    set par(first-line-indent: 0pt)
    align(center, block(stroke: 0.5pt + pal.panel-edge, inset: 6pt, fill: panel-fill, it.body))
    if it.caption != none { v(5pt); align(center, it.caption) }
  })
  show figure.caption: it => {
    set par(first-line-indent: 0pt, justify: false)
    text(size: 8.5pt, fill: pal.dim, {
      text(font: f-mono, weight: "bold", fill: pal.cyan, tracking: 0.06em)[#it.supplement #context it.counter.display(it.numbering)]
      h(0.6em)
      it.body
    })
  }

  // headings
  set heading(numbering: none)
  show heading: set par(first-line-indent: 0pt, justify: false)
  show heading: set text(hyphenate: false)
  show heading.where(level: 1): it => block(below: 0pt, {
    set par(leading: if cjk { 0.45em } else { 0.35em })
    text(font: f-display, size: if cjk { 23pt } else { 24pt }, weight: "bold", fill: ink, it.body)
  })
  show heading.where(level: 2): it => block(above: 1.9em, below: 1em, sticky: true, {
    box(width: 3pt, height: 0.85em, fill: pal.magenta, baseline: 0.05em)
    h(7pt)
    text(font: f-display, size: 14.5pt, weight: "bold", fill: if is-print { ink } else { pal.cyan }, it.body)
  })
  show heading.where(level: 3): it => block(above: 1.6em, below: 0.85em, sticky: true,
    text(font: f-display, size: 12pt, weight: "bold", fill: ink, it.body))
  show heading.where(level: 4): it => block(above: 1.4em, below: 0.7em, sticky: true,
    text(font: f-display, size: 10.8pt, weight: "semibold", fill: pal.dim, it.body))
  show heading.where(level: 5): it => block(above: 1.2em, below: 0.6em, sticky: true,
    text(font: f-display, size: 10pt, weight: "semibold", fill: pal.dim, it.body))

  // outline (table of contents)
  set outline.entry(fill: box(width: 1fr, repeat(text(fill: pal.faint, size: 0.7em)[·], gap: 0.35em)))
  show outline.entry: set par(first-line-indent: 0pt, justify: false)
  show outline.entry.where(level: 1): it => block(above: 1.05em, below: 0.4em,
    text(font: f-display, weight: "semibold", size: 10.5pt, fill: ink, it))
  show outline.entry.where(level: 2): it => text(size: 9.5pt, fill: pal.dim, it)

  // ---------------------------------------------------------------- front matter
  page(margin: 0pt, header: none, footer: none, fill: if is-print { none } else { pal.void-deep }, background: none,
    tr-cover(meta, variant: variant))
  if is-print { page(header: none, footer: none, [])}
  title-page()
  colophon-page()
  set page(footer: running-footer)
  contents-page()
  [#metadata("end")#chapter-end]

  // ---------------------------------------------------------------- main matter
  set page(numbering: "1", header: running-header, background: opener-background)
  pagebreak(weak: true, to: if is-print { "odd" } else { none })
  counter(page).update(1)
  doc
}
